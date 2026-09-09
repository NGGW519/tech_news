---
name: ops-runbook
description: "tech-news-orchestrator 가 ops-investigator 에게 시키는 하위 절차 — 사용자 요청은 오케스트레이터가 먼저 받는다. 주간 테크 뉴스 브리핑 파이프라인의 읽기 전용 운영 진단 런북(저장소 파일을 수정하지 않는다): logs/last_run.txt 필드·status 해석표, failures 단계명→모듈→흔한 원인 매핑, 증상별 진단 트리(알림 누락·미발행·0건·exit 1), 멱등성을 고려한 복구 절차, 자격 증명 수명표와 카카오 refresh token 재발급 절차, SPEC 11절 외부 API 사양 점검표(Notion·카카오·Gemini 모델 ID·네이버 API HUB·arXiv). 실행 실패·알림 누락·자격 증명·외부 사양 진단을 맡은 에이전트는 이 스킬을 읽는다. 코드 수정 규약은 pipeline-dev, SPEC 갱신은 spec-change."
---

# 운영 런북

이 파이프라인은 GitHub Actions 에서 매주 월요일 08:10 KST 에 무인 실행된다. 실패의 대부분은 코드가 아니라
바깥이 바뀐 것에서 온다 — Reddit API 정책 변경(소스 제거), 네이버 검색 API 의 API HUB 이관, 카카오 콘솔 개편이
전부 실제로 있었다. 진단의 첫 질문은 "코드가 틀렸나"가 아니라 **"무엇이 바뀌었나"** 다.

**비밀값은 절대 출력하지 않는다.** `.env` 는 `sed -E 's/=.*/=<redacted>/' .env` 로 키 이름만 본다. 토큰·키는 진단 파일·메시지·로그 어디에도 넣지 않는다.

## 1. 실행 로그 — `logs/last_run.txt`

Actions 가 매 실행 후 커밋한다 (60일 비활성화 방지, SPEC 9절). 로컬 `--dry-run` 은 쓰지 않는다.

| 필드 | 의미 | 정상 |
|------|------|------|
| `run_at` | 실행 시각 KST | 월요일 08:1x~08:3x |
| `week` | `week_label` — 귀속 주차 (목요일 앵커) | 직전 주 |
| `domestic` / `overseas` | 발행 건수 | 각 5. 미달이면 부분 발행 (2절) |
| `summary` | `gemini N / fallback M` | fallback 0~2. **gemini 0 이면 Gemini 배치 실패** (섹션 전체 fallback) |
| `status` | 아래 표 | `published` |
| `notion` | 주차 토글 앵커 URL | `https://www.notion.so/<page>#<block>` |
| `failures` | `_guard` 가 잡은 단계명 | `-` |

| `status` | 뜻 | 조치 |
|----------|-----|------|
| `published` | Notion 쓰기 완료. `failures` 에 `kakao` 가 있으면 알림만 누락 | `failures` 확인 |
| `already_exists` | 그 주 토글이 이미 있어 종료 (멱등성). Gemini 는 이미 호출됨 | 의도된 재실행이면 정상. 아니면 이전 실행이 이미 발행한 것 — Notion 확인 |
| `nothing_to_publish` | 국내·해외 **모두 0건**. 토글 안 만듦 | 수집 실패 진단 (4절). 원인 고친 뒤 `workflow_dispatch` 로 회복 가능 (토글이 없으므로 멱등성에 안 걸림) |
| `dry_run` | 로컬 dry-run (로그 파일에는 안 남음) | — |

`failures` 가 비어 있지 않으면 종료 코드 1 → Actions 가 "실패"로 표시되지만 **발행은 끝난 뒤다**.

## 2. 단계명 → 모듈 → 흔한 원인

