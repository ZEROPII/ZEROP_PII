# 연구자 4인 검토 보강 (ADR-0032): 공개 원장 · 입력 단계 게이팅 · 공개 직전 문장 처리 · 답 시간 한도 · 미리 확인 한도 · 민감도 등급.
# 운영 모드(serve) 기본값처럼 보강을 모두 켠 엔진을 따로 만든다. 보강을 끈 기본 동작은 test_medicloak.py가 그대로 지킨다.

import json
import random
import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from medical.defense import ALLOW, GENERALIZE, SUPPRESS, SUPPRESSED_MARK, Decision
from tests.medicloak.fake_anthropic import FakeAnthropic
from tests.medicloak.test_medicloak import PW, Q_DRUG, current_conv, fake_llm, launch, login
from webdemo.backend import app as app_module
from webdemo.backend import clinic as clinic_module
from webdemo.backend import emr, redact
from webdemo.backend.app import Product, create_app
from webdemo.backend.auth import add_user, ensure_initial_accounts
from webdemo.backend.engine import Engine
from webdemo.backend.gate import GATE_NOTE, InputGate, span_phrase
from webdemo.backend.ledger import DisclosureLedger
from webdemo.backend.persist import Persist
from webdemo.backend.review import REFUSAL_TIMEOUT, TIMEOUT_TEXT
from webdemo.backend.sensitivity import categories, grade, minor_sud_patients
from webdemo.backend.store import Store
from webdemo.backend.textguard import count_bucket, post_release

DATE = "2004-06-16"                     # T0014 사례1 loratadine 첫 처방 시작일 (이 값 하나로 후보 1명)
DRUG = "loratadine 5 MG Chewable Tablet"


@pytest.fixture(scope="module")
def hard(tmp_path_factory):
    """test_medicloak의 world와 같되, 운영 모드 기본값처럼 보강을 켠 엔진 (답 시간 한도는 테스트마다 따로)."""
    w = tmp_path_factory.mktemp("hardening")
    store = Store(w / "mc.db")
    emr.load_csv(store, log=lambda s: None)
    ensure_initial_accounts(store, PW, w / "accounts.txt")
    paths = emr.export_csv(store, w / "snap", log=lambda s: None)
    fake = FakeAnthropic()
    eng = Engine(w / "engine", log=lambda s: None, paths=paths, live_llm=fake_llm(fake), live_label="실제 LLM (fake-model-1)",
                 first_id=Persist(store, None).next_id(), ledger=DisclosureLedger(store), input_gate=True, sensitivity=True, strict_k=10)
    app = create_app(eng, simulations=True, product=Product(store=store))
    base = TestClient(app)
    base.__enter__()
    yield dict(dir=w, store=store, fake=fake, eng=eng, app=app, paths=paths)
    base.__exit__(None, None, None)


def drug_and_date(system: str, user: str, messages: list) -> str | None:
    """
    대상 AI가 사례1의 약과 '첫 처방 시작일'을 말하는 답. 게이팅으로 지시문에는 그 날짜가 없지만(비공개),
    대상 AI가 어디선가 값을 꺼내 와도 출력 단계가 다시 막는지(두 겹) 보려고 날짜를 넣는다.
    """
    if user.startswith("사례1에 대한 질문"):
        return f"사례1 환자는 {DRUG}를 처방받았고, 첫 처방 시작일은 {DATE}입니다."
    return None


def target_systems(fake: FakeAnthropic, start: int) -> list[str]:
    return [c["payload"]["system"] for c in fake.calls[start:] if "[검색된 사례]" in (c["payload"].get("system") or "")]


def case_block(system: str, n: int) -> str:
    return system.split(f"[사례{n}]\n", 1)[1].split("\n\n[사례", 1)[0]


