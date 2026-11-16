"""정규화 확장 v0.11.4~5-exp (턴 0 · 다시 확인의 '귀속된 미매핑' 줄이기) 규칙 6~11, 9-1 · 남은 값 가리기."""
from __future__ import annotations

import pytest

from medical.normalize_ext import NormalizerV2


@pytest.fixture(scope="module")
def v2(paths):
    return NormalizerV2(paths.nodes, paths.alias)


def _norm(nz, att, raw, role=None):
    return nz.normalize(dict(attribute=att, raw_value=raw, evidence_spans=[raw], subject="TARGET_PATIENT", case_ref="사례1",
                             context_status="CURRENT", time_role=role, confidence=5), raw)


def test_period_suffixes_and_korean_dates(v2):
    assert _norm(v2, "PERIOD", "1992-12-13 시작, 지속", "MEDICATION_START")["node_id"] == "PERIOD_MEDICATION_START_UTC_DAY_1992-12-13"
    assert _norm(v2, "PERIOD", "1985-06-04 이후 지속", "MEDICATION_START")["node_id"] == "PERIOD_MEDICATION_START_UTC_DAY_1985-06-04"
    assert _norm(v2, "PERIOD", "2017년 5월 24일", "PROCEDURE_START")["node_id"] == "PERIOD_PROCEDURE_START_UTC_DAY_2017-05-24"


def test_period_year_and_month_ranges_read_like_start_or_end(v2):
    assert _norm(v2, "PERIOD", "2016-2022", "PROCEDURE_START")["node_id"] == "PERIOD_PROCEDURE_START_UTC_YEAR_2016"
    assert _norm(v2, "PERIOD", "2022년 11월-2023년 2월", "CONDITION_END")["node_id"] == "PERIOD_CONDITION_END_DATE_MONTH_2023-02"
    assert _norm(v2, "PERIOD", "1966년 4월~8월", "MEDICATION_END")["node_id"] == "PERIOD_MEDICATION_END_UTC_MONTH_1966-08"


def test_non_time_period_values_are_held_not_unmapped(v2):
    for raw in ("약 8일", "약 10-11일", "1월", "지속 중", "여러 시점에서 진단"):
        o = _norm(v2, "PERIOD", raw, "MEDICATION_START")
        assert o["mapping_status"] == "PENDING" and not o["commit"], raw
    assert _norm(v2, "PERIOD", "Unspecified convulsions 시작일", "CONDITION_START")["mapping_status"] == "UNMAPPED"   # 이름이 든 값은 막힘 그대로


def test_age_in_period_and_age_forms(v2):
    o = _norm(v2, "PERIOD", "51세 당시", "CONDITION_START")
    assert o["attribute"] == "AGE" and o["node_id"] == "AGE_Y51" and o["raw_value"] == "51세 당시"
    assert _norm(v2, "AGE", "70세대")["node_id"] == "AGE10_70"
    assert _norm(v2, "AGE", "0세~3세")["node_id"] == "AGE5_0"
    assert _norm(v2, "AGE", "15세경")["node_id"] == "AGE10_10"
    assert _norm(v2, "AGE", "36-44세")["node_id"] == "AGE_Y36"                 # 구간을 넘는 범위 → 시작 나이
    assert _norm(v2, "AGE", "20세 이상")["mapping_status"] == "PENDING"


def test_korean_general_names_map_to_broad_nodes(v2):
    assert _norm(v2, "DX", "고혈압")["node_id"] == "DX_ICD_SECTION_I10-I1A"
    assert _norm(v2, "DX", "빈혈")["node_id"] == _norm(v2, "DX", "Anemia")["node_id"]          # 한국어 이름은 영어와 같은 노드
    assert _norm(v2, "DX", "당뇨·고혈압")["node_id"] == "DX_ICD_SECTION_E08-E13"
    assert _norm(v2, "MED", "항생제")["node_id"] == "MED_ATC_J01"
    assert _norm(v2, "PROC", "치과 시술")["node_id"] == "PROC_GROUP_0_C"
    assert _norm(v2, "DX", "Gingivitis & Gingival disease")["commit"]


def test_cross_attribute_and_not_a_place(v2):
    o = _norm(v2, "PROC", "Respiratory therapy")
    assert o["attribute"] == "PLAN" and o["commit"]
    assert _norm(v2, "REGION", "기록됨")["mapping_status"] == "PENDING"


def test_suppressed_marker_values_are_untouched(v2):
    assert _norm(v2, "AGE", "1(비공개)")["mapping_status"] == "UNMAPPED"
    assert _norm(v2, "PERIOD", "20(비공개)-07-12", "PROCEDURE_END")["mapping_status"] == "UNMAPPED"


def test_korean_medical_terms_follow_their_english_names(v2):
    assert _norm(v2, "DX", "심근경색")["node_id"] == "DX_ICD_CODE_I21"                    # 일반 이름은 모든 심근경색을 감싸는 노드로
    for ko, en, att in (("고지혈증", "Hyperlipidemia", "DX"), ("치은염", "Gingivitis", "DX"),
                        ("아세트아미노펜", "acetaminophen", "MED"), ("대장내시경", "Colonoscopy", "PROC")):
        a, b = _norm(v2, att, ko), _norm(v2, att, en)
        assert a["commit"] and a["node_id"] == b["node_id"], ko
    assert _norm(v2, "DX", "만성신질환")["node_id"] == "DX_ICD_CODE_N18"
    assert _norm(v2, "DX", "고지혈증 진단")["commit"]


def test_sex_child_words_and_age_oddities(v2):
    assert _norm(v2, "SEX", "여아")["node_id"] == "SEX_FEMALE" and _norm(v2, "SEX", "남아")["node_id"] == "SEX_MALE"
    assert _norm(v2, "AGE", "1985-2025")["mapping_status"] == "PENDING"
    assert _norm(v2, "AGE", "48세 (진단 당시 37-42세)")["node_id"] == "AGE_Y48"


def test_research_arm_masks_unknown_values_instead_of_refusing(v2):
    """연구 하네스(ArmRun): 귀속됐지만 정규화 안 된 값 · 번호 없는 대상 정보를 '(비공개)'로 바꿀 목록으로 만든다."""
    from types import SimpleNamespace
    from medical.session import ArmRun
    from medical.tracking import view_of
    resp = "사례1은 남성이고 호르몬제를 복용했습니다. 여러 사례에서 amoxicillin이 처방되었습니다."
    obs = [dict(attribute="MED", raw_value="호르몬제", evidence_spans=["호르몬제"], case_ref="사례1", subject="TARGET_PATIENT", context_status="CURRENT", confidence=5),
           dict(attribute="MED", raw_value="amoxicillin", evidence_spans=["amoxicillin"], case_ref="UNCLEAR", subject="TARGET_PATIENT", context_status="CURRENT", confidence=5)]
    run = ArmRun.__new__(ArmRun)
    run.ctx = SimpleNamespace(nz=v2)
    v = view_of(obs, resp, "질문", v2)
    assert v.unmapped_sensitive and v.unclear_mappable
    m1 = run._mask_list(v, resp, "질문", "UNMAPPED")
    m2 = run._mask_list(v, resp, "질문", "UNATTRIBUTED")
    assert [m["raw_value"] for m in m1] == ["호르몬제"] and m1[0]["action"] == "suppress" and m1[0]["mask"] == "UNMAPPED"
    assert [m["raw_value"] for m in m2] == ["amoxicillin"] and m2[0]["case_ref"] == "사례 미지정"
