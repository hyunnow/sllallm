# HANDOFF — sllallm 세션 인수인계 (2026-07-13 기준)

> 새 세션 시작 시 이 문서를 그대로 전달하면 이전 세션과 동일한 맥락·원칙·우선순위로 이어서 작업할 수 있다.
> 코드/스펙의 세부는 리포에 있으니 여기엔 "리포만 봐서는 모르는 것"을 적는다.

## 0. 프로젝트 정체 (30초 요약)

- **제품**: 학생이 실라버스(PDF 등)를 올리면 **현재·다가올 학기 시간표/일정**을 만들어주는 도구. 과거 학기 복원 아카이브 아님 (v7 §0).
- **현재 목표 (v4에서 재정의)**: 실라버스의 **전 필드 구조화 추출** + 필드별로 **rule / LLM / 하이브리드 방법 비교**를 데이터(gold)로 판정.
- **불변 원칙**: ① 틀리게 채우는 것 ≫ 못 채우는 것 (abstain-on-uncertain), ② 환각 0 (근거 없는 날짜·시각 생성 절대 금지), ③ 성능은 신뢰 gold로만 판정 (순환 gold 금지), ④ 해석(교시→시각, 주차→날짜)은 모델이 아니라 결정론 KB.
- **스펙 문서** (리포 루트, 시간순): `syllabus_classifier_claude_code_prompt.md`(v1 분류기) → `syllabus_edge_cases_master_v2.md` → v4 `syllabus_full_extraction_v4.md` → v5 `syllabus_eval_first_v5.md`(평가 무결성) → v6 `syllabus_next_step_v6.md`(표→하이브리드) → v7 `syllabus_kb_strategy_v7.md`(KB 전략). **v3(캘린더 컴파일/ICS)은 한 번도 공유받지 못함** — ICS가 범위에 들어오면 사용자에게 요청.

## 1. 지금까지의 상태 (측정치 포함)

**완료된 것**
- v1 시간 후보 분류기: klue/roberta 인코더 학습 완료(Colab). test: class_schedule **precision 0.984 / recall 0.490 / 면담→수업 0.000** @ threshold 0.80 (모델+validator 파이프라인). 모델은 Colab/Drive에 저장, 로컬 미보유.
- 전 필드 파이프라인: `normalize_doc`(pdfplumber/hwp5/CID감지) → `rule_fields`(+학수번호 4형태) → `table_plan`(주차표, 페이지분할 병합, abstain) → `field_router`(+C4 다분반 탐지) → `event_hybrid`(LLM 표면+무조작 게이트) → `record_builder`(교차검증) → `record_resolver`(Week N→날짜/주범위).
- KB: 교시표 5+2개교(값 채움, 동국=반교시제 "1.0"키), 학사일정 24항목(22개 high 사용가능, `term_start_confidence` 게이트). 커버리지: 교시 문서 7/7, 현재학기 이벤트 — in_document 38 / calendar 해결가능 49 / 잔여 actionable 9.
- Gold: **배치1** 37docs·475셀 확정(게이트: 편집률 38.6%, blind 격차 +9.7%p) / **배치2** 36docs·442셀(정정 후 편집률 31.1%, 격차 +17.6%p ⚠주의 유지) / **배치3** 40docs·560셀 **확정·게이트 통과** (편집률 24.48%, blind 격차 **+8.35%p** — 배치1보다 낮음; 메모 26건 전량 대응, 커밋 로그 참조). 2026-07-10 사용자 결정 3건(대학 간접추론 승인·B3-028 정정·무기한 통일)이 gold 6셀 정정으로 반영됨(검수 xlsx 메모에 근거 기재).
- 방법 비교(배치3 40docs, 잠정, cov/prec/fab): 대학 **98/100/0** · 학기 60/100/0 · 학년도 52/100/0 · 학점 42/100/0 · 수업시간 **22/78/0** (요일묶음 동치 채점) · 연락처 82/82/6 · 학수번호 72/79/0 · 과목명 65/77/0 · 총주차 40/81/0 · 교수 48/47/0 ⚠ · 주차별내용 40/38/6 · 이벤트 하이브리드 cov85%·event-level 완전일치 11/128·type 84·kind 86·title 51·date 15 · 무기한과제 57/13/83 (기준 확정이 gold보다 늦어 배치1~3 gold와 미정합 — **배치4부터 유효 측정**).
- 배치2 재측정(정정 후): 대학 94/100/0 · 수업시간 18/83/0 · 이벤트 하이브리드 완전일치 **14**/70·title 45·type 60. 이벤트 hybrid cell-fab(배치3 15%)은 무기한 시험 null|uncertain 승격이 옛 gold와 부딪히는 전환기 노이즈 — 배치4 안내문 규칙으로 해소 예정.

