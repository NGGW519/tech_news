"""URL 정규화 두 종류 (SPEC 4절 "앵커 URL", 6절 "중복 제거").

    비교용 normalize_for_compare : 호스트 소문자화 + www. 제거 + 트래킹 제거 + 후행 슬래시 제거 → extra.normalized_url
    앵커용 anchor_url            : 트래킹 파라미터만 제거. www.·후행 슬래시·대소문자 원본 유지 → extra.anchor_url

트래킹 파라미터 집합 (SPEC 4절 v1.5): `utm_` 접두 전부 + fbclid · gclid · ref · source.
그 외 파라미터는 순서·인코딩 그대로 보존한다 — 기사 식별자를 지우면 링크가 깨진다.
해외 수집기만 쓴다. 국내는 정규화 단계 자체가 없다.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

TRACKING_PREFIXES: tuple[str, ...] = ("utm_",)
TRACKING_KEYS: frozenset[str] = frozenset({"fbclid", "gclid", "ref", "source"})


def is_tracking_param(key: str) -> bool:
    key = key.lower()
    return key in TRACKING_KEYS or key.startswith(TRACKING_PREFIXES)


def strip_tracking_query(query: str) -> str:
    """쿼리 문자열에서 트래킹 파라미터만 뺀다. 재인코딩하지 않는다 (`?5612388` 같은 값 보존)."""
    if not query:
        return ""
    kept = [part for part in query.split("&") if part and not is_tracking_param(part.split("=", 1)[0])]
    return "&".join(kept)


def anchor_url(url: str) -> str:
    """앵커용: 트래킹 파라미터만 제거."""
    parts = urlsplit(url)
    return urlunsplit(parts._replace(query=strip_tracking_query(parts.query)))


def normalize_for_compare(url: str) -> str:
    """비교용: 호스트 소문자화 · www. 제거 · 트래킹 제거 · 후행 슬래시 제거. 앵커에 쓰지 않는다."""
    parts = urlsplit(url)
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/") if parts.path != "/" else ""
    return urlunsplit((parts.scheme.lower(), host, path, strip_tracking_query(parts.query), parts.fragment))
