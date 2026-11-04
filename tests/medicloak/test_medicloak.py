# MediCloak 운영 모드 테스트 (python -m medicloak): 로그인 · 역할 · 가상 EMR · 실제 LLM 경로 · 숫자 없는 의료진 API · 영속화
#
# 실제 LLM 경로는 진짜 키 대신 가짜 HTTP 세션(fake_anthropic.FakeAnthropic)을 core.llm_client.LLMClient에 끼워
# ClientRoleLLM → LLMClient → HTTP 요청 · 응답 해석까지 그대로 돌린다 (네트워크 없음).
import json
import os
import stat
import threading
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from core.config import Settings  # noqa: E402
from core.llm_client import LLMClient  # noqa: E402
from medical.config import MedicalConfig  # noqa: E402
from medical.llm import ClientRoleLLM  # noqa: E402
from tests.medicloak.fake_anthropic import FakeAnthropic  # noqa: E402
from webdemo.backend import emr, redact  # noqa: E402
from webdemo.backend.app import Product, create_app  # noqa: E402
from webdemo.backend.auth import COOKIE, ensure_demo_accounts, hash_password, token_hash, verify_password  # noqa: E402
from webdemo.backend.engine import Engine  # noqa: E402
from webdemo.backend.persist import Persist  # noqa: E402
from webdemo.backend.store import Store  # noqa: E402

PW = "pw-test-1234"
KEY = "sk-test-NOT-A-REAL-KEY-7f3a"
Q_DRUG = "이 환자에게 쓴 약과 시작 시기를 알려 주세요"


def fake_llm(fake: FakeAnthropic) -> ClientRoleLLM:
    s = Settings.from_env(dict(LLM_API_KEY=KEY, LLM_API_BASE="https://llm.example.invalid", LLM_MODEL="fake-model-1", LLM_MAX_RETRIES="1"))
    cfg = MedicalConfig(mode="exploration")
    return ClientRoleLLM(LLMClient(s, session=fake, sleep=lambda _: None), models=dict(cfg.models), temperature=cfg.temperature)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """DB(가상 EMR · 데모 계정) + 엔진(가짜 HTTP 위의 실제 LLM 경로) + 운영 모드 앱."""
    w = tmp_path_factory.mktemp("medicloak")
    store = Store(w / "mc.db")
    emr.load_csv(store, log=lambda s: None)
    ensure_demo_accounts(store, PW, w / "accounts.txt")
    paths = emr.export_csv(store, w / "snap", log=lambda s: None)
    fake = FakeAnthropic()
    eng = Engine(w / "engine", log=lambda s: None, paths=paths, live_llm=fake_llm(fake), live_label="실제 LLM (fake-model-1)",
                 first_id=Persist(store, None).next_id())
    app = create_app(eng, simulations=False, product=Product(store=store))
    base = TestClient(app)
    base.__enter__()                    # lifespan 한 번 (다른 클라이언트는 쿠키만 따로)
    yield dict(dir=w, store=store, fake=fake, eng=eng, app=app, paths=paths)
    base.__exit__(None, None, None)


def login(world, username: str) -> TestClient:
    c = TestClient(world["app"])
    r = c.post("/api/auth/login", json=dict(username=username, password=PW))
    assert r.status_code == 200, r.text
    return c


def launch(c: TestClient, trial: str = "T0014", purpose: str = "PRESCRIPTION") -> tuple[dict, str]:
    wl = c.get("/api/emr/worklist").json()
    row = next(x for x in wl if any(p["trialId"] == trial for p in x["purposes"]))
    r = c.post("/api/emr/launch", json=dict(fhirId=row["fhirId"], purpose=purpose))
    assert r.status_code == 200, r.text
    assert r.json()["trialId"] == trial
    sid = c.get("/api/cases/case-1/session").json()["sessionId"]
    return row, sid


def current_conv(sec: TestClient, owner: str) -> str:
    return next(x["id"] for x in sec.get("/api/watch").json() if x["current"] and x["owner"] == owner)


