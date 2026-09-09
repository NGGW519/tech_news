# tech_news — 주간 테크 뉴스 브리핑 자동화

매주 월요일 아침, 지난 한 주간 가장 이슈가 됐던 **IT / Physical AI 뉴스**를 국내·해외 각 5건씩
자동으로 수집·요약해 Notion 에 쌓고, Notion 멘션으로 도착을 알린다.

- **축적**은 Notion — 검색·회고 가능한 자산으로 남긴다
- **도달**도 Notion — 주차 토글에 나를 @멘션하면 앱이 푸시를 보내고, 탭 1회로 그 줄에 도착한다

설계 명세는 [`SPEC.md`](SPEC.md) 에 있다. 이 README 는 입구이고, 규칙과 근거는 전부 SPEC 이 권위다.
SPEC 과 코드가 다르면 SPEC 이 맞다 (아니면 SPEC 을 먼저 고친다).

## 어떻게 도는가

```
GitHub Actions (매주 월 08:10 KST)
   │
   ├─ 국내 수집  NAVER API HUB 뉴스 검색 (피지컬 AI · 휴머노이드 · 자율주행 · 로봇)
   └─ 해외 수집  Hacker News (Algolia) + 보조 RSS (arXiv cs.RO/cs.AI · DeepMind · NVIDIA)
   │
   ├─ 랭킹       국내: 제목 유사도 클러스터링 → 많이 보도된 순
   │            해외: HN 점수 정규화 → URL 병합 → 상위 5 (미달 시 RSS 예비 풀)
   ├─ 본문 보강  해외 상위 5건 원문 앞 1500자 (HN 링크 글은 요약 입력이 없기 때문)
   ├─ 요약       Gemini — 섹션당 1회 배치, 한글 2문장. 실패 시 원문 description 으로 대체
   ├─ 멱등성     그 주 토글이 이미 있으면 종료
   └─ Notion     월 페이지 → 주차 토글 append + 나를 @멘션 → 폰 푸시
                 토글 라벨이 곧 알림 문구: "9월 1주 (08/31~09/06) · 국내 5 / 해외 5"
```

Notion 에는 이렇게 쌓인다:

```
📄 Tech News Scrap                       ← 루트 페이지 (Notion 통합을 여기에 연결)
   └─ 📄 2026-09                          ← 월별 페이지 (자동 생성)
       ├─ ▸ 9월 1주 (08/31~09/06) · 국내 5 / 해외 5
       └─ ▸ 9월 2주 (09/07~09/13) · 국내 5 / 해외 5
```

주차 토글을 열면:

```
### 국내

**1. 삼성전자, 휴머노이드용 AP 양산 착수**          ← 제목에 원문 링크
    2027년 상용화를 목표로 전용 연산 칩을 개발 중이다.
    기존 모바일 AP 대비 추론 성능을 4배로 끌어올렸다.
    전자신문 · 08/13

### 해외

**1. Figure raises $1.5B at $39B valuation**        ← 해외 제목은 번역하지 않는다 (검색 가능하도록)
    휴머노이드 스타트업 피규어가 시리즈 D를 마감했다.
    BMW 공장 실배치 실적이 평가에 결정적으로 작용했다.
    TechCrunch · 08/11
```

5건에 못 미치는 주는 확보된 만큼만 발행하고 건수를 라벨에 그대로 적는다 (`국내 3 / 해외 5`).
주 1회 실행이라 한 번 중단하면 그 주를 통째로 잃기 때문이다.

## 설정 (한 번만)

### 1. 자격 증명

| 변수 | 어디서 |
|---|---|
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | **NAVER API HUB** 의 Client ID / Secret (개발자센터 키가 아니다 — 검색 API 가 API HUB 로 이관됐다) |
| `GEMINI_API_KEY` | Google AI Studio (유료 Tier 1 권장 — 무료 티어 정책 리스크 회피) |
| `NOTION_TOKEN` | Notion Internal Integration 토큰. 루트 페이지에 이 통합을 **연결**해야 한다. 권한은 아래 2절 |
| `NOTION_ROOT_PAGE_ID` | 루트 페이지 ID |
| `NOTION_USER_ID` | 알림 멘션 대상(본인) UUID — 아래 2절에서 얻는다. 만료 없는 상수 |

로컬은 `.env` (gitignore 대상), Actions 는 repository Secrets 에 넣는다. 코드에 값을 두지 않는다 (SPEC 12절).

### 2. Notion 알림 설정

알림은 주차 토글 라벨에 본인을 `@멘션`하는 것으로 이뤄진다. 세 단계다.

**① 통합 권한 올리기 (필수).** `notion.so/profile/integrations` › `tech_news` › 기능 › 사용자 기능에서
「**이메일 주소를 제외한 사용자 정보 읽기**」를 고른다. 기본값인 「사용자 정보 없음」이면 멘션이 거부된다.

> 이 설정을 빼먹으면 **알림만 빠지는 게 아니라 그 주 발행 전체가 실패**한다 —
> 멘션이 토글과 한 페이로드라 멘션 검증 실패가 곧 블록 쓰기 실패다:
> `400 validation_error: Could not find user with ID … capabilities to read user information`
>
> 토글이 만들어지지 않았으므로 멱등성에는 걸리지 않는다. 권한을 고친 뒤 `workflow_dispatch` 로 온전히 회복된다.

