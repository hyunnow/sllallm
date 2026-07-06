# Claude Code 작업 지시서: 실라버스 시간 후보 분류기 (Syllabus Time-Candidate Classifier)

> 이 문서 전체를 Claude Code에게 전달하세요. Claude Code는 이 문서를 프로젝트 명세이자 작업 지시서로 사용합니다.

---

## 0. 너(Claude Code)에게: 작업 방식

너는 지금부터 실라버스(강의계획서) 파싱을 위한 **작은 특화 모델**을 만드는 프로젝트를 진행한다. 다음 원칙을 지켜라.

1. **단계별로 진행한다.** 아래 Phase 0 → Phase 9 순서로 간다. 각 Phase가 끝나면 결과물과 다음 단계 계획을 요약하고 멈춰서 내 확인을 받아라. 한 번에 전부 만들지 마라.
2. **Phase 0에서 먼저 나에게 질문한다.** 아래 "Phase 0"에 있는 질문들에 내가 답하기 전에는 데이터 파이프라인을 짜지 마라. 환경(GPU 유무), 데이터 위치/포맷을 모른 채 가정하고 진행하지 마라.
3. **가정은 명시한다.** 확실하지 않으면 코드에 `# ASSUMPTION:` 주석을 달고, Phase 요약에 "내가 이렇게 가정했다"를 적어라.
4. **작은 것부터 돌아가게 만든다.** 처음부터 완벽한 모델을 만들지 말고, 데이터 10개로 파이프라인이 끝까지 돌아가는지 먼저 확인한 뒤 규모를 키워라.
5. **모든 것을 재현 가능하게.** 랜덤 시드 고정, config 파일 사용(YAML), 실행 스크립트에 인자 명시.

---

## 1. 프로젝트 목표 (정확히 무엇을 만드는가)

**만드는 것:** 실라버스 안의 "날짜/시간 후보" 하나하나를 분류하는 **작은 분류 모델**.

**만들지 않는 것:** PDF 전체를 넣으면 완성된 JSON이 나오는 전체 파서 LLM. (이건 나중 단계이고 지금 목표가 아니다.)

**왜 이 모델이 먼저인가:** 현재 실제로 겪는 오류는 LLM이 시간을 못 읽어서가 아니라, 읽은 시간을 **잘못 분류**하기 때문이다. 대표 오류:

- 실라버스에 "연구실 및 면담시간 / Office Location&Hours: 월요일 22:00~23:00"이 있는데, 이걸 **정규 수업시간**으로 캘린더에 넣어버림.
- 이건 교수 면담시간(office hours)이지 수업시간이 아니다.

이 모델의 단 하나의 임무: **class_schedule(수업시간)에 넣으면 안 되는 시간을 걸러낸다.**

**핵심 원칙: 이 제품에서는 "일정을 못 찾는 것"보다 "틀린 일정을 넣는 것"이 훨씬 치명적이다.** 따라서 recall보다 **class_schedule의 precision**이 최우선이다.

---

## 2. 데이터 현실 (반드시 인지할 것)

- 내가 가진 건 **실제 실라버스 약 1,000개**이고, **각각 양식이 다르다** (학교/교수/학과별 자유 양식, PDF/이미지/한글파일 등).
- 1,000개는 딥러닝 기준으로 **적은 편**이다. 그래서 두 가지가 필수다:
  1. **노이즈 증강(augmentation)**으로 학습 데이터를 늘린다.
  2. **실제 데이터 holdout**을 반드시 따로 떼어 둔다. 성능은 합성/증강 데이터가 아니라 **실제 holdout**으로 판단한다.
- 다행히 이 모델은 **문서 단위가 아니라 "시간 후보 단위"로 학습**한다. 실라버스 1개당 시간/날짜 후보가 10~50개면, 1,000개 → **후보 1만~5만 개**의 학습 샘플이 된다. 이 관점 전환이 이 프로젝트의 핵심이다.

---

## 3. 전체 아키텍처 (이 모델이 시스템에서 차지하는 위치)

```
문서(PDF/이미지/HWP) 
  → 텍스트/표/레이아웃 추출
  → 날짜·시간 후보 전부 추출 (규칙 기반)
  → [★ 우리가 만드는 모델 ★] 후보 분류기
  → rule validator (규칙 기반 최종 검증)
  → class_schedule 후보만 통과
  → 캘린더 이벤트 생성
```

