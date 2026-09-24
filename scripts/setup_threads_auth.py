"""Local script: exchange a short-lived Threads token for a long-lived one, 
or refresh an existing long-lived token.

Usage
-----
    python scripts/setup_threads_auth.py

Reads ``THREADS_APP_ID``, ``THREADS_APP_SECRET`` and
``THREADS_ACCESS_TOKEN`` from ``.env`` (via the environment).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make the repo root importable when running the script directly.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # type: ignore  # noqa: E402

from sources.threads.auth import ThreadsAuth  # noqa: E402
from sources.threads.exceptions import ThreadsError  # noqa: E402
from sources.threads.token_store import write_env_file  # noqa: E402


ENV_PATH = ROOT / ".env"


def _print_code0_help() -> None:
    print()
    print("SPECIFIC FIX FOR CODE 0 (ViewerContextCreationJustificationValidationException):")
    print("  1. Open your Meta App Dashboard at https://developers.facebook.com/apps/")
    print("  2. Select your Threads app.")
    print("  3. Go to App Roles → Roles → Add People.")
    print("  4. Under 'Additional roles for this app' choose 'Threads Tester'.")
    print("  5. Add yourself (the Facebook/Threads account you will authenticate with).")
    print("  6. On threads.net: Settings → Account → Website permissions → Invites → Accept.")
    print("  7. Regenerate the short-lived token in the Graph API Explorer")
    print("     with the Threads.net API version selected (not graph.facebook.com).")
    print("  8. Re-run this script.")
    print()
    print("If all else fails, file a bug at https://developers.facebook.com/bugs/")
    print("and include the fbtrace_id printed above.")


def main() -> int:
    load_dotenv(ENV_PATH)

    app_id = os.environ.get("THREADS_APP_ID", "").strip()
    app_secret = os.environ.get("THREADS_APP_SECRET", "").strip()
    input_token = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()

    missing = [
        name
        for name, value in (
            ("THREADS_APP_ID", app_id),
            ("THREADS_APP_SECRET", app_secret),
            ("THREADS_ACCESS_TOKEN", input_token),
        )
        if not value
    ]
    if missing:
        print(f"[ERROR] Missing required environment variables: {', '.join(missing)}")
        print(f"        Add them to {ENV_PATH} and try again.")
        return 1

    print("=" * 60)
    print("  NEWSROOM THREADS AUTH SETUP")
    print("=" * 60)
    
    # SECURITY FIX: Mask sensitive data instead of printing raw values
    print(f"App ID:                {app_id}")
    print(f"App secret:            {'*' * 8} (loaded, not displayed)")
    print(f"Input token:           {input_token[:4]}...{input_token[-4:]}")
    print("-" * 60)

    print("\nWhat do you want to do?")
    print("  1. Exchange a SHORT-LIVED token for a LONG-LIVED token")
    print("  2. REFRESH an existing LONG-LIVED token (Recommended)")
    choice = input("Enter choice [1/2, default 2]: ").strip() or "2"

    auth = ThreadsAuth(app_id=app_id, app_secret=app_secret)
    
    try:
        if choice == "1":
            print("\nExchanging short-lived token for long-lived token...")
            result = auth.exchange_short_lived_for_long_lived(short_lived_token=input_token)
        elif choice == "2":
            print("\nRefreshing long-lived token...")
            # This uses the exact logic from token_generation_new.py but saves to .env
            result = auth.refresh_long_lived_token(access_token=input_token)
        else:
            print("[ERROR] Invalid choice.")
            return 1

    except ThreadsError as exc:
        print()
        print("=" * 60)
        print("  THREADS AUTHENTICATION FAILED")
        print("=" * 60)
        print(exc.pretty())
        print("=" * 60)
        if getattr(exc, "error_code", None) == 0:
            _print_code0_help()
        return 2
    finally:
        auth.close()

    # Securely extract the token value
    long_token = result.access_token.get_secret_value()
    print("[OK] Operation successful.")
    print(f"New token:             {long_token[:4]}...{long_token[-4:]}")
    print("-" * 60)

    answer = input("Write the new token to .env? [y/N]: ").strip().lower()
    if answer == "y":
        write_env_file(str(ENV_PATH), {"THREADS_ACCESS_TOKEN": long_token})
        print(f"[OK] Updated THREADS_ACCESS_TOKEN in {ENV_PATH}")
    else:
        print("[SKIP] .env not modified. You can copy the token manually.")

    print()
    print("Reminder: refresh is MANUAL. If the token ever expires, run")
    print("`python scripts/setup_threads_auth.py` and choose Option 2.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())