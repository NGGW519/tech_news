"""Notion 블록 렌더링 — WeeklyBrief → 주차 토글 블록 JSON (SPEC 5절 "주차 토글의 블록 구조").

순수 로직이다. Notion API 호출은 하지 않는다 (호출부는 별도 모듈).

    toggle  "<week_label> · 국내 N / 해외 M"  @사용자   ← rich_text 2조각 (SPEC 5절 표)
    ├─ heading_3  "국내"
    ├─ paragraph   ← 항목 1 전체 (rich_text 5조각)
    ├─ …
    ├─ heading_3  "해외"
    └─ paragraph …

    toggle.rich_text:
      1. toggle_label                기본      ← 반드시 첫 조각 (SPEC 9절 멱등성 계약)
      2. 사용자 mention               기본      ← 이것이 알림이다 (SPEC 8절)

    paragraph.rich_text:
      1. "{rank}. "                  기본
      2. title                       앵커용 URL 링크
      3. "\\n" + summary_lines[0]     기본      ← summary_lines 에 있는 만큼만
      4. "\\n" + summary_lines[1]     기본
      5. "\\n" + "{publisher} · {MM/DD}"  회색

항목 하나 = paragraph 하나. 블록을 더 쪼개지 않는다. 4절 예시의 4칸 들여쓰기는 재현하지 않는다.
0건 섹션은 heading_3 를 남기고 paragraph 하나에 "(해당 없음)". 양쪽 0건이면 토글을 만들지 않는다 (2절).

`render_item_text` 는 같은 항목의 4절 텍스트 형식(로그·테스트용)이며 Notion 에는 쓰지 않는다.
"""

from __future__ import annotations

from typing import Any

from src.schema import BriefItem, WeekMeta, WeeklyBrief

HEADING_DOMESTIC = "국내"
HEADING_OVERSEAS = "해외"
EMPTY_SECTION_TEXT = "(해당 없음)"
SOURCE_COLOR = "gray"


# ─────────────────────────────────────────────────────────────────────────────
# rich_text 조각
# ─────────────────────────────────────────────────────────────────────────────


def text(content: str, *, link: str | None = None, color: str | None = None) -> dict[str, Any]:
    piece: dict[str, Any] = {"type": "text", "text": {"content": content}}
    if link:
        piece["text"]["link"] = {"url": link}
    if color:
        piece["annotations"] = {"color": color}
    return piece


def mention(user_id: str) -> dict[str, Any]:
    """사용자 mention 조각 — Notion 이 이 사용자에게 모바일 푸시를 보내는 유일한 장치다 (SPEC 8절).

    통합에 「이메일 주소를 제외한 사용자 정보 읽기」 권한이 없으면 이 조각이 든 블록 append 가
    `400 validation_error` 로 죽는다. 알림이 아니라 **그 주 발행 전체가 무산된다** (SPEC 8절 "통합 권한").
    멘션을 빼고 재시도하는 fallback 을 넣지 말 것 — SPEC 8·9절이 명시적으로 금지한다.
    """
    return {"type": "mention", "mention": {"type": "user", "user": {"object": "user", "id": user_id}}}


def toggle_label(week: WeekMeta, domestic_count: int, overseas_count: int) -> str:
    """`8월 2주 (08/10~08/16) · 국내 3 / 해외 5`. 건수는 실제 발행 건수다 (SPEC 2절)."""
    return f"{week.week_label} · 국내 {domestic_count} / 해외 {overseas_count}"


# ─────────────────────────────────────────────────────────────────────────────
# 블록
# ─────────────────────────────────────────────────────────────────────────────


def _block(kind: str, rich_text: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"object": "block", "type": kind, kind: {"rich_text": rich_text, **extra}}


def render_item(item: BriefItem) -> dict[str, Any]:
    pieces = [
        text(f"{item.rank}. "),
        text(item.title, link=item.url),
        *(text("\n" + line) for line in item.summary_lines),
        text("\n" + item.source_line, color=SOURCE_COLOR),
    ]
    return _block("paragraph", pieces)


def render_section(heading: str, items: tuple[BriefItem, ...]) -> list[dict[str, Any]]:
    blocks = [_block("heading_3", [text(heading)])]
    if items:
        blocks.extend(render_item(i) for i in sorted(items, key=lambda i: i.rank))
    else:
        blocks.append(_block("paragraph", [text(EMPTY_SECTION_TEXT)]))
    return blocks


def render_week_toggle(brief: WeeklyBrief, user_id: str) -> dict[str, Any] | None:
    """주차 토글 블록. 양쪽 0건이면 None — 빈 토글은 멱등성 체크 때문에 만들면 안 된다 (SPEC 2·9절).

    `rich_text` 는 두 조각이다 — 라벨 텍스트, 그 뒤에 사용자 mention (SPEC 5절 표).
    **순서를 뒤집지 말 것.** 멱등성 판정이 `rich_text[0].plain_text` 접두 일치만 보므로
    mention 이 앞에 오면 첫 조각의 plain_text 가 사용자 이름이 되어 `week_key` 가 사라지고
    **같은 주 토글이 매주 새로 쌓인다** (SPEC 9절 "mention 은 rich_text[0] 뒤에 온다").

    양쪽 0건이면 토글도 mention 도 없다 — 알림이 안 왔다는 것 자체가 신호다 (SPEC 2절).
    """
    if not brief.domestic and not brief.overseas:
        return None
    children = [
        *render_section(HEADING_DOMESTIC, brief.domestic),
        *render_section(HEADING_OVERSEAS, brief.overseas),
    ]
    label = toggle_label(brief.week, len(brief.domestic), len(brief.overseas))
    return _block("toggle", [text(label), mention(user_id)], children=children)


# ─────────────────────────────────────────────────────────────────────────────
# 텍스트 형식 (SPEC 4절 스케치) — 로그·테스트용
# ─────────────────────────────────────────────────────────────────────────────


def render_item_text(item: BriefItem) -> str:
    lines = [f"**{item.rank}. {item.title}**", *(f"    {line}" for line in item.summary_lines), f"    {item.source_line}"]
    return "\n".join(lines)


def render_brief_text(brief: WeeklyBrief) -> str:
    def section(heading: str, items: tuple[BriefItem, ...]) -> str:
        body = "\n\n".join(render_item_text(i) for i in sorted(items, key=lambda i: i.rank)) or EMPTY_SECTION_TEXT
        return f"### {heading}\n\n{body}"
    return section(HEADING_DOMESTIC, brief.domestic) + "\n\n" + section(HEADING_OVERSEAS, brief.overseas)
