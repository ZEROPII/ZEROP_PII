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


def test_prompt_addenda_are_inserted_once():
    from medical.prompts import PROMPTS, TARGET_ADDENDUM, EXTRACTOR_ADDENDUM
    assert PROMPTS["target_system"].count(TARGET_ADDENDUM) == 1 and PROMPTS["target_system"].endswith("{cases}")
    assert PROMPTS["extractor"].count(EXTRACTOR_ADDENDUM) == 1 and PROMPTS["extractor"].rstrip().endswith("{response}")


def test_client_role_llm_escalates_max_tokens_when_truncated():
    from types import SimpleNamespace
    from medical.llm import ESCALATE, MAX_TOKENS, ClientRoleLLM

    class FakeClient:
        def __init__(self):
            self.limits = []

        def chat(self, messages, *, system_prompt=None, max_tokens=None, temperature=None, model=None):
            self.limits.append(max_tokens)
            cut = len(self.limits) == 1
            return SimpleNamespace(text="[" if cut else "[]", model="m", input_tokens=1, output_tokens=1, latency_ms=1.0,
                                   attempts=1, truncated=cut)

    fc = FakeClient()
    llm = ClientRoleLLM(fc)
    assert llm.complete("extractor", "프롬프트", []) == "[]"
    assert fc.limits == [MAX_TOKENS["extractor"], ESCALATE["extractor"]]
    assert [u["truncated"] for u in llm.usage] == [True, False]
    fc2 = FakeClient()
    ClientRoleLLM(fc2).complete("mutator", "프롬프트", [])        # 변형기는 늘리지 않음
    assert fc2.limits == [MAX_TOKENS["mutator"]]


def test_case_ref_spacing_and_other_subject_with_case_ref_are_fixed(nz):
    resp = "사례 4 환자는 여성이고 Gingivitis 진단을 받았습니다."
    obs = [dict(attribute="DX", raw_value="Gingivitis", evidence_spans=["Gingivitis"], case_ref="사례 4", subject="OTHER",
                event_ref="e1", confidence=5, inference_mode="EXPLICIT"),
           dict(attribute="SEX", raw_value="여성", evidence_spans=["여성"], case_ref="[사례4]", subject="OTHER",
                confidence=5, inference_mode="EXPLICIT")]
    v = view_of(obs, resp, "여성 환자와 비슷한 사례가 있나요?", nz)
    assert v.case_refs == ["사례4"]
    norm = v.normalized["사례4"]
    assert norm[0]["subject"] == "TARGET_PATIENT"          # 답변에서 나온 값 → 사례 값으로 고침
    assert norm[1]["subject"] == "OTHER"                   # 질문에도 있는 값('여성') → 그대로
    assert [d["attribute"] for d in v.disclosures["사례4"]] == ["DX"]


def test_group_repair_splits_merged_events_and_keeps_true_groups(data, paths):
    from medical.bundle.kcalc import KCalc
    from medical.grouping import GroupRepairKC
    pid = "4d20edfc-aa1e-22b1-33a9-2fef32cf5c6d"
    kc = KCalc(paths.nodes, paths.events)
    rk = GroupRepairKC(kc)
    merged = [dict(attribute="DX", node_id="DX_SCT_66383009", event_group="c:e1"),
              dict(attribute="DX", node_id="DX_SCT_18718003", event_group="c:e1"),
              dict(attribute="PERIOD", node_id="PERIOD_CONDITION_START_DATE_DAY_2016-11-14", event_group="c:e1"),
              dict(attribute="MED", node_id="MED_RX_1535362", event_group="c:e5"),
              dict(attribute="PERIOD", node_id="PERIOD_MEDICATION_START_UTC_DAY_2016-11-21", event_group="c:e5"),
              dict(attribute="PERIOD", node_id="PERIOD_MEDICATION_END_UTC_DAY_2024-01-08", event_group="c:e5")]
    assert kc.k(merged)["k"] == 0                          # 두 진단·처방 두 번을 사건 하나로 묶으면 아무도 안 맞음
    r = rk.k(merged)
    assert r["k"] >= 1 and pid in rk.candidates(merged)
    assert sum(f.startswith("REGROUPED") for f in r["flags"]) == 2
    true_group = merged[3:5]                               # 실제 한 사건 (처방 + 그 시작일)
    assert rk.k(true_group)["k"] == kc.k(true_group)["k"] and not any(f.startswith("REGROUPED") for f in rk.k(true_group)["flags"])
    bogus = [dict(attribute="PERIOD", node_id="PERIOD_MEDICATION_START_UTC_DAY_2016-11-21", event_group=None),
             dict(attribute="SEX", node_id="SEX_FEMALE", event_group=None)]
    assert rk.k(bogus)["k"] == kc.k(bogus)["k"]
    assert len(rk.by_pat) == len(kc.by_pat)                # 나머지 속성은 그대로 넘김
