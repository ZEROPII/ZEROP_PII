# RAG 기준 재측정 도구 (요청서 2026-11-05 R2 · R3 · R4 · R5 · R6): 가짜 HTTP 위의 실제 LLM 경로로 끝까지 한 번 돈다 (토큰 0).
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _rows(p: Path) -> list[dict]:
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def test_rag_remeasure_pipeline_on_fake_llm(tmp_path, monkeypatch):
    import core.config
    import core.llm_client
    from core.config import Settings
    from tests.medicloak.fake_anthropic import FakeAnthropic

    fake = FakeAnthropic()
    st = Settings.from_env(dict(LLM_API_KEY="sk-test-not-a-real-key", LLM_API_BASE="https://llm.example.invalid", LLM_MODEL="fake-model-1",
                                LLM_MAX_RETRIES="1"))
    Real = core.llm_client.LLMClient
    monkeypatch.setattr(core.config, "get_settings", lambda env_file=None: st)
    monkeypatch.setattr(core.llm_client, "LLMClient", lambda s: Real(s, session=fake, sleep=lambda _: None))
    # 가짜 HTTP는 변형기 · 검사기 답을 흉내 내지 않는다 ('확인'): 질문 만들기만 Seed 문장 그대로 (말투마다 끝말을 달리)
    import medical.attack
    monkeypatch.setattr(medical.attack, "realize", lambda llm, cfg, seed_text, qi, objective, scenario, subject, op, role, sent:
                        (seed_text if op == "M1" else f"{seed_text} ({op} 말투로 다시)", [dict(text=seed_text, structural=[], semantic=None)]))
    import rag_postcalc
    import rag_remeasure
    import rag_retrieval_dump
    import rag_truth_verifier

    # R2: 검색 덤프 + 층화 추출 (LLM 0)
    r2 = tmp_path / "r2"
    assert rag_retrieval_dump.main(["--out", str(r2), "--sample", "6"]) == 0
    summ = json.loads((r2 / "요약.json").read_text(encoding="utf-8"))
    assert summ["pool"] == 115 and summ["valid_combos"] == 296 and summ["queries_used"] == 114
    assert summ["population"] == 227 and len(summ["not_eligible"]) == 1
    targets = _rows(r2 / "r4_targets.csv")
    assert len(targets) == 6 and all(t["query_patient"] and t["query_type"] for t in targets)
    assert "r4_targets.csv  sha256" in (r2 / "사전등록.txt").read_text(encoding="utf-8")
    dump = _rows(r2 / "retrieval_dump.csv")
    assert {(d["query_patient"], d["query_type"]) for d in dump if d["store_patient_id"] == targets[0]["target_patient"]}

    # R3 · R4: 대상 고정 · 반복(온도) · 질문 계획 · 로그 확장
    out = tmp_path / "r4"
    assert rag_remeasure.main(["--target-patient", str(r2 / "r4_targets.csv"), "--limit", "2", "--repeat", "2", "--temperatures", "0,0.7",
                               "--arms", "C0,C1", "--out", str(out)]) == 0
    target_calls = [c["payload"] for c in fake.calls if "[검색된 사례]" in (c["payload"].get("system") or "")]
    other_calls = [c["payload"] for c in fake.calls if "[검색된 사례]" not in (c["payload"].get("system") or "")]
    assert {p.get("temperature") for p in target_calls} == {0.0, 0.7}
    assert {p.get("temperature") for p in other_calls} <= {0.0}                    # 대상 AI만 온도를 바꾼다
    trials = [json.loads(x) for x in (out / "trials.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(trials) == 2 * 2 * 2
    used = {r["trial_id"]: r for r in _rows(out / "targets_used.csv")}
    for t in trials:
        assert t["case_A"] == t["target_ref"] == used[t["trial_id"]]["target_ref"]
        assert t["temperature"] == (0.0 if t["repeat"] == 0 else 0.7)
    recs = [json.loads(x) for x in (out / "턴기록.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    turns = [r for r in recs if r.get("turn") is not None]
    assert turns and all(len(r["exposed"]) == 5 and {"rank", "patient_id", "k", "committed"} <= set(r["exposed"][0]) for r in turns)
    assert {"RETRIEVAL", "F", "P", "S", "D"} <= {r.get("attack_family") for r in turns}
    assert any(r.get("derived") == "duration" for r in turns)
    meta = json.loads((out / "run_meta.json").read_text(encoding="utf-8"))["measurement"]
    assert meta["targets_sha256"] and meta["repeat"] == 2 and "LiveLLM" in meta["extraction_fix"]
    assert sum(1 for x in (out / "검색시간.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()) >= 4

    # 사후 계산 · 원본 대조
    assert rag_postcalc.main([str(out)]) == 0
    s = json.loads((out / "postcalc" / "summary.json").read_text(encoding="utf-8"))
    assert set(s["arms"]) == {"C0", "C1"} and s["arms"]["C1"]["conversations"]["n"] == 4 and s["arms"]["C1"]["targets"]["n"] == 2
    assert s["timing"]["검색"]["n"] >= 4 and "by_kind" in s["failures"]
    assert rag_truth_verifier.main([str(out)]) == 0
    t = json.loads((out / "truth" / "truth_summary.json").read_text(encoding="utf-8"))
    assert set(t["arms"]) == {"C0", "C1"} and (out / "truth" / "검수시트.csv").exists()

    # R6: 대화 분할 (R4 기록의 C1 · 반복 0 질문을 다시 묻는다) + C1G(공개 원장)
    r6 = tmp_path / "r6"
    assert rag_remeasure.main(["--split-from", str(out), "--split-top", "1", "--split-m", "1,2", "--arms", "C1,C1G", "--out", str(r6)]) == 0
    t6 = [json.loads(x) for x in (r6 / "trials.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(t6) == (1 + 2) * 2 and {x["m"] for x in t6} == {1, 2} and {x["account"] for x in t6 if x["m"] == 2} == {"A", "B"}
    q = [r["query_text"] for r in (json.loads(x) for x in (r6 / "턴기록.jsonl").read_text(encoding="utf-8").splitlines() if x.strip())
         if r.get("turn") and r["arm"] == "C1" and r.get("m") == 1]
    src = [r["query_text"] for r in turns if r["arm"] == "C1" and r["repeat"] == 0 and r["turn"] >= 1 and r["trial_id"] == t6[0]["trial_id"].split("-m")[0]]
    assert q == src                                                                    # 같은 공격 질문을 그대로 다시
    assert rag_postcalc.main([str(r6), "--split"]) == 0
    sp = json.loads((r6 / "postcalc" / "summary.json").read_text(encoding="utf-8"))["split"]["table"]
    assert set(sp) == {"C1", "C1G"} and set(sp["C1"]) == {"1", "2"}
