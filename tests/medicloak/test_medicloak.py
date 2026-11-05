# MediCloak 운영 모드 테스트 (python -m medicloak): 로그인 · 역할 · 가상 EMR · 실제 LLM 경로 · 숫자 없는 의료진 API · 영속화
#
# 실제 LLM 경로는 진짜 키 대신 가짜 HTTP 세션(fake_anthropic.FakeAnthropic)을 core.llm_client.LLMClient에 끼워
# ClientRoleLLM → LLMClient → HTTP 요청 · 응답 해석까지 그대로 돌린다 (네트워크 없음).
import json
import os
import re
import stat
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from core.config import Settings  # noqa: E402
from core.llm_client import LLMClient  # noqa: E402
from medical.config import ROOT, MedicalConfig  # noqa: E402
from medical.llm import ClientRoleLLM  # noqa: E402
from tests.medicloak.fake_anthropic import FakeAnthropic  # noqa: E402
from webdemo.backend import emr, redact  # noqa: E402
from webdemo.backend.app import Product, create_app  # noqa: E402
from webdemo.backend.auth import COOKIE, add_user, ensure_initial_accounts, hash_password, token_hash, verify_password  # noqa: E402
from webdemo.backend.engine import Engine  # noqa: E402
from webdemo.backend.persist import Persist  # noqa: E402
from webdemo.backend.live import ANSWER_STYLE, ANSWER_STYLE_ID  # noqa: E402
from webdemo.backend.review import RELEASE_VERSION  # noqa: E402
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
    ensure_initial_accounts(store, PW, w / "accounts.txt")
    paths = emr.export_csv(store, w / "snap", log=lambda s: None)
    fake = FakeAnthropic()
    eng = Engine(w / "engine", log=lambda s: None, paths=paths, live_llm=fake_llm(fake), live_label="실제 LLM (fake-model-1)",
                 first_id=Persist(store, None).next_id())
    app = create_app(eng, simulations=True, product=Product(store=store))          # 운영 모드는 시뮬레이션 대화를 만들지 않는다
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


def wait_prefetch(world, timeout: float = 60.0) -> None:
    """뒤에서 도는 첫 답 미리 준비가 모두 끝날 때까지 (끝난 스레드는 목록에서 스스로 내려간다)."""
    eng, end = world["eng"], time.time() + timeout
    while time.time() < end:
        with eng.lock:
            running = [t for t in eng._prefetching.values() if t.is_alive()]
        if not running:
            return
        running[0].join(0.5)
    raise AssertionError("미리 준비가 끝나지 않았습니다")


def fresh_first_answers(world) -> None:
    """가짜 LLM의 답을 바꾸는 테스트: 다른 대화가 받아 둔 첫 답(같은 요청)을 지운다 (실제 LLM은 온도 0이라 같은 요청에 같은 답)."""
    world["eng"].turn0_cache.answers.clear()


def current_conv(sec: TestClient, owner: str) -> str:
    return next(x["id"] for x in sec.get("/api/watch").json() if x["current"] and x["owner"] == owner)


# ── 로그인 · 역할 ──────────────────────────────────────────

def test_product_mode_has_no_simulation_conversations(world):
    sec = login(world, "privacy1")
    o = sec.get("/api/monitor/overview").json()
    assert o["simulations"] == "idle" and all(x["source"] == "clinic" for x in o["sessions"])


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


def test_no_conversation_until_patient_is_opened(world):
    """운영 모드는 기본 환자를 저절로 열지 않는다. EMR에서 열기 전에는 409(no-conversation)이고 LLM을 부르지 않는다."""
    from webdemo.backend.auth import add_user
    add_user(world["store"], "doctor_new", "새의사", "clinician", "내과", PW)
    fake: FakeAnthropic = world["fake"]
    n0 = len(fake.calls)
    doc = login(world, "doctor_new")
    for path in ("/api/workspace", "/api/patient-context", "/api/risk-states", "/api/protection-policy"):
        r = doc.get(path)
        assert r.status_code == 409 and r.headers.get("X-MediCloak-State") == "no-conversation", path
    assert doc.get("/api/clinic/messages").json() == []
    assert doc.post("/api/cases/case-1/messages", json=dict(sessionId="x", question=Q_DRUG, clientMessageId="z")).status_code == 409
    assert len(fake.calls) == n0                                             # 로그인 · 화면 요청만으로는 LLM을 부르지 않는다
    _, sid = launch(doc, "T0014")
    assert len(fake.calls) > n0                                              # 환자를 열면 첫 답(턴 0)을 실제 LLM 경로로 만든다
    assert doc.get("/api/workspace").status_code == 200
    cases = doc.get("/api/cases", params=dict(patientContextId=doc.get("/api/patient-context").json()["contextId"])).json()
    assert [c["diagnosis"] for c in cases][:1] == ["Acute bronchitis"] and "loratadine" in cases[0]["description"]


def test_worklist_and_launch(world):
    doc = login(world, "doctor1")
    wl = doc.get("/api/emr/worklist").json()
    assert len(wl) >= 100 and all(x["purposes"] for x in wl)
    assert {"trialId", "purpose", "purposeLabel", "visitDate", "mainDx", "item"} <= set(wl[0]["purposes"][0])
    # 목록에는 성별 · 연령대만: 생년 · 거주 지역은 내보내지 않는다 (AI 답의 사례와 맞춰 볼 단서를 늘리지 않는다)
    assert all({"birthYear", "region", "lastVisit"}.isdisjoint(x) and all("ageSex" not in p for p in x["purposes"]) for x in wl)
    bands = {x["ageBand"] for x in wl}
    assert bands and all(re.fullmatch(r"[1-9]\d*0대|10세 미만", b) for b in bands)            # 진료 중 환자 띠와 같은 연령대
    # 진료 상태: 끝나지 않은 진단 · 관리 계획이 없으면 완치, 있어도 마지막 기록이 3년 넘게 앞서면 장기 미내원. 진료 중이 먼저 온다
    order = {"ACTIVE": 0, "RESOLVED": 1, "DORMANT": 2}
    status = [x["status"] for x in wl]
    assert set(status) == set(order) and status == sorted(status, key=order.get)
    assert all((x["status"] == "RESOLVED") == (x["openItems"] == 0) for x in wl)
    assert all(x["lastRecord"] and re.fullmatch(r"\d{4}-\d{2}-\d{2}", x["lastRecord"]) for x in wl)
    from webdemo.backend.emr import Emr
    latest = Emr(world["store"]).latest_record()                             # EMR 전체 마지막 기록일 (합성 데이터를 만든 날)
    assert latest >= max(x["lastRecord"] for x in wl)
    cut = f"{int(latest[:4]) - 3:04d}{latest[4:]}"
    assert all(x["lastRecord"] < cut for x in wl if x["status"] == "DORMANT")
    assert all(x["lastRecord"] >= cut for x in wl if x["status"] == "ACTIVE")
    assert {x["statusLabel"] for x in wl} == {"진료 중", "완치", "장기 미내원"}
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
    assert p["system"].endswith(ANSWER_STYLE)                                    # 대상 AI 답 형식 (레드팀과 같은 설정)
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
    # 운영 모드 원문 열람: 고른 사유만으로는 열리지 않는다 (한 줄 설명 필수)
    assert sec.post(f"/api/monitor/sessions/{w}/reveal", json=dict(reason="오탐 확인")).status_code == 422
    d2 = sec.post(f"/api/monitor/sessions/{w}/reveal", json=dict(reason="오탐 확인", note="실제 LLM 답에서 가린 시기 확인")).json()
    assert "2004-06-16" in d2["arms"]["C1"]["turns"][-1]["raw"]
    assert d2["patient_tag"].startswith("P-") and all(r["tag"].startswith("P-") and r["patient"] for r in d2["retrieval"])
    rv_log = next(a for a in sec.get("/api/monitor/audit").json() if a["action"] == "reveal")
    assert rv_log["note"] == "실제 LLM 답에서 가린 시기 확인" and rv_log["patient_tag"] == d2["patient_tag"]
    assert [x["tag"] for x in rv_log["subjects"]] == [r["tag"] for r in d2["retrieval"]]          # 열람한 과거 환자 모두 (기호)
    assert not any(r["patient"] in json.dumps(rv_log, ensure_ascii=False) for r in d2["retrieval"])   # 번호는 감사 기록에 그대로 두지 않는다
    assert d["patient_tag"] == d2["patient_tag"] and d["patient"] is None                          # 열람 전에도 기호는 보인다
    row = next(x for x in sec.get("/api/monitor/overview").json()["sessions"] if x["id"] == w)
    assert row["owner"] == "김서연" and row["llm_mode"] == "live" and row["status"] == "danger" and row["last_question"] == Q_DRUG
    # 원 응답이 든 턴 기록은 DB에만 (C1S는 뒤에서 계산한 뒤 저장)
    recs = {a: world["store"].turns_of(w, a) for a in ("C0", "C1", "C1S")}
    assert [r["turn"] for r in recs["C1"]] == [0, 1] and "2004-06-16" in recs["C1"][1]["raw_response_text"]
    assert [r["turn"] for r in recs["C1S"]] == [0, 1]


def test_dates_only_inside_med_fields_are_still_counted(world):
    """실제 추출기가 날짜를 약 항목의 period_start에만 적어도(PERIOD 단서 없음) 규칙 추출이 날짜를 세어 가린다.
    규칙 추출이 없으면 공개 계획이 날짜를 세지 않아, 다른 값을 고칠 일이 없으면 시작일이 그대로 나가고
    다른 값을 고쳤다면 고친 답을 다시 뽑을 때에야 날짜가 나와 답 전체가 거절된다 (2026-11-04 실제 LLM 대화 S0009)."""
    from dataclasses import replace
    eng = world["eng"]
    good, ctx0 = eng.live_llm.inner, eng.live_ctx
    eng.live_llm.inner = fake_llm(FakeAnthropic(period_in_med=True))
    try:
        assert ctx0.cfg.rule_extract is True                                     # 실제 LLM 대화에는 기본으로 켠다
        doc = login(world, "doctor2")
        _, sid = launch(doc, "T0014")
        body = doc.post("/api/cases/case-1/messages", json=dict(sessionId=sid, question=Q_DRUG, clientMessageId="p1")).json()
        prot = body["assistantMessage"]["protection"]
        assert prot["releaseMode"] == "REWRITTEN", prot
        assert {t["attribute"]: t["action"] for t in prot["transformations"]} == {"MED": "allow", "PERIOD": "suppress"}
        text = "".join(s["text"] for s in body["assistantMessage"]["segments"])
        assert "loratadine" in text and "2004-06-16" not in json.dumps(body, ensure_ascii=False)

        eng.live_ctx = replace(ctx0, cfg=replace(ctx0.cfg, rule_extract=False))  # 끄면 생기는 일 (설정 확인용)
        _, sid2 = launch(doc, "T0014")
        b2 = doc.post("/api/cases/case-1/messages", json=dict(sessionId=sid2, question=Q_DRUG, clientMessageId="p2")).json()
        assert b2["assistantMessage"]["protection"]["releaseMode"] == "RAW"
        assert "2004-06-16" in "".join(s["text"] for s in b2["assistantMessage"]["segments"])
    finally:
        eng.live_llm.inner, eng.live_ctx = good, ctx0
        eng.wait_compare(20)


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
    doc = login(world, "doctor2")
    _, sid = launch(doc, "T0024")                         # 첫 답(턴 0)도 실제 LLM 경로라 정상 LLM으로 먼저 연다
    eng.live_llm.inner = fake_llm(bad)                    # 같은 엔진에서 키 오류만 흉내 낸다
    try:
        before = doc.get("/api/cases/case-1/session").json()
        r = doc.post("/api/cases/case-1/messages", json=dict(sessionId=sid, question=Q_DRUG, clientMessageId="e1"))
        assert r.status_code == 502 and "LLMHTTPError" in r.json()["detail"] and KEY not in r.text
        assert doc.get("/api/cases/case-1/session").json() == before
        sec = login(world, "privacy1")
        w = current_conv(sec, "박준호")
        assert sec.get(f"/api/monitor/sessions/{w}").json()["turn"] == 0
        assert len(bad.calls) == 1                        # 401은 다시 시도하지 않는다
        # 새 환자를 열 때(턴 0) 실패해도 502이고, 지금 대화는 그대로 남는다
        fresh_first_answers(world)
        wl = doc.get("/api/emr/worklist").json()
        row = next(x for x in wl if any(p["trialId"] == "T0036" for p in x["purposes"]))
        r2 = doc.post("/api/emr/launch", json=dict(fhirId=row["fhirId"], purpose=row["purposes"][0]["purpose"]))
        assert r2.status_code == 502 and KEY not in r2.text
        assert current_conv(sec, "박준호") == w and doc.get("/api/cases/case-1/session").json() == before
    finally:
        eng.live_llm.inner = good



