"""src/publishers.py — SPEC 6절 "`publisher` — 도메인 → 매체명" 계약 검증.

세 층으로 검증한다.
  1. 단위: 등록 도메인 추출, fallback, 4절 특례
  2. 표 위생: 키가 전부 등록 도메인·소문자이고 조회에 그대로 걸리는가
  3. fixture 전수: fixture 가 고정한 모든 `publisher` 값이 표에서 재현되는가 (SPEC 6절 요구)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.publishers import (
    DOMAIN_TO_NAME,
    MULTI_LABEL_SUFFIXES,
    host_of,
    publisher_name,
    registered_domain,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────────────────────────
# 1. 단위
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://www.etnews.com/20260813000123", "etnews.com"),
        ("https://news.mt.co.kr/mtview.php?no=1", "mt.co.kr"),          # 2단 접미사 + 서브도메인
        ("https://zdnet.co.kr/view/?no=1", "zdnet.co.kr"),              # 2단 접미사, 서브도메인 없음
        ("https://www.1x.tech/discover/neo-preorders", "1x.tech"),
        ("https://deepmind.google/discover/blog/x/", "deepmind.google"),  # 브랜드 TLD
        ("https://old.reddit.com/r/robotics/comments/x/", "reddit.com"),
        ("https://i.redd.it/abc.jpg", "redd.it"),
        ("HTTPS://WWW.TechCrunch.COM/x", "techcrunch.com"),              # 소문자화
        ("https://user:pw@example.com:8443/x", "example.com"),          # userinfo · 포트
        ("https://example.com./x", "example.com"),                      # 후행 점
        ("example.com/no-scheme", "example.com"),                       # 스킴 없음
        ("localhost", "localhost"),                                     # 단일 라벨
    ],
)
def test_registered_domain(url, expected):
    assert registered_domain(url) == expected


def test_host_of_strips_userinfo_port_and_case():
    assert host_of("https://User:pw@News.MT.co.kr:443/a?b=c") == "news.mt.co.kr"


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://blog.example.com/x", "example"),   # 표에 없음 → TLD 제거, 서브도메인 무시
        ("https://foo.co.kr/x", "foo"),              # 2단 접미사 통째로 제거
        ("https://bar.io", "bar"),
        ("https://sub.some-site.tech/y", "some-site"),
        ("localhost", "localhost"),                  # 뗄 TLD 가 없으면 그대로
    ],
)
def test_fallback_strips_tld_and_nothing_else(url, expected):
    assert registered_domain(url) not in DOMAIN_TO_NAME, "이 케이스는 표에 없어야 fallback 을 검증한다"
    assert publisher_name(url) == expected


def test_fallback_keeps_lowercase_as_is():
    # SPEC: "대소문자를 임의로 손보지 않는다" — 호스트는 소문자화되므로 결과도 소문자 그대로
    assert publisher_name("https://www.SomeStartup.ai/post") == "somestartup"


class TestSpecialCases:
    """SPEC 4절 특례 — arXiv, Reddit self-post. 도메인 표보다 우선한다."""

    def test_arxiv_any_subdomain(self):
        assert publisher_name("https://arxiv.org/abs/2608.04417") == "arXiv"
        assert publisher_name("https://export.arxiv.org/abs/2608.04417") == "arXiv"

    def test_arxiv_wins_even_via_reddit_link_post(self):
        # reddit:1mpz8vr — Reddit 에 올라온 arXiv 링크 글. is_self=False 라 링크 대상 도메인으로 간다
        assert publisher_name("https://arxiv.org/abs/2608.04417", subreddit="robotics", is_self=False) == "arXiv"

    def test_reddit_self_post(self):
        url = "https://www.reddit.com/r/robotics/comments/1mq0a4b/unitree_g1_teardown_bom_breakdown/"
        assert publisher_name(url, subreddit="robotics", is_self=True) == "Reddit r/robotics"
        assert publisher_name("https://old.reddit.com/r/MachineLearning/comments/x/",
                              subreddit="MachineLearning", is_self=True) == "Reddit r/MachineLearning"

    def test_reddit_self_post_without_subreddit_is_contract_violation(self):
        with pytest.raises(ValueError):
            publisher_name("https://www.reddit.com/r/robotics/comments/x/", is_self=True)

    def test_reddit_link_post_to_reddit_itself_uses_table(self):
        # 크로스포스트·미디어 링크 글: 특례 아님 → 표의 "Reddit"
        assert publisher_name("https://www.reddit.com/r/robotics/comments/x/", subreddit="robotics", is_self=False) == "Reddit"
        assert publisher_name("https://v.redd.it/abc", subreddit="robotics", is_self=False) == "Reddit"

    def test_is_self_flag_ignored_outside_reddit(self):
        # 수집기가 플래그를 잘못 넘겨도 도메인이 reddit.com 이 아니면 특례가 발동하지 않는다
        assert publisher_name("https://techcrunch.com/x/", subreddit="robotics", is_self=True) == "TechCrunch"


# ─────────────────────────────────────────────────────────────────────────────
# 2. 표 위생
# ─────────────────────────────────────────────────────────────────────────────


def test_table_keys_are_normalized_registered_domains():
    for key in DOMAIN_TO_NAME:
        assert key == key.lower(), key
        assert not key.startswith("www."), key
        assert registered_domain(key) == key, f"{key} 는 등록 도메인이 아니다 (서브도메인 포함?)"


def test_table_values_are_clean():
    for key, name in DOMAIN_TO_NAME.items():
        assert name and name == name.strip(), key


def test_multi_label_suffixes_have_exactly_two_labels():
    for suffix in MULTI_LABEL_SUFFIXES:
        assert suffix.count(".") == 1, suffix


# ─────────────────────────────────────────────────────────────────────────────
# 3. fixture 전수 — SPEC 6절 "fixture 의 publisher 값이 표에서 재현되지 않으면 표의 결함"
# ─────────────────────────────────────────────────────────────────────────────


def _iter_raw_article_dicts(obj):
    """fixture 트리에서 RawArticle 모양의 dict 만 골라낸다 (`article_id` + `extra`)."""
    if isinstance(obj, dict):
        if "article_id" in obj and "extra" in obj and "publisher" in obj:
            yield obj
        for value in obj.values():
            yield from _iter_raw_article_dicts(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_raw_article_dicts(item)


def _all_fixture_raw_articles():
    files = sorted(FIXTURES.glob("*.json")) + sorted((FIXTURES / "summary_cases").glob("*.json"))
    seen: dict[str, dict] = {}
    for path in files:
        for raw in _iter_raw_article_dicts(json.loads(path.read_text(encoding="utf-8"))):
            seen.setdefault(raw["article_id"], raw)
    return seen


RAW_BY_ID = _all_fixture_raw_articles()


@pytest.mark.parametrize("article_id", sorted(RAW_BY_ID))
def test_every_fixture_raw_article_publisher_is_reproduced(article_id):
    raw = RAW_BY_ID[article_id]
    extra = raw["extra"]
    url = extra.get("anchor_url") or raw["url"]      # 해외는 앵커용, 국내는 originallink(=url)
    got = publisher_name(url, subreddit=extra.get("subreddit"), is_self=bool(extra.get("is_self")))
    assert got == raw["publisher"], f"{article_id}: {url}"


def test_brief_items_publisher_matches_source_raw_article():
    """BriefItem.publisher 는 RawArticle.publisher 를 그대로 승계한다 — 역추적 키로 대조."""
    for name in ("brief_items_domestic.json", "brief_items_overseas.json"):
        for item in _load(name):
            raw = RAW_BY_ID[item["source_article_id"]]
            assert item["publisher"] == raw["publisher"], item["source_article_id"]


def test_cluster_publishers_reproduced_from_naver_originallink():
    """ranked_articles_domestic.cluster_publishers 는 URL 이 붙어 있지 않다.
    article_id = naver:<sha1(originallink)[:12]> 규약(SPEC 6절)으로 originallink 를 역추적해 대조한다."""
    link_by_id = {}
    for path in FIXTURES.glob("api_naver_news_*.json"):
        for item in json.loads(path.read_text(encoding="utf-8"))["items"]:
            link = item["originallink"]
            link_by_id["naver:" + hashlib.sha1(link.encode()).hexdigest()[:12]] = link

    checked = 0
    for ranked in _load("ranked_articles_domestic.json"):
        ev = ranked["evidence"]
        assert len(ev["cluster_article_ids"]) == len(ev["cluster_publishers"])
        for aid, want in zip(ev["cluster_article_ids"], ev["cluster_publishers"]):
            assert publisher_name(link_by_id[aid]) == want, aid
            checked += 1
    assert checked == 9  # 4 + 3 + 2


def test_every_naver_fixture_domain_is_in_table_not_fallback():
    """노이즈 기사(fnnews, mk)까지 포함해 네이버 fixture 의 모든 originallink 도메인이 표에 있어야 한다."""
    for path in FIXTURES.glob("api_naver_news_*.json"):
        for item in json.loads(path.read_text(encoding="utf-8"))["items"]:
            domain = registered_domain(item["originallink"])
            assert domain in DOMAIN_TO_NAME, f"{domain} 이 표에 없다 → fallback 을 타게 된다"


def test_every_overseas_fixture_domain_is_in_table_or_special_case():
    for raw in _load("raw_articles_overseas.json"):
        domain = registered_domain(raw["extra"]["anchor_url"])
        assert domain in DOMAIN_TO_NAME or domain == "arxiv.org", domain
