"""OCR 백로그 판정 (HANDOFF §2 ④).

정규화가 텍스트 레이어를 뽑아도 그 내용이 URL·페이지 머리글 같은 chrome뿐이면
실질 스캔본이다 (B6-001: 한양대 LMS 인쇄 PDF, 495자 전부 'Page 1 of 4' +
portal.hanyang.ac.kr URL + 날짜 스탬프). 이런 문서는 텍스트가 있어도 needs_ocr.
"""
from __future__ import annotations

import re

_CHROME = [
    re.compile(r"https?://\S+"),                         # URL
    re.compile(r"\bPage\s+\d+\s+of\s+\d+\b", re.I),      # 페이지 머리글
    re.compile(r"\b\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}\b"),  # 날짜 스탬프
    re.compile(r"\b\d{1,2}:\d{2}\s*(?:[AP]M)?\b", re.I),   # 시각 스탬프
    re.compile(r"[\s\W_]+"),                             # 공백·구두점
]


def substantive_text(text: str) -> str:
    """chrome(URL·페이지머리글·날짜·시각·공백/구두점)를 걷어낸 실질 글자."""
    s = text or ""
    for pat in _CHROME:
        s = pat.sub("", s)
    return s


def is_low_content(text: str, npages: int = 1, *, min_total: int = 80,
                   min_per_page: int = 25) -> bool:
    """실질 글자 수가 문서 전체 또는 페이지당 기준 미만이면 저내용(=OCR 필요)."""
    sub = len(substantive_text(text))
    return sub < min_total or sub / max(npages, 1) < min_per_page
