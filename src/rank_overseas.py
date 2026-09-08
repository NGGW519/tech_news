"""해외 랭킹 — 소스 내 합성 → 소스별 min-max → URL 병합 합산 (SPEC 6절 "해외").

순수 로직이다. 입력은 수집기가 만든 `RawArticle` 목록(해외, 이미 수집 창으로 필터된 상태)이고,
`extra.normalized_url`(비교용 정규화, SPEC 4·6절)이 채워져 있어야 한다.

    1) 소스 내 합성 (로그 스케일)
         hn     = 0.7 * log1p(points) + 0.3 * log1p(comments)
         reddit = log1p(upvotes)
         rss    = 신호 없음 (None)
    2) 소스별 min-max — 분모는 그 주 수집 풀. 풀에 1건뿐이면(분모 0) 1.0
    3) normalized_url 이 같은 항목을 1건으로 병합, 소스별 정규화 점수를 합산 — 상한 없음
       대표 = 게시 시각이 이른 항목
    정렬: 점수 내림차순 → 동점은 게시 시각 이른 순
    신호가 전혀 없는 병합 그룹 → 예비 풀 (normalized_score None, sort_score -1.0, 게시 시각 역순)

수치는 fixture(`ranked_articles_overseas.json`)와 자릿수까지 맞추기 위해 소수 5자리로 반올림한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import log1p

from src.schema import Origin, RankedArticle, RankEvidence, RawArticle, SourceKind

HN_POINTS_WEIGHT = 0.7
HN_COMMENTS_WEIGHT = 0.3
SCORE_DECIMALS = 5
TOP_N = 5                     # SPEC 2절: 해외 5건
RESERVE_SORT_SCORE = -1.0     # SPEC 6절: 예비 풀 sort_score. 어떤 경쟁 항목보다 확실히 뒤


@dataclass(frozen=True)
class OverseasRanking:
    top: tuple[RankedArticle, ...]       # rank 1..top_n. 발행 대상
    competed: tuple[RankedArticle, ...]  # 경쟁한 전원 (top 포함), rank 1..N. 근거 확인·디버깅용
    reserve: tuple[RankedArticle, ...]   # 예비 풀. rank 는 예비 풀 내부 순번 (게시 시각 역순)


# ─────────────────────────────────────────────────────────────────────────────
# 1) 소스 내 합성
# ─────────────────────────────────────────────────────────────────────────────


def raw_score(article: RawArticle) -> float | None:
    """소스 내 원시 점수. 인기도 신호가 없으면 None ("0점" 이 아니다 — SPEC 6절 RawMetrics 원칙)."""
    m = article.metrics
    if article.source is SourceKind.HACKER_NEWS and m.points is not None:
        return HN_POINTS_WEIGHT * log1p(m.points) + HN_COMMENTS_WEIGHT * log1p(m.comments or 0)
    if article.source is SourceKind.REDDIT and m.upvotes is not None:
        return log1p(m.upvotes)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 2) 소스별 min-max
# ─────────────────────────────────────────────────────────────────────────────


def normalize_by_source(articles: list[RawArticle]) -> dict[str, float]:
    """article_id → 소스별 min-max 정규화 점수 (신호 있는 항목만). 분모 0 → 1.0 (SPEC 6절 경계)."""
    by_source: dict[SourceKind, list[tuple[str, float]]] = {}
    for a in articles:
        score = raw_score(a)
        if score is not None:
            by_source.setdefault(a.source, []).append((a.article_id, score))

    normalized: dict[str, float] = {}
    for scored in by_source.values():
        lo = min(s for _, s in scored)
        hi = max(s for _, s in scored)
        span = hi - lo
        for article_id, s in scored:
            normalized[article_id] = 1.0 if span == 0 else (s - lo) / span
    return normalized


# ─────────────────────────────────────────────────────────────────────────────
# 3) URL 병합 · 정렬
# ─────────────────────────────────────────────────────────────────────────────


def merge_key(article: RawArticle) -> str:
    try:
        return article.extra["normalized_url"]
    except KeyError:
        raise ValueError(
            f"{article.article_id}: extra.normalized_url 이 없다. 해외 수집기는 비교용 정규화 URL 을 반드시 채워야 한다 (SPEC 6절)"
        ) from None


def _group_by_url(articles: list[RawArticle]) -> list[list[RawArticle]]:
    groups: dict[str, list[RawArticle]] = {}
    for a in articles:
        groups.setdefault(merge_key(a), []).append(a)
    # 그룹 내부는 게시 시각 오름차순 — [0] 이 대표, merged_article_ids 순서도 이것
    return [sorted(g, key=lambda a: a.published_at) for g in groups.values()]


def _evidence(members: list[RawArticle], normalized: dict[str, float]) -> RankEvidence:
    components: dict[str, float] = {}
    for m in members:
        if m.article_id in normalized:
            key = m.source.value
            components[key] = components.get(key, 0.0) + normalized[m.article_id]
    components = {k: round(v, SCORE_DECIMALS) for k, v in components.items()}
    total = round(sum(components.values()), SCORE_DECIMALS) if components else None
    return RankEvidence(
        origin=Origin.OVERSEAS,
        normalized_score=total,
        score_components=components,
        merged_article_ids=tuple(m.article_id for m in members),
    )


def rank_overseas(articles: list[RawArticle], top_n: int = TOP_N) -> OverseasRanking:
    for a in articles:
        if a.origin is not Origin.OVERSEAS:
            raise ValueError(f"{a.article_id}: 해외 랭킹에 국내 기사가 섞였다 (origin={a.origin.value})")

    normalized = normalize_by_source(articles)
    competing: list[tuple[RawArticle, RankEvidence]] = []
    reserve: list[tuple[RawArticle, RankEvidence]] = []
    for members in _group_by_url(articles):
        ev = _evidence(members, normalized)
        (competing if ev.normalized_score is not None else reserve).append((members[0], ev))

    competing.sort(key=lambda pair: (-pair[1].normalized_score, pair[0].published_at))
    reserve.sort(key=lambda pair: pair[0].published_at, reverse=True)

    competed = tuple(
        RankedArticle(article=a, rank=i, display_title=a.title, sort_score=ev.normalized_score, evidence=ev)
        for i, (a, ev) in enumerate(competing, start=1)
    )
    reserve_ranked = tuple(
        RankedArticle(article=a, rank=i, display_title=a.title, sort_score=RESERVE_SORT_SCORE, evidence=ev)
        for i, (a, ev) in enumerate(reserve, start=1)
    )
    return OverseasRanking(top=competed[:top_n], competed=competed, reserve=reserve_ranked)