# ── 공개 원장 ──────────────────────────────────────────────
def test_ledger_records_across_conversations_and_survives_restart(tmp_path):
    store = Store(tmp_path / "ledger.db")
    now = [1_000_000.0]
    L = DisclosureLedger(store, window_days=1.0, clock=lambda: now[0])
    L.record("P1", [dict(attribute="DX", node_id="DX_A", event_group="사례1:dx1"), dict(attribute="MED", node_id="MED_B", event_group="사례1:e1")],
             conv_id="S1", user_id=7, turn=1)
    L.record("P1", [dict(attribute="PERIOD", node_id="PERIOD_X", event_group="사례1:e1")], conv_id="S1", user_id=7, kind="approval")
    L.record("P1", [dict(attribute="MED", node_id="MED_B", event_group="사례3:e1")], conv_id="S2", user_id=8, turn=2)
    assert L.version == 3
    # 다른 대화(S2)가 보는 값: 자기 대화 것은 빼고, 사건 묶음은 '지금 사례:공개한 대화:사건' (대화마다 사례 번호가 달라 떼고 다시 붙인다)
    got = {(x["attribute"], x["node_id"], x["event_group"]) for x in L.prior("P1", "사례2", exclude_conv="S2")}
    assert got == {("DX", "DX_A", "사례2:S1:dx1"), ("MED", "MED_B", "사례2:S1:e1"), ("PERIOD", "PERIOD_X", "사례2:S1:e1")}
    sm = L.summary("P1", exclude_conv="S9")
    assert (sm["values"], sm["conversations"], sm["users"], sm["approvals"]) == (3, 2, 2, 1)
    assert L.prior("P2", "사례1") == []
    with pytest.raises(ValueError):
        L.record("P1", [dict(attribute="DX", node_id="DX_A")], conv_id="S1", kind="guess")
    # 서버를 다시 켜도 DB에서 기간 창 안의 기록을 다시 읽는다
    L2 = DisclosureLedger(store, window_days=1.0, clock=lambda: now[0])
    assert len(L2.entries("P1")) == 4 and L2.describe()["persistent"]
    # 기간 창이 지나면 합치지 않는다 (0이면 기간 없이 모두)
    now[0] += 2 * 86400
    assert L.prior("P1", "사례2") == [] and len(DisclosureLedger(store, window_days=0, clock=lambda: now[0]).entries("P1")) == 4


