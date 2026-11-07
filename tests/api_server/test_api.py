# api_server 배선 확인 (가짜 LLM = medical.llm.MockRoleLLM, 토큰 0). 숫자 자체는 의미 없고, 연구 모듈이 실제로 불리는지·
# 결과가 화면 계약대로 옮겨지는지·사례끼리 섞이지 않는지만 본다.
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api_server.app import create_app
from api_server.engine import ApiSettings, ResearchWorkspace
from core.llm_client import LLMTransportError
from medical.data import MedicalData
from medical.llm import MockRoleLLM

QUESTIONS = ["이 환자의 성별은?", "거주지는?", "진단은?", "진단 시작일은?", "진단 당시 나이는?"]


@pytest.fixture(scope="module")
def data() -> MedicalData:
    return MedicalData()


def _client(tmp_path, data, arm="C1", llm=None):
    ws = ResearchWorkspace(ApiSettings(llm="dry-run", arm=arm, out=tmp_path), llm=llm or MockRoleLLM(), data=data)
    return TestClient(create_app(workspace_factory=lambda: ws)), ws


def _ask(c, case_id, q):
    sid = c.get(f"/api/cases/{case_id}/session").json()["sessionId"]
    r = c.post(f"/api/cases/{case_id}/messages", json=dict(sessionId=sid, question=q, clientMessageId=f"c-{q}"))
    return r


def _turns(ws):
    return [json.loads(l) for l in (ws.out / "턴기록.jsonl").read_text(encoding="utf-8").splitlines()]


@pytest.fixture(scope="module")
def c1(tmp_path_factory, data):
    c, ws = _client(tmp_path_factory.mktemp("api_c1"), data)
    responses = [_ask(c, "case-1", q).json() for q in QUESTIONS]
    return c, ws, responses


def test_question_runs_research_pipeline(c1):
    _, ws, responses = c1
    roles = [u["role"] for u in ws.ctx.llm.usage]
    assert roles.count("target") == len(QUESTIONS) and roles.count("extractor") >= len(QUESTIONS)
    turns = _turns(ws)
    assert [t["user_question"] for t in turns] == QUESTIONS
    assert all(t["query_text"] == f"사례1에 대한 질문: {t['user_question']}" for t in turns)   # 탭의 사례를 가리키는 앞말
    assert all(r["assistantMessage"]["protection"]["releaseMode"] == t["release_mode"] for r, t in zip(responses, turns))


def test_k_is_kcalc_of_committed_state_and_accumulates(c1):
    _, ws, responses = c1
    committed = ws.run.cases["사례1"].committed
    assert responses[-1]["riskState"]["k"] == ws.ctx.kc.k(committed)["k"] == ws.run.cases["사례1"].k_hist[-1]
    ks = [r["riskState"]["k"] for r in responses]
    assert all(b <= a for a, b in zip(ks, ks[1:]))                       # 공개는 지워지지 않으므로 k는 늘지 않는다
    assert [r["assistantMessage"]["protection"]["kAfter"] for r in responses[:-1]] == \
           [r["assistantMessage"]["protection"]["kBefore"] for r in responses[1:]]
    assert [r["riskState"]["version"] for r in responses] == list(range(2, 2 + len(QUESTIONS)))


def test_defender_decision_reaches_released_answer(c1):
    _, ws, responses = c1
    changed = [(r, t) for r, t in zip(responses, _turns(ws)) if t["release_changes"]]
    assert changed, "가짜 LLM 시나리오에서 Defender가 한 번은 바꿔야 한다 (거주지·날짜)"
    for r, t in changed:
        text = "".join(s["text"] for s in r["assistantMessage"]["segments"])
        assert text == t["response_text"] != t["raw_response_text"]          # 화면에는 공개 응답만
        for ch in t["release_changes"]:
            if ch["action"] == "suppress":
                assert ch["raw_value"] not in text
        acts = {x["action"] for x in r["assistantMessage"]["protection"]["transformations"]}
        assert acts - {"allow"}


