"""src/rank_domestic.py — SPEC 6절 국내 클러스터링·랭킹. fixture 12건 → 4/3/2 → 국내 3건 재현."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.rank_domestic import (
    JACCARD_THRESHOLD,
    cluster,
    jaccard,
    rank_domestic,
    similarity_key,
    strip_prefix,
)
from src.schema import KST, Origin, RankedArticle, RawArticle, RawMetrics, SourceKind
from tests.test_collect_naver import parse_fixture_pool

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def pool() -> list[RawArticle]:
    return parse_fixture_pool()


# ─────────────────────────────────────────────────────────────────────────────
# fixture 재현
# ─────────────────────────────────────────────────────────────────────────────


def test_top_reproduces_ranked_domestic_fixture_exactly(pool):
    expected = [RankedArticle.from_dict(d) for d in json.loads((FIXTURES / "ranked_articles_domestic.json").read_text(encoding="utf-8"))]
    got = rank_domestic(pool).top
    assert [r.to_dict() for r in got] == [r.to_dict() for r in expected]


def test_cluster_sizes_4_3_2_and_three_singletons(pool):
    sizes = sorted((len(c) for c in rank_domestic(pool).clusters), reverse=True)
    assert sizes == [4, 3, 2, 1, 1, 1]


def test_singletons_are_not_published(pool):
    result = rank_domestic(pool)
    assert len(result.ranked) == 3                      # 부분 발행: 국내 3 (fixture README)
    assert all(r.evidence.cluster_size >= 2 for r in result.ranked)


def test_measured_similarities_from_spec_6(pool):
    """SPEC 6절 v1.5 근거표: 상한 10/25, 하한 4/32."""
    by_id = {a.article_id: a for a in pool}
    samsung, zdnet, roboworld = by_id["naver:fc1fc8735424"], by_id["naver:d832bfd2a901"], by_id["naver:2c8a1cb18d5d"]
    assert jaccard(samsung.title, zdnet.title) == pytest.approx(10 / 25)
    assert jaccard(samsung.title, roboworld.title) == pytest.approx(4 / 32)
    assert 4 / 32 < JACCARD_THRESHOLD <= 10 / 25


@pytest.mark.parametrize("threshold, sizes", [
    (0.45, [3, 2, 2, 1, 1, 1, 1, 1]),   # SPEC v1.4 값 — 삼성이 쪼개진다 (폐기 근거)
    (0.40, [4, 3, 2, 1, 1, 1]),
    (0.35, [4, 3, 2, 1, 1, 1]),
    (0.13, [4, 3, 2, 1, 1, 1]),
    (0.125, [5, 3, 2, 1, 1]),           # 로보월드가 삼성에 붙는다
])
def test_threshold_sweep_matches_spec_measurement(pool, threshold, sizes):
    assert sorted((len(c) for c in cluster(pool, threshold)), reverse=True) == sizes


# ─────────────────────────────────────────────────────────────────────────────
# 규칙별 단위 검증
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw, expected", [
    ("[단독] 삼성전자, 휴머노이드용 AP 양산 착수", "삼성전자, 휴머노이드용 AP 양산 착수"),
    ("[속보] 현대차그룹, 아틀라스 투입", "현대차그룹, 아틀라스 투입"),
    ("[포토]로보월드 개막", "로보월드 개막"),
    ("[분석] 목록에 없는 접두사", "[분석] 목록에 없는 접두사"),      # 치명적이지 않다 (SPEC 4절)
    ("접두사 없음", "접두사 없음"),
])
def test_strip_prefix(raw, expected):
    assert strip_prefix(raw) == expected


def test_similarity_key_drops_space_punctuation_symbols_but_keeps_letters_digits():
    assert similarity_key("[단독] 삼성전자, 휴머노이드용 AP 양산 착수… \"4배\"·Q9?") == "삼성전자휴머노이드용AP양산착수4배Q9"


def test_jaccard_edge_cases():
    assert jaccard("[단독]", "[속보]") == 1.0        # 둘 다 빈 집합
    assert jaccard("[단독]", "삼성전자") == 0.0       # 한쪽만 빈 집합
    assert jaccard("가", "가") == 1.0                 # 길이 1 → bigram 없음 → 양쪽 빈 집합
    assert jaccard("삼성전자 AP", "삼성전자 AP") == 1.0


T0 = datetime(2026, 8, 10, 9, 0, tzinfo=KST)


def _art(article_id: str, title: str, when: datetime, publisher: str = "P") -> RawArticle:
    return RawArticle(
        article_id=article_id, origin=Origin.DOMESTIC, source=SourceKind.NAVER_NEWS, title=title,
        url=f"https://example.com/{article_id}", publisher=publisher, published_at=when, collected_at=when,
        metrics=RawMetrics(),
    )


def test_prefix_is_stripped_before_similarity():
    # 사건이 다른 두 기사가 접두사를 공유해도 묶이면 안 된다
    a = _art("a", "[속보] 삼성전자 실적 발표", T0)
    b = _art("b", "[속보] 현대차 파업 돌입", T0 + timedelta(hours=1))
    assert jaccard(a.title, b.title) < JACCARD_THRESHOLD
    assert len(cluster([a, b])) == 2


def test_leader_is_earliest_and_members_are_compared_with_leader_only():
    # A~B, B~C 이지만 A~C 는 무관: 연결 요소면 3건이 한 덩어리, 리더 방식이면 C 는 따로 간다
    a = _art("a", "가나다라마바사", T0)
    b = _art("b", "가나다라마바사아자차카", T0 + timedelta(hours=1))
    c = _art("c", "마바사아자차카타파하", T0 + timedelta(hours=2))
    assert jaccard(a.title, b.title) >= JACCARD_THRESHOLD
    assert jaccard(b.title, c.title) >= JACCARD_THRESHOLD
    assert jaccard(a.title, c.title) < JACCARD_THRESHOLD
    got = cluster([c, b, a])                                       # 입력 순서와 무관
    assert [[m.article_id for m in g] for g in got] == [["a", "b"], ["c"]]


def test_tie_on_cluster_size_broken_by_earlier_representative():
    late = [_art("l1", "국내 로봇 산업 전망 세미나", T0 + timedelta(days=2)), _art("l2", "국내 로봇 산업 전망 세미나 개최", T0 + timedelta(days=2, hours=1))]
    early = [_art("e1", "휴머노이드 배터리 규격 표준화", T0), _art("e2", "휴머노이드 배터리 규격 표준화 추진", T0 + timedelta(hours=1))]
    top = rank_domestic(late + early).top
    assert [r.article.article_id for r in top] == ["e1", "l1"]
    assert [r.sort_score for r in top] == [2.0, 2.0]


def test_ranked_article_shape():
    a = _art("a", "[단독] 삼성전자, 휴머노이드용 AP 양산 착수", T0, "전자신문")
    b = _art("b", "삼성전자 휴머노이드 AP 양산 착수… 추론 성능 4배", T0 + timedelta(hours=1), "머니투데이")
    r = rank_domestic([b, a]).top[0]
    assert r.article is a and r.rank == 1
    assert r.display_title == "삼성전자, 휴머노이드용 AP 양산 착수"      # 접두사만 제거, 문장부호는 그대로
    assert r.article.title.startswith("[단독]")                            # 수집 원문 제목은 보존
    assert r.sort_score == 2.0
    assert r.evidence.cluster_article_ids == ("a", "b") and r.evidence.cluster_publishers == ("전자신문", "머니투데이")
    assert r.evidence.representative_reason == "earliest_in_cluster"
    assert r.evidence.normalized_score is None and r.evidence.score_components == {}


def test_overseas_article_is_rejected(pool):
    with pytest.raises(ValueError, match="origin"):
        rank_domestic([replace(pool[0], origin=Origin.OVERSEAS)])
