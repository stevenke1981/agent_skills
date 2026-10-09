"""Behavioral checks for packaging, conflicts, integrity, search and client setup."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location("skills_db", Path(__file__).resolve().parents[1] / "scripts/skills_db.py")
DB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DB)
BASE = Path(__file__).resolve().parents[1]


class LibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="skills-library-test-")
        self.root = Path(self.temporary.name)
        self.library = self.root / "library"

    def tearDown(self) -> None:
        resolved = self.root.resolve()
        if not resolved.is_relative_to(Path(tempfile.gettempdir()).resolve()) or not resolved.name.startswith("skills-library-test-"):
            raise RuntimeError("Refusing cleanup outside the test workspace")
        if resolved.exists():
            shutil.rmtree(DB.filesystem_path(resolved))
        self.temporary.cleanup()

    def skill(self, folder: str, script: str = "print('same')\n", todo: bool = False) -> Path:
        root = self.root / "sources" / folder
        (root / "scripts").mkdir(parents=True)
        description = "[TODO: Briefly describe what this skill does and when it applies.]" if todo else "當使用者需要繁中字幕時，輸出 SRT；不適用付費生成。"
        (root / "SKILL.md").write_text("---\nname: subtitle-test\ndescription: " + json.dumps(description, ensure_ascii=False) + "\n---\n\n# 字幕\n\n## 交付\n\n- 繁體中文字幕檔。\n\n## 例外\n\n- 資料不足時標記待確認。\n", encoding="utf-8")
        (root / "scripts/task.py").write_text(script, encoding="utf-8")
        return root / "SKILL.md"

    def build(self, paths: list[Path]) -> list[dict]:
        discovery = {"paths": [str(path) for path in paths], "machine": "test-machine", "scans": [], "previous_catalog_missing": []}
        discovery_file = self.root / "discovery.json"
        DB.write_json(discovery_file, discovery)
        with contextlib.redirect_stdout(io.StringIO()):
            DB.build(discovery_file, self.library)
        current = DB.read_json(self.library / "CURRENT.json")
        return DB.read_json(self.library / current["release"] / "catalog.json")

    def test_entire_package_hash_distinguishes_supporting_scripts(self) -> None:
        records = self.build([self.skill("one"), self.skill("copy"), self.skill("different", "print('different')\n")])
        self.assertEqual(len(records), 2)
        self.assertEqual(sorted(len(record["sources"]) for record in records), [1, 2])
        self.assertTrue(all(len(record["same_name_variants"]) == 2 for record in records))
        with contextlib.redirect_stdout(io.StringIO()):
            result = DB.verify(self.library, sources=True)
        self.assertEqual(result["changed_sources"], [])
        self.assertEqual(result["sqlite_records"], 2)

    def test_tampered_package_fails_integrity(self) -> None:
        records = self.build([self.skill("one")])
        path = DB.relative_path(self.library, records[0]["object_path"]).parent / "scripts/task.py"
        path.write_text("print('tampered')", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "Package integrity failed"):
            with contextlib.redirect_stdout(io.StringIO()):
                DB.verify(self.library)

    def test_tampered_catalog_fails_integrity(self) -> None:
        self.build([self.skill("one")])
        current = DB.read_json(self.library / "CURRENT.json")
        (self.library / current["release"] / "catalog.json").write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "Release integrity failed"):
            with contextlib.redirect_stdout(io.StringIO()):
                DB.verify(self.library)

    def test_source_changes_are_detected_without_rewriting_source(self) -> None:
        original = self.skill("one")
        self.build([original])
        original.write_text(original.read_text(encoding="utf-8") + "Changed source\n", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            with contextlib.redirect_stdout(io.StringIO()):
                DB.verify(self.library, sources=True)

    def test_placeholders_and_credentials_are_not_recommended(self) -> None:
        good = self.skill("one")
        (good.parent / ".env").write_text("TEST_SECRET=private-fixture", encoding="utf-8")
        records = self.build([good, self.skill("todo", todo=True)])
        self.assertTrue(all(record["status"] == "quarantined" for record in records))
        self.assertTrue(any(any(omission["reason"] == "credential-filename" for omission in record["omitted"]) for record in records))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(DB.search(self.library, "字幕", 10), [])

    def test_chinese_search_returns_actual_package_path(self) -> None:
        self.build([self.skill("one")])
        with contextlib.redirect_stdout(io.StringIO()):
            result = DB.search(self.library, "繁中 字幕", 10)
        self.assertEqual(len(result), 1)
        self.assertTrue(Path(result[0]["entrypoint"]).is_file())

    def test_path_traversal_is_rejected(self) -> None:
        for path in ["../outside", "safe/../../outside", "/absolute", "C:/outside", r"\\server\share", "safe/../../../x"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                DB.relative_path(self.root, path)

    def test_smb_rename_retry_publishes_complete_directory(self) -> None:
        pending = self.root / "package.incoming"
        pending.mkdir()
        (pending / "resource.txt").write_text("complete package", encoding="utf-8")
        destination = self.root / "package"
        original_rename = Path.rename
        denied = False

        def transient_rename(source: Path, target: Path) -> Path:
            nonlocal denied
            if not denied:
                denied = True
                raise PermissionError("temporary sharing denial")
            return original_rename(source, target)

        with mock.patch.object(Path, "rename", transient_rename), mock.patch.object(DB.time, "sleep"):
            DB.rename_with_retry(pending, destination)
        self.assertFalse(pending.exists())
        self.assertEqual((destination / "resource.txt").read_text(encoding="utf-8"), "complete package")

    def test_persistent_rename_denial_preserves_pending_and_current(self) -> None:
        pending = self.root / "CURRENT.pending.json"
        current = self.root / "CURRENT.json"
        pending.write_text("new snapshot", encoding="utf-8")
        current.write_text("verified snapshot", encoding="utf-8")
        with mock.patch.object(Path, "replace", side_effect=PermissionError("persistent denial")), mock.patch.object(DB.time, "sleep"):
            with self.assertRaises(PermissionError):
                DB.rename_with_retry(pending, current, replace=True)
        self.assertEqual(current.read_text(encoding="utf-8"), "verified snapshot")
        self.assertEqual(pending.read_text(encoding="utf-8"), "new snapshot")

    def test_yaml_dates_are_preserved_as_catalog_strings(self) -> None:
        original = self.skill("one")
        text = original.read_text(encoding="utf-8").replace("name: subtitle-test", "name: subtitle-test\nmetadata:\n  updated: 2026-10-09")
        original.write_text(text, encoding="utf-8")
        records = self.build([original])
        self.assertEqual(records[0]["frontmatter"]["metadata"]["updated"], "2026-10-09")

    @unittest.skipUnless(os.name == "nt", "Extended path fixture is Windows only")
    def test_long_relative_resource_paths_are_packaged(self) -> None:
        original = self.skill("one")
        nested = DB.filesystem_path(original.parent) / "references"
        for index in range(7):
            nested = nested / ("deep-reference-" + str(index) + "-" + "a" * 25)
        nested.mkdir(parents=True)
        (nested / "reference.txt").write_text("Traditional Chinese reference", encoding="utf-8")
        records = self.build([original])
        self.assertFalse(records[0]["omitted"])
        self.assertEqual(records[0]["file_count"], 3)
        with contextlib.redirect_stdout(io.StringIO()):
            DB.verify(self.library)

    def test_generated_workspaces_are_excluded_and_linked_resources_are_kept(self) -> None:
        original = self.skill("one")
        (original.parent / "work").mkdir()
        (original.parent / "work/generated.txt").write_text("working output", encoding="utf-8")
        (original.parent / "custom-guides").mkdir()
        (original.parent / "custom-guides/rules.md").write_text("Required workflow reference", encoding="utf-8")
        original.write_text(original.read_text(encoding="utf-8") + "\nRead [rules](custom-guides/rules.md).\n", encoding="utf-8")
        records = self.build([original])
        root = DB.relative_path(self.library, records[0]["object_path"]).parent
        self.assertFalse((root / "work").exists())
        self.assertTrue((root / "custom-guides/rules.md").is_file())
        self.assertTrue((original.parent / "work/generated.txt").is_file())

    @unittest.skipUnless(os.name == "nt", "PowerShell client fixture is Windows only")
    def test_client_setup_reuses_managed_entry_and_refuses_foreign_overwrite(self) -> None:
        self.build([self.skill("one")])
        user = self.root / "user"
        command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(BASE / "Setup-Client.ps1"),
                   "-Client", "Codex", "-LibraryRoot", str(self.library), "-UserRoot", str(user)]
        first = subprocess.run(command, capture_output=True)
        self.assertEqual(first.returncode, 0, first.stderr.decode(errors="replace"))
        entry = user / ".codex/skills/nas-skill-library/SKILL.md"
        self.assertIn("搜尋 NAS", entry.read_text(encoding="utf-8"))
        first_hash = DB.file_digest(entry)
        second = subprocess.run(command, capture_output=True)
        self.assertEqual(second.returncode, 0)
        self.assertEqual(first_hash, DB.file_digest(entry))
        entry.write_text("human change", encoding="utf-8")
        final = subprocess.run(command, capture_output=True)
        self.assertNotEqual(final.returncode, 0)
        self.assertEqual(entry.read_text(encoding="utf-8"), "human change")

    @unittest.skipUnless(os.name == "nt", "PowerShell search fixture is Windows only")
    def test_powershell_search_verifies_and_reads_current(self) -> None:
        self.build([self.skill("one")])
        command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(BASE / "Search-Skills.ps1"),
                   "-Query", "subtitle-test", "-LibraryRoot", str(self.library)]
        result = subprocess.run(command, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertIn(b"subtitle-test", result.stdout)

    @unittest.skipUnless(os.name == "nt", "Multi-client setup fixture is Windows only")
    def test_combined_setup_creates_only_codex_and_opencode_entries(self) -> None:
        self.build([self.skill("one")])
        user = self.root / "two-client-user"
        environment = dict(os.environ, NAS_SKILLS_SETUP_SCRIPT=str(BASE / "Setup-Client.ps1"),
                           NAS_SKILLS_TEST_LIBRARY=str(self.library), NAS_SKILLS_TEST_USER=str(user))
        command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                   "& $env:NAS_SKILLS_SETUP_SCRIPT -Client Codex,OpenCode -LibraryRoot $env:NAS_SKILLS_TEST_LIBRARY -UserRoot $env:NAS_SKILLS_TEST_USER"]
        result = subprocess.run(command, capture_output=True, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        codex = user / ".codex/skills/nas-skill-library/SKILL.md"
        opencode = user / ".config/opencode/skills/nas-skill-library/SKILL.md"
        self.assertEqual(codex.read_bytes(), opencode.read_bytes())
        self.assertEqual(len([path for path in user.rglob("*") if path.is_file()]), 4)
        self.assertFalse((user / ".config/opencode/opencode.json").exists())

    def test_publish_uses_frozen_management_source(self) -> None:
        self.build([self.skill("one")])
        current = DB.read_json(self.library / "CURRENT.json")
        expected = (self.library / current["release"] / "management-source/README.md").read_bytes()
        changing_workspace = self.root / "changing-workspace"
        changing_workspace.mkdir()
        (changing_workspace / "README.md").write_text("unpublished change", encoding="utf-8")
        destination = self.root / "nas"
        with mock.patch.object(DB, "BASE", changing_workspace), mock.patch.object(DB, "MANAGED_FILES", ["README.md"]):
            with contextlib.redirect_stdout(io.StringIO()):
                DB.publish(self.library, destination)
        self.assertEqual((destination / "README.md").read_bytes(), expected)


if __name__ == "__main__":
    unittest.main()
