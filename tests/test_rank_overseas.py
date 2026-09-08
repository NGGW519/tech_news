"""src/rank_overseas.py — SPEC 6절 해외 랭킹. fixture 12건 → 상위 5 · 예비 풀 1 을 자릿수까지 재현."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.rank_overseas import (
    RESERVE_SORT_SCORE,
    normalize_by_source,
    rank_overseas,
    raw_score,
)
from src.schema import KST, Origin, RankedArticle, RawArticle, RawMetrics, SourceKind

FIXTURES = Path(__file__).parent / "fixtures"


def _load_raw(name: str) -> list[RawArticle]:
    return [RawArticle.from_dict(d) for d in json.loads((FIXTURES / name).read_text(encoding="utf-8"))]


def _load_ranked(name: str) -> list[RankedArticle]:
    return [RankedArticle.from_dict(d) for d in json.loads((FIXTURES / name).read_text(encoding="utf-8"))]


@pytest.fixture(scope="module")
def pool() -> list[RawArticle]:
    return _load_raw("raw_articles_overseas.json")


# ─────────────────────────────────────────────────────────────────────────────
# fixture 재현 — 이것이 이 모듈의 기준 테스트다
# ─────────────────────────────────────────────────────────────────────────────


def test_top5_reproduces_fixture_exactly(pool):
    expected = _load_ranked("ranked_articles_overseas.json")
    got = rank_overseas(pool).top
    assert [r.to_dict() for r in got] == [r.to_dict() for r in expected]


def test_reserve_reproduces_fixture_exactly(pool):
    expected = _load_ranked("ranked_articles_overseas_reserve.json")
    got = rank_overseas(pool).reserve
    assert [r.to_dict() for r in got] == [r.to_dict() for r in expected]


def test_cut_items_match_readme_calculation_table(pool):
    """fixtures/README '해외 랭킹 — 계산 근거' 표의 6~9위 (fixture 파일에는 없는 컷 항목)."""
    competed = rank_overseas(pool).competed
    assert len(competed) == 9
    tail = [(r.rank, r.article.article_id, r.sort_score, r.evidence.merged_article_ids) for r in competed[5:]]
    assert tail == [
        (6, "reddit:1mpz8vr", 0.36721, ("reddit:1mpz8vr",)),
        (7, "hn:41248903", 0.32950, ("hn:41248903",)),
        (8, "rss:deepmind:gemini-robotics-1-5", 0.0, ("rss:deepmind:gemini-robotics-1-5", "hn:41244517")),
        (9, "reddit:1mr7t2c", 0.0, ("reddit:1mr7t2c",)),
    ]


def test_source_minmax_matches_readme_table(pool):
    n = normalize_by_source(pool)
    rounded = {k: round(v, 5) for k, v in n.items()}
    assert rounded == {
        "hn:41240355": 1.0, "hn:41236780": 0.91907, "hn:41253117": 0.8837,
        "hn:41248903": 0.3295, "hn:41244517": 0.0,
        "reddit:1mqk4pz": 1.0, "reddit:1mr2h8k": 0.74125, "reddit:1mq0a4b": 0.47493,
        "reddit:1mpz8vr": 0.36721, "reddit:1mr7t2c": 0.0,
    }
    assert "rss:arxiv:2608.05119" not in n and "rss:deepmind:gemini-robotics-1-5" not in n


# ─────────────────────────────────────────────────────────────────────────────
# 규칙별 단위 검증
# ─────────────────────────────────────────────────────────────────────────────


def _article(article_id, source, *, points=None, comments=None, upvotes=None, url, published, title="t"):
    return RawArticle(
        article_id=article_id, origin=Origin.OVERSEAS, source=source, title=title, url=url,
        publisher="P", published_at=published, collected_at=published,
        metrics=RawMetrics(points=points, comments=comments, upvotes=upvotes),
        extra={"normalized_url": url, "anchor_url": url},
    )


T0 = datetime(2026, 8, 10, 9, 0, tzinfo=KST)


def test_raw_score_formulas():
    hn = _article("hn:1", SourceKind.HACKER_NEWS, points=100, comments=10, url="u", published=T0)
    rd = _article("reddit:1", SourceKind.REDDIT, upvotes=50, comments=5, url="v", published=T0)
    rss = _article("rss:x:y", SourceKind.RSS, url="w", published=T0)
    assert raw_score(hn) == pytest.approx(0.7 * __import__("math").log1p(100) + 0.3 * __import__("math").log1p(10))
    assert raw_score(rd) == pytest.approx(__import__("math").log1p(50))
    assert raw_score(rss) is None


def test_single_item_pool_gets_1_0_not_division_by_zero():
    # SPEC 6절 경계: 소스 풀에 1건뿐 → 분모 0 → 1.0
    only = _article("hn:1", SourceKind.HACKER_NEWS, points=10, comments=1, url="a", published=T0)
    assert normalize_by_source([only]) == {"hn:1": 1.0}
    top = rank_overseas([only]).top
    assert top[0].sort_score == 1.0 and top[0].evidence.score_components == {"hacker_news": 1.0}


def test_tie_broken_by_earlier_published_at():
    # 각 소스 1위는 항상 1.0 → HN 1위 vs Reddit 1위 동점은 상시 발생 (SPEC 6절)
    later = _article("hn:1", SourceKind.HACKER_NEWS, points=10, comments=1, url="a", published=T0 + timedelta(hours=5))
    earlier = _article("reddit:1", SourceKind.REDDIT, upvotes=10, url="b", published=T0)
    top = rank_overseas([later, earlier]).top
    assert [r.article.article_id for r in top] == ["reddit:1", "hn:1"]
    assert top[0].sort_score == top[1].sort_score == 1.0


def test_merge_sums_across_sources_and_picks_earliest_as_representative():
    hn = _article("hn:1", SourceKind.HACKER_NEWS, points=10, comments=1, url="same", published=T0 + timedelta(hours=1))
    rd = _article("reddit:1", SourceKind.REDDIT, upvotes=10, url="same", published=T0)
    other = _article("reddit:2", SourceKind.REDDIT, upvotes=1, url="other", published=T0)
    top = rank_overseas([hn, rd, other]).top
    lead = top[0]
    assert lead.article.article_id == "reddit:1"                       # 이른 쪽이 대표
    assert lead.evidence.merged_article_ids == ("reddit:1", "hn:1")   # 게시 시각 오름차순
    assert lead.sort_score == 2.0                                      # 1.0 + 1.0, 상한 없음
    assert lead.evidence.score_components == {"reddit": 1.0, "hacker_news": 1.0}


def test_rss_merged_with_scored_platform_competes_instead_of_reserve():
    rss = _article("rss:blog:p", SourceKind.RSS, url="same", published=T0)
    hn = _article("hn:1", SourceKind.HACKER_NEWS, points=10, comments=1, url="same", published=T0 + timedelta(hours=1))
    lone_rss = _article("rss:blog:q", SourceKind.RSS, url="alone", published=T0)
    result = rank_overseas([rss, hn, lone_rss])
    assert [r.article.article_id for r in result.top] == ["rss:blog:p"]   # RSS 가 대표지만 HN 점수로 경쟁
    assert [r.article.article_id for r in result.reserve] == ["rss:blog:q"]


def test_reserve_ordering_newest_first_and_score_representation():
    a = _article("rss:x:a", SourceKind.RSS, url="a", published=T0)
    b = _article("rss:x:b", SourceKind.RSS, url="b", published=T0 + timedelta(days=1))
    reserve = rank_overseas([a, b]).reserve
    assert [(r.rank, r.article.article_id) for r in reserve] == [(1, "rss:x:b"), (2, "rss:x:a")]
    for r in reserve:
        assert r.sort_score == RESERVE_SORT_SCORE
        assert r.evidence.normalized_score is None          # 0.0 이 아니다 (SPEC 6절)
        assert r.evidence.score_components == {}
        assert r.evidence.merged_article_ids == (r.article.article_id,)


def test_top_n_cuts_but_competed_keeps_everyone(pool):
    result = rank_overseas(pool, top_n=3)
    assert len(result.top) == 3 and len(result.competed) == 9
    assert [r.rank for r in result.competed] == list(range(1, 10))


def test_missing_normalized_url_is_a_contract_violation(pool):
    broken = replace(pool[0], extra={k: v for k, v in pool[0].extra.items() if k != "normalized_url"})
    with pytest.raises(ValueError, match="normalized_url"):
        rank_overseas([broken])


def test_domestic_article_is_rejected(pool):
    wrong = replace(pool[0], origin=Origin.DOMESTIC)
    with pytest.raises(ValueError, match="origin"):
        rank_overseas([wrong])
