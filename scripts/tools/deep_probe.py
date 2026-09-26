"""Deep probe — show ALL top-level attributes of source modules."""
from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

MODULES = [
    "sources.tavily", "sources.ddgs", "sources.google_news",
    "sources.gdelt", "sources.threads",
    "tools.search", "tools.threads",
]


def describe(name: str, obj) -> str:
    if inspect.isfunction(obj) or inspect.iscoroutinefunction(obj):
        try:
            sig = inspect.signature(obj)
        except (ValueError, TypeError):
            sig = "(...)"
        marker = "async " if inspect.iscoroutinefunction(obj) else ""
        return f"{marker}def {name}{sig}"
    if inspect.isclass(obj):
        methods = [
            m for m in dir(obj)
            if not m.startswith("_") and callable(getattr(obj, m, None))
        ]
        return f"class {name}  methods={methods[:8]}"
    return f"{name} = {type(obj).__name__}"


def main() -> None:
    for mod_name in MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except Exception as exc:  # noqa: BLE001
            print(f"\n[{mod_name}] <import failed: {exc}>")
            continue
        print(f"\n[{mod_name}]")
        shown = 0
        for name, obj in inspect.getmembers(mod):
            if name.startswith("_") or inspect.ismodule(obj):
                continue
            print(f"  {describe(name, obj)}")
            shown += 1
        if shown == 0:
            print("  <no public attributes>")


if __name__ == "__main__":
    main()
