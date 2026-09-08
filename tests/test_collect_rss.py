"""src/collect_rss.py — RSS 2.0 / Atom 파싱(순수) → raw_articles_overseas.json 의 RSS 2건 재현."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.collect_rss import DEFAULT_FEEDS, Feed, collect_rss, fetch_feed, parse_feed, slug_for
from src.schema import KST
from src.week import compute_week

FIXTURES = Path(__file__).parent / "fixtures"
COLLECTED = datetime(2026, 8, 17, 8, 12, 55, tzinfo=KST)
WEEK = compute_week(datetime(2026, 8, 17).date())

DEEPMIND = Feed("deepmind", "https://deepmind.google/blog/rss.xml")
ARXIV_RO = Feed("arxiv", "http://export.arxiv.org/api/query?search_query=cat:cs.RO", {"sortBy": "submittedDate"})


def _xml(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _expected(article_id: str) -> dict:
    raw = json.loads((FIXTURES / "raw_articles_overseas.json").read_text(encoding="utf-8"))
    return next(r for r in raw if r["article_id"] == article_id)


def test_rss2_deepmind_reproduces_fixture_exactly():
    got = parse_feed(_xml("api_rss_deepmind.xml"), DEEPMIND, COLLECTED)
    assert len(got) == 1
    assert got[0].to_dict() == _expected("rss:deepmind:gemini-robotics-1-5")


def test_atom_arxiv_reproduces_fixture_exactly():
    got = parse_feed(_xml("api_rss_arxiv_cs_ro.xml"), ARXIV_RO, COLLECTED)
    assert len(got) == 1
    assert got[0].to_dict() == _expected("rss:arxiv:2608.05119")
    assert got[0].published_at.isoformat() == "2026-08-14T09:00:00+09:00"   # 00:00Z → KST


def test_slug_rules():
    assert slug_for("deepmind", "https://deepmind.google/discover/blog/gemini-robotics-1-5/") == "gemini-robotics-1-5"
    assert slug_for("arxiv", "https://arxiv.org/abs/2608.05119v2") == "2608.05119"     # 버전 제거
    assert slug_for("nvidia", "https://blogs.nvidia.com/blog/some-post/") == "some-post"


def test_default_feed_keys_match_spec():
    assert [f.key for f in DEFAULT_FEEDS] == ["arxiv", "arxiv", "deepmind", "nvidia"]
    assert DEFAULT_FEEDS[0].url == "http://export.arxiv.org/api/query?search_query=cat:cs.RO"   # fixture 의 feed_url


def test_fetch_filters_window_and_passes_params():
    calls = []

    def fake(url, params=None):
        calls.append((url, params))
        return _xml("api_rss_deepmind.xml")

    assert len(fetch_feed(DEEPMIND, WEEK, get_text=fake, collected_at=COLLECTED)) == 1
    other_week = compute_week(datetime(2026, 9, 7).date())
    assert fetch_feed(DEEPMIND, other_week, get_text=fake, collected_at=COLLECTED) == []
    assert fetch_feed(ARXIV_RO, WEEK, get_text=lambda u, p=None: (calls.append((u, p)), _xml("api_rss_arxiv_cs_ro.xml"))[1],
                      collected_at=COLLECTED)
    assert calls[-1] == (ARXIV_RO.url, {"sortBy": "submittedDate"})
    assert calls[0] == (DEEPMIND.url, None)


def test_collect_dedupes_cross_listed_arxiv_and_sleeps_between_arxiv_calls():
    slept = []
    feeds = (ARXIV_RO, Feed("arxiv", "http://export.arxiv.org/api/query?search_query=cat:cs.AI"), DEEPMIND)
    got = collect_rss(WEEK, feeds=feeds, collected_at=COLLECTED, sleep=slept.append,
                      get_text=lambda u, p=None: _xml("api_rss_arxiv_cs_ro.xml") if "arxiv" in u else _xml("api_rss_deepmind.xml"))
    assert sorted(a.article_id for a in got) == ["rss:arxiv:2608.05119", "rss:deepmind:gemini-robotics-1-5"]
    assert slept == [3.0]                                                   # arXiv → arXiv 사이에만
