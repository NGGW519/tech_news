"""텍스트 정제 — 수집 단계에서 즉시 수행한다 (SPEC 6절 "텍스트 정제 시점")."""

from __future__ import annotations

import html
import re

_TAG = re.compile(r"<[^>]+>")


def clean_html(value: str | None) -> str:
    """태그 제거 → HTML 엔티티 해제 → 양끝 공백 제거. None 은 빈 문자열."""
    if not value:
        return ""
    return html.unescape(_TAG.sub("", value)).strip()
