"""[실험 v3] 실행 중 k의 '작은 k 해석'(grouping.conservative) · 규칙 C(다시 확인에서 새로 붙은 성별 · 나이).

사례는 실제 LLM 실행 fix_A8 T0005 사례2 (턴 6까지의 공개 11개, 저장소 461명):
다시 확인 추출이 '현재 환자(1세 남아)'의 '남아'를 사례2에 붙여 SEX_MALE이 먼저 들어갔고, 다음 턴의 실제 거주 도시가
기존 보정에서 '모순'으로 빠져 실행 k 7이 됐다. 정답 기준 k는 1이다.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from medical.bundle.kcalc import KCalc
from medical.data import STORE, split_cohort
from medical.grouping import GroupRepairKC

PID = "5b8b519c-06c9-d5e7-d489-b058c0619911"       # fix_A8 T0005 사례2의 정답 환자 (여성)
CITY = "REGION_DATASET_LOCALITY_79165D5DAE8D832D"
G = "사례2:e1"
TURN6 = [dict(attribute="AGE", node_id="AGE_Y3", event_group=G),
         dict(attribute="PROC", node_id="PROC_SCT_1260009003", event_group=G),
         dict(attribute="PROC", node_id="PROC_SCT_1260010008", event_group=G),
         dict(attribute="PROC", node_id="PROC_SCT_1256042007", event_group=G),
         dict(attribute="AGE", node_id="AGE5_0", event_group=None),
         dict(attribute="REGION", node_id="REGION_DATASET_STATE_MASSACHUSETTS", event_group=None),
         dict(attribute="AGE", node_id="AGE5_0", event_group=None),
         dict(attribute="AGE", node_id="AGE_Y3", event_group=None),
         dict(attribute="SEX", node_id="SEX_MALE", event_group=None),          # 잘못 붙은 값
         dict(attribute="AGE", node_id="AGE5_0", event_group=None),
         dict(attribute="REGION", node_id=CITY, event_group=None)]            # 실제 거주 도시


@pytest.fixture(scope="module")
def store_kc(paths, data):
    store = {p for p, s in split_cohort(data, 0.2, 20261009).items() if s == STORE}
    return KCalc(paths.nodes, paths.events, patients=store)


def test_conservative_repair_does_not_let_a_wrong_value_push_out_a_true_one(store_kc):
    old, new = GroupRepairKC(store_kc), GroupRepairKC(store_kc, conservative=True)
    assert store_kc.k(TURN6)["k"] == 0                                    # 틀린 성별과 실제 도시가 함께 맞는 사람이 없다
    r_old, r_new = old.k(TURN6), new.k(TURN6)
    assert r_old["k"] == 7 and any(f.startswith(f"CONFLICT_DROPPED REGION:{CITY}") for f in r_old["flags"])
    assert r_new["k"] == 1 and "CONSERVATIVE_DROP SEX:SEX_MALE" in r_new["flags"]
    assert new.candidates(TURN6) == {PID}
    without_wrong = [d for d in TURN6 if d["node_id"] != "SEX_MALE"]
    assert new.k(without_wrong)["k"] == old.k(without_wrong)["k"] == 1    # 값끼리 맞으면 두 방식이 같다


def test_conservative_repair_keeps_merged_events_as_before(paths):
    """같은 약을 여러 번 처방한 것을 한 줄로 합친 경우(묶음 나누기만 필요)는 작은 k 해석을 쓰지 않는다."""
    kc = KCalc(paths.nodes, paths.events)
    merged = [dict(attribute="DX", node_id="DX_SCT_66383009", event_group="c:e1"),
              dict(attribute="DX", node_id="DX_SCT_18718003", event_group="c:e1"),
              dict(attribute="PERIOD", node_id="PERIOD_CONDITION_START_DATE_DAY_2016-11-14", event_group="c:e1"),
              dict(attribute="MED", node_id="MED_RX_1535362", event_group="c:e5"),
              dict(attribute="PERIOD", node_id="PERIOD_MEDICATION_START_UTC_DAY_2016-11-21", event_group="c:e5"),
              dict(attribute="PERIOD", node_id="PERIOD_MEDICATION_END_UTC_DAY_2024-01-08", event_group="c:e5")]
    a, b = GroupRepairKC(kc).k(merged), GroupRepairKC(kc, conservative=True).k(merged)
    assert a["k"] == b["k"] and not any(f.startswith("CONSERVATIVE") for f in b["flags"])


def test_patient_level_conflict_counts_the_smaller_side(store_kc):
    """남성과 여성이 함께 붙으면 kcalc는 둘 다 버린다(k가 커짐). 작은 k 해석은 한쪽씩 남겨 센 값 중 작은 것을 쓴다."""
    both = [dict(attribute="SEX", node_id="SEX_FEMALE", event_group=None),
            dict(attribute="SEX", node_id="SEX_MALE", event_group=None),
            dict(attribute="REGION", node_id=CITY, event_group=None)]
    old, new = GroupRepairKC(store_kc).k(both)["k"], GroupRepairKC(store_kc, conservative=True).k(both)
    f = store_kc.k([both[0], both[2]])["k"]
    m = store_kc.k([both[1], both[2]])["k"]
    assert old == store_kc.k([both[2]])["k"] and new["k"] == min(f, m) < old
    assert any(x.startswith("PATIENT_CONFLICT keep SEX:") for x in new["flags"])


def test_validation_keeps_the_previous_repair(store_kc, data):
    """정답 기준 k(Validated k)는 실행 k의 작은 k 해석을 쓰지 않는다 (이전 실행과 같은 정의)."""
    from medical.validate import _eval_kc, validate_case
    old, new = GroupRepairKC(store_kc), GroupRepairKC(store_kc, conservative=True)
    assert _eval_kc(old) is old and _eval_kc(new).conservative is False and _eval_kc(new) is _eval_kc(new)
    a, b = validate_case(TURN6, PID, data, old), validate_case(TURN6, PID, data, new)
    assert a == b and a["k_val"] == 1 and a["labels"].count("INCORRECT") == 1


def _run_with(kc, committed):
    from medical.session import ArmRun
    from medical.tracking import Case
    run = ArmRun.__new__(ArmRun)
    run.ctx = SimpleNamespace(kc=kc)
    run.cases = {"사례2": Case(ref="사례2", committed=list(committed))}
    return run


def test_rule_c_blocks_sex_or_age_that_neither_the_plan_nor_the_state_has(store_kc):
    kc = GroupRepairKC(store_kc, conservative=True)
    run = _run_with(kc, TURN6[:8])                                         # 턴 5 전: 나이 AGE_Y3 · AGE5_0 은 이미 공개됨
    run._plan_ok = {"사례2": {"REGION_DATASET_STATE_MASSACHUSETTS"}}      # 이번 계획이 내보내도 된다고 한 노드
    parent = kc.node["AGE5_0"]["parent_id"]
    v = SimpleNamespace(case_refs=["사례2"],
                        disclosures={"사례2": [dict(attribute="SEX", node_id="SEX_MALE", event_group=None),
                                              dict(attribute="AGE", node_id="AGE5_0", event_group=None),
                                              dict(attribute="AGE", node_id=parent, event_group=None),
                                              dict(attribute="AGE", node_id="AGE_Y1", event_group=None)]},
                        sources={"사례2": [dict(raw_value="남아"), dict(raw_value="0-3세"), dict(raw_value="어린이"), dict(raw_value="1세")]})
    bad = run._unplanned_person(v)
    assert [(b["attribute"], b["node_id"], b["raw_value"]) for b in bad] == [("SEX", "SEX_MALE", "남아"), ("AGE", "AGE_Y1", "1세")]
    assert all(b["reason"] == "UNPLANNED_SEX_AGE" and b["ok"] is False for b in bad)
    run._plan_ok = {"사례2": {"SEX_MALE", "AGE_Y1"}}                       # 계획에 있으면 통과
    assert run._unplanned_person(v) == []
    del run._plan_ok                                                      # 계획 정보가 없으면(이번 공개 전) 검사하지 않는다
    assert run._unplanned_person(v) == []


def test_rule_c_uses_this_turns_plan_kept_by_the_product_defender(store_kc):
    """제품(webdemo)은 단위 맞춤(ROUNDED)에서 release 밖에서 다시 확인한다. 그때도 지난 턴 계획이 아니라 이번 턴 계획으로 본다."""
    kc = GroupRepairKC(store_kc, conservative=True)
    run = _run_with(kc, [])
    run._plan_ok = {"사례2": set()}                                          # 지난 턴에 남은 계획 (쓰면 안 됨)
    x = SimpleNamespace(action="allow", disclosure=dict(attribute="AGE", node_id="AGE10_30"), to_node="AGE10_30")
    run.ctx = SimpleNamespace(kc=kc, defender=SimpleNamespace(last_plans=[SimpleNamespace(ref="사례2", decisions=[x])]))
    v = SimpleNamespace(case_refs=["사례2"], disclosures={"사례2": [dict(attribute="AGE", node_id="AGE10_30", event_group=None)]},
                        sources={"사례2": [dict(raw_value="30~39세")]})
    assert run._unplanned_person(v) == []


def test_rule_c_values_are_the_ones_masked_on_retry(store_kc):
    run = _run_with(GroupRepairKC(store_kc, conservative=True), [])
    v = SimpleNamespace(case_refs=["사례2"], disclosures={"사례2": [dict(attribute="SEX", node_id="SEX_MALE", event_group=None),
                                                                  dict(attribute="REGION", node_id=CITY, event_group=None)]},
                        sources={"사례2": [dict(raw_value="남아", case_ref="사례2", attribute="SEX"),
                                          dict(raw_value="Watertown", case_ref="사례2", attribute="REGION")]})
    checks = [dict(ref="사례2", reason="UNPLANNED_SEX_AGE", attribute="SEX", node_id="SEX_MALE", raw_value="남아", ok=False)]
    out = run._leftover_changes([], v, checks, "현재 환자(1세 남아)", "질문")
    assert [(c["raw_value"], c["action"]) for c in out] == [("남아", "suppress")]
