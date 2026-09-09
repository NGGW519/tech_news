---
name: tech-news-orchestrator
description: "주간 테크 뉴스 브리핑 파이프라인(tech_news) 에이전트 팀 오케스트레이터 — 이 저장소의 파이프라인에 관한 모든 작업 요청의 유일한 사용자 진입점. 수집(네이버/HN/RSS)·랭킹·본문 보강·Gemini 요약·Notion·카카오·GitHub Actions 워크플로우(cron 포함)·SPEC·fixture·실행 로그·자격 증명에 관한 변경·수정·튜닝·진단·감사·검증 요청이 오면 반드시 이 스킬을 사용할 것. 예: '지난주 실행 왜 실패했어', '카톡이 안 왔어', '토큰 만료된 것 같아', '수집 키워드 추가해줘', '임계값 바꿔서 실측해봐', '소스 추가/제거', 'publisher 표에 매체 추가', 'Gemini 모델 ID 아직 유효한지 확인', 'SPEC 이랑 코드 맞는지 감사', 'fixture 점검', '테스트 돌려서 검증해줘', '워크플로우 수정'. 후속 작업 — '다시 실행', '재실행', '수정', '보완', '업데이트', '이전 결과 기반으로 개선', '~만 다시', '이전 진단 재확인' 도 이 스킬. 하위 스킬(spec-change, pipeline-dev, pipeline-qa, ops-runbook)은 이 스킬이 팀원에게 시키는 절차이므로 사용자 요청에 직접 매칭하지 않는다. 제외: 파일 변경·실행·검증이 필요 없는 순수 설명 요청(값 하나, 필드 정의, 함수 동작 설명)은 직접 답한다 — 단, 실측·재실행·수정·검증·진단이 한 단어라도 들어가면 이 스킬. 대상이 이 저장소 밖(Notion·Gemini·카카오 API 를 쓰는 별개 신규 프로젝트)이면 해당 없음."
---

# Tech News Orchestrator — 파이프라인 유지보수 팀 조율

주간 테크 뉴스 브리핑 파이프라인의 **유지보수·진화** 작업을 4인 전문가 팀으로 수행하는 통합 스킬.
파이프라인은 이미 완성돼 주 1회 무인 실행 중이다. 이 하네스가 다루는 일은 "새로 만들기"가 아니라
**운영 진단 → 설계(SPEC) 정합 → 구현 → 검증** 의 반복이다.

이 프로젝트의 두 가지 특수성이 팀 구조를 결정한다:
1. **SPEC.md 가 코드보다 상위 권위다.** SPEC 에 없는 동작은 코드부터 짜지 않고 SPEC 부터 고친다. 그래서 설계 관리자(spec-guardian)가 구현자와 분리돼 있다.
2. **주 1회 실행 + 멱등성.** 잘못 발행되면 그 주는 잘못된 채 남는다. 그래서 검증자(pipeline-qa)가 모듈 단위로 즉시 개입한다.

## 실행 모드: 하이브리드

| Phase | 모드 | 이유 |
|-------|------|------|
| Phase 2 진단·분석 | 서브 에이전트 (병렬) | 로그 진단·SPEC 영향 분석·외부 사양 확인은 서로 독립. 결과만 리더가 모으면 된다 |
| Phase 4 구현·검증 | 에이전트 팀 | 구현자 ↔ 검증자의 즉시 피드백 루프(incremental QA)와 설계 관리자 질의가 품질을 결정한다 |

### 이 환경의 팀 도구 (2026-09-09 확인)

이 환경에는 `TeamCreate`/`TaskCreate` 가 없다. 팀 모드는 다음 조합으로 구현한다:

