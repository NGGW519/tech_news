# tech_news

## 하네스: 주간 테크 뉴스 브리핑 파이프라인 유지보수

**목표:** 주 1회 무인 실행되는 파이프라인(수집 → 랭킹 → 보강 → Gemini 요약 → Notion + 멘션 알림)을 SPEC.md 권위 아래에서 진단·설계·구현·검증하는 4인 에이전트 팀 운영.

**트리거:** 파이프라인·수집 소스·랭킹·요약·Notion·알림·GitHub Actions·SPEC·fixture·실행 로그·자격 증명에 관한 변경·수정·튜닝·진단·감사 요청 시 `tech-news-orchestrator` 스킬을 사용하라. 후속 요청("다시", "수정", "보완", "~만 다시")도 같다. SPEC 한 줄 질문이나 코드 설명 같은 단순 질의는 직접 응답 가능.

**변경 이력:**
| 날짜 | 변경 내용 | 대상 | 사유 |
|------|----------|------|------|
| 2026-09-09 | 초기 구성 — 에이전트 4 (spec-guardian, pipeline-engineer, pipeline-qa, ops-investigator), 스킬 5 (tech-news-orchestrator, spec-change, pipeline-dev, pipeline-qa, ops-runbook), fixture 검사기 번들 | 전체 | - |
| 2026-09-09 | 팀 모드를 `Agent(name)` + `SendMessage` + 파일 기반으로 정의 | skills/tech-news-orchestrator | 이 환경에 `TeamCreate`/`TaskCreate` 도구가 없음 |
| 2026-09-09 | 팀원 `name` = 에이전트 정의 이름으로 통일, 이름 재사용·재스폰 규칙, `ToolSearch` 선행 규칙, A→B 승격 시 spec-guardian 스폰 | orchestrator, agents/* | 드라이런 리뷰: 짧은 이름(`qa`)과 정의 이름(`pipeline-qa`)이 달라 Phase 4 통신이 전부 실패 |
| 2026-09-09 | 하위 스킬 4개 description 에 "오케스트레이터가 진입점" 표시, 오케스트레이터 제외 조항 정량화·저장소 범위 명시 | skills/* description | 트리거 판정 20/20 통과했으나 하위 스킬이 동급 경쟁 |
| 2026-09-09 | 경계면 #3 생산자를 해외 수집기로 정정, fallback 원천 순서(입력 순서와 반대) 명시, Reddit 제거·fixture 유지 사실, dry-run 전제(.env 7키·실제 수집 호출), incremental QA 루프 순서 | skills/pipeline-qa, pipeline-dev | QA 실행 테스트에서 스킬 문서 오류 5건 발견 |
| 2026-09-09 | 진단 트리에 "run_at 이 정기 슬롯 아니면 수동 실행 → 정기 실행 부재 원인부터", "already_exists 면 카카오 미호출" 추가 | skills/ops-runbook | with/without 실행 테스트 두 쪽이 공통으로 도달한 통찰 |
| 2026-09-09 | 팀원 프롬프트 첫 줄에 에이전트 정의 파일 Read 지시를 항상 넣도록 규칙화 | skills/tech-news-orchestrator | 프로브: 세션 중 생성한 커스텀 타입은 스폰은 되지만 정의가 시스템 프롬프트로 로드되지 않음 |
| 2026-09-09 | SPEC v1.6 — 알림 채널을 카카오 "나에게 보내기" → Notion 본문 멘션으로 교체. 스킬 5종·README 동기화 | SPEC, skills/*, README | 카카오가 "나에게 보내기"에 푸시를 의도적으로 발생시키지 않음(담당자 답변 3건). Notion 멘션은 푸시 + 탭 1회로 그 줄 도달 — 실측 확인 |
