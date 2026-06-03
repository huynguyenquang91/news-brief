"""Fetch international football news from Google News RSS.

No API key or quota: we query Google News' public search RSS endpoint once per
configured query, merge the results, normalize them, and drop anything we've
already seen recently (cross-run dedup against ``data/briefs.csv``).
"""

from __future__ import annotations

import csv
import html
import re
import ssl
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import feedparser

try:
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
    ssl._create_default_https_context = lambda: _SSL_CONTEXT  # noqa: SLF001
except ImportError:
    pass

from . import config

RSS_BASE = "https://news.google.com/rss/search"


@dataclass
class Article:
    title: str
    url: str
    source: str
    published: str          # ISO 8601 (UTC) or "" if unknown
    snippet: str
    published_dt: datetime | None = field(default=None, repr=False)


def _build_rss_url(query: str) -> str:
    params = {
        "q": query,
        "hl": config.NEWS_HL,
        "gl": config.NEWS_GL,
        "ceid": config.NEWS_CEID,
    }
    return f"{RSS_BASE}?{urllib.parse.urlencode(params)}"


def _strip_html(raw: str) -> str:
    """Google News summaries are HTML fragments; reduce to plain text."""
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_published(entry) -> datetime | None:
    # feedparser exposes a parsed struct_time when it can; fall back to RFC822.
    if getattr(entry, "published_parsed", None):
        try:
            return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass
    if getattr(entry, "published", None):
        try:
            dt = parsedate_to_datetime(entry.published)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (TypeError, ValueError):
            pass
    return None


def _extract_source(entry) -> str:
    src = getattr(entry, "source", None)
    if src and getattr(src, "title", None):
        return src.title
    # Google News titles are often "Headline - Publisher"; use the tail.
    title = getattr(entry, "title", "") or ""
    if " - " in title:
        return title.rsplit(" - ", 1)[-1].strip()
    return ""


def _clean_title(entry) -> str:
    title = (getattr(entry, "title", "") or "").strip()
    source = _extract_source(entry)
    # Trim the trailing " - Publisher" that Google News appends.
    if source and title.endswith(f" - {source}"):
        title = title[: -(len(source) + 3)].strip()
    return title


def _canonical_key(url: str, title: str) -> str:
    """Stable key for dedup: prefer the URL, fall back to a normalized title."""
    if url:
        parsed = urllib.parse.urlsplit(url)
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return re.sub(r"\W+", "", title.lower())


def _load_recent_keys(lookback_days: int) -> set[str]:
    """Read previously-seen article keys from the CSV history for dedup."""
    keys: set[str] = set()
    if not config.CSV_PATH.exists():
        return keys
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    with config.CSV_PATH.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            run_dt = row.get("run_datetime_utc", "")
            try:
                seen_at = datetime.fromisoformat(run_dt)
                if seen_at.tzinfo is None:
                    seen_at = seen_at.replace(tzinfo=timezone.utc)
            except ValueError:
                seen_at = None
            if seen_at is not None and seen_at < cutoff:
                continue
            keys.add(_canonical_key(row.get("url", ""), row.get("title_en", "")))
    return keys


def fetch_articles(limit: int | None = None) -> list[Article]:
    """Return up to ``limit`` recent, deduped international football articles."""
    limit = limit or config.FETCH_LIMIT
    seen_recent = _load_recent_keys(config.DEDUP_LOOKBACK_DAYS)
    seen_this_run: set[str] = set()
    articles: list[Article] = []

    for query in config.NEWS_QUERIES:
        feed = feedparser.parse(_build_rss_url(query))
        for entry in feed.entries:
            url = getattr(entry, "link", "") or ""
            title = _clean_title(entry)
            if not title:
                continue
            key = _canonical_key(url, title)
            if key in seen_recent or key in seen_this_run:
                continue
            seen_this_run.add(key)
            published_dt = _parse_published(entry)
            articles.append(
                Article(
                    title=title,
                    url=url,
                    source=_extract_source(entry),
                    published=published_dt.isoformat() if published_dt else "",
                    snippet=_strip_html(getattr(entry, "summary", "")),
                    published_dt=published_dt,
                )
            )

    # Most recent first; undated items sink to the bottom.
    articles.sort(
        key=lambda a: a.published_dt or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return articles[:limit]


if __name__ == "__main__":
    # Standalone smoke test: print the candidate list.
    for i, art in enumerate(fetch_articles(), 1):
        print(f"{i:2d}. [{art.source}] {art.title}")
        print(f"     {art.published}  {art.url}")
        if art.snippet:
            print(f"     {art.snippet[:140]}")
