"""src/render_notion.py — SPEC 5절 블록 구조를 fixture WeeklyBrief 로 검증."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.render_notion import (
    EMPTY_SECTION_TEXT,
    render_brief_text,
    render_item,
    render_item_text,
    render_week_toggle,
    toggle_label,
)
from src.schema import BriefItem, WeekMeta, WeeklyBrief

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def brief() -> WeeklyBrief:
    return WeeklyBrief(
        week=WeekMeta.from_dict(_load("week_meta.json")[0]["week"]),
        domestic=tuple(BriefItem.from_dict(d) for d in _load("brief_items_domestic.json")),
        overseas=tuple(BriefItem.from_dict(d) for d in _load("brief_items_overseas.json")),
    )


def _contents(block: dict) -> list[str]:
    return [p["text"]["content"] for p in block[block["type"]]["rich_text"]]


# ─────────────────────────────────────────────────────────────────────────────
# 토글 구조
# ─────────────────────────────────────────────────────────────────────────────


def test_toggle_label_uses_actual_counts(brief):
    toggle = render_week_toggle(brief)
    assert toggle["type"] == "toggle"
    assert _contents(toggle) == ["8월 2주 (08/10~08/16) · 국내 3 / 해외 5"]
    assert toggle_label(brief.week, 0, 5) == "8월 2주 (08/10~08/16) · 국내 0 / 해외 5"


def test_children_layout_heading_then_one_paragraph_per_item(brief):
    children = render_week_toggle(brief)["toggle"]["children"]
    kinds = [b["type"] for b in children]
    assert kinds == ["heading_3"] + ["paragraph"] * 3 + ["heading_3"] + ["paragraph"] * 5   # 10 블록, 항목당 1개
    assert _contents(children[0]) == ["국내"] and _contents(children[4]) == ["해외"]
    assert _contents(children[1])[0] == "1. " and _contents(children[5])[0] == "1. "        # 섹션마다 1부터


def test_domestic_item_rich_text_five_pieces_with_link_and_gray_source(brief):
    item = brief.domestic[0]
    block = render_item(item)
    pieces = block["paragraph"]["rich_text"]
    assert [p["text"]["content"] for p in pieces] == [
        "1. ",
        "삼성전자, 휴머노이드용 AP 양산 착수",
        "\n2027년 상용화를 목표로 전용 연산 칩을 개발 중이다.",
        "\n기존 모바일 AP 대비 추론 성능을 4배로 끌어올렸다.",
        "\n전자신문 · 08/13",
    ]
    assert pieces[1]["text"]["link"] == {"url": "https://www.etnews.com/20260813000123"}
    assert pieces[4]["annotations"] == {"color": "gray"}
    assert all("link" not in p["text"] for i, p in enumerate(pieces) if i != 1)               # 링크는 제목에만


def test_overseas_link_is_anchor_url_not_normalized(brief):
    # 3위: utm 만 지워진 앵커용 URL. www. 는 살아 있다 (SPEC 4절)
    third = brief.overseas[2]
    link = render_item(third)["paragraph"]["rich_text"][1]["text"]["link"]["url"]
    assert link == "https://www.physicalintelligence.company/blog/pi06-open-weights"


def test_fallback_items_shrink_summary_pieces_instead_of_padding(brief):
    fourth, fifth = brief.overseas[3], brief.overseas[4]                # 4위: 요약 줄 생략, 5위: fallback 1줄
    assert _contents(render_item(fourth)) == ["4. ", fourth.title, "\nWaymo · 08/13"]
    fifth_contents = _contents(render_item(fifth))
    assert len(fifth_contents) == 4 and fifth_contents[2].endswith("⚠️ 자동 요약 실패")


def test_no_indentation_and_no_bare_urls_in_blocks(brief):
    toggle = render_week_toggle(brief)
    for block in toggle["toggle"]["children"]:
        for content in _contents(block):
            assert not content.startswith("    ")                        # 4절의 4칸 들여쓰기는 재현하지 않는다
            assert "http" not in content                                  # URL 노출 금지 (4절)


def test_empty_section_keeps_heading_with_placeholder(brief):
    only_overseas = replace(brief, domestic=())
    children = render_week_toggle(only_overseas)["toggle"]["children"]
    assert [b["type"] for b in children[:2]] == ["heading_3", "paragraph"]
    assert _contents(children[0]) == ["국내"] and _contents(children[1]) == [EMPTY_SECTION_TEXT]
    assert _contents(render_week_toggle(only_overseas)) == ["8월 2주 (08/10~08/16) · 국내 0 / 해외 5"]


def test_both_empty_makes_no_toggle(brief):
    assert render_week_toggle(replace(brief, domestic=(), overseas=())) is None


def test_items_are_ordered_by_rank_even_if_input_is_shuffled(brief):
    shuffled = replace(brief, overseas=tuple(reversed(brief.overseas)))
    children = render_week_toggle(shuffled)["toggle"]["children"]
    assert [_contents(b)[0] for b in children[5:]] == ["1. ", "2. ", "3. ", "4. ", "5. "]


# ─────────────────────────────────────────────────────────────────────────────
# 텍스트 형식 (4절 스케치) — summary_cases 의 expected.rendered 와 README 예시
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["case_domestic_normal.json", "case_title_only.json", "case_with_body.json"])
def test_item_text_matches_summary_case_rendered(name):
    case = _load(f"summary_cases/{name}")
    item = BriefItem.from_dict(case["expected"]["brief_item"])
    assert render_item_text(item) == case["expected"]["rendered"].rstrip("\n")


def test_brief_text_matches_spec_4_example(brief):
    rendered = render_brief_text(brief)
    assert rendered.startswith(
        "### 국내\n\n"
        "**1. 삼성전자, 휴머노이드용 AP 양산 착수**\n"
        "    2027년 상용화를 목표로 전용 연산 칩을 개발 중이다.\n"
        "    기존 모바일 AP 대비 추론 성능을 4배로 끌어올렸다.\n"
        "    전자신문 · 08/13\n"
    )
    assert "**4. Waymo opens freeway driving to all riders in three metros**\n    Waymo · 08/13" in rendered
