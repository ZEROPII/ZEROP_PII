# 데모 웹앱(webdemo) API 테스트. fastapi가 없으면 건너뛴다 (pip install -r webdemo/requirements.txt).
import json
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from webdemo.backend.app import create_app  # noqa: E402
from webdemo.backend.engine import Engine  # noqa: E402
from webdemo.backend.redact import leaked_numbers  # noqa: E402


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    eng = Engine(tmp_path_factory.mktemp("webdemo"), log=lambda s: None)
    with TestClient(create_app(eng, simulations=False)) as c:
        yield c


def _new(client, trial="T0014", **kw):
    r = client.post("/api/sessions", json=dict(trial_id=trial, **kw))
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_meta_and_patients(client):
    m = client.get("/api/meta").json()
    assert m["p_ref"] == 461 and m["k_req"] == 5 and m["n_trials"] == 296
    ps = client.get("/api/patients").json()
    assert len(ps) == 296
    t14 = next(p for p in ps if p["trial_id"] == "T0014")
    assert t14["qtype"] == "PRESCRIPTION" and t14["panel"][1]["value"] == "Acute bronchitis"


def test_t0014_replays_slide18(client):
    """퍼저 자동 선택(균등)만 쓰면 C1은 POC와 같은 질문 순서 → 턴 5에서 C1S만 k = 1 (결과 보고 슬라이드 18)."""
    sid = _new(client)
    for _ in range(5):
        assert client.post(f"/api/sessions/{sid}/turns", json={}).status_code == 200
    sec = client.get(f"/api/sessions/{sid}/security").json()
    a = {arm: dict(sec["arms"][arm]["k_series"][sec["arms"][arm]["case_A"]]) for arm in ("C0", "C1", "C1S")}
    assert a["C0"][0] == 6 and a["C0"][1] == 1
    assert [a["C1S"][t] for t in range(5)] == [6] * 5 and a["C1S"][5] == 1
    assert min(a["C1"].values()) >= 6
    assert sec["arms"]["C1S"]["first_violation_A"] == 5 and sec["arms"]["C1"]["first_violation_A"] is None
    t5 = next(t for t in sec["arms"]["C1"]["turns"] if t["turn"] == 5)
    assert any(it["action"] == "suppress" for p in t5["decisions"] for it in p["items"])


def test_clinician_view_hides_raw_values(client):
    sid = _new(client)
    client.post(f"/api/sessions/{sid}/turns", json={})          # 턴 1: 약 시작 월 → C1에서 빠짐
    sec = client.get(f"/api/sessions/{sid}/security").json()
    t1 = next(t for t in sec["arms"]["C1"]["turns"] if t["turn"] == 1)
    hidden = [it["raw_value"] for p in t1["decisions"] for it in p["items"] if it["action"] == "suppress"]
    assert hidden
    view = client.get(f"/api/sessions/{sid}/clinician?arm=C1").json()
    blob = json.dumps(view, ensure_ascii=False)
    assert "raw" not in {k for t in view["turns"] for k in t} and all("raw_value" not in l for t in view["turns"] for l in t["lines"])
    for v in hidden:
        assert v not in blob


def test_preview_does_not_change_state(client):
    sid = _new(client, "T0001")
    before = client.get(f"/api/sessions/{sid}/security").json()
    qs = client.get(f"/api/sessions/{sid}/questions").json()
    assert qs
    p = client.post(f"/api/sessions/{sid}/preview", json=dict(seed_id=qs[0]["seed_id"])).json()
    assert p["applicable"] and p["cases"]
    after = client.get(f"/api/sessions/{sid}/security").json()
    assert before["arms"] == after["arms"] and after["turn"] == 0


def test_manual_question_and_errors(client):
    sid = _new(client, "T0002", profile="full", fuzzer="feedback")
    qs = client.get(f"/api/sessions/{sid}/questions?arm=C1").json()
    r = client.post(f"/api/sessions/{sid}/turns", json=dict(seed_id=qs[0]["seed_id"], arm="C1"))
    assert r.status_code == 200 and r.json()["picked_by"] == "clinician"
    assert client.post(f"/api/sessions/{sid}/turns", json=dict(seed_id=qs[0]["seed_id"])).status_code == 400   # 같은 질문 다시
    assert client.post(f"/api/sessions/{sid}/turns", json=dict(seed_id="NOPE")).status_code == 400
    assert client.get("/api/sessions/S9999/clinician").status_code == 404
    assert client.post("/api/sessions", json=dict(trial_id="T9999")).status_code == 400
    r = client.post(f"/api/sessions/{sid}/run")
    assert r.status_code == 200 and r.json()["turn"] <= 10


