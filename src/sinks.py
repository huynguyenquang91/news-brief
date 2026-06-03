"""Output sinks: append rows to the local CSV history and to a Google Sheet."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials

from . import config
from .gemini_eval import ScoredArticle

SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def build_rows(scored: list[ScoredArticle], run_dt: datetime, run_slot: str) -> list[dict]:
    """Flatten scored articles into CSV/Sheet rows (one per article)."""
    run_iso = run_dt.astimezone(timezone.utc).isoformat()
    rows: list[dict] = []
    for s in scored:
        fs = s.filter_score
        rows.append(
            {
                "run_datetime_utc": run_iso,
                "run_slot": run_slot,
                "published": s.article.published,
                "source": s.article.source,
                "title_en": s.article.title,
                "url": s.article.url,
                "newsworthiness": s.newsworthiness,
                "suitability": s.suitability,
                "composite": s.composite,
                "article_type": s.article_type,
                "source_tier": fs.source_tier if fs else "",
                "type_tier": fs.type_tier if fs else "",
                "keyword_tier": fs.keyword_tier if fs else "",
                "top_keywords": ", ".join(fs.top_keywords) if fs else "",
                "filter_priority": fs.filter_priority if fs else 0.0,
                "combined_score": s.combined_score,
                "rank": s.rank,
                "briefed": s.briefed,
                "title_vi": s.title_vi,
                "brief_vi": s.brief_vi,
            }
        )
    return rows


def write_csv(rows: list[dict]) -> None:
    """Append rows to data/briefs.csv, creating it with a header if needed."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    new_file = not config.CSV_PATH.exists()
    with config.CSV_PATH.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=config.COLUMNS)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)


def _credentials() -> Credentials:
    """Build service-account creds from a JSON file path or raw JSON env var."""
    if config.GCP_SERVICE_ACCOUNT_JSON.strip():
        info = json.loads(config.GCP_SERVICE_ACCOUNT_JSON)
        return Credentials.from_service_account_info(info, scopes=SHEETS_SCOPES)
    path = config.GOOGLE_APPLICATION_CREDENTIALS
    if path and os.path.exists(path):
        return Credentials.from_service_account_file(path, scopes=SHEETS_SCOPES)
    raise RuntimeError(
        "No Google credentials: set GCP_SERVICE_ACCOUNT_JSON or "
        "GOOGLE_APPLICATION_CREDENTIALS to a valid key file."
    )


def append_google_sheet(rows: list[dict]) -> None:
    """Append rows to the configured worksheet, creating header if empty."""
    if not config.GOOGLE_SHEET_ID:
        raise RuntimeError("GOOGLE_SHEET_ID is not set")

    client = gspread.authorize(_credentials())
    spreadsheet = client.open_by_key(config.GOOGLE_SHEET_ID)
    try:
        ws = spreadsheet.worksheet(config.SHEET_WORKSHEET)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(
            title=config.SHEET_WORKSHEET, rows=1000, cols=len(config.COLUMNS)
        )

    if not ws.get_all_values():
        ws.append_row(config.COLUMNS, value_input_option="RAW")

    values = [[row[col] for col in config.COLUMNS] for row in rows]
    ws.append_rows(values, value_input_option="RAW")
