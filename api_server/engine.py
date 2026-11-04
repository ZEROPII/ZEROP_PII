# 연구 세션 한 개 = 질의 환자 1명 × 검색 사례 5건 × 실행 갈래 1개 (medical/session.py ArmRun 하나)
#
# 실험(run_experiment)과 다른 점
#   - 질문은 변형기(Seed·연산자)가 아니라 의료진이 직접 쓴다. 턴 0의 자동 사례 검색 질문도 보내지 않는다.
#     그래서 Prefix는 make_prefix 중 LLM을 부르지 않는 앞부분(바인딩 → 검색 → 대상 AI 시스템 프롬프트)만 같은 순서로 만든다.
#   - 매 질문은 ArmRun._turn 을 그대로 부른다: 대상 AI 원 응답 → 추출 → 공개 게이트(C0/C1/C1S) → State 반영 → 사례별 kcalc k.
#   - 대화 이력·State는 ArmRun 하나가 갖는다 (연구 하네스와 같은 단일 대화). 화면의 사례 탭은 대상 AI의 '사례N' 표기와 1:1이고,
#     State는 연구 모듈이 case_ref별로 따로 쌓으므로 사례끼리 섞이지 않는다. 사례 A 탭에서 한 질문에 사례 B가 언급되면
#     그 공개는 사례 B의 State로 들어간다 (그 사례의 누적 위험이므로).
#   - 사용자 질문에 '사례N' 표기가 없으면 탭의 사례를 가리키도록 "사례N에 대한 질문: " 을 앞에 붙여 대상 AI에 보낸다.
#     화면에는 사용자가 쓴 문장 그대로 보인다.
# 화면에 넘기지 않는 것: 원 응답, 검색 문서 본문·사실표, 사례 환자 id·doc_id, 질의 환자 id, 추출기 원 출력.
# 이것들은 서버 쪽 턴기록.jsonl(runs/api/…)에만 남는다.

from __future__ import annotations

import json
import random
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from medical.config import ROOT, MedicalConfig
from medical.data import MedicalData
from medical.defense import ALLOW, GENERALIZE, SUPPRESS
from medical.experiment import build_context, plan_trials
from medical.llm import RoleLLM
from medical.prompts import PROMPTS
from medical.retrieval import code_sets, fill_case_query, panel_text, query_binding, retrieve
from medical.session import ARMS, ArmRun, Prefix, dumps

ATTR_LABEL = dict(AGE="나이", SEX="성별", REGION="거주 지역", DX="진단", PROC="시술", PERIOD="시기(날짜)", MED="처방 약", PLAN="관리 계획")
QTYPE_LABEL = dict(PRESCRIPTION="처방 확인", TREATMENT_PROCEDURE="치료·시술 확인", COURSE_CARE="경과·관리 확인")
ROLE_LABEL = dict(DOCTOR="의료진", RESEARCHER="연구자")
STATE_MODE_LABEL = dict(C0="방어 없음", C1="누적 State 판정", C1S="매 턴 빈 State 판정")
_REF = re.compile(r"\s*사례\s*(\d+)\s*")
_MENTIONS_CASE = re.compile(r"사례\s*\d")


class NotFound(KeyError):
    pass


class Conflict(ValueError):
    pass


@dataclass
class ApiSettings:
    llm: str = "real"                 # real (.env의 모델) | dry-run (medical.llm.MockRoleLLM, 숫자 의미 없음)
    arm: str = "C1"
    trial_id: str = "T0001"           # plan_trials 순서의 질의 환자 (연구 계획과 같은 결정적 선택)
    out: Path | None = None           # 서버 쪽 기록 폴더. 없으면 runs/api/session_<시각>
    store_limit: int | None = None    # 저장소 환자 수 상한 (테스트용)


def make_llm(settings: ApiSettings, cfg: MedicalConfig) -> RoleLLM:
    if settings.llm == "dry-run":
        from medical.llm import MockRoleLLM
        return MockRoleLLM()
    if settings.llm != "real":
        raise ValueError(f"llm은 real 또는 dry-run 이어야 합니다: {settings.llm}")
    from core.config import get_settings
    from core.llm_client import LLMClient
    from medical.llm import ClientRoleLLM
    return ClientRoleLLM(LLMClient(get_settings()), models=cfg.models, temperature=cfg.temperature)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CaseSlot:
    case_id: str
    number: int                       # 대상 AI 표기 '사례N'의 N
    messages: list[dict[str, Any]] = field(default_factory=list)
    questions: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)
    last_action: str = ALLOW
    decisions: list[dict[str, Any]] = field(default_factory=list)   # 지금까지 이 사례에 내려진 Defender 판정 (턴 번호 포함)

    @property
    def label(self) -> str:
        return f"사례 {self.number}"


