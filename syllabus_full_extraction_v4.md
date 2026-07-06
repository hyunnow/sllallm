# 확장 지시서 v4: 실라버스 전체 항목 추출 + 방법 비교 (rule / rule+LLM / LLM)

> 이 문서는 프로젝트의 **범위를 재정의**한다. 앞 문서들(분류기 Phase 프롬프트 + 엣지케이스 v2 + 뒷단 v3)은 "일정/시험 슬라이스"만 다뤘다. 실제 목표는 **실라버스의 거의 모든 항목을 구조화 추출**하는 것이며, 이 문서가 그 전체 그림이다. 기존에 만든 분류기·KB·컴파일러는 버리지 않고 이 큰 추출기의 **시간/시험/과제 서브시스템**으로 편입한다.

---

## 0. 프로젝트 재정의

**하려는 것:** 임의 양식의 실라버스(PDF·이미지·한글, 학교/교수별 자유 양식)에서 **모든 주요 필드를 구조화 JSON으로 추출**한다. 그리고 각 필드에 대해 **rule / rule+LLM / LLM 세 방법을 비교**해 필드별로 최적 방법을 확정한다. (이전 프로젝트의 엑셀이 정확히 이 비교표였다: 필드 × 방법 × 정답플래그.)

**핵심 원칙(계승):** ① 틀리게 넣는 것이 못 넣는 것보다 치명적 → 근거 없으면 needs_review. ② 없는 값을 지어내지 않는다(hallucination 0). ③ 성능은 real holdout으로만 판단. ④ 해석(교시→시각, 주차→날짜)은 모델이 아니라 결정론적 KB.

---

## 1. 최종 목표 스키마 (실제 데이터 기반 전체 필드)

아래는 실제 연세대/고려대/OCW 양식에서 관찰된 필드를 종합한 목표 스키마다. 모든 필드는 값이 없으면 `null`, 불확실하면 `needs_review`.

```json
{
  "meta": {
    "syllabus_id": "SYL-022",
    "source_file": "...pdf",
    "format": "pdf|image|hwp",
    "school": null,              // 학교 (학과와 혼동 금지)
    "campus": null,              // 캠퍼스 (서울/원주 등 — 교시표가 다름)
    "department": null,          // 개설학과/소속
    "academic_year": null,       // 학년도 (★ 인쇄일/출력일과 구분)
    "term": null,                // 학기 (1/2/여름/겨울)
    "course_code": null          // 학수번호
  },
  "course": {
    "title_ko": null, "title_en": null,
    "credits": null,             // 학점
    "classification": null,      // 이수구분(교양/전공 등)
    "target_students": null,     // 수강대상
    "keywords": []               // 교과목 키워드
  },
  "instructors": [               // 여러 명 가능
    { "name_ko": null, "name_en": null, "affiliation": null,
      "office": null, "phone": null, "email": null,
      "office_hours": [],        // 면담시간 (수업시간과 구분! 서브시스템 담당)
      "bio": null }              // 교수정보
  ],
  "tas": [                       // 조교정보, 여러 명 가능
    { "name": null, "office": null, "phone": null, "email": null }
  ],
  "meeting": {
    "location": null,            // 강의실
    "raw_time": null,            // 원문 강의시간 (예: "화5,6,수7(수8)")
    "status": "present",         // present | tba | async | not_specified
    "events": []                 // 서브시스템이 채움: 요일·교시·resolved_time
  },
  "content": {
    "objectives": null,          // 수업목표/학습목표
    "description": null,         // 교과목 소개/개요
    "prerequisites": null,       // 선수과목
    "teaching_method": null,     // 강좌운영방식/수업방법
    "grading": {                 // 성적평가방법 → 구조화
      "raw": null,
      "components": []           // [{name:"중간고사", weight:40}, ...]
    },
    "textbooks": [],             // 교재 [{title, author, publisher, role:"main|ref"}]
    "english_syllabus": null     // 영문 수업계획내용
  },
  "schedule": {
    "weekly_plan": [             // 주별 학습내용
      { "week": null, "date_range": null, "topic": null,
        "textbook_range": null, "remarks": null }
    ],
    "exams": [                   // 서브시스템 + date_kind
      { "type": null, "date_kind": null, "raw_reference": null,
        "resolved_date": null, "weight": null, "needs_review": false }
    ],
    "assignments": [
      { "title": null, "date_kind": null, "raw_reference": null,
        "resolved_date": null, "recurrence": null, "needs_review": false }
    ]
  },
  "admin": {
    "attendance_policy": null,
    "disability_support": null,
    "learning_ethics": null
  }
}
```

