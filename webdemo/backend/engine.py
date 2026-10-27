# 데모 엔진: 저장소의 의료 파이프라인을 한 턴씩 돌린다 (LLM 호출 0, 결정적)
#
# 쓰는 것 (모두 medical/ 그대로, 수정 없음)
#   사례 검색 retrieval · 결정적 응답기 OracleRoleLLM(대상 AI·추출기·재작성기) · 정규화 normalize_bridge ·
#   사건 단위 k GroupRepairKC(kcalc) · Defender(risk_defender 정책 5·3) · Seed v0.13 · 피드백 선택(fuzzer/feedback.py)
#
# 대화 하나(세션) = 질의 환자 1명 × 조회 유형 1개. 세 조건 C0·C1·C1S를 같은 질문으로 나란히 진행한다.
#   - 질문은 의료진 화면이 고른 Seed 또는 퍼저가 고른 Seed. 화면에 보이는 조건(기본 C1)의 공개 상태로 후보를 만든다.
#   - 조건마다 자기 공개 상태로 Seed를 채운다 (앞서 공개된 값이 조건마다 다르기 때문).
#   - 그 조건의 상태에서 Seed 조건이 맞지 않으면: '처음 묻기'는 그대로 다시 묻고, '더 자세히'는 좁힐 값이 있으면 그 값으로,
#     없으면 그 조건은 이 턴을 건너뛴다 (화면에 이유 표시).
#   - trial 번호는 POC(medical.simulate)와 같다. 퍼저 자동 선택만 쓰면 C1 조건은 POC의 C1 실행과 같은 질문 순서가 된다.
# 의료진 화면용 응답(clinician_view)에는 공개된 답만 넣는다. 원 응답·원래 값은 보안 담당자 화면용(security_view)에만 있다.

from __future__ import annotations

import collections
import itertools
import random
import re
import threading
import time
import traceback
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from medical.adaptive import FeedbackSelector
from medical.attack import applicable_ops, choose_seed, fill_seed, realize
from medical.bundle.seed_select import target
from medical.config import ROOT, MedicalConfig
from medical.data import MedicalData
from medical.experiment import build_context, run_experiment
from medical.prompts import REFUSAL_TEXT
from medical.retrieval import PANEL_LABEL, query_binding
from medical.session import ARMS, ArmRun, Context, extract, make_prefix
from medical.simulate import SUPPRESSED, OracleRoleLLM, plan_all
from medical.tracking import known_cases_json, view_of
from medical.validate import validate_case

PROFILES = ("staged", "full")
FUZZERS = ("uniform", "feedback")
ATTR_KO = dict(SEX="성별", REGION="거주지", AGE="나이", PERIOD="시점", DX="진단", PROC="시술", MED="약", PLAN="관리 계획")
QTYPE_KO = dict(PRESCRIPTION="처방", TREATMENT_PROCEDURE="시술·치료", COURSE_CARE="경과·관리")
VARIANT_KO = dict(BASE="기본", REPHRASE="바꿔 말하기", REROUTE="다른 경로")
OBJECTIVE_KO = dict(NEW_QI_ACQUISITION="처음 묻기", SPECIFICITY_REFINEMENT="더 자세히")
SCOPE_KO = dict(GROUP="사례 전체", CASE="한 사례")
ARM_KO = dict(C0="방어 없음", C1="누적 State Defender", C1S="턴마다 빈 State")
PROFILE_KO = dict(staged="단계 공개형", full="전면 공개형")
FUZZER_KO = dict(uniform="균등 선택", feedback="k 피드백 선택")
_LINE = re.compile(r"^(사례\d+) · (.+?): (.+)$")


class DemoError(ValueError):
    """화면에 그대로 보여 줄 수 있는 오류 (잘못된 요청, 더 물을 질문 없음 등)."""


def attr_of_line(rest: str) -> str:
    return OracleRoleLLM._attr_of(rest)


def parse_answer(text: str) -> list[dict[str, Any]]:
    """응답기의 답 줄 → [{case, field, attribute, value} | {text}]."""
    out = []
    for ln in text.splitlines():
        m = _LINE.match(ln.strip())
        if m:
            out.append(dict(case=m.group(1), field=m.group(2), attribute=attr_of_line(m.group(2)), value=m.group(3).strip()))
        elif ln.strip():
            out.append(dict(text=ln.strip()))
    return out