def test_first_answer_is_shared_across_clinicians_and_shows_progress(world):
    """같은 환자 · 같은 진료 목적의 첫 답은 대화 사이에 나눠 쓴다 (두 번째 의료진은 실제 LLM을 부르지 않는다).
    여는 동안 /api/emr/launch/progress가 지금 단계와 실제 LLM 호출 수를 알려 준다. 거절된 첫 답은 나눠 쓰지 않는다."""
    fake: FakeAnthropic = world["fake"]
    fresh_first_answers(world)
    add_user(world["store"], "doctor_s1", "공유의사1", "clinician", "내과", PW)
    add_user(world["store"], "doctor_s2", "공유의사2", "clinician", "내과", PW)
    a, watcher, b = login(world, "doctor_s1"), login(world, "doctor_s1"), login(world, "doctor_s2")
    seen: list[dict] = []
    fake.delay = 0.15
    try:
        th = threading.Thread(target=lambda: launch(a, "T0016"))
        th.start()
        deadline = time.time() + 30
        while th.is_alive() and time.time() < deadline:
            p = watcher.get("/api/emr/launch/progress").json()
            if p.get("active"):
                seen.append(p)
            time.sleep(0.05)
        th.join(30)
    finally:
        fake.delay = 0.0
    assert seen and any(p["label"] == "비슷한 사례를 정리하는 중" for p in seen) and max(p["calls"] for p in seen) >= 2
    assert watcher.get("/api/emr/launch/progress").json() == {"active": False}
    n0 = len(fake.calls)
    launch(b, "T0016")
    assert len(fake.calls) == n0                                  # 두 번째 의료진: 실제 LLM을 다시 부르지 않았다
    # 거절된 첫 답(추출 실패)은 지운다: 다음에 열면 새로 부른다
    fresh_first_answers(world)
    fake.broken_extract = True
    try:
        launch(b, "T0005")
    finally:
        fake.broken_extract = False
    assert not world["eng"].turn0_cache.answers

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

def test_review_rules_and_approval_change_the_conversation(world):
    """보안 담당자 검토가 대화에 반영된다: 승인하면 가린 값이 그 의료진에게만 나가고 State에 더해지며, 규칙은 다음 답부터 그 단서를 가린다."""
    add_user(world["store"], "doctor_rv", "검토의사", "clinician", "내과", PW)
    doc = login(world, "doctor_rv")
    _, sid = launch(doc, "T0014")
    body = doc.post("/api/cases/case-1/messages", json=dict(sessionId=sid, question=Q_DRUG, clientMessageId="r1")).json()
    assert "2004-06-16" not in json.dumps(body, ensure_ascii=False)
    doc.post("/api/clinic/messages", json=dict(kind="access_request", text="시작 시기가 약 조정에 필요합니다.", caseId="case-1"))
    sec = login(world, "privacy1")
    w = current_conv(sec, "검토의사")
    # 후보가 줄어든 과정: 기준 집단 → 진단 → 약, 가린 시작일은 '그대로면 1명'
    n = sec.get(f"/api/watch/{w}/cases/case-1/narrowing").json()
    assert [s["kAfter"] for s in n["steps"]] == [189, 6] and n["population"] == 461 and n["k"] == 6
    assert [(h["attribute"], h["kIfRaw"]) for h in n["hidden"]] == [("PERIOD", 1)]
    # 보안 담당자 화면에는 다시 확인한 기록이 있고, 의료진 화면 API에는 없다
    wp = sec.get(f"/api/watch/{w}/cases/case-1/session").json()["messages"][-1]["protection"]
    assert wp["checks"] and wp["checks"][0]["ok"] and wp["transformations"][-1]["kIfRaw"] == 1
    cp = doc.get("/api/cases/case-1/session").json()["messages"][-1]["protection"]
    assert "checks" not in cp and all("kIfRaw" not in tt for tt in cp["transformations"]) and not redact.leaked_numbers(cp)
    # 공개 승인
    hidden = sec.get(f"/api/monitor/sessions/{w}/hidden").json()
    item = next(x for x in hidden if x["case"] == "사례1" and x["attribute"] == "PERIOD")
    assert "value" not in item and "raw_value" not in json.dumps(hidden)
    assert sec.post(f"/api/monitor/sessions/{w}/approve", json=dict(items=[item["id"]], reason="짧음")).status_code == 422
    assert sec.post(f"/api/monitor/sessions/{w}/messages", json=dict(kind="release", text="몰래 보내는 값 2004-06-16")).status_code == 422
    # 함께 공개하면 후보가 기준 아래(1명)로 내려간다: 고위험 확인 없이는 막고, 확인해도 사유가 짧으면 막는다 (2인 확인 대신)
    wi = sec.post(f"/api/monitor/sessions/{w}/what-if", json=dict(items=[item["id"]])).json()
    assert wi["kAfter"] == {"사례1": 1} and wi["lowest"] == 1 and wi["kReq"] == 5
    low = sec.post(f"/api/monitor/sessions/{w}/approve", json=dict(items=[item["id"]], reason="처방 시작 시기가 약 조정 판단에 필요함"))
    assert low.status_code == 422 and "1명까지" in low.json()["detail"]
    assert sec.post(f"/api/monitor/sessions/{w}/approve", json=dict(items=[item["id"]], reason="약 조정에 필요함", confirmLowK=True)).status_code == 422
    r = sec.post(f"/api/monitor/sessions/{w}/approve", json=dict(items=[item["id"]], reason="처방 시작 시기가 약 조정 판단에 필요함", confirmLowK=True))
    assert r.status_code == 200, r.text
    ap = r.json()["approval"]
    assert ap["k_after"] == {"사례1": 1} and ap["items"][0]["value"] is None and ap["high_risk"]   # 승인 응답에도 값은 없다 (열람 뒤 상세에서만)
    d = r.json()["detail"]
    assert d["approvals"][0]["items"][0]["value"] is None                    # 관제 상세는 열람 전에 값을 지운다
    # 승인으로 기준 아래가 된 사례는 경보(violated)가 아니라 '승인 공개'로 따로 센다
    assert d["row"]["k_now"] == 1 and d["row"]["violated"] == [] and d["row"]["approved_low"] == ["사례1"]
    kpi = sec.get("/api/monitor/overview").json()["kpi"]
    assert kpi["approved_low"] >= 1
    ap_log = next(a for a in sec.get("/api/monitor/audit").json() if a["action"] == "approve_release")
    assert ap_log["high_risk"] and ap_log["k_min"] == 1 and ap_log["subjects"][0]["case"] == "사례1" and ap_log["subjects"][0]["tag"]
    assert "2004-06-16" not in json.dumps(d, ensure_ascii=False)
    rel = [m for m in d["messages"] if m["kind"] == "release"]
    assert rel and rel[0]["masked"] and "2004-06-16" not in rel[0]["text"]
    th = sec.get(f"/api/monitor/sessions/{w}/messages").json()               # 메시지 목록은 열람과 관계없이 늘 지운다
    assert "2004-06-16" not in json.dumps(th, ensure_ascii=False) and th["messages"][-1]["masked"]
    rv = sec.post(f"/api/monitor/sessions/{w}/reveal", json=dict(reason="의료진 문의 대응", note="공개 승인한 값 확인")).json()
    assert rv["approvals"][0]["items"][0]["value"] == "2004-06-16"
    assert any(m["kind"] == "release" and "2004-06-16" in m["text"] and not m.get("masked") for m in rv["messages"])
    assert sec.post(f"/api/monitor/sessions/{w}/approve", json=dict(items=[item["id"]], reason="같은 값을 다시 공개")).status_code == 400
    # 의료진: 메시지로 값을 받고, 사례 노트에 승인 표시, 숫자는 여전히 없음
    msgs = doc.get("/api/clinic/messages").json()
    assert msgs[-1]["kind"] == "release" and "2004-06-16" in msgs[-1]["text"]
    ents = doc.get("/api/cases/case-1/disclosures").json()["entries"]
    assert any(e.get("approved") and e["value"] == "2004-06-16" for e in ents)
    assert doc.get("/api/risk-states").json()[0]["disclosureAllowed"] is False and not redact.leaked_numbers(doc.get("/api/risk-states").json())
    n2 = sec.get(f"/api/watch/{w}/cases/case-1/narrowing").json()
    assert n2["steps"][-1]["approved"] and n2["steps"][-1]["kAfter"] == 1 and n2["steps"][-1]["afterTurn"] == 1
    assert n2["hidden"][0]["released"] is True
    # 규칙: 사례1 약은 늘 가림 → 다음 답에서 약이 빠진다 (이미 나간 답은 그대로)
    bad = sec.post(f"/api/monitor/sessions/{w}/rules", json=dict(case="사례9", attribute="MED"))
    assert bad.status_code == 400
    fail = next(a for a in sec.get("/api/monitor/audit").json() if a["action"] == "add_rule_failed")       # 걸지 못한 시도도 남긴다
    assert fail["case"] == "사례9" and "사례" in fail["why"]
    d = sec.post(f"/api/monitor/sessions/{w}/rules", json=dict(case="사례1", attribute="MED", note="약 이름 반복 질문")).json()
    rule = d["rules"][0]
    assert rule["attribute"] == "MED" and rule["from_turn"] == 2 and rule["by"].startswith("이하늘")
    b2 = doc.post("/api/cases/case-1/messages", json=dict(sessionId=sid, question="사례1에서 쓴 약 이름을 다시 알려 주세요", clientMessageId="r2")).json()
    text = "".join(x["text"] for x in b2["assistantMessage"]["segments"])
    assert "loratadine" not in text
    tf = b2["assistantMessage"]["protection"]["transformations"]
    assert any(x["attribute"] == "MED" and x["action"] == "suppress" for x in tf)
    wtf = sec.get(f"/api/watch/{w}/cases/case-1/session").json()["messages"][-1]["protection"]["transformations"]
    assert any(x["attribute"] == "MED" and x["rule"] for x in wtf)
    d = sec.delete(f"/api/monitor/sessions/{w}/rules/{rule['id']}").json()
    assert d["rules"] == []
    actions = [a["action"] for a in sec.get("/api/monitor/audit").json()[:6]]
    assert {"approve_release", "add_rule", "remove_rule"} <= set(actions)
    # 지난 대화로 남아도 규칙 · 승인 기록과 후보가 줄어든 과정을 읽을 수 있다 (스냅숏)
    snap = world["store"].conversation(w)
    assert snap["security"]["approvals"][0]["items"][0]["value"] == "2004-06-16"
    assert snap["clinic"]["per_case"]["case-1"]["narrowing"]["steps"][-1]["approved"]



def test_review_only_reaches_the_current_conversation(world):
    """의료진이 다른 환자를 열면 지난 대화에는 다음 질문이 없다: 그 대화에 공개 승인 · 규칙을 걸면 409로 막는다."""
    add_user(world["store"], "doctor_nc", "전환의사", "clinician", "내과", PW)
    doc = login(world, "doctor_nc")
    _, sid = launch(doc, "T0014")
    doc.post("/api/cases/case-1/messages", json=dict(sessionId=sid, question=Q_DRUG, clientMessageId="n1"))
    sec = login(world, "privacy1")
    w1 = current_conv(sec, "전환의사")
    item = next(x for x in sec.get(f"/api/monitor/sessions/{w1}/hidden").json() if x["attribute"] == "PERIOD")
    launch(doc, "T0010")
    assert current_conv(sec, "전환의사") != w1
    r = sec.post(f"/api/monitor/sessions/{w1}/approve", json=dict(items=[item["id"]], reason="지난 대화의 값 공개 시도"))
    assert r.status_code == 409 and "다른 환자" in r.json()["detail"]
    assert sec.post(f"/api/monitor/sessions/{w1}/rules", json=dict(case="사례1", attribute="MED")).status_code == 409
    fail = next(a for a in sec.get("/api/monitor/audit").json() if a["action"] == "add_rule_failed")
    assert fail["session"] == w1 and "다른 환자" in fail["why"] and fail["subjects"][0]["case"] == "사례1"
    assert sec.get(f"/api/monitor/sessions/{w1}").json()["approvals"] == []


def _assist(sec: TestClient, w: str, timeout: float = 20.0) -> dict:
    """검토 보조 초안이 끝날 때까지 (뒤에서 만든다)."""
    end = time.time() + timeout
    while True:
        st = sec.get(f"/api/monitor/sessions/{w}/assist").json()
        if st["status"] != "running" or time.time() > end:
            return st
        time.sleep(0.05)


