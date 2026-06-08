"""Gemini-powered evaluation and Vietnamese briefing.

Two batched calls per run keep token usage low:
  Stage A — score ALL candidate articles in one call (newsworthiness +
            suitability for Vietnamese football fans).
  Stage B — write a Vietnamese headline + brief for the TOP N only.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from google import genai
from google.genai import types

from . import config
from .fetch_news import Article
from .filters import FilterScore, score_filter


@dataclass
class ScoredArticle:
    article: Article
    newsworthiness: float
    suitability: float
    reason: str
    composite: float = 0.0
    article_type: str = ""
    filter_score: FilterScore | None = None
    combined_score: float = 0.0
    rank: int = 0
    title_vi: str = ""
    brief_vi: str = ""
    briefed: bool = False


# --- Response schemas (force structured JSON) ------------------------------
_ARTICLE_TYPES = [
    "breaking_news", "transfer_news", "match_report", "interview",
    "analysis", "preview", "roundup", "feature", "other",
]

_SCORE_SCHEMA = types.Schema(
    type=types.Type.ARRAY,
    items=types.Schema(
        type=types.Type.OBJECT,
        required=["index", "newsworthiness", "reader_suitability", "reason", "article_type"],
        properties={
            "index": types.Schema(type=types.Type.INTEGER),
            "newsworthiness": types.Schema(type=types.Type.NUMBER),
            "reader_suitability": types.Schema(type=types.Type.NUMBER),
            "reason": types.Schema(type=types.Type.STRING),
            "article_type": types.Schema(
                type=types.Type.STRING,
                enum=_ARTICLE_TYPES,
            ),
        },
    ),
)

_BRIEF_SCHEMA = types.Schema(
    type=types.Type.ARRAY,
    items=types.Schema(
        type=types.Type.OBJECT,
        required=["index", "title_vi", "brief_vi"],
        properties={
            "index": types.Schema(type=types.Type.INTEGER),
            "title_vi": types.Schema(type=types.Type.STRING),
            "brief_vi": types.Schema(type=types.Type.STRING),
        },
    ),
)


def _client() -> genai.Client:
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set")
    return genai.Client(api_key=config.GEMINI_API_KEY)


def _generate(client: genai.Client, prompt: str, schema: types.Schema, retries: int = 3):
    """Call Gemini with a JSON schema, retrying on transient errors."""
    cfg = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=schema,
        temperature=0.3,
    )
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            resp = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=prompt,
                config=cfg,
            )
            return json.loads(resp.text)
        except Exception as err:  # noqa: BLE001 - retry any transient failure
            last_err = err
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Gemini call failed after {retries} attempts: {last_err}")


def _clamp(value: float) -> float:
    try:
        return max(0.0, min(10.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def score_articles(articles: list[Article]) -> list[ScoredArticle]:
    """Stage A: score every article in a single Gemini call."""
    if not articles:
        return []

    payload = [
        {
            "index": i,
            "title": a.title,
            "source": a.source,
            "snippet": a.snippet,
            "published": a.published,
        }
        for i, a in enumerate(articles)
    ]
    prompt = (
        "You are a sports news editor curating news about the 2026 FIFA World Cup "
        "(hosted by the USA, Canada and Mexico) for VIETNAMESE readers.\n"
        "For EACH article below, provide:\n"
        "- newsworthiness (0-10): how significant/breaking/important the story is "
        "FOR THE 2026 WORLD CUP (squads, qualification, draw, fixtures, host cities, "
        "key players, injuries, tickets, controversies).\n"
        "- reader_suitability (0-10): how interesting/relevant for a Vietnamese "
        "audience following the 2026 World Cup (Asian/AFC teams, global stars, "
        "host-nation angles).\n"
        "- article_type: classify as one of: breaking_news, transfer_news, "
        "match_report, interview, analysis, preview, roundup, feature, other.\n"
        "  Use 'roundup' for: squad list compilations across multiple teams, "
        "fixture/schedule guides, 'how to watch' articles, and any evergreen "
        "reference content. Use 'breaking_news' only for a single specific event "
        "that just happened (injury, selection, controversy, result).\n"
        "- reason: one-sentence English explanation.\n"
        "IMPORTANT: If an article is NOT about the 2026 FIFA World Cup, score BOTH "
        "newsworthiness AND reader_suitability between 0 and 2.\n"
        "Return one object per article, echoing its index.\n\n"
        f"ARTICLES (JSON):\n{json.dumps(payload, ensure_ascii=False)}"
    )

    rows = _generate(_client(), prompt, _SCORE_SCHEMA)
    by_index = {int(r["index"]): r for r in rows if "index" in r}

    scored: list[ScoredArticle] = []
    for i, art in enumerate(articles):
        r = by_index.get(i, {})
        news = _clamp(r.get("newsworthiness", 0))
        suit = _clamp(r.get("reader_suitability", 0))
        composite = (
            config.WEIGHT_NEWSWORTHINESS * news + config.WEIGHT_SUITABILITY * suit
        )
        article_type = str(r.get("article_type", "other")).strip()
        fs = score_filter(art.source, article_type, art.title, art.snippet)
        combined = round(
            config.WEIGHT_GEMINI * (composite / 10.0)
            + config.WEIGHT_FILTER * fs.filter_priority,
            4,
        )
        scored.append(
            ScoredArticle(
                article=art,
                newsworthiness=news,
                suitability=suit,
                reason=str(r.get("reason", "")).strip(),
                composite=round(composite, 3),
                article_type=article_type,
                filter_score=fs,
                combined_score=combined,
            )
        )

    scored.sort(key=lambda s: s.combined_score, reverse=True)
    for rank, s in enumerate(scored, 1):
        s.rank = rank
    return scored


def brief_top(scored: list[ScoredArticle], top_n: int | None = None) -> list[ScoredArticle]:
    """Stage B: write Vietnamese title + brief for the top N (in place)."""
    top_n = top_n or config.BRIEF_TOP_N
    top = scored[:top_n]
    if not top:
        return scored

    payload = [
        {
            "index": s.rank,
            "title": s.article.title,
            "source": s.article.source,
            "snippet": s.article.snippet,
        }
        for s in top
    ]
    prompt = (
        "Bạn là biên tập viên thể thao viết tin bóng đá quốc tế cho độc giả "
        "Việt Nam.\n"
        "Với MỖI bài dưới đây, hãy viết:\n"
        "- title_vi: một tiêu đề tiếng Việt ngắn gọn, hấp dẫn.\n"
        "- brief_vi: bản tóm tắt 2-3 câu bằng tiếng Việt tự nhiên.\n"
        "CHỈ dựa trên tiêu đề và đoạn trích được cung cấp; KHÔNG bịa thêm chi "
        "tiết. Trả về một object cho mỗi bài, giữ nguyên 'index'.\n\n"
        f"ARTICLES (JSON):\n{json.dumps(payload, ensure_ascii=False)}"
    )

    rows = _generate(_client(), prompt, _BRIEF_SCHEMA)
    by_index = {int(r["index"]): r for r in rows if "index" in r}

    for s in top:
        r = by_index.get(s.rank, {})
        s.title_vi = str(r.get("title_vi", "")).strip()
        s.brief_vi = str(r.get("brief_vi", "")).strip()
        s.briefed = bool(s.title_vi or s.brief_vi)
    return scored