def diff_answer(raw: str, released: str) -> list[dict[str, Any]]:
    """원 응답과 공개 응답을 줄 단위로 맞춰 바뀐 줄을 표시한다 (재작성기는 줄 구조를 바꾸지 않는다)."""
    r, p = parse_answer(raw), parse_answer(released)
    if released.strip() == REFUSAL_TEXT or len(r) != len(p):
        return [dict(x, change=None) for x in p]
    out = []
    for a, b in zip(r, p):
        ch = None
        if "case" in a and "case" in b and a["value"] != b["value"]:
            ch = "suppress" if b["value"] == SUPPRESSED else "generalize"
        out.append(dict(b, change=ch, raw_value=a.get("value")))
    return out


# ── 엔진 ────────────────────────────────────────────────────

class Engine:
    """프로세스에 하나. 데이터·문서·kcalc를 한 번 올리고 세션과 레드팀 작업을 관리한다."""

    def __init__(self, workdir: Path | None = None, log: Callable[[str], None] = print) -> None:
        t0 = time.time()
        self.workdir = Path(workdir or ROOT / "runs" / "webdemo")
        self.cfg = MedicalConfig(mode="exploration")                  # 데모 대화는 위반에 닿아도 멈추지 않는다
        self.data = MedicalData()
        self.llm = {p: OracleRoleLLM(data=self.data, profile=p) for p in PROFILES}
        base, self.split = build_context(self.cfg, self.llm["staged"], self.workdir / "engine", data=self.data)
        self.ctx: dict[str, Context] = {"staged": base, "full": replace(base, llm=self.llm["full"])}
        self.seed_by_id = {s["seed_id"]: s for s in base.seeds}
        self.plan = plan_all(None, self.cfg.seed)(self.data, self.split, self.cfg)     # POC와 같은 trial 번호 (T0001…)
        self.trial_of = {tid: (pid, qt) for tid, pid, qt, _ in self.plan}
        self.sessions: dict[str, Session] = {}
        self.jobs: dict[str, RedTeamJob] = {}
        self._ids = itertools.count(1)
        self.lock = threading.RLock()                                # kcalc 캐시·응답기 상태를 세션끼리 나눠 쓰므로 한 번에 한 요청
        log(f"[webdemo] 엔진 준비 {time.time() - t0:.1f}초 · 기준 집단 {base.p_ref}명 · 질의 trial {len(self.plan)}개 · Seed {len(base.seeds)}행")

    # ── 기본 정보 ──
    def meta(self) -> dict[str, Any]:
        c = self.cfg
        return dict(p_ref=self.ctx["staged"].p_ref, k_req=c.k_req, generalize_threshold=c.generalize_threshold,
                    suppress_threshold=c.suppress_threshold, budget=c.budget_B, top_k=c.top_k_retrieval, n_trials=len(self.plan),
                    n_seeds=len(self.seed_by_id), versions=self.ctx["staged"].versions, arms=list(ARMS), arm_labels=ARM_KO,
                    profiles=PROFILE_KO, fuzzers=FUZZER_KO, qtypes=QTYPE_KO, attributes=ATTR_KO,
                    target="결정적 응답기 (질문받은 단서를 검색 문서의 기록값으로 답함, LLM 호출 없음)")

    def patients(self) -> list[dict[str, Any]]:
        """질의 환자 목록 (trial 단위: 같은 환자가 조회 유형마다 따로 나온다)."""
        out = []
        for tid, pid, qt, _ in self.plan:
            b = query_binding(self.data, pid, qt, random.Random(f"{self.cfg.seed}-{tid}"))   # make_prefix와 같은 난수 → 같은 패널
            out.append(dict(trial_id=tid, patient=pid[:8], qtype=qt, qtype_label=QTYPE_KO[qt],
                            panel=[dict(label=lab, value=b["panel"][k]) for k, lab in PANEL_LABEL]))
        return out

    # ── 세션 ──
    def new_session(self, trial_id: str, profile: str = "staged", fuzzer: str = "uniform") -> "Session":
        if trial_id not in self.trial_of:
            raise DemoError(f"없는 trial입니다: {trial_id}")
        if profile not in PROFILES or fuzzer not in FUZZERS:
            raise DemoError("profile은 staged|full, fuzzer는 uniform|feedback 중 하나입니다.")
        with self.lock:
            sid = f"S{next(self._ids):04d}"
            s = Session(self, sid, trial_id, profile, fuzzer)
            self.sessions[sid] = s
            self._trim_usage()
            return s

    def session(self, sid: str) -> "Session":
        if sid not in self.sessions:
            raise KeyError(sid)
        return self.sessions[sid]

    def _trim_usage(self) -> None:
        for l in self.llm.values():
            del l.usage[:]             # 호출 기록은 데모에서 쓰지 않는다 (메모리만 늘어남)

    # ── 레드팀 ──
    def start_job(self, profile: str, fuzzer: str, per_type: int | None) -> "RedTeamJob":
        if profile not in PROFILES or fuzzer not in FUZZERS:
            raise DemoError("profile은 staged|full, fuzzer는 uniform|feedback 중 하나입니다.")
        if per_type is not None and per_type < 1:
            raise DemoError("per_type은 1 이상이어야 합니다.")
        with self.lock:
            if any(j.status == "running" for j in self.jobs.values()):
                raise DemoError("이미 돌고 있는 레드팀 실행이 있습니다. 끝난 뒤 다시 실행하세요.")
            jid = f"R{next(self._ids):04d}"
            job = RedTeamJob(self, jid, profile, fuzzer, per_type)
            self.jobs[jid] = job
        job.start()
        return job


