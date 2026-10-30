# 의료진 화면(frontend/ Clinical Case Finder) 계약을 데모 엔진 위에서 구현한다.
#
# 경로와 응답 모양은 frontend/src/api/httpApi.ts · api_server/와 같다 (접두사 /api). 다른 점은 대상 AI뿐이다.
#   api_server : 실제 LLM 대상 AI (.env 필요). 질문 문장을 그대로 읽는다.
#   webdemo    : 결정적 응답기 (LLM 0회). 질문 문장에서 묻는 단서를 찾아 Seed를 고른다 (webdemo/backend/intent.py).
# 대화 하나 = 엔진 Session 하나 (세 조건 C0·C1·C1S를 같은 질문으로 나란히 진행). 의료진 화면은 C1(누적 State Defender)만 본다.
# 나란히 돈 C0·C1S와 원 응답은 보안 담당자 관제 화면(/api/monitor)에서만 보인다.

from __future__ import annotations

import collections
import re
import time
from datetime import datetime, timezone
from typing import Any

from api_server.engine import segments_of
from medical.defense import ALLOW, GENERALIZE, SUPPRESS
from medical.retrieval import PANEL_LABEL
from webdemo.backend import intent as I
from webdemo.backend.engine import ATTR_KO, QTYPE_KO, DemoError, Engine, Session, parse_answer

ATTR_LABEL = dict(AGE="나이", SEX="성별", REGION="거주 지역", DX="진단", PROC="시술", PERIOD="시기", MED="처방 약", PLAN="관리 계획")
STATE_MODE_LABEL = dict(C0="방어 없음", C1="누적 판정 (대화 전체 기억)", C1S="턴별 판정 (매 턴 새로)")
_REF = re.compile(r"사례(\d+)")


class NotFound(KeyError):
    pass


class Conflict(ValueError):
    pass


def _iso(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts or time.time(), timezone.utc).isoformat()


class Slot:
    def __init__(self, n: int) -> None:
        self.number = n
        self.case_id = f"case-{n}"
        self.ref = f"사례{n}"
        self.label = f"사례 {n}"
        self.messages: list[dict[str, Any]] = []
        self.questions = 0
        self.history: list[dict[str, Any]] = []
        self.decisions: list[dict[str, Any]] = []
        self.last_action = ALLOW