# ── 로그인 · 역할 ──────────────────────────────────────────

def test_login_cookie_and_role_separation(world):
    anon = TestClient(world["app"])
    assert anon.get("/api/workspace").status_code == 401
    assert anon.get("/api/monitor/overview").status_code == 401
    assert anon.get("/fhir/Patient").status_code == 401
    h = anon.get("/api/health").json()
    assert h["auth"] and h["backend"] == "medicloak" and h["llm"]["mode"] == "live" and KEY not in json.dumps(h)
    assert anon.get("/api/auth/me").status_code == 401
    assert anon.post("/api/auth/login", json=dict(username="doctor1", password="wrong-password")).status_code == 401
    assert anon.post("/api/auth/login", json=dict(username="nobody", password="wrong-password")).status_code == 401

    r = anon.post("/api/auth/login", json=dict(username="doctor1", password=PW))
    assert r.status_code == 200 and r.json()["user"]["role"] == "clinician" and r.json()["user"]["displayName"] == "김서연"
    cookie = r.headers["set-cookie"]
    assert f"{COOKIE}=" in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    token = anon.cookies.get(COOKIE)
    st = world["store"]
    assert st.one("SELECT 1 FROM auth_session WHERE token_hash = ?", (token_hash(token),)) is not None      # 토큰은 해시로만
    assert st.one("SELECT 1 FROM auth_session WHERE token_hash = ?", (token,)) is None
    u = st.user_by_name("doctor1")
    assert PW not in (u["pw_hash"] + u["pw_salt"]) and verify_password(PW, u["pw_salt"], u["pw_hash"])
    assert anon.get("/api/auth/me").json()["user"]["username"] == "doctor1"
    # 의료진은 관제 · 의료진 대화 분석 · 레드팀을 못 쓴다
    for path in ("/api/monitor/overview", "/api/watch", "/api/poc", "/api/redteam", "/api/sessions", "/eval/"):
        assert anon.get(path).status_code == 403, path
    # 보안 담당자는 의료진 화면 API · EMR을 못 쓴다
    sec = login(world, "privacy1")
    for path in ("/api/workspace", "/api/risk-states", "/api/emr/worklist", "/fhir/Patient", "/api/clinic/messages"):
        assert sec.get(path).status_code == 403, path
    assert sec.get("/api/monitor/overview").status_code == 200
    # 로그아웃하면 쿠키 세션이 지워진다
    assert anon.post("/api/auth/logout").status_code == 200
    assert st.one("SELECT 1 FROM auth_session WHERE token_hash = ?", (token_hash(token),)) is None
    assert anon.get("/api/workspace").status_code == 401
    audit = sec.get("/api/monitor/audit").json()
    acts = [(a["action"], a["actor"]) for a in audit]
    assert ("logout", "김서연 (의료진 · doctor1)") in acts and ("login_failed", "doctor1 (로그인 시도)") in acts
    assert ("login_failed", "없는 아이디 (로그인 시도)") in acts            # 없는 아이디는 입력값을 남기지 않는다
    assert "nobody" not in json.dumps(audit, ensure_ascii=False) and "wrong-password" not in json.dumps(audit, ensure_ascii=False)


def test_login_is_rate_limited(world):
    from webdemo.backend.auth import add_user
    add_user(world["store"], "locktest", "잠금 시험", "clinician", None, PW)
    c = TestClient(world["app"])
    for _ in range(5):
        assert c.post("/api/auth/login", json=dict(username="locktest", password="nope-nope")).status_code == 401
    r = c.post("/api/auth/login", json=dict(username="locktest", password=PW))          # 맞는 비밀번호도 잠시 막는다
    assert r.status_code == 429 and "분 뒤" in r.json()["detail"]
    assert login(world, "doctor2").get("/api/auth/me").status_code == 200              # 다른 계정은 그대로 들어온다