우리는 이 중 **"후보 분류기"**를 만든다. 그리고 그것을 뒷받침할 **후보 추출기**와 **rule validator**도 같이 만든다. 나머지(캘린더 생성 등)는 이번 범위가 아니다.

---

## 4. 분류 스키마 (모델의 입력/출력)

### 입력 (한 개의 시간 후보에 대해)
```json
{
  "candidate_text": "월요일 22:00~23:00",
  "nearby_text_before": "연구실 및 면담시간 Office Location&Hours",
  "nearby_text_after": "WebEx를 이용해 비대면으로 시행",
  "section_title": "연구실 및 면담시간 / Office Location&Hours",
  "table_row_label": "연구실 및 면담시간",
  "table_col_label": null,
  "page": 1
}
```

### 출력
```json
{
  "classified_as": "instructor_office_hours",
  "include_in_class_schedule": false,
  "confidence": 0.98
}
```

### 분류 클래스 (label set)
- `class_schedule` — 정규 수업시간 (이것만 캘린더 반복수업이 됨)
- `instructor_office_hours` — 교수 면담/상담시간
- `ta_office_hours` — 조교 면담시간
- `exam_time` — 시험 시간
- `assignment_deadline` — 과제 마감
- `weekly_plan` — 주차별 강의계획 안의 시간/주차
- `policy_text` — 정책 설명문 속 시간
- `unknown` — 판단 불가

핵심 파생 필드: **`include_in_class_schedule`** (boolean). `class_schedule`일 때만 true, 나머지는 false. 이게 실제로 오류를 막는 값이다.

---

## 5. 리포지토리 구조 (Phase 0에서 생성)

```
syllabus-classifier/
├── README.md
├── config/
│   ├── data.yaml            # 데이터 경로, split 비율
│   ├── noise.yaml           # 노이즈 종류별 확률
│   └── train.yaml           # 모델/학습 하이퍼파라미터
├── data/
│   ├── raw/                 # 원본 실라버스 1000개 (읽기 전용 취급)
│   ├── normalized/          # 텍스트/표 추출 결과
│   ├── canonical/           # 문서별 정답 JSON (라벨)
│   ├── candidates/          # 후보 단위 데이터셋 (분류 학습용)
│   ├── augmented/           # 노이즈 증강 데이터
│   └── splits/              # train/val/test (누수 방지 split)
├── src/
│   ├── extract/             # 문서→텍스트/표, 시간후보 추출
│   ├── label/               # LLM 보조 라벨링 + 사람 검수 도구
│   ├── noise/               # 노이즈 증강기
│   ├── dataset/             # 후보 데이터셋 빌드, split
│   ├── model/               # 모델 정의, 학습, 추론
│   ├── validator/           # rule 기반 검증 layer
│   └── eval/                # 평가 지표
├── scripts/                 # 각 단계 실행 엔트리포인트
└── tests/                   # 회귀 테스트 (아래 Phase 8 참고)
```

---

## 6. Phase별 작업 지시

### Phase 0 — 환경 파악 + 리포 셋업 (먼저 나에게 질문)

진행 전에 나에게 아래를 물어봐라. 답을 받기 전에 데이터 파이프라인 코드를 짜지 마라.

1. **GPU 환경:** 학습에 쓸 GPU가 있는가? (있다면 VRAM 크기) 없으면 CPU/Colab/클라우드 중 무엇인가?
2. **데이터 포맷:** 1,000개 실라버스는 어떤 형식인가? (PDF 텍스트형 / PDF 스캔이미지형 / 한글(HWP/HWPX) / 이미지 / 혼합) 각각 대략 몇 %인가?
3. **데이터 언어:** 한국어 전용인가, 한/영 혼합인가?
4. **데이터 위치:** 파일들이 어디 있는가? (경로 알려주면 됨)
5. **기존 라벨 유무:** 정답(어떤 시간이 수업/면담/시험인지)이 라벨링된 게 있는가, 아니면 원본만 있는가?
6. **LLM 접근:** 라벨링 보조에 쓸 수 있는 LLM API 키가 있는가? (있으면 초기 라벨링을 크게 가속할 수 있음)