def test_ledger_joins_disclosures_of_the_same_past_patient_across_clinicians(hard):
    """
    같은 질의 환자를 세 의사가 연다 (검색된 과거 환자가 같다). 의사 나는 의사 가의 첫 답 값까지 합쳐 판정받고,
    그 뒤 의사 가의 대화에서 승인 공개로 사례1이 후보 1명까지 좁혀지면 의사 나의 대화가 '다른 대화와 합치면 기준 아래'로 올라온다.
    그 뒤에 연 의사 다의 대화는 처음부터 그 값을 합쳐, 대상 AI에 사례1 기록을 가려 넣는다.
    """
    fake: FakeAnthropic = hard["fake"]
    eng, store = hard["eng"], hard["store"]
    for u, name in (("doc_la", "원장의사가"), ("doc_lb", "원장의사나"), ("doc_lc", "원장의사다")):
        add_user(store, u, name, "clinician", "내과", PW)
    a = login(hard, "doc_la")
    _, sid_a = launch(a, "T0014")
    fake.target_hook = drug_and_date
    try:
        body = a.post("/api/cases/case-1/messages", json=dict(sessionId=sid_a, question=Q_DRUG, clientMessageId="la1")).json()
    finally:
        fake.target_hook = None
    assert DATE not in json.dumps(body, ensure_ascii=False)                    # 출력 단계가 다시 막았다
    sec = login(hard, "privacy1")
    wa = current_conv(sec, "원장의사가")
    sa = eng.sessions[wa]
    pid = sa.patient_of("사례1")

    # 의사 나: 의사 가의 첫 답 값(진단 · 약)까지 합쳐 판정한다 (원장 단계가 후보 줄어든 과정의 맨 앞)
    b = login(hard, "doc_lb")
    n0 = len(fake.calls)
    _, sid_b = launch(b, "T0014")
    wb = current_conv(sec, "원장의사나")
    sb = eng.sessions[wb]
    assert sb.patient_of("사례1") == pid and sb.prior("사례1")
    assert "loratadine" in case_block(target_systems(fake, n0)[0], 1)         # 합쳐도 후보가 기준보다 많은 값은 그대로 넣는다
    assert sb.runs["C1"].cases["사례1"].committed and sb.k_global("사례1") > 5
    nar = sec.get(f"/api/watch/{wb}/cases/case-1/narrowing").json()
    assert nar["steps"][0]["prior"] and nar["steps"][0]["kBefore"] == nar["population"]

    # 의사 가의 대화에서 가린 시작일을 승인 공개 → 원장에 승인 기록
    item = next(x for x in sec.get(f"/api/monitor/sessions/{wa}/hidden").json() if x["case"] == "사례1" and x["attribute"] == "PERIOD")
    r = sec.post(f"/api/monitor/sessions/{wa}/approve", json=dict(items=[item["id"]], reason="처방 시작 시기가 약 조정 판단에 필요함", confirmLowK=True))
    assert r.status_code == 200, r.text
    assert r.json()["approval"]["k_after"] == {"사례1": 1}
    rows = [x for x in store.ledger_entries() if x["patient_id"] == pid and x["conv_id"] == wa]
    assert {x["kind"] for x in rows} == {"turn", "approval"} and all(x["user_id"] is not None for x in rows)
    assert any(x["attribute"] == "PERIOD" and x["kind"] == "approval" for x in rows)

    # 의사 나의 대화: 이 대화만 보면 기준 위지만, 다른 대화와 합치면 기준 아래
    assert sb.k_global("사례1") == 1 and sb.current_k("C1", "사례1") > 5
    ov = sec.get("/api/monitor/overview").json()
    row = next(x for x in ov["sessions"] if x["id"] == wb)
    assert row["global_low"] == ["사례1"] and row["needs_review"] and row["violated"] == [] and row["flag"] == "다른 대화와 합치면 기준 아래"
    assert ov["kpi"]["global_low"] >= 1
    d = sec.get(f"/api/monitor/sessions/{wb}").json()
    assert d["ledger"]["on"] and d["ledger"]["cases"]["사례1"]["approvals"] == 1 and d["ledger"]["cases"]["사례1"]["kGlobal"] == 1
    assert not redact.leaked_numbers(b.get("/api/cases/case-1/session").json())     # 의료진 화면에는 후보 수 · 원장 숫자가 없다

    # 의사 다: 원장 값으로 이미 한 명인 사례1은 기록을 모두 가려 넣고, 다른 사례는 그대로 판정한다
    c = login(hard, "doc_lc")
    n1 = len(fake.calls)
    launch(c, "T0014")
    system = target_systems(fake, n1)[0]
    assert system.count(GATE_NOTE) == 1
    one, two = case_block(system, 1), case_block(system, 2)
    assert "loratadine" not in one and "Acute bronchitis" not in one and one.count(SUPPRESSED_MARK) >= 10
    assert "진단: Acute bronchitis" in two
    wc = current_conv(sec, "원장의사다")
    rc = next(x for x in sec.get("/api/monitor/overview").json()["sessions"] if x["id"] == wc)
    assert rc["global_low"] == []                                              # 이 대화에서는 사례1 값이 나가지 않았다
    assert not eng.sessions[wc].runs["C1"].cases.get("사례1") or not eng.sessions[wc].runs["C1"].cases["사례1"].committed


