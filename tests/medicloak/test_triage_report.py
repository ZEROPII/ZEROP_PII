# 환자 위험 등급(ADR-0041)과 유사 사례 보고서(ADR-0042)의 작은 단위 시험. 엔진 · 서버 없이 돈다 (보고서 전체 흐름은 test_medicloak.py).
import re
from types import SimpleNamespace

from webdemo.backend import case_report, triage


def groups(problems=(), meds=(), inactive=()):
    g = dict(problems={}, medications={})
    for p in problems:
        g["problems"][p] = dict(label=p, active=True)
    for p in inactive:
        g["problems"][p] = dict(label=p, active=False)
    for m in meds:
        g["medications"][m] = dict(label=m, active=True)
    return g


def test_triage_levels_follow_the_rules():
    r = triage.assess(groups(["Sepsis caused by Staphylococcus aureus", "Hypertension"]), age=50)
    assert (r["level"], r["label"]) == (1, "위급") and r["reasons"][0].startswith("위급 진단 진행 중: Sepsis")
    assert triage.assess(groups(["Malignant neoplasm of breast"]), age=50)["level"] == 2
    assert triage.weight("Carcinoma in situ of prostate") == 2 and triage.weight("Non-small cell carcinoma of lung") == 4
    # 만성 질환만으로는 합이 6점에서 묶인다: 당뇨 합병증 다섯 줄 → 3등급, 80세 이상이면 2등급
    dm = [f"Diabetic complication {i} due to diabetes mellitus" for i in range(5)]
    assert triage.assess(groups(dm), age=40)["level"] == 3
    assert triage.assess(groups(dm), age=81)["level"] == 2
    r = triage.assess(groups(["Hypertension"], meds=[f"drug {i}" for i in range(5)]), age=30)
    assert r["score"] == 3 and r["level"] == 3 and "처방 중인 약 5종" in r["reasons"]
    assert triage.assess(groups(["Hypertension"]), age=30)["level"] == 4
    r = triage.assess(groups(inactive=["Sepsis caused by E. coli"]), age=30)
    assert r["level"] == 5 and r["reasons"] == ["진행 중인 주요 진단 · 처방 없음"]              # 끝난 진단은 세지 않는다
    assert triage.assess(groups(["Acute bronchitis"]), age=30)["reasons"] == ["가벼운 진단만 진행 중: Acute bronchitis"]
    assert triage.assess(groups(), age=1)["level"] == 4                                          # 2세 미만은 1점
    r = triage.assess(groups(["Hypertension"]), age=70, dormant=True)
    assert r["reasons"][-1] == "장기 미내원: 마지막 내원 때 기록으로 셈" and len(r["reasons"]) <= 4


class FakeData:
    def __init__(self, events, anc=None, labels=None):
        self.by_pat = {"P1": events}
        self._anc, self._labels = anc or {}, labels or {}

    def anc(self, n):
        return self._anc.get(n, set())

    def label(self, n):
        return self._labels.get(n, n)


EVENTS = [
    dict(event_id="C1", event_type="CONDITION", code_node="DX_A", start="2010-03-01", stop="2010-03-20"),
    dict(event_id="C0", event_type="CONDITION", code_node="DX_A", start="2008-01-01", stop="2008-01-09"),
    dict(event_id="C2", event_type="CONDITION", code_node="DX_B", start="2009-01-01", stop=None),
    dict(event_id="C3", event_type="CONDITION", code_node="DX_C", start="2012-01-01", stop=None),
    dict(event_id="M1", event_type="MEDICATION", code_node="MED_X", start="2010-03-02", stop="2010-03-12"),
    dict(event_id="P1", event_type="PROCEDURE", code_node="PROC_Y", start="2010-03-01", stop=None),
    dict(event_id="L1", event_type="CAREPLAN", code_node="PLAN_Z", start="2010-03-05", stop=None),
    dict(event_id="M2", event_type="MEDICATION", code_node="MED_W", start="2011-01-01", stop=None),
]
ROWS = [
    dict(attribute="DX", node_id="DX_C", event_id="C3", span_text="C"),
    dict(attribute="PLAN", node_id="PLAN_Z", event_id="L1", span_text="Z plan"),
    dict(attribute="DX", node_id="DX_B", event_id="C2", span_text="B"),
    dict(attribute="MED", node_id="MED_W", event_id="M2", span_text="W"),
    dict(attribute="PROC", node_id="PROC_Y", event_id="P1", span_text="Y"),
    dict(attribute="DX", node_id="DX_A", event_id="C1", span_text="A"),
    dict(attribute="MED", node_id="MED_X", event_id="M1", span_text="X"),
    dict(attribute="SEX", node_id="SEX_F", event_id=None, span_text="여성"),
    dict(attribute="AGE", node_id="AGE_40_44", event_id="C3", span_text="41세"),
    dict(attribute="AGE", node_id="AGE_35_39", event_id="C1", span_text="37세"),
    dict(attribute="PERIOD", node_id="PERIOD_2010-03", event_id="C1", span_text="2010-03-01"),
]


