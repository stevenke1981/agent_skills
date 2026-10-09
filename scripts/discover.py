"""Inventory local Skill entrypoints without changing source directories."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime, timezone

EXCLUSIONS = [
    "**/.git/**", "**/node_modules/**", "**/.venv/**", "**/venv/**",
    "**/__pycache__/**", "**/target/**", "**/$RECYCLE.BIN/**",
    "**/System Volume Information/**", "**/AppData/**", "**/sessions/**",
    "**/memories/**", "**/agent_skills/**", "**/models/**", "**/.pnpm-store/**",
]


def scan(root: str, follow: bool = False) -> dict:
    command = ["rg", "--files", "--hidden", "--no-ignore", "-g", "SKILL.md"]
    if follow:
        command.append("--follow")
    for pattern in EXCLUSIONS:
        command.extend(["-g", "!" + pattern])
    command.append(root)
    try:
        result = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace", timeout=240)
        return {"root": root, "exit_code": result.returncode,
                "paths": sorted(set(result.stdout.splitlines())),
                "errors": result.stderr.splitlines()}
    except subprocess.TimeoutExpired as error:
        partial = error.stdout or b""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", errors="replace")
        return {"root": root, "paths": sorted(set(partial.splitlines())),
                "errors": ["scan-timeout; partial results preserved"], "exit_code": -1}
    except OSError as error:
        return {"root": root, "paths": [], "errors": [str(error)], "exit_code": -1}


def discover(output: Path) -> dict:
    user = Path.home()
    roots = [user / part for part in [
        ".codex/skills", ".codex/plugin-skills", ".codex/plugins/cache", ".agents/skills",
        ".claude/skills", ".config/opencode/skills", ".opencode/skills",
        ".gemini/skills", ".gemini/antigravity-cli/skills", ".bailian/skills",
        ".copilot/skills", ".pi/agent/skills", ".cursor/skills", ".cline/skills",
        ".config/agy/skills", ".agy/skills",
    ]]
    tasks = [(str(root), True) for root in roots if root.is_dir()]
    tasks.extend((str(root), False) for root in [user, Path("E:/"), Path("D:/")] if root.is_dir())
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda task: scan(*task), tasks))
    paths = sorted({path for result in results for path in result["paths"]}, key=str.casefold)
    old_catalog = user / ".codex/skill-library/catalog.jsonl"
    missing = []
    if old_catalog.exists():
        for line in old_catalog.read_text(encoding="utf-8-sig").splitlines():
            item = json.loads(line)
            for path in [item["path"], *item.get("aliases", [])]:
                if Path(path).is_file():
                    paths.append(path)
                else:
                    missing.append(path)
    paths = sorted(set(paths), key=str.casefold)
    summary = {"created_at": datetime.now(timezone.utc).isoformat(), "machine": os.environ.get("COMPUTERNAME", "unknown"),
               "paths": paths, "scans": results, "previous_catalog_missing": sorted(set(missing)),
               "exclusions": EXCLUSIONS}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"paths": len(paths), "scans": [{"root": result["root"], "count": len(result["paths"]),
          "errors": len(result["errors"])} for result in results], "previous_catalog_missing": len(set(missing))}, ensure_ascii=False))
    return summary


def scan_projects(root: Path, output: Path, max_depth: int = 6) -> None:
    """Bounded discovery on large project disks; skip runtime/media trees."""
    summary = json.loads(output.read_text(encoding="utf-8"))
    excluded = {".git", "node_modules", ".venv", "venv", "target", "__pycache__", "models", ".pnpm-store", "$recycle.bin", "system volume information",
                "media", "renders", "render", "audio", "video", "videos", "weights", "checkpoints", "site-packages", "dist", "build", "cache", ".cache"}
    paths, skill_roots, failures, limits = [], [], [], []
    pending = [(root, 0)]
    while pending:
        directory, depth = pending.pop()
        try:
            children = list(os.scandir(directory))
            if any(child.name == "SKILL.md" and child.is_file(follow_symlinks=False) for child in children):
                paths.append(str(directory / "SKILL.md"))
            if directory.name.casefold() in {"skills", "codex-skills", "claude-skills", "plugin-skills"}:
                skill_roots.append(str(directory))
                continue
            if depth >= max_depth:
                limits.append(str(directory))
                continue
            for child in children:
                if child.name.casefold() not in excluded and child.is_dir(follow_symlinks=False) and not Path(child.path).is_junction():
                    pending.append((Path(child.path), depth + 1))
        except OSError as error:
            failures.append(str(directory) + ":" + type(error).__name__)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(scan, skill_roots))
    paths.extend(path for result in results for path in result["paths"])
    summary["paths"] = sorted(set(summary["paths"] + paths), key=str.casefold)
    summary["scans"].extend(results)
    summary["scans"].append({"root": str(root), "mode": "bounded-project-discovery", "paths": sorted(set(paths)), "errors": failures,
                              "max_depth": max_depth, "depth_limits": limits, "excluded_directory_names": sorted(excluded)})
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"root": str(root), "project_paths": len(set(paths)), "total_paths": len(summary["paths"]), "errors": len(failures), "depth_limited_directories": len(limits)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(".work/discovery.json"))
    parser.add_argument("--projects", type=Path)
    arguments = parser.parse_args()
    if arguments.projects:
        scan_projects(arguments.projects, arguments.output)
    else:
        discover(arguments.output)
