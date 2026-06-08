"""Orchestrator: fetch -> score all -> rank -> brief top N -> CSV + Sheet."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone

from . import config
from .fetch_news import fetch_articles
from .gemini_eval import brief_top, score_articles
from .sinks import append_google_sheet, build_rows, write_csv


def _run_slot(now_utc: datetime) -> str:
    """Label the run am/pm based on Vietnam local time (UTC+7)."""
    vn_hour = (now_utc.hour + 7) % 24
    return "am" if vn_hour < 12 else "pm"


def _blocked_by_title(title: str) -> bool:
    t = title.lower()
    return any(p.lower() in t for p in config.BLOCK_TITLE_PATTERNS)


def _jaccard(t1: str, t2: str) -> float:
    w1 = set(re.sub(r"\W+", " ", t1.lower()).split())
    w2 = set(re.sub(r"\W+", " ", t2.lower()).split())
    if not w1 or not w2:
        return 0.0
    return len(w1 & w2) / len(w1 | w2)


def _dedup_titles(scored):
    """Drop lower-ranked article when two titles are near-identical."""
    kept = []
    for s in scored:
        if not any(_jaccard(s.article.title, k.article.title) >= config.TITLE_DEDUP_THRESHOLD
                   for k in kept):
            kept.append(s)
    return kept


def run(skip_sheet: bool = False) -> int:
    now = datetime.now(timezone.utc)
    slot = _run_slot(now)
    print(f"[1/5] Fetching news (slot={slot}, utc={now.isoformat()})...")
    articles = fetch_articles()
    print(f"      {len(articles)} candidate articles after dedup.")
    if not articles:
        print("      Nothing new to process. Exiting cleanly.")
        return 0

    print("[2/5] Scoring all articles with Gemini...")
    scored = score_articles(articles)
    print(f"      Scored {len(scored)} articles.")

    # Keep only 2026 World Cup-relevant items.
    scored = [s for s in scored if s.composite >= config.RELEVANCE_MIN_COMPOSITE]

    # Drop evergreen reference content by article type.
    if config.DROP_ARTICLE_TYPES:
        before = len(scored)
        scored = [s for s in scored if s.article_type not in config.DROP_ARTICLE_TYPES]
        if (dropped := before - len(scored)):
            print(f"      Dropped {dropped} by type ({', '.join(config.DROP_ARTICLE_TYPES)}).")

    # Drop articles whose titles match known evergreen patterns.
    if config.BLOCK_TITLE_PATTERNS:
        before = len(scored)
        scored = [s for s in scored if not _blocked_by_title(s.article.title)]
        if (dropped := before - len(scored)):
            print(f"      Dropped {dropped} by title pattern.")

    # Drop near-duplicate stories (same event, different outlets).
    before = len(scored)
    scored = _dedup_titles(scored)
    if (dropped := before - len(scored)):
        print(f"      Dropped {dropped} near-duplicate titles.")

    for i, s in enumerate(scored, 1):
        s.rank = i
    print(f"      {len(scored)} articles remaining after all filters.")
    if not scored:
        print("      No World Cup-relevant news this run. Exiting cleanly.")
        return 0

    print(f"[3/5] Writing Vietnamese briefs for top {config.BRIEF_TOP_N}...")
    scored = brief_top(scored)
    briefed = sum(1 for s in scored if s.briefed)
    print(f"      {briefed} briefs written.")

    rows = build_rows(scored, now, slot)

    print(f"[4/5] Appending {len(rows)} rows to CSV ({config.CSV_PATH})...")
    write_csv(rows)

    if skip_sheet:
        print("[5/5] Skipping Google Sheet (--skip-sheet).")
    else:
        print("[5/5] Appending rows to Google Sheet...")
        append_google_sheet(rows)
        print("      Sheet updated.")

    print("\nTop stories:")
    for s in scored[: config.BRIEF_TOP_N]:
        print(f"  #{s.rank} ({s.composite}) {s.title_vi or s.article.title}")
    print("Done.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily football news brief")
    parser.add_argument(
        "--skip-sheet", action="store_true", help="Write CSV only, skip Google Sheet"
    )
    args = parser.parse_args()
    try:
        return run(skip_sheet=args.skip_sheet)
    except Exception as err:  # noqa: BLE001 - surface failure as red CI
        print(f"ERROR: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
