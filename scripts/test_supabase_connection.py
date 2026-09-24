import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

import os

print("=" * 40)
print("SUPABASE CONNECTION TEST")
print("=" * 40)

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SECRET_KEY")

print(f"SUPABASE_URL: {'configured' if url else 'MISSING'}")
print(f"SUPABASE_SECRET_KEY: {'configured' if key else 'MISSING'}")

if not url or not key:
    print("\n✗ Missing required environment variables.")
    sys.exit(1)

print("\nConnecting to Supabase...")
from etl.persistence.supabase import get_supabase

client = get_supabase()
resp = client.table("sources").select("id").limit(1).execute()
print(f"✓ Supabase connection successful (sources table readable, {len(resp.data)} row(s) sampled).")