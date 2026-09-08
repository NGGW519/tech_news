"""본문 보강 — 해외 상위 5건의 원문을 fetch 해 앞 1500자를 요약 입력으로 (SPEC 6.5절).

    위치     랭킹 이후 · 요약 이전. 해외만. 국내는 태우지 않는다
    동작     앵커용 URL fetch → trafilatura 추출 → 앞 1500자
    타임아웃 5초 · 재시도 없음 · 실패 시 원상태 유지
    실패     HTTP 오류 · 타임아웃 · 추출 None · 추출 텍스트 200자 미만
    산출물   extra.enrich_status ("success"/"failed") · extra.enrich_text (실패 시 키 없음) · extra.enrich_url (= anchor_url)

네트워크(fetch)와 추출기(extract)는 주입 가능하다. 기본 구현만 실제 사이트와 trafilatura 를 쓴다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace

from src.http import get_text
from src.schema import Origin, RankedArticle, RawArticle

log = logging.getLogger(__name__)

ENRICH_TIMEOUT = 5.0
MAX_CHARS = 1500
MIN_CHARS = 200          # 이보다 짧으면 쿠키 배너·JS 안내문일 가능성이 커 실패로 본다 (SPEC 6.5절)
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"

Fetch = Callable[[str], str]
Extract = Callable[[str], str | None]


def fetch_html(url: str) -> str:
    return get_text(url, timeout=ENRICH_TIMEOUT)


def extract_text(html: str) -> str | None:
    import trafilatura  # 무거운 import 는 실제로 쓸 때만

    return trafilatura.extract(html, include_comments=False, include_tables=False)


def enrich_article(article: RawArticle, *, fetch: Fetch = fetch_html, extract: Extract = extract_text) -> RawArticle:
    """RawArticle 하나를 보강한 사본. 실패해도 예외를 밖으로 내지 않는다 — 파이프라인이 멈추면 안 된다."""
    if article.origin is not Origin.OVERSEAS:
        raise ValueError(f"{article.article_id}: 본문 보강은 해외에만 붙는다 (SPEC 6.5절)")
    url = article.extra.get("anchor_url") or article.url
    extra = {**article.extra, "enrich_url": url}
    try:
        text = extract(fetch(url))
    except Exception as e:  # noqa: BLE001 — 어떤 실패든 "원상태 유지"
        log.warning("enrich failed %s %s: %s", article.article_id, url, e)
        text = None
    text = (text or "").strip()
    if len(text) < MIN_CHARS:
        if text:
            log.warning("enrich too short %s (%d자) → failed", article.article_id, len(text))
        extra["enrich_status"] = STATUS_FAILED
    else:
        extra["enrich_status"] = STATUS_SUCCESS
        extra["enrich_text"] = text[:MAX_CHARS]
    return replace(article, extra=extra)


def enrich_ranked(ranked: list[RankedArticle], *, fetch: Fetch = fetch_html, extract: Extract = extract_text) -> list[RankedArticle]:
    """해외 상위 N 건 전부 보강. RankedArticle 의 다른 필드는 그대로."""
    return [replace(r, article=enrich_article(r.article, fetch=fetch, extract=extract)) for r in ranked]
