"""Audit .env — reports key names + lengths only. NEVER prints values."""
from __future__ import annotations
from pathlib import Path

env = Path(".env")
if not env.exists():
    print("No .env file present.")
    raise SystemExit(0)

print("=" * 60)
print("Env audit (names + lengths only — no values)")
print("=" * 60)
print()

for line in env.read_text(encoding="utf-8").splitlines():
    line = line.rstrip()
    if not line or line.lstrip().startswith("#"):
        continue
    if "=" not in line:
        continue
    key, _, value = line.partition("=")
    key = key.strip()
    value = value.strip().strip("'\"")
    if value:
        print(f"  {key:28} SET ({len(value)} chars)")
    else:
        print(f"  {key:28} EMPTY")
print()
