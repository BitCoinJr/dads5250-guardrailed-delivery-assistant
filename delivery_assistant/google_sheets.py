"""Read the private BA backlog through user-authorized, read-only Google OAuth.

There is deliberately no Sheets write API, public CSV endpoint, ambient service
account discovery, browser-cookie access, or automatic interactive sign-in here.
"""
from __future__ import annotations

from datetime import date
from contextlib import suppress
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
from urllib.parse import quote

from pydantic import ValidationError

from .backlog_models import BACKLOG_FIELDS, BACKLOG_HEADERS, BacklogItem

EXPECTED_SHEET_ID = "1xivPgl4mOwksttv2ScvZpMD3bpLRyNZPKVMjuRt4byY"
DEFAULT_RANGE = "Request backlog!A3:T200"
READ_ONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
SCOPES = (READ_ONLY_SCOPE,)
TOKEN_URI = "https://oauth2.googleapis.com/token"
MAX_SECRET_BYTES = 32_768
MAX_RESPONSE_BYTES = 1_000_000
MAX_DATA_ROWS = 197
DATE_FIELDS = frozenset({"requested_on", "desired_by", "planned_start", "planned_finish", "actual_start", "actual_finish"})


class GoogleSheetsError(ValueError):
    """An actionable error which never contains token or remote response bodies."""


def _project_root(project_root: Path | None = None) -> Path:
    return Path(project_root).resolve() if project_root is not None else Path(__file__).resolve().parents[1]


def _secret_path(project_root: Path | None, name: str) -> Path:
    if name not in {"google_oauth_client.json", "google_token.json"}:
        raise GoogleSheetsError("The Google credential filename is not permitted.")
    root = _project_root(project_root)
    folder = root / ".secrets"
    path = folder / name
    if folder.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()) or folder.resolve().parent != root:
        raise GoogleSheetsError("Google credential paths must be regular files inside this project's .secrets folder.")
    if path.exists() and not path.is_file():
        raise GoogleSheetsError("A Google credential path is not a regular file.")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if not path.is_file() or path.stat().st_size > MAX_SECRET_BYTES:
            raise GoogleSheetsError("The local Google credential file is missing or too large.")
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise GoogleSheetsError("The local Google credential file is invalid.")
        return value
    except GoogleSheetsError:
        raise
    except (OSError, ValueError):
        raise GoogleSheetsError("The local Google credential file could not be read. Check the setup guide.") from None


def _validate_token_info(info: dict[str, Any]) -> None:
    scopes = info.get("scopes", [])
    if isinstance(scopes, str):
        scopes = scopes.split()
    if not isinstance(scopes, (list, tuple)) or not all(isinstance(scope, str) for scope in scopes) or set(scopes) != set(SCOPES):
        raise GoogleSheetsError("The saved Google token must request only Sheets read-only access. Run the connection script again.")
    if info.get("token_uri") != TOKEN_URI:
        raise GoogleSheetsError("The saved Google token has an unexpected authorization endpoint.")
    if not isinstance(info.get("client_id"), str) or not info["client_id"].endswith(".apps.googleusercontent.com"):
        raise GoogleSheetsError("The saved Google token has an invalid client identity.")
    if not isinstance(info.get("client_secret"), str) or not info["client_secret"]:
        raise GoogleSheetsError("The saved Google token is incomplete. Run the connection script again.")
    if not info.get("token") and not info.get("refresh_token"):
        raise GoogleSheetsError("The saved Google token is incomplete. Run the connection script again.")


def _validate_client_config(config: dict[str, Any]) -> None:
    installed = config.get("installed")
    if not isinstance(installed, dict):
        raise GoogleSheetsError("Use a Google OAuth Desktop app client JSON, not a service-account key or web client.")
    if installed.get("token_uri") != TOKEN_URI or installed.get("auth_uri") not in {
        "https://accounts.google.com/o/oauth2/auth", "https://accounts.google.com/o/oauth2/v2/auth",
    }:
        raise GoogleSheetsError("The Google Desktop client has unexpected authorization endpoints.")
    if not isinstance(installed.get("client_id"), str) or not installed["client_id"].endswith(".apps.googleusercontent.com"):
        raise GoogleSheetsError("The Google Desktop client identity is invalid.")
    if not isinstance(installed.get("client_secret"), str) or not installed["client_secret"]:
        raise GoogleSheetsError("The Google Desktop client JSON is incomplete.")