def test_review_assistant_drafts_on_request_without_raw_values(world):
    """세부 정보 요청이 오면 검토 보조가 초안을 만든다: 값 원문 없이 판정하고, LLM에도 원문을 보내지 않고, 아무것도 스스로 보내지 않는다."""
    add_user(world["store"], "doctor_as", "보조의사", "clinician", "내과", PW)
    doc = login(world, "doctor_as")
    _, sid = launch(doc, "T0014")
    doc.post("/api/cases/case-1/messages", json=dict(sessionId=sid, question=Q_DRUG, clientMessageId="as1"))
    sec = login(world, "privacy1")
    w = current_conv(sec, "보조의사")
    assert sec.get(f"/api/monitor/sessions/{w}/assist").json()["status"] == "none"
    assert sec.post(f"/api/monitor/sessions/{w}/assist").status_code == 409          # 요청이 없으면 만들 초안이 없다
    n_calls = len(world["fake"].calls)
    doc.post("/api/clinic/messages", json=dict(kind="access_request", text="처방 시작 시기를 알아야 복용 기간을 판단할 수 있습니다.", caseId="case-1"))
    st = _assist(sec, w)
    assert st["status"] == "ready", st
    d = st["draft"]
    assert d["case"] == "사례1" and d["purpose"] == "PRESCRIPTION" and d["kReq"] == 5 and d["kNow"] == 6
    item = next(i for i in d["items"] if i["attribute"] == "PERIOD")
    assert item["kIfRelease"] == 1 and item["need"] == "coarse" and item["rec"] in ("decline", "keep") and item["recLabel"]
    assert d["verdict"] in ("keep", "consider") and d["release"] == [] and d["combinedK"] is None
    assert [s["label"] for s in d["steps"]] == ["요청 읽기", "가린 값 모으기", "하나씩 열어 보기", "조회 목적과 대조", "함께 열어 보기", "초안 쓰기"]
    assert d["writer"] == "llm" and d["reasonFit"] == "구체적" and "2004-06-16" not in json.dumps(st, ensure_ascii=False)
    assert not re.search(r"\d", re.sub(r"사례\s*\d+", "", d["reply"])) and "후보" not in d["reply"]
    # LLM에는 단서 종류 · 처리 · 후보 수 · 요청 문장만 간다 (값 · 약 이름 · 환자 번호 없음)
    prompts = [c["payload"]["messages"][-1]["content"] for c in world["fake"].calls[n_calls:]]
    reviewer = [p for p in prompts if p.startswith("[검토 보조]")]
    assert len(reviewer) == 1
    assert "2004-06-16" not in reviewer[0] and "loratadine" not in reviewer[0].lower() and "처방 시작 시기를 알아야" in reviewer[0]
    # 초안은 보내지 않는다: 의료진 메시지는 요청 하나 그대로, 공개 승인 · 규칙 없음
    det = sec.get(f"/api/monitor/sessions/{w}").json()
    assert [m["kind"] for m in det["messages"]] == ["access_request"] and det["approvals"] == [] and det["rules"] == []
    assert det["assist"]["status"] == "ready" and det["row"]["pending_request"]
    assert doc.get("/api/clinic/messages").json()[-1]["kind"] == "access_request"
    # 감사 기록: 누가(검토 보조 AI) · 어느 요청 · 추천 수 · 쓴 방식만
    a = next(x for x in sec.get("/api/monitor/audit").json() if x["action"] == "assist_draft" and x["session"] == w)
    assert a["actor"] == "검토 보조 AI" and a["writer"] == "llm" and a["case"] == "사례1" and "2004-06-16" not in json.dumps(a, ensure_ascii=False)
    # 의료진은 검토 보조 경로를 쓸 수 없다
    assert doc.get(f"/api/monitor/sessions/{w}/assist").status_code == 403
    # 초안대로 답장하면 의료진 화면에 도착한다 (담당자가 직접 보냄)
    r = sec.post(f"/api/monitor/sessions/{w}/messages", json=dict(kind="reply", text=d["reply"], case="사례1"))
    assert r.status_code == 200 and doc.get("/api/clinic/messages").json()[-1]["text"] == d["reply"]


def test_review_assistant_uses_fixed_sentences_when_the_llm_draft_is_unusable(world):
    """LLM 답장에 숫자가 섞이거나 JSON이 아니면 정해진 문장으로 쓴다. '다시 만들기'는 같은 요청으로 다시 돈다."""
    add_user(world["store"], "doctor_as2", "보조의사둘", "clinician", "내과", PW)
    doc = login(world, "doctor_as2")
    _, sid = launch(doc, "T0014")
    doc.post("/api/cases/case-1/messages", json=dict(sessionId=sid, question=Q_DRUG, clientMessageId="as2"))
    sec = login(world, "privacy1")
    w = current_conv(sec, "보조의사둘")
    fake = world["fake"]
    try:
        fake.assist = "numbers"
        doc.post("/api/clinic/messages", json=dict(kind="access_request", text="시작 날짜가 필요합니다.", caseId="case-1"))
        d = _assist(sec, w)["draft"]
        assert d["steps"][-1]["detail"].startswith("정해진 문장") and "ValueError" in d["steps"][-1]["detail"]
        assert d["writer"] == "template" and "후보" not in d["reply"] and not re.search(r"\d", re.sub(r"사례\s*\d+", "", d["reply"]))
        assert "사례 1" in d["reply"] and d["summary"].startswith("사례 1 요청")
        fake.assist = "broken"
        assert sec.post(f"/api/monitor/sessions/{w}/assist").json()["status"] in ("running", "ready")      # 가짜 LLM은 바로 끝날 수 있다
        st = _assist(sec, w)
        assert st["status"] == "ready" and st["draft"]["writer"] == "template" and "ValueError" in st["draft"]["steps"][-1]["detail"]
        fake.assist = "ok"
        assert sec.post(f"/api/monitor/sessions/{w}/assist").status_code == 200
        assert _assist(sec, w)["draft"]["writer"] == "llm"
    finally:
        fake.assist = "ok"


def test_review_assistant_what_if_and_greedy_combination_unit():
    """what_if는 State를 바꾸지 않는다 · 하나씩은 기준 이상이어도 함께 열면 기준 아래가 되는 값은 '사유 확인'으로 돌린다."""
    from webdemo.backend import assist

    assert assist.join_ko(["나이", "날짜", "약 이름"]) == "나이, 날짜와 약 이름" and assist.join_ko(["진단명", "날짜"]) == "진단명과 날짜"
    assert assist.josa("약 이름", "은", "는") == "약 이름은" and assist.josa("날짜", "은", "는") == "날짜는"
    assert assist.recommend("suppress", "need", 8, 5)[0] == "release"
    assert assist.recommend("suppress", "low", 2, 5)[0] == "decline"
    assert assist.recommend("generalize", "coarse", 2, 5)[0] == "keep"
    assert assist.recommend("suppress", "coarse", 1, 5)[0] == "decline"
    assert assist.recommend("suppress", "need", 3, 5)[0] == "consider"

    class Stub:
        qtype, messages, logs = "PRESCRIPTION", [], {"C1": []}
        cfg = MedicalConfig(mode="exploration")

        def hidden(self):
            return [dict(id="1:사례1:0", turn=1, case="사례1", index=0, attribute="MED", action="suppress", released=False, dropped=False),
                    dict(id="1:사례1:1", turn=1, case="사례1", index=1, attribute="DX", action="suppress", released=False, dropped=False),
                    dict(id="2:사례1:0", turn=2, case="사례1", index=0, attribute="SEX", action="suppress", released=False, dropped=False)]

        def current_k(self, arm, ref):
            return 20

        def what_if(self, ids):
            one = {"1:사례1:0": 9, "1:사례1:1": 7, "2:사례1:0": 2}
            return {"사례1": one[ids[0]] if len(ids) == 1 else 4}

    a = assist.analyse(Stub(), dict(id="M0001", case="사례1", text="약과 진단이 필요합니다"))
    rec = {i["attribute"]: i["rec"] for i in a["items"]}
    assert rec == {"MED": "release", "DX": "consider", "SEX": "decline"} and a["release"] == ["1:사례1:0"] and a["combinedK"] == 9
    assert a["verdict"] == "partial" and a["counts"] == dict(release=1, consider=1, keep=0, decline=1)
    t = assist.template_text(a)
    assert "약 이름은 공개 승인으로" in t["reply"] and "진단명은 그대로" in t["reply"] and "성별은 이번 처방 참고 목적과 관련이 적어" in t["reply"]
    assert t["reply"].startswith("요청하신 사례 1의") and "처방 참고에 필요한 약 공개" in t["reason"]
    with pytest.raises(ValueError):
        assist.parse_draft('{"summary": "사례 1 요청을 봤습니다.", "reply": "후보가 2명이라 공개하지 않습니다 다시 알려 주세요"}')
    ok = assist.parse_draft('설명\n{"summary": "사례 1 요청을 봤습니다.", "reply": "요청하신 사례 1의 날짜는 공개하지 않습니다.", "reason_fit": "모름"}')
    assert ok["reasonFit"] == "불분명"


def test_what_if_does_not_change_the_conversation(world):
    add_user(world["store"], "doctor_wi", "가정의사", "clinician", "내과", PW)
    doc = login(world, "doctor_wi")
    _, sid = launch(doc, "T0014")
    doc.post("/api/cases/case-1/messages", json=dict(sessionId=sid, question=Q_DRUG, clientMessageId="wi1"))
    sec = login(world, "privacy1")
    w = current_conv(sec, "가정의사")
    s = world["eng"].sessions[w]
    with world["eng"].lock:
        before = (len(s.runs["C1"].cases["사례1"].committed), s.current_k("C1", "사례1"), len(s.approvals))
        item = next(x for x in s.hidden() if x["attribute"] == "PERIOD")
        assert s.what_if([item["id"]]) == {"사례1": 1} and s.what_if(["9:사례9:0"]) == {}
        assert (len(s.runs["C1"].cases["사례1"].committed), s.current_k("C1", "사례1"), len(s.approvals)) == before


def test_hidden_values_show_as_named_locks_in_the_chat_answer(world):
    """실제 LLM 답은 가린 값을 문장에서 지운다: 그 사례 단락 끝에 '시기 비공개' 자리 표시가 붙는다 (글 · 판정은 그대로)."""
    add_user(world["store"], "doctor_ph", "표시의사", "clinician", "내과", PW)
    doc = login(world, "doctor_ph")
    _, sid = launch(doc, "T0014")
    body = doc.post("/api/cases/case-1/messages", json=dict(sessionId=sid, question=Q_DRUG, clientMessageId="ph1")).json()
    msg = body["assistantMessage"]
    segs, tf = msg["segments"], {x["id"]: x for x in msg["protection"]["transformations"]}
    marks = [s for s in segs if s.get("placeholder")]
    assert marks, segs
    m = marks[0]
    assert m["kind"] == "disclosure" and m["text"] == "(비공개)" and m["label"] == "시기"
    assert tf[m["transformationId"]]["action"] == "suppress" and tf[m["transformationId"]]["caseRef"] == "사례1"
    joined = "".join(s["text"] for s in segs if not s.get("placeholder"))
    assert "2004-06-16" not in joined and "2004-06" not in joined
    assert segs[-1] is m or segs.index(m) == len(segs) - 1          # 사례 1만 나온 답: 답 끝에 붙는다
    # 의료진 화면 API에는 여전히 숫자가 없다
    assert not redact.leaked_numbers(doc.get("/api/cases/case-1/session").json())
    stored = doc.get("/api/cases/case-1/session").json()["messages"][-1]["segments"]
    assert any(s.get("placeholder") and s.get("label") == "시기" for s in stored)


def test_hidden_marks_go_to_the_end_of_each_case_block_unit():
    from api_server.engine import segments_of
    from webdemo.backend.clinic import mark_hidden

    text = "사례1은 A를 처방받았습니다.\n사례2는 B를 처방받았고 경과가 좋았습니다. 사례3은 기록이 없습니다."
    tf = [dict(id="a", action="suppress", attribute="PERIOD", caseRef="사례1", disclosedValue=None),
          dict(id="b", action="suppress", attribute="AGE", caseRef="사례2", disclosedValue=None),
          dict(id="c", action="suppress", attribute="DX", caseRef="사례2", disclosedValue=None),
          dict(id="d", action="suppress", attribute="DX", caseRef="사례2", disclosedValue=None),                # 같은 사례 · 단서는 한 번
          dict(id="e", action="suppress", attribute="MED", caseRef="사례3", disclosedValue=None, dropped=True),   # 사례째로 뺀 값은 표시 안 함
          dict(id="f", action="allow", attribute="MED", caseRef="사례1", disclosedValue="A")]
    out = mark_hidden(text, segments_of(text, tf), tf, "사례1")
    assert "".join(s["text"] for s in out if not s.get("placeholder")) == text
    kinds = [(s.get("label"), s["text"]) if s.get("placeholder") else s["text"] for s in out]
    assert kinds == ["사례1은 ", "A", "를 처방받았습니다.", ("시기", "(비공개)"), "\n사례2는 B를 처방받았고 경과가 좋았습니다.",
                     ("사례 2 진단", "(비공개)"), ("사례 2 나이", "(비공개)"), " 사례3은 기록이 없습니다."]
    # 글에 이미 '(비공개)'로 남은 값은 그 자리에 두고 더하지 않는다 (결정적 응답기 답)
    t2 = "사례1 · 시기: (비공개)"
    tf2 = [dict(id="x", action="suppress", attribute="PERIOD", caseRef="사례1", disclosedValue=None)]
    assert not any(s.get("placeholder") for s in mark_hidden(t2, segments_of(t2, tf2), tf2, "사례1"))
    # 사례 줄 사이에 빈 줄이 있어도 표시는 그 사례 줄 끝에 붙는다 (빈 줄에 혼자 떨어지지 않는다). 마지막 사례는 그 문단 끝.
    # 같은 사례의 같은 단서가 답에 다른 값으로 보이면 '일부'(partial)
    t3 = "공통 약은 A입니다.\n\n사례1: A (COPD 관리)\n\n사례2: B\n\n전체적으로 비슷합니다."
    tf3 = [dict(id="m1", action="suppress", attribute="MED", caseRef="사례1", disclosedValue=None),
           dict(id="m2", action="allow", attribute="MED", caseRef="사례1", disclosedValue="A"),
           dict(id="m3", action="suppress", attribute="MED", caseRef="사례2", disclosedValue=None)]
    out3 = mark_hidden(t3, segments_of(t3, tf3), tf3, "사례1")
    flat = "".join(f"[{x['label']}{' 일부' if x.get('partial') else ''}]" if x.get("placeholder") else x["text"] for x in out3)
    assert flat == "공통 약은 A입니다.\n\n사례1: A (COPD 관리)[처방 약 일부]\n\n사례2: B[사례 2 처방 약]\n\n전체적으로 비슷합니다."
    # 글에 남은 '(비공개)'는 그 문장의 사례 조치에 잇는다 (앞에서부터 아무 가림 조치에 잇지 않는다)
    from webdemo.backend.clinic import place_suppressed
    t4 = "사례1 환자는 A를 처방받았습니다.\n\n사례2 환자는 (비공개)를 처방받았습니다."
    tf4 = [dict(id="p1", action="suppress", attribute="PERIOD", caseRef="사례1", disclosedValue=None),
           dict(id="m2", action="suppress", attribute="MED", caseRef="사례2", disclosedValue=None)]
    seg4 = segments_of(t4, tf4)
    assert next(x for x in seg4 if x["kind"] == "disclosure")["transformationId"] == "p1"          # 고치기 전: 사례 1 시기로 이어짐
    out4 = mark_hidden(t4, place_suppressed(t4, seg4, tf4, "사례1", 5), tf4, "사례1")
    flat4 = "".join(f"[{x['label']}]" if x.get("placeholder") else f"<{x['transformationId']}>" if x["kind"] == "disclosure" else x["text"]
                    for x in out4)
    assert flat4 == "사례1 환자는 A를 처방받았습니다.[시기]\n\n사례2 환자는 <m2>를 처방받았습니다."