# ── 입력 단계 게이팅 ──────────────────────────────────────────
def test_target_ai_gets_gated_case_records_from_the_first_answer(hard):
    """대상 AI에는 첫 답부터 지금 공개할 수 있는 값만 들어간다. 다음 질문도 그때 State로 다시 게이팅한다."""
    fake: FakeAnthropic = hard["fake"]
    add_user(hard["store"], "doc_gt", "게이팅의사", "clinician", "내과", PW)
    doc = login(hard, "doc_gt")
    n0 = len(fake.calls)
    _, sid = launch(doc, "T0024")
    systems = target_systems(fake, n0)
    assert systems and all(GATE_NOTE in s for s in systems)
    sec = login(hard, "privacy1")
    w = current_conv(sec, "게이팅의사")
    s = hard["eng"].sessions[w]
    raw_docs = "\n".join(d["text"] for d in s.prefix.docs)
    assert s.gated and SUPPRESSED_MARK not in raw_docs and SUPPRESSED_MARK in systems[0]
    # 가린 날짜는 원문에 있지만 지시문에는 없다 (나이는 5세 구간으로)
    hidden_dates = [r["span_text"] for d in s.prefix.docs for r in d["fact_rows"]
                    if r.get("attribute") == "PERIOD" and len(str(r.get("span_text"))) == 10 and str(r["span_text"]) not in systems[0]]
    assert hidden_dates and all(h in raw_docs for h in hidden_dates)
    assert "위 진단 당시 나이: " in systems[0] and not any(f"나이: {a}세." in systems[0] for a in range(1, 100))
    n1 = len(fake.calls)
    r = doc.post("/api/cases/case-1/messages", json=dict(sessionId=sid, question=Q_DRUG, clientMessageId="g1"))
    assert r.status_code == 200, r.text
    again = target_systems(fake, n1)
    assert again and GATE_NOTE in again[0]
    t = sec.get(f"/api/monitor/sessions/{w}").json()["arms"]["C1"]["turns"][-1]
    assert t["input_gate"] and {"ref", "allow", "generalize", "suppress"} <= set(t["input_gate"][0])
    assert sec.get("/api/monitor/policy").json()["protections"]["inputGate"]["on"]


def test_gate_counts_match_kcalc(hard):
    """게이팅의 후보 수(State 후보 ∩ 그 값을 가진 환자)는 kcalc가 그 값 하나를 더해 센 k와 같다."""
    eng = hard["eng"]
    g, kc = eng.gate, eng.gate.kc
    s = next(x for x in eng.sessions.values() if getattr(x, "source", None) == "clinic")
    rng = random.Random(7)
    checked = 0
    for i, d in enumerate(s.prefix.docs, 1):
        rows = [r for r in d["fact_rows"] if r.get("attribute") and r.get("node_id") in g.data.N]
        basis = [dict(attribute=r["attribute"], node_id=r["node_id"], event_group=f"사례{i}:b{j}") for j, r in enumerate(rng.sample(rows, 2))]
        cands, kb = g.candidates(basis)
        assert kb == kc.k(basis)["k"]
        for r in rng.sample(rows, min(12, len(rows))):
            exact = kc.k(basis + [dict(attribute=r["attribute"], node_id=r["node_id"], event_group="NEW:1")])["k"]
            assert g._k(r["attribute"], r["node_id"], cands, basis) == exact
            checked += 1
    assert checked >= 40


def test_gate_render_unit(hard):
    """문서 한 장: 값마다 판정해 바꾸고, 횟수는 범위로, 가린 날짜 사이 기간은 범위로 남긴다."""
    g = hard["eng"].gate
    s = next(x for x in hard["eng"].sessions.values() if getattr(x, "source", None) == "clinic")
    doc = s.prefix.docs[0]
    text, st = g.render(doc, [])
    assert st["allow"] + st["generalize"] + st["suppress"] == sum(1 for r in doc["fact_rows"] if r.get("attribute") and r.get("node_id"))
    assert text.count("\n") == doc["text"].count("\n")                         # 줄은 그대로 (번호 · 순서 유지)
    assert all(n == "1" for n in re.findall(r"총 (\d+)회", text))                # 횟수는 1회만 그대로, 나머지는 범위
    assert ("(시작부터 " in text) == (st["spans"] > 0)
    # 조회 목적에 필요 없는 단서(거주 지역)는 후보 수와 관계없이 가린다
    region = next(r for r in doc["fact_rows"] if r.get("attribute") == "REGION")
    assert g.decide([], "REGION", region["node_id"], blocked={"REGION"})[:2] == (SUPPRESS, None)
    assert count_bucket(1) == "1회" and count_bucket(3) == "2~3회" and count_bucket(7) == "4~9회" and count_bucket(12) == "10회 이상"
    assert span_phrase("2019-03-01", "2019-03-12") == "약 1~2주" and span_phrase("2019-03-12", "2019-03-01") is None