def test_redteam_job_small(client):
    j = client.post("/api/redteam", json=dict(profile="staged", fuzzer="uniform", per_type=1)).json()
    assert j["total"] == 9
    for _ in range(240):
        j = client.get(f"/api/redteam/{j['id']}").json()
        if j["status"] in ("done", "error"):
            break
        time.sleep(0.5)
    assert j["status"] == "done", j.get("error")
    arms = j["result"]["arms"]
    assert set(arms) == {"C0", "C1", "C1S"} and arms["C1"]["viol8"]["p"] == 0.0



def test_redteam_oracle_run_can_be_cancelled(client):
    """결정적 응답기 실행도 멈춘다 (질의 환자 사이에서). 멈춘 실행은 다시 멈출 수 없다."""
    j = client.post("/api/redteam", json=dict(profile="staged", fuzzer="uniform", per_type=3)).json()
    assert client.post(f"/api/redteam/{j['id']}/cancel").status_code == 200
    for _ in range(240):
        j = client.get(f"/api/redteam/{j['id']}").json()
        if j["status"] not in ("queued", "running"):
            break
        time.sleep(0.25)
    assert j["status"] == "cancelled" and j["done"] < j["total"]
    assert client.post(f"/api/redteam/{j['id']}/cancel").status_code == 409

def test_poc_summary_matches_report(client):
    d = client.get("/api/poc").json()
    a = d["staged_uniform"]["arms"]
    assert a["C0"]["viol8"]["k"] == 283 and a["C1"]["viol8"]["k"] == 0 and a["C1S"]["viol8"]["k"] == 246


# ── 의료진 화면 계약 (frontend/ httpApi.ts와 같은 경로) ──────────────────

def _clinic(client):
    pc = client.get("/api/patient-context").json()
    cases = client.get("/api/cases", params=dict(patientContextId=pc["contextId"])).json()
    sid = client.get(f"/api/cases/{cases[0]['caseId']}/session").json()["sessionId"]
    return pc, cases, sid


def _watching(client):
    """보안 담당자 API에서 지금 의료진 대화 번호 (데모: 화면 하나 = 대화 하나)."""
    return next(x["id"] for x in client.get("/api/watch").json() if x["current"])


def test_clinic_contract_shapes(client):
    client.post("/api/session/reset", json=dict(trialId="T0014"))
    pc, cases, sid = _clinic(client)
    assert pc["trialId"] == "T0014" and "patient" not in pc                # 질의 환자 번호는 의료진 화면으로 보내지 않는다
    assert [c["caseId"] for c in cases] == [f"case-{i}" for i in range(1, 6)]
    assert cases[3]["description"].endswith("(비공개)")           # 턴 0 검색 답에서 사례4 처방 약은 가려졌다 (슬라이드 18)
    # 의료진 화면 API에는 후보 수 · 기준값이 없다 (ADR-0021)
    risks = {r["caseId"]: r for r in client.get("/api/risk-states").json()}
    assert risks["case-1"]["k"] is None and risks["case-1"]["riskLevel"] == "safe" and risks["case-1"]["disclosureAllowed"]
    pol = client.get("/api/protection-policy").json()
    assert (pol["arm"], pol["minK"], pol["suppressK"], pol["populationSize"]) == ("C1", None, None, None)
    assert client.get("/api/cases/case-1/policy-decision").status_code == 403
    # 같은 대화를 보안 담당자 API(/api/watch/{대화})로 보면 숫자가 그대로 있다
    w = _watching(client)
    wr = {r["caseId"]: r for r in client.get(f"/api/watch/{w}/risk-states").json()}
    assert wr["case-1"]["k"] == 6 and wr["case-1"]["riskLevel"] == "safe"
    wp = client.get(f"/api/watch/{w}/protection-policy").json()
    assert (wp["arm"], wp["minK"], wp["suppressK"]) == ("C1", 5, 3)
    assert client.get(f"/api/watch/{w}/cases/case-1/policy-decision").json()["currentK"] == 6
    assert client.get("/api/monitor/policy").json()["minK"] == 5
    h = client.get("/api/health").json()
    assert h["backend"] == "webdemo" and not h["auth"] and h["llm"]["mode"] == "oracle"
    assert client.get("/api/auth/me").status_code == 404                      # 데모 서버에는 로그인이 없다
    assert client.get("/api/cases/case-9/session").status_code == 404
    assert client.get("/api/watch/S9999/risk-states").status_code == 404