def _job(jid, *, status="done", fp=None, settings=None, viol=(0, 3), utility=0.6, overblock=0.05, started=0.0, finished=None, trigger=None,
         per_type=1, fuzzer="feedback"):
    arm = dict(viol10=dict(k=viol[0], n=viol[1], p=viol[0] / viol[1]), utility=utility, overblock=dict(k=0, n=1, p=overblock))
    return dict(id=jid, live=True, status=status, fingerprint=fp, settings=settings, started_at=started, finished_at=finished or started + 1,
                trigger=trigger, per_type=per_type, fuzzer=fuzzer, result=dict(arms=dict(C1=arm)))


def test_autocheck_compare_and_start_decisions_unit():
    """비교 수준(경고 · 주의 · 이상 없음 · 첫 기준) · 켤 때 결정(같은 설정이면 안 돌림, 끊긴 것만 있으면 다시) · 매일 시각."""
    from webdemo.backend import autocheck as A

    base = _job("R0001", viol=(0, 3), utility=0.60, overblock=0.05)
    assert A.compare(_job("R0002", viol=(1, 3)), base)["level"] == "warn"
    c = A.compare(_job("R0002", utility=0.50), base)
    assert c["level"] == "caution" and "답변 유용도가 0.60 → 0.50로 낮아졌습니다" in c["text"]
    assert A.compare(_job("R0002", overblock=0.12), base)["level"] == "caution"
    assert A.compare(_job("R0002", utility=0.58, overblock=0.07), base)["level"] == "ok"
    assert A.compare(_job("R0002"), None)["level"] == "none"
    s1 = dict(release="medicloak-release-v4", answer_style="on", model="실제 LLM (m1)", rule_extract="on")
    s2 = dict(s1, release="medicloak-release-v5", answer_style="off")
    assert A.changes_between(s1, s2) == ["판정 규칙 판: v4 → v5", "대상 AI 답 형식: 켬 → 끔"]
    assert A.valid_daily("03:00") == "03:00" and A.valid_daily(None) is None
    with pytest.raises(ValueError):
        A.valid_daily("25:00")

    class Inner:
        client, models = object(), {}

    class Eng:
        answer_style, live_rule_extract, live_label = True, True, "실제 LLM (m1)"
        live_llm = type("L", (), {"inner": Inner()})()

    started: list[str] = []

    class J:
        def __init__(self, trig):
            self.id = f"R{len(started) + 10:04d}"

    def start(trig):
        started.append(trig)
        return J(trig)

    logs: list = []
    fp = A.fingerprint(A.settings_of(Eng()))
    a = A.AutoRedteam(Eng(), lambda: [_job("R0001", fp=fp)], start, lambda *x, **k: logs.append((x, k)), on_change=True)
    a.on_start()
    assert a.decision == "same" and started == []
    a = A.AutoRedteam(Eng(), lambda: [_job("R0001", fp=fp, status="interrupted")], start, lambda *x, **k: None, on_change=True)
    a.on_start()
    assert a.decision == "started" and started == ["change"]
    a = A.AutoRedteam(Eng(), lambda: [_job("R0001", fp="old", settings=dict(A.settings_of(Eng()), release="medicloak-release-v3"))],
                      start, lambda *x, **k: None, on_change=True)
    a.on_start()
    assert a.decision == "started" and a.changes == ["판정 규칙 판: v3 → " + A.RELEASE_VERSION.replace("medicloak-release-", "")]
    a = A.AutoRedteam(Eng(), lambda: [], start, lambda *x, **k: None, on_change=False, daily="03:00")
    a.enabled = True
    at = time.mktime((2026, 11, 6, 3, 0, 5, 0, 0, -1))
    assert a.tick(at) is True and a.tick(at + 10) is False                        # 하루 한 번
    assert a.tick(time.mktime((2026, 11, 6, 4, 0, 0, 0, 0, -1))) is False
    assert a.tick(time.mktime((2026, 11, 7, 3, 0, 1, 0, 0, -1))) is True
    noll = type("E", (), dict(Eng.__dict__, live_llm=None))
    a = A.AutoRedteam(noll(), lambda: [], start, lambda *x, **k: None, on_change=True)
    a.on_start()
    assert a.decision == "no-llm"


def test_autocheck_runs_when_settings_change_and_compares(world, tmp_path):
    """켤 때 점검이 없으면 기준 점검을 돌리고, 같은 설정으로 다시 켜면 돌리지 않고, 답 형식을 바꾸면 다시 돌려 직전 점검과 비교한다."""
    store = Store(tmp_path / "auto.db")
    ensure_initial_accounts(store, PW, tmp_path / "accounts.txt")
    fake = FakeAnthropic()
    eng = Engine(tmp_path / "engine", log=lambda s: None, paths=world["paths"], live_llm=fake_llm(fake), live_label="실제 LLM (fake-model-1)")

    def serve():
        return TestClient(create_app(eng, simulations=False, product=Product(store=store, auto_redteam="change")))

    def wait_done(c):
        deadline = time.time() + 240
        while time.time() < deadline:
            st = c.get("/api/redteam/auto").json()
            if st["running"] is None and st["latest"] is not None:
                return st
            time.sleep(0.2)
        raise AssertionError("자동 점검이 끝나지 않았습니다")

    with serve() as c:
        assert c.post("/api/auth/login", json=dict(username="privacy1", password=PW)).status_code == 200
        st = c.get("/api/redteam/auto").json()
        assert st["enabled"] and st["onChange"] and st["decision"] == "started" and "기준 점검" in st["decisionText"]
        st = wait_done(c)
        first = c.get("/api/redteam").json()[0]
        assert first["trigger"] == "change" and first["fingerprint"] == st["fingerprint"] and first["compare"]["level"] == "none"
        assert st["latest"]["id"] == first["id"] and st["alert"] is None
        audit = c.get("/api/monitor/audit").json()
        assert any(a["action"] == "redteam_start" and a["actor"] == "자동 점검" and a.get("trigger") == "change" for a in audit)
        assert any(a["action"] == "redteam_compare" and a["job"] == first["id"] for a in audit)
    with serve() as c:                                                     # 같은 설정으로 다시 켬: 돌리지 않는다
        c.post("/api/auth/login", json=dict(username="privacy1", password=PW))
        st = c.get("/api/redteam/auto").json()
        assert st["decision"] == "same" and st["running"] is None and len(c.get("/api/redteam").json()) == 1
    eng.answer_style = False
    try:
        with serve() as c:                                                 # 답 형식을 끔: 설정이 바뀌어 다시 돌리고 앞 점검과 비교
            c.post("/api/auth/login", json=dict(username="privacy1", password=PW))
            st = c.get("/api/redteam/auto").json()
            assert st["decision"] == "started" and st["changes"] == ["대상 AI 답 형식: 켬 → 끔"]
            wait_done(c)
            second = c.get("/api/redteam").json()[0]
            assert second["id"] != first["id"] and second["compare"]["baseline"]["id"] == first["id"]
            assert second["compare"]["level"] in ("ok", "caution", "warn") and second["compare"]["changes"] == ["대상 AI 답 형식: 켬 → 끔"]
            assert [r["key"] for r in second["compare"]["rows"]] == ["viol", "utility", "overblock"]
            doc = TestClient(c.app)
            doc.post("/api/auth/login", json=dict(username="doctor1", password=PW))
            assert doc.get("/api/redteam/auto").status_code == 403
    finally:
        eng.answer_style = True


def test_rewrite_without_case_labels_or_with_the_raw_value_fails_the_recheck(world):
    """재작성기가 '사례N' 표기를 떨어뜨리면 다시 뽑아도 사례를 못 찾아 확인이 그냥 통과하던 문제:
    원래 값이 글자 그대로 남거나 사례 표기가 없으면 통과시키지 않고, 값만 바꾼 답을 낸다."""
    fake: FakeAnthropic = world["fake"]
    add_user(world["store"], "doctor_rw", "재작성의사", "clinician", "내과", PW)
    doc = login(world, "doctor_rw")
    _, sid = launch(doc, "T0014")
    sec = login(world, "privacy1")
    w = current_conv(sec, "재작성의사")
    try:
        fake.drop_labels, fake.drop_date = True, False             # 표기를 떨어뜨리고 시작일은 그대로 둔다
        b1 = doc.post("/api/cases/case-1/messages", json=dict(sessionId=sid, question=Q_DRUG, clientMessageId="w1")).json()
        fake.drop_date = True                                      # 표기만 떨어뜨린다 (시작일은 뺌)
        b2 = doc.post("/api/cases/case-1/messages", json=dict(sessionId=sid, question=Q_DRUG, clientMessageId="w2")).json()
    finally:
        fake.drop_labels, fake.drop_date = False, True
    for b in (b1, b2):
        assert b["assistantMessage"]["protection"]["releaseMode"] == "REWRITTEN_FALLBACK"
        assert "2004-06-16" not in json.dumps(b, ensure_ascii=False)
    answers = [m for m in sec.get(f"/api/watch/{w}/cases/case-1/session").json()["messages"] if m.get("protection")][-2:]
    failed = [{x["reason"] for c in m["protection"]["checks"] if not c["ok"] for x in c["cases"] if x["reason"]} for m in answers]
    assert {"RAW_VALUE_LEFT", "NO_CASE_FOUND"} <= failed[0] and failed[1] == {"NO_CASE_FOUND"}
    assert all(m["protection"]["checks"][-1]["ok"] for m in answers)


def _cases_by_rank(doc: TestClient) -> dict[int, dict]:
    pc = doc.get("/api/patient-context").json()
    return {c["similarityRank"]: c for c in doc.get("/api/cases", params=dict(patientContextId=pc["contextId"])).json()}


def test_live_first_answer_drops_only_the_case_that_fails(world):
    """실제 LLM 첫 답에서 한 사례의 약이 다른 문장에 다시 나와(소문자) 재작성 · 값 치환이 모두 다시 확인을 통과하지 못하면,
    답 전체를 거절하지 않고 그 사례만 빼고 낸다 (맥에서 본 S0010과 같은 경우)."""
    fake: FakeAnthropic = world["fake"]
    add_user(world["store"], "doctor_cd", "사례빼기의사", "clinician", "내과", PW)
    doc = login(world, "doctor_cd")
    fresh_first_answers(world)
    n0 = len(fake.calls)
    fake.echo_lower = "사례4"
    try:
        _, sid = launch(doc, "T0014")
    finally:
        fake.echo_lower = None
        fresh_first_answers(world)
    assert fake.roles()[n0:].count("rewriter") == 2              # 비교 갈래(C1S)는 같은 요청을 다시 보내지 않는다
    cases = _cases_by_rank(doc)
    assert cases[4]["diagnosis"] == "(비공개)" and all(cases[i]["diagnosis"] == "Acute bronchitis" for i in (1, 2, 3, 5))
    assert "cetirizine" not in json.dumps(cases, ensure_ascii=False).lower()
    sec = login(world, "privacy1")
    w = current_conv(sec, "사례빼기의사")
    d = sec.get(f"/api/monitor/sessions/{w}").json()
    for arm in ("C1", "C1S"):
        t0 = d["arms"][arm]["turns"][0]
        assert t0["mode"] == "CASE_DROPPED" and not t0["refused"] and t0["dropped"] == ["사례4"]
        assert d["arms"][arm]["k_series"]["사례4"][-1][1] == 461              # 아무것도 공개되지 않은 사례: 기준 집단 전체
    assert d["row"]["focus_case"] == "사례4" and d["row"]["k_now"] == 461
    n = sec.get(f"/api/watch/{w}/cases/case-4/narrowing").json()
    assert n["steps"] == [] and n["k"] == 461 and n["hidden"] and all(h["dropped"] for h in n["hidden"])
    hidden = sec.get(f"/api/monitor/sessions/{w}/hidden").json()
    assert {(x["case"], x["attribute"]) for x in hidden if x["dropped"]} == {("사례4", "DX"), ("사례4", "MED")}
    # 다른 사례는 이어서 물을 수 있다
    body = doc.post("/api/cases/case-1/messages", json=dict(sessionId=sid, question=Q_DRUG, clientMessageId="cd1")).json()
    assert body["assistantMessage"]["protection"]["releaseMode"] != "REFUSAL" and not redact.leaked_numbers(body)