# ── 민감도 등급 ──────────────────────────────────────────────
def test_sensitive_values_need_more_candidates(hard):
    eng = hard["eng"]
    data, g = eng.gate.data, eng.gate
    assert categories(data, "DX_ICD_CODE_F1110") == {"SUD"}                   # 물질 사용 장애는 정신 건강과 겹쳐 세지 않는다
    assert categories(data, "DX_ICD_CODE_F02") == {"MENTAL"} and categories(data, "PROC_SCT_169553002") == {"REPRO"}
    assert categories(data, "DX_ICD_CODE_B20") == {"HIV"} and grade(data, "DX_ICD_CODE_D075") == 1
    assert categories(data, "DX_ICD_CODE_J20") == frozenset()
    plain = InputGate(g.kc, data, g.g, g.s, floors=True)                      # 민감도 없이
    # 치매 진단(후보 9명): 보통은 그대로지만 민감 값은 10명 이상이어야 하고, 민감하지 않은 상위 범주가 없어 가린다
    assert plain.decide([], "DX", "DX_ICD_CODE_F02")[0] == ALLOW
    assert g.decide([], "DX", "DX_ICD_CODE_F02") == (SUPPRESS, None, "strict")
    # 피임 패치(후보 9명): 민감하지 않은 상위 범주(G03)로 넓힌다. 암(등급 1)은 표시만 하고 기준은 그대로
    act, to, why = g.decide([], "MED", "MED_DF_1806237")
    assert (act, why) == (GENERALIZE, "strict") and to == "MED_ATC_G03" and not eng.sensitivity.strict(to)
    assert g.decide([], "DX", "DX_ICD_CODE_D075")[0] == ALLOW
    # 출력 단계도 같은 규칙: 그대로 내기로 한 치매 진단을 가린다 (strict 표시)
    s = next(x for x in eng.sessions.values() if getattr(x, "source", None) == "clinic")
    rd = s.runs["C1"].ctx.defender
    plan = SimpleNamespace(decisions=[Decision(dict(attribute="DX", node_id="DX_ICD_CODE_F02", event_group="사례1:dx9"), dict(raw_value="Dementia"),
                                               ALLOW, "DX_ICD_CODE_F02", 9, 0, 4)], risky=False)
    rd._strict(plan, [])
    assert plan.decisions[0].action == SUPPRESS and plan.decisions[0].strict and plan.risky
    assert eng.protections()["sensitivity"]["strictK"] == 10


def test_minor_substance_use_patients_are_left_out_of_retrieval():
    """미성년 시기 물질 사용 장애 진단이 있는 과거 환자를 찾는다 (이 합성 데이터에는 없어 작은 데이터로)."""
    data = SimpleNamespace(by_pat={
        "P-teen": [dict(event_type="CONDITION", code_node="DX_SUD", age_years_at_start="16")],
        "P-adult": [dict(event_type="CONDITION", code_node="DX_SUD", age_years_at_start="34")],
        "P-other": [dict(event_type="CONDITION", code_node="DX_FLU", age_years_at_start="12")],
    })
    data._sensitivity_cache = {"DX_SUD": frozenset({"SUD"}), "DX_FLU": frozenset()}
    assert minor_sud_patients(data) == {"P-teen"}
    assert minor_sud_patients(data, {"P-adult", "P-other"}) == set()