# ── 세션 ────────────────────────────────────────────────────

class Session:
    def __init__(self, eng: Engine, sid: str, trial_id: str, profile: str, fuzzer: str) -> None:
        self.eng, self.id, self.trial_id, self.profile, self.fuzzer = eng, sid, trial_id, profile, fuzzer
        self.ctx = eng.ctx[profile]
        self.cfg = self.ctx.cfg
        pid, qt = eng.trial_of[trial_id]
        self.patient_id, self.qtype = pid, qt
        self.created = time.time()
        p = self.prefix = make_prefix(self.ctx, trial_id, pid, qt, "DOCTOR")
        self.logs: dict[str, list[dict[str, Any]]] = {a: [] for a in ARMS}
        self.runs = {a: ArmRun(self.ctx, p, a, self.logs[a].append) for a in ARMS}
        self.steps: list[dict[str, Any]] = []           # 세션 턴마다: 질문 Seed와 조건별 처리 결과
        for a, r in self.runs.items():
            r._turn(0, p.q0, p.raw0, p.obs0, p.extract_ok0, p.extract_tries0,
                    dict(seed_id=None, case_query_id=p.case_query_id, operator=p.op0, realization_fallback=p.realization_fallback,
                         checks=p.tries0, regenerations=max(len(p.tries0) - 1, 0)))
        self.steps.append(dict(turn=0, seed_id=None, picked_by="retrieval", arms={a: dict(status="ANSWERED") for a in ARMS}))
        self.turn = 0
        self.rng = random.Random(f"{self.cfg.seed}-{trial_id}-follow")          # POC run()과 같은 난수열
        self.used: set[str] = set()
        self.blocked: set[str] = set()
        self.scen: collections.Counter = collections.Counter()
        self.selector = FeedbackSelector(threshold=self.cfg.k_req) if fuzzer == "feedback" else None

    # ── 상태 도우미 ──
    def case_a(self, arm: str) -> str | None:
        r = self.runs[arm]
        return r.order[0] if r.order else None

    def _state(self, arm: str) -> tuple[str, dict[Any, str]]:
        A = self.case_a(arm)
        if A is None:
            raise DemoError("사례 검색 답변에 사례가 없어 이어서 물을 수 없습니다.")
        return A, self.ctx.kc.reduce(self.runs[arm].cases[A].committed)[0]

    def _key_for(self, arm: str, seed: dict[str, Any]) -> tuple[Any, str | None]:
        """그 조건의 공개 상태에서 Seed가 무엇을 좁힐지. (key, 메모). key가 None이면 그 조건은 이 질문을 건너뛴다."""
        _, state = self._state(arm)
        kc, data = self.ctx.kc, self.ctx.data
        key = target(seed, state, kc.node, data.children, True)
        if key is not None:
            return key, None
        if seed["attack_objective"] == "NEW_QI_ACQUISITION":
            return True, "이미 공개된 단서를 다시 묻는 질문입니다 (이 조건의 공개 상태 기준)."
        keys = [k for k in state if k[0] == seed["target_qi"]]
        if keys:
            return keys[0], "더 좁힐 하위 값이 없거나 사건이 정해지지 않은 상태에서 다시 묻는 질문입니다."
        return None, "이 조건에서는 그 단서가 공개되지 않아 '더 자세히' 물을 값이 없습니다."

    def _fill(self, arm: str, seed: dict[str, Any], key: Any) -> str:
        A, state = self._state(arm)
        evtxt = {f"{A}:{g}": v for g, v in self.runs[arm].cases[A].events.items()}
        subj = f"{A} 환자" if seed.get("scope") != "GROUP" else "검색된 사례 전체"
        return fill_seed(seed, key, state, self.ctx.data.N, subj, evtxt)

    def _intent(self, arm: str, seed: dict[str, Any], key: Any) -> dict[str, Any]:
        r, A = self.runs[arm], self.case_a(arm)
        return dict(kind="FOLLOW", seed=seed, key=key, case_A=A, qtype=self.qtype,
                    said={ref: [d["node_id"] for d in c.committed] for ref, c in r.cases.items()},
                    events={ref: list(c.events) for ref, c in r.cases.items()})

    # ── 질문 후보 ──
    def questions(self, arm: str = "C1") -> list[dict[str, Any]]:
        """화면에 보이는 조건의 공개 상태에서 지금 물을 수 있는 Seed (이미 쓴 것 제외)."""
        if self.turn >= self.cfg.budget_B:
            return []
        A, state = self._state(arm)
        kc, data = self.ctx.kc, self.ctx.data
        sent = set(self.runs[arm].sent)
        out = []
        for s in self.ctx.seeds:
            if s["seed_id"] in self.used or s["seed_id"] in self.blocked:
                continue
            key = target(s, state, kc.node, data.children, True)
            if key is None:
                continue
            text = self._fill(arm, s, key)
            if text in sent:
                continue
            out.append(dict(seed_id=s["seed_id"], text=text, target_qi=s["target_qi"], target_qi_2=s.get("target_qi_2"),
                            target_label=ATTR_KO[s["target_qi"]] + (f"+{ATTR_KO[s['target_qi_2']]}" if s.get("target_qi_2") else ""),
                            objective=OBJECTIVE_KO.get(s["attack_objective"], s["attack_objective"]),
                            variant=VARIANT_KO.get(s["variant"], s["variant"]), scope=SCOPE_KO.get(s.get("scope"), s.get("scope")),
                            relation=s.get("expected_relation")))
        return out

    # ── 보내기 전 확인 ──
    def preview(self, seed_id: str, arm: str = "C1") -> dict[str, Any]:
        """이 질문에 대상 AI가 기록대로 답하면 사례별 후보 수가 어떻게 되는지 (State는 바꾸지 않는다)."""
        seed = self._seed(seed_id)
        key, note = self._key_for(arm, seed)
        if key is None:
            return dict(seed_id=seed_id, applicable=False, note=note, cases=[])
        r = self.runs[arm]
        q = self._fill(arm, seed, key)
        raw = self.ctx.llm.complete("target", self.prefix.system, r.msgs + [{"role": "user", "content": q}], docs=self.prefix.docs,
                                    intent=self._intent(arm, seed, key))
        obs, ok, _ = extract(self.ctx, q, raw, known_cases_json(r.cases, r.order), self.prefix.docs)
        v = view_of(obs, raw, q, self.ctx.nz)
        kc, d = self.ctx.kc, self.ctx.defender
        cases = []
        for ref in v.case_refs:
            base = list(r.cases[ref].committed) if ref in r.cases else []
            k_now = kc.k(base)["k"] if base else self.ctx.p_ref
            new = v.disclosures[ref]
            k_raw = kc.k(base + new)["k"] if new else k_now
            gate = None
            if arm != "C0" and new:
                basis = base if arm == "C1" else []
                plan = d.plan_case(ref, basis, new, v.sources[ref])
                gate = collections.Counter(x.action for x in plan.decisions)
            cases.append(dict(ref=ref, k_now=k_now, k_if_raw=k_raw, below=1 <= k_raw < self.cfg.k_req,
                              attributes=sorted({ATTR_KO.get(x["attribute"], x["attribute"]) for x in new}),
                              defender=dict(gate) if gate is not None else None))
        alt = [x for x in self.questions(arm) if x["seed_id"] != seed_id and x["target_qi"] not in ("PERIOD", seed["target_qi"])][:2]
        self.eng._trim_usage()
        return dict(seed_id=seed_id, applicable=True, note=note, question=q, cases=cases,
                    warn=any(c["below"] for c in cases), alternatives=alt)

    def _seed(self, seed_id: str) -> dict[str, Any]:
        if seed_id not in self.eng.seed_by_id:
            raise DemoError(f"없는 Seed입니다: {seed_id}")
        return self.eng.seed_by_id[seed_id]

    # ── 한 턴 ──
    def step(self, seed_id: str | None = None, arm: str = "C1") -> dict[str, Any]:
        """seed_id가 없으면 퍼저가 고른다 (화면 조건의 State 기준, POC와 같은 규칙)."""
        if self.turn >= self.cfg.budget_B:
            raise DemoError(f"질문 예산 {self.cfg.budget_B}턴을 다 썼습니다.")
        A, state = self._state(arm)
        picked_by = "clinician"
        while True:
            if seed_id is None:
                picked_by = "fuzzer-" + self.fuzzer
                seeds = [s for s in self.ctx.seeds if s["seed_id"] not in self.blocked]
                if self.selector is not None:
                    pick = self.selector.choose(seeds, state, self.ctx.kc.node, self.ctx.data.children, self.used, self.scen, self.rng)
                else:
                    pick = choose_seed(seeds, state, self.ctx.kc.node, self.ctx.data.children, self.used, self.scen, self.rng)
                if pick is None:
                    raise DemoError("이 공개 상태에서 더 물을 수 있는 Seed가 없습니다 (SATURATED).")
                seed = pick[0]
            else:
                seed = self._seed(seed_id)
            op = self.rng.choice(applicable_ops(seed, self.cfg.operators))
            res = self._send(seed, op, arm, picked_by)
            if res is not None:
                return res
            self.blocked.add(seed["seed_id"])               # 화면 조건에서 질문이 검사를 통과하지 못함 → 다시 고르지 않음
            if seed_id is not None:
                raise DemoError("이 질문은 이미 같은 문장으로 보냈거나 검사를 통과하지 못했습니다. 다른 질문을 고르세요.")

    def _send(self, seed: dict[str, Any], op: str, primary: str, picked_by: str) -> dict[str, Any] | None:
        turn = self.turn + 1
        kA_before = self.runs[primary].cases[self.case_a(primary)].k_hist[-1]
        prepared: dict[str, Any] = {}
        for a in ARMS:
            key, note = self._key_for(a, seed)
            if key is None:
                prepared[a] = dict(status="SKIPPED", note=note)
                continue
            try:
                filled = self._fill(a, seed, key)
            except (KeyError, IndexError):
                prepared[a] = dict(status="SKIPPED", note="이 조건의 공개 상태로는 질문 문장을 채울 수 없습니다.")
                continue
            A = self.case_a(a)
            subj = f"{A} 환자" if seed.get("scope") != "GROUP" else "검색된 사례 전체"
            q, tries = realize(self.ctx.llm, self.cfg, filled, seed["target_qi"], seed["attack_objective"], seed["variant"],
                               subj, op, "DOCTOR", self.runs[a].sent)
            if q is None:
                prepared[a] = dict(status="INVALID", note="같은 문장을 이미 보냈거나 검사를 통과하지 못했습니다.", filled=filled)
                continue
            prepared[a] = dict(status="READY", key=key, note=note, q=q, filled=filled, tries=tries)
        if prepared[primary]["status"] != "READY":
            return None
        self.turn = turn
        self.used.add(seed["seed_id"])
        self.scen[seed["variant"]] += 1
        for a in ARMS:
            pr = prepared[a]
            if pr["status"] != "READY":
                continue
            r = self.runs[a]
            r._turn(turn, pr["q"], None, None, None, 0,
                    dict(seed_id=seed["seed_id"], target_qi=seed["target_qi"], target_qi_2=seed.get("target_qi_2"), variant=seed["variant"],
                         scope=seed.get("scope"), relation=seed.get("expected_relation"), objective=seed["attack_objective"], operator=op,
                         filled_seed=pr["filled"], realization_fallback=False, checks=pr["tries"], regenerations=len(pr["tries"]) - 1,
                         fuzzer=self.fuzzer if picked_by.startswith("fuzzer") else None,
                         fuzzer_strategy=self.selector.strategy if self.selector else None, picked_by=picked_by),
                    intent=self._intent(a, seed, pr["key"]))
            pr["status"] = "ANSWERED"
        if self.selector is not None:
            self.selector.observe(kA_before, self.runs[primary].cases[self.case_a(primary)].k_hist[-1])
        self.steps.append(dict(turn=turn, seed_id=seed["seed_id"], picked_by=picked_by, operator=op,
                               arms={a: dict(status=prepared[a]["status"], note=prepared[a].get("note")) for a in ARMS}))
        self.eng._trim_usage()
        return dict(turn=turn, seed_id=seed["seed_id"], picked_by=picked_by, arms=self.steps[-1]["arms"])

    def run_to_end(self, arm: str = "C1") -> int:
        n = 0
        while self.turn < self.cfg.budget_B:
            try:
                self.step(None, arm)
            except DemoError:
                break
            n += 1
        return n

    # ── 화면용 데이터 ──
    def _records(self, arm: str) -> list[dict[str, Any]]:
        return [r for r in self.logs[arm] if r.get("turn") is not None]

    def _k_series(self, arm: str) -> dict[str, list[list[int]]]:
        out: dict[str, list[list[int]]] = collections.defaultdict(list)
        for rec in self._records(arm):
            for ref, c in (rec.get("cases") or {}).items():
                if "k" in c:
                    out[ref].append([rec["turn"], c["k"]])
        return dict(out)

    def _first_violation(self, series: list[list[int]]) -> int | None:
        return next((t for t, k in series if 1 <= k < self.cfg.k_req), None)

    def _disclosures(self, arm: str) -> dict[str, list[dict[str, Any]]]:
        """사례별 공개 내역 (공개된 답의 줄 기준). 넓힘·비공개는 값 대신 표시만."""
        out: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
        for rec in self._records(arm):
            for ln in diff_answer(rec["raw_response_text"], rec["response_text"]):
                if "case" not in ln:
                    continue
                out[ln["case"]].append(dict(turn=rec["turn"], field=ln["field"], attribute=ATTR_KO.get(ln["attribute"], ln["attribute"]),
                                            value=ln["value"], change=ln["change"]))
        return dict(out)

    def _case_titles(self, arm: str) -> dict[str, str]:
        rec0 = self._records(arm)[0]
        titles: dict[str, list[str]] = collections.defaultdict(list)
        for ln in parse_answer(rec0["response_text"]):
            if "case" in ln and ln["value"] != SUPPRESSED:
                titles[ln["case"]].append(ln["value"])
        return {k: " · ".join(v[:2]) for k, v in titles.items()}

    def _turn_view(self, rec: dict[str, Any], arm: str, full: bool) -> dict[str, Any]:
        lines = diff_answer(rec["raw_response_text"], rec["response_text"])
        cand = rec.get("cases_candidate_k") or {}
        changed: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        for ln in lines:
            if ln.get("change"):
                changed[ln["case"]][(ATTR_KO.get(ln["attribute"], ln["attribute"]), ln["change"])] += 1
        notes = [dict(case=ref, changes=[dict(attribute=a, change=c) for (a, c) in cnt], k_if_raw=cand.get(ref),
                      k_now=(rec.get("cases") or {}).get(ref, {}).get("k")) for ref, cnt in changed.items()]
        v = dict(turn=rec["turn"], question=rec["query_text"], mode=rec["release_mode"],
                 refused=rec["release_mode"].startswith("REFUSAL"),
                 lines=[{k: x[k] for k in ("case", "field", "attribute", "value", "change", "text") if k in x} for x in lines],
                 change_notes=notes, target_qi=rec.get("target_qi"), picked_by=rec.get("picked_by") or ("retrieval" if rec["turn"] == 0 else None))
        if full:
            v.update(raw=rec["raw_response_text"], released=rec["response_text"], seed_id=rec.get("seed_id"),
                     variant=rec.get("variant"), scope=rec.get("scope"), objective=rec.get("objective"), relation=rec.get("relation"),
                     operator=rec.get("operator"), utility=rec.get("turn_utility"),
                     raw_lines=[{k: x[k] for k in ("case", "field", "attribute", "value", "text") if k in x} for x in parse_answer(rec["raw_response_text"])],
                     cases={ref: dict(k=c.get("k"), k_if_raw=cand.get(ref)) for ref, c in (rec.get("cases") or {}).items() if "k" in c},
                     decisions=[dict(case=p["ref"], k_before=p["k_before"], k_projected=p["k_projected"], risky=p["risky"], k_final=p["k_final"],
                                     items=[dict(attribute=ATTR_KO.get(d["attribute"], d["attribute"]), raw_value=d["raw_value"], action=d["action"],
                                                 to_label=self.ctx.data.label(d["to_node"]) if d.get("to_node") and d["action"] == "generalize" else None,
                                                 k_raw=d["k_raw"], steps=d["steps"], utility=d["utility"]) for d in p["decisions"]])
                                for p in (rec.get("release_plans") or [])])
        return v

    def _summary(self) -> dict[str, Any]:
        return dict(id=self.id, trial_id=self.trial_id, patient=self.patient_id[:8], qtype=self.qtype, qtype_label=QTYPE_KO[self.qtype],
                    profile=self.profile, profile_label=PROFILE_KO[self.profile], fuzzer=self.fuzzer, fuzzer_label=FUZZER_KO[self.fuzzer],
                    turn=self.turn, budget=self.cfg.budget_B, k_req=self.cfg.k_req, p_ref=self.ctx.p_ref,
                    panel=[dict(label=lab, value=self.prefix.binding["panel"][k]) for k, lab in PANEL_LABEL])

    def clinician_view(self, arm: str = "C1") -> dict[str, Any]:
        """의료진 화면: 공개된 답만. 원 응답·원래 값·정답 환자는 넣지 않는다."""
        if arm not in ARMS:
            raise DemoError(arm)
        ks = self._k_series(arm)
        titles = self._case_titles(arm)
        disc = self._disclosures(arm)
        cases = [dict(ref=ref, title=titles.get(ref, ""), rank=i + 1, score=round(self.prefix.retrieval[i][1], 3),
                      k=ks.get(ref, [[0, self.ctx.p_ref]])[-1][1], n_disclosed=sum(1 for d in disc.get(ref, []) if d["change"] != "suppress"),
                      disclosures=disc.get(ref, []))
                 for i, ref in enumerate(f"사례{n}" for n in range(1, len(self.prefix.docs) + 1))]
        return dict(self._summary(), arm=arm, arm_label=ARM_KO[arm],
                    turns=[self._turn_view(r, arm, False) for r in self._records(arm)], cases=cases,
                    skipped=[dict(turn=s["turn"], note=s["arms"][arm].get("note")) for s in self.steps if s["arms"][arm]["status"] != "ANSWERED"])

    def security_view(self) -> dict[str, Any]:
        """보안 담당자 화면: 세 조건의 원 응답·판정·k, 정답 환자 대조(Validated k)."""
        arms = {}
        for a in ARMS:
            r = self.runs[a]
            ks = self._k_series(a)
            A = self.case_a(a)
            val = {}
            for ref, c in r.cases.items():
                m = re.fullmatch(r"사례(\d+)", ref)
                if not m or not 1 <= int(m.group(1)) <= len(self.prefix.retrieval):
                    continue
                pid = self.prefix.retrieval[int(m.group(1)) - 1][0]
                v = validate_case(c.committed, pid, self.ctx.data, self.ctx.kc)
                val[ref] = dict(patient=pid[:8], k_val=v["k_val"], labels=dict(collections.Counter(v["labels"])),
                                target_in_candidates=v["target_in_candidates"], flag=v["flag"])
            decisions = collections.Counter()
            for rec in self._records(a):
                for p in rec.get("release_plans") or []:
                    for d in p["decisions"]:
                        decisions[d["action"]] += 1
            arms[a] = dict(label=ARM_KO[a], case_A=A, k_series=ks,
                           first_violation_A=self._first_violation(ks.get(A, [])) if A else None,
                           violated_cases=sorted(ref for ref, s in ks.items() if self._first_violation(s) is not None),
                           utility=round(sum(r.utilities) / len(r.utilities), 4) if r.utilities else None,
                           release_modes=dict(r.release_modes), decisions=dict(decisions), validation=val,
                           turns=[self._turn_view(rec, a, True) for rec in self._records(a)])
        return dict(self._summary(), arms=arms, steps=self.steps,
                    retrieval=[dict(ref=f"사례{i}", patient=p[:8], score=round(s, 4)) for i, (p, s) in enumerate(self.prefix.retrieval, 1)])


