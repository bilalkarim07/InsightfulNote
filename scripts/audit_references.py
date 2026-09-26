"""Audit references to the old topic-queue system across the repo.

Searches every .py, .yaml, .yml, .md, .json file for references to the
old runner, its state files, and the old workflow. Reports file + line.

Does NOT modify anything. Safe to run repeatedly.
"""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path.cwd()

# What we're looking for and why.
TARGETS = {
    "run_next_topic.py":   "old topic-queue runner",
    "topic_queue.json":    "old topic queue state",
    "topic_queue":         "old topic queue reference",
    "quota.json":          "old local quota state",
    "newsroom.yml":        "old hourly workflow file",
    "data/quota.json":     "old quota JSON path",
    "data/topic_queue":    "old topic queue path",
}

# Directories to skip.
SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache", ".mypy_cache"}
# Extensions to scan.
SCAN_EXT = {".py", ".yaml", ".yml", ".md", ".txt", ".json", ".toml", ".cfg", ".ps1", ".sh"}


def iter_files() -> list[Path]:
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() not in SCAN_EXT:
            continue
        # Skip the audit script itself.
        if p.name == "audit_references.py":
            continue
        yield p


def main() -> None:
    print("=" * 74)
    print("Reference audit — old topic-queue system")
    print("=" * 74)
    print()

    findings: dict[str, list[tuple[Path, int, str]]] = {t: [] for t in TARGETS}

    for f in iter_files():
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        lines = text.splitlines()
        for lineno, line in enumerate(lines, start=1):
            for target in TARGETS:
                if target in line:
                    findings[target].append((f, lineno, line.strip()[:100]))

    total = 0
    for target, hits in findings.items():
        print(f"### {target}  —  {TARGETS[target]}")
        if not hits:
            print("  (no references found)")
            print()
            continue
        total += len(hits)
        for path, lineno, snippet in hits:
            rel = path.relative_to(ROOT)
            print(f"  {str(rel):60} :{lineno:4}  {snippet}")
        print()

    print("=" * 74)
    print(f"Total references: {total}")
    print("=" * 74)
    print()
    print("Interpretation:")
    print("  - Python files importing run_next_topic → need migration")
    print("  - YAML files invoking it → retire workflow")
    print("  - Markdown docs → update or leave as historical")
    print("  - JSON files with the path → delete or migrate")


if __name__ == "__main__":
    main()