def test_login_limit_holds_under_parallel_attempts(world):
    """시도를 비밀번호 확인 전에 세므로, 한꺼번에 보내도 한도(5번)를 넘겨 확인받지 못한다."""
    from concurrent.futures import ThreadPoolExecutor
    from webdemo.backend.auth import add_user
    add_user(world["store"], "racetest", "동시 시험", "clinician", None, PW)

    def attempt(_):
        return TestClient(world["app"]).post("/api/auth/login", json=dict(username="racetest", password="nope-nope")).status_code

    with ThreadPoolExecutor(16) as ex:
        codes = list(ex.map(attempt, range(16)))
    assert codes.count(401) <= 5 and codes.count(429) >= 11, codes


def test_access_rules_hold_under_root_path(world):
    """하위 경로 프록시 · uvicorn --root-path 뒤에서도 역할 검사가 빗나가지 않는다 (라우팅과 같은 경로로 검사)."""
    c = TestClient(world["app"], root_path="/mc")
    for path in ("/mc/api/monitor/audit", "/mc/api/sessions", "/mc/api/monitor/overview", "/mc/api/workspace", "/mc/fhir/Patient"):
        assert c.get(path).status_code == 401, path
    assert c.get("/mc/api/health").status_code == 200
    assert c.post("/mc/api/auth/login", json=dict(username="privacy1", password=PW)).status_code == 200
    assert c.get("/mc/api/monitor/overview").status_code == 200 and c.get("/mc/api/workspace").status_code == 403
    for path in ("/docs", "/openapi.json", "/redoc"):                     # 운영 모드에서는 API 문서를 열지 않는다 (화면 파일로 넘어감)
        r = TestClient(world["app"]).get(path)
        assert "application/json" not in r.headers.get("content-type", "") and '"openapi"' not in r.text and "swagger" not in r.text.lower()


def test_legacy_session_routes_refuse_clinic_conversations(world):
    """세션 직접 조작 경로로는 의료진 대화의 원문을 읽거나 질문을 더할 수 없다 (열람 사유 · 감사 기록을 건너뛰므로)."""
    doc = login(world, "doctor2")
    launch(doc, "T0037")
    sec = login(world, "privacy1")
    sid = current_conv(sec, "박준호")
    for method, path in (("get", f"/api/sessions/{sid}/security"), ("get", f"/api/sessions/{sid}/clinician?arm=C0"),
                         ("get", f"/api/sessions/{sid}/questions"), ("post", f"/api/sessions/{sid}/run"),
                         ("post", f"/api/sessions/{sid}/turns")):
        r = getattr(sec, method)(path, **({"json": {}} if method == "post" else {}))
        assert r.status_code == 403, (path, r.status_code)
    assert all(x["source"] != "clinic" for x in sec.get("/api/sessions").json())
    assert sec.get(f"/api/monitor/sessions/{sid}").json()["turn"] == 0       # 대화는 그대로


def test_password_hashing():
    salt, h = hash_password("correct horse")
    assert len(salt) == 32 and len(h) == 64
    assert verify_password("correct horse", salt, h) and not verify_password("correct horsf", salt, h)
    assert hash_password("correct horse")[1] != h                     # salt가 다르면 해시도 다르다


# ── 가상 EMR · FHIR ───────────────────────────────────────

def test_fhir_exposes_outpatients_only(world):
    doc = login(world, "doctor1")
    meta = doc.get("/fhir/metadata")
    assert meta.headers["content-type"].startswith("application/fhir+json") and meta.json()["fhirVersion"] == "4.0.1"
    b = doc.get("/fhir/Patient", params=dict(_count=5)).json()
    assert b["resourceType"] == "Bundle" and b["total"] == 115 and len(b["entry"]) == 5
    p = b["entry"][0]["resource"]
    assert p["meta"]["tag"][0]["code"] == "outpatient" and len(p["birthDate"]) == 4          # 생년은 연도만
    conds = doc.get("/fhir/Condition", params=dict(patient=p["id"])).json()
    assert conds["total"] >= 1 and conds["entry"][0]["resource"]["subject"]["reference"] == f"Patient/{p['id']}"
    meds = doc.get("/fhir/MedicationRequest", params=dict(patient=f"Patient/{p['id']}")).json()
    assert all(e["resource"]["resourceType"] == "MedicationRequest" for e in meds["entry"])
    # 유사 사례 검색 대상(과거 기록) 환자는 FHIR로 열 수 없다
    store_pid = world["store"].one("SELECT fhir_id FROM emr_patient WHERE cohort != 'QUERY_POOL'")["fhir_id"]
    r = doc.get(f"/fhir/Patient/{store_pid}")
    assert r.status_code == 404 and r.json()["resourceType"] == "OperationOutcome"
    assert doc.get("/fhir/Condition", params=dict(patient=store_pid)).status_code == 404
    assert doc.get("/fhir/Condition").status_code == 400
    assert doc.get("/fhir/Observation", params=dict(patient=p["id"])).status_code == 404


