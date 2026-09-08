"""국내 수집 — 네이버 검색 API (news), NAVER API HUB 경유 (SPEC 6절 "국내").

네트워크 호출부와 순수 로직을 나눈다 (SPEC 3절 유의점 4).

    순수:     clean_text · article_id_for · parse_response · merge_across_queries
    네트워크: urllib_get (기본 HTTP 구현) — collect_domestic 에 다른 http_get 을 주입하면 fixture 로 검증 가능

호출 파라미터 (SPEC 6절): sort=date, display=100, start 를 100 씩 올리며 수집 창을 벗어날 때까지.
HTML 태그·엔티티 제거는 여기서 즉시 수행한다 — RawArticle.title / description 은 정제된 상태다.
접두사([단독] 등)는 여기서 제거하지 않는다 (랭킹 진입 후, SPEC 4·6절).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

from src import http
from src.publishers import publisher_name
from src.schema import Origin, RawArticle, RawMetrics, SourceKind, WeekMeta, ensure_kst, now_kst
from src.text import clean_html

#: NAVER API HUB (NAVER Cloud Platform). 개발자센터(openapi.naver.com)의 검색 API 는 2026-07-31 부터 신규 신청이
#: 막혔고 2027-06-30 지원 종료라 처음부터 API HUB 를 쓴다. 응답 JSON 형식은 개발자센터와 같다 (이관 가이드, 2026-09-08 확인).
NAVER_NEWS_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"
HEADER_CLIENT_ID = "X-NCP-APIGW-API-KEY-ID"      # 구 X-Naver-Client-Id
HEADER_CLIENT_SECRET = "X-NCP-APIGW-API-KEY"     # 구 X-Naver-Client-Secret
#: SPEC 6절, 운영하며 조정. "ROS" 는 뺐다 — 라그나로크 온라인 e스포츠(ROS 2026)가 상위에 올라왔고(실측 2026-09-08),
#: 로봇 운영체제 기사는 "로봇" 키워드가 이미 덮는다.
DEFAULT_QUERIES: tuple[str, ...] = ("피지컬 AI", "휴머노이드", "자율주행", "로봇")
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


# 응답 본문의 errorCode / HTTP 상태 → 사람이 할 일
_NAVER_HINTS = {
    '"024"': "인증 실패 — NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 이 API HUB 의 Client ID / Client Secret 인지, "
             "Application 에 '검색' API 가 선택돼 있는지 확인 (개발자센터 키는 이 엔드포인트에서 안 통한다)",
    '"200"': "인증 헤더 누락/오류 (API Gateway) — 헤더 이름은 X-NCP-APIGW-API-KEY-ID / X-NCP-APIGW-API-KEY",
    '"210"': "API Gateway: 허용되지 않은 키 — Application 에 이 API 가 포함돼 있지 않다",
    '"SE05"': "존재하지 않는 검색 API — Application 의 API 목록에 '검색' 을 추가",
    '"SE03"': "start 값 범위 초과 (1~1000)",
    '"SE02"': "display 값 범위 초과 (1~100)",
}
_STATUS_HINTS = {
    401: "인증 실패 — 키가 API HUB 것인지 확인 (Application > Client ID / Client Secret)",
    403: "권한 없음 — Application 에 '검색' API 가 선택돼 있지 않거나 승인 전",
    429: "호출 한도 초과 — API HUB 검색 API 는 월 775,000건 · 50 RPS",
}


def urllib_get(url: str, params: dict[str, str], headers: dict[str, str]) -> dict[str, Any]:
    try:
        return http.get_json(url, params, headers, HTTP_TIMEOUT)
    except http.HttpError as e:
        hint = next((h for code, h in _NAVER_HINTS.items() if code in e.body), _STATUS_HINTS.get(e.status, ""))
        raise RuntimeError(f"네이버 API HUB HTTP {e.status}: {e.body[:200]}" + (f"\n→ {hint}" if hint else "")) from None


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
    headers = {HEADER_CLIENT_ID: client_id, HEADER_CLIENT_SECRET: client_secret}
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
