#!/usr/bin/env python3
"""카카오 "나에게 보내기"용 refresh token 발급 → .env 에 KAKAO_REFRESH_TOKEN 저장 (SPEC 8절·12절).

표준 라이브러리만 쓴다. 토큰 값은 화면에 찍지 않는다 — .env 에만 쓴다.

사전 준비 (developers.kakao.com 새 콘솔 기준, 2026-09-08 문서 확인, 한 번만):
  1. [앱] > [플랫폼 키] > [REST API 키]            → 키 값을 .env 의 KAKAO_REST_API_KEY 에
  2. 같은 화면의 [클라이언트 시크릿]                → 새 콘솔의 REST API 키는 **기본으로 켜져 있다.**
                                                    코드 값을 .env 의 KAKAO_CLIENT_SECRET 에 (없으면 KOE010)
  3. [카카오 로그인] > [사용 설정]                  → 상태 ON, 리다이렉트 URI 등록
                                                    (기본값 http://localhost:8080/oauth)
  4. [카카오 로그인] > [동의항목]                   → "카카오톡 메시지 전송"(talk_message) 을 선택 동의로
  5. [플랫폼] > Web > 사이트 도메인                 → https://www.notion.so 추가.
                                                    메시지 버튼 링크는 등록된 도메인만 허용되고, 아니면 등록된
                                                    첫 도메인(localhost)으로 조용히 바뀐다 (실측 2026-09-08)

사용:
  python3 scripts/kakao_refresh_token.py            # 발급 → .env 저장
  python3 scripts/kakao_refresh_token.py --test     # 저장된 refresh token 으로 access token 을 받아 나에게 시험 메시지 1통

흐름 (카카오 로그인 REST API 문서, 2026-09-08 확인):
  GET  https://kauth.kakao.com/oauth/authorize?response_type=code&client_id=...&redirect_uri=...&scope=talk_message
       → 브라우저에서 로그인·동의 → redirect_uri?code=XXXX 로 이동 (페이지가 안 떠도 주소창의 code 만 있으면 된다)
  POST https://kauth.kakao.com/oauth/token  grant_type=authorization_code ...
       → access_token(12시간) + refresh_token(60일) + refresh_token_expires_in
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

AUTHORIZE_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"
MEMO_SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
SCOPE = "talk_message"
DEFAULT_REDIRECT_URI = "http://localhost:8080/oauth"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV = PROJECT_ROOT / ".env"


# ─────────────────────────────────────────────────────────────────────────────
# .env 읽기 / 쓰기 — KEY=VALUE 한 줄 형식. 값에 따옴표·공백을 넣지 않는다
# ─────────────────────────────────────────────────────────────────────────────


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def write_env_key(path: Path, key: str, value: str) -> str:
    """해당 키 줄을 교체하거나(있으면) 맨 끝에 추가한다(없으면). 다른 줄은 손대지 않는다."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    new_line = f"{key}={value}"
    for i, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == key:
            lines[i] = new_line
            action = "교체"
            break
    else:
        lines.append(new_line)
        action = "추가"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return action


# ─────────────────────────────────────────────────────────────────────────────
# 카카오 호출
# ─────────────────────────────────────────────────────────────────────────────


def post_form(url: str, form: dict[str, str], headers: dict[str, str] | None = None) -> dict:
    data = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded;charset=utf-8")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        sys.exit(f"HTTP {e.code} {url}\n{body}\n{_hint_for(body)}")


# 카카오 로그인 문제 해결 문서(2026-09-08 확인)의 토큰 요청 에러 코드 → 사람이 할 일
_HINTS = {
    "KOE010": "→ 클라이언트 시크릿이 켜져 있는데 안 보냈거나 틀렸습니다. "
              "[앱] > [플랫폼 키] > [REST API 키] > [클라이언트 시크릿] 코드를 .env 의 KAKAO_CLIENT_SECRET 에 넣으세요.",
    "KOE303": "→ 인가 요청과 토큰 요청의 redirect_uri 가 다릅니다. .env 의 KAKAO_REDIRECT_URI 를 확인하세요.",
    "KOE006": "→ 등록되지 않은 리다이렉트 URI 입니다. [카카오 로그인] > [사용 설정] 에 "
              f"{DEFAULT_REDIRECT_URI} (또는 .env 의 KAKAO_REDIRECT_URI 값) 을 등록하세요.",
    "KOE320": "→ code 가 이미 쓰였거나 만료됐습니다. 스크립트를 다시 실행해 새 code 를 받으세요.",
    "KOE101": "→ client_id 가 REST API 키가 아닙니다. 네이티브/JavaScript 키가 아니라 REST API 키인지 확인하세요.",
}


def _hint_for(body: str) -> str:
    return next((hint for code, hint in _HINTS.items() if code in body), "")