def test_db_snapshot_matches_source_csv(world):
    """위험 계산 엔진은 DB에서 내보낸 스냅숏을 읽는다. 원자료 CSV와 같은 데이터여야 한다."""
    from medical.data import MedicalData
    a, b = MedicalData(world["paths"]), MedicalData()
    assert set(a.N) == set(b.N) and len(a.by_pat) == len(b.by_pat) == 576
    assert sum(len(v) for v in a.by_pat.values()) == sum(len(v) for v in b.by_pat.values()) == 51759
    assert world["eng"].ctx["staged"].p_ref == 461


def test_worklist_and_launch(world):
    doc = login(world, "doctor1")
    wl = doc.get("/api/emr/worklist").json()
    assert len(wl) >= 100 and all(x["purposes"] for x in wl) and wl[0]["featured"]
    assert {"trialId", "purpose", "purposeLabel", "visitDate", "mainDx", "item"} <= set(wl[0]["purposes"][0])
    row, _ = launch(doc, "T0014")
    pc = doc.get("/api/patient-context").json()
    assert pc["trialId"] == "T0014" and pc["primaryDiagnosis"] == "Acute bronchitis"
    assert doc.post("/api/emr/launch", json=dict(fhirId=row["fhirId"], purpose="NOPE")).status_code == 404
    assert doc.post("/api/emr/launch", json=dict(fhirId="not-a-patient", purpose="PRESCRIPTION")).status_code == 404
    assert doc.get("/api/clinic/patients").status_code == 404                # 데모 환자 목록은 운영 모드에 없다
    sec = login(world, "privacy1")
    a = next(x for x in sec.get("/api/monitor/audit").json() if x["action"] == "emr_launch")
    assert a["actor"].startswith("김서연") and a["purpose"] == "PRESCRIPTION" and a["trial"] == "T0014"


# ── 실제 LLM 경로 (가짜 HTTP) ─────────────────────────────

