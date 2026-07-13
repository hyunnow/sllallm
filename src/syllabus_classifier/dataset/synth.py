"""역방향 학습 (v5 §역방향, 트리거 3조건 충족 후) — 동결된 규칙·표기·cue 렉시콘으로
분류기 학습용 합성 후보를 결정론적으로 생성한다.

원칙:
  - 합성은 TRAIN 보강 전용. val/test는 실데이터만 (누출 금지, §6).
  - 각 합성 후보는 그 라벨을 결정하는 cue(model.infer 렉시콘)를 문맥에 반드시 담는다
    — 모델이 "이 표면형+이 cue → 이 라벨"을 배우도록. 근거 없는 합성은 만들지 않는다.
  - 희소 클래스(exam_time·office_hours·assignment·policy) 위주로 생성해 재균형.
  - 표면 다양성(KO/EN 요일·교시·시각범위·주차)은 동결된 표기 계약에서 나온다.
"""
from __future__ import annotations

import random
import re
from typing import Optional

from ..common.schema import Label, include_in_class_schedule
from ..dataset.build import compose_input

# --- 표면형 풀 (동결된 표기 계약) ---------------------------------------------
_KO_DAYS = ["월", "화", "수", "목", "금"]
_EN_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
_TIMES = ["09:00-09:50", "10:00-11:50", "13:00-14:15", "14:00-15:15", "15:30-16:45",
          "16:00-17:50", "11:00-12:15"]
_PERIODS = ["1,2", "3,4", "5,6", "2,3,4", "7,8", "9,10"]
_WEEKS = list(range(1, 16))
_DATES = ["2026-04-22", "2026-06-10", "2026-10-27", "2026-12-15", "5/14", "10월 27일"]

_EXAM_CUES = ["중간고사", "기말고사", "Midterm Exam", "Final Exam", "퀴즈", "Quiz"]
_ASSIGN_CUES = ["과제 제출", "Homework", "레포트 마감", "Assignment due", "숙제", "제출기한"]
_OFFICE_CUES = ["면담", "상담", "Office Hours", "오피스아워", "연구실 상담"]
_TA_CUES = ["조교 면담", "TA Office Hours", "조교 상담", "Teaching Assistant"]
_WEEKPLAN_CUES = ["주차별 강의계획", "Weekly Plan", "진도", "차시"]
_POLICY = ["출석 20% 미만 시 F", "성적 평가: 중간 40% 기말 40% 과제 20%",
           "지각 3회는 결석 1회", "Attendance policy: 3 absences = fail"]
_CLASS_LABELS = ["강의시간", "Class Time", "수업시간", "요일/시간"]
_UNKNOWN = ["교재: 자료구조 3판", "선수과목 없음", "학점 3", "이메일 주소",
            "강의실 공학관 301", "총 16주", "Prerequisites: none"]


_EN_FULL = {"Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday", "Thu": "Thursday", "Fri": "Friday"}
_START_TIMES = ["09:00", "10:00", "13:00", "14:00", "15:30", "18:00", "18:30", "19:00"]


def _time_expr(rng: random.Random) -> str:
    """수업시간 표면형 — 모델이 놓치던 다양한 형태를 넓게 커버 (recall 목적).
    단일 시작시각(월 18:00)은 강의시간 필드 맥락에서만 정당하므로 _one에서 그 라벨과 함께 쓴다."""
    style = rng.randint(0, 7)
    if style == 0:
        return f"{rng.choice(_KO_DAYS)} {rng.choice(_TIMES)}"
    if style == 1:
        d1, d2 = rng.sample(_EN_DAYS, 2)
        return f"{d1}/{d2} {rng.choice(_TIMES)}"
    if style == 2:
        return f"{rng.choice(_KO_DAYS)}{rng.choice(_PERIODS)}교시"
    if style == 3:
        d = rng.choice(_EN_DAYS)
        return f"{_EN_FULL[d]} {rng.choice(_TIMES)}"
    if style == 4:                                   # 요일 나열 + 시각범위 (월,수 …)
        d1, d2 = rng.sample(_KO_DAYS, 2)
        return f"{d1},{d2} {rng.choice(_TIMES)}"
    if style == 5:                                   # 요일 범위 (월~수)
        i = rng.randint(0, 2)
        return f"{_KO_DAYS[i]}~{_KO_DAYS[i+2]} {rng.choice(_TIMES)}"
    if style == 6:                                   # 단일 시작시각 (강의시간 필드에서만)
        return f"{rng.choice(_KO_DAYS)} {rng.choice(_START_TIMES)}"
    return f"{rng.choice(_EN_DAYS)} {rng.choice(_TIMES)}"