| 필요 기능 | 사용 도구 |
|----------|----------|
| 팀원 생성 | `Agent(subagent_type: "{에이전트 정의 이름}", name: "{같은 이름}", model: "opus", prompt: ...)` — 백그라운드로 실행되며 완료 시 리더에게 알림이 온다. 커스텀 타입(`spec-guardian` 등) 스폰이 이 환경에서 동작함을 확인했다 |
| 팀원에게 후속 지시·피드백 | `SendMessage(to: "{이름}", message: ...)` — 이전 컨텍스트를 유지한 채 이어서 작업한다 |
| 팀원 간 직접 통신 | 팀원이 자기 도구로 `SendMessage(to: "{다른 팀원 이름}")`. 에이전트 정의의 "팀 통신 프로토콜"이 대상과 내용을 정한다 |
| 지연 로드 도구 | `SendMessage`·`WebSearch`·`WebFetch` 는 지연 로드된다 — 리더도 팀원도 **첫 호출 전 `ToolSearch("select:SendMessage")`** 로 스키마를 먼저 받는다. 팀원 프롬프트에 이 한 줄을 넣는다 |
| 공유 작업 목록 | 없음 → **파일 기반**으로 대체. `_workspace/` 의 산출물 파일이 작업 상태다 |
| 팀 해체 | 별도 도구 없음. 산출물이 파일로 남았으면 그대로 다음 Phase 로 간다 |

**이름 규칙 — 통신이 깨지지 않는 유일한 조건:**
- 팀원의 `name` 은 **에이전트 정의 이름(subagent_type)과 같은 문자열**을 쓴다: `spec-guardian`, `pipeline-engineer`, `pipeline-qa`, `ops-investigator`. 에이전트 정의의 통신 프로토콜이 이 이름으로 상대를 부르기 때문이다
- 한 실행에서 같은 이름은 **한 번만 스폰**한다. 이미 스폰된 팀원에게 새 일을 시킬 때는 재스폰하지 않고 `SendMessage` 로 이어서 시킨다 (컨텍스트가 이어진다)
- 무응답으로 재스폰이 불가피할 때만 `{이름}-2` 로 새 이름을 쓰고, 다른 팀원에게 "이제 `{이름}-2` 에게 보내라"고 `SendMessage` 로 알린다
- 폴백: 커스텀 `subagent_type` 이 거부되는 환경이면 `general-purpose` 로 스폰하고 프롬프트 첫 줄에 `.claude/agents/{이름}.md` 를 Read 해 그 역할로 행동하라고 지시한다. `name` 은 그대로 정의 이름을 쓴다

`TeamCreate` 가 있는 환경이라면 Phase 4 를 그대로 팀 생성으로 치환해도 된다. 프로토콜은 동일하다.

## 에이전트 구성

| 팀원 (`name` = `subagent_type`) | 역할 | 스킬 | 출력 |
|------|------|------|------|
| `spec-guardian` | SPEC 영향 분석·분류, 개정안, drift 감사 | `spec-change` | `_workspace/{NN}_spec-guardian_impact.md`, SPEC.md |
| `pipeline-engineer` | src/tests/workflow 수정, 실측 | `pipeline-dev` | 코드, `_workspace/{NN}_pipeline-engineer_changes.md` |
| `pipeline-qa` | 경계면 교차 검증, 회귀, fixture, 실측 검토 | `pipeline-qa` | `_workspace/{NN}_pipeline-qa_report.md` |
| `ops-investigator` | 실행 로그·Actions·자격 증명·외부 사양 진단 | `ops-runbook` | `_workspace/{NN}_ops-investigator_diagnosis.md` |
| (리더 = 이 스킬) | 분류, 조율, 승인 게이트, 마무리 | — | 사용자 보고 |

모든 `Agent` 호출에 `model: "opus"` 를 명시한다. 팀원 프롬프트에는 반드시 다음을 넣는다:
(1) 읽어야 할 에이전트 정의·스킬 경로, (2) 입력 파일 절대 경로, (3) 출력 파일 절대 경로, (4) 통신 상대 팀원 이름과 "첫 `SendMessage` 전 `ToolSearch("select:SendMessage")`", (5) 사용자 요청 원문.

## 요청 분류 — 어느 팀을 꾸리는가