**핵심 이슈/컨텍스트**
- 배치2 앵커링 격차 +16.7%p는 "주의 딱지" 상태 — 승자 확정 금지 유지(v5 §4-3), field_methods.yaml은 잠정 그대로.
- 검수자(사용자)는 **메모 칸에 이슈를 남긴다 — 매 배치 반드시 전량 정독** (한 번 놓쳐서 지적받음; 99건 대응 이력은 커밋 로그 참조). 'N' 마크 = 의도적 미확정.
- 코퍼스: `실라버스 모음 폴더/` 1,026파일(git 제외), 39건 스캔 → **Colab EasyOCR 백로그**, 3건 .doc/.docx 미지원, CID깨짐 2건은 needs_ocr 자동 분류됨.

## 2. 진행 중 / 대기

| 항목 | 상태 | 다음 행동 |
|---|---|---|
| 배치3 | **완료** (게이트 통과 +8.35%p) | — |
| 배치4 | **완료** (2026-07-10 저녁: 게이트 통과 — 편집률 37.5%, blind 격차 **+6.66%p 전 배치 최저**; 메모 14건 전량 대응) | — |
| **표본 tripwire — 학년도 발동** | 표본 편집률 27%(3/11) > 배치3 전수 10%×2 | **배치5에서 학년도 전수 복귀** (`--sample-fields "학수번호,교수"`만). 원인: LLM 초안이 낡은 연도(2022)를 잡음 — 우리 rule 추출기는 증거형 규칙이라 무사(프리시전 100%) |
| 배치5 | **완료** (2026-07-12: 게이트 통과 — 편집률 24.2%, blind 격차 **+2.31%p 또 최저**; 메모 18건 전량 대응) | — |
| gold 판정 5건 | **반영 완료 (2026-07-12 사용자 확정, `d5dc04d`)** | B5-015 학년도 2026+학기 봄 / B5-024 수업시간 '화234'(대학 null) / B5-003 교수 Manglani+괄호 제거 / B5-002 수업시간 빈칸 / B5-026 연락처 라벨 미채택('3345'). 재ingest 후 게이트: 편집률 23.0%, blind 격차 **+1.97%p** |
| **정책 최종 확정: 대학 증거 = 본문 > 이메일 > 파일명** | 반영 완료 (2026-07-12 저녁) | 사용자가 파일명 출처(kocw 아카이브 명명 규칙) 확인 후 **파일명 폴백 유지** 확정 — 한 차례 철회를 복원, gold 3셀(B5-005 숭실대·B5-024 홍익대·B5-036 서강대) 정합. 배치2~5에서 파일명이 결정 증거인 문서 20건(전체 명단은 커밋 d5dc04d 다음 커밋 메시지·세션 로그). **대학 100%cov/100%prec/0%fab** |
| B5-036 학수번호·교수 | **확정 반영** (PHI2007·서상복) | 재ingest 후 **배치5 rule 추출기 fab 전 필드 0%** — 게이트: 편집률 22.9%, blind 격차 +2.09%p |
| **배치 종료 전망 (2026-07-12 판단)** | 원 계획(배치3 후 2~3회) 중 2회 소화 | **배치6이 기본 마지막 — "규칙 동결 검증" 배치**: 게이트는 수렴 완료(+2.09%p), 신규 엣지만 아직 0이 아님(b5에서 신규 3건+정책 2건). 배치6 메모에서 신규 관례 ≤1건이면 gold 표기 규칙 동결 선언 → 승자 확정(§4-3 dev/holdout) → 역방향 학습 트리거 3조건 충족. 3건+ 나오면 배치7 1회 연장 |
| 배치6 | **완료** (2026-07-13: 게이트 통과 — 편집률 29.4%, blind 격차 +7.75%p; 메모 27건 전량 대응) | **동결 판정: 신규 관례 4건 ≥3 → 배치7 연장 발동.** 신규: ① 날짜/세션→주차 부여(정책 A, 구현 완료 — 표·산문 양쪽, B6-020 9/9주·B6-019 15/16주) ② 학습목표 vs 강의내용(정책 B: 내용 우선) ③ 과제 출제/마감 의미론(정책 C: 행동일 기준, 반복 과제=recurring 이벤트) ④ 계절학기 bare 교시열 관행(B6-002, 구현 완료). 검수 슬립 3건(B6-001/002/026 행 밀림) 정정 완료. B6-001은 텍스트리스 PDF — OCR 백로그 추가 |
| **GwaTop 이식 트랙 (2026-07-13 개시)** | **1단계 완료** | 사용자 결정: ① 1차는 **heuristic+규칙 파이프라인**(인코더는 후속 — 체크포인트가 Colab/Drive에만 있고 EC2 워커 메모리 제약), ② **섀도 비교 후 컷오버**, ③ 기존 OpenAI 파서는 설정 플래그 폴백으로 **영구 보존**(삭제 금지). 단계별 설계·필드 매핑·실행 프롬프트·**진행 체크리스트**는 로컬 `GWATOP_PORT_PLAN.md`(git 제외, 인프라 상세 포함이라 비공개) — **이식 관련 세션은 그 문서를 먼저 읽을 것**(진행 상태의 진실은 그 문서). 0단계: gwatop-backend 태그/브랜치/베이스라인, dev 리베이스, pytest 106 green. 1단계: **이 레포** — KB 4개 패키지 내장+package-data, config 로딩순서, env.py 수정, `api.py::extract_syllabus`, compiler `kind` 필드, 신규 테스트 8개 → **pytest 156 green**, 설치 스모크 통과, `v0.1.0` 푸시. 2단계: **gwatop-backend `feature/sllallm-parser`** — 어댑터(`sllallm_parser.py`)+디스패처(`syllabus_engine.py`, openai|sllallm|shadow)+seam 교체(779, 하류 무변경)+config 4키+섀도리포트/dryrun 스크립트, 신규 테스트 21 → **127 green**, 기존 OpenAI 파서 무변경 보존. 3단계: **EC2 프로덕션 섀도 배포 완료**(dev@ffa0748, shadow 라이브, 서비스 healthy, API 200). 배포 전 EC2가 앞서있던 `1f865da`(schedules 수정) 위로 리베이스 후 배포. **섀도 비교 9건 판정: heuristic 컷오버 불가** — class_times 실데이터 0% 일치(15→0, 웹 시간표 상실), 과목명 12%, exams 66→24. **인프라(어댑터/디스패처/섀도/플래그)는 완성·검증**, 전환은 플래그 한 줄. class_times 추출 보강 티켓 완료(**v0.2.0**, main@36d74e5): 수업시간 포맷(HHMM·N시·bare교시) + **async 오탐 구조 수정**(KOCW=출처 제거, raw_time→present, 근거없음→not_specified+needs_review) + no-title 폴백, 회귀 8 tests, 총 164 green. 재측정(한국어 22건): async 오탐 ~전부→2, class_times 20→2 였던 게 22→4. **⚠ 잔여 갭은 티켓이 아니라 상류 텍스트 품질**(포털 PDF 글자깨짐→school=None→bare교시 KB키 부재). (a) 포털 URL로 school 감지 보강 **완료(v0.2.1)** — 하지만 class_times 3/28 불변: 막힌 문서는 학교명·URL 둘 다 텍스트에 없음(pdfplumber가 포털 export에서 소실). **class_times 천장 = 텍스트 추출 품질로 확정.** sllallm은 깔끔한 PDF에 강하고 degraded PDF는 이미 폴백(no-title→OpenAI)으로 처리됨 → **품질별 하이브리드가 자연 착지점.** **v0.2.4 섀도 배포 완료**(품질 향상: ① 시험 과다추출 dedup 건국 6→2 OpenAI와 동일, ② 연세 title 타임스탬프 가드. 건국 데모서 과목명·교수·수업시간·주차·시험 전부 OpenAI 일치 — 깔끔한 한국어 PDF선 sllallm≈OpenAI. 과제 갭은 OpenAI 과다추출이라 버그 아님). **v0.2.3**(과목명 개행/비교 정규화 → 과목명 일치율 1/8→7/8(88%)). **v0.2.2 섀도 배포**(사용자: 품질별 하이브리드 수용). gwatop dev@9b98a80(핀 v0.2.2), EC2 재설치·재시작, sllallm 0.2.2 라이브, API 200. **프로덕션 서빙은 여전히 OpenAI**(shadow는 병행 비교만) — 영문 표본은 불변(교시/KOCW 개선은 한국어용), **한국어 강의계획서가 업로드되면 개선 드러남**(로컬 하네스 입증: class_times 20→2가 22→4, async 오탐 해소). **다음 행동: organic 한국어 섀도 데이터 축적 관찰 → 충분하면 품질별 하이브리드 컷오버(sllallm 우선+OpenAI 폴백) 판정. 텍스트 추출(OCR) 투자는 별도 판단.** shadow 되돌리려면 EC2 `.env` backend=openai+워커 재시작. |
| 배치7 | **완료** (2026-07-13 밤: 편집률 25.8%, blind 격차 +14.76%p **주의 딱지** — 불일치가 자유서술 필드에 집중된 표본 구성 효과, 구조 필드는 깨끗) | 메모 4건 전량 대응: B7-040 중복 글리프 복원(`repair_doubled_runs`)+년도 표기+차시 헤더 구현, B7-008 topic-mode 관례 채택(안내문 반영). **B7-008 주차별내용은 N 마크** — 사용자가 Y로 바꾸면 재ingest 시 gold 편입 |
| **gold 표기 규칙 동결 선언 (2026-07-13)** | **성립** — 배치7 신규 관례 1건(B7-008, 채택 완료) ≤ 기준 1건 | 역방향 학습 트리거 ①동결 ✓ ②게이트(6배치 중 주의 2·통과 전부) ✓ ③승자 안정 ✓ — **합성→학습 재개 가능** |
| **승자 확정 (§4-3)** | **완료** — `scripts/17_winner_report.py`, 배치2~7 233docs, dev140/holdout93, seed42 | 전 14필드 민감도 안정(주의 배치 제외해도 불변). 13필드 ours(rule), 무기한과제만 ours_hybrid(유일 공급, 품질 잠정 18/29/59). **이벤트: 위험가중 규칙이 hybrid(cov 85%, fab>0)를 누르고 rule(fab 0%) 선택** — hybrid는 자동채움이 아니라 검토 큐 후보. 결과: `data/gold/field_winners.json` + `field_methods.yaml` 확정 주석. gold 축적 종료 — 배치8 없음 |
| 이벤트 gold 관례 통일 소급 | 선택 | 무기한 시험 `null\|uncertain` 규칙은 배치4부터 — 배치2/3 이벤트 gold는 구 관례라 hybrid fab 11~17%p가 관례 차이 잡음. 소급 정정 여부는 사용자 판단 |
| 주차별내용 week-level | **새 진단 지표** (16에 추가) | cell 완전일치는 검수자 요약·오타에 지배(v5 §3-3 자유서술=의미일치 원칙). 배치4: 주차 커버 65%·단어 회수율 72%, 배치3: 51%/80%, 배치2: 54%/65% |
| **gold 기준 합의 3건** | **해소 (2026-07-10 사용자 결정)** | ① 대학 간접추론 **허용**(이메일 도메인·파일명·본문 부분표기) — 구현·배치2 gold 3셀 정정 완료. ② B3-028 수업시간 = "MON WED 10:30-11:45" 정정 완료. ③ 무기한 항목 통일: 날짜 있음→이벤트, 무기한 시험→이벤트 `null\|uncertain`, 무기한 과제류→무기한과제만(중복 금지) — risk_gate·안내문·gold(B3-019) 반영 완료 |
| 학기 gold 소급 | 선택 | 배치1·2 gold의 학기 값은 숫자 표기 잔존 — 채점은 계절동치라 영향 없음, 소급 수정은 선택사항 |
| 수업시간 커버리지 | 22% | raw_time 라벨 없는 문서: 수업 이벤트→notation 직렬화 확장 |
| 주차별내용 차시별 상세 | 백로그 (B3-030/031) | 주차 옆 "내용 요약"/차시·날짜별 상세 칼럼 파싱 — 산문형과 함께 LLM 하이브리드 확장 후보 |
| 전 코퍼스 레코드 리포트 | 미실행 | `scripts/10` 1,026건 전량 + 필드 채움률/해석률 리포트 |
| Colab OCR 39+2건 | 백로그 | EasyOCR 후 재정규화·재추출 |
| 중복 실라버스 탐지 | 백로그 | B2-033(한 파일 多실라버스) + B3-025≡B3-031(파일 간 동일 실라버스) 파일/내용 단위 탐지 |

