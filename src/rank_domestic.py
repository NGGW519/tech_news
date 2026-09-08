"""국내 랭킹 — 접두사 제거 → 문자 bigram 자카드 → 그리디 리더 군집 → 클러스터 크기 순 (SPEC 6절 "국내").

순수 로직이다. 입력은 수집기가 만든 `RawArticle` 목록(국내, 키워드 간 중복 제거 완료).

    처리 순서 (고정): 랭킹 진입 → 접두사 제거 → bigram 자카드 클러스터링 → display_title 확정
    유사도:   접두사 제거 → 공백·문장부호·기호 제거 → 문자 bigram 집합 → |A∩B| / |A∪B|
    군집:     published_at 오름차순, 미할당 첫 기사를 리더로, 이후 기사를 **리더와만** 비교해 편입
    정렬:     cluster_size 내림차순 → 대표(published_at) 이른 순
    발행:     cluster_size >= MIN_CLUSTER_SIZE 인 클러스터만. 혼자 보도된 기사는 "커버리지" 신호가 없다

임계값 0.35 는 fixture 실측 구간 (0.125, 0.40] 의 중앙값이며 운영 중 튜닝 대상이다 (SPEC 6절 v1.5).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from src.schema import Origin, RankedArticle, RankEvidence, RawArticle

# SPEC 4절. 초안이며 운영하며 추가한다
TITLE_PREFIX = re.compile(r"^\[(단독|속보|종합|영상|포토|사진|인터뷰|기획)\]\s*")

JACCARD_THRESHOLD = 0.35   # SPEC 6절 v1.5 — 운영 중 튜닝 대상
TOP_N = 5                  # SPEC 2절: 국내 5건
MIN_CLUSTER_SIZE = 2       # 1건짜리 클러스터는 발행하지 않는다 (fixture: 6 클러스터 중 3건 발행)
REPRESENTATIVE_REASON = "earliest_in_cluster"


@dataclass(frozen=True)
class DomesticRanking:
    top: tuple[RankedArticle, ...]        # rank 1..top_n. 발행 대상 (MIN_CLUSTER_SIZE 이상만)
    ranked: tuple[RankedArticle, ...]     # 발행 자격이 있는 전 클러스터, rank 1..N
    clusters: tuple[tuple[RawArticle, ...], ...]  # 형성된 모든 클러스터 (1건짜리 포함). 각 튜플의 [0] 이 리더


# ─────────────────────────────────────────────────────────────────────────────
# 제목 전처리 · 유사도
# ─────────────────────────────────────────────────────────────────────────────


def strip_prefix(title: str) -> str:
    """`[단독]` 류 접두사 제거. 이 결과가 그대로 display_title 이 된다 (SPEC 4절)."""
    return TITLE_PREFIX.sub("", title).strip()


def similarity_key(title: str) -> str:
    """접두사 제거 → 공백(Z*)·구두점(P*)·기호(S*) 제거. 유사도 계산에만 쓰고 저장하지 않는다."""
    return "".join(
        ch for ch in strip_prefix(title)
        if not ch.isspace() and unicodedata.category(ch)[0] not in "PSZ"
    )


def bigrams(text: str) -> frozenset[str]:
    return frozenset(text[i : i + 2] for i in range(len(text) - 1))


def jaccard(title_a: str, title_b: str) -> float:
    a, b = bigrams(similarity_key(title_a)), bigrams(similarity_key(title_b))
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ─────────────────────────────────────────────────────────────────────────────
# 군집 · 랭킹
# ─────────────────────────────────────────────────────────────────────────────


def cluster(articles: list[RawArticle], threshold: float = JACCARD_THRESHOLD) -> list[list[RawArticle]]:
    """그리디 리더. 반환된 각 클러스터는 published_at 오름차순이며 [0] 이 리더(= 최초 보도)."""
    ordered = sorted(articles, key=lambda a: a.published_at)
    assigned: set[str] = set()
    clusters: list[list[RawArticle]] = []
    for leader in ordered:
        if leader.article_id in assigned:
            continue
        assigned.add(leader.article_id)
        members = [leader]
        for candidate in ordered:
            if candidate.article_id in assigned:
                continue
            if jaccard(leader.title, candidate.title) >= threshold:
                assigned.add(candidate.article_id)
                members.append(candidate)
        clusters.append(members)
    return clusters


def _ranked_article(members: list[RawArticle], rank: int) -> RankedArticle:
    leader = members[0]
    return RankedArticle(
        article=leader,
        rank=rank,
        display_title=strip_prefix(leader.title),
        sort_score=float(len(members)),
        evidence=RankEvidence(
            origin=Origin.DOMESTIC,
            cluster_size=len(members),
            cluster_article_ids=tuple(m.article_id for m in members),
            cluster_publishers=tuple(m.publisher for m in members),
            representative_reason=REPRESENTATIVE_REASON,
        ),
    )


def rank_domestic(
    articles: list[RawArticle],
    top_n: int = TOP_N,
    threshold: float = JACCARD_THRESHOLD,
    min_cluster_size: int = MIN_CLUSTER_SIZE,
) -> DomesticRanking:
    for a in articles:
        if a.origin is not Origin.DOMESTIC:
            raise ValueError(f"{a.article_id}: 국내 랭킹에 해외 기사가 섞였다 (origin={a.origin.value})")

    clusters = cluster(articles, threshold)
    eligible = [c for c in clusters if len(c) >= min_cluster_size]
    eligible.sort(key=lambda c: (-len(c), c[0].published_at))
    ranked = tuple(_ranked_article(c, i) for i, c in enumerate(eligible, start=1))
    return DomesticRanking(
        top=ranked[:top_n],
        ranked=ranked,
        clusters=tuple(tuple(c) for c in clusters),
    )
