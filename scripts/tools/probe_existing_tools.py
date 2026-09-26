"""Probe the existing repository for tools the agent layer can reuse."""
from __future__ import annotations

import importlib
import inspect
import pkgutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CANDIDATE_PACKAGES = [
    "etl", "extraction", "tools", "core", "pipeline", "services",
    "integrations", "db", "sources",
]
KEYWORDS = ["search", "supabase", "db", "threads", "tavily",
            "ddgs", "google_news", "gdelt"]


def _pkg_paths(pkg) -> list[Path]:
    """Return searchable paths for a package, handling namespace packages."""
    paths: list[Path] = []
    pkg_file = getattr(pkg, "__file__", None)
    if pkg_file:
        paths.append(Path(pkg_file).parent)
    else:
        for p in getattr(pkg, "__path__", []) or []:
            paths.append(Path(p))
    return paths


def probe() -> None:
    print("=" * 70)
    print("Existing repository tool probe")
    print("=" * 70)

    for pkg_name in CANDIDATE_PACKAGES:
        try:
            pkg = importlib.import_module(pkg_name)
        except ImportError:
            continue
        search_paths = _pkg_paths(pkg)
        if not search_paths:
            print(f"\n[{pkg_name}] <no searchable paths>")
            continue
        print(f"\n[{pkg_name}]")
        for pkg_path in search_paths:
            if not pkg_path.exists():
                continue
            for mod_info in pkgutil.iter_modules([str(pkg_path)]):
                name = mod_info.name
                if not any(k in name.lower() for k in KEYWORDS):
                    continue
                mod_name = f"{pkg_name}.{name}"
                try:
                    mod = importlib.import_module(mod_name)
                except Exception as exc:  # noqa: BLE001
                    print(f"  {mod_name}: <import error: {exc}>")
                    continue
                print(f"  {mod_name}:")
                for fn_name, fn in inspect.getmembers(mod, inspect.isfunction):
                    if fn_name.startswith("_"):
                        continue
                    try:
                        sig = inspect.signature(fn)
                    except (ValueError, TypeError):
                        sig = "(...)"
                    print(f"      {fn_name}{sig}")


if __name__ == "__main__":
    probe()
