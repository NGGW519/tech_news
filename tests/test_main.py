"""src/main.py — 가짜 서비스로 파이프라인을 끝까지 돌린다. fixture 주차(8월 2주)를 그대로 재현한다."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from src.main import Services, fill_from_reserve, run
from src.notion import NotionApi
from src.render_notion import mention
from src.rank_overseas import rank_overseas
from src.schema import KST, BriefItem, RankedArticle, RawArticle, SummaryStatus
from src.week import compute_week
from tests.test_collect_naver import parse_fixture_pool

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 8, 17, 8, 30, tzinfo=KST)
USER_ID = "1cfd872b-0000-4000-8000-000000000000"   # 알림 멘션 대상 (SPEC 12절 NOTION_USER_ID)


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeNotion(NotionApi):
    """월 페이지·토글을 메모리에 보관한다."""

    def __init__(self):
        super().__init__("tok")
        self.pages: dict[str, str] = {}
        self.toggles: dict[str, list[dict]] = {}

    def ensure_month_page(self, root, title):
        self.pages.setdefault(title, f"page-{title}")
        self.toggles.setdefault(self.pages[title], [])
        return self.pages[title]

    def week_toggle_exists(self, month_page_id, week_key):
        # 실제 구현과 같이 rich_text[0] 만 본다 — mention 이 뒤에 붙어도 판정은 라벨로 한다 (SPEC 9절 계약)
        return any(t["toggle"]["rich_text"][0]["text"]["content"].startswith(week_key) for t in self.toggles[month_page_id])

    def append_week_toggle(self, month_page_id, toggle_block):
        self.toggles[month_page_id].append(toggle_block)
        return "block-1234"


def _gemini_lines():
    lines = {}
    for name in ("brief_items_domestic.json", "brief_items_overseas.json"):
        for d in _load(name):
            if d["summary_status"] == "gemini":
                lines[d["source_article_id"]] = d["summary_lines"]
    return lines


def _fake_call(req):
    prompt = req["contents"][0]["parts"][0]["text"]
    items = [{"id": k, "lines": v} for k, v in _gemini_lines().items() if f"[id: {k}]" in prompt]
    return {"candidates": [{"content": {"parts": [{"text": json.dumps({"items": items}, ensure_ascii=False)}]}}]}


def _fake_enrich(ranked):
    texts = {r["article"]["article_id"]: r["article"]["extra"] for r in _load("enriched_articles_overseas.json")}
    from dataclasses import replace
    return [replace(r, article=replace(r.article, extra={**r.article.extra, **{k: v for k, v in texts[r.article.article_id].items() if k.startswith("enrich")}}))
            if r.article.article_id in texts else r for r in ranked]


@pytest.fixture
def services(tmp_path):
    notion = FakeNotion()
    overseas_raw = [RawArticle.from_dict(d) for d in _load("raw_articles_overseas.json")]
    s = Services(
        collect_domestic=lambda week: parse_fixture_pool(),
        overseas_collectors={"fixture": lambda week: overseas_raw},
        enrich=_fake_enrich,
        summarize_call=_fake_call,
        notion=notion,
        notion_root_page_id="root",
        notion_user_id=USER_ID,
        log_file=tmp_path / "logs" / "last_run.txt",
    )
    s.fake_notion = notion   # 테스트 편의
    return s


def test_full_run_reproduces_fixture_week(services):
    result = run(services, now=NOW)
    assert (result.status, result.domestic, result.overseas, result.exit_code) == ("published", 3, 5, 0)
    assert result.notion_link == "https://www.notion.so/page202608#block1234"   # 하이픈 제거 (SPEC 8절)

    toggle = services.fake_notion.toggles["page-2026-08"][0]
    # rich_text[0] 이 라벨이라는 이 단정이 9절 멱등성 계약의 회귀 방지선이다 — mention 을 앞에 넣으면 여기서 깨진다
    assert toggle["toggle"]["rich_text"][0]["text"]["content"] == "8월 2주 (08/10~08/16) · 국내 3 / 해외 5"
    kinds = [b["type"] for b in toggle["toggle"]["children"]]
    assert kinds == ["heading_3"] + ["paragraph"] * 3 + ["heading_3"] + ["paragraph"] * 5

    # 알림: 토글 라벨 뒤의 mention 조각이 곧 푸시다. 별도 발송 단계가 없다 (SPEC 8절)
    assert toggle["toggle"]["rich_text"][1] == mention(USER_ID)

    # 실행 로그
    text = services.log_file.read_text(encoding="utf-8")
    assert "week: 8월 2주 (08/10~08/16)" in text and "status: published" in text and "summary: gemini 6 / fallback 2" in text


def test_second_run_is_idempotent(services):
    run(services, now=NOW)
    second = run(services, now=NOW)
    assert second.status == "already_exists"
    assert len(services.fake_notion.toggles["page-2026-08"]) == 1   # mention 이 붙어도 접두 일치로 걸린다


def test_dry_run_writes_nothing(services, capsys):
    result = run(services, now=NOW, dry_run=True)
    assert result.status == "dry_run" and services.fake_notion.toggles == {}
    assert "### 국내" in capsys.readouterr().out
    assert not services.log_file.exists()


def test_both_empty_makes_no_toggle_and_no_notification(services):
    # 토글이 없으면 mention 도 없다 — 알림이 안 온 것 자체가 "아무것도 못 건졌다"는 신호다 (SPEC 2·8절)
    services.collect_domestic = lambda week: []
    services.overseas_collectors = {"fixture": lambda week: []}
    result = run(services, now=NOW)
    assert result.status == "nothing_to_publish" and result.exit_code == 0
    assert services.fake_notion.toggles == {}


def test_one_overseas_source_crash_keeps_the_others(services):
    overseas_raw = services.overseas_collectors["fixture"](None)
    services.overseas_collectors = {
        "hn": lambda week: overseas_raw,
        "reddit": lambda week: (_ for _ in ()).throw(RuntimeError("403")),
    }
    result = run(services, now=NOW)
    assert result.status == "published" and result.overseas == 5
    assert result.failures == ("collect_reddit",) and result.exit_code == 1


def test_collector_crash_publishes_other_side_and_fails_the_job(services):
    def boom(week):
        raise RuntimeError("naver 500")
    services.collect_domestic = boom
    result = run(services, now=NOW)
    assert result.status == "published" and (result.domestic, result.overseas) == (0, 5)
    assert result.failures == ("collect_domestic",) and result.exit_code == 1
    toggle = services.fake_notion.toggles["page-2026-08"][0]
    assert toggle["toggle"]["rich_text"][0]["text"]["content"].endswith("국내 0 / 해외 5")
    assert toggle["toggle"]["children"][1]["paragraph"]["rich_text"][0]["text"]["content"] == "(해당 없음)"


def test_no_llm_style_failure_makes_everything_fallback(services):
    services.summarize_call = lambda req: (_ for _ in ()).throw(RuntimeError("no llm"))
    result = run(services, now=NOW)
    toggle = services.fake_notion.toggles["page-2026-08"][0]
    assert result.status == "published" and result.exit_code == 0          # 요약 실패는 fallback 이지 실패가 아니다
    assert "fallback 8" in services.log_file.read_text(encoding="utf-8")


def test_fill_from_reserve_renumbers():
    pool = [RawArticle.from_dict(d) for d in _load("raw_articles_overseas.json")]
    ranking = rank_overseas(pool, top_n=3)
    filled = fill_from_reserve(ranking, top_n=4)
    assert [r.rank for r in filled] == [1, 2, 3, 4]
    assert filled[3].article.article_id == "rss:arxiv:2608.05119" and filled[3].sort_score == -1.0
    assert len(fill_from_reserve(ranking, top_n=3)) == 3