def _save_credentials(credentials: Any, project_root: Path | None) -> None:
    path = _secret_path(project_root, "google_token.json")
    try:
        serialized = credentials.to_json()
        if len(serialized.encode("utf-8")) > MAX_SECRET_BYTES:
            raise GoogleSheetsError("The returned Google credential file is too large.")
        _validate_token_info(json.loads(serialized))
        path.parent.mkdir(parents=True, exist_ok=True)
        _secret_path(project_root, "google_token.json")
        descriptor, temporary_name = tempfile.mkstemp(prefix=".google-token-", suffix=".tmp", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            _secret_path(project_root, "google_token.json")
            os.replace(temporary, path)
            if os.name != "nt":
                path.chmod(0o600)
        finally:
            temporary.unlink(missing_ok=True)
    except GoogleSheetsError:
        raise
    except Exception:
        raise GoogleSheetsError("Google sign-in could not be saved locally. Check the .secrets folder permissions.") from None


def connection_status(project_root: Path | None = None) -> dict[str, Any]:
    """Inspect local setup only. Never contact Google or trigger a browser login."""
    try:
        client_path = _secret_path(project_root, "google_oauth_client.json")
        token_path = _secret_path(project_root, "google_token.json")
        client_present, token_present = client_path.is_file(), token_path.is_file()
        if token_present:
            _validate_token_info(_read_json(token_path))
        return {
            "configured": token_present,
            "client_present": client_present,
            "token_present": token_present,
            "message": "Local Google sign-in is configured; refresh reads the selected private sheet." if token_present else "Connect Google once using scripts/connect_google.py. The setup guide is in docs/GOOGLE_SHEETS_SETUP_JA.md.",
        }
    except GoogleSheetsError as exc:
        return {"configured": False, "client_present": False, "token_present": False, "message": str(exc)}


def _load_credentials(project_root: Path | None) -> Any:
    token_path = _secret_path(project_root, "google_token.json")
    if not token_path.is_file():
        raise GoogleSheetsError("Google is not connected. Save the Desktop client JSON and run scripts/connect_google.py first.")
    info = _read_json(token_path)
    _validate_token_info(info)
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        credentials = Credentials.from_authorized_user_info(info, scopes=list(SCOPES))
        if not credentials.valid:
            if not credentials.refresh_token:
                raise GoogleSheetsError("Google sign-in expired. Run scripts/connect_google.py again.")
            credentials.refresh(Request())
            _save_credentials(credentials, project_root)
        return credentials
    except GoogleSheetsError:
        raise
    except ImportError:
        raise GoogleSheetsError("Google connection libraries are missing. Run Setup.ps1 to install the project requirements.") from None
    except Exception:
        raise GoogleSheetsError("Google sign-in could not be refreshed. Run scripts/connect_google.py again; no token details were logged.") from None


def _authorized_session(credentials: Any) -> Any:
    from google.auth.transport.requests import AuthorizedSession
    return AuthorizedSession(credentials, max_refresh_attempts=1, refresh_timeout=30)


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise GoogleSheetsError("A backlog cell has an unsupported value type.")
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    if len(text) > 6000 or "\x00" in text:
        raise GoogleSheetsError("A backlog cell exceeds the text limit or contains invalid characters.")
    return text


def parse_backlog_values(values: Any) -> list[BacklogItem]:
    """Map the bounded values matrix to business requests without evaluating cells."""
    if not isinstance(values, list) or not values or len(values) > MAX_DATA_ROWS + 1:
        raise GoogleSheetsError("The backlog must contain a header and at most 197 request rows.")
    if not isinstance(values[0], list):
        raise GoogleSheetsError("The backlog header row is invalid.")
    headers = [_cell_text(v) for v in values[0]]
    if len(headers) != len(BACKLOG_HEADERS) or len(set(headers)) != len(headers) or set(headers) != set(BACKLOG_HEADERS):
        raise GoogleSheetsError("Header row 3 must contain the 20 configured backlog column names exactly once.")
    field_by_header = dict(zip(BACKLOG_HEADERS, BACKLOG_FIELDS))
    items: list[BacklogItem] = []
    seen: set[str] = set()
    for number, row in enumerate(values[1:], start=4):
        if not isinstance(row, list) or len(row) > len(headers):
            raise GoogleSheetsError(f"Backlog row {number} has an invalid column count.")
        cells = [_cell_text(v) for v in row]
        if not any(cells):
            continue
        cells.extend([""] * (len(headers) - len(cells)))
        data: dict[str, Any] = {field_by_header[header]: value for header, value in zip(headers, cells)}
        for field in DATE_FIELDS:
            value = data[field]
            if value:
                try:
                    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                        raise ValueError
                    date.fromisoformat(value)
                except ValueError:
                    raise GoogleSheetsError(f"Backlog row {number} needs ISO dates such as 2026-11-18, or a blank date.") from None
        if data["business_impact"]:
            if not re.fullmatch(r"[1-5]", data["business_impact"]):
                raise GoogleSheetsError(f"Backlog row {number} needs a business impact rating from 1 to 5, or a blank until BA review.")
            data["business_impact"] = int(data["business_impact"])
        else:
            data["business_impact"] = None
        # Lifecycle defaults support early requests; missing business judgments
        # stay unknown instead of becoming a fabricated middle rating/priority.
        for field, default in {"priority":"Unassigned", "effort":"Unknown", "ba_status":"New", "ba_decision":"Pending"}.items():
            if not data[field]:
                data[field] = default
        try:
            item = BacklogItem.model_validate(data)
        except ValidationError:
            raise GoogleSheetsError(f"Backlog row {number} has missing required fields or invalid choice values. Check the sheet's dropdowns.") from None
        if item.request_id in seen:
            raise GoogleSheetsError(f"Backlog row {number} repeats a request ID.")
        seen.add(item.request_id)
        items.append(item)
    if not items:
        raise GoogleSheetsError("The request backlog has no populated request rows.")
    return items


def read_backlog(sheet_id: str, range_name: str = DEFAULT_RANGE, *, project_root: Path | None = None) -> list[BacklogItem]:
    """Read only the selected project's fixed sheet and bounded backlog range."""
    if sheet_id != EXPECTED_SHEET_ID or range_name != DEFAULT_RANGE:
        raise GoogleSheetsError("This demo can read only its configured request spreadsheet and bounded backlog range.")
    credentials = _load_credentials(project_root)
    session = response = None
    try:
        session = _authorized_session(credentials)
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{EXPECTED_SHEET_ID}/values/{quote(DEFAULT_RANGE, safe='')}"
        response = session.get(url, params={"majorDimension": "ROWS", "valueRenderOption": "FORMATTED_VALUE"}, timeout=(10, 30), allow_redirects=False, stream=True)
        if response.status_code != 200:
            messages = {
                401: "Google sign-in expired or was revoked. Run scripts/connect_google.py again.",
                403: "The connected account cannot read the request spreadsheet, or the Google Sheets API is not enabled.",
                404: "The configured request spreadsheet or backlog tab was not found, or is not accessible to this account.",
            }
            raise GoogleSheetsError(messages.get(response.status_code, f"Google Sheets did not complete the read (HTTP {response.status_code}). Retry later."))
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_content(chunk_size=65_536):
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise GoogleSheetsError("The bounded backlog response is too large. Shorten the request text before refreshing.")
            chunks.append(chunk)
        try:
            result = json.loads(b"".join(chunks))
        except (UnicodeError, ValueError):
            raise GoogleSheetsError("Google Sheets returned an invalid values response.") from None
        if not isinstance(result, dict) or result.get("majorDimension", "ROWS") != "ROWS":
            raise GoogleSheetsError("Google Sheets returned an unexpected values structure.")
        items = parse_backlog_values(result.get("values"))
        _save_credentials(credentials, project_root)
        return items
    except GoogleSheetsError:
        raise
    except ImportError:
        raise GoogleSheetsError("Google connection libraries are missing. Run Setup.ps1.") from None
    except Exception:
        raise GoogleSheetsError("The private spreadsheet could not be read. Check Google sign-in, access and connection; no response or credential details were logged.") from None
    finally:
        if response is not None:
            with suppress(Exception):
                response.close()
        if session is not None:
            with suppress(Exception):
                session.close()


def connect_google(project_root: Path | None = None) -> None:
    """Run only from the explicit connection script, never on an app rerun."""
    client_path = _secret_path(project_root, "google_oauth_client.json")
    if not client_path.is_file():
        raise GoogleSheetsError("Save your Google OAuth Desktop client as .secrets/google_oauth_client.json first. See docs/GOOGLE_SHEETS_SETUP_JA.md.")
    config = _read_json(client_path)
    _validate_client_config(config)
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_config(config, scopes=list(SCOPES), autogenerate_code_verifier=True)
        credentials = flow.run_local_server(host="127.0.0.1", port=0, open_browser=True, timeout_seconds=300,
                                            authorization_prompt_message="A Google sign-in window has opened. Complete sign-in there.",
                                            success_message="Google sign-in was received. You can close this window.")
        _save_credentials(credentials, project_root)
    except GoogleSheetsError:
        raise
    except ImportError:
        raise GoogleSheetsError("Google connection libraries are missing. Run Setup.ps1 before connecting.") from None
    except Exception:
        raise GoogleSheetsError("Google sign-in did not complete. Check the Desktop client, test-user settings and consent, then retry. No authorization details were logged.") from None
