"""[실험 v4] 최종판: k=5 하한(s=4) · 단조 보정 · 현재 환자 괄호 · 정규화 v0.11.6 · 억제 전 넓히기(widen_first)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from medical.config import MedicalConfig, MedicalPaths
from medical.defense import ALLOW, GENERALIZE, SUPPRESS, MedicalDefender, capped_k
from medical.normalize_ext import make_normalizer
from medical.session import ArmRun, Basis, release_need
from medical.tracking import Case, view_of


# ── 1. 하한 s=4 (옵션 B): 대체 허용도 k>=5 ──

def test_default_floor_matches_k_req():
    cfg = MedicalConfig()
    assert (cfg.k_req, cfg.generalize_threshold, cfg.suppress_threshold) == (5, 5, 4)
    assert release_need(cfg.suppress_threshold, 20) == cfg.k_req           # 다시 확인 하한도 5
    assert release_need(3, 20) == 4                                         # 옵션 A는 --suppress-threshold 3 으로 재현


def test_cli_and_simulation_defaults_follow_config():
    from medical import __main__ as cli, simulate
    assert MedicalConfig.suppress_threshold == 4 and MedicalConfig.widen_first == ()          # 억제 전 넓히기는 옵션
    for mod in (cli, simulate):                                              # 실행 명령 기본값이 설정 파일 기본값을 따른다
        src = open(mod.__file__, encoding="utf-8").read()
        assert "default=MedicalConfig.suppress_threshold" in src


# ── 2. 단조 보정 ──

class _GrowKC:
    """값 1개면 k 4, 2개 이상이면 k 11 ('한 사건' 해석이 깨져 '따로'로 넘어간 경우를 흉내)."""
    by_pat = {f"p{i}": None for i in range(461)}

    def k(self, ds):
        return {"k": 4 if len(ds) == 1 else 11, "flags": []}


class _Chain:
    """노드 'x' → 'x_parent' → 'ROOT' 사슬."""

    def anc(self, n):
        return [n, n + "_parent", "ROOT"]

    def is_root(self, n):
        return n == "ROOT"

    def depth(self, n):
        return 2


D0 = dict(attribute="AGE", node_id="AGE_Y3", event_group=None)
D1 = dict(attribute="DX", node_id="DX_A", event_group=None)


def test_monotone_cap_in_planner():
    d = MedicalDefender(_GrowKC(), _Chain(), generalize_threshold=5, suppress_threshold=4)
    plain = d.plan_case("사례5", [D0], [D1], [dict(raw_value="a")])
    assert plain.k_projected == 11 and not plain.risky                         # 보정 없이 세면 값이 늘었는데 k가 4 → 11
    b = Basis([D0])
    b.k_cap = 4
    capped = d.plan_case("사례5", b, [D1], [dict(raw_value="a")])
    assert capped.k_before == 4 and capped.k_projected == 4 and capped.risky
    assert [x.action for x in capped.decisions] == [SUPPRESS]
    assert capped_k(11, 4) == 4 and capped_k(0, 4) == 0 and capped_k(7, None) == 7


def _run(arm="C1", k_hist=(30, 6, 0)):
    run = ArmRun.__new__(ArmRun)
    run.arm = arm
    run.cases = {"사례5": Case(ref="사례5", committed=[D0], k_hist=list(k_hist))}
    return run


def test_harness_basis_carries_smallest_runtime_k():
    b = _run()._basis("사례5")
    assert isinstance(b, Basis) and list(b) == [D0] and b.k_cap == 6     # 0(아무도 맞지 않음)은 상한으로 쓰지 않는다
    assert _run(arm="C1S")._basis("사례5") == []

    class Product(ArmRun):                                               # 제품(webdemo RuledArmRun)은 ADR-0043 보정을 쓴다
        pass
    p = Product.__new__(Product)
    p.arm, p.cases = "C1", _run().cases
    assert p._basis("사례5").k_cap is None


# ── 3. 현재 환자 괄호 ──

@pytest.fixture(scope="module")
def nz():
    return make_normalizer(MedicalPaths(), "v2")


def _obs(raw, span, att="SEX"):
    return dict(attribute=att, raw_value=raw, evidence_spans=[span], case_ref="사례2", subject="TARGET_PATIENT",
                context_status="UNSPECIFIED")


def test_current_patient_paren_values_are_not_attributed_to_the_case(nz):
    text = "사례2는 현재 환자(1세 남아)와 연령대가 가장 유사한 사례입니다. 사례2는 여아입니다."
    v = view_of([_obs("남아", "현재 환자(1세 남아)"), _obs("1세", "1세 남아", "AGE"), _obs("여아", "사례2는 여아")], text, "질문", nz)
    assert [d["node_id"] for d in v.disclosures["사례2"]] == ["SEX_FEMALE"]
    fixed = [o for o in v.normalized["사례2"] if o.get("subject_fixed") == "CURRENT_PATIENT_PAREN"]
    assert [o["raw_value"] for o in fixed] == ["남아", "1세"] and not v.unmapped_sensitive


def test_current_patient_paren_kept_when_the_case_is_said_to_be_the_same(nz):
    text = "사례2도 현재 환자(1세 남아)와 같은 1세 남아입니다."
    v = view_of([_obs("남아", "현재 환자(1세 남아)")], text, "질문", nz)
    assert [d["node_id"] for d in v.disclosures["사례2"]] == ["SEX_MALE"]


# ── 4. 정규화 v0.11.6 ──

def _n(nz, att, raw, role=None):
    o = dict(attribute=att, raw_value=raw, evidence_spans=[raw], case_ref="사례1", subject="TARGET_PATIENT",
             context_status="UNSPECIFIED", time_role=role)
    return nz.normalize(o, raw, "")


@pytest.mark.parametrize("raw", ["진단 후 약 2-3년 경과 후", "약 9년 6개월", "약 13년 후", "약 3년 간격", "진단 후 약 1.5년 경과 후", "1960년대"])
def test_relative_periods_and_decades_are_held(nz, raw):
    o = _n(nz, "PERIOD", raw, "CONDITION_START")
    assert o["mapping_status"] == "PENDING" and not o["commit"]


def test_period_range_and_names_in_period(nz):
    assert _n(nz, "PERIOD", "1984년부터 1993년까지", "CONDITION_START")["node_id"] == "PERIOD_CONDITION_START_DATE_YEAR_1984"
    assert _n(nz, "PERIOD", "1984년부터 1993년까지", "CONDITION_END")["node_id"] == "PERIOD_CONDITION_END_DATE_YEAR_1993"
    o = _n(nz, "PERIOD", "Chronic sinusitis, unspecified 진단 시작일", "CONDITION_START")
    assert o["attribute"] == "DX" and o["mapping_status"] == "MAPPED" and "NAME_IN_PERIOD_TO_DX" in o["reasons"]


@pytest.mark.parametrize("att,raw,node", [
    ("MED", "구강 건강 관련 약물", "MED_ATC_A01"), ("MED", "고혈압 치료제", "MED_ATC_C"), ("MED", "호흡기 질환 치료제", "MED_ATC_R"),
    ("DX", "골절 관련 진단", "DX_ICD_CHAPTER_19"), ("DX", "전당뇨병", "DX_ICD_CODE_R7303"), ("PROC", "전립선절제술", "PROC_SCT_90470006"),
    ("PROC", "투석", "PROC_SCT_302497006"), ("PLAN", "Care plan for diabetes self-management", "PLAN_SCT_735985000"),
    ("PLAN", "Care plan for cancer management", "PLAN_SCT_736252007"),
    ("PLAN", "고혈압 관리를 위한 생활 습관 교육 (식이 조절, 스트레스 관리)", "PLAN_SCT_443402002"),
    ("PLAN", "암 환자 종합 관리 (치료 계획 수립 및 추적, 정기적 모니터링)", "PLAN_SCT_736252007"),
    ("REGION", "Massachusetts 주 내 Watertown 지역", "REGION_DATASET_LOCALITY_79165D5DAE8D832D"),
    ("REGION", "Massachusetts 주 내 Boston 인근 지역", "REGION_DATASET_STATE_MASSACHUSETTS"),      # '근처'는 그 도시가 아니다
    ("REGION", "매사추세츠 주", "REGION_DATASET_STATE_MASSACHUSETTS"),
])
def test_v0116_names(nz, att, raw, node):
    o = _n(nz, att, raw)
    assert o["mapping_status"] == "MAPPED" and o["node_id"] == node, o


@pytest.mark.parametrize("att,raw", [("DX", "호흡기 감염"), ("DX", "대사 이상"), ("DX", "unspecified"), ("MED", "대사질환 약물"),
                                     ("MED", "Oral Tablet"), ("MED", "약물 관리"), ("PROC", "생검"), ("PROC", "복부 시술"),
                                     ("PLAN", "혈당 모니터링, 식이 관리, 약물 복용 순응도 관리, 정기적 검사"),
                                     ("MED", "(비공개) 등 대사질환 약물")])
def test_values_that_name_no_single_node_are_held(nz, att, raw):
    o = _n(nz, att, raw)
    assert o["mapping_status"] == "PENDING" and not o["commit"], o


def test_mapped_values_are_unchanged_and_ongoing_markers_still_block(nz):
    from medical.tracking import is_marker_only
    assert _n(nz, "DX", "Gingivitis")["node_id"] == "DX_SCT_66383009"
    assert is_marker_only("(비공개) 시행") and not is_marker_only("(비공개) 지속") and not is_marker_only("(비공개) 장기 사용")
    o = _n(nz, "PLAN", "무릎 골관절염의 진행 억제 및 기능 유지")
    assert o["attribute"] == "DX" and o["mapping_status"] == "MAPPED"


# ── 5. 억제 전 넓히기 (widen_first) ──

class _DateKC:
    """원래 날짜(일)는 후보 2명, 연으로 넓히면 40명."""
    by_pat = {f"p{i}": None for i in range(461)}

    def k(self, ds):
        last = ds[-1]["node_id"] if ds else ""
        return {"k": 40 if last.endswith("_parent") else 2 if ds else 461, "flags": []}


def test_widen_first_generalizes_instead_of_suppressing():
    d_old = MedicalDefender(_DateKC(), _Chain(), generalize_threshold=5, suppress_threshold=4)
    d_new = MedicalDefender(_DateKC(), _Chain(), generalize_threshold=5, suppress_threshold=4, widen_first=("PERIOD", "AGE"))
    day = dict(attribute="PERIOD", node_id="PERIOD_DAY", event_group=None)
    dx = dict(attribute="DX", node_id="DX_B", event_group=None)
    old = d_old.plan_case("사례1", [], [day, dx], [{}, {}])
    new = d_new.plan_case("사례1", [], [day, dx], [{}, {}])
    assert [x.action for x in old.decisions] == [SUPPRESS, SUPPRESS]
    assert [(x.action, x.to_node) for x in new.decisions][0] == (GENERALIZE, "PERIOD_DAY_parent")
    assert new.decisions[1].action == SUPPRESS                           # 넓히기는 지정한 종류만
    assert ALLOW not in [x.action for x in new.decisions]


@pytest.mark.parametrize("att,raw,role,status,attr_out,node", [
    ("PERIOD", "Ischemic heart disease 진단 후 6일", "CONDITION_START", "MAPPED", "DX", "DX_SCT_414545008"),
    ("PERIOD", "Diabetes mellitus type 2 진단 후 4년 1개월", "CONDITION_START", "MAPPED", "DX", "DX_SCT_44054006"),
    ("PERIOD", "N NERVOUS SYSTEM DRUGS 첫 처방 시작일", "MEDICATION_START", "MAPPED", "MED", "MED_ATC_N"),
    ("PERIOD", "진단 후 1-3년 내", "CONDITION_START", "PENDING", "PERIOD", None),
    ("PERIOD", "2회 시행", "PROCEDURE_START", "PENDING", "PERIOD", None),
    ("AGE", "60~70세대", None, "MAPPED", "AGE", "AGE10_60"),
    ("DX", "Injury", None, "MAPPED", "DX", "DX_ICD_CHAPTER_19"),
    ("REGION", "기록에 명시된 거주지 정보 없음", None, "PENDING", "REGION", None),
    ("PLAN", "감염성 질환 관리", None, "PENDING", "PLAN", None),
    ("PLAN", "(비공개) (호흡기 치료)", None, "MAPPED", "PLAN", "PLAN_SCT_53950000"),
])
def test_v0116_rule18_examples_from_earlier_runs(nz, att, raw, role, status, attr_out, node):
    o = _n(nz, att, raw, role)
    assert (o["mapping_status"], o["attribute"], o.get("node_id")) == (status, attr_out, node), o