# ── 공개 직전 문장 처리 ───────────────────────────────────────
def test_post_release_sentence_rules_unit():
    out, ed = post_release("사례3은 acetaminophen만 처방받았고 다른 약물은 없습니다.", 5)
    assert out == "사례3은 acetaminophen을 처방받았습니다." and {e["kind"] for e in ed} == {"absence", "exclusive"}
    assert post_release("사례1 기록에는 loratadine 5 MG Chewable Tablet만 있습니다.", 5)[0] == "사례1 기록에는 loratadine 5 MG Chewable Tablet이 있습니다."
    assert post_release("사례5 환자는 타이레놀만을 복용했습니다.", 5)[0] == "사례5 환자는 타이레놀을 복용했습니다."
    out, ed = post_release("사례1 환자는 loratadine을 처방받았으며, 이는 알레르기 비염 때문으로 보입니다.", 5)
    assert out == "사례1 환자는 loratadine을 처방받았습니다." and ed[0]["kind"] == "speculation"
    assert post_release("사례2 환자는 같은 시술을 총 7회 받았습니다.", 5)[0] == "사례2 환자는 같은 시술을 총 4~9회 받았습니다."
    assert post_release("사례1 환자는 하루 2회 복용했습니다.", 5) == ("사례1 환자는 하루 2회 복용했습니다.", [])
    out, ed = post_release("사례1은 약 12일 동안 복용했습니다. 사례2는 3개월 간격으로 검사를 받았습니다.", 5)
    assert out == "사례1은 약 1~2주 동안 복용했습니다. 사례2는 1~3개월 간격으로 검사를 받았습니다."
    assert [e["kind"] for e in ed] == ["duration", "interval"]
    assert post_release("사례2 환자는 그 외 동반 질환이 없었습니다.", 5)[0] == ""          # 남는 말이 없으면 빈 답 (안내 문장으로 바꾼다)
    assert post_release("사례1 기록에는 처방 약이 없습니다. 사례2는 loratadine을 처방받았습니다.", 5)[0] == "사례2는 loratadine을 처방받았습니다."
    # 사례에 붙지 않은 일반 설명은 건드리지 않는다
    assert post_release("일반적으로 이 약은 하루 3회 복용합니다.", 5)[1] == []


def test_answer_without_record_support_is_trimmed_in_chat(hard):
    """기록으로 확인할 수 없는 '없음' · 짐작 문장은 공개 직전에 빼고, 의료진에게 그렇다고 알린다."""
    fake: FakeAnthropic = hard["fake"]
    add_user(hard["store"], "doc_pr", "문장의사", "clinician", "내과", PW)
    doc = login(hard, "doc_pr")
    _, sid = launch(doc, "T0014")

    def hook(system: str, user: str, messages: list) -> str | None:
        if "다른 약을 먹었나요" in user:
            return "사례1 환자는 그 외 다른 약은 없었습니다. 사례1 환자는 아마 증상이 가벼웠던 것으로 보입니다."
        return None

    fake.target_hook = hook
    try:
        b = doc.post("/api/cases/case-1/messages", json=dict(sessionId=sid, question="사례1 환자는 다른 약을 먹었나요?", clientMessageId="p1")).json()
    finally:
        fake.target_hook = None
    text = "".join(x["text"] for x in b["assistantMessage"]["segments"])
    assert "없었습니다" not in text and "아마" not in text and text.strip()
    sec = login(hard, "privacy1")
    w = current_conv(sec, "문장의사")
    rec = hard["eng"].sessions[w].logs["C1"][-1]
    assert {e["kind"] for e in rec["post_edits"]} >= {"absence"}
    t = sec.get(f"/api/monitor/sessions/{w}").json()["arms"]["C1"]["turns"][-1]
    assert t["post_edits"] and all(e.get("before") is None for e in t["post_edits"])     # 열람 전에는 지운 문장을 보이지 않는다


