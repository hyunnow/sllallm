# 확장 지시서 v2 (마스터): 실라버스 엣지 케이스 전체 처리

> 이 문서는 v1 addendum을 **대체**한다. 앞의 "Syllabus Time-Candidate Classifier" Phase 프롬프트 뒤에 이 문서를 이어 붙여라. 사용자가 실제 실라버스에서 찾은 유형 + Claude가 추가한 유형을 모두 포함한다.

---

## 1. 대원칙: 4가지 처리 메커니즘으로 분리한다

실라버스의 모든 변이는 아래 4가지 **처리 메커니즘** 중 하나 이상으로 해결한다. **모델이 하는 일은 오직 "이게 무슨 종류의 정보인가" 분류뿐이다.** 나머지는 모델이 아니라 스키마/KB/규칙이 담당한다.

| 코드 | 메커니즘 | 담당 | 언제 |
|---|---|---|---|
| **S** | 스키마 | `null` / 배열 구조 | 값이 없음, 값이 여러 개 |
| **M** | 모델 | 종류 분류 | 수업/면담/시험/과제/주차 구분 |
| **KB** | 지식베이스 조회 | 교시표·학사일정 테이블 | 교시→시각, 주차/일차/N강→날짜 |
| **R** | 규칙 + needs_review | 결정론적 규칙, 사용자 확인 | 애매/미확정/KB에 없음 |

**절대 규칙: 외부 지식이 필요한 변환(교시 시각, 주차→날짜)을 모델에 학습시키지 마라. KB로 처리한다.**

---

## 2. 두 개의 지식베이스(KB) — 이 프로젝트의 숨은 핵심

### 2-1. 교시 시간표 KB (`config/period_timetables.yaml`)

- **키: (학교, 학기종류).** 여름/겨울 계절학기는 교시 시각이 다르므로 반드시 학기종류로 구분한다.
```yaml
timetables:
  university_a__regular:
    period_length_min: 50
    periods: { "1": ["09:00","09:50"], "2": ["10:00","10:50"], "3": ["11:00","11:50"] }
  university_a__summer:          # 같은 학교라도 계절학기는 다름
    periods: { "1": ["09:00","10:40"], "2": ["10:50","12:30"] }
  university_b__regular:
    periods: { "2": ["10:30","11:45"] }   # 75분 교시, 시작 시각도 다름
```

### 2-2. 학사일정 KB (`config/academic_calendars.yaml`) ← 유형 4·5 해결의 핵심

"week 3 / 수업 5일차 / 1강 / N월"을 **실제 날짜로 바꾸려면 학기 시작일과 공휴일이 필요**하다. 이건 실라버스 안에 거의 없는 외부 지식이다.
```yaml
calendars:
  university_a__2026_fall:
    term_start: "2026-09-01"      # 1주차 시작
    term_end:   "2026-12-18"
    weeks: 16
    holidays: ["2026-09-24","2026-09-25","2026-10-03","2026-10-09"]  # 휴강/공휴일
    makeup_days: {"2026-10-03": "2026-12-19"}   # 보강일(선택)
```

**변환 로직 (resolver):**
- 주차(week N) → 날짜: `term_start + (N-1)주`, 단 그 주에 공휴일이 끼면 반영. 주 2회 수업이면 요일별로 각각.
- 수업 N일차 → 날짜: 수업 요일 시퀀스에서 N번째 실제 수업일.
- N강 → 대개 N일차 또는 N주차와 동일 취급(수업 회차). 문서 맥락으로 판단.
- N월(3월/4월) → 월 단위 tentative. 정확한 날짜 생성 금지, 해당 월 범위로만.
- **학기 시작일을 KB에서 못 찾으면** → 주차/일차만 남기고 `resolved_date: null`, `needs_review: true`. 절대 임의 날짜 생성 금지.

---

## 3. 전체 엣지 케이스 카탈로그

사용자가 찾은 유형(U1~U6) + Claude 추가(C1~C11). 각 항목은 처리 메커니즘과 기대 동작을 명시한다. 이 표 전체를 `data/edge_cases/registry.jsonl` 초기 시드로 넣어라.

### 사용자가 찾은 유형

| ID | 유형 | 예시 | 메커니즘 | 기대 동작 |
|---|---|---|---|---|
| U1 | 값 없음 | 교수 이름/연락처/수업시간 없음 | S | 해당 필드 `null` 또는 `status:not_specified`, hallucination 금지 |
| U2 | 값 여러 개 | 교수 여러 명, 강의시간이 기간마다 다름/변경 | S | 배열로. 시간 변경은 기간별 events로 분리 (아래 C1과 연결) |
| U3 | 문서만으로 해석 불가 | 학교별 교시 시각 다름 + 여름/겨울 다름 | KB | 교시표 KB (학교,학기) 키로 변환 |
| U4 | 일정 표기 다양 | `2026.10.27~11.10` / week 3 / 5일차 / 27or29일(불확실) / 3월,4월 / 1강,2강 | KB+R | absolute는 그대로, relative는 학사일정 KB, uncertain은 needs_review (§4) |
| U5 | 주차 미정 | 진도만 있고 몇 주차인지 없음 | S+R | weekly_plan에 순서만, 날짜/주차 생성 금지, `week:null` |
| U6 | 온라인/사이버 강의 | 비대면 사이버 강의 | S | `class_schedule.status:async`, events 비움 |