## 3. 사용자 질문에 대한 판단 (2026-07-08 답변 요지 — 유지할 입장)

- **역방향 학습(합성→학습)**: 아직 이르다. 트리거 = ①gold 표기 규칙 동결(**여전히 진화 중** — 배치3에서 학기 계절 표기·대학 간접추론 신규 규칙 발생), ②배치3 게이트 통과(✅ 달성), ③필드별 잠정 승자의 안정. 그 전 합성은 surface aug(이미 있음)까지만.
- **배치 검수 횟수**: 배치3 후 **2~3회 더**(총 150~200문서)면 승자 확정 가능 수준. 단 매 배치 (a)신뢰 게이트 (b)신규 엣지(메모) 발생률로 조기종료/연장 판단. 편집률 낮은 필드(학수번호 0%·교수 6%·학년도 10%)는 표본 검수로 부담 축소 가능. 배치3 메모 발생률(26건/560셀)은 배치2(99건)보다 크게 감소 — 수렴 신호.

## 4. 작업 규율 (이 세션에서 확립된 것 — 반드시 유지)

1. **PII**: `githooks/pre-commit` 활성 (`git config core.hooksPath githooks`). 데이터/엑셀/실라버스/gold는 절대 커밋 금지. 레포는 **public**임.
2. **게이트 우선**: gold 배치는 신뢰 게이트(편집률·blind 격차) 보고 전에 비교에 쓰지 않는다.
3. **abstain 원칙**: 변환·추출이 불확실하면 비우고 needs_review (bare 숫자열 교시 해석 금지, 밀린 표 미방출, 비증거 날짜 차단 등 전부 테스트로 고정).
4. **confidence 게이트**: 학사일정 `term_start_confidence`가 high(기본)가 아니면 확정 변환 금지.
5. **검수 메모 전량 정독** 후 메모→조치 대응표로 보고. 회귀 테스트는 메모 ID를 이름에 남긴다(`test_reviewer_memo_cases.py` 참조).
6. Phase/단계 끝마다 요약→확인. 승자 확정은 N 커질 때까지 금지. 커밋 메시지에 측정치와 근거를 남긴다.

