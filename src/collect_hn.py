"""해외 수집 — Hacker News (Algolia API) (SPEC 6절 "해외").

    GET https://hn.algolia.com/api/v1/search_by_date
        tags=story · query=<키워드> · numericFilters=created_at_i>{창 시작},created_at_i<{창 끝}
        hitsPerPage=100 · page=0..nbPages-1

`search_by_date` 다 — `search`(관련도순)는 기간 필터가 사실상 무력하다. `tags=story` 로 댓글을 뺀다.
키워드 없이 전체 스토리를 받으면 주제와 무관한 글이 풀을 채우므로, 국내(네이버)와 같은 방식으로
키워드별로 호출하고 objectID 로 키워드 간 중복을 제거한다.

순수: parse_hits · 네트워크: fetch_query / collect_hn (get_json 주입 가능)
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any

from src.http import get_json
from src.publishers import publisher_name
from src.schema import KST, Origin, RawArticle, RawMetrics, SourceKind, WeekMeta, ensure_kst, now_kst
from src.text import clean_html
from src.urls import anchor_url, normalize_for_compare

HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
HN_ITEM_URL = "https://news.ycombinator.com/item?id={id}"
DEFAULT_QUERIES: tuple[str, ...] = ("robot", "robotics", "humanoid", "physical AI", "autonomous driving")
#: Algolia 는 오타 허용·접두 매칭으로 "robot"→"root", "humanoid"→"Humanitas" 를 돌려준다 (실측 2026-09-08).
#: 그래서 제목에 이 단어 중 하나가 **실제로** 들어 있는 글만 남긴다. 소문자 부분 문자열 매칭이며
#: "robot" 이 robotics/robots 를 덮는다. 짧은 단어(ros 등)는 오탐이 커 넣지 않는다.
TITLE_KEYWORDS: tuple[str, ...] = (
    "robot", "humanoid", "physical ai", "embodied", "autonomous driving", "self-driving", "autonomous vehicle",
)
HITS_PER_PAGE = 100
MAX_PAGES = 10          # Algolia 상한 1000건

GetJson = Callable[..., Any]


def title_matches(title: str, keywords: Iterable[str] = TITLE_KEYWORDS) -> bool:
    lowered = title.lower()
    return any(k in lowered for k in keywords)


def parse_hit(hit: dict[str, Any], query: str, collected_at: datetime) -> RawArticle:
    object_id = str(hit["objectID"])
    item_url = HN_ITEM_URL.format(id=object_id)
    url = hit.get("url") or item_url                     # Ask HN 류는 외부 URL 이 없다 → HN 글 자체
    anchor = anchor_url(url)
    return RawArticle(
        article_id=f"hn:{object_id}",
        origin=Origin.OVERSEAS,
        source=SourceKind.HACKER_NEWS,
        title=clean_html(hit.get("title")),
        url=url,
        publisher=publisher_name(anchor),
        published_at=datetime.fromtimestamp(int(hit["created_at_i"]), tz=timezone.utc).astimezone(KST),
        collected_at=ensure_kst(collected_at),
        metrics=RawMetrics(points=hit.get("points"), comments=hit.get("num_comments")),
        description=clean_html(hit.get("story_text")),    # 링크 글은 null → ""
        query=query,
        extra={
            "hn_author": hit.get("author"),
            "hn_item_url": item_url,
            "created_at_i": int(hit["created_at_i"]),
            "normalized_url": normalize_for_compare(url),
            "anchor_url": anchor,
        },
    )


def parse_hits(payload: dict[str, Any], query: str, collected_at: datetime) -> list[RawArticle]:
    return [parse_hit(h, query, collected_at) for h in payload.get("hits", []) if h.get("title")]


def fetch_query(query: str, week: WeekMeta, *, get_json: GetJson = get_json,
                collected_at: datetime | None = None) -> list[RawArticle]:
    stamp = collected_at or now_kst()
    start = int(week.window_start_dt.timestamp())
    end = int(week.window_end_dt.timestamp())
    kept: list[RawArticle] = []
    for page in range(MAX_PAGES):
        payload = get_json(HN_SEARCH_URL, {
            "query": query, "tags": "story",
            "numericFilters": f"created_at_i>{start},created_at_i<{end}",
            "restrictSearchableAttributes": "title",
            "hitsPerPage": str(HITS_PER_PAGE), "page": str(page),
        })
        kept.extend(a for a in parse_hits(payload, query, stamp)
                    if week.contains(a.published_at) and title_matches(a.title))
        if page + 1 >= int(payload.get("nbPages", 1)):
            break
    return kept


def dedupe(articles: Iterable[RawArticle]) -> list[RawArticle]:
    seen: dict[str, RawArticle] = {}
    for a in articles:
        seen.setdefault(a.article_id, a)
    return list(seen.values())


def collect_hn(week: WeekMeta, *, queries: Iterable[str] = DEFAULT_QUERIES, get_json: GetJson = get_json,
               collected_at: datetime | None = None) -> list[RawArticle]:
    stamp = collected_at or now_kst()
    return dedupe(a for q in queries for a in fetch_query(q, week, get_json=get_json, collected_at=stamp))
