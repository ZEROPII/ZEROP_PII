from __future__ import annotations

import hashlib
import random
from pathlib import Path

from medical.data import QUERY_POOL, STORE, split_cohort
from medical.documents import build_facts, check_doc, make_document, template_doc
from medical.retrieval import code_sets, fill_case_query, query_binding, retrieve, similarity
from medical.tracking import Case, commit_view, parse_json, view_of
from tests.medical.conftest import EXAMPLE_PID

ROOT = Path(__file__).resolve().parents[2]


def test_bundle_code_is_unchanged():
    readme = (ROOT / "medical" / "bundle" / "README.md").read_text(encoding="utf-8")
    for name in ("kcalc.py", "normalize_bridge.py", "seed_select.py", "check_rag_facts.py", "check_registry.py", "harness_reference.py"):
        digest = hashlib.sha256((ROOT / "medical" / "bundle" / name).read_bytes()).hexdigest()
        assert digest in readme, f"{name}가 전달 받은 원본과 다릅니다"


def test_split_is_reproducible_and_covers_all(data):
    a, b = split_cohort(data, 0.2, 20261009), split_cohort(data, 0.2, 20261009)
    assert a == b and len(a) == 576
    assert sum(1 for s in a.values() if s == QUERY_POOL) == round(576 * 0.2)
    assert set(a.values()) == {QUERY_POOL, STORE}


def test_example_patient_facts_match_bundle_example(data):
    facts = build_facts(data, EXAMPLE_PID)
    assert len(facts) == 107                       # 05_RAG문서/예시_문서_형식.txt의 F1~F107
    assert facts[1]["text"] == "Boston, Massachusetts" and facts[2]["text"] == "Polyp of colon"
    ok, body, rows, probs = check_doc(template_doc(facts), facts)
    assert ok and not probs and body.startswith("[임상 프로필]")
    assert all(r["attribute"] for r in rows)


def test_check_doc_rejects_unsupported_number_and_missing_facts(data):
    facts = build_facts(data, EXAMPLE_PID)
    ok, _, _, probs = check_doc(["[임상 프로필]", "[1] 여성, 2099년 진단. {F1}"], facts)
    assert not ok and any("근거 없는 숫자" in p for p in probs) and any("빠진 사실" in p for p in probs)


def test_llm_document_falls_back_to_template(data):
    d = make_document(data, EXAMPLE_PID, mode="llm", write=lambda facts: "엉터리 출력", max_retries=2)
    assert d["mode"] == "TEMPLATE_FALLBACK" and d["attempts"] == 2 and d["fact_rows"]


def test_retrieval_ranks_by_mean_jaccard_and_breaks_ties_by_id():
    q = {"DX": {"a"}, "MED": set(), "PROC": set()}
    store = {"p2": {"DX": {"a"}, "MED": set(), "PROC": set()}, "p1": {"DX": {"a"}, "MED": set(), "PROC": set()},
             "p3": {"DX": {"b"}, "MED": set(), "PROC": set()}}
    assert similarity(q, store["p1"]) == 1 / 3
    assert [p for p, _ in retrieve(q, store, 2)] == ["p1", "p2"]


def test_query_binding_uses_records_up_to_index_date(data):
    pid = next(p for p in data.patients() if query_binding(data, p, "PRESCRIPTION", random.Random(0)))
    b = query_binding(data, pid, "PRESCRIPTION", random.Random(0))
    assert set(b) >= {"QUERY_AGE_BAND", "QUERY_SEX", "QUERY_MAIN_DX", "QUERY_RELATED_ITEM", "index_date"}
    assert b["QUERY_AGE_BAND"].endswith("대") or b["QUERY_AGE_BAND"] == "10세 미만"
    before = code_sets(data.by_pat[pid], b["index_date"])
    full = code_sets(data.by_pat[pid])
    assert all(before[k] <= full[k] for k in before)
    assert "[" not in fill_case_query("[QUERY_AGE_BAND] [QUERY_SEX] [QUERY_MAIN_DX] 환자", b)


def test_parse_json_finds_array_in_prose():
    assert parse_json('설명 [{"a": 1}] 끝', "array") == [{"a": 1}]
    assert parse_json("[1, 2]", "array") is None
    assert parse_json('{"x": true}', "object") == {"x": True}


def test_view_renames_event_groups_per_case_and_commit_keeps_events(nz):
    resp = "사례1 환자는 Diabetes mellitus type 2 진단 당시 60세였습니다. 사례2 환자도 Diabetes mellitus type 2가 있었습니다."
    obs = [dict(attribute="DX", raw_value="Diabetes mellitus type 2", evidence_spans=["Diabetes mellitus type 2"], case_ref="사례1",
                subject="TARGET_PATIENT", event_ref="e1", confidence=5, inference_mode="EXPLICIT"),
           dict(attribute="AGE", raw_value="60세", evidence_spans=["60세"], case_ref="사례1", subject="TARGET_PATIENT", event_ref="e1",
                confidence=5, inference_mode="EXPLICIT"),
           dict(attribute="DX", raw_value="Diabetes mellitus type 2", evidence_spans=["Diabetes mellitus type 2"], case_ref="사례2",
                subject="TARGET_PATIENT", event_ref="e1", confidence=5, inference_mode="EXPLICIT"),
           dict(attribute="SEX", raw_value="여성", evidence_spans=["여성 환자"], case_ref="UNCLEAR", subject="TARGET_PATIENT")]
    v = view_of(obs, resp, "질문", nz)
    assert v.case_refs == ["사례1", "사례2"]
    assert {d["event_group"] for d in v.disclosures["사례1"]} == {"사례1:e1"}
    assert {d["event_group"] for d in v.disclosures["사례2"]} == {"사례2:e1"}
    assert "UNCLEAR" in v.normalized and "UNCLEAR" not in v.disclosures
    cases, order = {}, []
    commit_view(v, cases, order)
    assert order == ["사례1", "사례2"] and cases["사례1"].events["e1"].endswith("진단")
    assert len(cases["사례1"].committed) == 2