## 5. 빠른 실행 레퍼런스

```bash
git config core.hooksPath githooks        # 필수 (새 클론 시)
python3 -m pytest -q                      # 118 tests
python3 scripts/16_batch2_eval.py --batch 7   # 배치별 평가 (ours/hybrid; --batch 2~7)
python3 scripts/17_winner_report.py       # 승자 확정 리포트 (dev/holdout, 민감도)
python3 scripts/15_kb_coverage.py         # KB 커버리지
python3 scripts/10_extract_record.py --sample 8   # 전체 레코드 파이프라인
# OPENAI 키: gwatop-backend/.env에서 자동 로드 (common/env.py), gpt-4o-mini
```
데이터 위치(전부 git 제외): gold `data/gold/`, 원본 `실라버스 모음 폴더/`, 검수용 원본복사 `b-2/`~`b-7/`, 비교엑셀 `ParserTest.xlsx`(37건 하네스), Colab 모델 노트북 `notebooks/train_colab.ipynb`.

## 5.5 v3 뒷단 (2026-07-13 심야 — 사용자가 v3 문서 공유, "1번부터 쭉" 지시로 구현 완료)

- **v3 문서 입수됨** (`~/Downloads/syllabus_backend_v3.md` — ICS 범위 확정). Phase 0 질문 5개는 기존 결정으로 답변: 출력=ICS+JSON, needs_review는 ICS 미포함(별도 JSON), 필드 추출=rule 자동/hybrid 검토큐.
- **기존 자산으로 충족**: Phase A(record 스키마), B(period_timetables/academic_calendars.yaml — §5-3 로드 검증 이번에 추가), C/D(kb/resolver.py의 in_document>KB>needs_review 3단), E(이벤트 계약).
- **신규 구현**: `compile/calendar_compiler.py`(3-버킷: confirmed/weekly_timetable/needs_review — weekly_timetable은 날짜 무관 시간표라 학사일정 없어도 안전) + `compile/ics_writer.py`(RFC 5545 직접 작성, TZID Asia/Seoul, UNTIL UTC 변환, 75-octet folding, needs_review 미포함) + `scripts/18_compile_report.py`(전 구간 리포트 + 위험 지표).
- **전 코퍼스 1,026건 e2e**: confirmed 24 이벤트(13 docs — 정책상 2026 가을/여름+high 캘린더만 RRULE 확정), 시간표 슬롯 382(222 docs), needs_review 2,650(최다 사유 "날짜 근거 없음 raw 유지" 2,150 = 정직한 abstain). **위험 지표 3종 전부 0** (근거없는 확정/공휴일 수업/면담 혼입 — §11 목표 달성, 컴파일 가드가 실제 유출 2건(출력일·인용날짜)을 잡아 차단 규칙化).
- ICS 눈검수 10건: `data/records/ics/` (git 제외).