def test_real_llm_question_is_defended_and_redacted(world):
    fake: FakeAnthropic = world["fake"]
    doc = login(world, "doctor1")
    _, sid = launch(doc, "T0014")
    pf = doc.post("/api/cases/case-1/preflight", json=dict(sessionId=sid, question=Q_DRUG)).json()
    assert pf["currentK"] is None and not redact.leaked_numbers(pf)
    n0 = len(fake.calls)
    r = doc.post("/api/cases/case-1/messages", json=dict(sessionId=sid, question=Q_DRUG, clientMessageId="q1"))
    assert r.status_code == 200, r.text
    body = r.json()
    calls = fake.calls[n0:]
    target = calls[0]
    assert target["headers"]["x-api-key"] == KEY and target["url"].startswith("https://llm.example.invalid")
    p = target["payload"]
    assert p["model"] == "fake-model-1" and p["temperature"] == 0.0 and "[검색된 사례]" in p["system"]
    assert p["messages"][-1]["content"] == f"사례1에 대한 질문: {Q_DRUG}"          # 고른 사례를 가리키도록 앞에 붙인다
    assert len(p["messages"]) == 3                                              # 턴 0 사례 검색 질문 · 답 + 이번 질문
    assert fake.roles()[n0:n0 + 4] == ["target", "extractor", "rewriter", "extractor"]
    prot = body["assistantMessage"]["protection"]
    assert prot["releaseMode"] == "REWRITTEN" and prot["decision"] == "suppress"
    acts = {t["attribute"]: t["action"] for t in prot["transformations"]}
    assert acts == {"MED": "allow", "PERIOD": "suppress"}
    text = "".join(s["text"] for s in body["assistantMessage"]["segments"])
    assert "loratadine" in text and "2004-06-16" not in json.dumps(body, ensure_ascii=False)     # 시작일(후보 1명)은 빠졌다
    assert not redact.leaked_numbers(body) and prot["explanation"] is None
    usage = world["eng"].live_usage()
    assert usage["by_role"]["target"]["input_tokens"] >= 120
    # 보안 담당자: 같은 대화를 숫자와 원 응답(열람 뒤)으로 본다
    sec = login(world, "privacy1")
    w = current_conv(sec, "김서연")
    assert world["eng"].wait_compare(20)
    wp = sec.get(f"/api/watch/{w}/cases/case-1/session").json()["messages"][-1]["protection"]
    assert (wp["kBefore"], wp["kAfter"]) == (6, 6)
    d = sec.get(f"/api/monitor/sessions/{w}").json()
    assert {a: s["status"] for a, s in d["steps"][-1]["arms"].items()} == dict(C0="ANSWERED", C1="ANSWERED", C1S="ANSWERED")
    t1 = d["arms"]["C1"]["turns"][-1]
    assert t1["raw"] is None and all(ln.get("text") is None for ln in t1["raw_lines"])          # 열람 전: 원 응답 없음
    assert t1["change_notes"] == [dict(case="사례1", changes=[dict(attribute="시점", change="suppress")], k_if_raw=1, k_now=6)]
    assert d["arms"]["C0"]["turns"][-1]["released"] is None
    assert d["arms"]["C0"]["k_series"]["사례1"][-1] == [1, 1]                                    # 방어 없었다면 후보 1명
    d2 = sec.post(f"/api/monitor/sessions/{w}/reveal", json=dict(reason="실제 LLM 답 확인")).json()
    assert "2004-06-16" in d2["arms"]["C1"]["turns"][-1]["raw"]
    row = next(x for x in sec.get("/api/monitor/overview").json()["sessions"] if x["id"] == w)
    assert row["owner"] == "김서연" and row["llm_mode"] == "live" and row["status"] == "danger" and row["last_question"] == Q_DRUG
    # 원 응답이 든 턴 기록은 DB에만 (C1S는 뒤에서 계산한 뒤 저장)
    recs = {a: world["store"].turns_of(w, a) for a in ("C0", "C1", "C1S")}
    assert [r["turn"] for r in recs["C1"]] == [0, 1] and "2004-06-16" in recs["C1"][1]["raw_response_text"]
    assert [r["turn"] for r in recs["C1S"]] == [0, 1]


def test_clinic_api_has_no_risk_numbers(world):
    doc = login(world, "doctor1")
    _, sid = launch(doc, "T0010")
    doc.post("/api/cases/case-2/messages", json=dict(sessionId=sid.replace("case-1", "case-2"), question=Q_DRUG, clientMessageId="n1"))
    pc = doc.get("/api/patient-context").json()
    got = [doc.get(p).json() for p in ("/api/workspace", "/api/protection-policy", "/api/risk-states", "/api/cases/case-2/session",
                                       "/api/cases/case-2/disclosures", "/api/clinic/history")]
    got.append(doc.get("/api/cases", params=dict(patientContextId=pc["contextId"])).json())
    got.append(doc.post("/api/cases/case-2/preflight", json=dict(sessionId=sid.replace("case-1", "case-2"), question="사례2 나이는?")).json())
    for g in got:
        assert not redact.leaked_numbers(g), g
        assert "후보" not in json.dumps(g, ensure_ascii=False)
    assert doc.get("/api/cases/case-2/policy-decision").status_code == 403
    # 실제 LLM 서버: 질문 뜻을 못 찾아도 '묻는 항목을 찾지 못함'으로 막지 않는다 (보내면 서버가 판정)
    pf = doc.post("/api/cases/case-1/preflight", json=dict(sessionId=sid, question="이 사례에서 눈여겨볼 점이 있나요?")).json()
    assert pf["supported"] is False


