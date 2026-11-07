# 유사 사례 보고서 (ADR-0042): 지금 대화의 과거 사례마다 주진단 · 그 무렵 시작한 치료 · 기록상 경과를 한 문서로 모은다.
#
# 보고서도 답과 같은 공개다. 그래서 값마다 답과 같은 Defender(대화의 누적 State + 공개 원장, 보안 담당자 규칙 · 조회 목적 ·
# 최소 공개 단위 · 민감도 등급)로 판정하고, 내보낸 값은 그 사례의 State와 원장에 더한다. 그 뒤의 답 · 보고서는 이 값까지 합쳐 판정한다.
#   - 보고서에 넣는 값은 우선 순서대로 판정한다: 주진단 → 그 무렵 시작한 처방 · 시술 · 관리 계획 → 성별 → 주진단 당시 나이 →
#     주진단 시작 시기 → 동반 진단. 함께 내면 후보가 줄어들므로 뒤의 값일수록 넓히거나 가리기 쉽다 (Defender의 차례 판정).
#   - 가린 값은 '비공개', 넓힌 값은 상위 범주 이름으로 적고 까닭(후보가 적음 · 조회 목적 · 규칙 · 공개 단위 · 민감 값)을 붙인다.
#   - 경과(종료까지 기간 · 처방 기간 · 횟수)는 날짜를 그대로 쓰지 않고 정해 둔 범위로만 적는다 (gate.span_phrase · textguard.count_bucket,
#     ADR-0032와 같은 구간). 이름을 가린 항목은 경과도 적지 않는다.
#   - 경과는 기록에 남은 날짜로 센 것이다. 치료 효과를 입증하지 않는다는 문장을 보고서에 늘 넣는다.
# 의료진 화면 계약이라 후보 수(k) 같은 숫자는 넣지 않는다.

from __future__ import annotations

import collections
import datetime as dt
import io
import re
import time
import warnings
from pathlib import Path
from typing import Any

from medical.defense import ALLOW, GENERALIZE, SUPPRESS
from medical.tracking import EV_WORD, Case
from webdemo.backend.gate import span_phrase
from webdemo.backend.textguard import count_bucket

FONT_DIR = Path(__file__).with_name("fonts")
#: 주진단과 '같은 시기'로 보는 치료 시작일 범위 (일): 주진단 시작 며칠 전부터 며칠 뒤까지
NEAR_BEFORE, NEAR_AFTER = 3, 14
#: 동반 진단은 몇 개까지 넣는가 (많이 넣을수록 다른 값이 가려진다)
OTHER_DX_MAX = 5
KIND_OF = dict(MED="medications", PROC="procedures", PLAN="carePlans")
KIND_KO = dict(medications="처방", procedures="시술", carePlans="관리 계획")
EVENT_TYPE = dict(MED="MEDICATION", PROC="PROCEDURE", PLAN="CAREPLAN")
WHY_KO = dict(count="그대로 적으면 해당하는 과거 환자가 아주 적습니다.", purpose="이번 조회 목적에 쓰지 않는 정보입니다.",
              rule="보안 담당자가 정한 규칙입니다.", floor="정해진 공개 단위(나이 5세 · 날짜 월)로만 적습니다.",
              strict="민감한 정보라 더 엄격하게 적용했습니다.")
NOTES = [
    "값은 이 대화의 답과 같은 기준으로 MediCloak이 판정했습니다. '비공개'는 과거 환자를 알아볼 수 있어 뺀 값이고, 넓혀 적은 값에는 '범위'가 붙습니다.",
    "보고서에 담은 값도 이 대화에서 공개한 것으로 셉니다. 보고서를 만든 뒤의 답에서는 같은 사례의 값이 더 가려질 수 있습니다.",
    "경과는 기록에 남은 날짜로 센 범위입니다. 치료 효과를 입증하지 않으며, 진단과 처방은 진료 의사가 판단합니다.",
    "과거 사례 기록은 바뀌지 않습니다. 가린 값이 꼭 필요하면 대화에서 그 사례에 물은 뒤 세부 정보 요청을 보내세요.",
]


