"""Reset the published story so we can test the new adapter."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from scripts._bootstrap import *
from core.tools.database.client import get_client

c = get_client()
sid = "52b6fc16-7151-421c-aba7-f4f479121b43"

# Delete the publication records for this story
c.table("publications").delete().eq("story_id", sid).execute()
print(f"deleted publications for {sid[:8]}")

# Reset story status
c.table("stories").update({"status": "candidate"}).eq("id", sid).execute()
print(f"story {sid[:8]} reset to 'candidate'")