### Claude 추가 유형

| ID | 유형 | 예시 | 메커니즘 | 기대 동작 |
|---|---|---|---|---|
| C1 | 학기 중 시간 변경 | 전반부 월1교시 / 후반부 수3교시 | S | events에 `valid_from`/`valid_until` 넣어 기간별 분리 |
| C2 | 공휴일·휴강·보강 | 추석 휴강, 개천절 휴강, 보강일 | KB+R | 반복 수업에서 해당 날짜 **제외(EXDATE)**, 보강일 별도 추가 |
| C3 | 이론/실습 분리 | 이론 월1-2교시 + 실습 수3-4교시 | S | 한 과목에 events 2개(요일·시간·장소 각각), `component:theory/lab` |
| C4 | 한 문서에 여러 분반 | 분반A 월1교시 / 분반B 화2교시 | S+R | `sections[]`로 분리, 어느 분반인지 불명이면 needs_review |
| C5 | 팀티칭/주차별 교수 변경 | 1~5주 A교수, 6~10주 B교수 | S | instructors 배열 + weekly_plan에 담당교수 연결 |
| C6 | 연락처 형식·난독화 | `hong[at]univ.ac.kr`, 전화만, 카톡ID, LMS 메시지, 이미지 이메일 | M+R | 이메일/전화/기타 채널 분리, 난독화 정규화(`[at]→@`), 이미지화면 needs_review |
| C7 | 시험시간 ≠ 수업시간 | 별도 고사시간, 공통고사기간, 온/오프라인 시험 | M+R | 시험 시각을 class_schedule로 가져오지 않기, 공통고사는 학사일정 참조 |
| C8 | 반복 마감 | 매주 금요일 23:59 과제 | S | assignment에 recurrence, 단일 이벤트로 오해 금지 |
| C9 | 격주/홀짝주 수업 | 격주 실습, 홀수주만 | S+R | recurrence `interval:2` 또는 needs_review |
| C10 | 집중/블록 강의 | 계절학기 하루 여러 시간, 특정 주 몰아서 | S | 여러 시간 슬롯을 하루에, tentative 아님 주의 |
| C11 | 표기·언어 정규화 | 날짜(2026.10.27 / 10월27일 / 27th Oct), 요일(월/월요일/Mon), 시각(오후2시/14:00/2PM), 범위(~/-/부터) | 규칙 | 정규화 레이어에서 통일 (§5) |

---

## 4. 유형 4·5 상세: 날짜 표기를 4종으로 먼저 분류한다

모든 날짜/일정 표현을 아래 4종으로 먼저 나눈 뒤 처리한다. 이걸 안 나누면 week3와 10월27일을 같은 파이프라인에 넣어 오류가 난다.

| 종류 | 예시 | 처리 |
|---|---|---|
| **absolute** (확정 날짜) | `2026.10.27`, `10월 27일~11월 10일` | 그대로 파싱, 캘린더 확정 이벤트 가능 |
| **relative** (기준점 필요) | `week 3`, `5일차`, `1강`, `3월` | 학사일정 KB로 변환. KB 없으면 needs_review |
| **uncertain** (불확실) | `27일 또는 29일`, `추후 공지`, `10월 말` | 확정 이벤트 금지, `tentative`+needs_review, 후보 날짜 보존 |
| **recurring** (반복) | `매주 금요일`, `격주` | recurrence 규칙으로, 단일 이벤트로 오해 금지 |

출력 스키마 예:
```json
{
  "date_expression": "week 3",
  "date_kind": "relative",
  "raw_reference": { "type": "week", "value": 3 },
  "resolved_date": null,          // 학사일정 KB로 채움. 못 채우면 null
  "resolved_by": null,            // in_document / academic_calendar_kb / null
  "needs_review": true
}
```

---

## 5. 정규화 레이어 (C11) — 추출 전에 통일

후보 추출 전에 표기를 정규화하는 결정론적 레이어를 둔다. **모델이 표기 다양성까지 학습하게 하지 마라. 규칙으로 줄여라.**
- 요일: `월/월요일/월욜/Mon/Monday` → `Monday`
- 시각: `오후 2시 / 14:00 / 2:00 PM / 14시` → `14:00` (24h)
- 날짜: `2026.10.27 / 2026-10-27 / 10월 27일 / 27th Oct 2026` → `2026-10-27`
- 범위: `~ / - / 부터...까지 / to` → 통일된 start/end
- 정규화 규칙은 config로 관리하고, 정규화 실패 원문은 `raw_text`로 항상 보존한다(디버깅용).

