"""Tier-based filtering framework for news articles.

Three scoring dimensions:
  source_tier   — publisher quality/prestige (BBC/Guardian = T1)
  type_tier     — article format urgency (breaking_news = T1)
  keyword_tier  — topic hotness (Messi/Ronaldo/Man Utd = T1)

filter_priority = weighted sum of per-dimension scores, each on 0–1.
  Tier 1 → 1.0, Tier 2 → 0.5, Tier 3 → 0.33…, unmatched → 0.0
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import config


@dataclass
class FilterScore:
    source_tier: int | None
    type_tier: int | None
    keyword_tier: int | None        # best (lowest number) tier among matches
    top_keywords: list[str]         # matched keywords, best-tier first
    filter_priority: float          # 0.0–1.0 composite
    tags: list[str]                 # human-readable labels e.g. ["src:T1", "kw:Messi(T1)"]


def _tier_for(name: str, tier_map: dict[int, list[str]]) -> int | None:
    """Return the tier for `name` via case-insensitive substring match."""
    name_lower = name.lower()
    for tier in sorted(tier_map):
        for entry in tier_map[tier]:
            if entry.lower() in name_lower or name_lower in entry.lower():
                return tier
    return None


def _keyword_matches(text: str, tier_map: dict[int, list[str]]) -> list[tuple[str, int]]:
    """Return all (keyword, tier) pairs found in `text`, best tier first."""
    text_lower = text.lower()
    matches: list[tuple[str, int]] = []
    seen: set[str] = set()
    for tier in sorted(tier_map):
        for kw in tier_map[tier]:
            kw_lower = kw.lower()
            if kw_lower in text_lower and kw_lower not in seen:
                matches.append((kw, tier))
                seen.add(kw_lower)
    return matches


def _tier_score(tier: int | None) -> float:
    """Tier → 0–1 score.  T1=1.0, T2=0.5, T3=0.33…, None=0.0"""
    return 0.0 if tier is None else 1.0 / tier


def score_filter(
    source: str,
    article_type: str,
    title: str,
    snippet: str,
) -> FilterScore:
    source_tier = _tier_for(source, config.SOURCE_TIERS)
    type_tier   = _tier_for(article_type, config.ARTICLE_TYPE_TIERS)

    kw_matches  = _keyword_matches(f"{title} {snippet}", config.KEYWORD_TIERS)
    kw_tier     = kw_matches[0][1] if kw_matches else None
    top_kws     = [kw for kw, _ in kw_matches[:5]]

    priority = round(
        _tier_score(source_tier)  * config.FILTER_WEIGHT_SOURCE
        + _tier_score(type_tier)  * config.FILTER_WEIGHT_TYPE
        + _tier_score(kw_tier)    * config.FILTER_WEIGHT_KEYWORD,
        4,
    )

    tags: list[str] = []
    if source_tier:
        tags.append(f"src:T{source_tier}")
    if type_tier:
        tags.append(f"type:T{type_tier}")
    for kw, t in kw_matches[:3]:
        tags.append(f"kw:{kw}(T{t})")

    return FilterScore(
        source_tier=source_tier,
        type_tier=type_tier,
        keyword_tier=kw_tier,
        top_keywords=top_kws,
        filter_priority=priority,
        tags=tags,
    )