def test_live_rewrite_retry_is_told_what_was_left(world):
    """다시 확인에 떨어진 재작성을 같은 지시로 다시 부르지 않는다: 두 번째 재작성에는 다시 뽑은 단서 중 남은 표현을 알려 준다."""
    fake: FakeAnthropic = world["fake"]
    add_user(world["store"], "doctor_rt", "재시도의사", "clinician", "내과", PW)
    doc = login(world, "doctor_rt")
    fresh_first_answers(world)
    n0 = len(fake.calls)
    fake.echo_lower, fake.heed_retry = "사례4", True
    try:
        launch(doc, "T0014")
    finally:
        fake.echo_lower, fake.heed_retry = None, False
        fresh_first_answers(world)
    prompts = [c["payload"]["messages"][-1]["content"] for c, r in zip(fake.calls[n0:], fake.roles()[n0:]) if r == "rewriter"]
    head = [x.rsplit("\n[바꿀 표현]\n", 1)[0] for x in prompts]
    assert len(head) == 2
    assert "6. 바꿀 값은 그 자리만이 아니라 답 전체에서 고친다" in head[0] and "'cetirizine'(사례4)" in head[0] and "10. 앞서" not in head[0]
    assert "8. 값을 빼서 내용이 없어진 줄" in head[0] and "9. 날짜를 빼더라도 기간" in head[0]
    assert "10. 앞서 고친 답을 다시 확인하니" in head[1] and "남은 표현: 'cetirizine hydrochloride 5 mg oral tablet'" in head[1]
    sec = login(world, "privacy1")
    w = current_conv(sec, "재시도의사")
    assert sec.get(f"/api/monitor/sessions/{w}").json()["arms"]["C1"]["turns"][0]["mode"] == "REWRITTEN"
    assert _cases_by_rank(doc)[4]["diagnosis"] == "Acute bronchitis"           # 사례째로 빼지 않고 약만 가렸다


def test_release_floor_follows_the_ontology_chain(world):
    """실제 LLM 갈래의 최소 공개 단위: 93세 → 90~94세, 노드 90~99세로 센 '93-98세' → 90~99세, 2018-03-24 → 2018-03.
    글자가 노드 이름과 같으면 그대로 둔다. 후보 수로 정한 가림은 건드리지 않는다."""
    from medical.defense import CasePlan, Decision
    from webdemo.backend.review import RuleDefender
    inner = world["eng"].ctx["staged"].defender
    data = inner.data
    day = next(n for n in data.N if str(n).startswith("PERIOD_PROCEDURE_START_UTC_DAY_2018-03-24"))
    rows = [("AGE", "AGE_Y93", "93세", "allow"), ("AGE", "AGE10_90", "93-98세", "allow"), ("AGE", "AGE10_90", "90~99세", "allow"),
            ("PERIOD", day, "2018-03-24", "allow"), ("DX", "DX_ICD_CODE_J20", "Acute bronchitis", "allow"), ("AGE", "AGE_Y98", "98세", "suppress")]
    decisions = [Decision(dict(attribute=a, node_id=n, event_group=None), dict(raw_value=r), act, n if act == "allow" else None, 9,
                          0, data.depth(n)) for a, n, r, act in rows]
    plan = CasePlan("사례1", 461, 9, False, decisions, 9)
    RuleDefender(inner, lambda ref: set(), floors=True)._floor(plan)
    got = [(x.action, data.label(x.to_node) if x.to_node else None, getattr(x, "floor", False)) for x in plan.decisions]
    assert got == [("generalize", "90~94세", True), ("generalize", "90~99세", True), ("allow", "90~99세", False),
                   ("generalize", "2018-03", True), ("allow", "Acute bronchitis", False), ("suppress", None, False)]
    assert plan.decisions[0].utility == round(1 - 1 / plan.decisions[0].max_steps, 4)



def test_live_age_goes_out_as_the_ontology_unit_without_the_rewriter(world):
    """실제 LLM이 나이를 '33-38세'처럼 쓰면(노드 30~39세로 셈) 답에는 노드 이름 '30~39세'로 나간다. 바꿀 것이 이것뿐이면
    재작성기를 부르지 않고 글자만 바꾼다(ROUNDED). 사례 노트에도 답에 나온 '30~39세'만 남는다."""
    fake: FakeAnthropic = world["fake"]
    add_user(world["store"], "doctor_ag", "나이의사", "clinician", "내과", PW)
    doc = login(world, "doctor_ag")
    launch(doc, "T0014")
    sid = doc.get("/api/cases/case-2/session").json()["sessionId"]
    n0 = len(fake.calls)
    fake.ages = {"사례2": "33-38세"}
    try:
        r = doc.post("/api/cases/case-2/messages", json=dict(sessionId=sid, question="사례2 환자의 나이를 알려 주세요", clientMessageId="ag1"))
        assert r.status_code == 200, r.text
        body = r.json()
    finally:
        fake.ages = {}
    text = "".join(x["text"] for x in body["assistantMessage"]["segments"])
    assert "33-38세" not in text and "30~39세" in text
    assert "rewriter" not in fake.roles()[n0:]
    assert body["assistantMessage"]["protection"]["releaseMode"] == "ROUNDED"
    sec = login(world, "privacy1")
    w = current_conv(sec, "나이의사")
    t1 = sec.get(f"/api/monitor/sessions/{w}").json()["arms"]["C1"]["turns"][1]
    assert t1["mode"] == "ROUNDED"
    ents = doc.get("/api/cases/case-2/disclosures").json()["entries"]
    assert [(e["action"], e["value"]) for e in ents if e["attribute"] == "AGE"] == [("generalize", "30~39세")]

def test_case_note_lists_only_values_the_released_answer_contains(world):
    """사례 노트는 계획이 허용한 값이 아니라 내보낸 답에 실제로 나온 값(답의 글자)만 적는다. 가린 값은 '비공개'로 남는다."""
    from webdemo.backend.clinic import ClinicDesk
    desk = ClinicDesk(world["eng"], "T0014")
    conv = desk.current
    cid = conv.case_of_ref("사례1")
    before = len(conv.slots[cid].history)
    rec = dict(turn=7, release_mode="REWRITTEN", cases_candidate_k={}, release_plans=[dict(ref="사례1", decisions=[
        dict(attribute="AGE", node_id="AGE_Y93", raw_value="93세", action="generalize", to_node="AGE5_90", k_raw=6, floor=True),
        dict(attribute="PERIOD", node_id="PERIOD_X_DAY_2018-03-24", raw_value="2018-03-24", action="allow", to_node="PERIOD_X_DAY_2018-03-24", k_raw=6),
        dict(attribute="REGION", node_id="REGION_X", raw_value="Norton, Massachusetts", action="suppress", to_node=None, k_raw=3)])],
        cases={"사례1": dict(normalized=[dict(attribute="AGE", node_id="AGE5_90", raw_value="90~94세", commit=True),
                                        dict(attribute="DX", node_id="DX_ICD_CODE_J20", raw_value="Acute bronchitis", commit=True)])})
    tf, entries = conv._absorb(rec, None)
    got = [(e["attribute"], e["action"], e["value"]) for e in entries[cid]]
    assert got == [("AGE", "generalize", "90~94세"), ("REGION", "suppress", None), ("DX", "allow", "Acute bronchitis")]
    assert len(conv.slots[cid].history) == before + 3 and "2018-03-24" not in json.dumps(entries, ensure_ascii=False)
    assert next(t for t in tf if t["attribute"] == "AGE")["floor"] is True