| 유형 | 예 | Phase 2 (서브) | Phase 3 승인 | Phase 4 (팀) |
|------|-----|---------------|------------|-------------|
| **A. 운영 진단** | "왜 실패했어", "카톡 안 왔어", "0건 나왔어" | ops-investigator | 조치가 상태 변경이면 필요 | 코드 원인이면 B 로 승격 (spec-guardian 을 그때 스폰) |
| **B. SPEC 범위 내 변경** | 키워드 추가, 타임아웃 조정, publisher 표 확장, 임계값 튜닝 | spec-guardian (경미 확인) | 불필요 | pipeline-engineer + pipeline-qa |
| **C. 설계 변경** | 소스 추가/제거, fallback 순서, 스키마 필드, 출력 형식 | spec-guardian + ops-investigator(외부 사실 필요 시) | **필수** — SPEC 개정안 승인 | spec-guardian(개정 반영) → pipeline-engineer + pipeline-qa |
| **D. 외부 사양 확인** | "모델 ID 유효?", "SPEC 11절 점검" | ops-investigator | 불필요 | 변경 필요 시 C (spec-guardian 을 그때 스폰) |
| **E. 정합성 감사** | "SPEC 이랑 코드 맞아?", "fixture 검토" | spec-guardian + pipeline-qa (병렬, 감사 모드) | 불필요 | 불일치 수정은 B 또는 C — Phase 2 의 pipeline-qa 를 재스폰하지 않고 `SendMessage` 로 이어 쓴다 |

분류가 애매하면 spec-guardian 에게 먼저 묻는다 — 분류 판정이 그 에이전트의 첫 번째 역할이다.

## 워크플로우

### Phase 0: 컨텍스트 확인 (후속 작업 지원)

1. `/home/robot/tech_news/_workspace/` 존재 여부 확인
2. 실행 모드 결정:
   - **미존재** → 초기 실행. Phase 1 로
   - **존재 + 부분 수정 요청** ("QA 만 다시", "진단 재확인", "이전 결과 개선") → **부분 재실행**. 해당 팀원만 호출하고(이미 이 세션에 있으면 `SendMessage`, 없으면 스폰), 프롬프트에 이전 산출물 경로를 넣어 delta 만 작업하게 한다. 새 파일 번호는 이어서 붙인다
   - **존재 + 새 요청** → **새 실행**. 기존 폴더를 `_workspace_{YYYYMMDD_HHMMSS}/` 로 이동한 뒤 Phase 1 로
3. `logs/last_run.txt` 를 읽어 마지막 실행 상태를 리더 컨텍스트에 둔다 — 어떤 요청이든 "지금 파이프라인이 어떤 상태인가"가 배경이다

### Phase 1: 준비·분류

1. 사용자 요청을 위 분류표로 A~E 판정. 근거 한 줄을 적어 둔다
2. `_workspace/` 생성, `00_input.md` 에 요청 원문 + 분류 + `last_run.txt` 내용 저장
3. 기준선 확보: `python3 -m pytest -q` 결과(passed 수)를 `00_input.md` 에 기록. 이후 회귀 판정의 기준이다
4. `ToolSearch("select:SendMessage")` — 리더가 팀원에게 후속 지시를 보내려면 필요하다

### Phase 2: 진단·분석
**실행 모드:** 서브 에이전트 (병렬, 단일 메시지에서 동시 호출)

분류에 따라 필요한 조사자만 호출한다. 각 팀원 프롬프트에 정의·스킬 경로와 출력 경로를 명시한다.

| 팀원 | 호출 조건 | 출력 |
|------|----------|------|
| `spec-guardian` | B, C, E | `_workspace/01_spec-guardian_impact.md` |
| `ops-investigator` | A, C(외부 사실 필요), D | `_workspace/01_ops-investigator_diagnosis.md` |
| `pipeline-qa` | E | `_workspace/01_pipeline-qa_report.md` (감사 모드: 입력 파일 없이 현재 상태 검증) |

완료 알림을 받으면 산출물을 Read 하고 다음을 판정한다:
- spec-guardian 이 **고정 항목 충돌** 로 분류 → 즉시 사용자에게 보고하고 중단. 다른 팀원 결과도 함께 첨부
- spec-guardian 이 **설계 변경** 으로 분류 → Phase 3
- A 에서 ops-investigator 가 "코드 원인" 판정 → B 로 승격: **spec-guardian 을 여기서 스폰**해 impact 를 받은 뒤 Phase 4
- A/D 에서 ops-investigator 가 "설정/외부" 판정 → Phase 5 로 직행 (사용자 조치 안내)

### Phase 3: 승인 게이트 (C 유형만)