class ReportError(ValueError):
    pass


def _day(s: str | None) -> dt.date | None:
    try:
        return dt.date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def _shown(data: Any, node: str | None) -> str:
    """노드 이름을 보고서 글로: '2008-05' → '2008년 5월', '2008-Q2' → '2008년 2분기', '기록상 남성' → '남성'."""
    lab = str(data.label(node) if node else "")
    m = re.fullmatch(r"(\d{4})-(\d{2})", lab)
    if m:
        return f"{m.group(1)}년 {int(m.group(2))}월"
    m = re.fullmatch(r"(\d{4})-Q([1-4])", lab)
    if m:
        return f"{m.group(1)}년 {m.group(2)}분기"
    if re.fullmatch(r"\d{4}", lab):
        return f"{lab}년"
    return lab.removeprefix("기록상 ")


class _Fact:
    __slots__ = ("role", "row", "kind")

    def __init__(self, role: str, row: dict[str, Any], kind: str | None = None) -> None:
        self.role, self.row, self.kind = role, row, kind


def plan_facts(doc: dict[str, Any], data: Any, main_node: str) -> tuple[list[_Fact], dict[str, Any] | None, list[dict[str, Any]]]:
    """
    보고서에 넣을 사실을 판정 차례대로 고른다. (사실 목록, 주진단 사건, 같은 시기 치료 사실 줄).
    주진단: 지금 환자의 주진단과 같은 진단(또는 그 아래 진단)의 첫 사건. 없으면 문서의 첫 진단.
    """
    rows = [r for r in doc.get("fact_rows") or [] if r.get("attribute") and r.get("node_id")]
    events = {e["event_id"]: e for e in data.by_pat.get(doc.get("patient_id"), [])}
    dx_rows = [r for r in rows if r["attribute"] == "DX"]
    main = next((r for r in dx_rows if r["node_id"] == main_node or main_node in data.anc(r["node_id"])), None) or (dx_rows[0] if dx_rows else None)
    main_ev = events.get(main["event_id"]) if main else None
    start = _day(main_ev.get("start")) if main_ev else None
    stop = _day(main_ev.get("stop")) if main_ev else None

    def near(r: dict[str, Any]) -> bool:
        e = events.get(r["event_id"])
        d = _day(e.get("start")) if e else None
        if start is None or d is None:
            return False
        if stop is not None and d > stop:
            return False
        return -NEAR_BEFORE <= (d - start).days <= NEAR_AFTER

    treat = [r for r in rows if r["attribute"] in KIND_OF and near(r)]
    treat.sort(key=lambda r: ("MED", "PROC", "PLAN").index(r["attribute"]))
    facts: list[_Fact] = []
    if main:
        facts.append(_Fact("main", main))
    facts += [_Fact("treat", r, KIND_OF[r["attribute"]]) for r in treat]
    facts += [_Fact("sex", r) for r in rows if r["attribute"] == "SEX"][:1]
    if main:
        facts += [_Fact("age", r) for r in rows if r["attribute"] == "AGE" and r["event_id"] == main["event_id"]][:1]
        facts += [_Fact("start", r) for r in rows if r["attribute"] == "PERIOD" and r["event_id"] == main["event_id"]][:1]
    others = [r for r in dx_rows if r is not main]
    if start is not None:
        def active_then(r: dict[str, Any]) -> bool:
            e = events.get(r["event_id"])
            s, t = (_day(e.get("start")), _day(e.get("stop"))) if e else (None, None)
            return s is not None and s <= start and (t is None or t >= start)
        others.sort(key=lambda r: not active_then(r))            # 주진단 때 이어지던 진단(동반 진단) 먼저 (정렬은 안정적)
    facts += [_Fact("other", r) for r in others[:OTHER_DX_MAX]]
    return facts, main_ev, treat