---

## 6. 통합 스키마 (최종본)

```json
{
  "course": { "title": null, "code": null, "term": "2026_fall" },
  "sections": [                          // C4: 분반. 단일이면 1개
    {
      "section_id": "A",
      "class_schedule": {
        "status": "present",             // present/not_specified/tentative/async  (U1,U6)
        "events": [
          {
            "component": "theory",       // theory/lab/practice          (C3)
            "day": "Monday",
            "time_type": "period",       // clock/period/async
            "period_numbers": [1,2],
            "resolved_time": { "start_time":"09:00","end_time":"10:50","resolved_by":"period_timetable_kb" },
            "recurrence": { "freq":"weekly","interval":1,"exdates":["2026-09-24"] },  // C2,C9
            "valid_from": null, "valid_until": null,   // C1: 학기 중 변경 시
            "needs_review": false
          }
        ]
      }
    }
  ],
  "instructors": [                       // U2,C5: 여러 명
    { "name":"홍길동","role":"professor","email":"hong@univ.ac.kr","phone":null,
      "contact_channels":[{"type":"kakao","value":"..."}],   // C6
      "office":"U502","office_hours":[{"day":"Monday","start_time":"22:00","end_time":"23:00"}] }
  ],
  "exams": [                             // C7
    { "type":"midterm","date_kind":"relative","raw_reference":{"type":"week","value":8},
      "resolved_date":null,"time_online":false,"needs_review":true } ],
  "assignments": [                       // C8
    { "title":"주간과제","date_kind":"recurring","recurrence":{"freq":"weekly","day":"Friday","time":"23:59"} } ],
  "weekly_plan": [                       // U5: 주차 미정이면 week:null
    { "order":1,"week":null,"topic":"...","instructor":"홍길동" } ]
}
```

---

## 7. needs_review 정책 (안전망)

아래는 **찍지 말고 사용자 확인으로 넘긴다** (`needs_review:true` + `review_reason`):
- 교시인데 교시표 KB에 없음
- 주차/일차/N강인데 학사일정 KB에 학기 시작일 없음
- 날짜가 uncertain (27일 or 29일, 추후공지, 월말)
- 분반이 여러 개인데 어느 분반인지 불명 (C4)
- 격주/홀짝 판단 불가 (C9)
- 연락처가 이미지화되어 추출 불가 (C6)
- 모델 confidence 임계값 미만

**원칙: "못 채우는 것"보다 "틀리게 채우는 것"이 훨씬 치명적. 확신 없으면 비우고 needs_review.**

---

## 8. 레지스트리 · 학습 · 평가에 반영

### 레지스트리
- §3 표 전체를 `registry.jsonl` 시드로 넣고, 새로 발견하는 케이스마다 추가한다.
- 각 항목은 (1) 회귀 테스트, (2) 노이즈 합성 규칙, (3) 유형별 평가 항목으로 동시에 쓰인다.

### 학습 데이터 생성 시 반드시 포함할 분포
- U1(없음) 케이스를 충분히 (모델이 "없음"을 정답으로 배우게)
- U3·U4(교시·주차)를 KB 있는 버전 / KB 없는 버전 둘 다
- U6(async), C3(이론/실습 분리), C4(분반)를 골고루

### 평가 (유형별 분리 측정)
- **모델 성능과 KB resolver 성능을 분리 측정.** "교시임을 맞혔는가"(모델) vs "시각 변환이 맞았는가"(KB)를 따로 본다. 주차→날짜도 동일.
- 유형별(U1~C11) real holdout 정확도를 각각 리포트. 전체 평균에 묻지 마라.
- 핵심 위험 지표: 없는 값 생성률(0 목표), 면담→수업 오분류(0 목표), 불확실 일정을 확정으로 만든 비율(0 목표), 주차/교시 임의 변환 비율(0 목표).

---

## 9. Claude Code에게: 이 문서 반영 순서

1. 앞 Phase 프롬프트의 스키마를 §6 통합 스키마로 교체.
2. Phase 0 질문에 추가: **가진 실라버스가 몇 개 학교/몇 개 학기에서 왔는지, 교시표·학사일정을 수집 가능한지.** (KB 커버리지가 needs_review 비율을 좌우함)
3. `config/period_timetables.yaml`, `config/academic_calendars.yaml` 스켈레톤 생성.
4. §3 카탈로그를 registry 시드로.
5. §5 정규화 레이어를 후보 추출 앞단에 배치.
6. §4 date_kind 4종 분류를 후보 분류기 출력에 포함.
7. 평가는 §8대로 모델/KB 분리 + 유형별.
