# v3 계측 검증: 배포 경로 응답 시간 · 턴 0 기록 · 추출 호출 연결 키 · 잘림/JSON 오류 구분 · run_meta · 덮어쓰기 방지 (가짜 LLM, 토큰 0)
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from medical.config import MedicalConfig
from medical.experiment import run_experiment
from medical.llm import MAX_TOKENS, MockRoleLLM
from medical.report import cluster_bootstrap, diagnostics, percentile
from medical.session import FAIL_JSON, FAIL_OTHER, FAIL_TRUNCATED, extract, extract_diag


@pytest.fixture(scope="module")
def run(tmp_path_factory, data):
    out = tmp_path_factory.mktemp("med_instr")
    cfg = MedicalConfig(trials_per_cell=1, budget_B=4, mode="exploration")
    llm = MockRoleLLM()
    summary = run_experiment(cfg, llm, out, limit=3, store_limit=60, data=data, progress=lambda s: None)
    return out, summary, llm


def _turns(out: Path) -> list[dict]:
    return [json.loads(l) for l in (out / "턴기록.jsonl").read_text(encoding="utf-8").splitlines()]


def _valid(out: Path) -> list[dict]:
    return [t for t in _turns(out) if t.get("turn") is not None and not t.get("invalid_mutation")]


def test_turn0_has_sec_answer_in_every_arm(run):
    out, _, _ = run
    t0 = [t for t in _valid(out) if t["turn"] == 0]
    assert {t["arm"] for t in t0} == {"C0", "C1", "C1S"}
    for t in t0:
        assert t["sec_answer"] is not None and t["sec_target"] is not None and t["timing_shared_prefix"] is True
    # 턴 0 대상 AI·추출 시간은 갈래 간 같은 실측값
    by_tid: dict[str, set] = {}
    for t in t0:
        by_tid.setdefault(t["trial_id"], set()).add((t["sec_target"], t["sec_extract"] if t["arm"] != "C0" else t["sec_measure_extract"]))
    assert all(len(v) == 1 for v in by_tid.values())


def test_c0_excludes_measurement_extraction(run):
    out, _, _ = run
    c0 = [t for t in _valid(out) if t["arm"] == "C0"]
    assert c0
    for t in c0:
        assert t["sec_extract"] is None and t["sec_measure_extract"] is not None
        assert t["answer_path"] == "target+release"
        assert t["sec_answer"] == pytest.approx(t["sec_target"] + t["sec_release"], abs=2e-3)


def test_c1_deployed_path_sum(run):
    out, _, _ = run
    rs = [t for t in _valid(out) if t["arm"] in ("C1", "C1S")]
    assert rs
    for t in rs:
        assert t["sec_measure_extract"] is None and t["answer_path"] == "target+extract+release"
        assert t["sec_answer"] == pytest.approx(t["sec_target"] + t["sec_extract"] + t["sec_release"], abs=2e-3)


def test_ttft_not_fabricated(run):
    out, _, _ = run
    for t in _valid(out):
        assert t["sec_ttft"] is None and t["ttft_status"] == "NOT_OBSERVABLE_NON_STREAMING"


def test_extraction_calls_link_to_usage(run):
    out, _, llm = run
    usage = {u["call_id"]: u for u in (json.loads(l) for l in (out / "llm_usage.jsonl").read_text(encoding="utf-8").splitlines())}
    assert len(usage) == len(llm.usage)
    n = 0
    for t in _valid(out):
        for c in t["extraction_calls"]:
            u = usage[c["call_id"]]
            assert u["role"] == "extractor" and u["trial_id"] == t["trial_id"] and u["attempt"] == c["attempt"]
            assert u["turn"] == t["turn"] and u["arm"] == ("SHARED" if t["turn"] == 0 else t["arm"])
            assert {"output_tokens", "truncated", "parse_ok", "retry_count", "max_tokens", "failure_reason"} <= set(c)
            n += 1
        for a in t.get("release_attempts") or []:
            for c in a["extraction_calls"]:
                assert usage[c["call_id"]]["purpose"] == "verify" and usage[c["call_id"]]["arm"] == t["arm"]
    assert n > 0
    assert all(u["max_tokens"] == MAX_TOKENS[u["role"]] for u in usage.values())