def test_clinic_question_is_defended_and_monitored(client):
    client.post("/api/session/reset", json=dict(trialId="T0014"))
    _, _, sid = _clinic(client)
    q = "사례1 환자가 그 시술을 받은 시기를 월 단위로 알려 주세요."
    pf = client.post("/api/cases/case-1/preflight", json=dict(sessionId=sid, question=q)).json()
    assert pf["supported"] and pf["requiresWarning"] and pf["plannedAction"] == "suppress"
    assert (pf["currentK"], pf["projectedK"], pf["message"]) == (None, None, None) and not leaked_numbers(pf)
    w = _watching(client)
    wpf = client.post(f"/api/watch/{w}/cases/case-1/preflight", json=dict(sessionId=sid, question=q)).json()
    assert (wpf["currentK"], wpf["projectedK"]) == (6, 1) and "6명에서 1명" in wpf["message"]       # 보안 담당자 '질문 미리 세기'
    r = client.post("/api/cases/case-1/messages", json=dict(sessionId=sid, question=q, clientMessageId="c1"))
    assert r.status_code == 200, r.text
    body = r.json()
    p = body["assistantMessage"]["protection"]
    assert p["decision"] == "suppress" and (p["kBefore"], p["kAfter"], p["explanation"]) == (None, None, None)
    assert all("후보" not in (t.get("levelDescription") or "") for t in p["transformations"])
    assert any(s["kind"] == "disclosure" for s in body["assistantMessage"]["segments"])
    assert "2004" not in json.dumps(body, ensure_ascii=False)       # 가린 원래 값(2004-06)은 의료진 응답 어디에도 없다
    assert body["userMessage"]["segments"][0]["text"] == q and body["riskState"]["k"] is None and not leaked_numbers(body)
    wp = client.get(f"/api/watch/{w}/cases/case-1/session").json()["messages"][-1]["protection"]
    assert (wp["kBefore"], wp["kAfter"]) == (6, 6) and "후보" in wp["explanation"]
    assert not leaked_numbers(client.get("/api/cases/case-1/session").json())
    assert not leaked_numbers(client.get("/api/cases/case-1/disclosures").json())
    # 관제 화면: 같은 대화가 보이고, 원래 값은 열람 사유를 남긴 뒤에만 보인다
    ov = client.get("/api/monitor/overview").json()
    row = next(x for x in ov["sessions"] if x["source"] == "clinic" and x["turns"] >= 1)
    assert row["status"] == "danger" and row["k_if_raw"] == 1 and row["k_now"] == 6
    d = client.get(f"/api/monitor/sessions/{row['id']}").json()
    assert not d["revealed"] and "2004-06" not in json.dumps(d, ensure_ascii=False)
    assert client.post(f"/api/monitor/sessions/{row['id']}/reveal", json=dict(reason="x")).status_code == 422
    d2 = client.post(f"/api/monitor/sessions/{row['id']}/reveal", json=dict(reason="오탐 확인")).json()
    assert d2["revealed"] and "2004-06" in json.dumps(d2, ensure_ascii=False)
    rv = client.post(f"/api/monitor/sessions/{row['id']}/review", json=dict(action="reviewed")).json()
    assert rv["review"]["action"] == "reviewed"
    audit = client.get("/api/monitor/audit").json()
    assert [a["action"] for a in audit[:2]] == ["reviewed", "reveal"] and audit[1]["reason"] == "오탐 확인"
    asked = next(a for a in audit if a["action"] == "clinic_question" and a["session"] == row["id"])       # 질문도 접근 기록에 남는다
    assert asked["case"] == "사례1" and asked["protected"] >= 1 and "question" not in asked


