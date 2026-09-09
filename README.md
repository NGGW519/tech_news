# tech_news — 주간 테크 뉴스 브리핑 자동화

매주 월요일 아침, 지난 한 주간 가장 이슈가 됐던 **IT / Physical AI 뉴스**를 국내·해외 각 5건씩
자동으로 수집·요약해 Notion 에 쌓고, 카카오톡으로 도착 알림을 보낸다.

- **축적**은 Notion — 검색·회고 가능한 자산으로 남긴다
- **도달**은 카카오톡 — 한 줄 알림 + Notion 링크 버튼

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
   ├─ Notion     월 페이지 → 주차 토글 append
   └─ 카카오톡   "📡 이번 주 테크 브리핑 · 국내 5 / 해외 5" + [Notion에서 보기]
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
| `NOTION_TOKEN` | Notion Internal Integration 토큰. 루트 페이지에 이 통합을 **연결**해야 한다 |
| `NOTION_ROOT_PAGE_ID` | 루트 페이지 ID |
| `KAKAO_REST_API_KEY` | 카카오 개발자 콘솔 [앱] › [플랫폼 키] › [REST API 키] |
| `KAKAO_CLIENT_SECRET` | 같은 화면 [클라이언트 시크릿] — 새 콘솔은 기본 ON 이라 없으면 `KOE010` |
| `KAKAO_REFRESH_TOKEN` | 아래 스크립트로 발급 (콘솔에서 복사하는 값이 아니다) |
| `GH_PAT` *(선택)* | repo Secrets 쓰기 권한 PAT. 있으면 카카오 토큰 재발급 시 Secrets 자동 갱신 |

로컬은 `.env` (gitignore 대상), Actions 는 repository Secrets 에 넣는다. 코드에 값을 두지 않는다 (SPEC 12절).

### 2. 카카오 "나에게 보내기"

콘솔 사전 준비 5단계(카카오 로그인 ON, `talk_message` 동의항목, 리다이렉트 URI, **웹 도메인에 `https://www.notion.so` 등록**)는
`scripts/kakao_refresh_token.py` 상단 docstring 에 있다. 그 다음:

```bash
python3 scripts/kakao_refresh_token.py          # 브라우저 로그인 → code 붙여넣기 → .env 에 refresh token 저장
python3 scripts/kakao_refresh_token.py --test   # 시험 발송. 버튼을 눌러 Notion 이 열리면 완료
```

웹 도메인을 등록하지 않으면 버튼이 조용히 `localhost` 로 바뀐다 — 시험 발송에서 버튼까지 눌러 보는 것이 완료 기준이다.

refresh token 은 60일짜리다. 주 1회 실행이 갱신을 앞지르지만, 재발급된 토큰을 저장하려면 `GH_PAT` 이 필요하다.
없으면 만료 전에 위 스크립트로 수동 재발급하고 Secret 을 갱신한다 (SPEC 8절).

### 3. GitHub Actions

`.github/workflows/weekly_brief.yml` 이 `cron: '10 23 * * 0'` (UTC 일 23:10 = KST 월 08:10) 으로 돈다.
실행 후 `logs/last_run.txt` 를 봇이 커밋하는데, 이것이 무료 계정의 **60일 무활동 워크플로우 중단**을 막는 장치다.
`Actions` › 실패 알림을 켜 두는 것을 전제로 한다.

## 로컬에서 돌리기

```bash
pip install -r requirements-dev.txt      # 실행 의존성은 trafilatura 하나, 나머지는 표준 라이브러리

python3 -m pytest -q                     # 216 tests, API 키 없이 fixture 만으로 돈다
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
failures: -              ← 잡아서 넘어간 단계명 (collect_naver, collect_hn, collect_rss, enrich, kakao)
```

`failures` 가 비어 있지 않으면 종료 코드 1 이라 Actions 가 실패로 표시되지만 **발행은 끝난 뒤다**.
Notion 쓰기는 됐는데 카톡만 실패한 경우 재실행해도 알림은 오지 않는다 — 알려진 한계로 감수했다 (SPEC 9절).

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
  notion.py  kakao.py   API 클라이언트
  publishers.py         도메인 → 매체명 표 (데이터 전용)
  urls.py  week.py  text.py  http.py  config.py
tests/                  216 tests. fixtures/ 는 2026-08-17 실행 한 주치로 고정, README 에 계산 근거표
scripts/kakao_refresh_token.py
.github/workflows/weekly_brief.yml
.claude/                유지보수용 에이전트 하네스 (아래)
```

**네트워크 호출부와 순수 로직이 분리돼 있다.** 랭킹·주차 계산·렌더링은 API 키 없이 fixture 만으로 테스트된다.
국내·해외는 별개 파이프라인이고 공유하는 것은 출력 타입뿐이다.

## 유지보수 — Claude Code 하네스

이 저장소는 Claude Code 에서 열면 4인 에이전트 팀이 붙는다 (`CLAUDE.md`, `.claude/`):
설계 관리자(SPEC 정합), 구현자, 검증자(모듈 경계면 교차 검증), 운영 진단자(로그·자격 증명·외부 API 사양).
"카톡이 안 왔어", "수집 키워드 추가하고 실측해봐", "SPEC 이랑 코드 맞는지 봐줘" 같은 요청으로 트리거된다.

## 비용

GitHub Actions · Notion · 카카오 · HN · RSS · 네이버 API HUB(일 25,000건 한도) 전부 무료. Gemini 만 월 수십~수백 원.