# ── 답 시간 한도 ─────────────────────────────────────────────
def test_answer_over_time_budget_is_refused_and_state_is_unchanged(hard):
    fake: FakeAnthropic = hard["fake"]
    add_user(hard["store"], "doc_tb", "시간의사", "clinician", "내과", PW)
    doc = login(hard, "doc_tb")
    _, sid = launch(doc, "T0014")
    sec = login(hard, "privacy1")
    w = current_conv(sec, "시간의사")
    s = hard["eng"].sessions[w]
    run = s.runs["C1"]
    before = {ref: len(c.committed) for ref, c in run.cases.items()}
    n_ledger = len(hard["store"].ledger_entries())
    run.budget = 0.02
    fake.delay, fake.target_hook = 0.03, drug_and_date
    try:
        b = doc.post("/api/cases/case-1/messages", json=dict(sessionId=sid, question=Q_DRUG, clientMessageId="t1")).json()
    finally:
        fake.delay, fake.target_hook, run.budget = 0.0, None, None
    prot = b["assistantMessage"]["protection"]
    assert prot["releaseMode"] == REFUSAL_TIMEOUT
    text = "".join(x["text"] for x in b["assistantMessage"]["segments"])
    assert DATE not in text and DRUG not in text
    assert text == TIMEOUT_TEXT and "식별 위험" not in text                 # 막은 까닭은 시간이다 (ADR-0043)
    assert {ref: len(c.committed) for ref, c in run.cases.items()} == before   # 확인하지 못한 답은 State에 넣지 않는다
    assert len(hard["store"].ledger_entries()) == n_ledger
    att = s.logs["C1"][-1]["release_attempts"]
    assert att[-1]["mode"] == REFUSAL_TIMEOUT and att[-1]["checks"][0]["reason"] == "TIME_BUDGET"