1. spec-guardian 에게 `SendMessage` 로 SPEC 개정 초안 요청 → `_workspace/02_spec-guardian_spec-draft.md`
2. 사용자에게 제시: 바뀌는 절, 옛 규칙 → 새 규칙, 근거, 영향받는 코드·fixture 목록
3. 승인 → spec-guardian 이 `SPEC.md` 에 반영(버전·헤더 블록 포함) → Phase 4
4. 거절/수정 요청 → spec-guardian 에게 `SendMessage` 로 피드백 전달, 초안 재작성 (최대 2회)
5. **사용자 응답을 받을 수 없는 자율 실행 상황이면** 초안까지만 만들고 여기서 멈춘다. SPEC 을 승인 없이 고치지 않는다

### Phase 4: 구현·검증
**실행 모드:** 에이전트 팀

1. **팀 확인·생성**
   - `spec-guardian` 이 아직 없으면(A→B, D→C 경로) 먼저 스폰해 impact 를 받는다. 있으면 그대로 둔다 — engineer/qa 의 SPEC 질의를 `SendMessage` 로 받아 답한다
   - 단일 메시지에서 두 팀원을 동시에 호출한다 (E 유형에서 `pipeline-qa` 가 이미 있으면 그쪽은 `SendMessage` 로 "이제 검증 모드로 전환, engineer 알림을 기다려라"):
     - `Agent(subagent_type: "pipeline-engineer", name: "pipeline-engineer", model: "opus", prompt: ...)` — 입력: impact/diagnosis 파일, 요청 원문. 지시: 모듈 단위로 완성될 때마다 `SendMessage(to: "pipeline-qa")` 로 알릴 것
     - `Agent(subagent_type: "pipeline-qa", name: "pipeline-qa", model: "opus", prompt: ...)` — 입력: impact 의 "검증 기준", 기준선 passed 수. **시작 시점에는 changes 파일이 없다** — engineer 의 `SendMessage` 알림이 첫 입력이다. 지시: 알림을 받으면 해당 경계면부터 검증하고 `SendMessage(to: "pipeline-engineer")` 로 수정 요청, 최종 리포트 파일 작성

2. **팀원 간 통신 규칙** (에이전트 정의의 프로토콜 요약):
   - pipeline-engineer → pipeline-qa: 모듈 완성 알림 (파일 + 검증 요청 경계면)
   - pipeline-qa → pipeline-engineer: 수정 요청 (`파일:라인`, 현재, 기대, SPEC 절). 발견 즉시
   - pipeline-engineer/pipeline-qa → spec-guardian: SPEC 공백·모순 질의. spec-guardian 은 답을 정하지 않고 설계 변경으로 리더에게 올린다
   - 누구든 → 리더(`main`): 산출물 파일 경로 + 한 줄 요약

3. **리더 모니터링**:
   - 완료 알림이 오면 산출물을 Read. qa 리포트에 FAIL 이 있으면 pipeline-engineer 에게 `SendMessage` 로 리포트 경로를 전달해 수정 라운드 진행
   - 수정 라운드는 **최대 3회**. 3회 후에도 FAIL 이 남으면 양쪽 근거를 사용자에게 올린다
   - spec-guardian 이 "설계 변경 필요" 를 올리면 Phase 3 으로 되돌아간다 (팀원은 대기)

4. **완료 조건**: qa 리포트 FAIL 0 + pytest passed ≥ 기준선 + `check_fixtures.py` 0 failed

### Phase 5: 마무리

1. 전체 재검증: `python3 -m pytest -q`, `python3 .claude/skills/pipeline-qa/scripts/check_fixtures.py`
2. 커밋 — pipeline-engineer 에게 요청하거나 리더가 직접. 메시지는 기존 `git log` 스타일(한국어 요약형). **푸시하지 않는다** (사용자가 직접 한다). `logs/last_run.txt` 가 로컬 실행으로 바뀌었으면 커밋에서 제외
3. `CLAUDE.md` 변경 이력 갱신 — **하네스 자체**(에이전트·스킬)가 바뀐 경우만. 파이프라인 코드 변경은 git 이력이 담당
4. `_workspace/` 보존 (`.gitignore` 대상 — 커밋되지 않는다)
5. 사용자 보고: 분류, 바뀐 것, 검증 결과(숫자), 커밋 해시, 사용자가 해야 할 조치(Secrets 갱신, Notion 토글 삭제, 푸시 등), 미해결 항목
6. 피드백 요청 한 줄: "결과나 팀 구성에서 고칠 점이 있으면 알려 달라" — 답이 없으면 넘어간다

