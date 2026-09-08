"""src/urls.py — SPEC 4절 두 정규화. raw_articles_overseas.json 12건의 normalized_url/anchor_url 을 재현."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.urls import anchor_url, is_tracking_param, normalize_for_compare, strip_tracking_query

FIXTURES = Path(__file__).parent / "fixtures"
RAW = json.loads((FIXTURES / "raw_articles_overseas.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("raw", RAW, ids=[r["article_id"] for r in RAW])
def test_fixture_urls_reproduced(raw):
    assert normalize_for_compare(raw["url"]) == raw["extra"]["normalized_url"]
    assert anchor_url(raw["url"]) == raw["extra"]["anchor_url"]


def test_merge_pairs_share_normalized_url_but_not_necessarily_anchor():
    by_id = {r["article_id"]: r["url"] for r in RAW}
    assert normalize_for_compare(by_id["hn:41236780"]) == normalize_for_compare(by_id["reddit:1mr2h8k"])
    assert normalize_for_compare(by_id["rss:deepmind:gemini-robotics-1-5"]) == normalize_for_compare(by_id["hn:41244517"])


@pytest.mark.parametrize("key, expected", [
    ("utm_source", True), ("UTM_Campaign", True), ("fbclid", True), ("gclid", True), ("ref", True), ("source", True),
    ("no", False), ("id", False), ("utm", False), ("ref_src", False), ("sourceid", False),
])
def test_is_tracking_param(key, expected):
    assert is_tracking_param(key) is expected


def test_non_tracking_params_are_preserved_verbatim_in_order():
    url = "https://zdnet.co.kr/view/?no=20260814082011&utm_source=x&b=2&a=1"
    assert anchor_url(url) == "https://zdnet.co.kr/view/?no=20260814082011&b=2&a=1"
    assert strip_tracking_query("5612388") == "5612388"                 # `?5612388` 같은 값은 재인코딩하지 않는다
    assert anchor_url("https://www.news1.kr/articles/?5612388") == "https://www.news1.kr/articles/?5612388"


def test_question_mark_dropped_when_nothing_remains():
    assert anchor_url("https://a.com/x?utm_source=r&utm_medium=s") == "https://a.com/x"
    assert normalize_for_compare("https://a.com/x/?utm_source=r") == "https://a.com/x"


def test_compare_normalization_rules():
    assert normalize_for_compare("HTTPS://WWW.Example.COM/Path/To/") == "https://example.com/Path/To"   # 경로 대소문자는 유지
    assert normalize_for_compare("https://www.example.com/") == "https://example.com"
    assert normalize_for_compare("https://www2.example.com/a") == "https://www2.example.com/a"          # www. 만 뗀다


def test_anchor_keeps_www_case_and_trailing_slash():
    url = "https://www.1x.tech/Discover/neo-preorders/"
    assert anchor_url(url) == url
