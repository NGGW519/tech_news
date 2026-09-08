"""HTTP 호출부 — 표준 라이브러리만. 수집기·보강·요약·Notion·카카오가 공유한다.

각 모듈은 이 함수들과 같은 시그니처의 가짜를 주입받아 fixture 로 검증한다 (SPEC 3절 유의점 4).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = "tech-news-brief/1.0 (+https://github.com/NGGW519/tech_news)"
DEFAULT_TIMEOUT = 10


class HttpError(RuntimeError):
    def __init__(self, status: int, url: str, body: str):
        super().__init__(f"HTTP {status} {url}: {body[:300]}")
        self.status, self.url, self.body = status, url, body


def _request(url: str, *, method: str, headers: dict[str, str], data: bytes | None, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        raise HttpError(e.code, url, e.read().decode("utf-8", errors="replace")) from None


def get_text(url: str, params: dict[str, str] | None = None, headers: dict[str, str] | None = None,
             timeout: float = DEFAULT_TIMEOUT) -> str:
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    _, body = _request(url, method="GET", headers=headers or {}, data=None, timeout=timeout)
    return body.decode("utf-8", errors="replace")


def get_json(url: str, params: dict[str, str] | None = None, headers: dict[str, str] | None = None,
             timeout: float = DEFAULT_TIMEOUT) -> Any:
    return json.loads(get_text(url, params, headers, timeout))


def post_json(url: str, payload: Any, headers: dict[str, str] | None = None,
              timeout: float = DEFAULT_TIMEOUT) -> Any:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    _, body = _request(url, method="POST", headers={"Content-Type": "application/json", **(headers or {})},
                       data=data, timeout=timeout)
    return json.loads(body.decode("utf-8")) if body else {}


def patch_json(url: str, payload: Any, headers: dict[str, str] | None = None,
               timeout: float = DEFAULT_TIMEOUT) -> Any:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    _, body = _request(url, method="PATCH", headers={"Content-Type": "application/json", **(headers or {})},
                       data=data, timeout=timeout)
    return json.loads(body.decode("utf-8")) if body else {}


def post_form(url: str, form: dict[str, str], headers: dict[str, str] | None = None,
              timeout: float = DEFAULT_TIMEOUT) -> Any:
    data = urllib.parse.urlencode(form).encode("utf-8")
    _, body = _request(url, method="POST",
                       headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8", **(headers or {})},
                       data=data, timeout=timeout)
    return json.loads(body.decode("utf-8")) if body else {}