| `failures` 값 | 모듈 | 흔한 원인 | 확인 |
|--------------|------|----------|------|
| `collect_domestic` | `collect_naver.py` | API HUB 키(`X-NCP-APIGW-API-KEY-ID`/`-KEY`) 오류, 일 한도(25,000), 응답 형식 변경, `start` 상한 | 로컬 `--dry-run --no-llm` 재현. 오류 본문에 힌트가 찍힌다 |
| `collect_hn` | `collect_hn.py` | Algolia 장애·응답 변경, 제목 키워드 필터가 전부 걸러냄 | 재현 + `collected hn: N건` 로그 |
| `collect_rss` | `collect_rss.py` | arXiv 429(3초 간격·1회 재시도 후에도)·30초 초과, 피드 URL 이동, XML 형식 변경 | 피드별로 격리돼 있으므로 로그에서 어느 피드인지 |
| `enrich` | `enrich.py` | 사이트 차단·타임아웃(5초)·본문 200자 미만 | 실패해도 요약은 fallback 으로 간다. 5건 전부 failed 면 네트워크 문제 |
| `kakao` | `kakao.py` | refresh token 만료(60일·2개월 연속 실패), `KOE010`(client secret 누락), `invalid_grant`, 웹 도메인 미등록(버튼이 localhost 로) | 6절 자격 증명 |
| (없음, `summary: gemini 0`) | `summarize.py` | 모델 ID 폐기, 키 무효, `responseSchema` 옵션명 변경, JSON 파싱 실패 | `_guard` 밖이라 failures 에 안 잡힌다. 7절 외부 사양 |
| (Actions 실패 + `last_run.txt` 미갱신) | `notion.py` 또는 `config.py` | Notion 토큰·루트 페이지 권한, API 버전, 환경 변수 누락(`환경 변수 누락:` SystemExit) | Notion 은 `_guard` 밖 — 예외면 프로세스가 죽고 로그도 안 써진다 |

## 3. 증상별 진단 트리

먼저 `run_at` 을 본다. 월요일 08:1x~08:3x 가 아니면 **수동 실행**(`workflow_dispatch`)이다 — 그러면 "정기 실행이 왜
없었나"가 첫 질문이다: 워크플로우 파일이 그 시각에 존재했는가(`git log --format='%ci %s' -- .github/workflows/`),
60일 비활성화, cron 지연·GitHub 장애. 그 뒤에 아래 트리로 간다.

```
카톡이 안 왔다
├─ Notion 에 이번 주 토글 있음 + status published + failures kakao → 6절 (자격 증명·도메인)
│     재실행해도 카톡은 안 온다 (SPEC 9절 알려진 한계). Notion 링크를 직접 열어 확인
├─ Notion 에 이번 주 토글 있음 + status already_exists → 이번 실행은 멱등성 게이트에서 끝났고
│     카카오는 **호출조차 안 됐다** (failures 에 kakao 가 없는 이유). 토글을 만든 이전 실행의 로그를
│     git 이력에서 찾아 그쪽 failures 를 본다. 알림이 꼭 필요하면 5절 "토글이 있는데" 절차
├─ Notion 에도 없음 + status already_exists → 토글 위치(월 페이지·주차 라벨) 재확인. 다른 월 페이지에 있을 수 있다
├─ Notion 에도 없음 + status nothing_to_publish → 양쪽 0건 → 4절 소스 건강도
└─ last_run.txt 가 이번 주 것이 아님 → 워크플로우가 안 돌았거나 Notion 이전에 죽음
      ├─ Actions 에 실행 기록 없음 → 60일 비활성화? cron 지연? workflow 파일 변경?
      └─ 실행 실패 → 실패 스텝 로그 (gh 없으면 사용자에게 붙여넣기 요청)

exit 1 인데 Notion 에는 있다 → 부분 실패 (failures 참조). 발행은 됐다
국내(또는 해외)만 0건 → 그 쪽 수집기만 죽음 (부분 발행) → 2절 해당 행
summary: gemini 0 / fallback 10 → Gemini 배치 실패 → 7절 모델 ID·옵션명·키
```

## 4. 소스 건강도 (0건·급감)

1. `python3 -m src.main --dry-run --no-llm --date {지난 월요일}` 로 재현. 로그의 `collected {source}: N건` / `ranked` 줄을 본다
2. 수집은 됐는데 랭킹 0건 — 국내는 클러스터 크기 2 미만(`MIN_CLUSTER_SIZE`)이거나 임계값, 해외는 제목 키워드 필터·예비 풀 소진
3. 수집 0건 — API 오류(본문 확인), 키워드가 그 주 뉴스와 안 맞음, 수집 창(7일) 안 게시물 없음
4. 원인이 "키워드·임계값" 이면 pipeline-dev 튜닝(B 유형), "API 변경" 이면 spec-change 로 (설계 변경 가능성)

## 5. 복구 절차

| 상황 | 절차 |
|------|------|
| 토글이 **없는** 주 (nothing_to_publish, Notion 이전 실패) | 원인 수정 → Actions `workflow_dispatch` 수동 실행. 비월요일 실행은 그 주 월요일로 스냅되므로 **다음 월요일 전에** 돌려야 지난 주가 나온다 |
| 토글이 **있는데** 내용이 틀린 주 | 멱등성 때문에 재실행이 `already_exists` 로 끝난다 → 사용자가 Notion 에서 해당 토글을 삭제한 뒤 `workflow_dispatch` |
| 카톡만 누락 | 재실행으로 회복 불가 (9절). 알림 없이 Notion 만 확인하거나, `scripts/kakao_refresh_token.py --test` 로 시험 메시지 |
| 60일 비활성화로 cron 중단 | 저장소에 아무 커밋이나 push → 워크플로우 재활성화 (Actions 탭에서 enable). 로그 커밋이 정상이면 발생하지 않는다 |
| 지난 주가 여러 개 밀림 | 한 번에 한 주씩. `--date` 는 로컬 dry-run 용이고 Actions 는 실행 시각 기준이라, 두 주 이상 밀린 것은 회복 불가 (수집 창이 7일 고정) |