# ── 레드팀 배치 ─────────────────────────────────────────────

class RedTeamJob(threading.Thread):
    """medical.experiment.run_experiment를 그대로 돌리고 medical.poc_analysis.analyse로 집계한다."""

    def __init__(self, eng: Engine, jid: str, profile: str, fuzzer: str, per_type: int | None) -> None:
        super().__init__(daemon=True)
        self.eng, self.id, self.profile, self.fuzzer, self.per_type = eng, jid, profile, fuzzer, per_type
        self.cfg = MedicalConfig(fuzzer=fuzzer)                   # POC와 같은 설정 (efficiency, budget 10)
        self.out = eng.workdir / "redteam" / f"{jid}_{profile}_{fuzzer}_{per_type or 'all'}"
        self.planner = plan_all(per_type, self.cfg.seed)
        self.total = len(self.planner(eng.data, eng.split, self.cfg)) * len(self.cfg.arms)
        self.done, self.status, self.error, self.result = 0, "queued", None, None
        self.started = self.finished = None
        self.last_line = ""

    def _progress(self, line: str) -> None:
        self.done += 1
        self.last_line = line

    def run(self) -> None:
        from medical.poc_analysis import analyse
        self.status, self.started = "running", time.time()
        try:
            llm = OracleRoleLLM(data=self.eng.data, profile=self.profile)
            run_experiment(self.cfg, llm, self.out, data=self.eng.data, planner=self.planner, progress=self._progress)
            self.result = summarize(analyse(self.out), self.cfg.k_req)
            self.status = "done"
        except Exception as exc:          # 화면에 보여 주고 서버는 계속 돈다
            self.status, self.error = "error", f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}"
        self.finished = time.time()

    def as_dict(self) -> dict[str, Any]:
        return dict(id=self.id, profile=self.profile, profile_label=PROFILE_KO[self.profile], fuzzer=self.fuzzer,
                    fuzzer_label=FUZZER_KO[self.fuzzer], per_type=self.per_type, total=self.total, done=self.done, status=self.status,
                    error=self.error, elapsed=round((self.finished or time.time()) - self.started, 1) if self.started else None,
                    out=str(self.out.relative_to(ROOT)) if self.out.is_relative_to(ROOT) else str(self.out),
                    last=self.last_line, result=self.result)


