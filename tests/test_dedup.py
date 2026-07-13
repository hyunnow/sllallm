"""중복 탐지 (HANDOFF §2 백로그). 알려진 두 사례를 회귀로 고정:
  B3-025≡B3-031  같은 강의(kocw), 추출 텍스트는 905자 vs 2079자로 갈림 → 파일명 키
  B2-033         한 파일에 간호학 4과목 → 파일 내 다중 실라버스
그리고 오탐 방지(한양대 웹추출 다른 과목, 주차행)를 함께 고정한다."""
from syllabus_classifier.dedup import (
    doc_signature, estimated_jaccard, intra_file_syllabus_count, metadata_key,
)
from syllabus_classifier.dedup.detect import filename_key


def test_b3_025_031_same_course_via_filename_key_despite_divergent_text():
    # NFD(분해형 자모) 파일명이어도 같은 키 — 학교 추론이 겪은 NFC 문제와 동일
    import unicodedata
    a = unicodedata.normalize("NFD", "kocw_syllabi__03_고려대__일반물리학및연습I__최준곤__7ae2f65673a33639")
    b = unicodedata.normalize("NFD", "kocw_syllabi__03_고려대__일반물리학_및_연습1__최준곤__b2bbcd3d3dcf7d68")
    ka, kb = filename_key(a), filename_key(b)
    assert ka is not None and ka == kb == "kocw|고려대|일반물리학및연습|최준곤"


def test_filename_key_distinguishes_different_courses():
    a = filename_key("kocw_syllabi__03_고려대__일반물리학및연습I__최준곤__aaaaaaaaaaaaaaaa")
    b = filename_key("kocw_syllabi__03_고려대__유기화학__김철수__bbbbbbbbbbbbbbbb")
    assert a != b
    # 비-kocw 파일명은 키 없음 (파일명 구조가 강의 정체를 안 담음)
    assert filename_key("hanyang_syllabi_302__19003_Plastic_Surgery") is None
    assert filename_key("Unist__oz.unist.ac.kr_8443_something") is None


def test_intra_file_multi_syllabus_counts_real_titles():
    # B2-033형: 서로 다른 과목명이 각각 "<제목> 강의계획서" 헤딩으로 선다
    text = ("간호경영과 지도자론 강의계획서\n<표>\n\n"
            "간호연구 및 통계 강의계획서\n<표>\n\n"
            "건강문제와 간호Ⅱ 강의계획서\n<표>\n\n"
            "통합실습 강의계획서\n<2016년 08월 29일~12월 9일> 15주\n")
    cnt, titles = intra_file_syllabus_count(text)
    assert cnt == 4
    assert "간호경영과 지도자론" in titles and "통합실습" in titles


def test_intra_file_ignores_section_headings_and_weekly_rows():
    # 단일 실라버스의 섹션/주차행이 다중으로 오탐되면 안 된다
    text = ("7/6/26, 2:41 PM 단국대학교\n강의계획서\n"
            "차시별 계획(Syllabus)\n"
            "장애학생 지원 관련 강의계획서\n"
            "1 품질혁신매뉴얼의 중요성 강의\n"
            "2 특허의 이해 강의계획\n")
    cnt, _ = intra_file_syllabus_count(text)
    assert cnt <= 1


def test_minhash_separates_same_course_from_boilerplate_siblings():
    # 같은 텍스트 ~1.0, 전혀 다른 텍스트 낮음 — 0.9 분리선의 근거
    base = "This syllabus covers linear algebra. " * 40
    same = base
    diff = "Completely different content about marine biology. " * 40
    assert estimated_jaccard(doc_signature(base), doc_signature(same)) >= 0.95
    assert estimated_jaccard(doc_signature(base), doc_signature(diff)) < 0.5


def test_metadata_key_normalizes_roman_and_spacing():
    a = metadata_key("고려대학교", "일반물리학및연습 I", "최준곤")
    b = metadata_key("고려대학교", "일반물리학 및 연습 1", "최준곤")
    assert a == b
