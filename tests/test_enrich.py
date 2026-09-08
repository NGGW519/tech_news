"""src/enrich.py — SPEC 6.5절. ranked_articles_overseas → enriched_articles_overseas 를 가짜 fetch/추출기로 재현."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.enrich import MAX_CHARS, MIN_CHARS, enrich_article, enrich_ranked
from src.schema import Origin, RankedArticle

FIXTURES = Path(__file__).parent / "fixtures"


def _ranked(name: str) -> list[RankedArticle]:
    return [RankedArticle.from_dict(d) for d in json.loads((FIXTURES / name).read_text(encoding="utf-8"))]


@pytest.fixture(scope="module")
def before():
    return _ranked("ranked_articles_overseas.json")


@pytest.fixture(scope="module")
def after():
    return _ranked("enriched_articles_overseas.json")


def test_reproduces_enriched_fixture_exactly(before, after):
    texts = {r.article.extra["enrich_url"]: r.article.extra.get("enrich_text") for r in after}

    def fake_fetch(url):
        if texts.get(url) is None:            # 4위 Waymo: 타임아웃
            raise TimeoutError("timed out")
        return f"<html>{url}</html>"

    got = enrich_ranked(before, fetch=fake_fetch, extract=lambda html: texts[html[6:-7]])
    assert [r.to_dict() for r in got] == [r.to_dict() for r in after]


def test_failed_has_status_and_url_but_no_text(before):
    got = enrich_article(before[3].article, fetch=lambda u: (_ for _ in ()).throw(TimeoutError()), extract=lambda h: h)
    assert got.extra["enrich_status"] == "failed"
    assert "enrich_text" not in got.extra
    assert got.extra["enrich_url"] == before[3].article.extra["anchor_url"]     # 어디에 걸었다가 실패했는지는 남긴다


def test_enrich_url_is_anchor_url_not_normalized(before):
    third = before[2].article                                                     # utm 이 붙어 있던 항목
    got = enrich_article(third, fetch=lambda u: "x" * 1000, extract=lambda h: h)
    assert got.extra["enrich_url"] == "https://www.physicalintelligence.company/blog/pi06-open-weights"
    assert got.extra["enrich_url"] != third.extra["normalized_url"]


def test_text_is_cut_to_1500_and_short_text_fails(before):
    art = before[0].article
    long = enrich_article(art, fetch=lambda u: "h", extract=lambda h: "가" * 5000)
    assert long.extra["enrich_status"] == "success" and len(long.extra["enrich_text"]) == MAX_CHARS
    short = enrich_article(art, fetch=lambda u: "h", extract=lambda h: "쿠키 사용에 동의해 주세요" * 3)
    assert short.extra["enrich_status"] == "failed" and "enrich_text" not in short.extra
    exact = enrich_article(art, fetch=lambda u: "h", extract=lambda h: "a" * MIN_CHARS)
    assert exact.extra["enrich_status"] == "success"


def test_extractor_none_is_failure_and_original_fields_untouched(before):
    art = before[0].article
    got = enrich_article(art, fetch=lambda u: "h", extract=lambda h: None)
    assert got.extra["enrich_status"] == "failed"
    assert got.description == art.description and got.title == art.title and got.url == art.url
    assert {k: v for k, v in got.extra.items() if not k.startswith("enrich")} == art.extra


def test_domestic_is_rejected(before):
    with pytest.raises(ValueError, match="해외"):
        enrich_article(replace(before[0].article, origin=Origin.DOMESTIC), fetch=lambda u: "h", extract=lambda h: h)