---

## 2. 방법 비교의 의미 + 필드별 최적 방법

세 방법을 **모든 필드에 똑같이** 쓰지 마라. 필드 성격에 따라 이기는 방법이 다르다. 목표는 필드별로 "어느 방법을 쓸지"를 데이터로 확정하는 것.

| 필드군 | 성격 | 1순위 방법 | 이유 / 주의 |
|---|---|---|---|
| 학수번호·학점·학년도·학기·이수구분 | 짧은 정형값 | **rule + LLM 검증** | rule은 싸지만 양식 취약. 학년도는 인쇄일과 구분하는 전용 규칙 필요(§3-1) |
| 학교·캠퍼스·학과 | 정형값, 혼동 위험 | **rule + LLM 검증** | 학교 vs 학과 구분 규칙 필수(§3-2) |
| 이메일·전화 | 정규식 대상 | **rule** | regex로 거의 완벽. 난독화(`[at]`) 정규화 |
| 연구실·면담시간 | 반정형 | **rule + 분류기** | 면담시간은 수업시간과 구분(기존 분류기 재사용) |
| 수업목표·소개·선수과목·강좌운영방식·교수정보·영문계획 | 자유 서술 | **LLM** | rule 실패. 해당 섹션만 잘라 좁게 프롬프트 |
| 성적평가방법 | 서술→구조화 | **rule + LLM** | "중간 40%,기말 40%..."를 components 배열로 파싱 |
| 교재/참고문헌 | 반정형 목록 | **LLM** | 저자/출판사/판차 분해 |
| 주별 학습내용 표 | 표 | **rule(표 탐지) + LLM(셀 정리)** | 컬럼 밀림 감지 필수(§3-7) |
| 시험·과제 | 표/서술 + 시간 | **분류기 + KB(서브시스템)** | LLM 단독은 날짜 환각(§3-4). 근거 없는 날짜 금지 |
| 강의시간·강의실 | 교시/정형 | **rule + 분류기 + KB** | 교시→시각은 반드시 (학교,캠퍼스,학기) KB(§3-3) |

---

## 3. 실제 데이터에서 관찰된 실패 유형 (회귀 테스트 시드)

아래는 제공된 엑셀에서 **실제로 발견된** 오류다. 각각을 `tests/`의 회귀 테스트 + 학습/평가 케이스로 반드시 넣어라.

**3-1. 연도 = 인쇄일/출력일 (학년도 아님)**
- SYL-022: 문서 "2015학년도 1학기"인데 메타 연도 2016 — 하단 푸터 "2016.10.6"(출력일)을 잡음.
- 규칙: `N학년도` 패턴을 최우선. 페이지 하단/헤더의 출력·접속 일자(예: `YYYY. M. D. 학사관리`, URL 근처)는 연도 후보에서 제외.

**3-2. 학교 ↔ 학과 혼동**
- SYL-028: `National Statistics`(개설학과)를 학교로 추출. 실제 고려대.
- 규칙: 학교명 사전/패턴(대학교, University)으로 학교를 우선 확정. `개설학과/Department` 라벨 값은 department로만.

**3-3. 교시 → 시각 오해석 + 캠퍼스 의존**
- SYL-022/024/028: 같은 "화5,6" 류를 방법마다 13:00 / 15:00 / 17:00으로 다르게 변환. 원주캠퍼스(SYL-024)는 서울과 교시 시각이 다를 수 있음.
- 대응: 교시→시각은 LLM 추론 금지. `(학교,캠퍼스,학기)` 키의 교시표 KB만 사용. KB 없으면 needs_review.

**3-4. 시험 날짜 환각 (가장 치명적)**
- SYL-032: 문서에 "Week 8/Week 16"만 있는데 한 방법이 중간 `2005-05-01`, 기말 `2005-06-01`로 없는 날짜 생성.
- 규칙: 문서/KB에 근거 없는 확정 날짜 생성 절대 금지. 주차만 있으면 `date_kind=relative` + resolved_date=null.