class ClinicDesk:
    """의료진 화면의 대화 하나 (질의 환자 1명). reset으로 다른 환자를 고르면 새 Session을 만든다 (지난 대화는 관제 화면에 남는다)."""

    def __init__(self, eng: Engine, trial_id: str = "T0014", arm: str = "C1", budget: int = 60) -> None:
        self.eng, self.arm, self.budget = eng, arm, budget
        self._seq = 0
        self.start(trial_id)

    # ── 준비 ──
    def start(self, trial_id: str) -> None:
        with self.eng.lock:
            s = self.eng.new_session(trial_id, source="clinic", budget=self.budget)
            self.session: Session = s
            self.workspace_id = f"ws-{s.id}"
            self.version = 1
            self.updated_at = _iso()
            self.slots = {f"case-{i}": Slot(i) for i in range(1, len(s.prefix.docs) + 1)}
            rec0 = self._records()[0]
            self.titles: dict[str, dict[str, str]] = collections.defaultdict(dict)
            for ln in parse_answer(rec0["response_text"]):
                if "case" in ln:
                    self.titles[ln["case"]][ln["attribute"]] = ln["value"]
            self._absorb(rec0, None)

    def _id(self, p: str) -> str:
        self._seq += 1
        return f"{p}-{self._seq}"

    def _records(self) -> list[dict[str, Any]]:
        return [r for r in self.session.logs[self.arm] if r.get("turn") is not None]

    def slot(self, case_id: str) -> Slot:
        if case_id not in self.slots:
            raise NotFound(case_id)
        return self.slots[case_id]

    def session_id(self, case_id: str) -> str:
        return f"{self.workspace_id}:{case_id}"

    def _check(self, case_id: str, session_id: str) -> Slot:
        s = self.slot(case_id)
        if session_id != self.session_id(case_id):
            raise Conflict("대화가 바뀌었습니다. 화면을 새로 불러오세요.")
        return s

    def case_of_ref(self, ref: str) -> str | None:
        m = _REF.fullmatch(ref or "")
        cid = f"case-{int(m.group(1))}" if m else None
        return cid if cid in self.slots else None

    # ── k와 위험 표시 ──
    def k(self, case_id: str) -> int:
        c = self.session.runs[self.arm].cases.get(self.slots[case_id].ref)
        ctx = self.session.ctx
        return ctx.kc.k(c.committed)["k"] if c and c.committed else ctx.p_ref

    def risk_state(self, case_id: str) -> dict[str, Any]:
        s, d = self.slot(case_id), self.session.ctx.defender
        k = self.k(case_id)
        if k == 0:
            level, label = "blocked", "후보 일치 없음"
        elif k <= d.s:
            level, label = "danger", "위험"
        elif k <= d.g:
            level, label = "caution", "추가 공개 제한"
        else:
            level, label = "safe", "여유"
        restricted = self.arm == "C1" and d.risky(k)
        return dict(caseId=case_id, k=k, riskLevel=level, statusLabel=label, disclosureAllowed=not restricted,
                    policyDecision="restrict" if restricted else s.last_action, version=self.version, updatedAt=self.updated_at)

    # ── 화면 계약 ──
    def environment(self) -> dict[str, Any]:
        return dict(roleLabel="의료진", locationLabel="Zero PII 데모 · Synthea 합성 환자")

    def policy(self) -> dict[str, Any]:
        d = self.session.ctx.defender
        return dict(modeLabel="데모 응답기 (LLM 없음)", arm=self.arm, stateModeLabel=STATE_MODE_LABEL[self.arm], minK=d.g, suppressK=d.s,
                    populationSize=self.session.ctx.p_ref, source="backend")

    def patient_context(self) -> dict[str, Any]:
        b, data, p = self.session.prefix.binding, self.session.ctx.data, self.session.prefix
        main = b["main_dx_node"]
        others = sorted({data.label(e["code_node"]) for e in data.by_pat[p.query_patient]
                         if e["event_type"] == "CONDITION" and (e["start"] or "")[:10] <= b["index_date"] and main not in data.anc(e["code_node"])})
        return dict(contextId=f"{self.workspace_id}:patient", ageSexLabel=f"{b['QUERY_AGE_BAND']} / {b['QUERY_SEX']}",
                    primaryDiagnosis=b["QUERY_MAIN_DX"], comorbidities=others, plannedProcedure=b["QUERY_RELATED_ITEM"],
                    queryPurpose=QTYPE_KO.get(p.query_type, p.query_type) + " 참고", source="backend", trialId=self.session.trial_id)

    def similar_cases(self, context_id: str) -> list[dict[str, Any]]:
        if context_id != f"{self.workspace_id}:patient":
            raise NotFound(context_id)
        out = []
        for s, (_, score) in zip(self.slots.values(), self.session.prefix.retrieval):
            t = self.titles.get(s.ref, {})
            item = next(((ATTR_LABEL[a], t[a]) for a in ("MED", "PROC", "PLAN") if a in t), None)
            out.append(dict(caseId=s.case_id, label=s.label, diagnosis=t.get("DX", "진단 비공개"),
                            description=(f"{item[0]} {item[1]}" if item else "관련 항목 없음"), similarityRank=s.number,
                            similarity=round(score, 3)))
        return out

    def conversation(self, case_id: str) -> dict[str, Any]:
        s = self.slot(case_id)
        return dict(sessionId=self.session_id(case_id), caseId=case_id, messages=s.messages, questionCount=s.questions)

    def disclosures(self, case_id: str) -> dict[str, Any]:
        return dict(caseId=case_id, entries=self.slot(case_id).history)

    def policy_decision(self, case_id: str) -> dict[str, Any]:
        s, d, data = self.slot(case_id), self.session.ctx.defender, self.session.ctx.data
        risk = self.risk_state(case_id)
        c = self.session.runs[self.arm].cases.get(s.ref)
        gen = [x for x in s.decisions if x["action"] == GENERALIZE]
        sup = [x for x in s.decisions if x["action"] == SUPPRESS]
        notes = [f"새로 나온 단서를 모두 더해도 후보가 {d.g}명보다 많으면 그대로 답합니다. 아니면 단서마다 원래 값으로 후보가 {d.s}명 이하이면 가리고, "
                 f"그 외에는 후보가 {d.g}명을 넘는 가장 가까운 상위 범주로 넓혀 답합니다.",
                 "후보 수는 사건 단위로 셉니다 (같은 진료 사건의 진단·나이·날짜를 한 사람이 함께 만족해야 후보).",
                 "사례마다 따로 셉니다. 한 사례에 나온 단서는 다른 사례의 후보 수에 더하지 않습니다."]
        return dict(caseId=case_id, currentK=risk["k"], minK=d.g, suppressK=d.s, arm=self.arm,
                    disclosedQis=[dict(attributeLabel=ATTR_LABEL.get(x["attribute"], x["attribute"]), levelDescription=data.label(x["node_id"]))
                                  for x in (c.committed if c else []) if x.get("node_id") in data.N],
                    generalized=[dict(attributeLabel=ATTR_LABEL.get(x["attribute"], x["attribute"]),
                                      levelDescription=f"'{data.label(x['to_node'])}'로 넓힘 (턴 {x['turn']})") for x in gen],
                    suppressed=[dict(attributeLabel=f"{ATTR_LABEL.get(x['attribute'], x['attribute'])} (턴 {x['turn']})") for x in sup],
                    finalDecision=risk["policyDecision"], finalDecisionLabel=risk["statusLabel"], notes=notes, stateVersion=risk["version"],
                    source="backend")

    # ── 질문 ──
    def _seed_for(self, it: I.Intent, focus: str):
        return I.candidates(self.session.ctx.seeds, it)[:14]

    def preflight(self, case_id: str, session_id: str, question: str) -> dict[str, Any]:
        with self.eng.lock:
            s = self._check(case_id, session_id)
            k_now = self.k(case_id)
            it = I.parse(question)
            focus = it.case or s.ref
            base = dict(caseId=case_id, question=question, requiresWarning=False, currentK=k_now, projectedK=None, message=None,
                        affectedAttributes=[], suggestions=[], source="backend", supported=True)
            if not it.understood:
                return dict(base, understood=False)
            for seed in self._seed_for(it, focus):
                pv = self.session.preview(seed["seed_id"], self.arm, focus, question)
                if not pv.get("applicable"):
                    continue
                mine = next((c for c in pv["cases"] if c["ref"] == focus), None) or (pv["cases"][0] if pv["cases"] else None)
                if mine is None:
                    return dict(base, understood=True)
                acts = mine.get("defender") or {}
                warn = bool(acts.get(SUPPRESS) or acts.get(GENERALIZE))
                label = mine["ref"].replace("사례", "사례 ")
                attrs = ", ".join(mine["attributes"]) or ATTR_KO.get(seed["target_qi"], seed["target_qi"])
                if acts.get(SUPPRESS):
                    msg = f"그대로 답하면 {label} 후보가 {mine['k_now']}명에서 {mine['k_if_raw']}명으로 줄어듭니다. 보내면 {attrs} 값은 가리고 답합니다."
                elif acts.get(GENERALIZE):
                    msg = f"그대로 답하면 {label} 후보가 {mine['k_now']}명에서 {mine['k_if_raw']}명으로 줄어듭니다. 보내면 {attrs} 값을 넓은 범주로 바꿔 답합니다."
                else:
                    msg = None
                return dict(base, requiresWarning=warn, understood=True, currentK=mine["k_now"], projectedK=mine["k_if_raw"], message=msg,
                            affectedAttributes=mine["attributes"],
                            suggestions=[dict(label=f"{x['label']} 묻기", question=x["question"])
                                         for x in self._ranked(focus, skip=(seed["target_qi"], "PERIOD", "AGE", "SEX", "REGION"))][:2] if warn else [])
            return dict(base, understood=True)

    def _ranked(self, ref: str, skip: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        """지금 이 사례에 물을 수 있는 질문을 단서 종류마다 하나씩 (한 사례 질문, 처음 묻기, 기본 문장 순)."""
        qs = self.session.questions(self.arm, ref)
        out, seen = [], set(skip)
        for q in sorted(qs, key=lambda q: (q["scope"] != "한 사례", q["objective"] != "처음 묻기", q["variant"] != "기본")):
            if q["target_qi"] in seen:
                continue
            seen.add(q["target_qi"])
            out.append(dict(label=q["target_label"], question=q["text"], target=q["target_qi"]))
        return out

    def suggestions(self, case_id: str) -> list[dict[str, Any]]:
        with self.eng.lock:
            s = self.slot(case_id)
            return [dict(label=x["label"], question=x["question"]) for x in self._ranked(s.ref)][:6]

    def ask(self, case_id: str, session_id: str, question: str, client_message_id: str) -> dict[str, Any]:
        question = question.strip()
        if not question:
            raise ValueError("질문이 비어 있습니다.")
        with self.eng.lock:
            s = self._check(case_id, session_id)
            it = I.parse(question)
            focus = it.case or s.ref
            k_before = {cid: self.k(cid) for cid in self.slots}
            rec = None
            if it.understood:
                for seed in self._seed_for(it, focus):
                    if self.session.ask(seed, focus, question, self.arm) is not None:
                        rec = self._records()[-1]
                        break
            self.version += 1
            self.updated_at = _iso()
            return self._reply(s, question, client_message_id, rec, k_before, it)

    # ── 응답 만들기 ──
    def _absorb(self, rec: dict[str, Any], turn_for_entries: int | None) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        """한 턴 기록의 Defender 판정 → 화면 조치 목록과 사례별 공개 이력."""
        data = self.session.ctx.data
        refusal = rec["release_mode"].startswith("REFUSAL")
        cand = rec.get("cases_candidate_k") or {}
        tf, entries = [], {cid: [] for cid in self.slots}
        for p in rec.get("release_plans") or []:
            cid = self.case_of_ref(p["ref"])
            for x in p["decisions"]:
                action = SUPPRESS if refusal else x["action"]
                to_label = data.label(x["to_node"]) if x.get("to_node") in data.N else None
                k_raw = x.get("k_raw") if x.get("k_raw") is not None else cand.get(p["ref"])
                if action == GENERALIZE:
                    value, desc = to_label, f"넓은 범주로 바꿔 공개: {to_label}"
                elif action == SUPPRESS:
                    value = None
                    desc = "거절 문장으로 대체" if refusal else (f"가림 (그대로면 후보 {k_raw}명)" if k_raw is not None else "가림")
                else:
                    value, desc = str(x.get("raw_value") or to_label or ""), "그대로 공개"
                label = ATTR_LABEL.get(x["attribute"], x["attribute"])
                tf.append(dict(id=self._id("tf"), attribute=x["attribute"], attributeLabel=(f"{p['ref'].replace('사례', '사례 ')} {label}"),
                               action=action, disclosedValue=value, levelDescription=desc, caseRef=p["ref"]))
                if cid:
                    turn = rec["turn"] if turn_for_entries is None else turn_for_entries
                    self.slots[cid].decisions.append(dict(x, action=action, turn=turn))
                    entries[cid].append(dict(entryId=self._id("dh"), turn=turn, attribute=x["attribute"], attributeLabel=label, action=action,
                                             description=f"{value}" if action == ALLOW else desc))
        for cid, es in entries.items():
            sl = self.slots[cid]
            sl.history += es
            if es:
                acts = {e["action"] for e in es}
                sl.last_action = SUPPRESS if SUPPRESS in acts else GENERALIZE if GENERALIZE in acts else ALLOW
        return tf, entries

    def _reply(self, s: Slot, question: str, cmid: str, rec: dict[str, Any] | None, k_before: dict[str, int], it: I.Intent) -> dict[str, Any]:
        turn_no = s.questions + 1
        created = _iso()
        if rec is None:
            text = I.HELP_TEXT if not it.understood else "이 질문으로 더 알려 드릴 기록이 없습니다. 다른 항목을 물어보세요."
            tf, entries, mode = [], {cid: [] for cid in self.slots}, "NO_ANSWER"
            explanation = "답할 수 있는 항목을 찾지 못해 사례 기록을 공개하지 않았습니다."
            segments = [dict(kind="text", text=text)]
        else:
            tf, entries = self._absorb(rec, None)
            mode, text = rec["release_mode"], rec["response_text"]
            explanation = self._explain(s, rec, tf, k_before)
            segments = [dict(kind="text", text=text)] if mode.startswith("REFUSAL") else segments_of(text, tf)
        acts = {t["action"] for t in tf}
        decision = SUPPRESS if SUPPRESS in acts else GENERALIZE if GENERALIZE in acts else ALLOW
        k_after = self.k(s.case_id)
        protection = dict(decision=decision, transformations=tf, kBefore=k_before[s.case_id], kAfter=k_after, explanation=explanation,
                          releaseMode=mode, extractionOk=bool(rec["extraction_ok"]) if rec else True)
        user = dict(messageId=cmid, caseId=s.case_id, role="user", turn=turn_no, createdAt=created, segments=[dict(kind="text", text=question)],
                    status="sent")
        asst = dict(messageId=self._id("msg"), caseId=s.case_id, role="assistant", turn=turn_no, createdAt=_iso(), segments=segments,
                    protection=protection, status="sent")
        s.messages += [user, asst]
        s.questions = turn_no
        related = [self.risk_state(cid) for cid in self.slots if cid != s.case_id and (entries[cid] or self.k(cid) != k_before[cid])]
        return dict(userMessage=user, assistantMessage=asst, riskState=self.risk_state(s.case_id), newDisclosures=entries[s.case_id],
                    relatedRiskStates=related)

    def _explain(self, s: Slot, rec: dict[str, Any], tf: list[dict[str, Any]], k_before: dict[str, int]) -> str:
        """화면이 후보 수(전→후)를 따로 보여 주므로 여기서는 무엇을 왜 했는지만 쓴다."""
        mode, g = rec["release_mode"], self.session.ctx.defender.g
        if mode == "REFUSAL_EXTRACTION_FAILED":
            return "답에서 단서를 확인하지 못해 위험을 판단할 수 없었습니다. 그래서 답 대신 거절 문장을 보냈습니다."
        if mode.startswith("REFUSAL"):
            return "고친 답이 다시 확인을 통과하지 못해 거절 문장을 보냈습니다."
        if self.arm == "C0":
            return "방어 없이 원래 답을 그대로 보냈습니다."
        changed = [t for t in tf if t["action"] != ALLOW]
        if not tf:
            return "이 답에는 새로 더해진 단서가 없습니다."
        if not changed:
            return f"새로 나온 단서를 모두 더해도 후보가 {g}명보다 많아 그대로 답했습니다."
        cand = rec.get("cases_candidate_k") or {}
        worst = min((cand[t["caseRef"]] for t in changed if cand.get(t["caseRef"]) is not None), default=None)
        n_sup = sum(t["action"] == SUPPRESS for t in changed)
        n_gen = len(changed) - n_sup
        what = ", ".join(x for x in (f"가림 {n_sup}건" if n_sup else "", f"넓힘 {n_gen}건" if n_gen else "") if x)
        head = f"그대로 답하면 후보가 {worst}명까지 줄어들어 " if worst is not None else ""
        return f"{head}일부 값을 보호해 답했습니다 ({what})."