def test_llm_error_returns_502_and_keeps_state(world, tmp_path):
    bad = FakeAnthropic(fail_status=401)
    eng = world["eng"]
    good = eng.live_llm.inner
    eng.live_llm.inner = fake_llm(bad)                    # 같은 엔진에서 키 오류만 흉내 낸다
    try:
        doc = login(world, "doctor2")
        _, sid = launch(doc, "T0024")
        before = doc.get("/api/cases/case-1/session").json()
        r = doc.post("/api/cases/case-1/messages", json=dict(sessionId=sid, question=Q_DRUG, clientMessageId="e1"))
        assert r.status_code == 502 and "LLMHTTPError" in r.json()["detail"] and KEY not in r.text
        assert doc.get("/api/cases/case-1/session").json() == before
        sec = login(world, "privacy1")
        w = current_conv(sec, "박준호")
        assert sec.get(f"/api/monitor/sessions/{w}").json()["turn"] == 0
        assert len(bad.calls) == 1                        # 401은 다시 시도하지 않는다
    finally:
        eng.live_llm.inner = good


def test_two_clinicians_keep_separate_conversations(world):
    d1, d2 = login(world, "doctor1"), login(world, "doctor2")
    launch(d1, "T0036")
    launch(d2, "T0005")
    assert d1.get("/api/patient-context").json()["trialId"] == "T0036"
    assert d2.get("/api/patient-context").json()["trialId"] == "T0005"
    d1.post("/api/clinic/messages", json=dict(kind="access_request", caseId="case-1", text="사례 1 투약 기간이 진료에 필요합니다."))
    assert len(d1.get("/api/clinic/messages").json()) == 1 and d2.get("/api/clinic/messages").json() == []
    sec = login(world, "privacy1")
    lst = sec.get("/api/watch").json()
    owners = {x["owner"] for x in lst if x["current"]}
    assert {"김서연", "박준호"} <= owners
    top = sec.get("/api/monitor/overview").json()["sessions"][0]
    assert top["pending_request"] and top["owner"] == "김서연"
    t = sec.post(f"/api/monitor/sessions/{top['id']}/messages", json=dict(kind="reply", case="사례1", text="연 단위까지 공개됩니다."))
    assert [m["actor"] for m in t.json()["messages"]] == ["김서연 (의료진 · doctor1)", "이하늘 (보안 담당자 · privacy1)"]
    assert [m["sender"] for m in d1.get("/api/clinic/messages").json()] == ["clinician", "security"]
    hist = d1.get("/api/clinic/history").json()
    assert hist[0]["current"] and hist[0]["trialId"] == "T0036" and len(hist) >= 2


def test_llm_wait_does_not_block_other_requests(world):
    """한 의료진의 질문이 LLM 답을 기다리는 동안에도 관제 화면 요청은 바로 돈다 (LiveLLM이 엔진 잠금을 푼다)."""
    eng = world["eng"]
    slow = FakeAnthropic(delay=0.4)
    good = eng.live_llm.inner
    eng.live_llm.inner = fake_llm(slow)
    try:
        doc = login(world, "doctor1")
        _, sid = launch(doc, "T0016")
        sec = login(world, "privacy1")
        done = {}

        def ask():
            done["r"] = doc.post("/api/cases/case-1/messages", json=dict(sessionId=sid, question=Q_DRUG, clientMessageId="s1"))

        th = threading.Thread(target=ask)
        th.start()
        time.sleep(0.15)
        t0 = time.time()
        assert sec.get("/api/monitor/overview").status_code == 200
        took = time.time() - t0
        th.join(30)
        assert done["r"].status_code == 200, done["r"].text
        assert took < 0.35, took                           # LLM 한 번(0.4초)을 기다리지 않았다
        assert eng.wait_compare(30) and slow.max_active == 1
    finally:
        eng.live_llm.inner = good