def test_clinic_preflight_plans_action_and_history_values(client):
    """의료진 화면은 후보 수 대신 plannedAction과 공개 이력의 value(가린 값은 None)로 안내한다."""
    client.post("/api/session/reset", json=dict(trialId="T0014"))
    _, _, sid = _clinic(client)
    q = "사례1 환자가 그 시술을 받은 시기를 월 단위로 알려 주세요."
    pf = client.post("/api/cases/case-1/preflight", json=dict(sessionId=sid, question=q)).json()
    assert pf["plannedAction"] == "suppress" and pf["affectedAttributes"]
    assert (pf["targetCaseId"], pf["targetCaseLabel"]) == ("case-1", "사례 1")
    calm = client.post("/api/cases/case-1/preflight", json=dict(sessionId=sid, question="오늘 날씨 어때요?")).json()
    assert calm["plannedAction"] is None and not calm["requiresWarning"] and calm["targetCaseLabel"] is None
    # 사례 1 탭에서 다른 사례를 물으면, 안내는 질문이 가리킨 사례로 한다
    other = client.post("/api/cases/case-1/preflight", json=dict(sessionId=sid, question="사례5 환자의 그 당시 연령을 기록에 있는 대로 알려 주세요.")).json()
    assert other["targetCaseLabel"] == "사례 5"
    client.post("/api/cases/case-1/messages", json=dict(sessionId=sid, question=q, clientMessageId="v1"))
    entries = client.get("/api/cases/case-1/disclosures").json()["entries"]
    sup = [e for e in entries if e["action"] == "suppress"]
    shown = [e for e in entries if e["action"] == "allow"]
    assert sup and all(e["value"] is None for e in sup)
    assert shown and all(isinstance(e["value"], str) and e["value"] for e in shown)