**3-5. Week N 상대 참조 (시험·과제 대부분)**
- SYL-027 시험 Week1~4, SYL-029 과제 Week2/7/9/15, SYL-030/031/033 시험 Week8/16.
- 대응: 학사일정 KB(학기 시작일+공휴일)로만 날짜화. 없으면 Week N 보존 + needs_review.

**3-6. TBA / 미정 강의시간**
- SYL-027: Class Time `TBA`.
- 규칙: `meeting.status=tba`. 시각 지어내지 말 것.

**3-7. 표 컬럼 밀림 / off-by-one**
- SYL-031: 주차 주제가 파일명 컬럼("Week 2")으로 한 칸 밀려 매핑.
- SYL-022: 주별 계획이 방법에 따라 15주 vs 16주(기말주 누락).
- 대응: 표 헤더로 컬럼 정렬 검증. 주차 번호 연속성 검사. 마지막 주(기말) 누락 감지.

**3-8. 인접 셀 침범 (field bleed)**
- SYL-022: 과목명 `"미분적분학과벡터해석(1) 학점 3"`, 교수명 `"안상욱 담당교수소속 과학기술대학 수학"` — 옆 라벨/값까지 빨림.
- 규칙: 라벨 사전으로 값 경계를 자름. `학점`, `담당교수소속` 등 다음 라벨이 나오면 값 종료.

**3-9. 과제 ↔ 시험 오분류**
- SYL-024: `Homework & Quiz | Week 1`이 한 방법은 assignment, 다른 방법은 exam.
- 대응: 기존 분류기로 판별. 과제/시험 라벨 일관성 검사.

**3-10. async/OCW 강의 (강의시간 없음)**
- SYL-031(KOCW), SYL-032/033(OCW): 강의실·강의시간 없음, 주별 계획만.
- 규칙: `meeting.status=async|not_specified`, 수업 이벤트 0개. 정상 처리로 취급(오류 아님).

---

## 4. 평가 하네스 = 너의 엑셀 재현

이전 엑셀 구조를 코드로 재현하라. 이게 "필드별 최적 방법"을 데이터로 정하는 도구다.

- 각 문서 × 각 필드에 대해 **세 방법(rule / rule+llm / llm)의 출력을 모두 저장**하고, **gold 라벨 컬럼**을 둔다(현재 "라벨대기" 상태).
- gold가 채워지면 방법별 **정답 플래그(TRUE/FALSE)**를 자동 계산.
- 산출물: `필드별 방법 승률 표`. 예: "학점=rule 98%, 수업목표=LLM 94%, 시험날짜=분류기+KB 96% vs LLM 61%(환각)".
- 필드마다 승자 방법을 config로 고정 → 프로덕션은 필드별 승자만 실행.
- **필드별 평가 지표는 성격에 맞게:** 정형값=정확 일치, 자유서술=근사 일치/사람검수, 시간·날짜=위험지표(환각 0, 교시 오해석 0).

`config/field_methods.yaml` 예:
```yaml
credits: rule
academic_year: rule            # 단 인쇄일 배제 규칙 적용
school: rule_llm
objectives: llm
grading: rule_llm
exams: classifier_kb
class_time: rule_classifier_kb
```

---

## 5. 아키텍처 (기존 서브시스템 편입)

```
문서 → 정규화(텍스트/표/라벨)
   → 필드 라우터 (필드별로 방법 선택: rule / rule+llm / llm / 서브시스템)
       ├─ 정형 필드: rule (+LLM 검증)
       ├─ 자유서술: LLM (섹션 한정)
       ├─ 표(주별계획): rule 표탐지 + LLM 셀정리
       └─ 시간/시험/과제: [기존] 후보추출 → 분류기 → validator → KB해석
   → 필드 병합기 (전체 JSON 조립, 필드별 승자 방법 결과 채택)
   → rule validator (교차검증: 학교≠학과, 연도=학년도, 근거없는 날짜 차단)
   → 전체 실라버스 레코드 JSON  (+ 캘린더 컴파일은 v3 뒷단)
```