def _course_main(data: Any, pid: str, ev: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    """주진단의 기록상 경과: (표에 적을 짧은 글, 요약 문장). 종료까지 기간 · 같은 진단 기록 수 (범위로만)."""
    if not ev:
        return [], []
    labels, sents = [], []
    s, t = ev.get("start"), ev.get("stop")
    if t:
        phrase = span_phrase(str(s)[:10], str(t)[:10])
        labels.append(f"시작부터 {phrase} 뒤 종료" if phrase else "종료 기록 있음")
        sents.append(f"주진단은 시작부터 {phrase} 뒤 종료 기록이 있습니다." if phrase else "주진단은 종료 기록이 있습니다.")
    else:
        labels.append("종료 기록 없음")
        sents.append("주진단은 종료 기록 없이 마지막 기록까지 이어졌습니다.")
    n = sum(1 for e in data.by_pat.get(pid, []) if e["event_type"] == "CONDITION" and e["code_node"] == ev["code_node"])
    if n > 1:
        labels.append(f"같은 진단 기록 {count_bucket(n)}")
        sents.append(f"같은 진단 기록은 {count_bucket(n)}입니다.")
    return labels, sents


def _course_item(data: Any, pid: str, attr: str, ev: dict[str, Any] | None) -> list[str]:
    """처방 · 시술 · 관리 계획의 경과: 횟수 범위 · 기간 범위 · 종료 여부 (날짜는 쓰지 않는다)."""
    if not ev:
        return []
    code = ev["code_node"]
    es = sorted((e for e in data.by_pat.get(pid, []) if e["event_type"] in (EVENT_TYPE[attr], "PROCEDURE_HISTORY") and e["code_node"] == code),
                key=lambda e: e.get("start") or "")
    out: list[str] = []
    if attr == "MED":
        if len(es) > 1:
            out.append(f"처방 {count_bucket(len(es))}")
        if es and all(e.get("stop") for e in es):
            phrase = span_phrase(str(es[0]["start"])[:10], max(str(e["stop"])[:10] for e in es))
            out.append(f"{phrase} 동안 처방" if phrase else "처방 종료 기록 있음")
        else:
            out.append("종료일 없이 계속 처방")
    elif attr == "PROC":
        dated = [e for e in es if e.get("start")]
        if len(dated) > 1:
            out.append(f"시행 {count_bucket(len(dated))}")
            phrase = span_phrase(str(dated[0]["start"])[:10], str(dated[-1]["start"])[:10])
            if phrase:
                out.append(f"처음부터 마지막까지 {phrase}")
        else:
            out.append("한 번 시행")
    else:
        if ev.get("stop"):
            phrase = span_phrase(str(ev["start"])[:10], str(ev["stop"])[:10])
            out.append(f"시작부터 {phrase} 뒤 종료" if phrase else "종료 기록 있음")
        else:
            out.append("종료일 없이 계속 진행")
    return out


def _value(data: Any, x: Any, why: str | None, raw: str) -> dict[str, Any]:
    """판정 하나를 화면 값으로. 그대로면 원래 글, 넓힘이면 상위 범주 이름, 가림이면 글 없음."""
    if x.action == SUPPRESS:
        return dict(text=None, action=SUPPRESS, why=why)
    if x.action == GENERALIZE:
        return dict(text=_shown(data, x.to_node), action=GENERALIZE, why=why)
    text = raw if x.disclosure["attribute"] in ("DX", "MED", "PROC", "PLAN") else _shown(data, x.to_node or x.disclosure["node_id"])
    return dict(text=text, action=ALLOW, why=None)


def _why(x: Any, ref: str, attr: str, purpose: frozenset[str] | set[str], rules: set[tuple[str, str]]) -> str | None:
    if x.action == ALLOW:
        return None
    if (ref, attr) in rules:
        return "rule"
    if attr in purpose and x.action == SUPPRESS:
        return "purpose"
    if getattr(x, "strict", False):
        return "strict"
    if getattr(x, "floor", False):
        return "floor"
    return "count"


def _summary(main: dict[str, Any] | None, treat: list[dict[str, Any]], sents: list[str]) -> str:
    """사례 요약 문장 (가린 이름은 쓰지 않는다)."""
    if main is None:
        return "이 사례에는 진단 기록이 없습니다."
    name = main["value"]["text"]
    if name is None:
        return "주진단이 비공개라 이 사례의 치료 경과는 적지 않았습니다."
    shown = collections.Counter(t["kind"] for t in treat if t["name"]["text"])
    hidden = sum(1 for t in treat if not t["name"]["text"])
    parts = " · ".join(f"{KIND_KO[k]} {n}개" for k, n in shown.items())
    if parts:
        out = [f"{name} 진단 무렵 {parts}를 시작했습니다."]
        if hidden:
            out.append(f"그 밖에 비공개 치료가 {hidden}개 있습니다.")
    elif hidden:
        out = [f"{name} 진단 무렵 시작한 치료는 비공개입니다."]
    else:
        out = [f"{name} 진단 무렵 시작한 치료 기록은 없습니다."]
    return " ".join(out + sents)


def build(conv: Any, *, user: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    지금 대화(ClinicConversation)의 유사 사례 보고서를 만들고, 내보낸 값을 State · 원장에 더한다.
    돌려주는 것은 의료진 화면 계약이다 (값 · 조치 · 까닭. 후보 수는 넣지 않는다).
    """
    s = conv.session
    if getattr(conv, "archived", False):
        raise ReportError("지난 대화로는 보고서를 새로 만들 수 없습니다.")
    if conv.arm != "C1" or "C1" not in s.runs:
        raise ReportError("보고서는 보호를 거치는 대화에서만 만듭니다.")
    with conv.eng.lock:
        run, data, p = s.runs["C1"], s.ctx.data, s.prefix
        d = run.ctx.defender
        purpose = getattr(run, "purpose_blocked", frozenset())
        rules = {(r["case"], r["attribute"]) for r in getattr(s, "rules", [])}
        main_node = p.binding["main_dx_node"]
        totals: collections.Counter = collections.Counter()
        cases = []
        for i, (doc, (pid, _score)) in enumerate(zip(p.docs, p.retrieval), 1):
            ref = f"사례{i}"
            facts, main_ev, _treat = plan_facts(doc, data, main_node)
            events = {e["event_id"]: e for e in data.by_pat.get(pid, [])}
            new = [dict(attribute=f.row["attribute"], node_id=f.row["node_id"],
                        event_group=f"{ref}:RPT{f.row['event_id']}" if f.row.get("event_id") else None) for f in facts]
            src = [dict(raw_value=f.row.get("span_text") or "", evidence_spans=[]) for f in facts]
            plan = d.plan_case(ref, run._basis(ref), new, src) if new else None
            decisions = list(plan.decisions) if plan else []
            vals = []
            for f, x in zip(facts, decisions):
                why = _why(x, ref, f.row["attribute"], purpose, rules)
                vals.append(_value(data, x, why, str(f.row.get("span_text") or "")))
                totals[x.action] += 1
            by_role: dict[str, list[tuple[_Fact, dict[str, Any]]]] = collections.defaultdict(list)
            for f, v in zip(facts, vals):
                by_role[f.role].append((f, v))
            main = None
            sents: list[str] = []
            if by_role.get("main"):
                f, v = by_role["main"][0]
                labels, sents = _course_main(data, pid, main_ev) if v["text"] else ([], [])
                main = dict(value=v, start=(by_role.get("start") or [(None, None)])[0][1], course=labels)
            treat = []
            for f, v in by_role.get("treat", []):
                ev = events.get(f.row["event_id"])
                treat.append(dict(kind=f.kind, kindLabel=KIND_KO[f.kind], name=v,
                                  course=_course_item(data, pid, f.row["attribute"], ev) if v["text"] else []))
            profile = dict(sex=(by_role.get("sex") or [(None, None)])[0][1], age=(by_role.get("age") or [(None, None)])[0][1])
            others = [v for _, v in by_role.get("other", [])]
            hidden = sum(1 for v in vals if v["action"] == SUPPRESS)
            ranged = sum(1 for v in vals if v["action"] == GENERALIZE)
            cases.append(dict(caseId=f"case-{i}", ref=ref, label=f"사례 {i}", rank=i, profile=profile, main=main, treatments=treat,
                              others=others, summary=_summary(main, treat, sents), hidden=hidden, ranged=ranged))
            # 내보낸 값(그대로 · 넓힘)을 이 사례의 State에 더한다: 뒤의 답 · 보고서 판정이 이 값까지 합쳐 센다
            had = {(c0["attribute"], c0["node_id"], c0.get("event_group")) for c0 in (run.cases[ref].committed if ref in run.cases else [])}
            released = [dict(x.disclosure, node_id=x.to_node) for x in decisions if x.action != SUPPRESS and x.to_node]
            released = [r for r in released if (r["attribute"], r["node_id"], r.get("event_group")) not in had]   # 다시 만들어도 같은 값은 한 번만
            if released:
                if ref not in run.cases:
                    run.cases[ref] = Case(ref)
                    run.order.append(ref)
                c = run.cases[ref]
                for r, f, x in zip(new, facts, decisions):
                    g = r.get("event_group")
                    if x.action != SUPPRESS and g and r["attribute"] in EV_WORD:
                        c.events.setdefault(g.split(":", 1)[1], f"{_shown(data, x.to_node) if x.action == GENERALIZE else f.row.get('span_text')} {EV_WORD[r['attribute']]}")
                c.committed += released
        if getattr(s, "ledger", None) is not None:
            s._ledger_sync("report", s.turn)             # 다른 대화 · 다른 의료진의 판정에도 들어간다 (ADR-0032)
        b = p.binding
        report = dict(
            reportId=f"R{int(time.time() * 1000)}", createdAt=time.time(), conversationId=s.id,
            createdBy=(user or {}).get("display_name"), purpose=conv.patient_context()["queryPurpose"],
            patient=dict(ageSex=f"{b['QUERY_AGE_BAND']} / {b['QUERY_SEX']}", primaryDiagnosis=b["QUERY_MAIN_DX"], visitDate=b.get("index_date")),
            target=conv.policy()["modeLabel"], cases=cases, notes=list(NOTES), whyLabels=dict(WHY_KO),
            counts=dict(allow=totals[ALLOW], generalize=totals[GENERALIZE], suppress=totals[SUPPRESS]))
        conv.report = report
        reports = getattr(s, "reports", None)
        if reports is None:
            reports = s.reports = []
        reports.append(dict(id=report["reportId"], at=report["createdAt"], by=(user or {}).get("user_id"), counts=report["counts"],
                            cases={c["ref"]: dict(hidden=c["hidden"], ranged=c["ranged"]) for c in cases}))
        s.last_active = report["createdAt"]
        conv.version += 1
        return report


# ── PDF ─────────────────────────────────────────────────────

def _text(v: dict[str, Any] | None) -> str:
    if v is None:
        return "–"
    if v["text"] is None:
        return "비공개"
    return f"{v['text']} (범위)" if v["action"] == GENERALIZE else v["text"]


def pdf(report: dict[str, Any], *, regno: str | None = None) -> bytes:
    """보고서를 A4 PDF로 (글꼴은 앱 안의 Wanted Sans 일부, 인터넷 없이). 가린 값은 '비공개' 상자, 넓힌 값은 '(범위)'."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")                  # Pillow 없이 묶은 앱: fpdf2가 그림을 못 넣는다는 경고 (그림은 쓰지 않는다)
        from fpdf import FPDF
        from fpdf.enums import XPos, YPos
    ink, ink2, ink3, line, tint = (22, 24, 39), (75, 80, 104), (102, 107, 131), (222, 225, 234), (240, 242, 247)
    accent = (16, 38, 46)

    class Doc(FPDF):
        def footer(self) -> None:
            self.set_y(-12)
            self.set_font("ws", size=7.5)
            self.set_text_color(*ink3)
            made = time.strftime("%Y-%m-%d %H:%M", time.localtime(report["createdAt"]))
            self.cell(0, 5, f"MediCloak 유사 사례 보고서 · {made} · 대화와 같은 보호 기준", align="L")
            self.cell(0, 5, f"{self.page_no()} / {{nb}}", align="R")

    doc = Doc(format="A4", unit="mm")
    doc.set_margins(16, 16, 16)
    doc.set_auto_page_break(True, 18)
    doc.add_font("ws", "", str(FONT_DIR / "WantedSans-Report-Regular.ttf"))
    doc.add_font("ws", "B", str(FONT_DIR / "WantedSans-Report-Bold.ttf"))
    doc.alias_nb_pages()
    doc.set_title("유사 사례 보고서")
    doc.set_author("MediCloak")
    doc.add_page()
    w = doc.w - doc.l_margin - doc.r_margin

    def nl(h: float = 2) -> None:
        doc.ln(h)

    def para(t: str, size: float = 9.5, color: tuple[int, int, int] = ink, style: str = "", lh: float = 5.0) -> None:
        doc.set_font("ws", style, size)
        doc.set_text_color(*color)
        doc.multi_cell(w, lh, t, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def chip(t: str) -> None:
        doc.set_font("ws", "B", 7.5)
        doc.set_fill_color(*tint)
        doc.set_text_color(*ink2)
        doc.cell(doc.get_string_width(t) + 4, 4.6, t, fill=True, align="C")

    # 머리
    doc.set_font("ws", "B", 17)
    doc.set_text_color(*accent)
    doc.cell(w * 0.7, 9, "유사 사례 보고서")
    doc.set_font("ws", "B", 8.5)
    doc.set_text_color(*ink3)
    doc.cell(w * 0.3, 9, "MediCloak 보호 적용", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    doc.set_draw_color(*accent)
    doc.set_line_width(0.6)
    doc.line(doc.l_margin, doc.get_y() + 1, doc.l_margin + w, doc.get_y() + 1)
    nl(4)
    meta = [("지금 보는 환자", " · ".join(x for x in (f"등록번호 {regno}" if regno else None, report["patient"]["ageSex"], report["patient"]["primaryDiagnosis"]) if x)),
            ("진료 목적", report["purpose"]), ("기준 진료일", report["patient"].get("visitDate") or "–"),
            ("만든 시각", time.strftime("%Y-%m-%d %H:%M", time.localtime(report["createdAt"])) + (f" · {report['createdBy']}" if report.get("createdBy") else "")),
            ("진료 지원 AI", report.get("target") or "–")]
    for k, v in meta:
        doc.set_font("ws", "", 8.5)
        doc.set_text_color(*ink3)
        doc.cell(28, 5.4, k)
        doc.set_font("ws", "B", 9)
        doc.set_text_color(*ink)
        doc.multi_cell(w - 28, 5.4, v, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    nl(3)
    # 보호 안내
    y0 = doc.get_y()
    doc.set_fill_color(*tint)
    doc.set_font("ws", "", 8.3)
    box = "\n".join(f"· {n}" for n in report["notes"])
    lines = doc.multi_cell(w - 8, 4.4, box, dry_run=True, output="LINES")
    doc.rect(doc.l_margin, y0, w, len(lines) * 4.4 + 6, style="F")
    doc.set_xy(doc.l_margin + 4, y0 + 3)
    doc.set_text_color(*ink2)
    doc.multi_cell(w - 8, 4.4, box, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    doc.set_y(y0 + len(lines) * 4.4 + 6)
    nl(5)

    for c in report["cases"]:
        if doc.get_y() > doc.h - 70:
            doc.add_page()
        doc.set_font("ws", "B", 12)
        doc.set_text_color(*accent)
        doc.cell(0, 7, f"{c['label']}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        prof = c["profile"]
        para(f"성별 {_text(prof.get('sex'))} · 주진단 당시 나이 {_text(prof.get('age'))}", 8.8, ink2)
        nl(1.5)
        m = c.get("main")
        rows: list[tuple[str, str, str]] = []
        if m:
            rows.append(("주진단", _text(m["value"]), " · ".join(x for x in [f"시작 {_text(m.get('start'))}" if m.get("start") else None, *m.get("course", [])] if x)))
        for t in c["treatments"]:
            rows.append((t["kindLabel"], _text(t["name"]), " · ".join(t.get("course") or [])))
        if not rows:
            para("판정할 기록이 없습니다.", 9, ink3)
        doc.set_draw_color(*line)
        doc.set_line_width(0.2)
        cw = (22, w * 0.46, w - 22 - w * 0.46)
        doc.set_font("ws", "B", 8)
        doc.set_text_color(*ink3)
        for wd, h in zip(cw, ("구분", "이름", "기록상 경과")):
            doc.cell(wd, 5.5, h, border="B")
        doc.ln(5.5)
        for kind, name, course in rows:
            hidden = name == "비공개"
            doc.set_font("ws", "B" if kind == "주진단" else "", 8.8)
            hs = [len(doc.multi_cell(cw[1] - 2, 4.6, name, dry_run=True, output="LINES")),
                  len(doc.multi_cell(cw[2] - 2, 4.6, course or "–", dry_run=True, output="LINES"))]
            h = max(hs) * 4.6 + 2.4
            if doc.get_y() + h > doc.h - 20:
                doc.add_page()
            y = doc.get_y()
            doc.set_xy(doc.l_margin, y + 1.2)
            doc.set_text_color(*ink2)
            doc.set_font("ws", "B", 8.3)
            doc.cell(cw[0], 4.6, kind)
            doc.set_xy(doc.l_margin + cw[0], y + 1.2)
            if hidden:
                chip("비공개")
            else:
                doc.set_font("ws", "B" if kind == "주진단" else "", 8.8)
                doc.set_text_color(*ink)
                doc.multi_cell(cw[1] - 2, 4.6, name)
            doc.set_xy(doc.l_margin + cw[0] + cw[1], y + 1.2)
            doc.set_font("ws", "", 8.5)
            doc.set_text_color(*ink2)
            doc.multi_cell(cw[2] - 2, 4.6, course or "–")
            doc.set_y(y + h)
            doc.line(doc.l_margin, doc.get_y(), doc.l_margin + w, doc.get_y())
        if c["others"]:
            nl(2)
            shown = [v["text"] + (" (범위)" if v["action"] == GENERALIZE else "") for v in c["others"] if v["text"]]
            hid = sum(1 for v in c["others"] if not v["text"])
            para("동반 진단: " + (", ".join(shown) if shown else "") + (f"{' · ' if shown else ''}비공개 {hid}개" if hid else ""), 8.6, ink2)
        nl(1.5)
        para(c["summary"], 9, ink, "B")
        nl(6)
    out = doc.output()
    return bytes(out)


def filename(report: dict[str, Any], regno: str | None = None) -> str:
    made = time.strftime("%Y%m%d-%H%M", time.localtime(report["createdAt"]))
    return f"MediCloak-유사사례보고서-{regno + '-' if regno else ''}{made}.pdf"


def as_io(data: bytes) -> io.BytesIO:
    return io.BytesIO(data)