# ── 영속화 · 다시 켜기 ────────────────────────────────────

def test_restart_keeps_records_read_only(world):
    st, eng0 = world["store"], world["eng"]
    eng0.wait_compare(30)
    sec0 = login(world, "privacy1")
    old_ids = {x["id"] for x in sec0.get("/api/watch").json() if x["turns"]}
    assert old_ids
    last_audit = sec0.get("/api/monitor/audit").json()[0]["id"]
    # 같은 DB로 서버를 새로 켠다
    eng = Engine(world["dir"] / "engine2", log=lambda s: None, paths=world["paths"], live_llm=fake_llm(FakeAnthropic()),
                 live_label="실제 LLM (fake-model-1)", first_id=Persist(st, None).next_id())
    app = create_app(eng, simulations=False, product=Product(store=st))
    with TestClient(app):
        sec = TestClient(app)
        sec.post("/api/auth/login", json=dict(username="privacy1", password=PW))
        rows = {x["id"]: x for x in sec.get("/api/monitor/overview").json()["sessions"]}
        assert old_ids <= set(rows) and all(rows[i]["archived"] for i in old_ids)
        sid = sorted(old_ids)[0]
        d = sec.get(f"/api/monitor/sessions/{sid}").json()
        assert d["archived"] and not d["revealed"] and d["arms"]["C1"]["turns"][-1]["raw"] is None
        assert sec.get(f"/api/watch/{sid}/risk-states").json()[0]["k"] is not None          # 숫자 그대로 (스냅숏)
        assert sec.post(f"/api/monitor/sessions/{sid}/messages", json=dict(kind="reply", text="지난 대화 답장")).status_code == 409
        rv = sec.post(f"/api/monitor/sessions/{sid}/review", json=dict(action="reviewed", note="다시 켠 뒤 확인"))
        assert rv.status_code == 200 and rv.json()["review"]["actor"].startswith("이하늘")
        audit = sec.get("/api/monitor/audit").json()
        assert int(audit[0]["id"][1:]) > int(last_audit[1:])                                  # 감사 번호가 이어진다
        assert any(a["id"] == last_audit for a in audit)                                      # 지난 기록도 남아 있다
        doc = TestClient(app)
        doc.post("/api/auth/login", json=dict(username="doctor1", password=PW))
        _, new_sid = launch(doc, "T0001")
        cur = next(x["id"] for x in sec.get("/api/watch").json() if x["current"] and x["owner"] == "김서연")
        assert int(cur[1:]) > max(int(i[1:]) for i in old_ids)                               # 대화 번호도 이어진다
        hist = doc.get("/api/clinic/history").json()
        assert hist[0]["current"] and any(h["archived"] for h in hist)
    assert st.conversation(sid)["review"]["note"] == "다시 켠 뒤 확인"


# ── 숫자 지우기 · 명령줄 ──────────────────────────────────

def test_redact_unit():
    r = redact.risk(dict(caseId="case-1", k=2, riskLevel="danger", statusLabel="위험", disclosureAllowed=False, policyDecision="restrict",
                         version=3, updatedAt="t"))
    assert r["k"] is None and r["riskLevel"] == "caution" and r["statusLabel"] == "세부 정보 제한"
    e = redact.entry(dict(entryId="d", turn=1, attribute="PERIOD", attributeLabel="시기", action="suppress", description="가림 (그대로면 후보 1명)",
                          value=None))
    assert e["description"] == "비공개" and e["value"] is None
    g = redact.entry(dict(entryId="d", turn=1, attribute="AGE", attributeLabel="나이", action="generalize", description="넓은 범주로 바꿔 공개: 10대",
                          value="10대"))
    assert g["description"] == "범위로 공개: 10대"
    assert redact.leaked_numbers(dict(a=[dict(k=3)], b=dict(kAfter=None))) == ["a[0].k"]


