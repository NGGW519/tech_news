"""카카오톡 "나에게 보내기" (SPEC 8절).

    본문   📡 이번 주 테크 브리핑 · 국내 N / 해외 M   +   주차 라벨.  200자 제한이라 뉴스 내용은 넣지 않는다
    버튼   [Notion에서 보기] → 주차 토글 앵커 URL (없으면 월 페이지 URL)
    토큰   refresh token → access token. 잔여 1개월 미만이면 새 refresh token 이 같이 온다 → 호출자가 보관

HTTP 는 post_form 주입 가능. 발급 절차는 scripts/kakao_refresh_token.py.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src import http
from src.schema import WeekMeta

log = logging.getLogger(__name__)

TOKEN_URL = "https://kauth.kakao.com/oauth/token"
MEMO_SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
BUTTON_TITLE = "Notion에서 보기"
TEXT_LIMIT = 200      # 카카오 문서 확인(2026-09-08): 텍스트 템플릿 text 최대 200자


class KakaoError(RuntimeError):
    pass


@dataclass(frozen=True)
class Tokens:
    access_token: str
    new_refresh_token: str | None      # 잔여 1개월 미만일 때만 옴. 있으면 Secrets 를 갱신해야 한다


def build_message_text(week: WeekMeta, domestic_count: int, overseas_count: int) -> str:
    text = f"📡 이번 주 테크 브리핑 · 국내 {domestic_count} / 해외 {overseas_count}\n{week.week_label}"
    assert len(text) <= TEXT_LIMIT
    return text


def refresh_access_token(rest_api_key: str, refresh_token: str, client_secret: str | None = None, *,
                         post_form: Callable[..., Any] = http.post_form) -> Tokens:
    form = {"grant_type": "refresh_token", "client_id": rest_api_key, "refresh_token": refresh_token}
    if client_secret:
        form["client_secret"] = client_secret
    payload = post_form(TOKEN_URL, form)
    if "access_token" not in payload:
        raise KakaoError(f"token refresh failed: {payload}")
    new_refresh = payload.get("refresh_token")
    if new_refresh:
        log.warning("카카오 refresh token 이 재발급됐다 — KAKAO_REFRESH_TOKEN 시크릿을 갱신해야 한다 (잔여 1개월 미만)")
    return Tokens(access_token=payload["access_token"], new_refresh_token=new_refresh)


def send_to_me(access_token: str, text: str, link_url: str, *, post_form: Callable[..., Any] = http.post_form) -> None:
    template = {
        "object_type": "text",
        "text": text,
        "link": {"web_url": link_url, "mobile_web_url": link_url},
        "button_title": BUTTON_TITLE,
    }
    payload = post_form(MEMO_SEND_URL, {"template_object": json.dumps(template, ensure_ascii=False)},
                        {"Authorization": f"Bearer {access_token}"})
    if payload.get("result_code") != 0:
        raise KakaoError(f"send failed: {payload}")
