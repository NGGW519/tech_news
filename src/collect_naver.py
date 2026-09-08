"""국내 수집 — 네이버 검색 API (news) (SPEC 6절 "국내").

네트워크 호출부와 순수 로직을 나눈다 (SPEC 3절 유의점 4).

    순수:     clean_text · article_id_for · parse_response · merge_across_queries
    네트워크: urllib_get (기본 HTTP 구현) — collect_domestic 에 다른 http_get 을 주입하면 fixture 로 검증 가능

호출 파라미터 (SPEC 6절): sort=date, display=100, start 를 100 씩 올리며 수집 창을 벗어날 때까지.
HTML 태그·엔티티 제거는 여기서 즉시 수행한다 — RawArticle.title / description 은 정제된 상태다.
접두사([단독] 등)는 여기서 제거하지 않는다 (랭킹 진입 후, SPEC 4·6절).
"""

from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

from src.publishers import publisher_name
from src.schema import Origin, RawArticle, RawMetrics, SourceKind, WeekMeta, ensure_kst, now_kst
from src.text import clean_html

NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"
DEFAULT_QUERIES: tuple[str, ...] = ("피지컬 AI", "휴머노이드", "자율주행", "로봇", "ROS")  # SPEC 6절, 운영하며 조정
DISPLAY = 100        # 호출당 상한
MAX_START = 1000     # API 의 start 상한 (SPEC 11절 확인 대상). 닿으면 그 키워드는 거기서 멈춘다
HTTP_TIMEOUT = 10

HttpGet = Callable[[str, dict[str, str], dict[str, str]], dict[str, Any]]

# ─────────────────────────────────────────────────────────────────────────────
# 순수 로직
# ─────────────────────────────────────────────────────────────────────────────

# `<b>` 등 태그 제거 → HTML 엔티티 해제 → 양끝 공백 제거. 접두사는 손대지 않는다 (src/text.py 공용)
clean_text = clean_html


def article_id_for(originallink: str) -> str:
    """SPEC 6절 규약: naver:<sha1(originallink) 앞 12자>. URL 문자열 그대로 해시한다."""
    return "naver:" + hashlib.sha1(originallink.encode("utf-8")).hexdigest()[:12]


def parse_item(item: dict[str, Any], query: str, collected_at: datetime) -> RawArticle:
    """네이버 응답의 items[i] 하나 → RawArticle. originallink 가 없으면 link 를 쓴다."""
    link = item.get("originallink") or item["link"]
    return RawArticle(
        article_id=article_id_for(link),
        origin=Origin.DOMESTIC,
        source=SourceKind.NAVER_NEWS,
        title=clean_text(item["title"]),
        url=link,
        publisher=publisher_name(link),
        published_at=ensure_kst(parsedate_to_datetime(item["pubDate"])),
        collected_at=ensure_kst(collected_at),
        metrics=RawMetrics(),                       # 국내는 인기도 신호 없음 — 전부 None
        description=clean_text(item.get("description", "")),
        query=query,
        extra={
            "naver_link": item.get("link", ""),
            "matched_queries": [query],
            "raw_title": item["title"],
        },
    )


def parse_response(payload: dict[str, Any], query: str, collected_at: datetime) -> list[RawArticle]:
    return [parse_item(item, query, collected_at) for item in payload.get("items", [])]


def merge_across_queries(articles: Iterable[RawArticle]) -> list[RawArticle]:
    """키워드 간 중복을 article_id 로 제거한다. 먼저 본 것을 남기고 matched_queries 만 누적한다."""
    merged: dict[str, RawArticle] = {}
    for a in articles:
        seen = merged.get(a.article_id)
        if seen is None:
            merged[a.article_id] = a
            continue
        queries = list(seen.extra.get("matched_queries", []))
        for q in a.extra.get("matched_queries", []):
            if q not in queries:
                queries.append(q)
        merged[a.article_id] = RawArticle(
            **{**seen.__dict__, "extra": {**seen.extra, "matched_queries": queries}}
        )
    return list(merged.values())


# ─────────────────────────────────────────────────────────────────────────────
# 네트워크 호출부
# ─────────────────────────────────────────────────────────────────────────────


def urllib_get(url: str, params: dict[str, str], headers: dict[str, str]) -> dict[str, Any]:
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers=headers)
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_query(
    query: str,
    week: WeekMeta,
    *,
    client_id: str,
    client_secret: str,
    http_get: HttpGet = urllib_get,
    collected_at: datetime | None = None,
) -> list[RawArticle]:
    """키워드 하나를 수집 창이 끝날 때까지 페이지네이션한다.

    sort=date 라 응답이 최신순이므로:
      - 창 뒤쪽(실행일 이후) 항목은 버리고 계속 본다
      - 창 앞쪽(window_start 이전) 항목을 만나면 그 키워드는 끝
    """
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    stamp = collected_at or now_kst()
    kept: list[RawArticle] = []
    start = 1
    while start <= MAX_START:
        payload = http_get(
            NAVER_NEWS_URL,
            {"query": query, "sort": "date", "display": str(DISPLAY), "start": str(start)},
            headers,
        )
        page = parse_response(payload, query, stamp)
        for article in page:
            if article.published_at > week.window_end_dt:
                continue                              # 창 뒤 — 버림
            if article.published_at < week.window_start_dt:
                return kept                           # 창 앞 — 이 키워드 종료
            kept.append(article)
        if len(page) < DISPLAY:
            break                                     # 마지막 페이지
        start += DISPLAY
    return kept


def collect_domestic(
    week: WeekMeta,
    *,
    client_id: str,
    client_secret: str,
    queries: Iterable[str] = DEFAULT_QUERIES,
    http_get: HttpGet = urllib_get,
    collected_at: datetime | None = None,
) -> list[RawArticle]:
    """키워드 전부 수집 → 키워드 간 중복 제거. 결과는 아직 접두사 제거·클러스터링 전이다."""
    pooled: list[RawArticle] = []
    for query in queries:
        pooled.extend(fetch_query(
            query, week, client_id=client_id, client_secret=client_secret,
            http_get=http_get, collected_at=collected_at,
        ))
    return merge_across_queries(pooled)