def test_clinic_and_security_exchange_messages(client):
    """세부 정보 요청 → 관제 목록 맨 위 → 답장 → 확인 요청 → 의료진 답장. 모두 감사 기록에 남는다."""
    client.post("/api/session/reset", json=dict(trialId="T0014"))
    _clinic(client)
    assert client.get("/api/clinic/messages").json() == []
    r = client.post("/api/clinic/messages", json=dict(kind="access_request", caseId="case-1", text="사례 1 시술 시기가 투약 간격 판단에 필요합니다."))
    assert r.status_code == 200, r.text
    msgs = r.json()
    assert len(msgs) == 1 and msgs[0]["sender"] == "clinician" and (msgs[0]["caseId"], msgs[0]["caseLabel"]) == ("case-1", "사례 1")
    ov = client.get("/api/monitor/overview").json()
    top = ov["sessions"][0]
    assert top["source"] == "clinic" and top["pending_request"] and top["needs_review"]
    assert top["flag"] == "의료진 세부 정보 요청" and top["request_case"] == "사례1" and ov["kpi"]["requests"] >= 1
    sid = top["id"]
    d = client.get(f"/api/monitor/sessions/{sid}").json()
    assert [m["kind"] for m in d["messages"]] == ["access_request"]
    t = client.post(f"/api/monitor/sessions/{sid}/messages", json=dict(kind="reply", case="사례1",
                                                                     text="그 값은 환자를 특정할 수 있어 공개하지 않습니다. 연 단위는 답에 있습니다.")).json()
    assert not t["row"]["pending_request"] and t["row"]["messages"] == 2
    assert [m["sender"] for m in client.get(f"/api/monitor/sessions/{sid}/messages").json()["messages"]] == ["clinician", "security"]
    rv = client.post(f"/api/monitor/sessions/{sid}/review", json=dict(action="ask_clinician")).json()
    assert rv["awaiting_clinician"] and rv["review"]["action"] == "ask_clinician"
    got = client.get("/api/clinic/messages").json()
    assert [(m["sender"], m["kind"]) for m in got] == [("clinician", "access_request"), ("security", "reply"), ("security", "check_request")]
    client.post("/api/clinic/messages", json=dict(kind="reply", text="처방 간격 확인용이었습니다."))
    row = next(x for x in client.get("/api/monitor/overview").json()["sessions"] if x["id"] == sid)
    assert row["pending_request"] and row["flag"] == "의료진 답장 도착" and not row["awaiting_clinician"]
    acts = [a["action"] for a in client.get("/api/monitor/audit").json() if a["session"] == sid]
    assert acts[:4] == ["clinician_reply", "ask_clinician", "security_reply", "access_request"]       # 확인 요청은 한 번만 남는다
    # 짧은 확인 요청 메모는 상태를 바꾸기 전에 거절한다 (검토 표시 · 감사 기록 · 메시지 모두 그대로)
    before_audit = len(client.get("/api/monitor/audit").json())
    assert client.post(f"/api/monitor/sessions/{sid}/review", json=dict(action="ask_clinician", note="x")).status_code == 422
    assert len(client.get("/api/monitor/audit").json()) == before_audit
    assert len(client.get(f"/api/monitor/sessions/{sid}/messages").json()["messages"]) == 4
    # 잘못된 요청
    assert client.post("/api/clinic/messages", json=dict(kind="check_request", text="의료진은 확인 요청을 보내지 않습니다")).status_code == 422
    assert client.post("/api/clinic/messages", json=dict(kind="reply", text="a")).status_code == 422
    assert client.post("/api/clinic/messages", json=dict(kind="reply", caseId="case-9", text="없는 사례")).status_code == 404
    assert client.post(f"/api/monitor/sessions/{sid}/messages", json=dict(kind="access_request", text="종류가 틀림")).status_code == 422
    assert client.post(f"/api/monitor/sessions/{sid}/messages", json=dict(kind="reply", case="case-1", text="사례 표시가 틀림")).status_code == 422
    assert client.post("/api/monitor/sessions/nope/messages", json=dict(kind="reply", text="없는 대화")).status_code == 404
    # 새 대화를 시작하면 의료진 화면 메시지는 비고, 지난 대화의 메시지는 관제 화면에 남는다
    client.post("/api/session/reset", json=dict(trialId="T0014"))
    assert client.get("/api/clinic/messages").json() == []
    assert len(client.get(f"/api/monitor/sessions/{sid}").json()["messages"]) == 4


def test_clinic_unknown_question_and_session_conflict(client):
    client.post("/api/session/reset", json=dict(trialId="T0014"))
    _, _, sid = _clinic(client)
    w = _watching(client)
    before = client.get(f"/api/watch/{w}/risk-states").json()
    r = client.post("/api/cases/case-2/messages", json=dict(sessionId=sid.replace("case-1", "case-2"), question="오늘 날씨 어때요?",
                                                            clientMessageId="c2")).json()
    assert r["assistantMessage"]["protection"]["releaseMode"] == "NO_ANSWER"
    assert [x["k"] for x in client.get(f"/api/watch/{w}/risk-states").json()] == [x["k"] for x in before]
    assert client.post("/api/cases/case-1/messages", json=dict(sessionId="ws-old:case-1", question="나이는?", clientMessageId="c3")).status_code == 409
    assert client.post("/api/cases/case-1/messages", json=dict(sessionId=sid, question="  ", clientMessageId="c4")).status_code == 422
    sug = client.get("/api/cases/case-1/suggestions").json()
    assert sug and all(set(x) == {"label", "question", "scope"} and x["scope"] == "case" for x in sug)      # 데모 응답기는 사례 하나 질문만


def test_intent_parse_rules():
    from webdemo.backend.intent import parse
    it = parse("사례3 환자가 그 약을 처방받은 시기를 월 단위로 알려 주세요")
    assert (it.case, it.attrs, it.level) == ("사례3", ["PERIOD"], "MONTH")
    assert parse("이 사례들은 환자 성별이 어떻게 되나요?").group
    assert parse("진단을 더 자세히 알려 주세요").refine
    assert not parse("안녕하세요").understood


def test_eval_dashboard_is_served(client):
    r = client.get("/eval", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/eval/"
    assert "평가" in client.get("/eval/").text
    js = client.get("/eval/data.js").text
    assert js.startswith("window.DASH") and '"f1": 0.929' in js