기존 `src/syllabus_classifier/`의 분류기·resolve·compile는 그대로 두고, 그 위에 필드 라우터/병합기를 얹는다.

---

## 6. 리포지토리 추가 구조

```
config/
├── field_methods.yaml          # 필드별 승자 방법
├── school_dictionary.yaml       # 학교명/캠퍼스 사전 (학과와 구분용)
├── label_dictionary.yaml        # 필드 라벨 사전 (값 경계 자르기용)
src/syllabus_classifier/
├── extract/
│   ├── rule_fields.py          # 정형 필드 rule 추출 + 경계 자르기
│   ├── llm_fields.py           # 자유서술 LLM 추출 (섹션 한정)
│   ├── table_plan.py           # 주별계획 표 추출 + 컬럼밀림 감지
│   └── field_router.py         # 필드별 방법 선택
├── merge/
│   └── record_builder.py       # 전체 레코드 병합 + 교차검증
├── eval/
│   └── method_harness.py       # 필드×방법×정답 하네스 (엑셀 재현)
tests/
└── test_observed_failures.py   # §3의 3-1~3-10 회귀 테스트
```

---

## 7. Phase별 작업

- **Phase 1 — 스키마·하네스 고정:** §1 목표 스키마와 §4 평가 하네스부터. gold 라벨 포맷을 확정하고, 현재 엑셀의 "라벨대기"를 채울 검수 도구를 만든다.
- **Phase 2 — 정형 필드 rule:** 학수번호·학점·학년도·학기·학교·캠퍼스·학과·연락처. §3-1/3-2/3-8 규칙 포함. LLM 검증 붙임.
- **Phase 3 — 자유서술 LLM:** 목표·소개·선수과목·강좌운영방식·교재·교수정보·영문계획. 섹션 한정 프롬프트. 성적평가방법은 components 구조화.
- **Phase 4 — 주별계획 표:** rule 표탐지 + LLM 셀정리. §3-7 컬럼밀림/주차연속성 검사.
- **Phase 5 — 시간/시험/과제:** 기존 서브시스템 연결. §3-3/3-4/3-5/3-6/3-9/3-10 반영.
- **Phase 6 — 병합 + 교차검증:** record_builder로 전체 JSON. rule validator로 학교≠학과·연도=학년도·근거없는 날짜 차단.
- **Phase 7 — 방법 비교 결정:** 하네스로 필드별 승률 산출 → `field_methods.yaml` 확정.
- **Phase 8 — end-to-end 평가:** real holdout으로 문서→전체레코드. §3 관찰 실패가 모두 잡히는지 회귀 테스트.

---

## 8. Phase 0 — 먼저 나에게 질문

1. **엑셀 방법 컬럼 정확히 몇 개인가?** 3개(rule/rule+llm/llm)인가, 아니면 4번째가 gold/최종인가? 컬럼→방법 매핑을 확정해야 하네스를 정확히 재현한다.
2. **gold 라벨:** 현재 "라벨대기"인 정답을 누가 어떻게 채우나? LLM 초안+사람검수 허용?
3. **LLM API:** 자유서술/셀정리에 어떤 LLM을 쓰나? (비용·프라이버시 제약)
4. **학교/캠퍼스/학사일정 수집:** 대상 학교·캠퍼스가 몇 개고, 교시표·학기시작일을 구할 수 있나? (KB 커버리지 = needs_review 비율 결정)
5. **최종 산출물:** 전체 레코드 JSON까지인가, v3의 캘린더(ICS)까지인가?

답을 받은 뒤 리포 구조 추가 → 문서 5~10건으로 §5 파이프라인이 전체 레코드까지 흐르는지 먼저 통과시켜라. 각 Phase 끝마다 요약하고 내 확인을 받아라. 막히면 가정하지 말고 물어라.

---

## 9. 한 줄 요약

**rule은 정형값, LLM은 자유서술, rule+LLM+KB는 표·시간·날짜에 쓰고, 필드별 승자는 하네스로 데이터가 정하게 하라. 그리고 §3의 실제 관찰 실패(인쇄일 연도, 학교=학과, 교시 오해석, 날짜 환각, 컬럼 밀림, 셀 침범)를 회귀 테스트로 못 박아라.**
