# HANDOFF — sllallm 세션 인수인계 (2026-07-08 기준)

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
- Gold: **배치1** 37docs·475셀 확정(게이트: 편집률 38.6%, blind 격차 +9.7%p) / **배치2** 36docs·442셀(편집률 31.9%, 격차 +16.7%p ⚠주의 — 표기이탈 반감 후에도 잔존) / **배치3** 생성완료·검수 대기(40docs, 학수번호 첫 포함, blind B3-001/011/016/021/022/028, 원본은 `b-3/`).
- 방법 비교(배치2, 실제 표, 잠정): 과목명 68%cov/91%prec · 학년도 47/100 · 학점 50/100 · 연락처 76/85 · 학기 ~65+(계절동치) · 총주차 38/54 · 주차별내용 35/42 · 수업시간 18/67/조작0 · 이벤트 하이브리드 cov74%·완전일치 9/70·date_kind 44/70·조작0 · 무기한과제 잔여 조작은 gold 누락 의심.

**핵심 이슈/컨텍스트**
- 배치2 앵커링 격차 +16.7%p는 "주의 딱지" 상태 — 승자 확정 금지 유지(v5 §4-3), field_methods.yaml은 잠정 그대로.
- 검수자(사용자)는 **메모 칸에 이슈를 남긴다 — 매 배치 반드시 전량 정독** (한 번 놓쳐서 지적받음; 99건 대응 이력은 커밋 로그 참조). 'N' 마크 = 의도적 미확정.
- 코퍼스: `실라버스 모음 폴더/` 1,026파일(git 제외), 39건 스캔 → **Colab EasyOCR 백로그**, 3건 .doc/.docx 미지원, CID깨짐 2건은 needs_ocr 자동 분류됨.

## 2. 진행 중 / 대기

| 항목 | 상태 | 다음 행동 |
|---|---|---|
| 배치3 검수 | **사용자 진행 중** | 완료되면 `13_gold_ingest --review data/gold/gold_review_batch3.xlsx --drafts data/gold/drafts_batch3.jsonl --out data/gold/gold_batch3.jsonl` → **신뢰 게이트(편집률·blind격차)부터 보고** → 통과 시 16류 재측정 (배치3 평가 스크립트는 16을 batch3 경로로 일반화 필요) |
| 무기한과제 gold 기준 | 미결 | 다음 배치 안내문에 "평가표 안 무기한 산출물 포함" 기준 명시 여부 사용자와 합의 |
| 수업시간 커버리지 | 18~23% | raw_time 라벨 없는 문서: 수업 이벤트→notation 직렬화 확장 |
| 주차별내용 미출력 13건 | 원인=표 미탐지 | 산문형 주차계획은 LLM 몫(하이브리드 확장 후보) |
| 전 코퍼스 레코드 리포트 | 미실행 | `scripts/10` 1,026건 전량 + 필드 채움률/해석률 리포트 |
| Colab OCR 39+2건 | 백로그 | EasyOCR 후 재정규화·재추출 |
| B2-033 유형(한 파일 多실라버스) 탐지 | 백로그 | 파일 단위 탐지 |

## 3. 사용자 질문에 대한 판단 (2026-07-08 답변 요지 — 유지할 입장)

- **역방향 학습(합성→학습)**: 아직 이르다. 트리거 = ①gold 표기 규칙 동결(메모로 규칙이 계속 진화 중), ②배치3 게이트 통과, ③필드별 잠정 승자의 안정. 그 전 합성은 surface aug(이미 있음)까지만.
- **배치 검수 횟수**: 배치3 후 **2~3회 더**(총 150~200문서)면 승자 확정 가능 수준. 단 매 배치 (a)신뢰 게이트 (b)신규 엣지(메모) 발생률로 조기종료/연장 판단. 편집률 낮은 필드(학점·학년도)는 표본 검수로 부담 축소 가능.

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
python3 -m pytest -q                      # 90 tests
python3 scripts/14_method_compare.py      # 배치1 방법비교 (+--no-hybrid)
python3 scripts/16_batch2_eval.py         # 배치2 평가 (ours/hybrid)
python3 scripts/15_kb_coverage.py         # KB 커버리지
python3 scripts/10_extract_record.py --sample 8   # 전체 레코드 파이프라인
# OPENAI 키: gwatop-backend/.env에서 자동 로드 (common/env.py), gpt-4o-mini
```
데이터 위치(전부 git 제외): gold `data/gold/`, 원본 `실라버스 모음 폴더/`, 검수용 원본복사 `b-2/ b-3/`, 비교엑셀 `ParserTest.xlsx`(37건 하네스), Colab 모델 노트북 `notebooks/train_colab.ipynb`.

## 6. 다음 세션 시작 절차

1. 이 문서 + `git log --oneline -20` 훑기.
2. 사용자에게 배치3 검수 완료 여부 확인 → 완료면 §2 표의 게이트 절차.
3. 미완이면 §2의 비차단 작업(수업시간 커버리지 / 전 코퍼스 레코드 리포트) 진행.
