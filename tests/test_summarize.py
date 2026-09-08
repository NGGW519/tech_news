"""src/summarize.py — SPEC 7절. summary_cases 3건 + brief_items fixture 를 가짜 Gemini 호출로 재현."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from src.schema import BriefItem, Origin, RankedArticle, SummaryStatus
from src.summarize import (
    RESPONSE_SCHEMA,
    TITLE_ONLY_INSTRUCTION,
    build_prompt,
    build_request,
    fallback_lines,
    parse_response,
    resolve_input,
    summarize_section,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _ranked(name: str) -> list[RankedArticle]:
    return [RankedArticle.from_dict(d) for d in _load(name)]


def _response(items: dict[str, list[str]]) -> dict:
    text = json.dumps({"items": [{"id": k, "lines": v} for k, v in items.items()]}, ensure_ascii=False)
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


CASES = ["case_domestic_normal.json", "case_title_only.json", "case_with_body.json"]


# ─────────────────────────────────────────────────────────────────────────────
# summary_cases — 입력 선택 · 조건부 규칙 · BriefItem 조립
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", CASES)
def test_input_resolution_matches_case(name):
    case = _load(f"summary_cases/{name}")
    ranked = RankedArticle.from_dict(case["input"]["ranked_article"])
    chosen = resolve_input(ranked.article)
    assert chosen.source == case["input"]["summary_input"]["source"]
    assert chosen.text == case["input"]["summary_input"]["text"]


@pytest.mark.parametrize("name", CASES)
def test_conditional_instruction_appended_only_for_title_only(name):
    case = _load(f"summary_cases/{name}")
    ranked = RankedArticle.from_dict(case["input"]["ranked_article"])
    prompt = build_prompt(ranked.origin, [ranked])
    expected_rule = case["input"]["summary_input"]["conditional_title_only_rule"]
    assert (TITLE_ONLY_INSTRUCTION in prompt) is expected_rule
    if expected_rule:
        assert case["input"]["summary_input"]["appended_instruction"] == TITLE_ONLY_INSTRUCTION
    assert f"[id: {ranked.article.article_id}]" in prompt and ranked.display_title in prompt


@pytest.mark.parametrize("name", CASES)
def test_section_with_expected_lines_reproduces_brief_item(name):
    case = _load(f"summary_cases/{name}")
    ranked = RankedArticle.from_dict(case["input"]["ranked_article"])
    expected = BriefItem.from_dict(case["expected"]["brief_item"])
    got = summarize_section([ranked], call=lambda req: _response({ranked.article.article_id: list(expected.summary_lines)}))
    assert got[0].to_dict() == expected.to_dict()


def test_prompt_variants_differ_by_origin():
    dom = _ranked("ranked_articles_domestic.json")
    ovs = _ranked("enriched_articles_overseas.json")
    assert "국내" in build_prompt(Origin.DOMESTIC, dom) and "영문" not in build_prompt(Origin.DOMESTIC, dom)
    assert "영문" in build_prompt(Origin.OVERSEAS, ovs)
    assert TITLE_ONLY_INSTRUCTION in build_prompt(Origin.OVERSEAS, ovs)      # 4위가 제목뿐 → 배치에 조건부 규칙
    assert TITLE_ONLY_INSTRUCTION not in build_prompt(Origin.DOMESTIC, dom)


def test_request_forces_json_schema():
    req = build_request("p")
    gc = req["generationConfig"]
    assert gc["responseMimeType"] == "application/json" and gc["responseSchema"] == RESPONSE_SCHEMA
    assert req["contents"][0]["parts"][0]["text"] == "p"


# ─────────────────────────────────────────────────────────────────────────────
# 주차 fixture 재현 — 국내 3 / 해외 5 (정상 + fallback 1·3순위)
# ─────────────────────────────────────────────────────────────────────────────


def test_domestic_section_reproduces_brief_items():
    ranked = _ranked("ranked_articles_domestic.json")
    expected = [BriefItem.from_dict(d) for d in _load("brief_items_domestic.json")]
    lines = {b.source_article_id: list(b.summary_lines) for b in expected}
    got = summarize_section(ranked, call=lambda req: _response(lines))
    assert [g.to_dict() for g in got] == [e.to_dict() for e in expected]


def test_overseas_section_reproduces_brief_items_including_fallbacks():
    ranked = _ranked("enriched_articles_overseas.json")
    expected = [BriefItem.from_dict(d) for d in _load("brief_items_overseas.json")]
    gemini_lines = {b.source_article_id: list(b.summary_lines) for b in expected if b.summary_status is SummaryStatus.GEMINI}
    assert len(gemini_lines) == 3                                    # 1·2·3위만 모델이 답한 상황
    got = summarize_section(ranked, call=lambda req: _response(gemini_lines))
    assert [g.to_dict() for g in got] == [e.to_dict() for e in expected]
    assert got[3].summary_lines == () and got[4].summary_lines[0].endswith("⚠️ 자동 요약 실패")


def test_fallback_priority_description_then_enrich_then_omit():
    ranked = _ranked("enriched_articles_overseas.json")
    fifth = ranked[4].article                                        # description 있음 + enrich_text 있음 → description
    assert fallback_lines(fifth) == (fifth.description[:120].rstrip() + " ⚠️ 자동 요약 실패",)
    first = ranked[0].article                                        # description "" + enrich_text → enrich_text (2순위)
    assert fallback_lines(first) == (first.extra["enrich_text"][:120].rstrip() + " ⚠️ 자동 요약 실패",)
    fourth = ranked[3].article                                       # 둘 다 없음 → 생략
    assert fallback_lines(fourth) == ()


# ─────────────────────────────────────────────────────────────────────────────
# 형식 위반 · 실패 처리
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def one():
    return _ranked("ranked_articles_domestic.json")[:1]


def test_three_or_more_lines_keeps_first_two(one, caplog):
    aid = one[0].article.article_id
    with caplog.at_level(logging.WARNING):
        got = summarize_section(one, call=lambda r: _response({aid: ["가.", "나.", "다."]}))
    assert got[0].summary_lines == ("가.", "나.") and got[0].summary_status is SummaryStatus.GEMINI
    assert "3문장" in caplog.text


def test_long_line_is_kept_with_warning_not_cut(one, caplog):
    aid = one[0].article.article_id
    long = "이 문장은 사십 자를 훌쩍 넘기도록 일부러 길게 늘여 쓴 요약 문장입니다 정말로."
    assert len(long) > 40
    with caplog.at_level(logging.WARNING):
        got = summarize_section(one, call=lambda r: _response({aid: [long, "둘."]}))
    assert got[0].summary_lines == (long, "둘.") and got[0].summary_status is SummaryStatus.GEMINI
    assert "자르지 않고" in caplog.text


def test_single_line_is_kept(one):
    aid = one[0].article.article_id
    got = summarize_section(one, call=lambda r: _response({aid: ["하나."]}))
    assert got[0].summary_lines == ("하나.",) and got[0].summary_status is SummaryStatus.GEMINI


def test_empty_lines_or_missing_id_fall_back_per_item(one):
    aid = one[0].article.article_id
    assert summarize_section(one, call=lambda r: _response({aid: []}))[0].summary_status is SummaryStatus.FALLBACK_DESCRIPTION
    assert summarize_section(one, call=lambda r: _response({"naver:unknown": ["x."]}))[0].summary_status is SummaryStatus.FALLBACK_DESCRIPTION


@pytest.mark.parametrize("bad_call", [
    lambda r: (_ for _ in ()).throw(RuntimeError("HTTP 503")),
    lambda r: {"candidates": [{"content": {"parts": [{"text": ""}]}}]},                 # 빈 문자열
    lambda r: {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]},
    lambda r: {"candidates": []},
])
def test_batch_failure_sends_whole_section_to_fallback(one, bad_call):
    got = summarize_section(one, call=bad_call)
    assert got[0].summary_status is SummaryStatus.FALLBACK_DESCRIPTION
    assert got[0].summary_lines[0].endswith("⚠️ 자동 요약 실패")


def test_fenced_json_is_tolerated():
    payload = {"candidates": [{"content": {"parts": [{"text": '```json\n{"items":[{"id":"a","lines":["x."]}]}\n```'}]}}]}
    assert parse_response(payload) == {"a": ["x."]}


def test_mixed_origins_rejected():
    dom = _ranked("ranked_articles_domestic.json")[:1]
    ovs = _ranked("ranked_articles_overseas.json")[:1]
    with pytest.raises(ValueError):
        summarize_section(dom + ovs, call=lambda r: _response({}))


def test_empty_section_makes_no_call():
    assert summarize_section([], call=lambda r: (_ for _ in ()).throw(AssertionError("호출되면 안 된다"))) == []
