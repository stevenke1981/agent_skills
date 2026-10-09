"""Behavior checks for user-controlled imports and reversible client entries."""
import io
import json
import hashlib
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from manager_core import LibraryManager, parse_github_url
from manager_server import ManagerServer


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="nas-manager-test-")
        self.root = Path(self.temporary.name)
        library = self.root / "nas"
        release = library / "releases/test"
        release.mkdir(parents=True)
        (release / "catalog.json").write_text("[]")
        manifest = json.dumps({"files": [{"path": "catalog.json", "sha256": hashlib.sha256(b"[]").hexdigest()}]}).encode()
        (release / "release-manifest.json").write_bytes(manifest)
        (library / "CURRENT.json").write_text(json.dumps({"schema": 1, "repo_id": "1a3e8840-2f5a-489e-8a4c-27f75bdb5cc0", "snapshot": "test", "release": "releases/test", "release_manifest_sha256": hashlib.sha256(manifest).hexdigest()}))
        self.manager = LibraryManager(library, self.root / "user")

    def tearDown(self):
        if not self.root.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()) or not self.root.name.startswith("nas-manager-test-"):
            raise RuntimeError("Refusing cleanup outside the test workspace")
        self.temporary.cleanup()

    def archive(self, extra=None):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("repo/skills/test-game/SKILL.md", "---\nname: test-game\ndescription: Create a test game.\n---\n# Game\nRead [rules](references/rules.md).\n")
            archive.writestr("repo/skills/test-game/references/rules.md", "Keep the user's game scope.")
            for path, value in (extra or {}).items():
                archive.writestr(path, value)
        return output.getvalue()

    def test_import_is_pending_and_repeat_import_is_idempotent(self):
        first = self.manager.import_zip(self.archive(), {"url": "local-zip", "label": "fixture"})
        second = self.manager.import_zip(self.archive(), {"url": "local-zip", "label": "fixture"})
        self.assertEqual(first[0]["id"], second[0]["id"])
        self.assertEqual(len(self.manager.state()["imports"]), 1)
        self.assertEqual(first[0]["approval"], "pending")
        self.assertEqual(self.manager.bindings(), {"Codex": [], "OpenCode": []})

    def test_unsafe_archive_paths_and_symlinks_are_rejected(self):
        for path in ["../escape.txt", "repo/../../escape.txt", "C:/escape.txt", "repo/a:stream", "repo/CON", "repo/x./SKILL.md"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.manager.import_zip(self.archive({path: "escape"}), {"url": "fixture"})
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            entry = zipfile.ZipInfo("repo/link")
            entry.external_attr = 0o120777 << 16
            archive.writestr(entry, "outside")
        with self.assertRaises(ValueError):
            self.manager.import_zip(output.getvalue(), {"url": "fixture"})
        self.assertFalse((self.root / "escape.txt").exists())

    def test_new_import_requires_confirmation_and_removal_preserves_package(self):
        record = self.manager.import_zip(self.archive(), {"url": "fixture"})[0]
        with self.assertRaises(PermissionError):
            self.manager.install(record["id"], "Codex", False)
        installed = self.manager.install(record["id"], "Codex", True)
        self.assertEqual(len(self.manager.bindings()["Codex"]), 1)
        entry = Path(installed["entrypoint"])
        self.assertIn("objects", entry.read_text(encoding="utf-8"))
        self.manager.uninstall(record["id"], "Codex")
        self.assertFalse(entry.exists())
        self.assertEqual(self.manager.bindings()["Codex"], [])
        self.assertTrue(self.manager.entry_path(record).is_file())
        self.assertTrue(any((self.root / "user/.codex/nas-library-removed").rglob("SKILL.md")))

    def test_modified_local_entry_cannot_be_removed_or_overwritten(self):
        record = self.manager.import_zip(self.archive(), {"url": "fixture"})[0]
        installed = self.manager.install(record["id"], "OpenCode", True)
        entry = Path(installed["entrypoint"])
        entry.write_text("human edit", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            self.manager.uninstall(record["id"], "OpenCode")
        with self.assertRaises(RuntimeError):
            self.manager.install(record["id"], "OpenCode", True)
        self.assertEqual(entry.read_text(encoding="utf-8"), "human edit")

    def test_archive_is_reversible_and_state_history_is_kept(self):
        record = self.manager.import_zip(self.archive(), {"url": "fixture"})[0]
        self.manager.archive(record["id"], True)
        self.assertTrue(self.manager.record(record["id"])["archived"])
        self.manager.archive(record["id"], False)
        self.assertFalse(self.manager.record(record["id"])["archived"])
        self.assertTrue(list((self.manager.library / "manager-state/history").glob("*.json")))

    def test_credentials_are_excluded_and_candidate_is_quarantined(self):
        record = self.manager.import_zip(self.archive({"repo/skills/test-game/.env": "secret"}), {"url": "fixture"})[0]
        self.assertEqual(record["status"], "quarantined")
        self.assertFalse((self.manager.entry_path(record).parent / ".env").exists())
        with self.assertRaises(ValueError):
            self.manager.install(record["id"], "Codex", True)

    def test_github_input_rejects_arbitrary_hosts_and_supports_skill_links(self):
        value = parse_github_url("https://github.com/example/skills/blob/main/skills/game/SKILL.md")
        self.assertEqual(value["path"], "skills/game")
        self.assertEqual(value["ref"], "main")
        for url in ["http://github.com/a/b", "https://127.0.0.1/a/b", "https://github.com.evil.test/a/b", "https://user:pass@github.com/a/b", "https://github.com/a/b/tree/main/../escape"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                parse_github_url(url)

    def test_previous_snapshot_pointer_remains_removable(self):
        record = self.manager.import_zip(self.archive(), {"url": "fixture"})[0]
        self.manager.install(record["id"], "Codex", True)
        with self.manager.write_state() as state:
            state["imports"] = []
        self.assertEqual(self.manager.record(record["id"])["id"], record["id"])
        self.manager.uninstall(record["id"], "Codex")
        self.assertEqual(self.manager.bindings()["Codex"], [])

    def test_http_import_authorization_install_and_reversible_removal(self):
        server = ManagerServer(("127.0.0.1", 0), self.manager)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = "http://127.0.0.1:" + str(server.server_port)
        def request(path, body=None, headers=None):
            req = Request(origin + path, data=body, headers=headers or {})
            with urlopen(req, timeout=5) as response:
                return json.loads(response.read())
        try:
            status = request("/api/status")
            headers = {"Origin": origin, "X-Local-Token": status["token"], "Content-Type": "application/json"}
            data = json.dumps({"url": "https://github.com/example/skills"}).encode()
            for foreign in [{}, dict(headers, Origin="https://external.example"), dict(headers, Host="external.example"), {"Origin": origin, "Content-Type": "application/json"}]:
                with self.subTest(headers=foreign), self.assertRaises(HTTPError) as error:
                    request("/api/bookmark", data, foreign)
                self.assertEqual(error.exception.code, 403)
                error.exception.close()
            self.assertEqual(self.manager.state()["revision"], 0)
            with self.assertRaises(HTTPError) as error:
                request("/api/status", headers={"Origin": "https://external.example"})
            self.assertEqual(error.exception.code, 403)
            error.exception.close()
            imported = request("/api/import-zip", self.archive(), dict(headers, **{"Content-Type": "application/octet-stream"}))["records"][0]
            action = {"action": "install", "id": imported["id"], "client": "OpenCode"}
            with self.assertRaises(HTTPError) as error:
                request("/api/action", json.dumps(action).encode(), headers)
            self.assertEqual(error.exception.code, 403)
            error.exception.close()
            action["confirmed"] = True
            enabled = request("/api/action", json.dumps(action).encode(), headers)
            self.assertTrue(Path(enabled["entrypoint"]).exists())
            self.assertEqual(len(request("/api/bindings")["OpenCode"]), 1)
            action["action"] = "uninstall"
            removed = request("/api/action", json.dumps(action).encode(), headers)
            self.assertFalse(Path(enabled["entrypoint"]).exists())
            self.assertTrue((Path(removed["restorable_backup"]) / "SKILL.md").exists())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_github_file_aliases_are_materialized_without_creating_links(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("repo/SKILL.md", "---\nname: alias-test\ndescription: Test alias import.\n---\n# Skill\n")
            archive.writestr("repo/AGENTS.md", "rules")
            entry = zipfile.ZipInfo("repo/CLAUDE.md")
            entry.external_attr = 0o120777 << 16
            archive.writestr(entry, "AGENTS.md")
        record = self.manager.import_zip(output.getvalue(), {"url": "github-fixture"}, materialize_links=True)[0]
        copied = self.manager.entry_path(record).parent / "CLAUDE.md"
        self.assertEqual(copied.read_text(), "rules")
        self.assertFalse(copied.is_symlink())
        unsafe = io.BytesIO()
        with zipfile.ZipFile(unsafe, "w") as archive:
            entry = zipfile.ZipInfo("repo/CLAUDE.md")
            entry.external_attr = 0o120777 << 16
            archive.writestr(entry, "../../outside")
        with self.assertRaises(ValueError):
            self.manager.import_zip(unsafe.getvalue(), {"url": "github-fixture"}, materialize_links=True)

    def test_client_search_uses_only_approved_nonarchived_imports(self):
        record = self.manager.import_zip(self.archive(), {"url": "fixture"})[0]
        def search():
            command = ["powershell.exe", "-NoProfile", "-File", str(Path(__file__).resolve().parents[1] / "Search-Skills.ps1"), "-LibraryRoot", str(self.manager.library), "-Name", "test-game"]
            result = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace", timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertEqual(search(), [])
        self.manager.install(record["id"], "Codex", True)
        self.assertEqual(search()[0]["Id"], record["id"])
        self.assertTrue(Path(search()[0]["EntryPoint"]).is_file())
        self.manager.uninstall(record["id"], "Codex")
        self.manager.archive(record["id"], True)
        self.assertEqual(search(), [])

    def test_shared_state_writers_keep_every_bookmark_and_revision(self):
        other = LibraryManager(self.manager.library, self.root / "other-user")
        errors = []
        def add(index):
            try:
                (other if index % 2 else self.manager).bookmark("https://github.com/example/skills" + str(index))
            except Exception as error:
                errors.append(error)
        threads = [threading.Thread(target=add, args=(index,)) for index in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(errors, [])
        self.assertFalse(any(thread.is_alive() for thread in threads))
        state = self.manager.state()
        self.assertEqual(len(state["bookmarks"]), 6)
        self.assertEqual(state["revision"], 6)


if __name__ == "__main__":
    unittest.main()
