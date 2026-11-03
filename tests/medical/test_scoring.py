# medical/scoring: 팀 고정본 채점 파일이 바뀌지 않았는지, 채점 스크립트가 실행 기록 위에서 끝까지 도는지 (가짜 LLM, 숫자 의미 없음)
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from medical.config import ROOT, MedicalConfig
from medical.experiment import run_experiment
from medical.llm import MockRoleLLM

SCORING = ROOT / "medical" / "scoring"
FROZEN = SCORING / "frozen"


def test_frozen_files_match_hashes():
    lines = [ln.split() for ln in (FROZEN / "고정본_해시.txt").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert {name for _, name in lines} == {"extract_eval_v4.py", "extractor_recall.py", "normalize_bridge_v0.11.2.patch"}
    for digest, name in lines:
        assert hashlib.sha256((FROZEN / name).read_bytes()).hexdigest() == digest, f"{name}은 고정본이라 고치면 안 됩니다"


@pytest.fixture(scope="module")
def dry_run(tmp_path_factory, data):
    out = tmp_path_factory.mktemp("scoring_dry")
    cfg = MedicalConfig(trials_per_cell=1, budget_B=3, rule_extract=True)
    run_experiment(cfg, MockRoleLLM(), out, limit=2, store_limit=60, data=data, progress=lambda s: None)
    return out


def _run(*args: str) -> str:
    env = dict(os.environ, PYTHONHASHSEED="0")
    p = subprocess.run([sys.executable, *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    assert p.returncode == 0, p.stderr[-2000:]
    return p.stdout


def test_scoring_scripts_run(dry_run, tmp_path):
    recall = str(FROZEN / "extractor_recall.py")
    out = _run(str(FROZEN / "extract_eval_v4.py"), str(dry_run), recall)
    assert out.startswith("평가 trial 2개") and "4 + 나열 귀속" in out
    out = _run(str(SCORING / "check_committed_recall.py"), str(dry_run), recall)
    assert "확정 재현율" in out
    out = _run(str(SCORING / "miss_breakdown.py"), str(dry_run))
    assert "[1] trial별" in out and "[4] 확정 값 정밀도" in out
    v1 = tmp_path / "v1"
    assert "다시 처리 (v1)" in _run(str(SCORING / "reprocess.py"), str(dry_run), str(v1), "--code", "v1")
    assert _run(str(FROZEN / "extract_eval_v4.py"), str(v1), recall).startswith("평가 trial 2개")
    assert "결론" in _run(str(SCORING / "check_same_extractor.py"), str(dry_run), str(v1))
    assert _run(str(SCORING / "risk_decision_f1.py"), str(dry_run), "--arm", "C1")
    assert "전체" in _run(str(SCORING / "llm_latency.py"), str(dry_run))


def test_patient_lists_grow_in_order():
    import json

    sets = [{t["query_patient"] for t in json.loads((SCORING / "patients" / f"before_holdout_{i}.json").read_text(encoding="utf-8"))["trials"]}
            for i in (1, 2, 3)]
    assert sets[0] < sets[1] < sets[2]