## 5.6 다섯 트랙 일괄 진행 (2026-07-13 심야 — 사용자 "1번부터 쭉" 지시)

동결·승자확정 이후 사용자가 지목한 ①~⑤ 전부 완료:
- **③ 전 코퍼스 리포트** (`scripts/19_corpus_report.py`): 977 텍스트유효. 채움률 대학99·학수번호79·학기71·이메일70·총주차60(record 스키마 갭 수정 — build_record가 total_weeks를 안 넘기던 것 배선), 약필드 강의실23·교수26. 해석률: 상대참조 1787개 중 10%만 날짜化(정책상 2026 가을/여름 high 캘린더 한정, 나머지 정직한 abstain).
- **⑤ 중복 탐지** (`scripts/20_dedup.py`, `dedup/`): 파일명키(kocw 학교·과목·교수, **NFC 정규화 필수**)+MinHash(0.9 분리선). B3-025≡031(텍스트 0.08인데 파일명키로 same_course), B2-033(간호학 4과목) 정확 포착. 82클러스터=같은강의46/템플릿얇은추출36, 파일내다중 5. `duplicates.json`.
- **④ OCR 백로그** (`scripts/21_ocr_backlog.py`, `extract/ocr_backlog.py`): 로컬 OCR엔진 없음=**Colab 몫**(불변). chrome-only 탐지 신설(B6-001: URL·페이지머리글 495자→needs_ocr). 매니페스트 52건(원본경로 전부 확인)+`--reingest` 브리지(왕복 검증). normalize_pdf에 저내용 가드 배선.
- **② 약필드** (`rule_fields`): 강의실 결합셀 방추출("월2,3(사범313)"→"사범313") holdout 44→77%; 교수 이름/성명 라벨+이메일/접두 제거 50/86%. 무기한과제는 gold 비일관('Homework' 판정 문서마다 다름)으로 개선 저항 확인·문서화(승자 유지).
- **① 역방향 학습** (`scripts/22_synth_dataset.py`, `dataset/synth.py`): 동결 규칙·cue로 희소클래스 합성(policy 43→257·exam 145→359·office 136/166→307/337). 무결성(라벨마다 cue 보유)+누출가드(synthetic__ 접두, val/test 불가침)+로컬 검증(office→class 누출 0). **학습은 Colab**: `07_train.py --train-file data/splits/train_plus_synth.jsonl` (미실행, Colab 대기).

