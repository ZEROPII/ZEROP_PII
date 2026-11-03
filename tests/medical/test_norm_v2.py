"""정규화 확장 v0.11.3(medical/normalize_ext.py) · 추출 바로잡기(medical/obs_fix.py) · 나열 귀속 · 질의 환자 빼기."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from medical.bundle.normalize_bridge import Normalizer
from medical.config import MedicalConfig
from medical.data import split_cohort
from medical.experiment import plan_trials
from medical.normalize_ext import NormalizerV2
from medical.obs_fix import fix_observations
from medical.rule_extract import list_observations
from medical.session import extract


@pytest.fixture(scope="module")
def v2(paths):
    return NormalizerV2(paths.nodes, paths.alias)


def _norm(nz, att, raw, **kw):
    return nz.normalize(dict(attribute=att, raw_value=raw, evidence_spans=[raw], subject="TARGET_PATIENT", case_ref="사례1", **kw), raw)


def test_period_ranges_read_like_their_start_or_end(v2, nz):
    assert v2._period("2018-03-09~24", "MEDICATION_END") == nz._period("2018-03-24", "MEDICATION_END")
    assert v2._period("2018-03-09~24", "MEDICATION_START") == nz._period("2018-03-09", "MEDICATION_START")
    assert v2._period("2017-08-01~08-15", "PROCEDURE_END") == nz._period("2017-08-15", "PROCEDURE_END")
    assert v2._period("2016-02-01~현재", "MEDICATION_START") == nz._period("2016-02-01", "MEDICATION_START")
    assert v2._period("2012-10-02 시작", "CAREPLAN_START") == nz._period("2012-10-02", "CAREPLAN_START")


def test_sex_short_forms_and_age_ranges(v2, nz):
    assert _norm(v2, "SEX", "남")["node_id"] == "SEX_MALE" and _norm(v2, "SEX", "여")["node_id"] == "SEX_FEMALE"
    assert not _norm(nz, "SEX", "남")["commit"]                       # 묶음 그대로(v1)는 못 받음
    assert v2._age("93-96세") == "AGE10_90" and v2._age("61-63세") == "AGE5_60" and v2._age("54세") == "AGE_Y54"


def test_partial_names_map_to_their_closest_common_ancestor(v2):
    o = _norm(v2, "MED", "ibuprofen")
    assert o["commit"] and "TOKEN_SUBSET_LCA" in o["reasons"]
    assert o["node_id"] in v2._anc("MED_RX_198405") and not o["node_id"].startswith("ANY")    # 제품보다 넓게, 뿌리는 아님
    p = _norm(v2, "PROC", "Removal of supragingival plaque")
    assert p["commit"] and p["node_id"] in v2._anc("PROC_SCT_1260009003")
    for vague in ("of", "500 MG", "care"):                              # 너무 짧거나 숫자뿐이면 찾지 않음 / 뿌리면 반영 안 함
        assert not _norm(v2, "MED", vague)["commit"]


def test_exact_names_are_unchanged_by_v2(v2, nz):
    for att, raw in (("MED", "ibuprofen 100 MG Oral Tablet"), ("DX", "Laceration of forearm"), ("SEX", "남성")):
        assert _norm(v2, att, raw)["node_id"] == _norm(nz, att, raw)["node_id"]


def test_fix_observations():
    base = dict(evidence_spans="x", case_ref="사례1", subject="TARGET_PATIENT")
    out = fix_observations([dict(base, attribute="PLAN", raw_value="ibuprofen 100 MG Oral Tablet"),
                            dict(base, attribute="PERIOD", raw_value="3세", time_role="CONDITION_START"),
                            dict(base, attribute="AGE", raw_value="37세→43세"),
                            dict(base, attribute="PERIOD", raw_value="12세 이후", time_role="CONDITION_START"),
                            dict(base, attribute="PLAN", raw_value="Physiotherapy care plan")])
    got = [(o["attribute"], o["raw_value"], o.get("fixed_from")) for o in out]
    assert got == [("MED", "ibuprofen 100 MG Oral Tablet", "PLAN"), ("AGE", "3세", "PERIOD"), ("AGE", "37세", "AGE_ARROW"),
                   ("AGE", "43세", "AGE_ARROW"), ("PERIOD", "12세 이후", None), ("PLAN", "Physiotherapy care plan", None)]
    assert "time_role" not in out[1]
    mixed = fix_observations([dict(base, attribute="PLAN", raw_value="acetaminophen 325 MG Oral Tablet, Respiratory therapy"),
                              dict(base, attribute="DX", raw_value="Chronic sinusitis, unspecified"),
                              dict(base, attribute="MED", raw_value="clonazepam 0.25 MG Oral Tablet, diazepam 5 MG Oral Tablet")])
    assert [(o["attribute"], o["raw_value"]) for o in mixed] == [
        ("MED", "acetaminophen 325 MG Oral Tablet"), ("PLAN", "Respiratory therapy"), ("DX", "Chronic sinusitis, unspecified"),
        ("MED", "clonazepam 0.25 MG Oral Tablet"), ("MED", "diazepam 5 MG Oral Tablet")]


def test_list_attribution(v2):
    resp = "공통 진단\n- 사례1, 3: Laceration of forearm\n- 사례2: 기록 없음"
    got = {(o["case_ref"], o["attribute"], o["raw_value"]) for o in list_observations(resp, [], v2)}
    assert got == {("사례1", "DX", "Laceration of forearm"), ("사례3", "DX", "Laceration of forearm")}
    known = [dict(case_ref="사례1", attribute="DX", raw_value="Laceration of forearm")]
    assert {o["case_ref"] for o in list_observations(resp, known, v2)} == {"사례3"}


def test_extract_applies_fixes_only_with_rule_flag(v2):
    llm = SimpleNamespace(complete=lambda *a, **k: json.dumps([dict(attribute="PLAN", raw_value="ibuprofen 100 MG Oral Tablet",
                                                                    evidence_spans=["ibuprofen 100 MG Oral Tablet"], case_ref="사례1", subject="TARGET_PATIENT")]))
    for flag, att in ((False, "PLAN"), (True, "MED")):
        ctx = SimpleNamespace(cfg=SimpleNamespace(max_extract_retries=0, rule_extract=flag), llm=llm, nz=v2)
        obs, ok, _ = extract(ctx, "질문", "사례1\n처방: ibuprofen 100 MG Oral Tablet", "[]", [])
        assert ok and obs[0]["attribute"] == att


def test_plan_can_exclude_earlier_query_patients(data):
    split = split_cohort(data, 0.2, 20261009)
    full = plan_trials(data, split, MedicalConfig())
    first = full[0][1]
    kept = plan_trials(data, split, MedicalConfig(exclude_patients=(first,)))
    assert first not in {t[1] for t in kept} and len(kept) == len([t for t in full if t[1] != first])
    assert [t[0] for t in kept] == [t[0] for t in full if t[1] != first]      # trial 번호는 그대로
