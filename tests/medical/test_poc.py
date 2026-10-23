# 의료 POC 도구: 피드백 Seed 선택, 모의 대상 AI 실행, 평가 v7.2 변환
from __future__ import annotations

import json

import pytest

from medical.adaptive import FeedbackSelector
from medical.config import MedicalConfig
from medical.data import load_data


def test_feedback_strategy_mapping():
    s = FeedbackSelector(threshold=5)
    s.last_seed = dict(seed_id="X", target_qi="PROC", variant="BASE")
    s.observe(100, 40)
    assert (s.status, s.strategy) == ("improved", "intensify")
    s.observe(40, 40)
    assert s.strategy == "diversify"
    s.observe(40, 30)
    assert s.strategy == "refine"
    s.observe(30, 0)
    assert s.strategy == "abort" and "PROC" in s.banned_qis


def test_feedback_pool_prefers_deeper_rows():
    s = FeedbackSelector()
    s.last_seed = dict(seed_id="A1", target_qi="PROC", variant="BASE")
    s.strategy = "intensify"
    rows = [(dict(seed_id="P-O2", target_qi="PROC", expected_relation="DESCENDANT", variant="BASE"), None),
            (dict(seed_id="D-O1", target_qi="DX", expected_relation="NEW", variant="BASE"), None)]
    assert [x[0]["seed_id"] for x in s._pool(rows)] == ["P-O2"]
    s.strategy = "diversify"
    s.asked_qis["PROC"] = 1
    assert [x[0]["seed_id"] for x in s._pool(rows)] == ["D-O1"]


@pytest.fixture(scope="module")
def sim_run(tmp_path_factory):
    from medical.experiment import run_experiment
    from medical.simulate import OracleRoleLLM, plan_all
    out = tmp_path_factory.mktemp("sim")
    data = load_data()
    cfg = MedicalConfig(budget_B=4)
    run_experiment(cfg, OracleRoleLLM(data=data, profile="staged"), out, data=data, store_limit=120,
                   planner=lambda d, s, c: plan_all(1, c.seed)(d, s, c)[:2], progress=lambda _: None)
    return out


def test_oracle_run_produces_paired_arms(sim_run):
    trials = json.loads((sim_run / "trial요약.json").read_text(encoding="utf-8"))["trials"]
    assert {t["arm"] for t in trials} == {"C0", "C1", "C1S"}
    turns = [json.loads(x) for x in open(sim_run / "턴기록.jsonl", encoding="utf-8")]
    # 모의 추출기는 대상 AI가 말한 값을 모두 정규화할 수 있어야 한다 (UNMAPPED 0)
    statuses = {o["mapping_status"] for r in turns for c in (r.get("cases") or {}).values() for o in c.get("normalized", [])}
    assert statuses <= {"MAPPED"}
    assert all("cases_candidate_k" in r for r in turns if r.get("turn") is not None)


def test_export_to_eval_v72(sim_run, tmp_path):
    from medical.export_eval import evaluate, export
    meta = export(sim_run, tmp_path / "ev")
    lines = [json.loads(x) for x in open(tmp_path / "ev" / "turn_log.jsonl", encoding="utf-8")]
    assert min(r["turn"] for r in lines) == 1
    assert {r["release_mode"] for r in lines} <= {"PASSTHROUGH", "ALLOWED", "REWRITTEN", "REFUSAL"}
    res = evaluate(tmp_path / "ev", meta["doc_icd3"], meta["target_icd3"])["result"]
    assert set(res["by_condition"]) == {"C0", "C1", "C1S"}
    assert res["tests"]


def test_grouping_cache_returns_independent_copies():
    from medical.bundle.kcalc import KCalc
    from medical.config import MedicalPaths
    from medical.grouping import GroupRepairKC
    p = MedicalPaths()
    data = load_data()
    pid = data.patients()[0]
    kc = GroupRepairKC(KCalc(p.nodes, p.events, patients=set(data.patients()[:50])))
    ds = [dict(attribute="SEX", node_id=data.by_pat[pid][0]["sex_node"], event_group=None)]
    a = kc.k(ds)
    a["flags"].append("x")
    assert "x" not in kc.k(ds)["flags"] and kc.k(ds)["k"] == a["k"]
    assert kc.candidates(ds) == kc.base.candidates(ds)
