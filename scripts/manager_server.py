"""Loopback-only browser UI: NAS collection and this computer's entries."""
from __future__ import annotations
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
import socket
import traceback
import zipfile
from urllib.parse import parse_qs, urlsplit
from urllib.error import HTTPError, URLError

import skills_db as db
from manager_core import LibraryManager, MAX_DOWNLOAD

WEB = Path(__file__).resolve().parents[1] / "manager-web"


def public_record(record):
    fields = ["id", "name", "summary", "description", "category", "category_label", "status", "approval", "archived", "imported", "file_count", "bytes", "issues", "dependencies", "source", "same_name_variants"]
    return {key: record.get(key) for key in fields}


class ManagerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, manager):
        self.manager = manager
        self.token = secrets.token_urlsafe(32)
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(45)

    def log_message(self, format, *args):
        # Request bodies, tokens and source content never enter logs.
        return

    def valid_host(self):
        port = self.server.server_address[1]
        return self.headers.get("Host") in {"127.0.0.1:" + str(port), "localhost:" + str(port)}

    def respond(self, value, status=200, content_type="application/json; charset=utf-8"):
        body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.respond({"error": "Cross-origin requests are not supported"}, 403)

    def do_GET(self):
        if not self.valid_host():
            return self.respond({"error": "Invalid local host"}, 403)
        origin = self.headers.get("Origin")
        allowed = {"http://" + self.headers["Host"]}
        if origin and origin not in allowed:
            return self.respond({"error": "Foreign origin"}, 403)
        try:
            url = urlsplit(self.path)
            query = parse_qs(url.query)
            manager = self.server.manager
            if url.path in {"/", "/app.js", "/style.css"}:
                names = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/style.css": ("style.css", "text/css; charset=utf-8")}
                name, mime = names[url.path]
                return self.respond((WEB / name).read_bytes(), content_type=mime)
            if url.path == "/api/status":
                current = db.read_json(manager.library / "CURRENT.json")
                return self.respond({"repo_id": db.REPO_ID, "token": self.server.token, "machine": socket.gethostname(), "user_root": str(manager.user_root), "library": str(manager.library), "snapshot": current["snapshot"], "categories": db.CATEGORIES, "test_user_root": not manager._default_user})
            if url.path == "/api/library":
                words = query.get("query", [""])[0].casefold().split()
                mode = query.get("mode", ["collection"])[0]
                category = query.get("category", [""])[0]
                result = []
                for record in manager.records():
                    if mode == "archived" and not record["archived"] or mode not in {"archived", "all"} and record["archived"]:
                        continue
                    if mode == "pending" and record["approval"] != "pending":
                        continue
                    if mode == "imports" and not record["imported"]:
                        continue
                    if mode == "collection" and (record.get("archive_only") or record["status"] == "quarantined"):
                        continue
                    if category and record["category"] != category:
                        continue
                    text = " ".join([record["name"], record["description"], record["summary"], *record.get("keywords", []), *record["dependencies"]]).casefold()
                    if all(word in text for word in words):
                        result.append(record)
                result.sort(key=lambda record: (record["approval"] != "pending", record["name"].casefold(), record["id"]))
                offset = max(0, int(query.get("offset", ["0"])[0]))
                limit = min(100, max(1, int(query.get("limit", ["30"])[0])))
                return self.respond({"total": len(result), "records": [public_record(record) for record in result[offset:offset + limit]], "bookmarks": manager.state()["bookmarks"]})
            if url.path == "/api/bindings":
                bindings = manager.bindings()
                for values in bindings.values():
                    for binding in values:
                        binding["record"] = public_record(manager.record(binding["id"]))
                return self.respond(bindings)
            if url.path == "/api/entry":
                record = manager.record(query.get("id", [""])[0])
                path = manager.entry_path(record)
                content = path.read_bytes()
                return self.respond({"record": record, "entrypoint": str(path), "content": content[:262144].decode("utf-8-sig", errors="replace"), "truncated": len(content) > 262144})
            if url.path == "/api/gaps":
                path = Path(__file__).resolve().parents[1] / "config/gaps.json"
                return self.respond(db.read_json(path) if path.exists() else {"items": []})
            self.respond({"error": "Not found"}, 404)
        except Exception as error:
            self.respond({"error": str(error)}, 400)

    def do_POST(self):
        if not self.valid_host() or self.headers.get("Origin") != "http://" + self.headers.get("Host", "") or not secrets.compare_digest(self.headers.get("X-Local-Token", ""), self.server.token):
            # Drain small rejected form/JSON bodies so Windows can read the 403
            # before the connection closes. Never process or retain this input.
            try:
                rejected_length = int(self.headers.get("Content-Length", "0"))
                if 0 < rejected_length <= 16384:
                    self.rfile.read(rejected_length)
            except (ValueError, OSError):
                pass
            return self.respond({"error": "Local operation authorization failed"}, 403)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > MAX_DOWNLOAD:
                raise ValueError("Request size exceeds the limit")
            url = urlsplit(self.path)
            manager = self.server.manager
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("Incomplete request body")
            if url.path == "/api/import-zip":
                if self.headers.get("Content-Type", "").split(";")[0] != "application/octet-stream":
                    raise ValueError("Expected ZIP bytes")
                return self.respond({"records": [public_record(record) for record in manager.import_zip(body, {"url": "local-zip", "label": "使用者匯入的 ZIP"})]})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json" or length > 16384:
                raise ValueError("Expected bounded JSON input")
            data = json.loads(body)
            if url.path == "/api/bookmark":
                return self.respond(manager.bookmark(data["url"]))
            if url.path == "/api/import-github":
                return self.respond({"records": [public_record(record) for record in manager.import_github(data["url"])]})
            if url.path == "/api/action":
                identity = data["id"]
                action = data["action"]
                if action == "install":
                    result = manager.install(identity, data["client"], data.get("confirmed") is True)
                elif action == "uninstall":
                    result = manager.uninstall(identity, data["client"])
                elif action in {"archive", "restore"}:
                    result = manager.archive(identity, action == "archive")
                else:
                    raise ValueError("Unknown action")
                return self.respond(result)
            self.respond({"error": "Not found"}, 404)
        except PermissionError as error:
            self.respond({"error": str(error)}, 403)
        except (ValueError, KeyError, zipfile.BadZipFile) as error:
            self.respond({"error": str(error)}, 400)
        except (HTTPError, URLError) as error:
            self.respond({"error": "GitHub 下載失敗；可稍後再試或匯入 ZIP。" + str(error)}, 502)
        except RuntimeError as error:
            self.respond({"error": str(error)}, 409)
        except Exception:
            traceback.print_exc()
            self.respond({"error": "Operation failed; inspect the local service log"}, 500)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", type=Path, default=Path(db.NAS))
    parser.add_argument("--user-root", type=Path)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    server = ManagerServer(("127.0.0.1", args.port), LibraryManager(args.library, args.user_root))
    print(json.dumps({"url": "http://127.0.0.1:" + str(server.server_address[1]), "machine": socket.gethostname()}), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