class ResearchWorkspace:
    def __init__(self, settings: ApiSettings, *, llm: RoleLLM | None = None, data: MedicalData | None = None) -> None:
        if settings.arm not in ARMS:
            raise ValueError(f"arm은 {ARMS} 중 하나여야 합니다: {settings.arm}")
        self.settings = settings
        cfg = MedicalConfig(arms=(settings.arm,))
        self.out = settings.out or ROOT / "runs" / "api" / time.strftime("session_%Y%m%d_%H%M%S")
        self.out.mkdir(parents=True, exist_ok=True)
        self.ctx, split = build_context(cfg, llm or make_llm(settings, cfg), self.out, store_limit=settings.store_limit, data=data)
        plan = {t[0]: t for t in plan_trials(self.ctx.data, split, cfg)}
        if settings.trial_id not in plan:
            raise ValueError(f"연구 계획에 없는 trial입니다: {settings.trial_id} (가능: {', '.join(sorted(plan))})")
        self.prefix = self._prefix(*plan[settings.trial_id])
        self.workspace_id = f"ws-{int(time.time())}"
        self.cases = {f"case-{i}": CaseSlot(f"case-{i}", i) for i in range(1, len(self.prefix.docs) + 1)}
        self._log_file = open(self.out / "턴기록.jsonl", "a", encoding="utf-8")
        self.run = ArmRun(self.ctx, self.prefix, settings.arm, self._log)
        self.turn = 0
        self.version = 1
        self.updated_at = _now()
        self.lock = threading.Lock()
        self._seq = 0

    # ── 준비 ────────────────────────────────────────────────

    def _prefix(self, tid: str, qpid: str, qtype: str, role: str) -> Prefix:
        """medical.session.make_prefix 중 LLM을 부르지 않는 부분과 같은 순서 (난수열도 같다)."""
        ctx = self.ctx
        rng = random.Random(f"{ctx.cfg.seed}-{tid}")
        b = query_binding(ctx.data, qpid, qtype, rng)
        if b is None:
            raise ValueError(f"{tid}의 질의 환자는 {qtype} 유형에 쓸 수 없습니다.")
        cq = rng.choice(ctx.case_queries[qtype])
        base = fill_case_query(cq["template_text"], b)
        ret = retrieve(code_sets(ctx.data.by_pat[qpid], b["index_date"]), ctx.store_sets, ctx.cfg.top_k_retrieval)
        docs = [ctx.docs[p] for p, _ in ret]
        system = PROMPTS["target_system"].format(n=len(docs), panel=panel_text(b), cases="\n\n".join(f"[사례{i}]\n{d['text']}" for i, d in enumerate(docs, 1)))
        return Prefix(tid, qpid, qtype, role, b, cq["case_query_id"], base, docs, ret, system,
                      op0="-", q0="", tries0=[], realization_fallback=False, raw0="", obs0=[], extract_ok0=False, extract_tries0=0)

    def _log(self, rec: dict[str, Any]) -> None:
        self._log_file.write(dumps(rec) + "\n")
        self._log_file.flush()

    def _id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}-{self._seq}"

    def slot(self, case_id: str) -> CaseSlot:
        if case_id not in self.cases:
            raise NotFound(case_id)
        return self.cases[case_id]

    def session_id(self, case_id: str) -> str:
        return f"{self.workspace_id}:{case_id}"

    def case_of_ref(self, ref: str) -> str | None:
        m = _REF.fullmatch(ref)
        cid = f"case-{int(m.group(1))}" if m else None
        return cid if cid in self.cases else None

    def label_of_ref(self, ref: str) -> str:
        cid = self.case_of_ref(ref)
        return self.cases[cid].label if cid else ref

    # ── k (kcalc) ──────────────────────────────────────────

    def committed(self, case_id: str) -> list[dict[str, Any]]:
        """이 사례로 이어지는 case_ref(보통 '사례N' 하나)의 누적 공개. 연구 모듈 State 그대로."""
        out: list[dict[str, Any]] = []
        for ref in self.run.order:
            if self.case_of_ref(ref) == case_id:
                out += self.run.cases[ref].committed
        return out

    def k(self, case_id: str) -> int:
        c = self.committed(case_id)
        return self.ctx.kc.k(c)["k"] if c else self.ctx.p_ref

    # ── 화면 계약으로 옮기기 ───────────────────────────────

    def policy(self) -> dict[str, Any]:
        d, arm = self.ctx.defender, self.settings.arm
        llm = "실제 LLM" if self.settings.llm == "real" else "dry-run 가짜 LLM · 숫자 의미 없음"
        return dict(modeLabel=f"연구 모듈 {arm} ({llm})", arm=arm, stateModeLabel=STATE_MODE_LABEL[arm], minK=d.g, suppressK=d.s,
                    populationSize=self.ctx.p_ref, source="backend")

    def environment(self) -> dict[str, Any]:
        return dict(roleLabel=ROLE_LABEL.get(self.prefix.role, self.prefix.role), locationLabel="ZEROOP2 medical 하네스 · Synthea 합성 환자")

    def patient_context(self) -> dict[str, Any]:
        """질의 환자(현재 환자) 맥락. 사례 환자 데이터와 섞지 않는다. 환자 id는 넘기지 않는다."""
        b, data = self.prefix.binding, self.ctx.data
        main = b["main_dx_node"]
        others = sorted({data.label(e["code_node"]) for e in data.by_pat[self.prefix.query_patient]
                         if e["event_type"] == "CONDITION" and (e["start"] or "")[:10] <= b["index_date"] and main not in data.anc(e["code_node"])})
        return dict(contextId=f"{self.workspace_id}:patient", ageSexLabel=f"{b['QUERY_AGE_BAND']} / {b['QUERY_SEX']}",
                    primaryDiagnosis=b["QUERY_MAIN_DX"], comorbidities=others, plannedProcedure=b["QUERY_RELATED_ITEM"],
                    queryPurpose=QTYPE_LABEL.get(self.prefix.query_type, self.prefix.query_type), source="backend")

    def similar_cases(self, context_id: str) -> list[dict[str, Any]]:
        if context_id != f"{self.workspace_id}:patient":
            raise NotFound(context_id)
        # 사례 문서 내용(진단 등)은 Defender를 거치지 않은 공개가 되므로 목록에 싣지 않는다. 순위와 검색 점수만.
        return [dict(caseId=s.case_id, label=s.label, diagnosis="세부 정보는 질문으로 확인 (Defender 판정 후 공개)",
                     description=f"검색 유사도 {score:.3f} (DX·MED·PROC 코드 집합 Jaccard 평균)", similarityRank=s.number)
                for s, (_, score) in zip(self.cases.values(), self.prefix.retrieval)]

    def risk_state(self, case_id: str) -> dict[str, Any]:
        s, d, arm = self.slot(case_id), self.ctx.defender, self.settings.arm
        k = self.k(case_id)
        # 표시 구간은 Defender 기준값(generalize·suppress)에서만 나온다. 새 기준을 만들지 않는다.
        if k == 0:
            level, label = "blocked", "후보 일치 없음 (k = 0, ZERO_MATCH)"
        elif k <= d.s:
            level, label = "danger", f"위험 · k ≤ {d.s}"
        elif k <= d.g:
            level, label = "blocked", f"추가 공개 제한 · k ≤ {d.g}"
        else:
            level, label = "safe", f"기준 초과 · k > {d.g}"
        restricted = arm == "C1" and d.risky(k)
        if arm != "C1" and d.risky(k):
            label += " (C0: 방어 없음)" if arm == "C0" else " (C1S: 누적 State로 판정하지 않음)"
        return dict(caseId=case_id, k=k, riskLevel=level, statusLabel=label, disclosureAllowed=not restricted,
                    policyDecision="restrict" if restricted else s.last_action, version=self.version, updatedAt=self.updated_at)

    def conversation(self, case_id: str) -> dict[str, Any]:
        s = self.slot(case_id)
        return dict(sessionId=self.session_id(case_id), caseId=case_id, messages=s.messages, questionCount=s.questions)

    def disclosures(self, case_id: str) -> dict[str, Any]:
        return dict(caseId=case_id, entries=self.slot(case_id).history)

    def policy_decision(self, case_id: str) -> dict[str, Any]:
        s, d, data = self.slot(case_id), self.ctx.defender, self.ctx.data
        risk = self.risk_state(case_id)
        gen = [x for x in s.decisions if x["action"] == GENERALIZE]
        sup = [x for x in s.decisions if x["action"] == SUPPRESS]
        notes = [f"판정 정책은 risk_defender와 같습니다: 새 공개를 모두 넣은 k > {d.g}이면 그대로, 아니면 공개마다 원래 값 k ≤ {d.s}이면 비공개, "
                 f"그 외에는 k > {d.g}(없으면 > {d.s})가 되는 첫 상위 개념으로 일반화합니다.",
                 "k는 kcalc 사건 단위 계산입니다 (같은 사건의 진단·나이·날짜는 한 사건이 함께 만족해야 후보).",
                 f"공개된 QI는 공개된 답변을 다시 추출해 State에 넣은 값입니다. 사례끼리 State를 공유하지 않습니다."]
        if self.settings.arm == "C1S":
            notes.append("C1S: Defender가 매 턴 빈 State에서 판정합니다 (누적 State의 기여를 보기 위한 대조군).")
        if self.settings.arm == "C0":
            notes.append("C0: Defender 없이 원 응답을 그대로 공개합니다.")
        return dict(caseId=case_id, currentK=risk["k"], minK=d.g, suppressK=d.s, arm=self.settings.arm,
                    disclosedQis=[dict(attributeLabel=ATTR_LABEL.get(c["attribute"], c["attribute"]), levelDescription=data.label(c["node_id"]))
                                  for c in self.committed(case_id) if c.get("node_id") in data.N],
                    generalized=[dict(attributeLabel=ATTR_LABEL.get(x["attribute"], x["attribute"]),
                                      levelDescription=f"{x['steps']}단계 상위 개념 '{data.label(x['to_node'])}'로 (턴 {x['turn']})") for x in gen],
                    suppressed=[dict(attributeLabel=f"{ATTR_LABEL.get(x['attribute'], x['attribute'])} (턴 {x['turn']})") for x in sup],
                    finalDecision=risk["policyDecision"], finalDecisionLabel=risk["statusLabel"], notes=notes, stateVersion=risk["version"],
                    source="backend")

    def preflight(self, case_id: str, session_id: str, question: str) -> dict[str, Any]:
        self._check_session(case_id, session_id)
        # 연구 모듈의 추출기는 답변에서만 QI를 뽑는다. 질문만으로 k를 미리 계산하는 기능은 없으므로 만들지 않는다.
        return dict(caseId=case_id, question=question, requiresWarning=False, currentK=self.k(case_id), projectedK=None,
                    message="사전 위험 평가는 연구 모듈에 없어 제공하지 않습니다. 전송하면 Defender가 답변을 판정합니다.",
                    affectedAttributes=[], suggestions=[], source="backend", supported=False)

    def _check_session(self, case_id: str, session_id: str) -> CaseSlot:
        s = self.slot(case_id)
        if session_id != self.session_id(case_id):
            raise Conflict("세션이 일치하지 않습니다.")
        return s

    # ── 질문 한 건 ─────────────────────────────────────────

    def ask(self, case_id: str, session_id: str, question: str, client_message_id: str) -> dict[str, Any]:
        question = question.strip()
        if not question:
            raise ValueError("질문이 비어 있습니다.")
        with self.lock:
            s = self._check_session(case_id, session_id)
            k_before = {cid: self.k(cid) for cid in self.cases}
            query = question if _MENTIONS_CASE.search(question) else f"사례{s.number}에 대한 질문: {question}"
            # LLM 오류(LLMError)는 State를 바꾸기 전에 난다 (ArmRun._turn은 응답·추출·게이트를 끝낸 뒤에만 State에 반영).
            rec = self.run._turn(self.turn + 1, query, None, None, None, 0,
                                 dict(source="api", case_id=case_id, client_message_id=client_message_id, user_question=question))
            self.turn += 1
            self.version += 1
            self.updated_at = _now()
            return self._record(s, question, client_message_id, rec, k_before)

    def _decisions(self, rec: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        """case_ref → 이번 턴 판정 목록. C1·C1S는 Defender 계획, C0은 공개된 답변의 commit 관찰(모두 allow)."""
        out: dict[str, list[dict[str, Any]]] = {}
        if rec["release_plans"]:
            for p in rec["release_plans"]:
                out[p["ref"]] = [dict(x, k_before=p["k_before"], k_projected=p["k_projected"]) for x in p["decisions"]]
        elif rec["release_mode"] == "RAW":
            for ref, c in rec["cases"].items():
                if ref == "UNCLEAR":
                    continue
                out[ref] = [dict(attribute=o["attribute"], node_id=o["node_id"], raw_value=o.get("raw_value"), action=ALLOW,
                                 to_node=o["node_id"], k_raw=None, steps=0, max_steps=0)
                            for o in c.get("normalized", []) if o.get("commit")]
        return out

    def _record(self, s: CaseSlot, question: str, client_message_id: str, rec: dict[str, Any], k_before: dict[str, int]) -> dict[str, Any]:
        data, mode = self.ctx.data, rec["release_mode"]
        refusal = mode.startswith("REFUSAL")
        text = rec["response_text"]
        turn_no = s.questions + 1
        created = _now()
        transformations, new_entries = [], {cid: [] for cid in self.cases}
        for ref, decs in self._decisions(rec).items():
            cid = self.case_of_ref(ref)
            prefix = "" if cid == s.case_id else f"{self.label_of_ref(ref)} · "
            for x in decs:
                action = SUPPRESS if refusal else x["action"]
                to_label = data.label(x["to_node"]) if x.get("to_node") in data.N else None
                if action == GENERALIZE:
                    desc = f"{x['steps']}단계 상위 개념으로 → {to_label}"
                    value = to_label
                elif action == SUPPRESS:
                    desc = "거절 응답으로 대체 (공개 안 함)" if refusal else "공개하지 않음"
                    value = None
                else:
                    desc = "그대로 공개"
                    value = str(x.get("raw_value") or to_label or "")
                tid = self._id("tf")
                transformations.append(dict(id=tid, attribute=x["attribute"], attributeLabel=prefix + ATTR_LABEL.get(x["attribute"], x["attribute"]),
                                            action=action, disclosedValue=value, levelDescription=desc))
                if cid:
                    slot = self.cases[cid]
                    slot.decisions.append(dict(x, action=action, turn=self.turn))
                    new_entries[cid].append(dict(entryId=self._id("dh"), turn=self.turn, attribute=x["attribute"],
                                                 attributeLabel=ATTR_LABEL.get(x["attribute"], x["attribute"]), action=action,
                                                 description=f"{value} (그대로 공개)" if action == ALLOW else desc, value=value))
        for cid, entries in new_entries.items():
            slot = self.cases[cid]
            slot.history += entries
            if entries:
                acts = {e["action"] for e in entries}
                slot.last_action = SUPPRESS if acts == {SUPPRESS} else GENERALIZE if acts - {ALLOW} else ALLOW
        acts = {t["action"] for t in transformations}
        decision = SUPPRESS if refusal or (acts and acts == {SUPPRESS}) else GENERALIZE if acts - {ALLOW} else ALLOW
        k_after = self.k(s.case_id)
        protection = dict(decision=decision, transformations=transformations, kBefore=k_before[s.case_id], kAfter=k_after,
                          explanation=self._explain(s, rec, transformations, k_before[s.case_id], k_after),
                          releaseMode=mode, extractionOk=bool(rec["extraction_ok"]))
        # engineTurn: 대화 전체 턴 번호(공개 이력 turn과 같은 번호). 의료진 화면 사례 노트가 질문과 이력을 잇는 데 쓴다.
        user_msg = dict(messageId=client_message_id, caseId=s.case_id, role="user", turn=turn_no, createdAt=created,
                        segments=[dict(kind="text", text=question)], status="sent", engineTurn=self.turn)
        asst_msg = dict(messageId=self._id("msg"), caseId=s.case_id, role="assistant", turn=turn_no, createdAt=_now(),
                        segments=[dict(kind="text", text=text)] if refusal else segments_of(text, transformations),
                        protection=protection, status="sent", engineTurn=self.turn)
        s.messages += [user_msg, asst_msg]
        s.questions = turn_no
        related = [self.risk_state(cid) for cid in self.cases if cid != s.case_id and (new_entries[cid] or self.k(cid) != k_before[cid])]
        return dict(userMessage=user_msg, assistantMessage=asst_msg, riskState=self.risk_state(s.case_id),
                    newDisclosures=new_entries[s.case_id], relatedRiskStates=related)

    def _explain(self, s: CaseSlot, rec: dict[str, Any], tf: list[dict[str, Any]], k0: int, k1: int) -> str:
        mode, arm, g = rec["release_mode"], self.settings.arm, self.ctx.defender.g
        n_gen = sum(t["action"] == GENERALIZE for t in tf)
        n_sup = sum(t["action"] == SUPPRESS for t in tf)
        k_txt = f"{s.label}의 후보 수 k {k0}" + (f" → {k1}." if k1 != k0 else " 유지.")
        if mode == "REFUSAL_EXTRACTION_FAILED":
            return f"원 응답에서 QI 추출에 실패해 위험을 판단할 수 없으므로 거절 문장을 공개했습니다 (fail-closed). {k_txt}"
        if mode == "REFUSAL":
            return f"Defender 변경안을 적용한 답변이 재추출 확인을 통과하지 못해 거절 문장을 공개했습니다. {k_txt}"
        if arm == "C0":
            head = "C0(방어 없음): 원 응답을 그대로 공개했습니다."
            if not rec["extraction_ok"]:
                head += " QI 추출에 실패해 이번 공개는 State에 반영되지 않았습니다."
            return f"{head} {k_txt}"
        if not tf:
            return f"이 답변에서 State에 넣을 새 준식별자가 추출되지 않았습니다. {k_txt}"
        if mode == "RAW":
            return f"새 공개 {len(tf)}건을 모두 넣어도 k > {g}라서 그대로 공개했습니다. {k_txt}"
        how = "재작성기 LLM으로 고친 뒤" if mode == "REWRITTEN" else "재작성 결과가 확인을 통과하지 못해 결정적 치환으로 고친 뒤"
        return f"Defender 판정에 따라 {n_gen}건 일반화 · {n_sup}건 비공개 처리했습니다 ({how} 재추출 확인 통과). {k_txt}"


SUPPRESSED_MARK = "(비공개)"


def segments_of(text: str, transformations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    공개된 본문에서 각 조치의 공개 표현(그대로 공개한 값, 일반화한 값, '(비공개)' 표시)이 처음 나오는 곳을 찾아 조각으로 나눈다.
    글자 그대로 찾을 수 없는 조치(재작성기가 다른 표현을 쓴 경우)는 표시만 빠지고 protection.transformations에는 남는다.
    """
    spans: list[tuple[int, int, str]] = []
    taken = lambda a, b: any(a < y and x < b for x, y, _ in spans)
    for t in sorted(transformations, key=lambda t: -len(t["disclosedValue"] or SUPPRESSED_MARK)):
        needle = t["disclosedValue"] if t["action"] != SUPPRESS else SUPPRESSED_MARK
        if not needle:
            continue
        start = 0
        while (i := text.find(needle, start)) >= 0:
            if not taken(i, i + len(needle)):
                spans.append((i, i + len(needle), t["id"]))
                break
            start = i + 1
    out, pos = [], 0
    for a, b, tid in sorted(spans):
        if a > pos:
            out.append(dict(kind="text", text=text[pos:a]))
        out.append(dict(kind="disclosure", text=text[a:b], transformationId=tid))
        pos = b
    if pos < len(text):
        out.append(dict(kind="text", text=text[pos:]))
    return out


def usage_summary(ws: ResearchWorkspace) -> dict[str, Any]:
    """역할별 호출 수 (토큰·지연 포함). 화면용 아님, 점검용."""
    by: dict[str, int] = {}
    for u in ws.ctx.llm.usage:
        by[u["role"]] = by.get(u["role"], 0) + 1
    return dict(calls=by, log=str(ws.out / "턴기록.jsonl"))


def write_usage(ws: ResearchWorkspace) -> None:
    with open(ws.out / "llm_usage.jsonl", "w", encoding="utf-8") as f:
        for u in ws.ctx.llm.usage:
            f.write(json.dumps(u, ensure_ascii=False) + "\n")