def test_raw_and_source_data_never_leave_server(c1):
    c, ws, responses = c1
    blob = json.dumps(responses, ensure_ascii=False) + c.get("/api/cases?patientContextId=" + c.get("/api/patient-context").json()["contextId"]).text
    for t in _turns(ws):
        if t["raw_response_text"] != t["response_text"]:
            assert t["raw_response_text"] not in blob
    assert ws.prefix.query_patient not in blob
    for d in ws.prefix.docs:
        assert d["doc_id"] not in blob and d["text"][:40] not in blob


def test_messages_carry_engine_turn_and_history_values(c1):
    """의료진 화면 사례 노트는 공개 이력 turn(대화 전체 턴)과 질문을 engineTurn으로 잇는다. 가린 값은 value가 None."""
    c, ws, responses = c1
    assert [r["userMessage"]["engineTurn"] for r in responses] == list(range(1, len(QUESTIONS) + 1))
    assert all(r["assistantMessage"]["engineTurn"] == r["userMessage"]["engineTurn"] for r in responses)
    entries = c.get("/api/cases/case-1/disclosures").json()["entries"]
    assert entries and all("value" in e for e in entries)
    assert all(e["value"] is None for e in entries if e["action"] == "suppress")
    turns = {m["engineTurn"] for m in c.get("/api/cases/case-1/session").json()["messages"]}
    assert {e["turn"] for e in entries} <= turns


def test_cases_do_not_mix(tmp_path, data):
    c, ws = _client(tmp_path, data)
    p_ref = ws.ctx.p_ref
    _ask(c, "case-1", QUESTIONS[0])
    states = {s["caseId"]: s for s in c.get("/api/risk-states").json()}
    assert states["case-1"]["k"] < p_ref and all(states[f"case-{i}"]["k"] == p_ref for i in range(2, 6))
    # 가짜 대상 AI는 언제나 '사례1'로 답한다 → 사례 2 탭의 질문이어도 공개는 사례 1의 State로 간다
    r = _ask(c, "case-2", QUESTIONS[2]).json()
    assert r["riskState"]["caseId"] == "case-2" and r["riskState"]["k"] == p_ref and r["newDisclosures"] == []
    assert [x["caseId"] for x in r["relatedRiskStates"]] == ["case-1"]
    assert c.get("/api/cases/case-2/disclosures").json()["entries"] == []
    assert len(c.get("/api/cases/case-1/session").json()["messages"]) == 2
    assert len(c.get("/api/cases/case-2/session").json()["messages"]) == 2
    assert set(ws.run.cases) == {"사례1"}


def test_c0_releases_raw(tmp_path, data):
    c, ws = _client(tmp_path, data, arm="C0")
    for q in QUESTIONS:
        r = _ask(c, "case-1", q).json()
        assert r["assistantMessage"]["protection"]["releaseMode"] == "RAW"
        assert {x["action"] for x in r["assistantMessage"]["protection"]["transformations"]} <= {"allow"}
    assert c.get("/api/protection-policy").json()["arm"] == "C0"


class _FailingTarget(MockRoleLLM):
    def complete(self, role, system, messages, **kw):
        if role == "target":
            raise LLMTransportError("down")
        return super().complete(role, system, messages, **kw)


def test_llm_error_is_502_and_state_unchanged(tmp_path, data):
    c, ws = _client(tmp_path, data, llm=_FailingTarget())
    r = _ask(c, "case-1", QUESTIONS[0])
    assert r.status_code == 502
    assert ws.turn == 0 and ws.run.cases == {} and c.get("/api/cases/case-1/session").json()["messages"] == []
    assert c.get("/api/risk-states").json()[0]["version"] == 1


def test_errors_and_unsupported_preflight(tmp_path, data):
    c, ws = _client(tmp_path, data)
    assert c.post("/api/cases/case-1/messages", json=dict(sessionId="wrong", question="q", clientMessageId="x")).status_code == 409
    assert c.get("/api/cases/case-9/session").status_code == 404
    assert c.get("/api/cases?patientContextId=nope").status_code == 404
    sid = c.get("/api/cases/case-1/session").json()["sessionId"]
    pf = c.post("/api/cases/case-1/preflight", json=dict(sessionId=sid, question="나이는?")).json()
    assert pf["supported"] is False and pf["requiresWarning"] is False and pf["projectedK"] is None
    assert ws.ctx.llm.usage == []                                         # 사전 평가는 LLM·State를 건드리지 않는다