## 데이터 흐름

```
[리더] ── 분류 ──► _workspace/00_input.md
   │
   ├─ Phase 2 (서브, 병렬)
   │     Agent(spec-guardian)   ──► 01_spec-guardian_impact.md
   │     Agent(ops-investigator)──► 01_ops-investigator_diagnosis.md
   │     Agent(pipeline-qa, 감사)──► 01_pipeline-qa_report.md          (E 만)
   │
   ├─ Phase 3 (C 만)  spec-guardian ──► 02_spec-guardian_spec-draft.md ──승인──► SPEC.md
   │
   ├─ Phase 4 (팀)
   │     Agent(pipeline-engineer) ◄──SendMessage──► Agent(pipeline-qa)   (E 면 Phase 2 의 것을 이어 씀)
   │        │  Read 01_*                                 │  첫 입력 = engineer 의 알림
   │        ▼                                            ▼
   │     src/ tests/ 변경                            03_pipeline-qa_report.md
   │     03_pipeline-engineer_changes.md                 │
   │        └────── SendMessage(to: spec-guardian) ◄─────┘   (SPEC 질의)
   │
   └─ Phase 5  pytest + check_fixtures ──► 커밋(푸시 없음) ──► 사용자 보고
```

## 파일 규약

- 루트: `/home/robot/tech_news/_workspace/` (절대 경로로 팀원에게 전달)
- 이름: `{NN}_{팀원 이름}_{artifact}.md` — `NN` 은 Phase 순번(00 입력, 01 진단, 02 설계, 03 구현·검증). 부분 재실행은 04 부터 이어 붙인다
- 비밀값은 어떤 산출물에도 넣지 않는다. `.env` 는 키 이름만

## 에러 핸들링

| 상황 | 전략 |
|------|------|
| 팀원 1명 무응답 | `SendMessage` 로 상태 확인 → 응답 없으면 같은 프롬프트로 1회 재스폰(`{이름}-2`) 하고 다른 팀원에게 새 이름을 알린다. 재실패 시 그 산출물 없이 진행하고 보고서에 "미수행" 명시 |
| 커스텀 `subagent_type` 거부 | `general-purpose` + 정의 파일 Read 지시로 폴백 (이름 규칙 참조) |
| `SendMessage` 호출 실패 (스키마 없음) | `ToolSearch("select:SendMessage")` 후 재시도 |
| spec-guardian 이 고정 항목 충돌 판정 | 즉시 중단·보고. 다른 팀원 결과는 참고 자료로 첨부 |
| ops-investigator 가 재현 불가 (`.env` 없음, `gh` 없음) | 정적 진단으로 대체. 사용자에게 Actions 로그 붙여넣기 요청 |
| qa FAIL 이 3라운드 후에도 남음 | pipeline-engineer·pipeline-qa 양쪽 근거를 사용자에게 올리고 커밋 보류 |
| engineer 와 qa 판정 상충 | 삭제하지 않고 양쪽 근거 병기. SPEC 근거가 있는 쪽 우선, 없으면 spec-guardian 판단 → 그래도 없으면 사용자 |
| 외부 API 일시 장애로 실측 불가 | 시각과 오류를 기록하고 fixture 기반 검증만으로 진행. 보고서에 "실측 미수행" 명시 |
| pytest 기준선보다 passed 감소 | 회귀로 간주. 삭제된 테스트가 SPEC 개정 때문인지 spec-guardian 확인 없이는 커밋하지 않는다 |
| 사용자 응답 필요한데 자율 실행 중 | 승인 게이트 직전까지 만들고 멈춘다. SPEC 개정·상태 변경 조치는 하지 않는다 |

## 테스트 시나리오