def extract_code(pasted: str) -> str:
    """리다이렉트된 전체 URL 이든 code 값만이든 받아서 code 를 꺼낸다."""
    pasted = pasted.strip()
    if "code=" in pasted:
        query = urllib.parse.urlsplit(pasted).query or pasted.split("?", 1)[-1]
        code = urllib.parse.parse_qs(query).get("code", [""])[0]
        if code:
            return code
    return pasted


def issue(env_path: Path) -> None:
    env = read_env(env_path)
    rest_key = env.get("KAKAO_REST_API_KEY")
    if not rest_key:
        sys.exit(f"{env_path} 에 KAKAO_REST_API_KEY 가 없습니다. 먼저 REST API 키를 넣으세요.")
    redirect_uri = env.get("KAKAO_REDIRECT_URI", DEFAULT_REDIRECT_URI)
    client_secret = env.get("KAKAO_CLIENT_SECRET", "")

    auth_url = AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": rest_key,
        "redirect_uri": redirect_uri,
        "scope": SCOPE,
    })
    print("1) 아래 URL 을 브라우저에서 열고 로그인 → '카카오톡 메시지 전송' 동의")
    print()
    print("   " + auth_url)
    print()
    print(f"2) 주소창이 {redirect_uri}?code=... 로 바뀝니다. 페이지는 안 떠도 됩니다.")
    print("   그 주소 전체(또는 code 값만)를 여기에 붙여넣으세요.")
    print()
    code = extract_code(input("code 또는 URL> "))
    if not code:
        sys.exit("code 가 비어 있습니다.")

    form = {
        "grant_type": "authorization_code",
        "client_id": rest_key,
        "redirect_uri": redirect_uri,
        "code": code,
    }
    if client_secret:
        form["client_secret"] = client_secret
    tokens = post_form(TOKEN_URL, form)

    refresh = tokens.get("refresh_token")
    if not refresh:
        sys.exit("응답에 refresh_token 이 없습니다:\n" + json.dumps(tokens, ensure_ascii=False, indent=2))
    granted = tokens.get("scope", "")
    if SCOPE not in granted.split():
        print(f"경고: 동의된 scope 에 {SCOPE} 가 없습니다 (scope={granted!r}). "
              "동의항목에서 '카카오톡 메시지 전송'을 켰는지 확인하세요.", file=sys.stderr)

    action = write_env_key(env_path, "KAKAO_REFRESH_TOKEN", refresh)
    days = int(tokens.get("refresh_token_expires_in", 0)) // 86400
    print()
    print(f"완료: {env_path} 에 KAKAO_REFRESH_TOKEN {action} (유효기간 약 {days}일, scope={granted})")
    print("     값은 출력하지 않았습니다. --test 로 시험 발송해 보세요.")


def test_send(env_path: Path) -> None:
    env = read_env(env_path)
    rest_key, refresh = env.get("KAKAO_REST_API_KEY"), env.get("KAKAO_REFRESH_TOKEN")
    if not rest_key or not refresh:
        sys.exit(f"{env_path} 에 KAKAO_REST_API_KEY 와 KAKAO_REFRESH_TOKEN 이 모두 있어야 합니다.")

    form = {"grant_type": "refresh_token", "client_id": rest_key, "refresh_token": refresh}
    if env.get("KAKAO_CLIENT_SECRET"):
        form["client_secret"] = env["KAKAO_CLIENT_SECRET"]
    tokens = post_form(TOKEN_URL, form)
    access = tokens["access_token"]
    if tokens.get("refresh_token"):  # 잔여 1개월 미만이면 새 refresh_token 이 같이 온다 — 그대로 저장
        write_env_key(env_path, "KAKAO_REFRESH_TOKEN", tokens["refresh_token"])
        print("refresh token 이 갱신되어 .env 를 업데이트했습니다.")

    template = {
        "object_type": "text",
        "text": "📡 tech_news 시험 발송 — 이 메시지가 보이면 KAKAO_REFRESH_TOKEN 설정이 끝난 것입니다.",
        "link": {"web_url": "https://www.notion.so", "mobile_web_url": "https://www.notion.so"},
        "button_title": "확인",
    }
    result = post_form(
        MEMO_SEND_URL,
        {"template_object": json.dumps(template, ensure_ascii=False)},
        headers={"Authorization": f"Bearer {access}"},
    )
    print("발송 응답:", json.dumps(result, ensure_ascii=False), "→ result_code 0 이면 성공. 카톡 '나와의 채팅'을 확인하세요.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--test", action="store_true", help="저장된 refresh token 으로 나에게 시험 메시지 1통")
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV, help=f".env 경로 (기본 {DEFAULT_ENV})")
    args = parser.parse_args()
    (test_send if args.test else issue)(args.env)


if __name__ == "__main__":
    main()