## 5.7 분류기 재학습 (Colab, 2026-07-13) — 임계값 0.5로 완화

- **합성 재학습 완료** (Colab, `train_plus_synth.jsonl`): 고정 0.80 임계값에선 precision 0.991/recall 0.438 — 합성이 대조 클래스 과다로 모델을 보수화해 recall이 베이스라인 0.490보다 **하락**. 하지만 sweep(`08_eval`)이 프론티어를 드러냄: 모델+validator에서 **임계값 0.5 → precision 0.946/recall 0.633/office→class 0.000**.
- **결정 (사용자)**: precision 하한 0.98→**0.95 완화, 임계값 0.5 채택** (`train.yaml` 반영). 빈 캘린더가 오탐보다 나쁘고, validator가 office→class를 임계값 무관 0으로 보장하므로 안전.
- **FP 분해 증거** (`scripts/23_fp_breakdown.py`, Colab): 0.5의 FP 9는 **전부 gold=unknown, exam/assignment 누출 0**. → validator의 exam/assignment 차단(`block_events`)은 **코드에 넣되 휴면 OFF 유지**. 활성화 트리거: real holdout에서 exam→class/assignment→class 오탐 관찰 시.
- **후순위 큐(#19)**: 합성 레시피 재조정(대조 클래스 비중 축소 → 0.98 하한에서도 recall↑). 임계값 무관 프론티어 개선이라 나중에.
- **재학습 재현**: Colab `git pull` → `22_synth_dataset.py --n 1200` → `07_train.py --train-file data/splits/train_plus_synth.jsonl` → `08_eval.py --model checkpoints/encoder/best`. 학습된 체크포인트는 Colab/Drive(로컬 미보유).

## 5.8 후속 3종 (2026-07-13, 사용자 "1~3 전부 실행")

- **로컬 모델 배선** (`model/load.py`): `load_classifier('heuristic'|<ckpt>)` 단일 로더, 임계값은 train.yaml(0.50) 단일 소스. `09_predict`·`18_compile_report`·`19_corpus_report`에 `--model` 플래그 추가 — 체크포인트를 로컬에 받으면 `--model checkpoints/encoder/best`로 학습 모델을 전 파이프라인에 태운다(exam/assignment 커버리지에 영향). 체크포인트는 Colab/Drive.
- **합성 레시피 v2** (`dataset/synth.py`): 1차가 대조 클래스 과다로 recall↓였던 것 교정 — class_schedule를 지배 비중으로(+436, 이전 +129) + 표면형 8종(교시·범위·단일시작@강의시간필드·요일범위·영문full…), 대조 클래스 축소(exam 5→3, office/policy 등 하향). 무결성·누출가드 유지. **검증=다음 Colab 재학습**(22→07→08). 0.98 하한에서도 recall 오르는지 확인.
- **Colab OCR 러너** (`scripts/24_colab_ocr.py`): 매니페스트 각 원본 → 텍스트(.pdf=pdf2image+EasyOCR, office/hwp=libreoffice txt) → `<doc_id>.txt`. Colab에서 `apt install poppler-utils libreoffice` + `pip install easyocr pdf2image` 후 실행 → `21 --reingest`. 로컬은 엔진 없어 전량 skip(정상).

## 5.9 레시피 v2 재학습 결과 + OCR 실행 교훈 (2026-07-13)

- **v2 재학습 (Colab)**: 0.95 하한에서 recall **0.550→0.633 (+8pp)** — v1은 0.95를 넘으려면 임계값 0.7(recall 0.550)까지 올려야 했으나 v2는 임계값 0.4에서 precision 0.952/recall 0.633. **train.yaml 0.5→0.40 반영.** office→class 0 유지.
- **recall 천장 발견**: 모델 단독 recall 0.821이 validator를 거치며 **0.633으로 캡**됨(형태 규칙이 진짜 수업 일부를 쳐냄). 합성 레시피 레버는 소진 — recall을 더 올리려면 **validator Rule 3/4 완화 조사**(작업 #20). 이게 다음 recall 레버.
- **OCR 실행 교훈**: `24_colab_ocr.py`를 Colab에서 돌리면 실패 — 매니페스트·원본 파일(`실라버스 모음 폴더/`)이 git 제외라 clone에 없음. **OCR은 로컬에서 하는 게 맞다**(파일·매니페스트 다 로컬): `brew install poppler libreoffice` + `pip3 install easyocr pdf2image` → `python3 scripts/24_colab_ocr.py` → `21 --reingest`. Colab은 엔진만 없었을 뿐 불필요.

## 5.10 validator recall 캡 조사 결론 (작업 #20, 2026-07-13) — 가설 기각

`scripts/25_validator_recall_probe.py`(모델 불필요, test.jsonl 로컬)로 분해:
- gold=class_schedule 251건 중 validator 통과 163 → **허용 recall 상한 0.649**. 쳐낸 88건 중 **86건이 Rule 4(단일 시점·형태 없음)**.
- 쳐낸 후보의 실체: `MON`·`WED`·`화`·`27강`처럼 **시각 없는 요일/회차 조각**. validator가 막는 게 **옳다**(시각 없는 "월"은 캘린더 이벤트 불가). → **validator는 완화 대상 아님.**
- 그중 55건은 근처 텍스트에 시각 존재("MON" + nearby "13:00-14:00") — 후보 추출기가 요일+시각을 쪼갠 것. 살리려면 후보 재분절+재라벨(대공사).
- **결정적**: 실제 수업 시간표는 `meeting.raw_time`(규칙 추출기, 승자확정)에서 오고 규칙 추출기는 "MON 13:00-14:00" 전체 셀을 이미 읽는다. 분류기 class_schedule recall은 `meeting.status`만 좌우 → **recall 0.63을 올려도 실제 시간표는 안 변한다.** 후보-병합은 대공사인데 제품 가치 낮음 → **미추진.**
- (선택 후속) 컴파일러가 raw_time 없을 때 분류기 class_events로 폴백하지 않음 — raw_time 미포착 문서에서 분류기가 찾은 수업시간이 유실. 규칙 추출기 raw_time 커버리지 감안하면 한계효용 낮아 보류.

## 5.11 End-to-end ICS 눈검수 (v3 §11, 2026-07-13) — 실버그 3개 발견·수정

집계 위험지표(fabrication 0)는 gold 없는 코퍼스 문서의 날짜 오파싱을 못 잡는다. 문서→ICS 개별 이벤트를 원문과 대조해 **컴파일러 버그 3종**을 잡았다(전부 `calendar_compiler.py`, 회귀 테스트 `test_compile.py`):
1. **말도 안 되는 연도**: 회사법1 주차표 오타 '2076-10-20'(원본 1→7)이 확정됐다. 학년도 없을 때 **문서 지배연도**(2016) 기준으로 크게 벗어난 확정일 차단.
2. **주차행 오추출 시험**: UNIST 2026 "Week 5 (Tuesday 2026-04-02)" 주차행이 시험으로 새어, TBA 시험을 4/2에 가짜 확정. **제목이 주차마커면 이벤트 거부** — 이제 UNIST는 확정 0(시험 전부 TBA로 needs_review) ✓.
3. **과거 학기(v7 §0)**: 확정 34건 중 32건이 2013~2024 kocw 옛 실라버스. `compile_record(current_year=)` 필터로 과거 확정→needs_review. `18` 스크립트가 오늘 연도 자동 전달.
- **결과**: 전 코퍼스 확정 이벤트 42→**2건**(홍익대 전자기학 중간 2026-04-22·기말 2026-06-10 — 원문 시험 셀에 저녁 18-20시로 명시, **검수 정확** ✓), 위험 3종 0. 즉 파이프라인이 이제 현재학기 진짜 시험만 확정한다.
- 잔여(사소): 시험 제목이 "중간고사" 대신 주차번호("8")→course명으로 정리됨(날짜·이벤트는 정확). 과거 실라버스의 cue-날짜 오정렬은 남지만 현재연도 필터로 제품에선 안 보임.

## 6. 다음 세션 시작 절차

1. 이 문서 + `git log --oneline -20` 훑기.
2. **gold 축적 종료 + ①~⑤ 완료 (2026-07-13).** Colab 대기 2건: 합성 데이터로 klue 재학습(`train_plus_synth.jsonl`), OCR 백로그 52건(`ocr_manifest.jsonl` → EasyOCR → `21 --reingest`). 그 외 후보: 캘린더 KB 2027-1 확장(confirmed 커버리지↑), Google/Apple 실기기 ICS 임포트 검증.
3. 잔여 소소한 것: B7-008 주차별내용 N 마크(사용자가 Y로 바꾸면 재ingest), B4-029 gold 오타 'Thinkling', B7-040 학기 gold '1'(계절동치라 채점 무해).
4. 배치5 관찰: 단국 그리드 학수번호 라벨 미커버(B5-031/037 gold '567140-1'형 — 라벨 사전 확장 후보), 정규화 파일명 NFD 한글(glob 시 NFC 변환 필요), B5-002 수업시간 gold '45'는 검수자 추측성 입력(시수 값) — 확인 필요, B5-026 연락처 라벨식 표기 제안("연락처1(연구실): ...") — 표기 규칙 합의 필요.