그 다음:
- 위 리포 구조를 만들고, `pyproject.toml` 또는 `requirements.txt`로 의존성을 고정한다.
- 랜덤 시드 유틸, config 로더를 만든다.
- **데이터 10개 정도로 파이프라인 스켈레톤이 끝까지 도는지** 먼저 검증할 계획을 세운다.

### Phase 1 — 문서 정규화 (텍스트/표 추출)

- `raw/`의 각 문서를 **텍스트 + 표 구조 + 페이지 + 섹션 제목**으로 추출해 `normalized/`에 저장한다.
- 표는 반드시 **row label / col label**을 보존하도록 추출한다. (면담시간이 표의 어느 행에 있는지가 분류의 핵심 단서다.)
- 포맷별 처리: 텍스트 PDF(pdfplumber 등), 스캔 PDF/이미지(OCR — 어떤 OCR 쓸지 나와 상의), 한글파일(변환 방법 상의).
- 추출 실패/저품질 문서는 별도 리스트로 로깅한다. (버리지 말고 기록.)

### Phase 2 — canonical JSON 라벨링 (정답 만들기)

목표: 각 실라버스마다 "어떤 시간이 수업/면담/시험/과제인지" 정답 JSON을 만든다.

- **LLM 보조 + 사람 검수** 방식을 쓴다. (LLM API가 있으면) LLM으로 초안 라벨을 뽑고, 사람이 검수/수정하기 쉬운 형태로 출력한다.
- 사람이 빠르게 검수할 수 있는 **간단한 검수 도구/포맷**을 만들어라. (예: 후보별로 예측 라벨과 근거 문장을 나란히 보여주고, 틀린 것만 고치게)
- **이번 대표 오류 케이스는 반드시 정답 예시로 포함:** "월요일 22:00~23:00 (연구실 및 면담시간)" → `instructor_office_hours`, `include_in_class_schedule=false`, `class_schedule.status="not_specified"`.
- 주의: 라벨은 완벽할 필요 없지만, **class_schedule / office_hours 구분만큼은 정확**해야 한다. 이게 오라벨이면 모델이 오류를 학습한다.

### Phase 3 — 시간/날짜 후보 추출기 (규칙 기반)

- `normalized/` 문서에서 **모든 날짜·시간 후보**를 규칙(정규식 등)으로 뽑는다. 모델이 아니라 규칙으로. 목표는 **recall 최대화** (놓치지 않기).
- 다양한 표현을 커버해야 한다:
  - `월요일 22:00~23:00`, `월 22:00-23:00`, `Monday 22:00-23:00`, `Mon 10-11`
  - `오후 10시`, `10:00 PM`, `22시~23시`
  - `월 7,8교시`, `3교시`
  - `23:59`(마감), `50분간 진행`(duration)
  - `8주차`, `중간고사 8주차`, `추후 공지`
- 각 후보마다 Phase 4 입력 스키마에 맞는 문맥(before/after, section, row/col label)을 같이 뽑아 저장한다.

### Phase 4 — 후보 분류 데이터셋 구축

- Phase 2의 canonical 라벨과 Phase 3의 후보를 **매칭**해서, "후보 + 문맥 → 정답 클래스" 형태의 데이터셋을 `candidates/`에 만든다.
- 이게 실제 학습 데이터다. 문서 1,000개 → 후보 수만 개가 나와야 정상이다.
- **클래스 분포를 반드시 리포트**해라. class_schedule / office_hours 비율, unknown 비율 등. 심하게 불균형이면 나에게 알려라.

### Phase 5 — 노이즈 증강 (이게 데이터를 늘리는 핵심)

두 갈래로 데이터를 늘린다.

