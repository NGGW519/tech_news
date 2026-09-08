"""요약 — Gemini 배치 호출 → BriefItem (SPEC 7절).

    호출 단위   섹션당 1회 (국내 1 + 해외 1). 배치가 통째로 실패하면 그 섹션 전원 fallback
    입력 선택   enrich_text → description → 제목만 (SPEC 6.5절)
    응답 스키마 {"items":[{"id":"...","lines":["문장1","문장2"]}]} — id 로만 매칭, 순서 불신
    형식 위반   3문장↑ → 앞 2문장 · 40자 초과 → 그대로 쓰고 경고 · 0문장 → 그 항목만 fallback · 재호출 없음
    fallback    description[:120] → enrich_text[:120] → 요약 줄 생략, 말미 " ⚠️ 자동 요약 실패". status 는 셋 다 FALLBACK_DESCRIPTION

네트워크는 `call` 하나로 주입한다: call(request_dict) -> response_dict. 기본 구현 call_gemini 만 실제 API 를 친다.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from src.http import post_json
from src.schema import BriefItem, Origin, RankedArticle, RawArticle, SummaryStatus

log = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-3.8-flash"          # SPEC 7절 "모델 ID" (2026-09-08 확인). 재확인 규칙은 SPEC 참조
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_TIMEOUT = 60

MAX_SENTENCES = 2
MAX_CHARS_PER_SENTENCE = 40
FALLBACK_CHARS = 120
FALLBACK_SUFFIX = " ⚠️ 자동 요약 실패"
TITLE_ONLY_INSTRUCTION = "본문이 제목뿐인 경우 제목에 없는 사실을 추측하지 말 것.\n두 문장 모두 제목의 맥락 설명에만 쓸 것."

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "lines": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "lines"],
            },
        }
    },
    "required": ["items"],
}

Call = Callable[[dict[str, Any]], dict[str, Any]]


# ─────────────────────────────────────────────────────────────────────────────
# 입력 선택 (SPEC 6.5절 우선순위)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SummaryInput:
    source: str            # "enrich_text" | "description" | "title_only"
    text: str | None


def resolve_input(article: RawArticle) -> SummaryInput:
    enrich_text = article.extra.get("enrich_text")
    if enrich_text:
        return SummaryInput("enrich_text", enrich_text)
    if article.description:
        return SummaryInput("description", article.description)
    return SummaryInput("title_only", None)


# ─────────────────────────────────────────────────────────────────────────────
# 프롬프트 · 요청
# ─────────────────────────────────────────────────────────────────────────────

_COMMON_RULES = """규칙
- 각 항목을 한글 두 문장으로 요약한다. 정확히 2문장, 문장당 40자 이내
- 제목에 이미 담긴 내용은 반복하지 않는다
- 문장 1 = 제목이 말하지 않은 구체적 사실. 반드시 본문에 있는 것만 쓴다
- 문장 2 = 왜 중요한지 또는 맥락
- 제목에 정보가 없는 경우(낚시성 제목)에는 두 문장 모두 사실 전달에 쓴다
- JSON 만 출력한다. 마크다운 펜스 금지. 형식: {"items":[{"id":"...","lines":["문장1","문장2"]}]}
- id 는 아래 항목의 id 를 글자 그대로 쓴다"""

_DOMESTIC_HEAD = "아래는 이번 주 국내 IT / 피지컬 AI 뉴스 {n}건이다."
_OVERSEAS_HEAD = """아래는 이번 주 해외 IT / 피지컬 AI 뉴스 {n}건이다. 제목과 본문은 영문이다.
요약은 한글로 쓰되, 모델명·회사명·제품명 같은 고유명사는 원문 표기를 유지한다."""


def build_prompt(origin: Origin, items: Iterable[RankedArticle]) -> str:
    items = list(items)
    head = (_DOMESTIC_HEAD if origin is Origin.DOMESTIC else _OVERSEAS_HEAD).format(n=len(items))
    blocks, any_title_only = [], False
    for r in items:
        chosen = resolve_input(r.article)
        body = chosen.text if chosen.text else "(본문 없음 — 제목뿐)"
        any_title_only |= chosen.source == "title_only"
        blocks.append(f"[id: {r.article.article_id}]\n제목: {r.display_title}\n본문: {body}")
    parts = [head, _COMMON_RULES]
    if any_title_only:
        parts.append(TITLE_ONLY_INSTRUCTION)            # SPEC 7절 조건부 규칙
    parts.append("항목\n\n" + "\n\n".join(blocks))
    return "\n\n".join(parts)


def build_request(prompt: str) -> dict[str, Any]:
    return {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
            "temperature": 0.2,
        },
    }


def call_gemini(request: dict[str, Any], *, api_key: str, model: str = GEMINI_MODEL) -> dict[str, Any]:
    return post_json(GEMINI_URL.format(model=model), request, headers={"x-goog-api-key": api_key}, timeout=GEMINI_TIMEOUT)


# ─────────────────────────────────────────────────────────────────────────────
# 응답 파싱 · 형식 규칙
# ─────────────────────────────────────────────────────────────────────────────

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_response(payload: dict[str, Any]) -> dict[str, list[str]]:
    """generateContent 응답 → {article_id: lines}. 파싱 실패는 예외 = 배치 실패 (SPEC 7절)."""
    text = payload["candidates"][0]["content"]["parts"][0]["text"]
    data = json.loads(_FENCE.sub("", text.strip()))
    out: dict[str, list[str]] = {}
    for item in data["items"]:
        lines = item.get("lines")
        if isinstance(item.get("id"), str) and isinstance(lines, list):
            out[item["id"]] = [str(l).strip() for l in lines if str(l).strip()]
    return out


def apply_format_rules(lines: list[str], article_id: str) -> tuple[str, ...]:
    if len(lines) > MAX_SENTENCES:
        log.warning("summary %s: %d문장 → 앞 %d문장만 사용", article_id, len(lines), MAX_SENTENCES)
        lines = lines[:MAX_SENTENCES]
    for line in lines:
        if len(line) > MAX_CHARS_PER_SENTENCE:
            log.warning("summary %s: %d자 > %d자 — 자르지 않고 그대로 사용: %r", article_id, len(line), MAX_CHARS_PER_SENTENCE, line)
    return tuple(lines)


# ─────────────────────────────────────────────────────────────────────────────
# fallback · BriefItem
# ─────────────────────────────────────────────────────────────────────────────


def fallback_lines(article: RawArticle) -> tuple[str, ...]:
    source = article.description or article.extra.get("enrich_text") or ""
    if not source:
        return ()                                       # 3순위: 요약 줄 생략
    return (source[:FALLBACK_CHARS].rstrip() + FALLBACK_SUFFIX,)


def to_brief_item(ranked: RankedArticle, lines: tuple[str, ...], status: SummaryStatus) -> BriefItem:
    a = ranked.article
    url = a.extra.get("anchor_url", a.url) if a.origin is Origin.OVERSEAS else a.url   # SPEC 4절 앵커 URL
    return BriefItem(
        rank=ranked.rank, origin=a.origin, title=ranked.display_title, url=url, summary_lines=lines,
        publisher=a.publisher, published_at=a.published_at, summary_status=status, source_article_id=a.article_id,
    )


def summarize_section(items: list[RankedArticle], *, call: Call) -> list[BriefItem]:
    """한 섹션(국내 또는 해외)을 배치 1회로 요약한다. 실패는 fallback 으로 흡수하고 예외를 내지 않는다."""
    if not items:
        return []
    origins = {r.origin for r in items}
    if len(origins) != 1:
        raise ValueError("한 배치에 국내·해외가 섞였다 — 섹션별로 호출한다 (SPEC 7절)")
    origin = origins.pop()

    by_id: dict[str, list[str]] = {}
    try:
        by_id = parse_response(call(build_request(build_prompt(origin, items))))
    except Exception as e:  # noqa: BLE001 — 호출·파싱 실패 모두 배치 실패
        log.warning("summary batch failed (%s): %s", origin.value, e)

    out = []
    for r in sorted(items, key=lambda x: x.rank):
        lines = apply_format_rules(by_id.get(r.article.article_id, []), r.article.article_id)
        if lines:
            out.append(to_brief_item(r, lines, SummaryStatus.GEMINI))
        else:
            out.append(to_brief_item(r, fallback_lines(r.article), SummaryStatus.FALLBACK_DESCRIPTION))
    return out
