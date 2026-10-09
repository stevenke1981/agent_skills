"""Build, verify and publish an immutable, searchable NAS Skill library."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import concurrent.futures
import csv
from datetime import datetime, timezone, timedelta
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import sys
import time
import uuid
from urllib.parse import quote
import yaml

REPO_ID = "1a3e8840-2f5a-489e-8a4c-27f75bdb5cc0"
NAS = r"\\DVA3221\public_ssd\agent_skills"
BASE = Path(__file__).resolve().parents[1]
TZ = timezone(timedelta(hours=8))
CATEGORIES = {
    "data-analysis": "資料與分析", "business-automation": "日常與商業自動化",
    "templates": "模板與框架", "verification": "審查與驗證",
    "incident-runbooks": "除錯與應變", "creative-media": "影音與創作",
    "development": "開發與工程", "platform-management": "平台與技能管理",
}
RULES = [
    ("incident-runbooks", r"debug|troubleshoot|incident|build.resolv|fix.finding|repair|recovery|除錯|排查|故障|應變"),
    ("verification", r"review|audit|verif|validat|test|triage|security.scan|threat.model|assess|審查|驗證|檢查|品質|測試"),
    ("platform-management", r"skill|mcp|codex|agent.workflow|agentic|harness|environment|部署|安裝|配置|技能"),
    ("data-analysis", r"analys|research|database|data.?scien|bio|genom|proteom|chem|statistic|scientific|transcrib|asr|資料|數據|研究|辨識|分析"),
    ("templates", r"templat|scaffold|document|presentation|spreadsheet|pdf|write.like|模板|文件|簡報|試算表"),
    ("creative-media", r"video|audio|music|image|figma|design|blender|3d|animat|story|novel|comic|tts|art|視覺|設計|影|音|故事|小說|漫畫|字幕|歌|寵物"),
    ("development", r"code|dev|engineer|architect|frontend|backend|rust|python|javascript|typescript|react|web|api|程式|開發|架構"),
]
TOOL_PATTERNS = {
    "FFmpeg": r"\bffmpeg\b|\bffprobe\b", "Python": r"\bpython(?:3)?\b|\.py\b",
    "Node.js": r"\bnode(?:\.js)?\b|\bnpm\b|\bnpx\b", "Git": r"\bgit\b",
    "ripgrep": r"\bripgrep\b|\brg\s", "Docker": r"\bdocker\b",
    "CUDA / NVIDIA GPU": r"\bcuda\b|\bnvidia\b", "Blender": r"\bblender\b",
    "Fish Audio": r"\bfish\s+(?:audio|s2)\b", "Qwen3ASR": r"\bqwen3asr\b",
    "soundx": r"\bsoundx\b", "agent-browser": r"\bagent-browser\b",
    "Playwright": r"\bplaywright\b", "AutoGui": r"\bautogui\b|\brsautogui\b",
    "Google Flow": r"flow\.google\.com|google flow", "Flow Music": r"flowmusic\.app",
    "OpenAI tool runtime": r"mcp__codex|codex_apps|artifact_session|use_figma|image_gen|cua_repl|chatgpt space",
    "MCP server": r"\bmcp\b|mcp__", "yt-dlp": r"\byt-dlp\b",
}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "target", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache",
             "models", "weights", "checkpoints", "artifacts", ".ag-artifacts", ".alignment-backup", ".codebase-memory", "gguf-test", "renders", "media",
             "work", ".work", "output", "outputs", "deliverables", "logs", "tmp", "temp", "model-envs", "jobs", "diagnostics", "test-results"}
RESOURCE_DIRS = {"scripts", "references", "assets", "agents", "examples", "templates", "schemas", "prompts", "docs", "src", "tests", "skills", "resources", "tools", "lib", "data", "raw", "bin", "config", "fixtures", "evals", "validation", "packaging", "installer", ".github"}
MANAGED_FILES = ["README.md", "Setup-Client.ps1", "Setup-Codex.cmd", "Setup-Codex-OpenCode.cmd", "Search-Skills.ps1", "config/overrides.json", "docs/OPERATIONS.md", "docs/PRINCIPLES.md",
                 "scripts/discover.py", "scripts/skills_db.py", "dashboard/index.template.html", "manager/nas-skill-library/SKILL.md", "tests/test_library.py", "lessons.md", ".gitignore"]
SECRET_FILE = re.compile(r"^(?:\.env(?:\..+)?|credentials(?:\..+)?|auth\.json|tokens?\.json|cookies?(?:\..+)?|id_rsa|id_ed25519)$", re.I)
SECRET_PATTERNS = [
    ("private-key", re.compile(rb"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----")),
    ("provider-token", re.compile(rb"\b(?:sk-[A-Za-z0-9_-]{32,}|gh[pousr]_[A-Za-z0-9]{30,}|AIza[0-9A-Za-z_-]{35})\b")),
    ("aws-key", re.compile(rb"\bAKIA[0-9A-Z]{16}\b")),
]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for part in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(part)
    return result.hexdigest()


def rename_with_retry(source: Path, destination: Path, *, replace: bool = False) -> None:
    """Allow brief SMB sharing denials while retaining atomic publication."""
    delays = (0, 0.2, 0.5, 1, 2)
    for attempt, delay in enumerate(delays):
        if delay:
            time.sleep(delay)
        try:
            if replace:
                source.replace(destination)
            else:
                source.rename(destination)
            return
        except PermissionError:
            if attempt == len(delays) - 1:
                raise


def filesystem_path(path: Path) -> Path:
    """Use Windows extended paths for deep original resources and UNC objects."""
    absolute = str(path.absolute())
    if os.name != "nt" or absolute.startswith("\\\\?\\"):
        return Path(absolute)
    if absolute.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute[2:])
    return Path("\\\\?\\" + absolute)


def readonly_sqlite(path: Path) -> sqlite3.Connection:
    text = str(path.absolute())
    if text.startswith("\\\\?\\UNC\\"):
        text = "\\\\" + text[8:]
    elif text.startswith("\\\\?\\"):
        text = text[4:]
    normalized = text.replace("\\", "/")
    uri = ("file://" if normalized.startswith("//") else "file:") + quote(normalized, safe="/:")
    return sqlite3.connect(uri + "?mode=ro&immutable=1", uri=True)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def relative_path(root: Path, value: str) -> Path:
    """Manifest paths may never escape their designated root, including on Windows."""
    normalized = value.replace("\\", "/")
    if not normalized or normalized.startswith("/") or ":" in normalized or ".." in normalized.split("/"):
        raise ValueError("Unsafe relative path")
    target = root.joinpath(*normalized.split("/"))
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Path escapes root through a link")
    return target


def source_scope(path: str) -> tuple[str, str]:
    text = path.replace("\\", "/").lower()
    if re.search(r"backup|retired|quarantine|archiv|備份|\.ag-artifacts|/\.codex-worktrees/|/\.codex/artifacts/|/documents/codex/\d{4}-\d{2}-\d{2}/", text):
        return "archive", "歷史或備份"
    if "/plugins/cache/" in text or "/plugin-skills/" in text:
        return "plugin", "Codex 插件快取"
    for fragment, client in [("/.codex/skills/", "Codex"), ("/.agents/skills/", "共用 Agents"),
                             ("/.claude/skills/", "Claude"), ("/opencode/skills/", "OpenCode"),
                             ("/.opencode/skills/", "OpenCode"), ("/.gemini/", "Gemini / AGY"),
                             ("/.pi/agent/skills/", "Pi"), ("/.copilot/skills/", "Copilot"),
                             ("/.bailian/skills/", "Bailian"), ("/.cursor/skills/", "Cursor")]:
        user_prefix = str(Path.home()).replace("\\", "/").lower().rstrip("/")
        if text.startswith(user_prefix + fragment):
            return "installed", client
    return "project", "本機專案或收藏"


def finalize(library: Path) -> dict:
    """Finalize unpublished local metadata without repacking verified objects."""
    library = filesystem_path(library)
    if not library.resolve().is_relative_to(filesystem_path(BASE / ".work").resolve()):
        raise RuntimeError("Finalization is restricted to the local working directory")
    current = read_json(library / "CURRENT.json")
    published = library / "publish-result.json"
    if published.exists() and read_json(published)["snapshot"] == current["snapshot"]:
        raise RuntimeError("Published snapshots are immutable; build a new snapshot")
    release = relative_path(library, current["release"])
    records = read_json(release / "catalog.json")
    summary = read_json(release / "summary.json")
    overrides = read_json(BASE / "config/overrides.json")
    for record in records:
        record["summary"] = make_summary(record["description"], record["name"])
        if record["name"] in overrides:
            record.update(overrides[record["name"]])
            record["category_label"] = CATEGORIES[record["category"]]
            record["classification_basis"] = "curated override"
        for source in record["sources"]:
            source["scope"], source["client"] = source_scope(source["path"])
        record["archive_only"] = all(source["scope"] == "archive" for source in record["sources"])
        record["recommended"] = record["status"] == "catalogued" and not record["archive_only"]
        (release / "cards" / (record["id"] + ".md")).write_text(render_card(record), encoding="utf-8")
    summary["archive_only"] = sum(record["archive_only"] for record in records)
    summary["categories"] = dict(Counter(record["category"] for record in records))
    summary["source_scopes"] = dict(Counter(source["scope"] for record in records for source in record["sources"]))
    summary["finalized_at"] = datetime.now(TZ).isoformat()
    write_json(release / "catalog.json", records)
    (release / "catalog.jsonl").write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")
    write_json(release / "summary.json", summary)
    write_inventory_csv(release / "inventory.csv", records)
    temporary_sqlite = release / "skills.finalizing.sqlite"
    temporary_sqlite.unlink(missing_ok=True)
    create_sqlite(temporary_sqlite, records)
    temporary_sqlite.replace(release / "skills.sqlite")
    for relative in MANAGED_FILES:
        target = relative_path(release / "management-source", relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(relative_path(BASE, relative), target)
    (release / "manager/SKILL.md").write_bytes((BASE / "manager/nas-skill-library/SKILL.md").read_bytes())
    render_dashboard(release, records, summary)
    release_files = [{"path": file.relative_to(release).as_posix(), "size": file.stat().st_size, "sha256": file_digest(file)} for file in sorted(release.rglob("*")) if file.is_file() and file.name != "release-manifest.json"]
    write_json(release / "release-manifest.json", {"schema": 1, "snapshot": current["snapshot"], "files": release_files, "sha256": manifest_digest(release_files)})
    current["release_manifest_sha256"] = file_digest(release / "release-manifest.json")
    write_json(library / "CURRENT.json", current)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


def parse_skill(path: Path) -> tuple[dict, str, list[str]]:
    issues = []
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if "\ufffd" in text:
        issues.append("encoding-replacement")
    match = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", text, re.S)
    metadata = {}
    body = text
    if match:
        try:
            metadata = yaml.safe_load(match.group(1)) or {}
            if not isinstance(metadata, dict):
                metadata = {}
                issues.append("invalid-frontmatter")
        except yaml.YAMLError:
            issues.append("invalid-yaml")
        body = text[match.end():]
    else:
        issues.append("missing-frontmatter")
    if not isinstance(metadata.get("name"), str) or not metadata.get("name"):
        issues.append("missing-name")
    if not isinstance(metadata.get("description"), str) or not metadata.get("description"):
        issues.append("missing-description")
    if re.search(r"\[TODO|\[TBD|Briefly describe|Add the task-specific guidance", text, re.I):
        issues.append("unfinished-placeholder")
    return metadata, body, issues


def sentences(text: str, pattern: str, limit: int = 5) -> list[str]:
    fragments = re.split(r"(?<=[。！？])|(?<=[.!?])\s+|\n", text)
    result = []
    for fragment in fragments:
        fragment = fragment.strip(" #-\t")
        if re.search(pattern, fragment, re.I) and len(fragment) > 10:
            result.append(fragment[:700])
        if len(result) >= limit:
            break
    return list(dict.fromkeys(result))


def section_lines(body: str, heading_pattern: str) -> list[str]:
    active = False
    result = []
    for line in body.splitlines():
        if re.match(r"^#{1,3}\s", line):
            active = bool(re.search(heading_pattern, line, re.I))
        elif active and line.strip() and not line.startswith("```"):
            result.append(line.strip()[:500])
            if len(result) == 8:
                break
    return result


def metadata_card(metadata: dict, body: str, source: Path, issues: list[str]) -> dict:
    name = str(metadata.get("name") or source.parent.name).strip()
    description = metadata.get("description") if isinstance(metadata.get("description"), str) else ""
    description = re.sub(r"\s+", " ", description).strip()
    summary = make_summary(description, name)
    sample = description + "\n" + body[:18000]
    triggers = sentences(description, r"use when|use for|when |適用|使用者|當|只要|用於|use this|trigger")
    if not triggers:
        triggers = section_lines(body, r"when to use|trigger|適用|觸發|使用情境")
    if not triggers:
        issues.append("trigger-needs-review")
    boundaries = sentences(description + "\n" + body[:5000], r"not for|do not|never|only when|不負責|不適用|不套用|不需要|不得|不能|不要|僅限|超出|邊界")
    if not boundaries:
        issues.append("boundary-needs-review")
    exceptions = section_lines(body, r"exception|failure|fallback|troubleshoot|例外|失敗|資料不足|異常|限制")
    if not exceptions:
        exceptions = sentences(body[:18000], r"missing |unavailable|if .*fail|if .*not|不足|缺少|未取得|未確認|失敗|超出|不明|待確認|無法")
    if not exceptions:
        issues.append("exception-needs-review")
    outputs = section_lines(body, r"deliver|output|產物|交付|輸出|成果")
    if not outputs:
        outputs = sentences(description, r"create|produce|generate|return|build|交付|輸出|產出|建立|製作", 3)
    if not outputs:
        issues.append("output-needs-review")
    category = "business-automation"
    for candidate, pattern in RULES:
        if re.search(pattern, name, re.I):
            category = candidate
            break
    else:
        for candidate, pattern in RULES:
            if re.search(pattern, description, re.I):
                category = candidate
                break
    tools = []
    tool_evidence = []
    for tool, pattern in TOOL_PATTERNS.items():
        match = re.search(pattern, sample, re.I)
        if match:
            tools.append(tool)
            tool_evidence.append({"tool": tool, "evidence": sample[max(0, match.start()-50):match.end()+90].replace("\n", " "), "availability": "not-checked"})
    requirements = []
    for filename in ["requirements.txt", "pyproject.toml", "package.json", "Cargo.toml"]:
        if (source.parent / filename).is_file():
            requirements.append(filename)
    local_paths = sorted(set(re.findall(r"\b[A-Za-z]:[/\\][^\n\r`\"<>|]{3,160}", sample)))[:20]
    portability = "client-runtime-required" if "OpenAI tool runtime" in tools else "check-dependencies"
    if local_paths:
        issues.append("machine-specific-paths")
    return {"name": name, "summary": summary, "description": description,
            "category": category, "category_label": CATEGORIES[category], "classification_basis": "heuristic; editable override",
            "triggers": triggers, "intent": triggers or [description or "待補：缺少用途描述"],
            "outputs": outputs, "boundaries": boundaries, "exceptions": exceptions,
            "dependencies": tools, "dependency_evidence": tool_evidence, "dependency_files": requirements,
            "local_path_references": local_paths, "portability": portability,
            "keywords": [], "frontmatter": json.loads(json.dumps(metadata, ensure_ascii=False, default=str)), "validation": "workflow-not-run"}


def make_summary(description: str, name: str) -> str:
    return (re.split(r"(?<=[。！？])|(?<=[.!?])\s+", description, maxsplit=1)[0] or name)[:350]


def package_files(source: Path) -> tuple[list[dict], list[dict]]:
    root = filesystem_path(source.parent).resolve()
    entry_text = source.read_text(encoding="utf-8-sig", errors="replace")
    referenced_dirs = set(re.findall(r"(?:\]\(|`)([A-Za-z0-9_.-]+)/[^\s)`,]+", entry_text))
    records, omitted = [], []
    for parent, dirs, files in os.walk(root, followlinks=False):
        parent_path = Path(parent)
        selected = []
        for directory in dirs:
            child = parent_path / directory
            relative = child.relative_to(root).as_posix()
            if directory in SKIP_DIRS or directory.lower().startswith((".venv", "venv-", "env-")):
                omitted.append({"path": relative, "reason": "runtime-or-cache-directory"})
            elif parent_path == root and directory not in RESOURCE_DIRS and directory not in referenced_dirs:
                omitted.append({"path": relative, "reason": "non-skill-workspace-directory"})
            elif child.is_symlink() or child.is_junction():
                omitted.append({"path": relative, "reason": "directory-link; external-dependency"})
            else:
                selected.append(directory)
        dirs[:] = selected
        for filename in sorted(files):
            child = parent_path / filename
            relative = child.relative_to(root).as_posix()
            try:
                if SECRET_FILE.match(filename) and not filename.endswith((".example", ".template", ".sample")):
                    omitted.append({"path": relative, "reason": "credential-filename"})
                    continue
                if child.is_symlink() and not child.resolve().is_relative_to(root):
                    omitted.append({"path": relative, "reason": "external-file-link"})
                    continue
                if child.stat().st_size > 64 * 1024 * 1024:
                    omitted.append({"path": relative, "reason": "large-runtime-or-asset; retain-source"})
                    continue
                if filename.endswith((".pyc", ".pyo")):
                    continue
                data = child.read_bytes()
                sensitive = next((kind for kind, pattern in SECRET_PATTERNS if pattern.search(data)), None)
                if sensitive:
                    omitted.append({"path": relative, "reason": "sensitive-content:" + sensitive})
                    continue
                records.append({"path": relative, "size": len(data), "sha256": digest(data)})
            except OSError as error:
                omitted.append({"path": relative, "reason": "read-error:" + type(error).__name__})
    return sorted(records, key=lambda entry: entry["path"]), omitted


def manifest_digest(files: list[dict]) -> str:
    return digest(json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def copy_package(source: Path, root: Path, records: list[dict], object_hash: str) -> None:
    root = filesystem_path(root)
    destination = root / "objects" / object_hash[:2] / object_hash
    if destination.exists():
        return
    temporary = destination.with_name("incoming-" + uuid.uuid4().hex)
    temporary.mkdir(parents=True)
    for record in records:
        original = relative_path(filesystem_path(source.parent), record["path"])
        data = original.read_bytes()
        if digest(data) != record["sha256"]:
            raise RuntimeError("Source changed during packaging: " + str(original))
        target = relative_path(temporary / "skill", record["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    write_json(temporary / "manifest.json", {"schema": 1, "sha256": object_hash, "files": records})
    temporary.rename(destination)


def create_sqlite(path: Path, records: list[dict]) -> None:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE skills (id TEXT PRIMARY KEY, name TEXT, summary TEXT, category TEXT, status TEXT, package_sha256 TEXT, record_json TEXT)")
    connection.execute("CREATE VIRTUAL TABLE skill_search USING fts5(id UNINDEXED, name, description, dependencies, triggers, tokenize='unicode61')")
    connection.execute("CREATE TABLE sources (skill_id TEXT, path TEXT, client TEXT, scope TEXT, FOREIGN KEY(skill_id) REFERENCES skills(id))")
    for record in records:
        connection.execute("INSERT INTO skills VALUES(?,?,?,?,?,?,?)", (record["id"], record["name"], record["summary"], record["category"], record["status"], record["package_sha256"], json.dumps(record, ensure_ascii=False)))
        connection.execute("INSERT INTO skill_search VALUES(?,?,?,?,?)", (record["id"], record["name"], record["description"], " ".join(record["dependencies"]), " ".join(record["triggers"] + record.get("keywords", []))))
        connection.executemany("INSERT INTO sources VALUES(?,?,?,?)", [(record["id"], source["path"], source["client"], source["scope"]) for source in record["sources"]])
    connection.execute("CREATE INDEX skills_category ON skills(category)")
    connection.commit()
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise RuntimeError("SQLite integrity failure")
    connection.close()


def write_inventory_csv(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ID", "名稱", "一句話用途", "分類", "觸發條件", "相依工具", "任務產物", "邊界", "例外處理", "狀態", "待改善", "來源", "SHA256"])
        for record in records:
            values = [record["id"], record["name"], record["summary"], record["category_label"], " | ".join(record["triggers"]),
                      " | ".join(record["dependencies"]), " | ".join(record["outputs"]), " | ".join(record["boundaries"]),
                      " | ".join(record["exceptions"]), record["status"], " | ".join(record["issues"]),
                      " | ".join(source["path"] for source in record["sources"]), record["package_sha256"]]
            writer.writerow(["'" + value if value and value[:1] in "=+-@" else value for value in values])


def render_card(record: dict) -> str:
    lines = ["# " + record["name"], "", record["summary"], "", "- 管理 ID：`" + record["id"] + "`",
             "- 分類：" + record["category_label"], "- 狀態：" + record["status"],
             "- 驗證：原始工作流程未執行；以下為來源文字擷取，分類可人工調整。",
             "- 封裝 SHA-256：`" + record["package_sha256"] + "`", ""]
    for title, key in [("使用情境與觸發條件", "triggers"), ("使用者意圖", "intent"), ("任務產物", "outputs"),
                       ("邊界條件", "boundaries"), ("來源中的例外處理", "exceptions"), ("相依工具", "dependencies")]:
        lines.extend(["## " + title, ""])
        lines.extend("- " + str(value).replace("\n", " ") for value in record[key] or ["待確認：來源未明確記載。"])
        lines.append("")
    lines.extend(["## 管理規則", "", "資料不足時保留待確認欄位；來源衝突時逐份列出差異。同名技能不自動合併；依客戶端、工具與產物選擇。執行前讀取完整原始 SKILL.md，並以其所在目錄解析 references/scripts/assets。", "",
                  "這份管理卡不授予發送、付費生成、發布或帳號操作權限。不因封裝或靜態檢查通過而標記原工作流程已驗收。", "", "## 來源", ""])
    lines.extend("- `" + source["path"] + "`（" + source["client"] + " / " + source["scope"] + "）" for source in record["sources"])
    lines.extend(["", "## 待改善", ""])
    lines.extend("- " + issue for issue in record["issues"] or ["未發現上述靜態問題；仍需真實任務驗證。"])
    return "\n".join(lines) + "\n"


def render_dashboard(release: Path, records: list[dict], summary: dict) -> None:
    template = (BASE / "dashboard/index.template.html").read_text(encoding="utf-8")
    data = json.dumps({"records": records, "summary": summary, "categories": CATEGORIES}, ensure_ascii=False)
    data = data.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    for target, prefix in [(release / "index.html", "../../"), (release / "root-index.html", "")]:
        target.write_text(template.replace("__CATALOG_DATA__", data).replace("__ROOT_PREFIX__", prefix), encoding="utf-8")


def build(discovery_path: Path, library: Path) -> dict:
    library = filesystem_path(library)
    discovery = read_json(discovery_path)
    snapshot = datetime.now(TZ).strftime("%Y%m%dT%H%M%S+0800") + "-" + re.sub(r"[^A-Za-z0-9_-]", "-", socket.gethostname())
    release = library / "releases" / snapshot
    release.mkdir(parents=True)
    overrides = read_json(BASE / "config/overrides.json")
    physical: dict[str, dict] = {}
    failures = []
    for entry in discovery["paths"]:
        path = Path(entry)
        try:
            resolved = str(path.resolve(strict=True))
            key = os.path.normcase(resolved)
            scope, client = source_scope(entry)
            source = {"path": entry, "resolved_path": resolved, "scope": scope, "client": client}
            if key not in physical:
                metadata, body, issues = parse_skill(path)
                physical[key] = {"path": Path(resolved), "metadata": metadata, "body": body, "issues": issues, "sources": []}
            physical[key]["sources"].append(source)
        except (OSError, ValueError) as error:
            failures.append({"path": entry, "reason": type(error).__name__})
    print(json.dumps({"phase": "package", "physical_entrypoints": len(physical), "snapshot": snapshot}), flush=True)
    unique: dict[str, dict] = {}
    source_manifest = []
    omissions = []
    for index, item in enumerate(physical.values()):
        if index % 80 == 0:
            print(json.dumps({"phase": "inventory", "done": index + 1, "total": len(physical), "unique": len(unique)}), flush=True)
        source = item["path"]
        files, omitted = package_files(source)
        source_manifest.extend({"root": str(source.parent), **record} for record in files)
        issues = list(item["issues"])
        meaningful_omissions = [entry for entry in omitted if entry["reason"] not in {"runtime-or-cache-directory", "non-skill-workspace-directory"}]
        omissions.extend({"source": str(source), **entry} for entry in omitted)
        if meaningful_omissions:
            issues.append("omitted-files-needs-review")
        if not any(record["path"] == source.name for record in files):
            failures.append({"path": str(source), "reason": "entrypoint-excluded; retained-locally"})
            continue
        object_hash = manifest_digest(files)
        if object_hash in unique:
            unique[object_hash]["sources"].extend(item["sources"])
            unique[object_hash]["issues"] = sorted(set(unique[object_hash]["issues"] + issues))
            unique[object_hash]["omitted"].extend({"source": str(source), **entry} for entry in omitted)
            continue
        copy_package(source, library, files, object_hash)
        record = metadata_card(item["metadata"], item["body"], source, issues)
        slug = re.sub(r"[^a-z0-9-]", "-", record["name"].lower()).strip("-")[:64] or "skill"
        record.update({"id": slug + "-" + object_hash[:12], "package_sha256": object_hash,
                       "object_path": "objects/" + object_hash[:2] + "/" + object_hash + "/skill/SKILL.md",
                       "sources": item["sources"], "omitted": [{"source": str(source), **entry} for entry in omitted],
                       "issues": sorted(set(issues)), "file_count": len(files), "bytes": sum(entry["size"] for entry in files)})
        override = overrides.get(record["name"], {})
        if override:
            record.update(override)
            record["category_label"] = CATEGORIES[record["category"]]
            record["classification_basis"] = "curated override"
        unique[object_hash] = record
        if index % 80 == 0:
            print(json.dumps({"phase": "package", "done": index + 1, "total": len(physical), "unique": len(unique)}), flush=True)
    records = sorted(unique.values(), key=lambda record: (record["name"].casefold(), record["id"]))
    groups = defaultdict(list)
    for record in records:
        groups[record["name"].casefold()].append(record["id"])
    duplicates = {name: ids for name, ids in groups.items() if len(ids) > 1}
    for record in records:
        record["sources"] = list({source["path"].casefold(): source for source in record["sources"]}.values())
        record["same_name_variants"] = duplicates.get(record["name"].casefold(), [])
        record["archive_only"] = all(source["scope"] == "archive" for source in record["sources"])
        critical = {"invalid-yaml", "invalid-frontmatter", "missing-frontmatter", "missing-name", "missing-description", "unfinished-placeholder", "encoding-replacement", "omitted-files-needs-review"}
        record["status"] = "quarantined" if critical.intersection(record["issues"]) else "catalogued"
        record["recommended"] = record["status"] == "catalogued" and not record["archive_only"]
        record["card_path"] = "releases/" + snapshot + "/cards/" + record["id"] + ".md"
        target = release / "cards" / (record["id"] + ".md")
        target.parent.mkdir(exist_ok=True)
        target.write_text(render_card(record), encoding="utf-8")
    summary = {"schema": 1, "repo_id": REPO_ID, "snapshot": snapshot, "created_at": datetime.now(TZ).isoformat(),
               "machine": discovery["machine"], "discovered_aliases": len(discovery["paths"]),
               "physical_entrypoints": len(physical), "unique_packages": len(records),
               "names": len(groups), "same_name_variant_groups": len(duplicates),
               "exact_duplicate_packages_saved": len(physical) - len(records) - len(failures),
               "files": sum(record["file_count"] for record in records), "bytes": sum(record["bytes"] for record in records),
               "quarantined": sum(record["status"] == "quarantined" for record in records),
               "archive_only": sum(record["archive_only"] for record in records),
               "categories": dict(Counter(record["category"] for record in records)),
               "review_issues": dict(Counter(issue for record in records for issue in record["issues"])),
               "scan_errors": sum(len(scan["errors"]) for scan in discovery["scans"]),
               "failed_entrypoints": len(failures), "workflow_acceptance": "not-run"}
    write_json(release / "summary.json", summary)
    write_json(release / "catalog.json", records)
    (release / "catalog.jsonl").write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")
    write_inventory_csv(release / "inventory.csv", records)
    create_sqlite(release / "skills.sqlite", records)
    write_json(release / "audit/discovery.json", discovery)
    write_json(release / "audit/source-files.json", source_manifest)
    write_json(release / "audit/omissions.json", omissions)
    write_json(release / "audit/failures.json", failures)
    write_json(release / "audit/same-name-variants.json", duplicates)
    write_json(release / "audit/review-queue.json", [{"id": record["id"], "name": record["name"], "status": record["status"], "issues": record["issues"]} for record in records if record["issues"]])
    manager = release / "manager/SKILL.md"
    manager.parent.mkdir()
    manager.write_bytes((BASE / "manager/nas-skill-library/SKILL.md").read_bytes())
    for relative in MANAGED_FILES:
        original = relative_path(BASE, relative)
        target = relative_path(release / "management-source", relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
    render_dashboard(release, records, summary)
    release_files = [{"path": file.relative_to(release).as_posix(), "size": file.stat().st_size, "sha256": file_digest(file)} for file in sorted(release.rglob("*")) if file.is_file()]
    write_json(release / "release-manifest.json", {"schema": 1, "snapshot": snapshot, "files": release_files, "sha256": manifest_digest(release_files)})
    write_json(library / "CURRENT.json", {"schema": 1, "repo_id": REPO_ID, "snapshot": snapshot,
                                          "release": "releases/" + snapshot, "release_manifest_sha256": file_digest(release / "release-manifest.json")})
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


def verify(library: Path, sources: bool = False, snapshot: str | None = None) -> dict:
    library = filesystem_path(library)
    current = read_json(library / "CURRENT.json")
    if current["repo_id"] != REPO_ID:
        raise RuntimeError("Unrecognized library")
    release = relative_path(library, "releases/" + snapshot if snapshot else current["release"])
    manifest_path = release / "release-manifest.json"
    if not snapshot and file_digest(manifest_path) != current["release_manifest_sha256"]:
        raise RuntimeError("Release manifest changed")
    release_manifest = read_json(manifest_path)
    if manifest_digest(release_manifest["files"]) != release_manifest["sha256"]:
        raise RuntimeError("Invalid release manifest")
    for entry in release_manifest["files"]:
        path = relative_path(release, entry["path"])
        if not path.is_file() or path.stat().st_size != entry["size"] or file_digest(path) != entry["sha256"]:
            raise RuntimeError("Release integrity failed: " + entry["path"])
    records = read_json(release / "catalog.json")
    checked_files = 0
    for index, record in enumerate(records):
        object_root = library / "objects" / record["package_sha256"][:2] / record["package_sha256"]
        manifest = read_json(object_root / "manifest.json")
        if manifest_digest(manifest["files"]) != record["package_sha256"] or manifest["sha256"] != record["package_sha256"]:
            raise RuntimeError("Invalid package manifest")
        for entry in manifest["files"]:
            path = relative_path(object_root / "skill", entry["path"])
            if not path.is_file() or path.stat().st_size != entry["size"] or file_digest(path) != entry["sha256"]:
                raise RuntimeError("Package integrity failed: " + record["id"] + "/" + entry["path"])
            checked_files += 1
        if index % 150 == 0:
            print(json.dumps({"phase": "verify", "packages": index + 1, "total": len(records)}), flush=True)
    changed_sources = []
    if sources:
        for entry in read_json(release / "audit/source-files.json"):
            original = relative_path(filesystem_path(Path(entry["root"])), entry["path"])
            if not original.is_file() or file_digest(original) != entry["sha256"]:
                changed_sources.append(str(original))
    connection = readonly_sqlite(release / "skills.sqlite")
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    count = connection.execute("SELECT count(*) FROM skills").fetchone()[0]
    connection.close()
    result = {"snapshot": release.name, "packages": len(records), "files": checked_files, "sqlite_integrity": integrity,
              "sqlite_records": count, "source_hashes_checked": sources, "changed_sources": changed_sources}
    if integrity != "ok" or count != len(records) or changed_sources:
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def publish(library: Path, destination: Path) -> dict:
    library = filesystem_path(library)
    destination = filesystem_path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    lock = destination / ".publish.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(descriptor, json.dumps({"machine": socket.gethostname(), "started": datetime.now(TZ).isoformat()}).encode())
        os.close(descriptor)
        registry_path = destination / "REGISTRY.json"
        if registry_path.exists() and read_json(registry_path)["repo_id"] != REPO_ID:
            raise RuntimeError("NAS target belongs to another database")
        current = read_json(library / "CURRENT.json")
        release = relative_path(library, current["release"])
        records = read_json(release / "catalog.json")
        def publish_object(record: dict) -> None:
            relative = "objects/" + record["package_sha256"][:2] + "/" + record["package_sha256"]
            original, target = relative_path(library, relative), relative_path(destination, relative)
            if target.exists():
                expected = read_json(original / "manifest.json")
                actual = read_json(target / "manifest.json")
                if actual != expected:
                    raise RuntimeError("Existing immutable object differs")
                for entry in expected["files"]:
                    if file_digest(relative_path(target / "skill", entry["path"])) != entry["sha256"]:
                        raise RuntimeError("Existing immutable object is corrupt")
                return
            temporary = target.with_name(target.name + ".incoming-" + uuid.uuid4().hex)
            shutil.copytree(original, temporary)
            rename_with_retry(temporary, target)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            for index, _ in enumerate(pool.map(publish_object, records)):
                if index % 100 == 0:
                    print(json.dumps({"phase": "nas-copy", "packages": index + 1, "total": len(records)}), flush=True)
        target_release = relative_path(destination, current["release"])
        if target_release.exists():
            if file_digest(target_release / "release-manifest.json") != current["release_manifest_sha256"]:
                raise RuntimeError("Existing release differs")
        else:
            temporary = target_release.with_name(target_release.name + ".incoming-" + uuid.uuid4().hex)
            shutil.copytree(release, temporary)
            rename_with_retry(temporary, target_release)
        # Verify the immutable snapshot before changing the shared CURRENT pointer.
        temporary_current = destination / ("CURRENT.pending-" + uuid.uuid4().hex + ".json")
        write_json(temporary_current, current)
        # verify() accepts the local current manifest while package bytes come from NAS.
        previous_current = destination / "CURRENT.json"
        if previous_current.exists() and read_json(previous_current)["repo_id"] != REPO_ID:
            raise RuntimeError("Unexpected CURRENT file")
        verify_snapshot(destination, target_release, current)
        managed = MANAGED_FILES
        registry = read_json(registry_path) if registry_path.exists() else {"repo_id": REPO_ID, "managed_hashes": {}}
        for relative in managed + ["index.html"]:
            original = release / "root-index.html" if relative == "index.html" else relative_path(BASE, relative)
            target = relative_path(destination, relative)
            if target.exists():
                known = registry["managed_hashes"].get(relative)
                actual = file_digest(target)
                if actual != known and actual != file_digest(original):
                    raise RuntimeError("NAS managed file was independently modified: " + relative)
        for relative in managed + ["index.html"]:
            original = release / "root-index.html" if relative == "index.html" else relative_path(BASE, relative)
            target = relative_path(destination, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".incoming-" + uuid.uuid4().hex)
            shutil.copyfile(original, temporary)
            rename_with_retry(temporary, target, replace=True)
            registry["managed_hashes"][relative] = file_digest(target)
        registry.update({"last_published": datetime.now(TZ).isoformat(), "latest_snapshot": current["snapshot"]})
        write_json(registry_path, registry)
        rename_with_retry(temporary_current, previous_current, replace=True)
        result = {"destination": str(destination), "snapshot": current["snapshot"], "packages": len(records), "readback": "sha256-pass"}
        write_json(library / "publish-result.json", result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return result
    finally:
        lock.unlink(missing_ok=True)


def verify_snapshot(destination: Path, release: Path, current: dict) -> None:
    manifest = read_json(release / "release-manifest.json")
    if file_digest(release / "release-manifest.json") != current["release_manifest_sha256"]:
        raise RuntimeError("NAS release manifest mismatch")
    for entry in manifest["files"]:
        if file_digest(relative_path(release, entry["path"])) != entry["sha256"]:
            raise RuntimeError("NAS release readback mismatch")
    records = read_json(release / "catalog.json")
    for index, record in enumerate(records):
        root = destination / "objects" / record["package_sha256"][:2] / record["package_sha256"]
        package_manifest = read_json(root / "manifest.json")
        if manifest_digest(package_manifest["files"]) != record["package_sha256"]:
            raise RuntimeError("NAS object manifest mismatch")
        for entry in package_manifest["files"]:
            if file_digest(relative_path(root / "skill", entry["path"])) != entry["sha256"]:
                raise RuntimeError("NAS package readback mismatch: " + record["id"])
        if index % 100 == 0:
            print(json.dumps({"phase": "nas-readback", "packages": index + 1, "total": len(records)}), flush=True)


def search(library: Path, query: str, limit: int) -> list[dict]:
    current = read_json(library / "CURRENT.json")
    records = read_json(relative_path(library, current["release"]) / "catalog.json")
    words = query.casefold().split()
    results = []
    for record in records:
        if not record["recommended"]:
            continue
        text = " ".join([record["name"], record["summary"], record["description"], *record["dependencies"], *record["triggers"], *record.get("keywords", [])]).casefold()
        if all(word in text for word in words):
            results.append(record)
    results.sort(key=lambda record: (query.casefold() != record["name"].casefold(), len(record["same_name_variants"]) > 0, record["name"].casefold()))
    trimmed = [{"id": record["id"], "name": record["name"], "summary": record["summary"], "category": record["category_label"],
                "dependencies": record["dependencies"], "entrypoint": str(relative_path(library, record["object_path"])), "variants": len(record["same_name_variants"])} for record in results[:limit]]
    print(json.dumps(trimmed, ensure_ascii=False, indent=2))
    return trimmed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["build", "finalize", "verify", "publish", "search"])
    parser.add_argument("--library", type=Path, default=BASE / ".work/library")
    parser.add_argument("--discovery", type=Path, default=BASE / ".work/discovery.json")
    parser.add_argument("--nas", type=Path, default=Path(NAS))
    parser.add_argument("--sources", action="store_true")
    parser.add_argument("--snapshot")
    parser.add_argument("--query", default="")
    parser.add_argument("--limit", type=int, default=10)
    arguments = parser.parse_args()
    if arguments.command == "build":
        build(arguments.discovery, arguments.library)
    elif arguments.command == "finalize":
        finalize(arguments.library)
    elif arguments.command == "verify":
        verify(arguments.library, arguments.sources, arguments.snapshot)
    elif arguments.command == "publish":
        publish(arguments.library, arguments.nas)
    else:
        search(arguments.library, arguments.query, arguments.limit)


if __name__ == "__main__":
    main()