def _row(candidate: str, *, label: Label, date_kind: str,
         section: Optional[str] = None, row_label: Optional[str] = None,
         before: str = "", after: str = "", idx: int = 0) -> dict:
    r = {
        "doc_id": f"synthetic__{label.value}__{idx}",
        "candidate_text": candidate,
        "section_title": section,
        "table_row_label": row_label,
        "table_col_label": None,
        "nearby_text_before": before,
        "nearby_text_after": after,
        "date_kind": date_kind,
        "label": label.value,
        "include_in_class_schedule": include_in_class_schedule(label.value),
        "source": "synthetic",
    }
    r["input_text"] = compose_input(r)
    return r


def _one(label: Label, rng: random.Random, idx: int) -> dict:
    if label == Label.CLASS_SCHEDULE:
        expr = _time_expr(rng)
        # 단일 시작시각은 강의시간 필드 라벨과 함께여야 정당 (validator Rule 4와 일치)
        single_start = bool(re.match(r"[월화수목금] \d{2}:\d{2}$", expr))
        row_label = rng.choice(_CLASS_LABELS) if single_start else rng.choice(_CLASS_LABELS + [None, None])
        return _row(expr, label=label, date_kind="recurring",
                    row_label=row_label or "강의시간", idx=idx)
    if label == Label.EXAM_TIME:
        cue = rng.choice(_EXAM_CUES)
        when = rng.choice(_DATES) if rng.random() < 0.6 else f"{rng.randint(1,15)}주차"
        dk = "absolute" if "-" in when or "월" in when or "/" in when else "relative"
        return _row(when, label=label, date_kind=dk, row_label=cue,
                    before=f"{cue}는 {when}에 실시", idx=idx)
    if label == Label.ASSIGNMENT_DEADLINE:
        cue = rng.choice(_ASSIGN_CUES)
        when = rng.choice(_DATES) if rng.random() < 0.5 else f"{rng.randint(1,15)}주차"
        dk = "absolute" if "-" in when or "월" in when or "/" in when else "relative"
        return _row(when, label=label, date_kind=dk, row_label=cue,
                    before=f"{cue} {when}", idx=idx)
    if label == Label.INSTRUCTOR_OFFICE_HOURS:
        cue = rng.choice(_OFFICE_CUES)
        return _row(_time_expr(rng), label=label, date_kind="recurring",
                    section=cue, row_label=cue, before=f"교수 {cue}", idx=idx)
    if label == Label.TA_OFFICE_HOURS:
        cue = rng.choice(_TA_CUES)
        return _row(_time_expr(rng), label=label, date_kind="recurring",
                    section=cue, row_label=cue, before=cue, idx=idx)
    if label == Label.WEEKLY_PLAN:
        wk = rng.choice(_WEEKS)
        return _row(f"{wk}주차", label=label, date_kind="relative",
                    section=rng.choice(_WEEKPLAN_CUES), row_label=f"Week {wk}",
                    after="자료구조 개요", idx=idx)
    if label == Label.POLICY_TEXT:
        p = rng.choice(_POLICY)
        return _row(p, label=label, date_kind="uncertain",
                    section="평가/성적", row_label="성적평가", idx=idx)
    return _row(rng.choice(_UNKNOWN), label=Label.UNKNOWN, date_kind="uncertain", idx=idx)


# 생성 비중 (2026-07-13 재조정 — v2). 1차 레시피는 대조 클래스(exam/office/policy)를
# class_schedule보다 6배 많이 넣어 모델을 보수화 → recall이 0.490→0.438로 하락했다.
# recall을 올리려면 놓치는 진짜 수업(class_schedule)의 다양한 표면형을 지배적으로 넣고,
# 대조 클래스는 경계 유지에 필요한 만큼만 남긴다. (검증은 다음 Colab 재학습.)
DEFAULT_MIX: dict[Label, int] = {
    Label.CLASS_SCHEDULE: 8,          # 지배적 — 8종 표면형(교시·범위·단일시작·요일범위·영문…)
    Label.EXAM_TIME: 3,
    Label.ASSIGNMENT_DEADLINE: 2,
    Label.INSTRUCTOR_OFFICE_HOURS: 2,
    Label.TA_OFFICE_HOURS: 2,
    Label.POLICY_TEXT: 2,
    Label.WEEKLY_PLAN: 1,
    Label.UNKNOWN: 2,                 # 대조군(시간처럼 생겼지만 수업 아님)
}


def generate(n: int, seed: int = 42, mix: Optional[dict] = None) -> list[dict]:
    """가중 비중에 따라 총 ~n개의 합성 후보를 결정론적으로 생성."""
    rng = random.Random(seed)
    mix = mix or DEFAULT_MIX
    total_w = sum(mix.values())
    rows = []
    idx = 0
    for label, w in mix.items():
        k = max(1, round(n * w / total_w))
        for _ in range(k):
            rows.append(_one(label, rng, idx))
            idx += 1
    rng.shuffle(rows)
    return rows
