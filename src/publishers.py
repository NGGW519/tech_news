"""publisher 매핑 — 도메인 → 출력용 매체명 (SPEC 6절 "`publisher` — 도메인 → 매체명").

**데이터 전용 모듈이다.** 표와 조회 함수만 둔다. 수집·랭킹 로직을 넣지 않는다.
국내·해외 수집기가 둘 다 이 모듈을 import 하므로, 여기에 로직이 들어가면
"국내/해외는 별개 파이프라인"(SPEC 3절 유의점 1)이 무너진다.

조회 순서 (SPEC 6절):

    1. 4절 "출처 표기 규칙" 특례가 먼저다
         arxiv.org               -> "arXiv"
         reddit.com + self-post  -> "Reddit r/<서브레딧>"
       Reddit **링크 글**은 특례가 아니다 — 링크 대상 도메인으로 내려간다.
    2. DOMAIN_TO_NAME 에 있으면 그 값
    3. fallback — 등록 도메인에서 TLD 를 뗀 문자열을 **그대로** (대소문자 손대지 않음)

키는 **등록 도메인**(eTLD+1, 소문자)이다. 국내는 `originallink` 도메인,
해외는 **앵커용 URL**(`extra.anchor_url`, SPEC 4절) 도메인을 넣는다.

fallback 은 표를 채우기 전까지의 임시값이다. 출력에 낯선 소문자 매체명이 보이면
그 도메인을 표에 추가하는 것이 정상 운영 절차다.
"""

from __future__ import annotations

from urllib.parse import urlsplit

# ─────────────────────────────────────────────────────────────────────────────
# 표
# ─────────────────────────────────────────────────────────────────────────────

#: 등록 도메인(소문자) → 출력용 매체명.
#: `tests/fixtures/` 에 등장하는 도메인은 전부 들어 있어야 한다 (SPEC 6절).
DOMAIN_TO_NAME: dict[str, str] = {
    # ── 국내 — 네이버 originallink 도메인 ──
    "etnews.com": "전자신문",
    "newsis.com": "뉴시스",
    "news1.kr": "뉴스1",
    "yna.co.kr": "연합뉴스",
    "mk.co.kr": "매일경제",
    "sedaily.com": "서울경제",
    "asiae.co.kr": "아시아경제",
    "dt.co.kr": "디지털타임스",
    "mt.co.kr": "머니투데이",
    "zdnet.co.kr": "ZDNet Korea",
    "fnnews.com": "파이낸셜뉴스",
    # ── 해외 — 앵커용 URL 도메인 ──
    "techcrunch.com": "TechCrunch",
    "waymo.com": "Waymo",
    "github.com": "GitHub",
    "deepmind.google": "Google DeepMind",
    "1x.tech": "1X",
    "physicalintelligence.company": "Physical Intelligence",
    "agilityrobotics.com": "Agility Robotics",
    "tri.global": "Toyota Research Institute",
    "arxiv.org": "arXiv",           # 1의 특례와 같은 값. 표에도 두어 조회가 어느 경로든 같게
    "reddit.com": "Reddit",         # self-post 는 1의 특례가 우선. 크로스포스트 등 링크 글용
    "redd.it": "Reddit",            # i.redd.it / v.redd.it 미디어 링크 글
}

#: 등록 도메인이 3라벨인 2단 공개 접미사. `news.mt.co.kr` 의 등록 도메인은 `mt.co.kr` 이다.
#: 외부 의존성(`tldextract`) 대신 이 프로젝트가 실제로 만나는 접미사만 둔다 (SPEC 6절).
MULTI_LABEL_SUFFIXES: frozenset[str] = frozenset({
    "co.kr", "or.kr", "ne.kr", "go.kr", "re.kr", "pe.kr", "ac.kr",
    "co.jp", "co.uk", "com.au", "com.cn",
})

# 4절 특례 대상 도메인
ARXIV_DOMAIN = "arxiv.org"
REDDIT_DOMAIN = "reddit.com"


# ─────────────────────────────────────────────────────────────────────────────
# 조회 함수
# ─────────────────────────────────────────────────────────────────────────────


def host_of(url: str) -> str:
    """URL(또는 맨 호스트 문자열)에서 호스트만 소문자로 꺼낸다.

    userinfo(`user:pw@`)·포트·후행 점은 버린다. 스킴이 없어도 동작한다.
    """
    netloc = urlsplit(url).netloc if "://" in url else url.split("/", 1)[0]
    host = netloc.rsplit("@", 1)[-1]          # userinfo 제거
    if host.startswith("["):                  # IPv6 리터럴 — 그대로 둔다
        return host.lower()
    host = host.split(":", 1)[0]              # 포트 제거
    return host.lower().rstrip(".")


def _split_registered(host: str) -> tuple[str, str]:
    """호스트 → (등록 도메인, 공개 접미사). 라벨이 하나뿐이면 접미사는 빈 문자열."""
    labels = host.split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in MULTI_LABEL_SUFFIXES:
        return ".".join(labels[-3:]), ".".join(labels[-2:])
    if len(labels) >= 2:
        return ".".join(labels[-2:]), labels[-1]
    return host, ""


def registered_domain(url: str) -> str:
    """URL 의 등록 도메인(eTLD+1, 소문자). `DOMAIN_TO_NAME` 의 키와 같은 형태.

        https://www.etnews.com/2026...      -> etnews.com
        https://news.mt.co.kr/mtview.php   -> mt.co.kr
        https://old.reddit.com/r/robotics  -> reddit.com
    """
    return _split_registered(host_of(url))[0]


def _fallback_name(host: str) -> str:
    """등록 도메인에서 TLD 를 뗀 문자열. `zdnet.co.kr` -> `zdnet`, `example.com` -> `example`."""
    registered, suffix = _split_registered(host)
    if not suffix:
        return registered
    return registered[: -(len(suffix) + 1)]


def publisher_name(
    url: str,
    *,
    subreddit: str | None = None,
    is_self: bool = False,
) -> str:
    """`RawArticle.publisher` 에 넣을 매체명 (SPEC 4절 표기 규칙 + 6절 조회 순서).

    `url` 은 국내면 `originallink`, 해외면 **앵커용 URL** 이다.
    `subreddit`·`is_self` 는 Reddit 수집기만 넘긴다. self-post 인데 `subreddit` 이
    없으면 수집기 쪽 계약 위반이므로 조용히 `Reddit r/None` 을 만들지 않고 실패한다.
    """
    host = host_of(url)
    registered, _ = _split_registered(host)

    # 1. 4절 특례
    if registered == ARXIV_DOMAIN:
        return "arXiv"
    if registered == REDDIT_DOMAIN and is_self:
        if not subreddit:
            raise ValueError(f"Reddit self-post 인데 subreddit 이 없다: {url}")
        return f"Reddit r/{subreddit}"

    # 2. 표
    name = DOMAIN_TO_NAME.get(registered)
    if name is not None:
        return name

    # 3. fallback
    return _fallback_name(host)