### 정상 흐름 — B 유형 (임계값 튜닝)
1. 사용자: "국내 클러스터가 너무 잘게 쪼개지는 것 같아. 자카드 임계값 0.30 으로 실측해보고 괜찮으면 바꿔줘"
2. Phase 0: `_workspace/` 없음 → 초기 실행. Phase 1: B 로 분류 (SPEC 6절이 "운영 중 튜닝 대상"으로 명시), 기준선 216 passed, `ToolSearch("select:SendMessage")`
3. Phase 2: `Agent(spec-guardian)` → impact: 닿는 절 6절, 고정 항목 아님, 검증 기준 = fixture 클러스터 4/3/2 유지 + 실측 건수
4. Phase 4: `Agent(pipeline-engineer)` + `Agent(pipeline-qa)` 동시 스폰. engineer 가 `JACCARD_THRESHOLD` 변경 + `test_rank_domestic.py` 통과 + `--dry-run --no-llm --date 2026-09-08` 실측 → `SendMessage(to: "pipeline-qa")` → qa 가 `test_rank_domestic.py`, `check_fixtures.py`, 실측 출력 검토 → PASS → 리더에게 리포트 경로
5. Phase 5: pytest 216 passed, 커밋 "실측 튜닝: 국내 자카드 임계값 0.35 → 0.30 (…근거)". spec-guardian 에게 `SendMessage` 로 SPEC 6절 값 갱신 요청·확인
6. 예상 결과: 커밋 1개(푸시 없음), `_workspace/00~03_*.md` 4개

### 설계 변경 흐름 — C 유형 (소스 추가)
1. 사용자: "해외 소스에 Lobsters 추가해줘"
2. Phase 2: `Agent(spec-guardian)` → "설계 변경" (SPEC 3·6·10·12절 영향, `article_id` 접두사 신설 필요). `Agent(ops-investigator)` → Lobsters API 인증·레이트 리밋 확인(확인일 기록)
3. Phase 3: spec-guardian 에게 `SendMessage` 로 초안 요청 → 사용자 승인 → SPEC v1.6 반영
4. Phase 4: engineer 가 `collect_lobsters.py` + fixture + 테스트, `main.build_services` 의 `overseas_collectors` 에 추가 → qa 가 수집→계약 경계면(article_id 규약, KST, metrics, `normalized_url`·`anchor_url` 두 키) + `check_fixtures.py` 건수표 갱신 확인
5. 예상 결과: SPEC 헤더에 "1.6 변경" 블록, 커밋 1개

### 에러 흐름 — A 유형에서 재현 불가
1. 사용자: "이번 주 카톡이 안 왔어"
2. Phase 2: `Agent(ops-investigator)` 가 `last_run.txt` 읽음 → `run_at` 이 정기 슬롯이 아님(수동 실행) + `status: already_exists` → 카카오는 호출조차 안 됐음. 정기 실행 부재 원인을 git 이력에서 확인. `gh` 없어 Actions 로그 못 읽음
3. 판정: 설정/배포 시점. 코드 수정 불필요 → Phase 4 생략 (spec-guardian 스폰 안 함)
4. Phase 5: 사용자 조치 안내 — Notion 토글 직접 확인, 알림이 꼭 필요하면 토글 삭제 후 다음 월요일 전에 `workflow_dispatch`, `scripts/kakao_refresh_token.py --test` 로 경로 확인
5. 예상 결과: 코드 변경 없음, `_workspace/01_ops-investigator_diagnosis.md` 1개, 보고서에 "재현: 로컬 .env 기준 / Actions 로그 미확인" 명시

### 에러 흐름 — Phase 4 에서 qa 무응답
1. engineer 가 `SendMessage(to: "pipeline-qa")` 를 보냈는데 30분째 리포트 없음
2. 리더가 `SendMessage(to: "pipeline-qa")` 로 상태 확인 → 무응답
3. `Agent(subagent_type: "pipeline-qa", name: "pipeline-qa-2", ...)` 로 재스폰, engineer 에게 "이제 `pipeline-qa-2` 에게 보내라" 통지
4. 재스폰도 실패 → 리더가 직접 `python3 -m pytest -q` + `check_fixtures.py` 만 돌리고, 보고서에 "경계면 교차 검증 미수행" 명시, 커밋은 사용자 확인 후
