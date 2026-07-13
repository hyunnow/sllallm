"""중복 실라버스 탐지 (HANDOFF §2 백로그).

두 유형:
  파일 간 근사중복 (B3-025≡B3-031): 같은 실라버스가 다른 파일로 — 텍스트
    MinHash 유사도 + 메타 지문(학교|과목명|교수)으로 잡는다. 추출 길이가 달라도
    (905자 vs 2079자) 메타 지문이 같으면 후보.
  파일 내 다중 실라버스 (B2-033): 한 파일에 여러 과목 — `(제목) 강의계획서`류
    헤딩이 여러 번 반복. 서로 다른 제목이 2개 이상이면 분할 대상.

MinHash는 외부 의존성 없이 결정론적으로(고정 계수) 구현 — 재현성 위해 hashlib.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Optional

_K = 48                          # MinHash 시그니처 길이
_PRIME = (1 << 61) - 1
# 고정 계수 (결정론) — blake2b(seed)로 유도
_A = [int.from_bytes(hashlib.blake2b(f"a{i}".encode(), digest_size=7).digest(), "big") | 1
      for i in range(_K)]
_B = [int.from_bytes(hashlib.blake2b(f"b{i}".encode(), digest_size=7).digest(), "big")
      for i in range(_K)]

_WS = re.compile(r"\s+")
# 다중 실라버스 신호는 "<과목명> 강의계획서"가 한 줄로 선 STANDALONE 헤딩 —
# 본문 문장 속 'Syllabus'(This syllabus…/Course information…Syllabus)는 제외하려고
# 줄 시작~끝 앵커 + 마커 뒤 짧은 꼬리(날짜·괄호)만 허용 (B2-033 vs NYU/숭실 오탐).
_SYLLABUS_HEADING = re.compile(
    r"(?m)^\s*([^\n]{2,40}?)\s*(?:강의계획서|수업계획서|강의계획안|Course\s+Syllabus)"
    r"\s*[\(（]?[^)\n]{0,18}[\)）]?\s*$")
# 제목이 아니라 섹션/템플릿 라벨인 헤딩 — 다중 실라버스 오탐의 주범 (단국대 템플릿의
# '차시별 계획(Syllabus'·'장애학생 지원 관련 강의계획서'·학교명 헤더)
_SECTION_STOPWORDS = re.compile(
    r"차시|장애|지원|관련|계획|운영|개요|평가|성적|목표|출석|교재|정보|안내|"
    r"대학교|대학원|university|college|오전|오후|[ap]\.?m\.?|\d{1,2}:\d{2}", re.IGNORECASE)
# kocw 아카이브 파일명: kocw_syllabi__NN_학교__과목__교수__hash
_KOCW_ID = re.compile(r"^kocw_syllabi__\d+_([^_]+(?:_[^_]+)*?)__(.+?)__([^_]+?)__[0-9a-f]+$")


def _shingles(text: str, k: int = 5) -> set[int]:
    """공백 정규화 후 문자 k-그램을 8바이트 해시 정수 집합으로."""
    s = _WS.sub(" ", text or "").strip().lower()
    if len(s) < k:
        return {int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "big")} if s else set()
    out = set()
    for i in range(len(s) - k + 1):
        out.add(int.from_bytes(hashlib.blake2b(s[i:i + k].encode(), digest_size=8).digest(), "big"))
    return out


def doc_signature(text: str) -> Optional[list[int]]:
    """MinHash 시그니처. 텍스트가 너무 짧으면 None (비교 무의미)."""
    sh = _shingles(text)
    if len(sh) < 8:
        return None
    sig = [_PRIME] * _K
    for x in sh:
        for i in range(_K):
            h = (_A[i] * x + _B[i]) % _PRIME
            if h < sig[i]:
                sig[i] = h
    return sig


def estimated_jaccard(sig_a: Optional[list[int]], sig_b: Optional[list[int]]) -> float:
    if not sig_a or not sig_b:
        return 0.0
    return sum(1 for x, y in zip(sig_a, sig_b) if x == y) / _K


def _norm_title(title: str) -> str:
    # macOS 파일명 한글은 NFD(분해형 자모) — 완성형 범위(가-힣) 밖이라 반드시 NFC로
    # 먼저 합성 (school 추론이 겪은 것과 동일; test_b3_010 참조). 언더스코어(파일명의
    # 공백)·구두점 모두 제거 — '일반물리학및연습' == '일반물리학_및_연습'.
    t = unicodedata.normalize("NFC", (title or "")).lower()
    t = re.sub(r"[^가-힣a-z0-9]", "", t)
    return re.sub(r"(i{1,3}|[12])$", "", t)          # 로마numeral/후미 숫자 접미 무시


def filename_key(doc_id: str) -> Optional[str]:
    """kocw 아카이브 파일명에서 학교|과목|교수 키를 뽑는다 — 추출 텍스트가 크게
    달라도(B3-025 905자 vs B3-031 2079자) 같은 강의를 잇는 유일한 확실 신호."""
    m = _KOCW_ID.match(doc_id or "")
    if not m:
        return None
    school, title, instructor = m.group(1), m.group(2), m.group(3)
    nt = _norm_title(title)
    if len(nt) < 2:
        return None
    who = _WS.sub("", unicodedata.normalize("NFC", instructor).lower())
    return f"kocw|{unicodedata.normalize('NFC', school).lower()}|{nt}|{who}"


def metadata_key(school: Optional[str], title: Optional[str],
                 instructor: Optional[str]) -> Optional[str]:
    """학교|정규화 과목명|교수 — 같은 과목의 다른 파일을 잇는 고정밀 키.
    과목명이 없으면(약한 신호) None."""
    if not title:
        return None
    t = _norm_title(title)
    if len(t) < 2:
        return None
    who = _WS.sub("", (instructor or "").lower())
    return f"{(school or '').lower()}|{t}|{who}"


_SCHEDULE_ROWish = re.compile(
    r"^\s*\d"                                        # 앞자리 숫자 = 주차/회차 행
    r"|\d{1,2}\s*[/월]\s*\d{1,2}"                    # 7/21, 3월 5
    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s*\.?\s*\d",
    re.IGNORECASE)


def _looks_like_course_title(title: str) -> bool:
    """실 과목명인가 — 섹션/템플릿 라벨(차시·장애·계획·학교명)·주차행(앞자리 숫자·
    날짜)·너무 짧은 조각을 배제. 다중 실라버스 오탐의 대부분이 주차 계획 행이었다."""
    if not title or _SECTION_STOPWORDS.search(title) or _SCHEDULE_ROWish.search(title):
        return False
    letters = re.findall(r"[가-힣]|[A-Za-z]+", title)
    return len(letters) >= 2 and len(title.strip()) >= 4


def intra_file_syllabus_count(text: str) -> tuple[int, list[str]]:
    """파일 내 서로 다른 실라버스 제목 수와 목록. 2 이상이면 다중 실라버스 의심.
    제목이 실제 과목명처럼 보이는 헤딩만 센다 (섹션 헤딩·학교명 헤더 제외)."""
    seen: list[str] = []
    seen_keys: set[str] = set()
    for m in _SYLLABUS_HEADING.finditer(text or ""):
        title = _WS.sub(" ", m.group(1)).strip(" -–—:·\t()（）")
        if not _looks_like_course_title(title):
            continue
        key = re.sub(r"[^\w가-힣]", "", title.lower())
        if key and key not in seen_keys:
            seen_keys.add(key)
            seen.append(title)
    return len(seen), seen