**(A) 실제 후보에 텍스트 노이즈 부여 (surface augmentation)**
Phase 4의 실제 후보 각각에 대해, 의미(라벨)는 그대로 두고 표면 텍스트만 변형해 여러 버전을 만든다:
- OCR 오류 시뮬레이션: `0↔O`, `l↔1`, 한글 자모 혼동, 무작위 글자 삭제/삽입
- 공백/표 깨짐: 표를 flatten, 열 병합, 줄바꿈 삽입
- 라벨 표현 치환: `면담시간 ↔ 상담시간 ↔ Office Hours ↔ 오피스아워`
- 시간 포맷 치환: `22:00~23:00 ↔ 22:00-23:00 ↔ 오후 10시~11시 ↔ 22시~23시`
- 한/영 혼합, 문맥 문장 순서 셔플
- 확률은 `config/noise.yaml`로 조절 가능하게.

**(B) 역방향 합성 (canonical → 문서 → 노이즈 → 복원)**
- canonical JSON에서 **가짜 실라버스 문서를 생성**하고, 거기에 노이즈를 입힌 뒤, 그 문서에서 다시 후보를 뽑아 학습 데이터로 쓴다. 이렇게 하면 라벨은 자동으로 안다(정답 JSON에서 만들었으므로).
- 특히 **hard negative(헷갈리는 오답)를 의도적으로 많이** 만든다. 아래 케이스들을 반드시 다량 생성:

| 케이스 | 학습 목적 |
|---|---|
| 강의시간 칸 비어있음 + 면담시간만 있음 | office hour를 수업시간으로 넣지 않기 |
| 수업시간 있음 + 면담시간도 있음 | 둘을 정확히 분리 |
| 비동기 온라인 강의 | class_schedule 비우기 |
| "50분간 진행" | duration을 start/end로 오해하지 않기 |
| "중간고사 8주차" | 주차만, 임의 날짜 생성 금지 |
| "추후 공지" | tentative 처리 |
| "과제 제출 23:59" | assignment_deadline 분류 |
| "월 7,8교시" | 교시 표현 |
| T/A Office Hours / WebEx office hour | 조교 면담 분리 |

- **대표 오류 케이스는 최소 수십~수백 개 변형으로 복제:**
  `연구실 및 면담시간: 월요일 22:00~23:00` / `Office Location&Hours: Monday 22:00-23:00` / `상담시간: 월 22:00~23:00` / `T/A Office Hours: 월요일 22:00~23:00` → 전부 정답 `include_in_class_schedule=false`.

### Phase 6 — 데이터 분할 (누수 방지가 생명)

- **절대 규칙:** 같은 원본 실라버스(또는 같은 canonical JSON)에서 파생된 후보/증강본은 **전부 같은 split에만** 들어가야 한다. train과 test에 나뉘어 들어가면 성능이 과대평가된다. → **문서 ID 기준 group split**을 써라.
- 분할 권장:
  - Train: 실제 문서의 ~70% + 그 문서들의 증강/합성 데이터
  - Validation: 실제 문서의 ~15% (증강 최소화)
  - **Real holdout test: 실제 문서의 ~15%, 증강 전혀 없음, 학습에 한 번도 안 쓴 문서.** 성능 판단은 이걸로만.
- 합성(순수 가짜) 데이터로만 이루어진 **synthetic stress test**도 별도로 둔다. (일반화 vs 합성 성능을 구분해서 보기 위해.)

### Phase 7 — 모델 학습

- **1순위 추천 아키텍처: 인코더 기반 분류기.** 한/영 혼합이므로 다국어 인코더 후보를 우선 검토:
  - `klue/roberta-base`, `klue/bert-base` (한국어 강함)
  - `xlm-roberta-base` (한/영 혼합에 강함)
  - 리소스 작으면 `sentence-transformer + 경량 classifier`도 가능
- 입력 구성: `candidate_text [SEP] section_title / row_label [SEP] nearby_text`. 출력: 8-클래스 분류 + `include_in_class_schedule`.
- **불균형 처리:** class_schedule의 false positive가 치명적이므로 class weight 또는 focal loss를 쓰고, **class_schedule 예측에는 높은 confidence threshold**를 걸어 보수적으로 만든다. (애매하면 class_schedule로 안 넣는 방향.)
- LoRA 옵션: 소형 LLM LoRA로도 이 분류를 할 수 있지만, **후보 분류 태스크는 인코더가 더 가볍고 빠르고 정확**할 가능성이 높다. LoRA는 나중 "전체 JSON extractor" 단계에서 검토. 지금은 인코더로 시작하되, 원하면 소형 LLM LoRA 버전도 비교 실험으로 만들어라.
- config로 하이퍼파라미터 관리, 학습 로그와 체크포인트 저장.