def test_report_facts_are_judged_in_a_fixed_order():
    """주진단 → 그 무렵(3일 전 ~ 14일 뒤) 시작한 처방 · 시술 · 관리 계획 → 성별 → 주진단 때 나이 → 시작 시기 → 동반 진단(그때 이어지던 것 먼저)."""
    data = FakeData(EVENTS, anc={"DX_A": {"DX_PARENT"}})
    facts, main_ev, treat = case_report.plan_facts(dict(patient_id="P1", fact_rows=ROWS), data, "DX_PARENT")
    assert [(f.role, f.row["node_id"]) for f in facts] == [
        ("main", "DX_A"), ("treat", "MED_X"), ("treat", "PROC_Y"), ("treat", "PLAN_Z"), ("sex", "SEX_F"),
        ("age", "AGE_35_39"), ("start", "PERIOD_2010-03"), ("other", "DX_B"), ("other", "DX_C")]
    assert main_ev["event_id"] == "C1" and [r["node_id"] for r in treat] == ["MED_X", "PROC_Y", "PLAN_Z"]


def test_report_course_is_written_in_ranges_without_dates():
    data = FakeData(EVENTS)
    ev = {e["event_id"]: e for e in EVENTS}
    labels, sents = case_report._course_main(data, "P1", ev["C1"])
    assert labels[0].startswith("시작부터 ") and labels[0].endswith(" 뒤 종료") and labels[1].startswith("같은 진단 기록 ")
    med = case_report._course_item(data, "P1", "MED", ev["M1"])
    assert med[-1].endswith(" 동안 처방")
    assert case_report._course_item(data, "P1", "PROC", ev["P1"]) == ["한 번 시행"]
    assert case_report._course_item(data, "P1", "PLAN", ev["L1"]) == ["종료일 없이 계속 진행"]
    for t in labels + sents + med:
        assert not re.search(r"\d{4}-\d{2}|\d{4}년", t), t                                # 날짜는 쓰지 않는다


def test_report_reasons_values_and_summary():
    x = lambda action, **kw: SimpleNamespace(action=action, **kw)
    assert case_report._why(x("allow"), "사례1", "MED", set(), set()) is None
    assert case_report._why(x("suppress"), "사례1", "MED", set(), {("사례1", "MED")}) == "rule"
    assert case_report._why(x("suppress"), "사례1", "MED", {"MED"}, set()) == "purpose"
    assert case_report._why(x("generalize", strict=True), "사례1", "AGE", set(), set()) == "strict"
    assert case_report._why(x("generalize", floor=True), "사례1", "AGE", set(), set()) == "floor"
    assert case_report._why(x("suppress"), "사례1", "DX", set(), set()) == "count"
    data = FakeData([], labels={"PERIOD_2010-03": "2010-03", "Q": "2010-Q1", "SEX_F": "기록상 여성"})
    assert [case_report._shown(data, n) for n in ("PERIOD_2010-03", "Q", "SEX_F")] == ["2010년 3월", "2010년 1분기", "여성"]
    hid = dict(text=None, action="suppress", why="count")
    assert case_report._summary(dict(value=hid), [], []) == "주진단이 비공개라 이 사례의 치료 경과는 적지 않았습니다."
    main = dict(value=dict(text="Otitis media", action="allow", why=None))
    treat = [dict(kind="medications", name=dict(text="amoxicillin", action="allow", why=None)), dict(kind="procedures", name=hid)]
    assert case_report._summary(main, treat, []) == "Otitis media 진단 무렵 처방 1개를 시작했습니다. 그 밖에 비공개 치료가 1개 있습니다."


def test_report_pdf_has_korean_font_and_a_download_name():
    v = lambda t, a="allow", why=None: dict(text=t, action=a, why=why)
    rep = dict(
        reportId="R1", createdAt=1_760_000_000, conversationId="S1", createdBy="김서연", purpose="처방 참고",
        patient=dict(ageSex="70대 / 여성", primaryDiagnosis="Otitis media", visitDate="2025-10-29"), target="실제 LLM",
        notes=list(case_report.NOTES), whyLabels=dict(case_report.WHY_KO), counts=dict(allow=3, generalize=1, suppress=2),
        cases=[dict(caseId="case-1", ref="사례1", label="사례 1", rank=1, hidden=2, ranged=1,
                    profile=dict(sex=v("여성"), age=v("70~74세", "generalize", "floor")),
                    main=dict(value=v("Otitis media"), start=v(None, "suppress", "count"), course=["시작부터 약 1~2주 뒤 종료"]),
                    treatments=[dict(kind="medications", kindLabel="처방", name=v("amoxicillin 500 MG"), course=["약 1~2주 동안 처방"]),
                                dict(kind="procedures", kindLabel="시술", name=v(None, "suppress", "count"), course=[])],
                    others=[v("Chronic sinusitis")], summary="Otitis media 진단 무렵 처방 1개를 시작했습니다.")])
    data = case_report.pdf(rep, regno="26-1234")
    assert data.startswith(b"%PDF") and data.count(b"/Type /Page") >= 1 and b"WantedSans" in data
    assert re.fullmatch(r"MediCloak-유사사례보고서-26-1234-\d{8}-\d{4}\.pdf", case_report.filename(rep, "26-1234"))
    assert case_report.filename(rep).startswith("MediCloak-유사사례보고서-2025")
