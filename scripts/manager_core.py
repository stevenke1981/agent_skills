"""Shared NAS collection with explicit, reversible per-computer activation."""
from __future__ import annotations

from contextlib import contextmanager
import io
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import socket
import stat
import tempfile
import threading
import time
from urllib.parse import quote, unquote, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
import uuid
import zipfile

import skills_db as db

MAX_DOWNLOAD = 64 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
MAX_FILES = 6000
CLIENTS = {"Codex": ".codex/skills", "OpenCode": ".config/opencode/skills"}
LOCK_STALE_SECONDS = 600
HISTORY_KEEP = 500
RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", re.I)


def safe_archive_name(name: str) -> str:
    if "\\" in name or re.search(r'[<>:"|?*\x00-\x1f]', name) or name.startswith("/"):
        raise ValueError("ZIP contains an unsafe path")
    parts = name.rstrip("/").split("/")
    if not parts or any(part in {"", ".", ".."} or ":" in part or part.endswith((" ", ".")) or RESERVED.match(part) for part in parts):
        raise ValueError("ZIP contains an unsafe Windows path")
    return "/".join(parts)


def parse_github_url(url: str) -> dict:
    parsed = urlsplit(url.strip())
    if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.username or parsed.password or parsed.port not in {None, 443} or parsed.query:
        raise ValueError("請提供公開 GitHub 的 https://github.com/擁有者/儲存庫 連結")
    parts = unquote(parsed.path).strip("/").split("/")
    if len(parts) < 2 or not all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts[:2]) or any(part in {".", "..", ""} for part in parts):
        raise ValueError("GitHub 路徑無效")
    result = {"owner": parts[0], "repo": parts[1].removesuffix(".git"), "ref": None, "path": ""}
    if len(parts) > 2:
        if len(parts) < 4 or parts[2] not in {"tree", "blob"}:
            raise ValueError("支援儲存庫、tree 資料夾或 blob/SKILL.md 連結")
        result["ref"] = parts[3]
        path = parts[4:]
        if parts[2] == "blob":
            if not path or path[-1] != "SKILL.md":
                raise ValueError("blob 連結須指向 SKILL.md")
            path = path[:-1]
        result["path"] = "/".join(path)
    return result


class GitHubRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        parsed = urlsplit(new_url)
        if parsed.scheme != "https" or parsed.hostname not in {"github.com", "api.github.com", "codeload.github.com", "raw.githubusercontent.com"} or parsed.port not in {None, 443} or parsed.username:
            raise ValueError("GitHub redirected outside the allowed source hosts")
        return super().redirect_request(request, fp, code, message, headers, new_url)


def github_bytes(url: str, limit: int = MAX_DOWNLOAD) -> bytes:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {"api.github.com", "codeload.github.com"}:
        raise ValueError("Unsupported download endpoint")
    request = Request(url, headers={"User-Agent": "NAS-Skills-Manager/1.0", "Accept": "application/vnd.github+json"})
    with build_opener(GitHubRedirect()).open(request, timeout=40) as response:
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError("下載超過 64 MiB；請使用較小的技能包 ZIP")
        return data