# ── 미리 확인 한도 ───────────────────────────────────────────
def test_preflight_is_rate_limited_for_clinicians_and_officers(hard, monkeypatch):
    monkeypatch.setattr(clinic_module, "PREFLIGHT_LIMIT", 3)
    monkeypatch.setattr(app_module, "PREFLIGHT_LIMIT", 3)
    monkeypatch.setattr(app_module, "OFFICER_PREFLIGHT_LIMIT", 3)
    add_user(hard["store"], "doc_pf", "미리의사", "clinician", "내과", PW)
    doc = login(hard, "doc_pf")
    _, sid = launch(doc, "T0014")
    outs = [doc.post("/api/cases/case-1/preflight", json=dict(sessionId=sid, question=Q_DRUG)).json() for _ in range(4)]
    assert [bool(o.get("limited")) for o in outs] == [False, False, False, True]
    assert outs[-1]["currentK"] is None and not redact.leaked_numbers(outs[-1])     # 안내 문구는 화면이 limited로 고른다
    sec = login(hard, "privacy1")
    w = current_conv(sec, "미리의사")
    audit = sec.get("/api/monitor/audit").json()
    assert sum(1 for a in audit if a["action"] == "preflight_limited" and a["session"] == w) == 1
    # 보안 담당자 '질문 미리 세기': 계정마다 한도, 부를 때마다 감사 기록 (질문 본문은 남기지 않는다)
    codes = [sec.post(f"/api/watch/{w}/cases/case-1/preflight", json=dict(sessionId=sid, question=Q_DRUG)).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    logs = [a for a in sec.get("/api/monitor/audit").json() if a["action"] == "watch_preflight" and a["session"] == w]
    assert len(logs) == 3 and all(a["question_chars"] == len(Q_DRUG) for a in logs)
    assert Q_DRUG not in json.dumps(logs, ensure_ascii=False)


# ── 설정 ────────────────────────────────────────────────────
def test_serve_turns_the_hardening_on_by_default():
    import argparse

    from medicloak.cli import _defaults, _serve_args
    ap = argparse.ArgumentParser()
    _serve_args(ap)
    a = ap.parse_args([])
    assert (a.ledger, a.ledger_window_days, a.input_gate, a.answer_budget, a.sensitivity, a.strict_k) == ("on", 90.0, "on", 90.0, "on", 10)
    a = ap.parse_args(["--ledger", "off", "--input-gate", "off", "--answer-budget", "0", "--sensitivity", "off"])
    assert (a.ledger, a.input_gate, a.answer_budget, a.sensitivity) == ("off", "off", 0.0, "off")
    d = _defaults(argparse.Namespace())
    assert (d.ledger, d.input_gate, d.answer_budget, d.sensitivity) == ("on", "on", 90.0, "on")


def test_policy_shows_the_hardening(hard):
    sec = login(hard, "privacy1")
    p = sec.get("/api/monitor/policy").json()
    pr = p["protections"]
    assert pr["ledger"]["on"] and pr["ledger"]["windowDays"] == 90.0 and pr["ledger"]["persistent"]
    assert pr["inputGate"]["on"] and pr["sensitivity"]["on"] and pr["sensitivity"]["excludedPatients"] == 0
    assert "다른 대화" in p["stateModeLabel"]


# ── 날짜 값 바로잡기 (RAG 재측정 R5 원본 대조에서 찾은 숨은 위반) ──────────────
def test_period_value_written_as_description_is_repaired():
    """
    실제 LLM 추출기가 날짜 단서의 값에 설명('Gingivitis 진단 시작')을 쓰고 날짜는 근거 문장에만 두면 정규화가 실패해 State에 안 들어가고,
    공개 판정이 그 날짜를 보지 못해 원 답 그대로 나갔다 (결과 ⑥ 기록 T0003 턴 4, 원본 대조 k 1). 근거 문장의 날짜를 값으로 쓴다.
    """
    from webdemo.backend.textguard import fix_extraction, fix_period_value
    resp = "사례1의 Gingivitis는 2017-11-20에 시작되었고, 2017-12-04에 종료되었습니다."
    obs = [dict(attribute="PERIOD", raw_value="Gingivitis 진단 시작", evidence_spans="2017-11-20에 시작되었고", time_role="CONDITION_START",
                case_ref="사례1"),
           dict(attribute="PERIOD", raw_value="Gingivitis 진단 종료", evidence_spans=["2017-12-04에 종료되었습니다"], time_role="CONDITION_END",
                case_ref="사례1"),
           dict(attribute="PERIOD", raw_value="2017-11-20", evidence_spans=["2017-11-20"], case_ref="사례1"),
           dict(attribute="DX", raw_value="Gingivitis", evidence_spans=["Gingivitis"], case_ref="사례1")]
    got = json.loads(fix_extraction(json.dumps(obs, ensure_ascii=False), resp, None))
    assert [o["raw_value"] for o in got] == ["2017-11-20", "2017-12-04", "2017-11-20", "Gingivitis"]
    assert got[0]["raw_value_was"] == "Gingivitis 진단 시작" and "raw_value_was" not in got[2]
    # 날짜가 둘 이상이거나 없으면 그대로 (어느 날짜인지 모른다)
    two = dict(attribute="PERIOD", raw_value="치료 기간", evidence_spans=["2017-11-20부터 2017-12-04까지"])
    assert fix_period_value(two) == two
    assert fix_period_value(dict(attribute="PERIOD", raw_value="2018년 3월", evidence_spans=["작년 봄"]))["raw_value"] == "2018-03"
    assert fix_period_value(dict(attribute="PERIOD", raw_value="첫 진단", evidence_spans=["2019년 5월에 처음"]))["raw_value"] == "2019-05"
    # 정규화기가 읽지 못하는 꼴: 재작성기가 '2014년 4월 1일'로 바꿔 다시 확인을 지나쳤다 (결과 ⑥ 기록 T0004 턴 6)
    assert fix_period_value(dict(attribute="PERIOD", raw_value="2014년 4월 1일"))["raw_value"] == "2014-04-01"
    assert fix_period_value(dict(attribute="PERIOD", raw_value="2014.04.01"))["raw_value"] == "2014-04-01"
    assert fix_period_value(dict(attribute="PERIOD", raw_value="처방 시작", evidence_spans=["2014년 9월 17일부터"]))["raw_value"] == "2014-09-17"
    assert fix_period_value(dict(attribute="PERIOD", raw_value="2014-13-40"))["raw_value"] == "2014-13-40"      # 날짜가 아니면 그대로
    assert fix_period_value(dict(attribute="PERIOD", raw_value="2014년 4월 1일부터 2015년 3월 2일까지"))["raw_value"].startswith("2014년")