def test_live_redteam_runs_on_real_llm_path_and_is_kept(world, tmp_path):
    """레드팀 점검이 서버의 실제 LLM 경로(가짜 HTTP)로 돌고, 호출 수를 따로 세고, 끝나면 DB에 남는다. 멈춤도 된다."""
    sec = login(world, "privacy1")
    fake: FakeAnthropic = world["fake"]
    n0 = len(fake.calls)
    fake.drop_labels = True              # 재작성기가 사례 표기를 떨어뜨린다: 레드팀도 의료진 대화와 같은 다시 확인을 거치는지 본다
    try:
        j = sec.post("/api/redteam", json=dict(per_type=1, fuzzer="feedback")).json()
        assert j["live"] is True and j["trials"] == 3 and j["total"] == 9
        deadline = time.time() + 240
        while time.time() < deadline:
            j = sec.get(f"/api/redteam/{j['id']}").json()
            assert j["status"] != "done" or j["result"] is not None          # 끝났다고 알릴 때는 결과가 이미 있다
            if j["status"] not in ("queued", "running"):
                break
            time.sleep(0.1)
    finally:
        fake.drop_labels = False
    assert j["status"] == "done", j.get("error")
    out = Path(j["out"]) if Path(j["out"]).is_absolute() else ROOT / j["out"]
    # 레드팀 대상 AI도 의료진 대화와 같은 답 형식으로 부른다 (잰 조건 = 운영 조건). 실행 기록에 지시문 판을 남긴다
    targets = [c["payload"]["system"] for c in fake.calls[n0:] if c["payload"].get("system")]
    assert targets and all(s.endswith(ANSWER_STYLE) for s in targets)
    assert j["answer_style"] == "on"
    versions = json.loads((out / "trial요약.json").read_text(encoding="utf-8"))["versions"]
    assert versions["answer_style"] == ANSWER_STYLE_ID and versions["medicloak_release"] == RELEASE_VERSION
    recs = [json.loads(x) for x in (out / "턴기록.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    reasons = {c.get("reason") for r in recs for a in r.get("release_attempts") or [] for c in a.get("checks") or []}
    assert "NO_CASE_FOUND" in reasons and "rewriter" in fake.roles()[n0:]
    assert j["usage"]["calls"] > 0 and len(fake.calls) - n0 >= j["usage"]["calls"]       # 이 실행의 호출만 센다
    assert set(j["result"]["arms"]) == {"C0", "C1", "C1S"}
    assert world["eng"].live_usage()["calls"] < len(fake.calls)                           # 의료진 대화 호출 수와 섞이지 않는다
    stored = {x["id"]: x for x in world["store"].runs()}
    assert stored[j["id"]]["status"] == "done" and stored[j["id"]]["result"]["arms"]["C1"]["n"] == 3
    listed = sec.get("/api/redteam").json()
    assert listed[0]["id"] == j["id"] and listed[0]["result"] is None
    # 멈춤: 끝낸 trial까지만 남긴다
    j2 = sec.post("/api/redteam", json=dict(per_type=2, fuzzer="uniform")).json()
    assert sec.post(f"/api/redteam/{j2['id']}/cancel").status_code == 200
    deadline = time.time() + 120
    while time.time() < deadline:
        j2 = sec.get(f"/api/redteam/{j2['id']}").json()
        if j2["status"] not in ("queued", "running"):
            break
        time.sleep(0.2)
    assert j2["status"] == "cancelled" and j2["done"] < j2["total"]
    assert sec.post(f"/api/redteam/{j2['id']}/cancel").status_code == 409
    doc = login(world, "doctor1")
    assert doc.post("/api/redteam", json=dict(per_type=1)).status_code == 403



def test_answer_style_off_is_one_switch_and_does_not_reuse_styled_first_answers(world):
    """--answer-style off: 의료진 대화의 대상 AI 지시문에 답 형식이 없고, 보호 정책에 꺼짐으로 보인다.
    답 형식이 붙은 요청으로 받아 둔 첫 답은 키가 달라 다시 쓰지 않는다."""
    fake: FakeAnthropic = world["fake"]
    eng = world["eng"]
    add_user(world["store"], "doctor_ns", "형식있음", "clinician", "내과", PW)
    add_user(world["store"], "doctor_ns2", "형식없음", "clinician", "내과", PW)
    launch(login(world, "doctor_ns"), "T0014")             # 답 형식이 붙은 첫 답을 받아 둔다 (이미 있으면 그대로)
    n0 = len(fake.calls)
    eng.answer_style = False
    try:
        launch(login(world, "doctor_ns2"), "T0014")        # 같은 환자 · 목적이어도 형식이 다르면 새로 부른다
        targets = [c["payload"]["system"] for c in fake.calls[n0:] if c["payload"].get("system")]
        assert targets and not any(ANSWER_STYLE in s for s in targets)
        sec = login(world, "privacy1")
        assert sec.get("/api/monitor/policy").json()["answerStyle"] is False
    finally:
        eng.answer_style = True
    assert login(world, "privacy1").get("/api/monitor/policy").json()["answerStyle"] is True
    assert all(len(k) == 64 for k in eng.turn0_cache.answers)                          # 키는 해시: 지시문 원문을 두지 않는다
    assert not any("[검색된 사례]" in k for k in eng.turn0_cache.answers)


def test_live_suggestions_follow_the_query_purpose_without_reidentification_probes(world):
    """실제 LLM 대화의 예시 질문은 조회 목적(처방 참고)에 맞는 진료 질문이다. 나이 · 성별 · 거주 지역을 그대로 묻는 연구용 문장은 없다."""
    add_user(world["store"], "doctor_sg", "예시", "clinician", "내과", PW)
    doc = login(world, "doctor_sg")
    launch(doc, "T0014")
    sug = doc.get("/api/cases/case-2/suggestions").json()
    assert [x["scope"] for x in sug] == ["case"] * 4 + ["all"]
    assert all("사례2" in x["question"] for x in sug if x["scope"] == "case")
    text = " ".join(x["question"] for x in sug)
    assert "처방" in text and not any(w in text for w in ("거주", "성별", "연령", "나이"))


def test_all_cases_question_goes_without_case_prefix_and_is_marked(world):
    """'찾은 사례 전체'로 물으면 고른 사례 표기를 붙이지 않고 보내고, 메시지에 범위가 남는다. 판정은 그대로 사례마다 한다."""
    fake: FakeAnthropic = world["fake"]
    add_user(world["store"], "doctor_all", "전체질문", "clinician", "내과", PW)
    doc = login(world, "doctor_all")
    _, sid = launch(doc, "T0014")
    n0 = len(fake.calls)
    q = "찾은 사례들에서 공통으로 쓴 약과 사례마다 다른 약을 정리해 주세요."
    r = doc.post("/api/cases/case-1/messages", json=dict(sessionId=sid, question=q, clientMessageId="all1", scope="all"))
    assert r.status_code == 200, r.text
    target = next(c for c in fake.calls[n0:] if c["payload"].get("system"))
    assert target["payload"]["messages"][-1]["content"] == f"검색된 사례 전체에 대한 질문: {q}"
    assert r.json()["userMessage"]["scope"] == "all"
    assert doc.get("/api/cases/case-1/session").json()["messages"][-2]["scope"] == "all"
    bad = doc.post("/api/cases/case-1/messages", json=dict(sessionId=sid, question="약을 알려 주세요", clientMessageId="bad", scope="nope"))
    assert bad.status_code == 422


def test_question_progress_reports_live_calls_while_answering(world):
    """질문에 답하는 동안 /api/clinic/progress가 지금 단계와 실제 LLM 호출 수를 알려 준다 (화면 갈래의 호출만)."""
    fake: FakeAnthropic = world["fake"]
    add_user(world["store"], "doctor_pg", "진행표시", "clinician", "내과", PW)
    doc = login(world, "doctor_pg")
    _, sid = launch(doc, "T0014")
    assert doc.get("/api/clinic/progress").json() == {"active": False}
    got: list = []
    snaps: list = []
    fake.delay = 0.2
    try:
        t = threading.Thread(target=lambda: got.append(doc.post("/api/cases/case-1/messages",
                                                                 json=dict(sessionId=sid, question=Q_DRUG, clientMessageId="pg1"))))
        t.start()
        watcher = login(world, "doctor_pg")
        deadline = time.time() + 30
        while t.is_alive() and time.time() < deadline:
            p = watcher.get("/api/clinic/progress").json()
            if p["active"]:
                snaps.append(p)
            time.sleep(0.05)
        t.join(30)
    finally:
        fake.delay = 0.0
    assert got and got[0].status_code == 200, got and got[0].text
    assert snaps and max(x["calls"] for x in snaps) >= 2
    assert {x["label"] for x in snaps} & {"답을 쓰는 중", "답에 환자를 알아볼 수 있는 값이 있는지 확인하는 중"}
    assert doc.get("/api/clinic/progress").json() == {"active": False}


def test_residence_is_hidden_for_every_query_purpose(world):
    """거주 지역은 어느 조회 목적에도 진료 판단에 쓰지 않아, 후보 수와 관계없이 가린다 (조회 목적 규칙)."""
    fake: FakeAnthropic = world["fake"]
    add_user(world["store"], "doctor_rg", "지역질문", "clinician", "내과", PW)
    doc = login(world, "doctor_rg")
    _, sid = launch(doc, "T0014")
    q = "사례1 환자의 거주 지역을 알려 주세요"
    fake.regions = {"사례1": "Boston, Massachusetts"}
    try:
        r = doc.post("/api/cases/case-1/messages", json=dict(sessionId=sid, question=q, clientMessageId="rg1"))
    finally:
        fake.regions = {}
    assert r.status_code == 200, r.text
    msg = r.json()["assistantMessage"]
    assert "Boston" not in "".join(x["text"] for x in msg["segments"])
    region = [t for t in msg["protection"]["transformations"] if t["attribute"] == "REGION"]
    assert region and all(t["action"] == "suppress" and t["purpose"] for t in region)
    ents = doc.get("/api/cases/case-1/disclosures").json()["entries"]
    assert [e["action"] for e in ents if e["attribute"] == "REGION"] == ["suppress"]
    # 보안 담당자: 판정 기록에 조회 목적이 남고, 공개 승인 목록에는 오르지 않는다
    sec = login(world, "privacy1")
    w = current_conv(sec, "지역질문")
    rec = world["eng"].sessions[w].logs["C1"][-1]
    region_d = [d for p in rec["release_plans"] for d in p["decisions"] if d["attribute"] == "REGION"]
    assert region_d and all(d["action"] == "suppress" and d.get("purpose") for d in region_d)
    assert "medicloak-release-v5" == world["eng"].sessions[w].runs["C1"].trial["versions"]["medicloak_release"]
    hidden = sec.get(f"/api/monitor/sessions/{w}/hidden").json()
    items = hidden["items"] if isinstance(hidden, dict) else hidden
    assert not any(x["attribute"] == "REGION" for x in items)


def test_redteam_with_every_llm_call_failing_ends_as_error(world):
    """LLM 호출이 모두 실패한 질의 환자는 '깨끗함'으로 세지 않는다. 처음 세 명이 모두 실패하면 결과 없이 오류로 끝난다."""
    eng = world["eng"]
    good = eng.live_llm.inner
    eng.live_llm.inner = fake_llm(FakeAnthropic(fail_status=401))
    try:
        sec = login(world, "privacy1")
        j = sec.post("/api/redteam", json=dict(per_type=1, fuzzer="uniform")).json()
        deadline = time.time() + 120
        while time.time() < deadline:
            j = sec.get(f"/api/redteam/{j['id']}").json()
            if j["status"] not in ("queued", "running"):
                break
            time.sleep(0.1)
    finally:
        eng.live_llm.inner = good
    assert j["status"] == "error" and j["result"] is None and j["kept"] == 0 and j["llm_error_trials"] == 3
    assert "check-llm" in j["error"] and KEY not in json.dumps(j)
    assert {x["id"]: x for x in world["store"].runs()}[j["id"]]["status"] == "error"

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
        # 지난 대화에는 규칙 · 공개 승인을 걸거나 지울 수 없다 (500이 아니라 409)
        assert sec.post(f"/api/monitor/sessions/{sid}/rules", json=dict(case="사례1", attribute="MED")).status_code == 409
        assert sec.delete(f"/api/monitor/sessions/{sid}/rules/R1").status_code == 409
        assert sec.post(f"/api/monitor/sessions/{sid}/approve", json=dict(items=["1:사례1:0"], reason="지난 대화 값 공개")).status_code == 409
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


def test_turn0_llm_replays_per_arm_and_resends_retries():
    """첫 답(턴 0): 세 갈래가 같은 실제 LLM 답을 쓰되(갈래마다 처음부터 다시 꺼냄), 한 갈래 안에서 같은 요청을 다시 보내면 새로 부른다."""
    from webdemo.backend.live import Turn0LLM

    class Live:
        def __init__(self):
            self.n = 0

        def complete(self, role, system, messages, **kw):
            self.n += 1
            return f"live{self.n}"

    class Det:
        def complete(self, role, system, messages, **kw):
            return "det"

    live = Live()
    t = Turn0LLM(live, Det())
    ask = lambda role="target": t.complete(role, "sys", [dict(role="user", content="q")])
    t.next_arm()
    assert [ask(), ask()] == ["live1", "live2"]          # 같은 갈래 안의 다시 묻기(재시도)는 캐시가 아니라 새 호출
    t.next_arm()
    assert [ask(), ask(), ask()] == ["live1", "live2", "live3"]
    assert ask("mutator") == "det" and live.n == 3       # 질문 만들기 역할은 결정적 응답기


S0010_REWRITTEN = """# 현재 환자와 유사한 사례들의 처방 내역

현재 환자(21세 남성, Dental caries, ADHD, Acute pharyngitis)와 유사한 사례들의 처방 약물을 정리하면 다음과 같습니다:

## **사례2** (가장 유사 - 남성, 유사 연령대)
- **penicillin V potassium 250 MG Oral Tablet** (2회 처방)
  - Streptococcal pharyngitis 치료
- **sodium fluoride 0.0272 MG/MG Oral Gel** (2회 처방)
  - 치아 우식증 관리

## **사례3** (남성, 유사 연령대 - 22세)
- **sodium fluoride 0.0272 MG/MG Oral Gel** (2회 처방)
  - Diseases of oral cavity and salivary glands (K00-K14) 관리

## **사례1, 사례4, 사례5**
- **sodium fluoride 0.0272 MG/MG Oral Gel** (반복 처방)
  - 모든 사례에서 dental caries 관리에 사용

---

**주목할 점:** 현재 고려 중인 **naproxen Oral Tablet**은 **사례2**와 **사례5**에서 통증 관리(각각 발목 염좌, 중이염)에 사용된 경험이 있습니다."""


def test_drop_cases_and_rewrite_rules_unit():
    """사례 단위로 빼기 (실제 LLM 첫 답 S0010의 재작성 답, 결정적 응답기 줄 모양, 문단) · 재작성 지시 보강."""
    from medical.prompts import PROMPTS
    from webdemo.backend.review import drop_cases, rewrite_rules, short_name
    out = drop_cases(S0010_REWRITTEN, {"사례2"})
    assert out is not None and "사례2" not in out and "penicillin" not in out and "naproxen" not in out and "Streptococcal" not in out
    assert "## **사례3**" in out and "## **사례1, 사례4, 사례5**" in out and "현재 환자(21세 남성" in out and not out.endswith("---")
    lines = "사례1 · [기록5] 진단: Acute bronchitis\n사례4 · [기록3] 진단: Acute bronchitis\n사례4 · [기록9] 처방 약: (비공개)\n사례5 · [기록7] 진단: Acute bronchitis"
    assert drop_cases(lines, {"사례4"}) == "사례1 · [기록5] 진단: Acute bronchitis\n사례5 · [기록7] 진단: Acute bronchitis"
    prose = "사례1 환자는 A를 처방받았습니다. 사례4 환자는 남성입니다. 이 환자는 2019년부터 B를 썼습니다. 사례5 환자는 C를 처방받았습니다."
    assert drop_cases(prose, {"사례4"}) == "사례1 환자는 A를 처방받았습니다. 사례5 환자는 C를 처방받았습니다."
    nested = "## 사례3\n- 사례2와 같은 약을 썼습니다.\n  - 2020-03-07에 시작\n- 사례3은 B를 썼습니다."
    assert drop_cases(nested, {"사례2"}) == "## 사례3\n- 사례3은 B를 썼습니다."
    assert drop_cases(lines, {"사례1", "사례4", "사례5"}) is None          # 남는 사례가 없으면 거절 그대로
    assert drop_cases(lines, {"사례2"}) is None                              # 바뀐 것이 없으면 거절 그대로
    assert [short_name(x) for x in ("naproxen sodium 220 MG Oral Tablet", "sodium fluoride 0.0272 MG/MG Oral Gel", "loratadine")] == \
        ["naproxen", "sodium fluoride", None]
    prompt = PROMPTS["rewriter"].format(changes="1. 사례2의 MED 'naproxen sodium 220 MG Oral Tablet' → 빼기", response="원 답")
    ch = [dict(case_ref="사례2", attribute="MED", raw_value="naproxen sodium 220 MG Oral Tablet", action="suppress"),
          dict(case_ref="사례5", attribute="MED", raw_value="fexofenadine hydrochloride 30 MG Oral Tablet", action="generalize")]
    r1, r2 = rewrite_rules(prompt, ch), rewrite_rules(prompt, ch, "- 사례2 환자를 알아볼 수 있는 표현이 아직 남았다.")
    assert r1.index("6. 바꿀 값은") < r1.rindex("\n[바꿀 표현]\n") and "'naproxen'(사례2)" in r1 and "fexofenadine'(" not in r1
    assert "10. 앞서" not in r1 and r2.index("10. 앞서 고친 답을") < r2.rindex("\n[바꿀 표현]\n")
    assert r1.endswith("[원 답변]\n원 답") and rewrite_rules("다른 지시문", ch) == "다른 지시문"

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
    main(["--db", str(db), "init", "--initial-password", "abcd-efgh-1234"])
    out = capsys.readouterr().out
    acc = db.parent / "initial_accounts.txt"
    assert "doctor1" in out and "privacy1" in out and acc.exists() and "abcd-efgh-1234" in acc.read_text(encoding="utf-8")
    assert stat.S_IMODE(os.stat(acc).st_mode) == 0o600 and "데모" not in out + acc.read_text(encoding="utf-8")
    db2 = tmp_path / "y" / "mc.db"                                        # 예전 옵션 이름도 받는다
    main(["--db", str(db2), "init", "--demo-password", "ijkl-mnop-5678"])
    capsys.readouterr()
    assert "ijkl-mnop-5678" in (db2.parent / "initial_accounts.txt").read_text(encoding="utf-8")
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


# ── 의료진 체험 반영 (2026-11-05, ADR-0029) ─────────────────────

def _case_blocks(system: str) -> dict[int, str]:
    return {int(n): b for n, b in re.findall(r"\[사례(\d+)\]\n(.*?)(?=\n\n\[사례|\Z)", system.split("[검색된 사례]", 1)[1], re.S)}


def _med_of(block: str) -> str | None:
    m = re.search(r"\] 처방 약: (.+?)\.\n", block)
    return m.group(1) if m else None


def test_case_missing_from_first_answer_is_not_called_hidden_and_all_scope_values_are_counted(world):
    """
    첫 답이 말하지 않은 사례는 '비공개'가 아니라 '첫 답에 나오지 않음'으로 보인다. '찾은 사례 전체' 질문 답에 그 사례의 약이 나오고
    추출기가 그 사례를 빠뜨려도, 사례 문서 대조(textguard)가 관측을 더해 판정 · 사례 노트 · 사례 목록 제목에 들어간다.
    """
    fake: FakeAnthropic = world["fake"]
    fresh_first_answers(world)
    picked: dict[str, int] = {}

    def hook(system: str, user: str, messages: list) -> str | None:
        blocks = _case_blocks(system)
        with_med = [n for n, b in sorted(blocks.items()) if _med_of(b)]
        if len(with_med) < 2:
            return None
        hide = with_med[-1]
        picked["n"] = hide
        if len(messages) == 1 and not re.search(r"사례\s*\d", user):            # 첫 답: 이 사례만 말하지 않는다
            return "\n".join(f"사례{n} 환자의 진단은 {re.search(r'] 진단: (.+?)\.', b).group(1)}이고, {_med_of(b)}를 처방받았습니다."
                             for n, b in sorted(blocks.items()) if n != hide and _med_of(b) and re.search(r"] 진단: (.+?)\.", b))
        if user.startswith("검색된 사례 전체에 대한 질문"):                    # 추출기(가짜)는 '사례N은 …만' 꼴을 뽑지 못한다
            return f"검색된 사례의 약을 정리했습니다. 사례{hide}은 {_med_of(blocks[hide])}만 처방받았고 다른 약은 없습니다."
        return None

    fake.target_hook = hook
    try:
        add_user(world["store"], "doctor_g1", "문서대조", "clinician", "내과", PW)
        doc = login(world, "doctor_g1")
        _, sid = launch(doc, "T0014")
        n = picked["n"]
        ctx_id = doc.get("/api/patient-context").json()["contextId"]
        cards = {c["caseId"]: c for c in doc.get(f"/api/cases?patientContextId={ctx_id}").json()}
        assert cards[f"case-{n}"]["diagnosis"] == "첫 답에 나오지 않음" and cards[f"case-{n}"]["mentioned"] is False
        assert "비공개" not in cards[f"case-{n}"]["description"]
        r = doc.post("/api/cases/case-1/messages", json=dict(sessionId=sid, question="찾은 사례들에서 쓴 약을 정리해 주세요.",
                                                             clientMessageId="g1", scope="all"))
        assert r.status_code == 200, r.text
    finally:
        fake.target_hook = None
        fresh_first_answers(world)
    sec = login(world, "privacy1")
    w = current_conv(sec, "문서대조")
    rec = world["eng"].sessions[w].logs["C1"][-1]
    added = [o for o in rec["raw_observations"] if o.get("source") == "DOC_MATCH"]
    assert any(o["case_ref"] == f"사례{n}" and o["attribute"] == "MED" for o in added)
    assert all(isinstance(o.get("evidence_spans"), list) for o in rec["raw_observations"])
    assert any(p["ref"] == f"사례{n}" and any(d["attribute"] == "MED" for d in p["decisions"]) for p in rec["release_plans"])
    ents = doc.get(f"/api/cases/case-{n}/disclosures").json()["entries"]
    assert any(e["attribute"] == "MED" and e["turn"] == rec["turn"] for e in ents)
    cards = {c["caseId"]: c for c in doc.get(f"/api/cases?patientContextId={ctx_id}").json()}
    assert cards[f"case-{n}"]["description"].startswith("처방 약") or "비공개" in cards[f"case-{n}"]["description"]


def test_durations_show_as_ranges_whatever_the_scope_and_go_to_the_case_note(world):
    """일수 · 주 같은 상대 기간은 묻는 범위와 상관없이 범위로만 나가고(방어 갈래), 사례 노트에 '기간'으로 남는다. 방어 없음(C0)은 그대로."""
    fake: FakeAnthropic = world["fake"]

    def hook(system: str, user: str, messages: list) -> str | None:
        if user.startswith("검색된 사례 전체에 대한 질문"):
            return "진단 기간을 보면 사례1은 약 12일, 사례2는 약 17일 동안 진단이 유지되었습니다."
        if "복용 기간" in user:
            return "사례1 환자는 약 12일 동안 약을 복용했습니다."
        return None

    fake.target_hook = hook
    try:
        add_user(world["store"], "doctor_du", "기간범위", "clinician", "내과", PW)
        doc = login(world, "doctor_du")
        _, sid = launch(doc, "T0014")
        a = doc.post("/api/cases/case-1/messages", json=dict(sessionId=sid, question="사례들이 보통 얼마나 걸렸나요?", clientMessageId="d1", scope="all")).json()
        b = doc.post("/api/cases/case-1/messages", json=dict(sessionId=sid, question="사례1 환자의 복용 기간은?", clientMessageId="d2", scope="case")).json()
    finally:
        fake.target_hook = None
    text_a = "".join(x["text"] for x in a["assistantMessage"]["segments"])
    text_b = "".join(x["text"] for x in b["assistantMessage"]["segments"])
    assert "약 1~2주" in text_a and "약 2~4주" in text_a and "12일" not in text_a and "17일" not in text_a
    assert "약 1~2주" in text_b and "12일" not in text_b
    tf = a["assistantMessage"]["protection"]["transformations"]
    assert {(t["caseRef"], t["disclosedValue"]) for t in tf if t["attribute"] == "DURATION"} == {("사례1", "약 1~2주"), ("사례2", "약 2~4주")}
    assert any(s.get("kind") == "disclosure" and s["text"] == "약 2~4주" for s in a["assistantMessage"]["segments"])
    notes = doc.get("/api/cases/case-1/disclosures").json()["entries"]
    assert [e["value"] for e in notes if e["attribute"] == "DURATION"] == ["약 1~2주", "약 1~2주"]
    sec = login(world, "privacy1")
    w = current_conv(sec, "기간범위")
    s = world["eng"].sessions[w]
    assert "12일" in s.logs["C0"][-1]["response_text"] and "12일" not in s.logs["C1"][-1]["response_text"]


def test_extraction_guard_unit():
    """추출기 출력 바로잡기 · 문서 대조 · 기간 범위 · 사례 귀속 (textguard)."""
    from medical.defense import apply_changes_deterministic
    from webdemo.backend import textguard as G
    resp = "검색된 5개 사례 모두에서 쓴 약은 acetaminophen 325 MG Oral Tablet입니다.\n\n사례3은 acetaminophen만 처방받았고 다른 약은 없습니다. 이 환자는 여성입니다."
    docs = [dict(doc_id=f"D{i}", text=f"t{i}", fact_rows=[dict(attribute="MED", span_text="acetaminophen 325 MG Oral Tablet", node_id="X"),
                                                        dict(attribute="SEX", span_text="여성", node_id="SEX_FEMALE")]) for i in range(1, 6)]
    found = [dict(attribute="MED", raw_value="acetaminophen 325 MG Oral Tablet", evidence_spans="acetaminophen 325 MG Oral Tablet입니다",
                  case_ref="사례1", subject="TARGET_PATIENT")]
    out = json.loads(G.fix_extraction(json.dumps(found, ensure_ascii=False), resp, docs))
    assert out[0]["evidence_spans"] == ["acetaminophen 325 MG Oral Tablet입니다"]
    added = {(o["case_ref"], o["attribute"]) for o in out if o.get("source") == "DOC_MATCH"}
    assert added == {("사례2", "MED"), ("사례3", "MED"), ("사례4", "MED"), ("사례5", "MED")}       # 사례1은 이미 있음, 성별은 그 사례 문장에서만
    assert G.fix_extraction("추출 못 함", resp, docs) == "추출 못 함"
    assert G.clean_spans("ab") == ["ab"] and G.clean_spans(["a", " xy "]) == ["xy"] and G.clean_spans(None) == []
    # 글자열 근거를 쪼개지 않으므로 값 치환이 글자 하나씩 바꾸지 않는다
    text = "사례1 환자는 lisinopril 10 MG Oral Tablet을 복용했습니다."
    ch = [dict(raw_value="simvastatin 20 MG Oral Tablet", evidence_spans=G.clean_spans("simvastatin 20 MG Oral Tablet"), action="suppress", to_label=None)]
    assert len(apply_changes_deterministic(text, ch)) == len(text)
    assert G.case_numbers("사례1, 2, 4는 같은 약") == [1, 2, 4] and G.case_numbers("사례1, 2021-05-27부터") == [1] and G.case_numbers("사례1, 2회") == [1]
    for raw, want in [("약 12일 동안", "약 1~2주 동안"), ("이틀 동안 입원", "3일 이내 입원"), ("3월 15일", "3월 15일"), ("1일 2회", "1일 2회"),
                      ("2019년", "2019년"), ("2주 간격", "2주 간격"), ("10일 만에", "1~2주 만에"), ("약 1년 동안", "약 1년 동안")]:
        assert G.coarsen_durations(raw)[0] == want, raw
    assert G.duration_mentions("사례1은 약 1~2주, 사례2는 약 2~4주 동안 유지되었습니다.", 5) == [("사례1", "약 1~2주"), ("사례2", "약 2~4주")]


def test_front_calls_do_not_wait_for_background_calls():
    """의료진 질문 호출은 뒤에서 이미 보낸 비교 갈래 · 미리 준비 호출이 끝나기를 기다리지 않는다. 뒤 호출은 앞 호출에 양보한다."""
    from webdemo.backend.live import _Slots
    s = _Slots(1)
    s.acquire(back=True)                                  # 뒤 호출 하나가 나가 있다
    done = threading.Event()
    threading.Thread(target=lambda: (s.acquire(back=False), done.set())).start()
    assert done.wait(1.0)                                 # 앞 호출은 바로 나간다
    late = threading.Event()
    threading.Thread(target=lambda: (s.acquire(back=True), late.set())).start()
    assert not late.wait(0.2)                             # 앞 호출이 나가 있는 동안 새 뒤 호출은 기다린다
    s.release(back=False)
    s.release(back=True)
    assert late.wait(1.0)
    s.release(back=True)


def test_recent_visit_binding_uses_latest_visit_and_active_comorbidities(world):
    """운영 모드 진료 기준은 가장 최근 진료다: 진료일 · 주진단 · 그날 이어지던 동반질환이 환자 요약과 검색 기준일에 들어간다."""
    import random as _r

    from webdemo.backend.clinic import ClinicConversation
    from webdemo.backend.visit import visit_binding
    eng = world["eng"]
    pid = next(p for p in eng.data.by_pat if p.startswith("0e7fe2c7"))
    b = visit_binding(eng.data, pid, "PRESCRIPTION", _r.Random(0))
    assert b["index_date"] == max(e["start"][:10] for e in eng.data.by_pat[pid] if e["event_type"] == "CONDITION")
    assert "Essential (primary) hypertension" in b["active"] and b["panel"]["PANEL_COMORBIDITY"] != "없음"
    tid = next(t for t, (p, q) in eng.trial_of.items() if p == pid and q == "PRESCRIPTION")
    old = eng.binding(tid)
    eng.recent_visit = True
    try:
        assert eng.binding(tid)["index_date"] == b["index_date"] and old["index_date"] < b["index_date"]
        s = eng.new_session(tid, source="clinic", llm_mode="live")
        pc = ClinicConversation(eng, s).patient_context()
    finally:
        eng.recent_visit = False
    assert s.prefix.binding["visit"] == "recent" and pc["visitDate"] == b["index_date"]
    assert "Essential (primary) hypertension" in pc["comorbidities"]
    assert [x["label"] for x in pc["aiSummary"]] == ["연령 / 성별", "주진단", "동반질환", "고려 중인 처치", "조회 목적"]
    assert pc["searchBasis"]["until"] == b["index_date"] and pc["searchBasis"]["medications"] >= 2


def test_prefetch_makes_the_first_answer_ahead_and_launch_reuses_it(world):
    """EMR에서 고른 환자 · 목적의 첫 답을 미리 만들어 두면, 열 때 LLM을 다시 부르지 않는다. 조회 기록에 환자 번호가 남는다."""
    fake: FakeAnthropic = world["fake"]
    fresh_first_answers(world)
    add_user(world["store"], "doctor_pf", "미리준비", "clinician", "내과", PW)
    doc = login(world, "doctor_pf")
    wl = doc.get("/api/emr/worklist").json()
    row = next(x for x in wl if any(p["trialId"] == "T0016" for p in x["purposes"]))
    purpose = next(p["purpose"] for p in row["purposes"] if p["trialId"] == "T0016")
    r = doc.post("/api/emr/prefetch", json=dict(fhirId=row["fhirId"], purpose=purpose))
    assert r.status_code == 200 and r.json()["status"] == "started"
    wait_prefetch(world)
    n0 = len(fake.calls)
    r = doc.post("/api/emr/launch", json=dict(fhirId=row["fhirId"], purpose=purpose))
    assert r.status_code == 200, r.text
    roles = fake.roles()[n0:]
    assert roles == [], roles          # 첫 답 · 추출 · 공개 처리(재작성 · 다시 확인)까지 미리 받은 것을 그대로 쓴다
    assert doc.post("/api/emr/prefetch", json=dict(fhirId=row["fhirId"], purpose=purpose)).json()["status"] == "current"
    hist = doc.get("/api/clinic/history").json()
    assert hist[0]["current"] and hist[0]["patientId"] == row["fhirId"][:8]


def test_serve_options_for_visit_basis_and_prefetch():
    """serve 옵션: 진료 기준(--visit)과 첫 답 미리 준비(--prefetch). 기본은 가장 최근 진료 · 미리 준비 켬."""
    import argparse

    from medicloak.cli import _defaults, _serve_args
    ap = argparse.ArgumentParser()
    _serve_args(ap)
    a = ap.parse_args([])
    assert a.visit == "recent" and a.prefetch == "on"
    a = ap.parse_args(["--visit", "research", "--prefetch", "off"])
    assert a.visit == "research" and a.prefetch == "off"
    d = _defaults(argparse.Namespace())
    assert d.visit == "recent" and d.prefetch == "on"


def test_doctor_picks_todays_diagnosis_and_prefetch_is_audited(world):
    """
    오늘 진단 고르기: 그 환자의 진단 목록에서 고르면 그 진료일을 기준으로 연다 (가장 최근 진료와 오늘 볼 문제가 다를 때).
    미리 준비도 고른 진단으로 하고, 열기 전에 대상 AI로 나간 일은 감사 기록에 남는다.
    """
    fake: FakeAnthropic = world["fake"]
    fresh_first_answers(world)
    add_user(world["store"], "doctor_dx", "진단고르기", "clinician", "내과", PW)
    doc = login(world, "doctor_dx")
    row = next(x for x in doc.get("/api/emr/worklist").json() if x["fhirId"].startswith("0c6f6684"))
    v = doc.get("/api/emr/visits", params=dict(fhirId=row["fhirId"])).json()["purposes"]["PRESCRIPTION"]
    assert sum(c["isDefault"] for c in v) == 1 and len({c["label"] for c in v}) == len(v)
    ckd = next(c for c in v if c["label"] == "Chronic kidney disease stage 4")
    assert ckd["date"] == "2021-04-27" and ckd["item"] and not ckd["isDefault"]

    r = doc.post("/api/emr/prefetch", json=dict(fhirId=row["fhirId"], purpose="PRESCRIPTION", visitEvent=ckd["eventId"]))
    assert r.status_code == 200 and r.json()["status"] == "started"
    wait_prefetch(world)
    n0 = len(fake.calls)
    r = doc.post("/api/emr/launch", json=dict(fhirId=row["fhirId"], purpose="PRESCRIPTION", visitEvent=ckd["eventId"]))
    assert r.status_code == 200, r.text
    assert fake.roles()[n0:] == []                      # 고른 진단으로 미리 받은 첫 답을 그대로 쓴다
    pc = doc.get("/api/patient-context").json()
    assert pc["primaryDiagnosis"] == "Chronic kidney disease stage 4" and pc["visitDate"] == "2021-04-27" and pc["visitChosen"]
    assert pc["visitEvent"] == ckd["eventId"] and pc["plannedProcedure"] == ckd["item"]
    assert doc.post("/api/emr/prefetch", json=dict(fhirId=row["fhirId"], purpose="PRESCRIPTION",
                                                    visitEvent=ckd["eventId"])).json()["status"] == "current"

    # 기본 진료로 다시 열면 고른 진단의 대화를 다시 쓰지 않고 새로 연다
    r = doc.post("/api/emr/launch", json=dict(fhirId=row["fhirId"], purpose="PRESCRIPTION"))
    assert r.status_code == 200, r.text
    pc2 = doc.get("/api/patient-context").json()
    assert pc2["primaryDiagnosis"] != "Chronic kidney disease stage 4" and not pc2["visitChosen"]
    # 쓸 수 없는 진단 사건 · 외래 목록에 없는 환자
    bad = doc.post("/api/emr/launch", json=dict(fhirId=row["fhirId"], purpose="PRESCRIPTION", visitEvent="no-such-event"))
    assert bad.status_code == 400 and "관련 항목" in bad.json()["detail"]
    assert doc.get("/api/emr/visits", params=dict(fhirId="no-such-patient")).status_code == 404

    sec = login(world, "privacy1")
    assert sec.get("/api/emr/visits", params=dict(fhirId=row["fhirId"])).status_code == 403
    audit = sec.get("/api/monitor/audit").json()
    pre = next(a for a in audit if a["action"] == "emr_prefetch" and a.get("visit_dx") == "Chronic kidney disease stage 4")
    assert pre["purpose"] == "PRESCRIPTION" and pre["trial"] and pre["visit_date"] == "2021-04-27" and pre["session"] is None
    assert pre["calls"] >= 1 and pre["ok"] is True                   # 실제로 부른 호출 수
    assert any(a["action"] == "emr_launch" and a.get("visit_dx") == "Chronic kidney disease stage 4" for a in audit)


def test_prefetch_keeps_the_last_pick_while_one_is_running(world):
    """미리 준비가 도는 중에 다른 진단을 고르면 버리지 않고 이어서 한다 (마지막으로 고른 것 하나만). 열 때 LLM을 다시 부르지 않는다."""
    fake: FakeAnthropic = world["fake"]
    fresh_first_answers(world)
    add_user(world["store"], "doctor_q", "이어서", "clinician", "내과", PW)
    doc = login(world, "doctor_q")
    row = next(x for x in doc.get("/api/emr/worklist").json() if x["fhirId"].startswith("0c6f6684"))
    v = doc.get("/api/emr/visits", params=dict(fhirId=row["fhirId"])).json()["purposes"]["PRESCRIPTION"]
    others = [c for c in v if not c["isDefault"]][:2]
    fake.delay = 0.15                                    # 첫 미리 준비가 도는 동안 다음 두 개를 고른다
    try:
        first = doc.post("/api/emr/prefetch", json=dict(fhirId=row["fhirId"], purpose="PRESCRIPTION")).json()["status"]
        mid = doc.post("/api/emr/prefetch", json=dict(fhirId=row["fhirId"], purpose="PRESCRIPTION", visitEvent=others[0]["eventId"])).json()
        last = doc.post("/api/emr/prefetch", json=dict(fhirId=row["fhirId"], purpose="PRESCRIPTION", visitEvent=others[1]["eventId"])).json()
        assert (first, mid["status"], last["status"]) == ("started", "queued", "queued")
        wait_prefetch(world)
    finally:
        fake.delay = 0.0
    n0 = len(fake.calls)
    r = doc.post("/api/emr/launch", json=dict(fhirId=row["fhirId"], purpose="PRESCRIPTION", visitEvent=others[1]["eventId"]))
    assert r.status_code == 200, r.text
    assert fake.roles()[n0:] == []                       # 마지막으로 고른 진단은 미리 준비됐다
    sec = login(world, "privacy1")
    dx = [a.get("visit_dx") for a in sec.get("/api/monitor/audit").json() if a["action"] == "emr_prefetch" and a["actor"].startswith("이어서")]
    assert others[1]["label"] in dx and others[0]["label"] not in dx       # 사이에 고른 것은 버렸다


def test_monitor_flags_repeat_subjects_focuses_requests_and_ignores_double_sends(world):
    """
    관제: 같은 과거 환자를 다른 대화 · 다른 의료진이 물으면 표시한다(판정은 그대로). 답을 기다리는 요청이 있으면 그 사례부터 보인다.
    같은 답장 · 확인 요청을 바로 두 번 보내면 한 번만 간다. 의료진 질문 감사 기록에 지금 환자와 과거 환자의 기호가 남는다.
    """
    add_user(world["store"], "doc_r1", "반복일", "clinician", "내과", PW)
    add_user(world["store"], "doc_r2", "반복이", "clinician", "내과", PW)
    d1, d2 = login(world, "doc_r1"), login(world, "doc_r2")
    _, s1 = launch(d1, "T0014")
    d1.post("/api/cases/case-1/messages", json=dict(sessionId=s1, question=Q_DRUG, clientMessageId="rp1"))
    _, s2 = launch(d2, "T0014")
    d2.post("/api/cases/case-1/messages", json=dict(sessionId=s2, question=Q_DRUG, clientMessageId="rp2"))
    sec = login(world, "privacy1")
    w1, w2 = current_conv(sec, "반복일"), current_conv(sec, "반복이")
    rows = {r["id"]: r for r in sec.get("/api/monitor/overview").json()["sessions"]}
    for w in (w1, w2):
        rep = next(x for x in rows[w]["repeat_subjects"] if x["case"] == "사례1")
        assert rep["conversations"] >= 1 and rep["clinicians"] >= 2 and rep["tag"].startswith("P-")
        assert rows[w]["flag"] == "같은 과거 환자 다른 대화에서도 조회" and rows[w]["needs_review"]
    assert sec.get(f"/api/monitor/sessions/{w1}").json()["row"]["repeat_subjects"]
    q = next(a for a in sec.get("/api/monitor/audit").json() if a["action"] == "clinic_question" and a["session"] == w2)
    assert q["patient_tag"].startswith("P-") and [x["case"] for x in q["subjects"]] == ["사례1"]
    assert q["subjects"][0]["tag"] == rows[w2]["repeat_subjects"][0]["tag"]

    # 요청이 온 사례부터 보인다
    d2.post("/api/clinic/messages", json=dict(kind="access_request", text="사례 2의 처방 시기가 필요합니다.", caseId="case-2"))
    row2 = next(r for r in sec.get("/api/monitor/overview").json()["sessions"] if r["id"] == w2)
    assert row2["pending_request"] and row2["focus_case"] == "사례2" and row2["request_case"] == "사례2"
    # 같은 답장을 바로 두 번: 한 번만 간다
    n0 = len(sec.get(f"/api/monitor/sessions/{w2}/messages").json()["messages"])
    for _ in range(2):
        assert sec.post(f"/api/monitor/sessions/{w2}/messages", json=dict(kind="reply", text="확인하고 있습니다.", case="사례2")).status_code == 200
    assert len(sec.get(f"/api/monitor/sessions/{w2}/messages").json()["messages"]) == n0 + 1
    # 의료진에게 확인 요청을 바로 두 번: 메시지 · 감사 기록 모두 한 번
    a0 = sum(a["action"] == "ask_clinician" for a in sec.get("/api/monitor/audit").json())
    for _ in range(2):
        assert sec.post(f"/api/monitor/sessions/{w1}/review", json=dict(action="ask_clinician", note="진료에 필요한 내용이었는지 알려 주세요")).status_code == 200
    th = sec.get(f"/api/monitor/sessions/{w1}/messages").json()["messages"]
    assert sum(m["kind"] == "check_request" for m in th) == 1
    assert sum(a["action"] == "ask_clinician" for a in sec.get("/api/monitor/audit").json()) == a0 + 1
    # 두 번 누른 요청이 동시에 와도 한 번만 (같은 메시지 검사와 덧붙이기를 한 번에 한다)
    sec2 = login(world, "privacy1")
    n1 = len(sec.get(f"/api/monitor/sessions/{w2}/messages").json()["messages"])
    gate, codes = threading.Barrier(2), []

    def send(c: TestClient) -> None:
        gate.wait()
        codes.append(c.post(f"/api/monitor/sessions/{w2}/messages", json=dict(kind="reply", text="동시에 두 번 누른 답장", case="사례2")).status_code)

    ts = [threading.Thread(target=send, args=(c,)) for c in (sec, sec2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(30)
    assert codes == [200, 200]
    assert len(sec.get(f"/api/monitor/sessions/{w2}/messages").json()["messages"]) == n1 + 1
