"""scripts/measure_latency.py (발표 결과 ⑥: 한 턴 처리 시간 측정) 테스트.

결정적 응답기 실행과, 가짜 HTTP 세션 위의 실제 LLM 경로(ClientRoleLLM → LLMClient)를 짧게 돌려
산출물 · 단계 표시 · 시간 기록을 본다. 네트워크와 키는 쓰지 않는다.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ml = _load("measure_latency")
r3 = _load("verify_result3")

OUTPUTS = ("run_meta.json", "llm_usage.jsonl", "턴시간.jsonl", "턴기록.jsonl", "trial요약.json", "시간요약.md", "시간요약.json")


def _rows(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_percentile_is_linear():
    assert ml.pctl([], 0.95) is None
    assert ml.pctl([5.0], 0.95) == 5.0
    assert ml.pctl([1, 2, 3, 4], 0.5) == 2.5
    assert ml.pctl(list(range(1, 21)), 0.95) == pytest.approx(19.05)


@pytest.fixture(scope="module")
def oracle_run(tmp_path_factory):
    from webdemo.backend.review import RuleDefender
    before = RuleDefender.plan_case
    out = tmp_path_factory.mktemp("latency") / "oracle"
    assert ml.main(["--llm", "oracle", "--per-type", "1", "--budget", "2", "--out", str(out)]) == 0
    assert RuleDefender.plan_case is before                     # 끼운 시간 재기는 끝나면 되돌린다
    return out


def test_oracle_run_records_decision_time(oracle_run):
    out = oracle_run
    for f in OUTPUTS:
        assert (out / f).exists(), f
    m = json.loads((out / "run_meta.json").read_text(encoding="utf-8"))["measurement"]
    assert m["llm"] == "oracle" and m["finished_at"] and m["cpu"]["cpu_count"] and m["trials"] == 3
    turns = [t for t in _rows(out / "턴시간.jsonl") if t["kind"] == "turn"]
    assert {t["arm"] for t in turns} == {"C0", "C1"}
    assert max(t["turn"] for t in turns) <= 2
    assert not any(t["plan_calls"] for t in turns if t["arm"] == "C0")          # C0는 판정하지 않는다
    assert any(t["plan_calls"] and t["decide_ms"] > 0 for t in turns if t["arm"] == "C1")
    for t in turns:
        assert t["total_ms"] >= t["decide_ms"]
    s = json.loads((out / "시간요약.json").read_text(encoding="utf-8"))
    assert s["decide"]["C1"]["n"] >= 1


def test_real_llm_path_tags_phases(tmp_path, monkeypatch):
    """가짜 HTTP 위의 실제 LLM 경로: 단계(answer · extract · rewrite · recheck) 표시, wall ≥ latency, 키는 남기지 않음."""
    import core.config as cc
    import core.llm_client as lc
    from tests.medicloak.fake_anthropic import FakeAnthropic

    key = "sk-test-NOT-A-REAL-KEY-91c2"
    fake = FakeAnthropic(delay=0.01)
    monkeypatch.setattr(cc, "get_settings", lambda env_file=None: cc.Settings.from_env(dict(
        LLM_API_KEY=key, LLM_API_BASE="https://llm.example.invalid", LLM_MODEL="fake-model-1", LLM_MAX_RETRIES="1")))
    orig = lc.LLMClient
    monkeypatch.setattr(lc, "LLMClient", lambda s, **kw: orig(s, session=fake, sleep=lambda _: None, **kw))
    out = tmp_path / "real"
    assert ml.main(["--per-type", "1", "--budget", "1", "--out", str(out)]) == 0
    usage = _rows(out / "llm_usage.jsonl")
    assert {"answer", "extract", "rewrite", "recheck"} <= {u["phase"] for u in usage}
    assert all(u["role"] == "extractor" for u in usage if u["phase"] in ("extract", "recheck"))
    assert all(u["model"] == "fake-model-1" for u in usage if u.get("latency_ms") is not None)
    walls = [u for u in usage if u.get("wall_ms") is not None and u.get("latency_ms") is not None]
    assert walls and all(u["wall_ms"] + 1 >= u["latency_ms"] for u in walls)
    m = json.loads((out / "run_meta.json").read_text(encoding="utf-8"))["measurement"]
    assert m["models_configured"]["target"] == "fake-model-1" and m["answer_style"].startswith("short-")
    for f in OUTPUTS:
        assert key not in (out / f).read_text(encoding="utf-8"), f
    assert "대상 AI 답" in (out / "시간요약.md").read_text(encoding="utf-8")


def test_verify_result3_counts_decisions(oracle_run, tmp_path):
    """결과 ③ 세기: 판정 수 = 턴기록의 판정 수, C0는 판정 없이 나간 단서만, 위반은 trial 기록과 일치."""
    js = tmp_path / "r3.json"
    assert r3.main([str(oracle_run), "--turns", "3", "--json", str(js)]) == 0
    res = json.loads(js.read_text(encoding="utf-8"))
    n_dec = sum(len(p["decisions"]) for r in _rows(oracle_run / "턴기록.jsonl") if r["arm"] == "C1" and r["turn"] <= 2
                for p in r.get("release_plans") or [])
    c1 = res["arms"]["C1"]
    assert c1["decisions"]["privacy"]["n"] + c1["decisions"]["medical"]["n"] == n_dec
    assert res["arms"]["C0"]["decisions"]["privacy"]["n"] == 0 and sum(res["arms"]["C0"]["c0_released"].values()) > 0
    for arm in ("C0", "C1"):
        assert res["arms"][arm]["agree_with_trial_record"] == res["arms"][arm]["n"]
    assert res["raw_check"].get("다름", 0) == 0