**② 본인 user ID 얻기.** 권한을 올리면 `GET /v1/users` 가 열린다. 응답에서 `type` 이 `person` 인 항목의
`id` 를 `NOTION_USER_ID` 에 넣는다. 목록에는 봇도 섞여 나오므로 `person` 인지 확인한다.
한 번만 구하면 되는 상수다.

**③ 폰 알림 켜기.** Notion 앱 `••• › Settings › My notifications` 의 모바일 푸시,
그리고 OS 알림 권한 (iOS 설정 › 알림 › Notion / Android 앱 정보 › 알림).

> **폰이나 PC 에서 Notion 을 열어 두면 푸시 대신 인박스 뱃지만 뜬다.** Notion 의 설계된 동작이지 장애가 아니다.
> 실행이 월요일 아침이라 보통은 닫혀 있어 푸시가 나간다. "알림이 안 온다" 싶으면 이것부터 확인한다.

### 3. GitHub Actions

`.github/workflows/weekly_brief.yml` 이 `cron: '10 23 * * 0'` (UTC 일 23:10 = KST 월 08:10) 으로 돈다.
실행 후 `logs/last_run.txt` 를 봇이 커밋하는데, 이것이 무료 계정의 **60일 무활동 워크플로우 중단**을 막는 장치다.
`Actions` › 실패 알림을 켜 두는 것을 전제로 한다.

## 로컬에서 돌리기

```bash
pip install -r requirements-dev.txt      # 실행 의존성은 trafilatura 하나, 나머지는 표준 라이브러리

python3 -m pytest -q                     # 221 tests, API 키 없이 fixture 만으로 돈다
python3 .claude/skills/pipeline-qa/scripts/check_fixtures.py   # fixture ↔ schema ↔ SPEC 규약 검사

python3 -m src.main --dry-run --no-llm --date 2026-09-08   # 수집·랭킹·보강 실측, 요약은 fallback. 비용 0, 발행 없음
python3 -m src.main --dry-run                              # + Gemini 요약 (소액 과금). 발행 없음
python3 -m src.main                                        # 실제 발행 — 로컬에서 돌리지 말 것 (그 주는 멱등성으로 다시 못 돌린다)
```

`--date` 는 비월요일이면 그 주 월요일로 스냅된다. `python` 이 아니라 `python3` 다.

## 실행 결과 읽기

`logs/last_run.txt`:

```
status: published        ← 정상. already_exists = 그 주 토글이 이미 있어 종료, nothing_to_publish = 양쪽 0건
summary: gemini 10 / fallback 0
failures: -              ← 잡아서 넘어간 단계명 (collect_domestic, collect_hn, collect_rss, enrich)
```

`failures` 가 비어 있지 않으면 종료 코드 1 이라 Actions 가 실패로 표시되지만 **발행은 끝난 뒤다**.
Notion 쓰기가 끝났다면 알림도 나갔다 — 멘션이 토글 안에 있어 둘이 분리되지 않는다 (SPEC 8절).
Notion 쓰기가 실패하면 발행과 알림이 함께 실패하지만, 토글이 없으므로 `workflow_dispatch` 로 회복된다 (SPEC 9절).

## 저장소 구조

```
SPEC.md                 설계 명세 (권위). 절 번호는 코드·테스트가 참조하므로 움직이지 않는다
src/
  main.py               진입점. 외부 호출은 전부 Services 로 주입, 단계 실패는 _guard 로 격리
  schema.py             모듈 간 데이터 계약 (RawArticle → RankedArticle → BriefItem → WeeklyBrief)
  collect_naver.py      국내 수집 (NAVER API HUB)
  collect_hn.py         HN Algolia + 제목 키워드 필터
  collect_rss.py        보조 RSS/Atom (예비 풀)
  rank_domestic.py      bigram 자카드 클러스터링 → 커버리지 랭킹
  rank_overseas.py      점수 정규화 → URL 병합 → 예비 풀
  enrich.py             해외 원문 본문 보강 (trafilatura)
  summarize.py          Gemini 배치 요약 + 2단 fallback
  render_notion.py      주차 토글 블록 렌더
  notion.py             Notion API 클라이언트 (토글 append · 멱등성 · 멘션 알림)
  publishers.py         도메인 → 매체명 표 (데이터 전용)
  urls.py  week.py  text.py  http.py  config.py
tests/                  221 tests. fixtures/ 는 2026-08-17 실행 한 주치로 고정, README 에 계산 근거표
.github/workflows/weekly_brief.yml
.claude/                유지보수용 에이전트 하네스 (아래)
```

**네트워크 호출부와 순수 로직이 분리돼 있다.** 랭킹·주차 계산·렌더링은 API 키 없이 fixture 만으로 테스트된다.
국내·해외는 별개 파이프라인이고 공유하는 것은 출력 타입뿐이다.

## 유지보수 — Claude Code 하네스

이 저장소는 Claude Code 에서 열면 4인 에이전트 팀이 붙는다 (`CLAUDE.md`, `.claude/`):
설계 관리자(SPEC 정합), 구현자, 검증자(모듈 경계면 교차 검증), 운영 진단자(로그·자격 증명·외부 API 사양).
"알림이 안 왔어", "수집 키워드 추가하고 실측해봐", "SPEC 이랑 코드 맞는지 봐줘" 같은 요청으로 트리거된다.

## 비용

GitHub Actions · Notion(알림 포함) · HN · RSS · 네이버 API HUB(일 25,000건 한도) 전부 무료. Gemini 만 월 수십~수백 원.