### Phase 8 — 평가 (일반 accuracy 금지)

일반 정확도만 보지 마라. 이 제품의 위험 구조에 맞춘 지표를 만들어라.

| 지표 | 목표 |
|---|---|
| **class_schedule precision** | 매우 높게 (98~99%+ 목표) |
| **office_hours → class_schedule 오분류율** | 거의 0 |
| class_schedule false positive rate | 최대한 낮게 |
| exam 확정날짜 hallucination | 0에 가깝게 |
| tentative(추후공지/주차) 검출 recall | 높게 |
| 클래스별 F1, confusion matrix | 전부 리포트 |

- **혼동행렬(confusion matrix)을 반드시 출력**하고, 특히 `office_hours ↔ class_schedule` 칸을 강조해서 보여줘라.
- **회귀 테스트(tests/):** 아래 같은 단정문을 자동 테스트로 만들어라. 프롬프트/모델을 고쳤을 때 좋아졌는지 나빠졌는지 판단하는 기준이 된다.
  - `"연구실 및 면담시간: 월요일 22:00~23:00"` → class_schedule에 포함 안 됨 (instructor_office_hours)
  - `"50분간 진행"` → start/end time으로 쓰이지 않음
  - `"중간고사 8주차"` → 확정 날짜 생성 안 함 (tentative)
  - `"T/A Office Hours: 수요일 15:00~16:00"` → class_schedule 아님
  - 강의시간 칸이 비어있을 때 다른 행 시간으로 채우지 않음
- 성능은 **real holdout 기준**으로 보고하고, synthetic test 성능과 나란히 비교해서 "합성 착시"가 없는지 확인해라.

### Phase 9 — rule validator (모델 뒤의 안전망)

모델이 실수해도 규칙이 막게 한다. 아래를 규칙으로 강제:
- 주변에 `면담 / Office Hours / 상담 / WebEx / appointment`가 있으면 class_schedule 금지.
- 강의시간 필드가 비어있으면 다른 섹션 시간으로 채우기 금지.
- 시험이 "N주차"로만 있으면 확정 날짜 생성 금지 → tentative.
- "50분" 등 duration은 start/end time으로 변환 금지.
- 최종 출력에 `rejected_time_candidates`(왜 class_schedule에서 걸러졌는지)를 포함시켜라. (모델이 "무엇을 안 넣는지"도 남겨야 디버깅이 된다.)

최종 출력 예시:
```json
{
  "class_schedule": { "status": "not_specified", "events": [],
    "reason": "No explicit class meeting time found." },
  "time_candidates": [
    { "text": "월요일 22:00~23:00", "classified_as": "instructor_office_hours",
      "include_in_class_schedule": false,
      "evidence_label": "연구실 및 면담시간 / Office Location&Hours",
      "confidence": 0.98 }
  ],
  "rejected_time_candidates": [
    { "text": "월요일 22:00~23:00", "rejected_from": "class_schedule",
      "reason": "Office hour context." }
  ]
}
```

---

## 7. 지켜야 할 원칙 (매 Phase마다 self-check)

1. **성능은 real holdout으로만 판단한다.** 합성/증강 데이터 성능에 속지 마라.
2. **누수 금지.** 같은 원본에서 나온 데이터가 train/test에 섞이면 즉시 알려라.
3. **precision > recall.** 못 뽑는 건 사용자가 고치면 되지만, 틀린 걸 넣으면 신뢰가 무너진다.
4. **class_schedule은 근거(positive evidence)가 있을 때만 넣는다.** 애매하면 넣지 않는다.
5. **작게 시작해서 키운다.** 10개로 파이프라인 검증 → 전체로 확장.
6. 막히거나 데이터가 예상과 다르면 **가정하고 진행하지 말고 나에게 물어라.**

---

## 8. 지금 당장 할 일

Phase 0을 시작해라. 먼저 위 "Phase 0"의 질문들을 나에게 하고, 내 답을 받은 뒤 리포 구조를 만들어라. 데이터 파이프라인 코드는 내가 환경/데이터 질문에 답한 다음에 작성한다.
