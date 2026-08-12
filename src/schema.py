"""모듈 간 데이터 계약 (SPEC 3절 "출력 인터페이스만 통일").

파이프라인 흐름과 이 파일의 타입 대응:

    수집 (네이버 / HN·Reddit·RSS)  ->  RawArticle
    중복 제거 · 랭킹               ->  RankedArticle (+ RankEvidence)
    Gemini 요약                    ->  BriefItem
    Notion 렌더링 · 카카오 알림     ->  WeeklyBrief (WeekMeta + BriefItem 목록)
    주차 계산 (목요일 앵커)         ->  WeekMeta

── 국내/해외 비대칭 처리 원칙 ────────────────────────────────────────────────
SPEC 3절이 못박은 대로 국내·해외는 **별개 파이프라인**이고 공유하는 것은
출력 타입뿐이다. 그래서 타입을 국내용/해외용으로 쪼개지 않고,
`origin` 을 판별자(discriminator)로 둔 **단일 타입 + 반쪽 선택 필드** 구조를 쓴다.

  - 신호 비대칭  : 해외는 points/comments/upvotes 가 있고 국내는 없다.
                   -> `RawMetrics` 의 모든 필드를 Optional 로 두고, 국내는 전부 None.
                      "신호가 없음(None)" 과 "신호가 0점(0)" 을 반드시 구분한다.
  - 랭킹 근거 비대칭: 국내는 클러스터 크기, 해외는 정규화 점수.
                   -> `RankEvidence` 한 타입에 양쪽 필드를 모두 두되,
                      `origin` 이 어느 쪽 필드가 유효한지 결정한다.
                      정렬에 실제로 쓰인 값은 `RankedArticle.sort_score` 로 통일한다.
  - 제목 비대칭  : 국내는 접두사 제거, 해외는 영문 원문 유지 (SPEC 4절).
                   -> `RawArticle.title` 은 수집 원문 그대로 보존하고,
                      출력용 제목은 `RankedArticle.display_title` 로 분리한다.
  - 요약 이후    : `BriefItem` 부터는 비대칭이 사라진다. 국내/해외 구분은
                   `origin` 하나로 남고, 렌더러는 섹션을 나누는 데만 쓴다.

── 날짜 · 시각 정책 (SPEC 5절: 모든 날짜 연산은 KST 기준) ────────────────────
  - 이 모듈의 모든 `datetime` 필드는 **tz-aware 이며 KST(UTC+9) 로 정규화**된다.
    naive datetime 은 계약 위반으로 본다 (`ensure_kst()` 참조).
    HN/Reddit 은 UTC(epoch/Z) 로 주므로 수집 단계에서 반드시 변환해 담는다.
  - 이 모듈의 모든 `date` 필드는 **KST 달력 기준 날짜**다.
    Actions 런너는 UTC이므로 `date.today()` 를 그대로 쓰면 안 된다 (`now_kst()` 참조).
  - 직렬화 시 datetime 은 `+09:00` 오프셋이 붙은 ISO 8601, date 는 `YYYY-MM-DD`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# 시간대
# ─────────────────────────────────────────────────────────────────────────────

KST = timezone(timedelta(hours=9), "KST")  # SPEC 5절 기준 시간대. 이 프로젝트의 유일한 로컬 타임존


def now_kst() -> datetime:
    """현재 시각(KST). UTC 런너에서도 안전하도록 항상 이 함수를 경유한다."""
    return datetime.now(KST)


def ensure_kst(value: datetime) -> datetime:
    """tz-aware 인지 검증하고 KST 로 변환한다. naive 는 계약 위반이므로 예외."""
    if value.tzinfo is None:
        raise ValueError(f"naive datetime 은 허용하지 않는다 (KST 명시 필요): {value!r}")
    return value.astimezone(KST)


# ─────────────────────────────────────────────────────────────────────────────
# 열거형 — JSON 직렬화를 위해 모두 str 기반
# ─────────────────────────────────────────────────────────────────────────────


class Origin(str, Enum):
    """국내/해외 판별자. 파이프라인 분기와 Notion 섹션 구분에 함께 쓰인다."""

    DOMESTIC = "domestic"  # 국내 — 네이버, 인기도 신호 없음
    OVERSEAS = "overseas"  # 해외 — HN/Reddit/RSS, 인기도 신호 있음


class SourceKind(str, Enum):
    """수집 소스 종류 (SPEC 6절). 정규화 방식과 원시 지표 해석이 이 값에 달려 있다."""

    NAVER_NEWS = "naver_news"    # 네이버 검색 API (news)
    HACKER_NEWS = "hacker_news"  # HN Algolia API — points, num_comments
    REDDIT = "reddit"            # r/robotics, r/MachineLearning — ups
    RSS = "rss"                  # arXiv, NVIDIA/DeepMind 블로그 등 보조 RSS — 점수 없음


class SummaryStatus(str, Enum):
    """요약 생성 경로 (SPEC 7절 2단 fallback). 어느 경로로 만들어졌는지 추적용."""

    GEMINI = "gemini"                              # 정상 — 호출 + JSON 파싱까지 성공
    FALLBACK_DESCRIPTION = "fallback_description"  # 실패 — 원문 description 그대로 사용


# ─────────────────────────────────────────────────────────────────────────────
# 1. RawArticle — 수집 직후
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RawMetrics:
    """소스가 제공한 **원시** 인기도 지표 (SPEC 6절: 정규화는 랭킹 단계 책임).

    국내(네이버)는 인기도 API 자체가 없으므로 세 필드 모두 None 으로 남는다.
    0 이 아니라 None 인 것이 핵심이다 — "지표 없음" 과 "0점" 은 다른 사건이고,
    정규화 단계에서 0점짜리를 분모에 넣으면 국내 기사를 잘못 순위매기게 된다.
    """

    points: int | None = None    # HN points. 국내 None, Reddit None
    comments: int | None = None  # HN num_comments / Reddit num_comments. 국내 None
    upvotes: int | None = None   # Reddit ups(score). 국내 None, HN None

    @property
    def has_signal(self) -> bool:
        """랭킹에 쓸 인기도 신호가 하나라도 있는가 (국내 · 보조 RSS 는 False)."""
        return any(v is not None for v in (self.points, self.comments, self.upvotes))

    def to_dict(self) -> dict[str, Any]:
        return {"points": self.points, "comments": self.comments, "upvotes": self.upvotes}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RawMetrics:
        return cls(
            points=data.get("points"),
            comments=data.get("comments"),
            upvotes=data.get("upvotes"),
        )


@dataclass(frozen=True)
class RawArticle:
    """수집 직후의 기사 한 건. 국내/해외 공통 형태이며 원시 정보를 손실 없이 보존한다.

    이 타입까지가 네트워크 호출부의 산출물이다. 여기서부터 아래는 전부 순수 로직이며
    API 키 없이 fixture 만으로 단위 테스트가 가능해야 한다 (SPEC 3절 유의점 4).
    """

    article_id: str          # 파이프라인 전역 고유 ID. "<source>:<소스 내 ID>" 규약 (예: "hn:41236780")
    origin: Origin           # 국내/해외 판별자
    source: SourceKind       # 어느 수집기가 만들었는지
    title: str               # 제목 원문. HTML 태그/엔티티만 푼 상태이고 [단독] 등 접두사는 **유지**
    url: str                 # 원문 링크. 국내는 naver originallink 우선(없으면 link), 해외는 대상 URL
    publisher: str           # 출력용 매체명 (SPEC 4절 "출처"). 국내는 언론사명, 해외는 도메인/피드명
    published_at: datetime   # 발행 시각. tz-aware KST. 해외 플랫폼 게시 시각을 UTC->KST 변환한 값
    collected_at: datetime   # 이 레코드를 만든 시각. tz-aware KST. 재현·디버깅용
    metrics: RawMetrics      # 원시 인기도 지표. 국내는 전 필드 None (위 비대칭 원칙 참조)
    description: str = ""    # 원문 요약/본문 도입부. 없으면 "" — 요약 실패 시 fallback 원천 (SPEC 7절)
    query: str | None = None  # 이 기사를 데려온 질의. 국내는 네이버 키워드, 해외는 서브레딧/피드 이름
    extra: dict[str, Any] = field(default_factory=dict)  # 소스 원본 필드 보존 (naver link, HN author 등)

    def to_dict(self) -> dict[str, Any]:
        return {
            "article_id": self.article_id,
            "origin": self.origin.value,
            "source": self.source.value,
            "title": self.title,
            "url": self.url,
            "publisher": self.publisher,
            "published_at": ensure_kst(self.published_at).isoformat(),
            "collected_at": ensure_kst(self.collected_at).isoformat(),
            "metrics": self.metrics.to_dict(),
            "description": self.description,
            "query": self.query,
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RawArticle:
        return cls(
            article_id=data["article_id"],
            origin=Origin(data["origin"]),
            source=SourceKind(data["source"]),
            title=data["title"],
            url=data["url"],
            publisher=data["publisher"],
            published_at=ensure_kst(datetime.fromisoformat(data["published_at"])),
            collected_at=ensure_kst(datetime.fromisoformat(data["collected_at"])),
            metrics=RawMetrics.from_dict(data.get("metrics") or {}),
            description=data.get("description", ""),
            query=data.get("query"),
            extra=dict(data.get("extra") or {}),
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. RankedArticle — 랭킹 후
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RankEvidence:
    """왜 이 순위인지에 대한 근거. 국내/해외가 서로 다른 반쪽만 채운다.

    `origin` 이 어느 반쪽이 유효한지 결정하는 판별자다.
      DOMESTIC -> cluster_* 만 유효, normalized_score/score_components 는 비어 있다
      OVERSEAS -> normalized_score/score_components/merged_* 만 유효, cluster_* 는 비어 있다
    두 파이프라인이 공유 코드가 거의 없으므로 타입을 나누는 대신 한 타입에 담고,
    소비자(Notion 렌더러·테스트)는 origin 으로만 분기하면 되게 했다.
    """

    origin: Origin  # 아래 필드 중 어느 쪽이 유효한지 결정하는 판별자

    # ── 국내 전용 (SPEC 6절: 자카드 유사도 >= 0.5 클러스터링, 크기 = 이슈 강도 프록시) ──
    cluster_size: int | None = None                     # 같은 사건을 보도한 기사 수. 국내 정렬 기준값
    cluster_article_ids: tuple[str, ...] = ()           # 클러스터 구성원 article_id (대표 기사 포함)
    cluster_publishers: tuple[str, ...] = ()            # 보도 매체명 목록. 커버리지 근거 표시·검증용
    representative_reason: str | None = None            # 대표 선정 사유. 기본값 "earliest" (클러스터 내 최초 보도)

    # ── 해외 전용 (SPEC 6절: 소스별 점수 정규화 후 합산) ──
    normalized_score: float | None = None               # 정규화 점수 합계. 해외 정렬 기준값
    score_components: dict[str, float] = field(default_factory=dict)  # 소스·지표별 정규화 기여분 (예: {"hn_points": 0.82})
    merged_article_ids: tuple[str, ...] = ()            # 같은 URL 이 여러 플랫폼에 올라와 합산된 원본 ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "origin": self.origin.value,
            "cluster_size": self.cluster_size,
            "cluster_article_ids": list(self.cluster_article_ids),
            "cluster_publishers": list(self.cluster_publishers),
            "representative_reason": self.representative_reason,
            "normalized_score": self.normalized_score,
            "score_components": dict(self.score_components),
            "merged_article_ids": list(self.merged_article_ids),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RankEvidence:
        return cls(
            origin=Origin(data["origin"]),
            cluster_size=data.get("cluster_size"),
            cluster_article_ids=tuple(data.get("cluster_article_ids") or ()),
            cluster_publishers=tuple(data.get("cluster_publishers") or ()),
            representative_reason=data.get("representative_reason"),
            normalized_score=data.get("normalized_score"),
            score_components=dict(data.get("score_components") or {}),
            merged_article_ids=tuple(data.get("merged_article_ids") or ()),
        )


@dataclass(frozen=True)
class RankedArticle:
    """랭킹을 마친 기사. 국내 5건 / 해외 5건이 각각 rank 1..5 로 만들어진다."""

    article: RawArticle      # 원본 기사 (대표 기사). 원시 정보는 여기 그대로 남는다
    rank: int                # 1부터 시작하는 순위. 국내/해외 각각 독립적으로 1..5
    display_title: str       # 출력용 제목. 국내는 접두사 제거본, 해외는 **영문 원문 그대로** (SPEC 4절)
    sort_score: float        # 실제 정렬에 쓴 값. 국내=클러스터 크기, 해외=정규화 점수 합계 (타입 통일용)
    evidence: RankEvidence   # 위 sort_score 가 어떻게 나왔는지에 대한 근거

    @property
    def origin(self) -> Origin:
        """국내/해외 판별자 (원본 기사에서 위임)."""
        return self.article.origin

    def to_dict(self) -> dict[str, Any]:
        return {
            "article": self.article.to_dict(),
            "rank": self.rank,
            "display_title": self.display_title,
            "sort_score": self.sort_score,
            "evidence": self.evidence.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RankedArticle:
        return cls(
            article=RawArticle.from_dict(data["article"]),
            rank=data["rank"],
            display_title=data["display_title"],
            sort_score=float(data["sort_score"]),
            evidence=RankEvidence.from_dict(data["evidence"]),
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. BriefItem — 요약 후 (Notion 렌더링 입력)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BriefItem:
    """SPEC 4절 출력 블록 한 개를 만들기 위한 최소·완전한 정보.

        **{rank}. {title}**          <- title 에 url 앵커 (URL 문자열 노출 금지)
            {summary_lines[0]}
            {summary_lines[1]}
            {publisher} · {MM/DD}    <- source_line 프로퍼티

    여기서부터는 국내/해외 구조가 완전히 같다. origin 은 섹션 분류에만 쓴다.
    """

    rank: int                        # 섹션 내 순위 (1..5). 출력 번호로 그대로 쓴다
    origin: Origin                   # 국내/해외 섹션 분류용
    title: str                       # 앵커 텍스트. RankedArticle.display_title 을 그대로 승계
    url: str                         # 앵커 링크 (SPEC 4절: 본문에 URL 노출 금지)
    summary_lines: tuple[str, ...]   # 한글 요약 문장들. 정상 2문장·문장당 40자 이내 (SPEC 7절)
    publisher: str                   # 출처 매체명
    published_at: datetime           # 발행 시각. tz-aware KST. 출력에는 MM/DD 만 쓴다
    summary_status: SummaryStatus    # 요약 경로 (Gemini / fallback). 품질 추적용
    source_article_id: str           # 원본 RawArticle.article_id. 렌더 결과 -> 수집 원본 역추적용

    @property
    def published_label(self) -> str:
        """출력용 발행일 문자열 `MM/DD` (KST 기준)."""
        return ensure_kst(self.published_at).strftime("%m/%d")

    @property
    def source_line(self) -> str:
        """출력용 출처 줄 `매체명 · MM/DD` (SPEC 4절)."""
        return f"{self.publisher} · {self.published_label}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "origin": self.origin.value,
            "title": self.title,
            "url": self.url,
            "summary_lines": list(self.summary_lines),
            "publisher": self.publisher,
            "published_at": ensure_kst(self.published_at).isoformat(),
            "summary_status": self.summary_status.value,
            "source_article_id": self.source_article_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BriefItem:
        return cls(
            rank=data["rank"],
            origin=Origin(data["origin"]),
            title=data["title"],
            url=data["url"],
            summary_lines=tuple(data["summary_lines"]),
            publisher=data["publisher"],
            published_at=ensure_kst(datetime.fromisoformat(data["published_at"])),
            summary_status=SummaryStatus(data["summary_status"]),
            source_article_id=data["source_article_id"],
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. WeekMeta — 주차 정보 (SPEC 5절 목요일 앵커 규칙의 산출물)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WeekMeta:
    """주차 계산 결과. Notion 월 페이지·주차 토글·멱등성 체크·카톡 문구의 공통 입력.

    모든 필드는 **KST 달력 기준 date** 다 (SPEC 5절). Actions 런너는 UTC 이므로
    이 값을 만드는 쪽에서 반드시 KST 로 변환한 뒤 채운다.
    year/month/week_no 는 anchor(목요일)에서 파생되지만, 계산 결과를 다시 계산하지 않고
    소비할 수 있도록 필드로 명시해 둔다 — 귀속 규칙이 바뀌어도 소비자는 영향받지 않는다.
    """

    run_date: date      # 실행일 (KST 월요일)
    window_start: date  # 수집 창 시작 = run_date - 7일 (직전 월요일 00:00 KST)
    window_end: date    # 수집 창 종료 = run_date - 1일 (일요일 23:59 KST)
    anchor: date        # 귀속 기준일 = window_start + 3일 (그 주 목요일)
    year: int           # 귀속 연도 = anchor.year (월을 넘나드는 주 때문에 run_date 와 다를 수 있음)
    month: int          # 귀속 월 = anchor.month
    week_no: int        # 그 달의 n번째 목요일 = (anchor.day - 1) // 7 + 1 (5주차 발생은 정상)

    @property
    def month_page_title(self) -> str:
        """Notion 월별 페이지 제목 `2026-08` (SPEC 5절)."""
        return f"{self.year:04d}-{self.month:02d}"

    @property
    def week_key(self) -> str:
        """주차 식별자 `8월 2주`. 날짜 범위를 뺀 형태 — 멱등성 startswith 비교의 기준 (SPEC 9절)."""
        return f"{self.month}월 {self.week_no}주"

    @property
    def week_label(self) -> str:
        """주차 토글 라벨 `8월 2주 (08/10~08/16)`. 날짜 범위는 실제 수집 창 그대로 (SPEC 5절)."""
        return f"{self.week_key} ({self.window_start:%m/%d}~{self.window_end:%m/%d})"

    @property
    def window_start_dt(self) -> datetime:
        """수집 창 시작 경계 (KST 월요일 00:00:00). 포함(inclusive)."""
        return datetime.combine(self.window_start, time.min, tzinfo=KST)

    @property
    def window_end_dt(self) -> datetime:
        """수집 창 종료 경계 (KST 일요일 23:59:59.999999). 포함(inclusive)."""
        return datetime.combine(self.window_end, time.max, tzinfo=KST)

    def contains(self, moment: datetime) -> bool:
        """해당 시각이 수집 창(7일 고정) 안에 있는가. 입력은 tz-aware 여야 한다."""
        return self.window_start_dt <= ensure_kst(moment) <= self.window_end_dt

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_date": self.run_date.isoformat(),
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "anchor": self.anchor.isoformat(),
            "year": self.year,
            "month": self.month,
            "week_no": self.week_no,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WeekMeta:
        return cls(
            run_date=date.fromisoformat(data["run_date"]),
            window_start=date.fromisoformat(data["window_start"]),
            window_end=date.fromisoformat(data["window_end"]),
            anchor=date.fromisoformat(data["anchor"]),
            year=data["year"],
            month=data["month"],
            week_no=data["week_no"],
        )


# ─────────────────────────────────────────────────────────────────────────────
# 5. WeeklyBrief — 한 주치 결과 묶음 (Notion 렌더러 · 카카오 알림의 단일 입력)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WeeklyBrief:
    """주차 메타 + 국내/해외 브리핑 목록. 렌더링 계층이 받는 최종 형태.

    국내·해외를 한 리스트에 담고 origin 으로 거르는 대신 두 필드로 분리했다.
    SPEC 4절 출력이 `### 국내` / `### 해외` 두 섹션으로 고정이고,
    각각 5건이라는 개수 계약도 여기서 바로 검증할 수 있기 때문이다.
    """

    week: WeekMeta                    # 주차 정보 (월 페이지 제목·토글 라벨의 출처)
    domestic: tuple[BriefItem, ...]   # 국내 섹션. rank 오름차순, 기대 길이 5
    overseas: tuple[BriefItem, ...]   # 해외 섹션. rank 오름차순, 기대 길이 5

    def to_dict(self) -> dict[str, Any]:
        return {
            "week": self.week.to_dict(),
            "domestic": [i.to_dict() for i in self.domestic],
            "overseas": [i.to_dict() for i in self.overseas],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WeeklyBrief:
        return cls(
            week=WeekMeta.from_dict(data["week"]),
            domestic=tuple(BriefItem.from_dict(d) for d in data.get("domestic") or ()),
            overseas=tuple(BriefItem.from_dict(d) for d in data.get("overseas") or ()),
        )