def test_cli_init_users_and_check_llm(tmp_path, capsys):
    from medicloak.cli import main
    from webdemo.backend.live import check_llm, make_live_llm
    db = tmp_path / "x" / "mc.db"
    main(["--db", str(db), "init", "--demo-password", "abcd-efgh-1234"])
    out = capsys.readouterr().out
    acc = db.parent / "demo_accounts.txt"
    assert "doctor1" in out and "privacy1" in out and acc.exists()
    assert stat.S_IMODE(os.stat(acc).st_mode) == 0o600
    main(["--db", str(db), "init"])                                       # 두 번째는 그대로 둔다
    assert "이미 들어 있습니다" in capsys.readouterr().out
    main(["--db", str(db), "users"])
    assert "보안 담당자" in capsys.readouterr().out
    # .env 확인: 키 값은 어디에도 출력하지 않는다
    env = tmp_path / "t.env"
    env.write_text(f"LLM_API_KEY={KEY}\nLLM_API_BASE=https://llm.example.invalid\nLLM_MODEL=fake-model-1\n", encoding="utf-8")
    lines: list[str] = []
    assert check_llm(str(env), send=False, out=lines.append)
    assert KEY not in "\n".join(lines) and any("llm_api_key_set = True" in ln for ln in lines)
    llm, label = make_live_llm("real", MedicalConfig(), str(env))
    assert isinstance(llm, ClientRoleLLM) and label == "실제 LLM (fake-model-1)"
    empty = tmp_path / "empty.env"
    empty.write_text("LLM_API_KEY=\n", encoding="utf-8")
    lines.clear()
    saved = {k: os.environ.pop(k) for k in ("LLM_API_KEY", "LLM_API_BASE", "LLM_MODEL") if k in os.environ}
    try:
        assert not check_llm(str(empty), send=False, out=lines.append)
    finally:
        os.environ.update(saved)
    assert "LLM_API_KEY" in lines[0]


def test_eviction_keeps_conversation_when_save_fails(world):
    """메모리에서 내리기 전 저장이 실패하면 대화를 그대로 두고 요청은 끝까지 돈다. 비교 갈래 계산이 남은 대화는 내리지 않는다."""
    from webdemo.backend.clinic import ClinicDesk
    calls = []

    def bad(conv):
        calls.append(conv.id)
        raise OSError("disk full")

    desk = ClinicDesk(world["eng"], "T0014", keep=1, on_evict=bad)
    first = desk.current
    desk.start("T0010")                                   # 저장 실패: 예외 없이 새 대화로 바뀌고, 지난 대화는 메모리에 남는다
    assert desk.current.session.trial_id == "T0010" and first.id in desk.history and calls == [first.id]
    assert first.id in world["eng"].sessions
    first.session.compare_pending = 1                     # 뒤에서 계산할 비교 갈래가 남은 대화
    done = []
    desk.on_evict = lambda conv: done.append(conv.id)
    desk.start("T0024")
    assert first.id in desk.history and first.id not in done          # 비교 갈래가 끝날 때까지 둔다
    first.session.compare_pending = 0
    desk.start("T0036")
    assert first.id in done and first.id not in desk.history and len(desk.history) == 1


def test_session_idle_timeout_and_inactive_account(world):
    from webdemo.backend.auth import Auth, add_user
    st = world["store"]
    add_user(st, "idletest", "유휴 시험", "security", None, PW)
    a = Auth(st, idle=60)
    token, _ = a.login("idletest", PW)
    assert a.user_of(token)["username"] == "idletest"
    st.x("UPDATE auth_session SET last_seen = last_seen - 3600 WHERE token_hash = ?", (token_hash(token),))
    assert a.user_of(token) is None                       # 60초 넘게 쓰지 않은 세션은 끝남
    st.x("UPDATE app_user SET active = 0 WHERE username = 'idletest'")
    assert a.login("idletest", PW) is None                # 쓰지 않는 계정은 맞는 비밀번호로도 못 들어온다