@dataclass
class ScriptedLLM:
    """추출기 출력을 차례로 돌려준다. (text, truncated) 쌍."""
    script: list[tuple[str, Any]]
    usage: list[dict[str, Any]] = field(default_factory=list)
    tag: dict[str, Any] = field(default_factory=dict)

    def complete(self, role: str, system: str, messages: list[dict[str, str]], **kw: Any) -> str:
        text, tr = self.script[len(self.usage)]
        self.usage.append(dict(call_id=len(self.usage) + 1, role=role, output_tokens=10, truncated=tr, max_tokens=MAX_TOKENS[role], **self.tag))
        return text


def _ctx(llm: Any, retries: int = 2) -> Any:
    return SimpleNamespace(cfg=SimpleNamespace(max_extract_retries=retries), llm=llm)


def test_truncation_vs_json_error_classification():
    llm = ScriptedLLM([('[{"attribute": "AGE", "raw_va', True), ("이건 JSON이 아님", False), ("[{\"a\": 1", None)])
    obs, ok, n, calls = extract_diag(_ctx(llm), "q", "r", "[]", [])
    assert (ok, n) == (False, 3) and obs == []
    assert [c["failure_reason"] for c in calls] == [FAIL_TRUNCATED, FAIL_JSON, FAIL_OTHER]
    assert calls[0]["co_symptoms"] == [FAIL_JSON] and calls[1]["co_symptoms"] == []
    assert [c["attempt"] for c in calls] == [1, 2, 3] and [c["retry_count"] for c in calls] == [0, 1, 2]
    assert [c["call_id"] for c in calls] == [1, 2, 3]


def test_success_judgement_unchanged():
    # 성공 판정은 parse_json 그대로: 잘렸어도 파싱되면 성공 (truncated는 기록만)
    llm = ScriptedLLM([("[]", True)])
    obs, ok, n, calls = extract_diag(_ctx(llm), "q", "r", "[]", [])
    assert ok and n == 1 and calls[0]["parse_ok"] and calls[0]["failure_reason"] is None and calls[0]["truncated"] is True
    # 기존 3-튜플 인터페이스 유지
    assert extract(_ctx(ScriptedLLM([("x", False), ('[{"a":1}]', False)])), "q", "r", "[]", [])[1:] == (True, 2)


def test_run_meta_records_git_and_selection(run):
    out, summary, _ = run
    meta = json.loads((out / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["git_commit"] and meta["git_commit"] != "" and "git_branch" in meta and "git_dirty" in meta
    from medical.config import ROOT
    assert all((ROOT / f).exists() for f in meta["git_changed_files"])        # 경로 앞글자가 잘리지 않음
    assert meta["started_at"] and meta["run_summary"]["max_tokens"]["extractor"] == MAX_TOKENS["extractor"]
    sel = meta["trial_selection"]
    assert sel["selected"] == 3 and sel["limit"] == 3 and sel["planned"] == 6 * 1 and sel["turn_budget"] == 4
    assert {t["trial_id"] for t in summary["trials"]} == set(sel["trial_ids"])


def test_refuses_to_overwrite_existing_run(run, data):
    out, _, _ = run
    before = {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()}
    with pytest.raises(FileExistsError):
        run_experiment(MedicalConfig(trials_per_cell=1), MockRoleLLM(), out, limit=1, store_limit=60, data=data, progress=lambda s: None)
    assert {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()} == before


def test_diagnostics_tables(run):
    out, _, _ = run
    d = diagnostics(out)
    assert set(d["extraction"]["completion"]) == {"C0", "C1", "C1S"}
    for b in d["extraction"]["bounds"].values():
        assert b["best"]["violations"] <= b["deployed"]["violations"] <= b["worst"]["violations"]
    lat = d["latency"]["arms"]
    assert lat["C0"]["sec_answer"]["turn0_n"] > 0 and lat["C0"]["sec_ttft"]["n_valid"] == 0
    assert "sec_measure_extract" in lat["C0"] and "sec_measure_extract" not in lat["C1"]


def test_percentile_and_bootstrap():
    assert percentile([1, 2, 3, 4], 50) == 2.5 and percentile([], 50) is None
    assert cluster_bootstrap({"p1": [1.0, 2.0]}, 50) is None          # 환자 1명 → CI 만들지 않음
    lo, hi = cluster_bootstrap({"p1": [1.0], "p2": [3.0], "p3": [5.0]}, 50)
    assert lo <= hi
