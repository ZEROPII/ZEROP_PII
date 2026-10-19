# 가짜 LLM으로 문서 → trial(C0·C1·C1S) → 평가 → 집계까지 배선과 불변 조건을 확인한다 (숫자 자체는 의미 없음)
from __future__ import annotations

import json
from pathlib import Path

import pytest

from medical.config import MedicalConfig
from medical.experiment import run_experiment
from medical.llm import MockRoleLLM
from medical.report import mcnemar_exact, report

OUTCOMES = {"NO_CASE", "RISK_AT_TURN0", "RISK_REACHED", "SATURATED", "MUTATION_BUDGET", "BUDGET", "LLM_ERROR"}


@pytest.fixture(scope="module")
def run(tmp_path_factory, data):
    out = tmp_path_factory.mktemp("med_dry")
    cfg = MedicalConfig(trials_per_cell=1, budget_B=6)
    summary = run_experiment(cfg, MockRoleLLM(), out, limit=4, store_limit=60, data=data, progress=lambda s: None)
    return out, summary


def _turns(out: Path) -> list[dict]:
    return [json.loads(l) for l in (out / "턴기록.jsonl").read_text(encoding="utf-8").splitlines()]


def test_files_and_outcomes(run):
    out, summary = run
    for f in ("코호트분리.csv", "RAG문서.jsonl", "사실표.csv", "run_meta.json", "턴기록.jsonl", "trial요약.json", "llm_usage.jsonl"):
        assert (out / f).exists(), f
    assert len(summary["trials"]) == 4 * 3
    assert {t["arm"] for t in summary["trials"]} == {"C0", "C1", "C1S"}
    assert all(t["outcome"] in OUTCOMES for t in summary["trials"])
    meta = json.loads((out / "run_meta.json").read_text(encoding="utf-8"))
    assert "rewriter" in meta["prompts"] and meta["cohort"]["store"] == 60


def test_turn0_is_shared_across_arms(run):
    out, _ = run
    t0 = {}
    for r in _turns(out):
        if r.get("turn") == 0:
            t0.setdefault(r["trial_id"], set()).add((r["query_text"], r["raw_response_text"]))
    assert t0 and all(len(v) == 1 for v in t0.values())


def test_c0_never_rewrites_and_c1_state_comes_from_released_text(run):
    out, _ = run
    for r in _turns(out):
        if r.get("turn") is None:
            continue
        if r["arm"] == "C0":
            assert r["release_mode"] == "RAW" and r["response_text"] == r["raw_response_text"]
        for ref, c in r["cases"].items():
            for o in c.get("normalized", []):
                if o.get("commit"):
                    assert all(sp in r["response_text"] for sp in o["evidence_spans"])   # 공개되지 않은 표현은 State에 없음
        for ch in r.get("release_changes", []):
            if r["release_mode"].startswith("REWRITTEN") and ch["action"] == "suppress" and ch["raw_value"]:
                assert ch["raw_value"] not in r["response_text"]


def test_validation_and_report(run):
    out, summary = run
    for t in summary["trials"]:
        for v in t.get("validation", {}).values():
            if "k_val" in v:
                assert v["k_val"] >= 1 and v["target_in_candidates"] in (True, False)
    s = report(out)
    assert set(s["arms"]) == {"C0", "C1", "C1S"}
    assert (out / "report.md").exists()


def test_mcnemar_exact():
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(6, 0) == pytest.approx(0.03125)
    assert mcnemar_exact(3, 3) == 1.0