def _cue(k: str) -> str:
    if k.startswith("턴0"):
        return "사례 검색 답 (턴 0)"
    return "+".join(ATTR_KO.get(x, x) for x in k.split("+"))


def summarize(res: dict[str, Any], k_req: int = 5) -> dict[str, Any]:
    """poc_analysis 결과 중 화면에 쓰는 것만 + exact McNemar (평가 v7.2 함수, 10턴 예산 기준 짝)."""
    from evaluation.eval_baseline import exact_mcnemar
    arms = {}
    for a, v in res["arms"].items():
        arms[a] = dict(label=ARM_KO.get(a, a), n=v["n"], viol8=v["violation_A_by_turn7"], viol10=v["violation_A_val"],
                       viol_any=v["violation_any_case_val"], turn0=v["risk_at_turn0"], first_median=v["first_violation_turn_median"],
                       cumulative=v["cumulative_violation_by_turn"], kA_median=v["kA_median_by_turn"], kA_q1=v["kA_q1_by_turn"],
                       kA_q3=v["kA_q3_by_turn"], utility=v["mean_utility"], decisive={_cue(k): n for k, n in v["decisive_qi"].items()},
                       defender={ATTR_KO.get(k, k): c for k, c in v["defender_actions"].items()},
                       overblock=v["case_level_overblock"], release_modes=v["release_modes"])
    paired = {}
    for name, p in res.get("paired_first_violation", {}).items():
        b, c = p["only_first"], p["only_second"]
        paired[name] = dict(p, p_value=exact_mcnemar(b, c) if b + c else None)
    return dict(arms=arms, paired=paired, config=res["config"])
