"""Bounded Google Sheets CSV intake. No spreadsheet expressions are evaluated."""
from __future__ import annotations

import csv
import io
from pydantic import ValidationError

from .models import ChangeRequest

MAX_CSV_BYTES = 1_000_000
MAX_CSV_ROWS = 100
REQUIRED_COLUMNS = {"request_id", "title", "description"}


def parse_csv(content: bytes) -> list[ChangeRequest]:
    if not content or len(content) > MAX_CSV_BYTES:
        raise ValueError("Upload a non-empty UTF-8 CSV smaller than 1 MB.")
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Export the sheet as a UTF-8 CSV and try again.") from exc
    if "\x00" in decoded:
        raise ValueError("The CSV contains invalid null characters.")
    reader = csv.DictReader(io.StringIO(decoded, newline=""))
    headers = [h.strip() for h in (reader.fieldnames or [])]
    if len(headers) != len(set(headers)) or len(headers) > 30:
        raise ValueError("CSV headers must be unique, with at most 30 columns.")
    missing = REQUIRED_COLUMNS - set(headers)
    if missing:
        raise ValueError("Missing CSV columns: " + ", ".join(sorted(missing)))
    reader.fieldnames = headers
    requests: list[ChangeRequest] = []
    seen: set[str] = set()
    try:
        for row_number, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(f"CSV row {row_number} contains more cells than the header.")
            if all(not (v or "").strip() for v in row.values()):
                continue
            if len(requests) >= MAX_CSV_ROWS:
                raise ValueError(f"Upload at most {MAX_CSV_ROWS} requests per CSV.")
            values = {k: (v or "").strip() for k, v in row.items()}
            try:
                request = ChangeRequest(
                    request_id=values["request_id"],
                    title=values["title"],
                    description=values["description"],
                    acceptance_criteria=values.get("acceptance_criteria", ""),
                    target_metric=values.get("target_metric", "") or "revenue",
                )
            except ValidationError as exc:
                # Pydantic error text can contain the input. Never echo it.
                raise ValueError(f"CSV row {row_number} has missing or oversized fields.") from exc
            if request.request_id in seen:
                raise ValueError(f"CSV row {row_number} repeats a request ID.")
            seen.add(request.request_id)
            requests.append(request)
    except csv.Error as exc:
        raise ValueError("The CSV could not be parsed. Check quotes and column separators.") from exc
    if not requests:
        raise ValueError("The CSV has a header but contains no requests.")
    return requests