상태를 바꾸는 조치(토글 삭제, Secrets 갱신, workflow_dispatch)는 **사용자가 직접** 하거나 명시 승인 후에만.

## 6. 자격 증명

| Secret | 용도 | 수명 | 갱신 | 실패 징후 |
|--------|------|------|------|----------|
| `NAVER_CLIENT_ID/SECRET` | 국내 수집 — **NAVER API HUB** 키 (개발자센터 키 아님) | 무기한. 일 25,000건 | API HUB 콘솔 | `collect_domestic` 401/403 |
| `GEMINI_API_KEY` | 요약 (유료 Tier 1) | 무기한 | AI Studio | `summary: gemini 0` |
| `NOTION_TOKEN` | Internal Integration | 무기한 | Notion 통합 페이지. 루트 페이지에 통합 연결 필요 | Notion 단계 예외 |
| `NOTION_ROOT_PAGE_ID` | 루트 페이지 | — | — | 월 페이지 생성 실패 |
| `KAKAO_REST_API_KEY` | 앱 키 | 무기한 | 콘솔 [앱] › [플랫폼 키] | `KOE` 오류 |
| `KAKAO_CLIENT_SECRET` | 새 콘솔은 기본 ON | 무기한 | 같은 화면 [클라이언트 시크릿] | `KOE010` |
| `KAKAO_REFRESH_TOKEN` | 나에게 보내기 | **60일**. 잔여 1개월 미만이면 갱신 호출이 새 토큰을 돌려줌 → `GH_PAT` 있으면 자동 갱신, 없으면 `::warning::` | 아래 재발급 | `invalid_grant`, `failures: kakao` |
| `GH_PAT` *(선택)* | repo secrets 쓰기 PAT | PAT 만료일 | GitHub 설정 | Actions 경고 "GH_PAT 이 없어 Secrets 를 갱신하지 못했다" |

**카카오 재발급** — 브라우저 로그인·동의가 필요해 에이전트가 못 한다. 사용자에게 안내:

```
! python3 scripts/kakao_refresh_token.py          # 브라우저 → code 붙여넣기 → .env 저장
! python3 scripts/kakao_refresh_token.py --test   # 시험 발송. 버튼 눌러 Notion 이 열리는지까지 확인
```

그 뒤 `.env` 의 새 값을 GitHub Secrets `KAKAO_REFRESH_TOKEN` 에 사용자가 직접 넣는다. 콘솔 사전 준비 5단계는 스크립트 docstring.
**"2개월 연속 실행 실패 시 만료"** — Actions 실패 알림을 꺼 두면 조용히 만료된다.

## 7. 외부 사양 점검 (SPEC 11절)

SPEC 이 "기억에 의존하지 말고 최신 공식 문서를 확인할 것"이라 한 항목. 항목별 현재 기록값·확인 위치·판정 규칙·
바뀌면 고칠 곳은 `references/external-apis.md`. 점검 결과는 항목마다 **확인일 + 출처 URL + 변경 없음/있음** 으로
적고, 변경 있음은 guardian 에게 (SPEC 갱신), 코드 영향은 engineer 에게 넘긴다.

정기 점검 시점: 마지막 확인일(SPEC 7·8·11절의 "2026-09-08 확인")에서 한 달 이상 지났을 때, 또는 `summary: gemini 0`·`kakao` 실패가 원인 불명일 때.

## 8. 이 머신의 제약

- `gh` CLI 없음 → Actions 로그는 사용자가 붙여넣거나 로컬 재현으로 대신한다
- `python` 없음 → `python3`
- `.env` 가 있으면 로컬 재현 가능. `--dry-run --no-llm` 은 발행·과금 없음. **dry-run 없이 실행하지 않는다**

## 9. 진단 리포트

`/home/robot/tech_news/_workspace/{NN}_ops-investigator_diagnosis.md`. 형식은 에이전트 정의. 원인 판정은
`코드 | 설정/자격 증명 | 외부 서비스 | 미확정(후보 나열)` 네 가지 중 하나. "아마도"는 근거가 있을 때만.
