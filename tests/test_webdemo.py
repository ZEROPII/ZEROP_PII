# 데모 웹앱(webdemo) API 테스트. fastapi가 없으면 건너뛴다 (pip install -r webdemo/requirements.txt).
import json
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from webdemo.backend.app import create_app  # noqa: E402
from webdemo.backend.engine import Engine  # noqa: E402


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    eng = Engine(tmp_path_factory.mktemp("webdemo"), log=lambda s: None)
    with TestClient(create_app(eng)) as c:
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


def test_poc_summary_matches_report(client):
    d = client.get("/api/poc").json()
    a = d["staged_uniform"]["arms"]
    assert a["C0"]["viol8"]["k"] == 283 and a["C1"]["viol8"]["k"] == 0 and a["C1S"]["viol8"]["k"] == 246