class LibraryManager:
    def __init__(self, library: Path, user_root: Path | None = None):
        self.library = db.filesystem_path(library)
        self.user_root = db.filesystem_path(user_root or Path.home())
        self.state_root = self.library / "manager-state"
        self.state_root.mkdir(parents=True, exist_ok=True)
        self._snapshot = None
        self._records = []
        self._mutex = threading.RLock()
        self._default_user = user_root is None
        current = db.read_json(self.library / "CURRENT.json")
        if current.get("repo_id") != db.REPO_ID:
            raise ValueError("Unrecognized NAS database")

    def state(self) -> dict:
        path = self.state_root / "library.json"
        if not path.exists():
            return {"schema": 1, "repo_id": db.REPO_ID, "revision": 0, "imports": [], "bookmarks": [], "archived": []}
        value = db.read_json(path)
        if value.get("repo_id") != db.REPO_ID or value.get("schema") != 1:
            raise ValueError("Unrecognized collection state")
        return value

    @contextmanager
    def write_state(self):
        lock = self.state_root / ".write.lock"
        descriptor = None
        for attempt in range(30):
            try:
                descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                # A crashed writer must not block every computer forever. Writers
                # finish well inside this window, even for 64 MiB SMB imports.
                try:
                    if time.time() - lock.stat().st_mtime > LOCK_STALE_SECONDS:
                        lock.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                if attempt == 29:
                    raise RuntimeError("另一台電腦正在更新收藏；請稍後再試")
                time.sleep(0.1)
        try:
            os.write(descriptor, json.dumps({"machine": socket.gethostname(), "pid": os.getpid(), "time": db.datetime.now(db.TZ).isoformat()}).encode())
            os.close(descriptor)
            value = self.state()
            yield value
            value["revision"] += 1
            value["updated_at"] = db.datetime.now(db.TZ).isoformat()
            history = self.state_root / "history" / (str(value["revision"]).zfill(8) + "-" + uuid.uuid4().hex + ".json")
            db.write_json(history, value)
            pending = self.state_root / ("library.pending-" + uuid.uuid4().hex + ".json")
            db.write_json(pending, value)
            db.rename_with_retry(pending, self.state_root / "library.json", replace=True)
            self._prune_history(history.parent)
        finally:
            lock.unlink(missing_ok=True)

    @staticmethod
    def _prune_history(folder: Path) -> None:
        # Every revision is a full state copy; keep a bounded recent window.
        entries = sorted(folder.glob("*.json"))
        for old in entries[:-HISTORY_KEEP]:
            old.unlink(missing_ok=True)

    def records(self) -> list[dict]:
        current = db.read_json(self.library / "CURRENT.json")
        with self._mutex:
            if current["snapshot"] != self._snapshot:
                release = db.relative_path(self.library, current["release"])
                if current.get("release_manifest_sha256"):
                    if db.file_digest(release / "release-manifest.json") != current["release_manifest_sha256"]:
                        raise ValueError("NAS release manifest hash changed")
                    manifest = db.read_json(release / "release-manifest.json")
                    expected = next(entry["sha256"] for entry in manifest["files"] if entry["path"] == "catalog.json")
                    if db.file_digest(release / "catalog.json") != expected:
                        raise ValueError("NAS catalog hash changed")
                self._records = db.read_json(release / "catalog.json")
                self._snapshot = current["snapshot"]
        state = self.state()
        result = {record["id"]: dict(record, approval="approved", imported=False) for record in self._records}
        result.update({record["id"]: dict(record, imported=True) for record in state["imports"]})
        for record in result.values():
            record["archived"] = record["id"] in state["archived"]
        return list(result.values())

    def record(self, identity: str) -> dict:
        record = next((item for item in self.records() if item["id"] == identity), None)
        if record:
            return record
        for values in self.bindings().values():
            for binding in values:
                if binding["id"] == identity and binding.get("record"):
                    return binding["record"]
        raise ValueError("找不到這個技能版本")

    def entry_path(self, record: dict) -> Path:
        return db.relative_path(self.library, record["object_path"])

    def bookmark(self, url: str) -> dict:
        parsed = parse_github_url(url)
        value = {"id": db.digest(url.strip().encode())[:16], "url": url.strip(), "label": parsed["owner"] + "/" + parsed["repo"], "added_at": db.datetime.now(db.TZ).isoformat()}
        with self.write_state() as state:
            if not any(item["id"] == value["id"] for item in state["bookmarks"]):
                state["bookmarks"].append(value)
        return value

    def import_github(self, url: str) -> list[dict]:
        parsed = parse_github_url(url)
        endpoint = "https://api.github.com/repos/" + parsed["owner"] + "/" + parsed["repo"]
        repository = json.loads(github_bytes(endpoint, 1024 * 1024))
        ref = parsed["ref"] or repository["default_branch"]
        commit = json.loads(github_bytes(endpoint + "/commits/" + quote(ref, safe=""), 4 * 1024 * 1024))["sha"]
        if not re.fullmatch(r"[a-f0-9]{40}", commit):
            raise ValueError("Unexpected GitHub commit identifier")
        data = github_bytes("https://codeload.github.com/" + parsed["owner"] + "/" + parsed["repo"] + "/zip/" + commit)
        source = {"url": url, "label": parsed["owner"] + "/" + parsed["repo"], "commit": commit,
                  "license": (repository.get("license") or {}).get("spdx_id") or "未提供", "downloaded_at": db.datetime.now(db.TZ).isoformat()}
        result = self.import_zip(data, source, parsed["path"], materialize_links=True)
        self.bookmark(url)
        return result

    def import_zip(self, data: bytes, source: dict, selected_path: str = "", *, materialize_links: bool = False) -> list[dict]:
        if len(data) > MAX_DOWNLOAD:
            raise ValueError("ZIP exceeds 64 MiB")
        with tempfile.TemporaryDirectory(prefix="nas-skill-import-") as temporary:
            unpacked = Path(temporary)
            if not unpacked.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()) or not unpacked.name.startswith("nas-skill-import-"):
                raise RuntimeError("Unexpected import workspace")
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) > MAX_FILES or sum(entry.file_size for entry in entries) > MAX_EXPANDED:
                    raise ValueError("ZIP exceeds the file count or expanded size limit")
                seen = set()
                named = {}
                for entry in entries:
                    name = safe_archive_name(entry.filename)
                    if name.casefold() in seen:
                        raise ValueError("ZIP contains duplicate Windows paths")
                    seen.add(name.casefold())
                    named[name] = entry
                aliases = {}
                expanded = sum(entry.file_size for entry in entries)
                for name, entry in named.items():
                    mode = entry.external_attr >> 16
                    if stat.S_ISLNK(mode):
                        if not materialize_links or entry.file_size > 4096:
                            raise ValueError("ZIP contains a link: " + name)
                        link = archive.read(entry).decode("utf-8")
                        if link.startswith("/") or "\\" in link or ":" in link:
                            raise ValueError("GitHub alias leaves its repository")
                        target_name = safe_archive_name(posixpath.normpath(posixpath.join(posixpath.dirname(name), link)))
                        reader_entry = named.get(target_name)
                        if target_name.split("/")[0] != name.split("/")[0] or not reader_entry or reader_entry.is_dir() or stat.S_IFMT(reader_entry.external_attr >> 16) not in {0, stat.S_IFREG}:
                            raise ValueError("GitHub alias must point to an ordinary file inside its repository")
                        aliases[name] = reader_entry
                        expanded += reader_entry.file_size
                    elif stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}:
                        raise ValueError("ZIP contains a link or special file")
                if expanded > MAX_EXPANDED:
                    raise ValueError("ZIP alias expansion exceeds the size limit")
                source = dict(source)
                if aliases:
                    source["materialized_aliases"] = [{"path": name, "target": entry.filename} for name, entry in aliases.items()]
                for name, entry in named.items():
                    target = db.relative_path(db.filesystem_path(unpacked), name)
                    if entry.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(aliases.get(name, entry)) as reader, target.open("xb") as writer:
                            shutil.copyfileobj(reader, writer)
            children = list(unpacked.iterdir())
            root = children[0] if len(children) == 1 and children[0].is_dir() else unpacked
            if selected_path:
                root = db.relative_path(root, safe_archive_name(selected_path))
                if not root.is_dir():
                    raise ValueError("GitHub 連結中的技能資料夾不存在")
            files, omissions = [], []
            for path in sorted(root.rglob("*")):
                if not path.is_file():
                    continue
                relative = path.relative_to(root).as_posix()
                if any(part.lower() in db.SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
                    continue
                content = path.read_bytes()
                reason = "credential-filename" if db.SECRET_FILE.match(path.name) else next((label for label, pattern in db.SECRET_PATTERNS if pattern.search(content)), None)
                if reason:
                    omissions.append({"path": relative, "reason": reason})
                    continue
                files.append({"path": relative, "size": len(content), "sha256": db.digest(content)})
            skills = [entry for entry in files if PurePosixPath(entry["path"]).name == "SKILL.md"]
            if not skills:
                raise ValueError("ZIP 中沒有可匯入的 SKILL.md")
            package_hash = db.manifest_digest(files)
            object_root = self.library / "objects" / package_hash[:2] / package_hash
            with self.write_state() as state:
                if object_root.exists():
                    manifest = db.read_json(object_root / "manifest.json")
                    if manifest["files"] != files:
                        raise RuntimeError("Existing immutable bundle differs")
                else:
                    staging = object_root.with_name(object_root.name + ".incoming-" + uuid.uuid4().hex)
                    for entry in files:
                        destination = db.relative_path(staging / "skill", entry["path"])
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(db.relative_path(root, entry["path"]), destination)
                    db.write_json(staging / "manifest.json", {"schema": 1, "sha256": package_hash, "files": files})
                    db.rename_with_retry(staging, object_root)
                for entry in files:
                    if db.file_digest(db.relative_path(object_root / "skill", entry["path"])) != entry["sha256"]:
                        raise RuntimeError("Imported bundle hash verification failed")
                known = {item["id"] for item in state["imports"]}
                result = []
                for entry in skills:
                    path = db.relative_path(root, entry["path"])
                    metadata, body, issues = db.parse_skill(path)
                    record = db.metadata_card(metadata, body, path, issues)
                    if omissions:
                        issues.append("omitted-files-needs-review")
                    critical = {"invalid-yaml", "invalid-frontmatter", "missing-frontmatter", "missing-name", "missing-description", "unfinished-placeholder", "encoding-replacement", "omitted-files-needs-review"}
                    identity = re.sub(r"[^a-z0-9-]", "-", record["name"].lower()).strip("-")[:45] or "skill"
                    identity += "-" + db.digest((package_hash + ":" + entry["path"]).encode())[:12]
                    record.update({"id": identity, "package_sha256": package_hash,
                                   "object_path": "objects/" + package_hash[:2] + "/" + package_hash + "/skill/" + entry["path"],
                                   "sources": [{"path": source.get("url", "ZIP"), "client": "GitHub / ZIP 收藏", "scope": "import"}],
                                   "source": source, "issues": sorted(set(issues)), "omitted": omissions,
                                   "status": "quarantined" if critical.intersection(issues) else "catalogued", "approval": "pending",
                                   "imported": True, "archive_only": False, "recommended": False, "same_name_variants": [],
                                   "file_count": len(files), "bytes": sum(item["size"] for item in files), "card_path": ""})
                    if identity not in known:
                        state["imports"].append(record)
                        known.add(identity)
                    else:
                        record = next(item for item in state["imports"] if item["id"] == identity)
                    result.append(record)
                return result

    def client_root(self, client: str) -> Path:
        if client not in CLIENTS:
            raise ValueError("Unsupported client")
        if client == "Codex" and self._default_user and os.environ.get("CODEX_HOME"):
            return Path(os.environ["CODEX_HOME"]) / "skills"
        return self.user_root / CLIENTS[client]

    def pointer_name(self, record: dict) -> str:
        slug = re.sub(r"[^a-z0-9-]", "-", record["name"].lower()).strip("-") or "skill"
        slug = re.sub("-+", "-", slug)[:40].rstrip("-")
        return "nas-" + slug + "-" + db.digest(record["id"].encode())[:12]

    def bindings(self) -> dict:
        result = {client: [] for client in CLIENTS}
        for client in CLIENTS:
            root = self.client_root(client)
            if not root.exists():
                continue
            for folder in root.glob("nas-*"):
                marker = folder / ".nas-skill-managed.json"
                if marker.is_file():
                    ownership = db.read_json(marker)
                    if ownership.get("repo_id") == db.REPO_ID:
                        result[client].append({"id": ownership["id"], "entrypoint": str(folder / "SKILL.md"), "folder": folder.name, "record": ownership.get("record")})
        return result

    def check_owned(self, folder: Path, record: dict) -> dict:
        marker = folder / ".nas-skill-managed.json"
        entry = folder / "SKILL.md"
        if not marker.is_file() or not entry.is_file():
            raise RuntimeError("同名資料夾不是此管理工具建立；不覆寫原件")
        value = db.read_json(marker)
        if value.get("repo_id") != db.REPO_ID or value.get("id") != record["id"] or value.get("entry_sha256") != db.file_digest(entry):
            raise RuntimeError("入口已被其他方式修改；保留原件，請先檢視")
        if {path.name for path in folder.iterdir()} != {"SKILL.md", ".nas-skill-managed.json"}:
            raise RuntimeError("入口資料夾有額外內容；不自動移除")
        return value

    def install(self, identity: str, client: str, confirmed: bool) -> dict:
        with self._mutex:
            record = self.record(identity)
            if record["archived"] or record["status"] == "quarantined":
                raise ValueError("這個技能在回收筒或仍需修整，不能啟用")
            if record["approval"] != "approved" and not confirmed:
                raise PermissionError("新下載的技能尚未經使用者確認安裝")
            manifest_root = self.library / "objects" / record["package_sha256"][:2] / record["package_sha256"]
            manifest = db.read_json(manifest_root / "manifest.json")
            if db.manifest_digest(manifest["files"]) != record["package_sha256"]:
                raise ValueError("Package manifest hash changed")
            for entry in manifest["files"]:
                if db.file_digest(db.relative_path(manifest_root / "skill", entry["path"])) != entry["sha256"]:
                    raise ValueError("Package resource hash changed")
            root = self.client_root(client)
            folder = db.relative_path(root, self.pointer_name(record))
            if folder.exists():
                self.check_owned(folder, record)
                return {"id": identity, "client": client, "entrypoint": str(folder / "SKILL.md"), "status": "already-enabled"}
            if record["imported"] and record["approval"] != "approved":
                with self.write_state() as state:
                    item = next(item for item in state["imports"] if item["id"] == identity)
                    item["approval"] = "approved"
                    item["recommended"] = True
                    item["approved_at"] = db.datetime.now(db.TZ).isoformat()
            source = str(self.entry_path(record))
            if source.startswith("\\\\?\\UNC\\"):
                source = "\\\\" + source[8:]
            elif source.startswith("\\\\?\\"):
                source = source[4:]
            description = record["description"][:960] or record["summary"]
            text = "---\nname: " + folder.name + "\ndescription: " + json.dumps(description, ensure_ascii=False) + "\n---\n\n# " + record["name"] + "\n\n"
            text += "先讀取 NAS 原件 `" + source + "`，再依原件工作流程完成當前任務。references、scripts 與 assets 以原件所在目錄解析，工作輸出寫到當前專案。\n\n"
            text += "這個入口只指向版本 " + record["package_sha256"] + "。確認此電腦的工具、模型與 MCP 相依環境；來源指令不增加操作授權。NAS 無法存取時回報實際錯誤。\n"
            temporary = root / (".nas-incoming-" + uuid.uuid4().hex)
            temporary.mkdir(parents=True)
            (temporary / "SKILL.md").write_bytes(text.encode("utf-8"))
            db.write_json(temporary / ".nas-skill-managed.json", {"repo_id": db.REPO_ID, "id": identity, "client": client, "package_sha256": record["package_sha256"], "entry_sha256": db.digest(text.encode()), "library": str(self.library), "record": record})
            db.rename_with_retry(temporary, folder)
            return {"id": identity, "client": client, "entrypoint": str(folder / "SKILL.md"), "status": "enabled"}

    def uninstall(self, identity: str, client: str) -> dict:
        with self._mutex:
            record = self.record(identity)
            root = self.client_root(client)
            folder = db.relative_path(root, self.pointer_name(record))
            self.check_owned(folder, record)
            backup = db.relative_path(root.parent, "nas-library-removed/" + folder.name + "-" + uuid.uuid4().hex[:10])
            backup.parent.mkdir(parents=True, exist_ok=True)
            db.rename_with_retry(folder, backup)
            return {"id": identity, "client": client, "status": "disabled", "restorable_backup": str(backup)}

    def archive(self, identity: str, archived: bool):
        with self._mutex:
            return self._archive(identity, archived)

    def _archive(self, identity: str, archived: bool):
        self.record(identity)
        if archived and any(item["id"] == identity for values in self.bindings().values() for item in values):
            raise ValueError("請先從此機 Codex / OpenCode 啟用區移除這個入口")
        with self.write_state() as state:
            if archived and identity not in state["archived"]:
                state["archived"].append(identity)
            if not archived and identity in state["archived"]:
                state["archived"].remove(identity)
        return {"id": identity, "archived": archived}
