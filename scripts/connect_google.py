"""Explicit, user-run Google OAuth connection. Never called by the app itself."""
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from delivery_assistant.google_sheets import EXPECTED_SHEET_ID, GoogleSheetsError, connect_google, read_backlog


def main() -> int:
    try:
        connect_google(PROJECT_ROOT)
        items = read_backlog(EXPECTED_SHEET_ID, project_root=PROJECT_ROOT)
    except GoogleSheetsError as exc:
        print(str(exc))
        return 1
    print(f"Google is connected. Read {len(items)} request rows from the private backlog.")
    print("No spreadsheet values or sharing settings were changed. Return to the app and refresh the live backlog.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
