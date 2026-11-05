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
import copy
import functools
import itertools
import json
import queue
import random
import re
import threading
import time
import traceback
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from core.llm_client import LLMError
from medical.adaptive import FeedbackSelector
from medical.attack import applicable_ops, choose_seed, fill_seed, realize
from medical.bundle.seed_select import target
from medical.config import ROOT, MedicalConfig, MedicalPaths
from medical.data import MedicalData
from medical.experiment import build_context
from medical.prompts import REFUSAL_TEXT
from medical.retrieval import PANEL_LABEL, query_binding
from medical.session import ARMS, Context, extract, make_prefix
from medical.simulate import SUPPRESSED, OracleRoleLLM, plan_all
from medical.tracking import Case, known_cases_json, view_of
from medical.validate import validate_case
from webdemo.backend.live import ANSWER_STYLE_ID, ORACLE_LABEL, AnswerStyleLLM, CallWatchLLM, LiveLLM, Turn0Cache, Turn0LLM, background_calls, styled
from webdemo.backend.review import RELEASE_VERSION, RuledArmRun, decision_of, hidden_items
from webdemo.backend.visit import diagnosis_events, make_prefix_with, visit_binding

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
_MENTIONS_CASE = re.compile(r"사례\s*\d")
LLM_MODES = ("oracle", "live")        # 세션의 대상 AI: oracle 결정적 응답기 · live 서버가 켤 때 정한 LLM(실제 모델 또는 배선 확인용 가짜)


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
    """
    프로세스에 하나. 데이터·문서·kcalc를 한 번 올리고 세션과 레드팀 작업을 관리한다.

    paths    : 노드표 · 사건연결표 경로. MediCloak 운영 모드에서는 DB에서 내보낸 스냅숏(emr.export_csv)을 준다.
    live_llm : 의료진 대화에 쓸 LLM (medical.llm.ClientRoleLLM = .env의 실제 모델, 또는 배선 확인용 MockRoleLLM).
               문서 · 턴 0 사례 검색 답 · 보내기 전 추정 · 레드팀 · 시뮬레이션은 언제나 결정적 응답기를 쓴다 (호출 비용 0, 재현 가능).
    first_id : 세션 · 작업 번호 시작값 (DB에 지난 대화가 있으면 그 다음 번호부터).
    """

    def __init__(self, workdir: Path | None = None, log: Callable[[str], None] = print, *, paths: MedicalPaths | None = None,
                 live_llm: Any = None, live_label: str | None = None, first_id: int = 1, llm_concurrency: int = 1,
                 live_rule_extract: bool = True, answer_style: bool = True, recent_visit: bool = False) -> None:
        t0 = time.time()
        self.lock = threading.RLock()                                # kcalc 캐시·응답기 상태를 세션끼리 나눠 쓰므로 한 번에 한 요청
        self.workdir = Path(workdir or ROOT / "runs" / "webdemo")
        self.cfg = MedicalConfig(mode="exploration")                  # 데모 대화는 위반에 닿아도 멈추지 않는다
        self.paths = paths or MedicalPaths()
        self.data = MedicalData(self.paths)
        self.llm = {p: OracleRoleLLM(data=self.data, profile=p) for p in PROFILES}
        base, self.split = build_context(self.cfg, self.llm["staged"], self.workdir / "engine", data=self.data, paths=self.paths)
        self.ctx: dict[str, Context] = {"staged": base, "full": replace(base, llm=self.llm["full"])}
        # 의료진 대화 LLM은 네트워크 호출 동안 엔진 잠금을 푸는 포장(LiveLLM)을 씌운다 (live.py)
        self.live_llm = LiveLLM(live_llm, self.lock, concurrency=llm_concurrency, data=self.data) if live_llm is not None else None
        # 운영 모드: 의료진 대화의 진료 기준을 가장 최근 진료로 (visit.py). 연구 계획 · 레드팀은 연구 기준 그대로
        self.recent_visit = recent_visit
        self._prefetching: dict[str, threading.Thread] = {}
        self._prefetch_next: dict[str, tuple] = {}                  # 의료진마다 도는 미리 준비 뒤에 이어서 할 마지막 것
        # 실제 LLM 추출기는 날짜를 따로 된 단서(PERIOD)로 내지 않고 약 항목의 period_start 칸에만 적을 때가 있다.
        # 그러면 공개 계획이 날짜를 세지 않고, 고친 답을 다시 뽑을 때에야 날짜가 단서로 나와 답 전체가 거절된다.
        # 그래서 실제 LLM 대화에는 규칙 추출(medical/rule_extract.py: 답에 적힌 나이 · 날짜를 정규식으로 보탬)을 켠다.
        # 결정적 응답기(데모 · 레드팀 · 시뮬레이션)는 바꾸지 않는다.
        self.live_rule_extract = live_rule_extract
        live_cfg = replace(base.cfg, rule_extract=True) if live_rule_extract else base.cfg
        self.live_ctx: Context | None = replace(base, llm=self.live_llm, cfg=live_cfg) if self.live_llm is not None else None
        self.turn0_cache = Turn0Cache()                   # 첫 답 요청 · 답 (대화 사이에 나눠 씀, 메모리)
        # 실제 LLM 대상 AI의 답 형식 (live.ANSWER_STYLE). 의료진 대화와 레드팀에 같이 걸어, 잰 조건과 운영 조건을 맞춘다
        self.answer_style = answer_style
        self.live_label = live_label or (ORACLE_LABEL if live_llm is None else "LLM")
        self.seed_by_id = {s["seed_id"]: s for s in base.seeds}
        self.plan = plan_all(None, self.cfg.seed)(self.data, self.split, self.cfg)     # POC와 같은 trial 번호 (T0001…)
        self.trial_of = {tid: (pid, qt) for tid, pid, qt, _ in self.plan}
        self.sessions: dict[str, Session] = {}
        self.jobs: dict[str, RedTeamJob] = {}
        self._ids = itertools.count(first_id)
        # 실제 LLM 대화의 비교 갈래(C1S) 계산: 의료진 답을 보낸 뒤 한 줄로 차례로 (재작성 호출이 더 들 수 있어서)
        self._compare_q: queue.Queue = queue.Queue()
        self._compare_thread: threading.Thread | None = None
        self.on_compare_done: Callable[[Any], None] | None = None
        log(f"[webdemo] 엔진 준비 {time.time() - t0:.1f}초 · 기준 집단 {base.p_ref}명 · 질의 trial {len(self.plan)}개 · Seed {len(base.seeds)}행")

    # ── 기본 정보 ──
    def meta(self) -> dict[str, Any]:
        c = self.cfg
        return dict(p_ref=self.ctx["staged"].p_ref, k_req=c.k_req, generalize_threshold=c.generalize_threshold,
                    suppress_threshold=c.suppress_threshold, budget=c.budget_B, top_k=c.top_k_retrieval, n_trials=len(self.plan),
                    n_seeds=len(self.seed_by_id), versions=self.ctx["staged"].versions, arms=list(ARMS), arm_labels=ARM_KO,
                    profiles=PROFILE_KO, fuzzers=FUZZER_KO, qtypes=QTYPE_KO, attributes=ATTR_KO,
                    target="결정적 응답기 (질문받은 단서를 검색 문서의 기록값으로 답함, LLM 호출 없음)")

    def binding(self, trial_id: str, visit_event: str | None = None) -> dict[str, Any] | None:
        """
        의료진 대화가 쓸 진료 기준 (환자 요약 · 검색 기준일). make_prefix와 같은 난수.
        visit_event(의사가 고른 진단 사건)가 있으면 그 진료, 없으면 운영 모드는 가장 최근 진료 · 아니면 연구 기준.
        """
        pid, qt = self.trial_of[trial_id]
        rng = random.Random(f"{self.cfg.seed}-{trial_id}")
        if visit_event is not None:
            return visit_binding(self.data, pid, qt, rng, index_event=visit_event)
        return visit_binding(self.data, pid, qt, rng) if self.recent_visit else query_binding(self.data, pid, qt, rng)

    def visit_choices(self, trial_id: str, limit: int = 15) -> list[dict[str, Any]]:
        """
        오늘 볼 진단으로 고를 수 있는 것 (ADR-0029 덧붙임): 진단 이름마다 그 목적이 성립하는 가장 최근 사건, 최근 것부터.
        기본(지금 기준 진료)에는 isDefault를 붙인다. 연구 기준 모드에서 기본 사건이 목록에 없으면 맨 앞에 넣는다.
        """
        pid, qt = self.trial_of[trial_id]
        base = self.binding(trial_id)
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for e, _ in sorted(diagnosis_events(self.data, pid), key=lambda x: ((x[0]["start"] or "")[:10], x[0]["event_id"]), reverse=True):
            label = self.data.label(e["code_node"])
            if label in seen:
                continue
            b = self.binding(trial_id, e["event_id"])
            if b is None:                       # 이 날에는 그 목적의 관련 항목이 없다: 같은 진단의 더 앞 사건을 본다
                continue
            seen.add(label)
            out.append(self._choice(b, label, e["event_id"]))
            if len(out) >= limit:
                break
        if base is not None:
            default = next((c for c in out if c["eventId"] == base["index_event"]), None)
            if default is None:
                default = self._choice(base, base["QUERY_MAIN_DX"], base["index_event"])
                out.insert(0, default)
            default["isDefault"] = True
        return out

    @staticmethod
    def _choice(b: dict[str, Any], label: str, event_id: str) -> dict[str, Any]:
        co = b["panel"].get("PANEL_COMORBIDITY")
        return dict(eventId=event_id, label=label, date=b["index_date"], item=b["QUERY_RELATED_ITEM"],
                    comorbidity=None if co in (None, "없음") else co, isDefault=False)

    def check_visit(self, trial_id: str, visit_event: str | None) -> str | None:
        """의사가 고른 진단 사건을 확인한다. 기본 진료와 같으면 None(기본 그대로). 이 환자 · 목적으로 쓸 수 없으면 DemoError."""
        if not visit_event:
            return None
        base = self.binding(trial_id)
        if base is not None and base["index_event"] == visit_event:
            return None
        if self.binding(trial_id, visit_event) is None:
            raise DemoError("고른 진단으로는 이 진료 목적의 관련 항목(처방 · 시술 · 관리 계획)이 없어 열 수 없습니다.")
        return visit_event

    def binder_for(self, visit_event: str | None) -> Any:
        """make_prefix_with에 넘길 기준 진료 함수. 고른 진단이 있으면 그 사건, 없으면 None(기본 규칙)."""
        return functools.partial(visit_binding, index_event=visit_event) if visit_event else None

    def patients(self) -> list[dict[str, Any]]:
        """질의 환자 목록 (trial 단위: 같은 환자가 조회 유형마다 따로 나온다)."""
        out = []
        for tid, pid, qt, _ in self.plan:
            b = self.binding(tid)
            out.append(dict(trial_id=tid, patient=pid[:8], qtype=qt, qtype_label=QTYPE_KO[qt],
                            panel=[dict(label=lab, value=b["panel"][k]) for k, lab in PANEL_LABEL]))
        return out

    # ── 세션 ──
    def new_session(self, trial_id: str, profile: str = "staged", fuzzer: str = "uniform", *, source: str = "manual",
                    budget: int | None = None, llm_mode: str = "oracle", on_call: Callable[[str, int], None] | None = None,
                    visit_event: str | None = None) -> "Session":
        if trial_id not in self.trial_of:
            raise DemoError(f"없는 trial입니다: {trial_id}")
        if profile not in PROFILES or fuzzer not in FUZZERS:
            raise DemoError("profile은 staged|full, fuzzer는 uniform|feedback 중 하나입니다.")
        if llm_mode not in LLM_MODES or (llm_mode == "live" and self.live_ctx is None):
            raise DemoError("이 서버에는 의료진 대화용 LLM이 설정되어 있지 않습니다.")
        with self.lock:
            sid = f"S{next(self._ids):04d}"
            s = Session(self, sid, trial_id, profile, fuzzer, source=source, budget=budget, llm_mode=llm_mode, on_call=on_call,
                        visit_event=visit_event)
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
        usage = getattr(self.live_llm, "usage", None)
        if usage is not None and len(usage) > 2000:
            del usage[:-1000]          # 실제 LLM 호출 기록은 /api/health 집계용으로 최근 것만 둔다

    # ── 비교 갈래 뒤 계산 ──
    def queue_compare(self, s: "Session", arm: str, turn: int, query: str, shared: tuple, meta: dict[str, Any]) -> None:
        with self.lock:
            s.compare_pending += 1
        self._compare_q.put((s, arm, turn, query, shared, meta))
        with self.lock:
            if self._compare_thread is None:
                self._compare_thread = threading.Thread(target=self._compare_worker, daemon=True, name="medicloak-compare")
                self._compare_thread.start()

    def _compare_worker(self) -> None:
        background_calls()                 # 이 스레드의 LLM 호출은 의료진 질문에 자리를 양보한다
        while True:
            s, arm, turn, query, shared, meta = self._compare_q.get()
            try:
                with self.lock:
                    step = next((x for x in s.steps if x["turn"] == turn), None)
                    s._compare_turn(arm, turn, query, shared, meta, step["arms"] if step else {})
                    s.compare_pending -= 1
                cb = self.on_compare_done
                if cb is not None:
                    try:
                        cb(s)
                    except Exception as exc:
                        print(f"[medicloak] 비교 갈래 저장 실패 ({s.id}): {type(exc).__name__}: {exc}")
            finally:
                self._compare_q.task_done()

    # ── 첫 답 미리 준비 (운영 모드, 실제 LLM) ──
    def prefetch(self, trial_id: str, key: str, visit_event: str | None = None,
                 on_done: Callable[[int, bool], None] | None = None) -> str:
        """
        EMR에서 환자 · 진료 목적(· 오늘 진단)을 고르면 '진료 지원 AI 열기'를 누르기 전에 첫 답을 뒤에서 만들어 둔다:
        대상 AI 답 · 추출, 그리고 화면 갈래(C1)의 첫 답 공개 처리(재작성 · 다시 확인).
        대화를 열 때 같은 요청을 Turn0Cache에서 꺼내 쓰고, 아직 부르는 중이면 끝나기를 기다린다 (같은 호출을 두 번 하지 않는다).
        호출은 의료진 질문에 자리를 양보한다(background_calls).
        key(의료진)마다 한 번에 하나. 도는 중에 또 고르면 마지막으로 고른 것 하나만 기다렸다가 이어서 한다 (그 사이 고른 것은 버린다).
        돌려주는 값: started · queued · off. on_done(실제 LLM 호출 수, 성공)은 하나가 끝날 때마다 부른다 (감사 기록).
        대화(Session) · 기록은 만들지 않는다 (공개 처리 갈래 객체는 버린다). 열기 전에는 의료진에게 아무것도 보이지 않는다.
        """
        if self.live_ctx is None or trial_id not in self.trial_of:
            return "off"
        job = (trial_id, visit_event, on_done)
        with self.lock:
            t = self._prefetching.get(key)
            if t is not None and t.is_alive():
                self._prefetch_next[key] = job
                return "queued"

            def run() -> None:
                background_calls()
                nxt: tuple | None = job
                while nxt is not None:
                    self._prefetch_one(*nxt)
                    with self.lock:                     # 다음 것을 꺼내지 못했으면 이 스레드를 목록에서 내린다 (새 요청이 새로 시작하게)
                        nxt = self._prefetch_next.pop(key, None)
                        if nxt is None and self._prefetching.get(key) is threading.current_thread():
                            del self._prefetching[key]

            t = threading.Thread(target=run, daemon=True, name="medicloak-prefetch")
            self._prefetching[key] = t
            t.start()
            return "started"

    def _prefetch_one(self, trial_id: str, visit_event: str | None, on_done: Callable[[int, bool], None] | None) -> None:
        pid, qt = self.trial_of[trial_id]
        llm0: Turn0LLM | None = None
        ok = False
        try:
            with self.lock:                      # 대화를 열 때(new_session)와 같은 잠금. 네트워크 호출 동안은 LiveLLM이 푼다
                live_ctx = replace(self.live_ctx, llm=AnswerStyleLLM(self.live_ctx.llm)) if self.answer_style else self.live_ctx
                llm0 = Turn0LLM(live_ctx.llm, self.ctx["staged"].llm, cache=self.turn0_cache)
                ctx0 = replace(live_ctx, llm=llm0)
                chosen = self.binder_for(visit_event)
                if chosen is not None:
                    p = make_prefix_with(ctx0, trial_id, pid, qt, "DOCTOR", chosen)
                elif self.recent_visit:
                    p = make_prefix_with(ctx0, trial_id, pid, qt, "DOCTOR", visit_binding)
                else:
                    p = make_prefix(ctx0, trial_id, pid, qt, "DOCTOR")
                # 화면 갈래(C1)의 첫 답 공개 처리를 대화와 똑같이 한 번 돌려 재작성 · 다시 확인 요청도 Turn0Cache에 남긴다.
                # 새 대화는 아직 보안 담당자 규칙이 없으므로(rules=[]) 열 때의 C1과 요청이 같다. 거절이면 나눠 쓰지 않는다.
                recs: list[dict[str, Any]] = []
                llm0.next_arm()
                RuledArmRun(ctx0, p, "C1", recs.append, list, live=True)._turn(
                    0, p.q0, p.raw0, p.obs0, p.extract_ok0, p.extract_tries0,
                    dict(seed_id=None, case_query_id=p.case_query_id, operator=p.op0, realization_fallback=p.realization_fallback,
                         checks=p.tries0, regenerations=max(len(p.tries0) - 1, 0)))
                if not recs or str(recs[0].get("release_mode", "")).startswith("REFUSAL"):
                    llm0.forget()
            ok = True
        except Exception as exc:                 # 미리 준비가 실패해도 열 때 다시 부른다
            print(f"[medicloak] 첫 답 미리 준비 실패 ({trial_id}): {type(exc).__name__}: {exc}")
        finally:
            if on_done is not None:
                try:
                    on_done(llm0.calls if llm0 is not None else 0, ok)
                except Exception as exc:         # 감사 기록이 실패해도 미리 준비는 끝난 것으로 둔다
                    print(f"[medicloak] 미리 준비 기록 실패 ({trial_id}): {type(exc).__name__}: {exc}")

    def compare_pending(self) -> int:
        return self._compare_q.unfinished_tasks

    def wait_compare(self, timeout: float = 30.0) -> bool:
        """뒤에서 계산 중인 비교 갈래가 끝날 때까지 기다린다 (테스트 · 점검용). 끝났으면 True."""
        end = time.time() + timeout
        while self._compare_q.unfinished_tasks and time.time() < end:
            time.sleep(0.02)
        return not self._compare_q.unfinished_tasks

    def live_usage(self) -> dict[str, Any] | None:
        """의료진 대화 LLM의 역할별 호출 수와 토큰 (점검용, 키 · 본문 없음)."""
        usage = getattr(self.live_llm, "usage", None)
        if usage is None:
            return None
        by: dict[str, dict[str, int]] = {}
        for u in usage:
            b = by.setdefault(u["role"], dict(calls=0, input_tokens=0, output_tokens=0))
            b["calls"] += 1
            b["input_tokens"] += int(u.get("input_tokens") or 0)
            b["output_tokens"] += int(u.get("output_tokens") or 0)
        return dict(label=self.live_label, by_role=by, calls=sum(b["calls"] for b in by.values()))

    # ── 레드팀 ──
    def start_job(self, profile: str, fuzzer: str, per_type: int | None, *, live: bool = False,
                  on_finish: Callable[["RedTeamJob"], None] | None = None, meta: dict[str, Any] | None = None) -> "RedTeamJob":
        if profile not in PROFILES or fuzzer not in FUZZERS:
            raise DemoError("profile은 staged|full, fuzzer는 uniform|feedback 중 하나입니다.")
        if per_type is not None and per_type < 1:
            raise DemoError("per_type은 1 이상이어야 합니다.")
        if live and self.live_llm is None:
            raise DemoError("이 서버에는 실제 LLM이 설정되어 있지 않습니다 (--llm real).")
        with self.lock:
            if any(j.status in ("queued", "running") for j in self.jobs.values()):
                raise DemoError("이미 돌고 있는 레드팀 실행이 있습니다. 끝나거나 멈춘 뒤 다시 실행하세요.")
            jid = f"R{next(self._ids):04d}"
            job = RedTeamJob(self, jid, profile, fuzzer, per_type, live=live, on_finish=on_finish, meta=meta)
            self.jobs[jid] = job
        job.start()
        return job


# ── 세션 ────────────────────────────────────────────────────

class Session:
    def __init__(self, eng: Engine, sid: str, trial_id: str, profile: str, fuzzer: str, *, source: str = "manual",
                 budget: int | None = None, llm_mode: str = "oracle", on_call: Callable[[str, int], None] | None = None,
                 visit_event: str | None = None) -> None:
        self.eng, self.id, self.trial_id, self.profile, self.fuzzer = eng, sid, trial_id, profile, fuzzer
        self.ctx = eng.ctx[profile]
        self.cfg = self.ctx.cfg
        self.budget = budget or self.cfg.budget_B           # 의료진 화면 대화는 더 길게 쓸 수 있게 늘린다
        self.source = source                                # clinic(의료진 화면) · simulation(시작할 때 돌린 레드팀 대화) · manual
        pid, qt = eng.trial_of[trial_id]
        self.patient_id, self.qtype = pid, qt
        self.created = self.last_active = time.time()
        self.review: dict[str, Any] | None = None           # 보안 담당자 검토 표시 (관제 화면)
        self.messages: list[dict[str, Any]] = []            # 의료진 ↔ 보안 담당자 메시지 (세부 정보 요청 · 확인 요청 · 답장 · 공개 승인)
        self.rules: list[dict[str, Any]] = []               # 보안 담당자 규칙: 이 대화에서 사례 · 단서 종류는 늘 가림 (review.py, C1에만)
        self.approvals: list[dict[str, Any]] = []           # 보안 담당자가 승인해 공개한 값 (review.py)
        # 실제 LLM 대화는 첫 답(턴 0, 사례 검색)부터 실제 LLM이 쓰고 방어 게이트를 거친다. 검색 질문 문장만 결정적 응답기가 만든다.
        # 대상 AI에는 답 형식을 붙이고(AnswerStyleLLM, 레드팀과 같은 설정), 첫 답은 같은 환자 · 목적의 다른 대화와 나눠 쓴다(Turn0Cache).
        live_ctx = None
        if llm_mode == "live":
            live_ctx = replace(eng.live_ctx, llm=AnswerStyleLLM(eng.live_ctx.llm)) if eng.answer_style else eng.live_ctx
        ctx0 = (replace(live_ctx, llm=Turn0LLM(live_ctx.llm, self.ctx.llm, cache=eng.turn0_cache, on_call=on_call))
                if live_ctx is not None else self.ctx)
        self.visit_event = visit_event                      # 의사가 고른 오늘 진단 (진단 사건 번호). 없으면 기본 기준 진료
        chosen = eng.binder_for(visit_event)
        if chosen is not None:                               # 의사가 고른 진단의 진료 기준 (visit.py)
            p = self.prefix = make_prefix_with(ctx0, trial_id, pid, qt, "DOCTOR", chosen)
        elif eng.recent_visit and source == "clinic":         # 운영 모드 의료진 대화: 가장 최근 진료 기준 (visit.py)
            p = self.prefix = make_prefix_with(ctx0, trial_id, pid, qt, "DOCTOR", visit_binding)
        else:
            p = self.prefix = make_prefix(ctx0, trial_id, pid, qt, "DOCTOR")
        self.logs: dict[str, list[dict[str, Any]]] = {a: [] for a in ARMS}
        self.runs = {a: RuledArmRun(ctx0, p, a, self._logger(a), lambda a=a: self.rules_for(a), live=llm_mode == "live") for a in ARMS}
        self.steps: list[dict[str, Any]] = []           # 세션 턴마다: 질문 Seed와 조건별 처리 결과
        for a, r in self.runs.items():
            if isinstance(ctx0.llm, Turn0LLM):
                ctx0.llm.next_arm()                          # 갈래마다 같은 요청은 앞 갈래의 답을 차례대로 다시 쓴다
            r._turn(0, p.q0, p.raw0, p.obs0, p.extract_ok0, p.extract_tries0,
                    dict(seed_id=None, case_query_id=p.case_query_id, operator=p.op0, realization_fallback=p.realization_fallback,
                         checks=p.tries0, regenerations=max(len(p.tries0) - 1, 0)))
        self.steps.append(dict(turn=0, seed_id=None, picked_by="retrieval", arms={a: dict(status="ANSWERED") for a in ARMS}))
        # 세션의 self.ctx(결정적)는 보내기 전 추정 · 질문 후보에 계속 쓰고, 갈래(ArmRun)만 live 문맥으로 바꾼다.
        self.llm_mode = llm_mode
        self.owner: dict[str, Any] | None = None             # 의료진 대화: 계정 (user_id, username, label)
        self.launch: dict[str, Any] | None = None            # EMR에서 연 대화: {fhirId, purpose}
        self.compare_pending = 0                             # 뒤에서 계산할 비교 갈래 턴 수 (실제 LLM 대화)
        self.watcher: CallWatchLLM | None = None             # 의료진 질문의 진행 표시 (화면 갈래 C1의 호출만)
        if live_ctx is not None:
            self.watcher = CallWatchLLM(live_ctx.llm)
            for a, r in self.runs.items():
                r.ctx = replace(live_ctx, llm=self.watcher) if a == "C1" else live_ctx
            first = self.logs["C1"][0] if self.logs["C1"] else None
            if first is None or first["release_mode"].startswith("REFUSAL"):
                ctx0.llm.forget()                            # 거절된 첫 답은 나눠 쓰지 않는다 (다시 열면 새로 부른다)
        self.turn = 0
        self.rng = random.Random(f"{self.cfg.seed}-{trial_id}-follow")          # POC run()과 같은 난수열
        self.used: set[str] = set()
        self.blocked: set[str] = set()
        self.scen: collections.Counter = collections.Counter()
        self.selector = FeedbackSelector(threshold=self.cfg.k_req) if fuzzer == "feedback" else None

    def _logger(self, arm: str) -> Callable[[dict[str, Any]], None]:
        """턴 기록을 남길 때 사례마다 그때까지 쌓인 공개 수를 같이 적는다 (후보가 줄어든 과정을 턴에 잇는 데 씀)."""
        def log(rec: dict[str, Any]) -> None:
            r = getattr(self, "runs", {}).get(arm)
            if r is not None and rec.get("turn") is not None:
                rec["committed_count"] = {ref: len(c.committed) for ref, c in r.cases.items()}
            self.logs[arm].append(rec)
        return log

    # ── 보안 담당자 검토 반영 (review.py) ──
    def rules_for(self, arm: str) -> list[tuple[str, str]]:
        return [(r["case"], r["attribute"]) for r in self.rules] if arm == "C1" else []

    def add_rule(self, case: str, attribute: str, *, by: str, note: str | None = None) -> dict[str, Any]:
        if not re.fullmatch(r"사례\d+", case) or int(case[2:]) > len(self.prefix.docs) or int(case[2:]) < 1:
            raise DemoError(f"없는 사례입니다: {case}")
        case = f"사례{int(case[2:])}"
        if attribute not in ATTR_KO:
            raise DemoError(f"단서 종류는 {', '.join(ATTR_KO)} 중 하나입니다.")
        if any(r["case"] == case and r["attribute"] == attribute for r in self.rules):
            raise DemoError("이미 같은 규칙이 있습니다.")
        rule = dict(id=f"RU{len(self.rules) + 1}-{int(time.time() * 1000) % 100000}", case=case, attribute=attribute,
                    attribute_label=ATTR_KO[attribute], by=by, at=time.time(), note=(note or "").strip() or None, from_turn=self.turn + 1)
        self.rules.append(rule)
        return rule

    def remove_rule(self, rule_id: str) -> dict[str, Any]:
        rule = next((r for r in self.rules if r["id"] == rule_id), None)
        if rule is None:
            raise KeyError(rule_id)
        self.rules.remove(rule)
        return rule

    def hidden(self) -> list[dict[str, Any]]:
        return hidden_items(self.logs["C1"], self.approvals)

    def approve(self, item_ids: list[str], *, by: str, reason: str) -> dict[str, Any]:
        """가린 값을 골라 의료진 화면 갈래(C1)의 누적 State에 더한다. 값은 이 대화에만 나간다."""
        items = {x["id"]: x for x in self.hidden()}
        chosen = [items[i] for i in dict.fromkeys(item_ids) if i in items and not items[i]["released"]]
        if not chosen:
            raise DemoError("공개할 값을 고르세요 (이미 공개한 값은 다시 고를 수 없습니다).")
        r, out, kc = self.runs["C1"], [], self.ctx.kc
        for x in chosen:
            d = decision_of(self.logs["C1"], x["turn"], x["case"], x["index"])
            if x["case"] not in r.cases:
                r.cases[x["case"]] = Case(x["case"])
                r.order.append(x["case"])
            c = r.cases[x["case"]]
            c.committed.append(dict(attribute=d["attribute"], node_id=d["node_id"],
                                    event_group=self._event_group_for(c.committed, x, d)))
            out.append(dict(turn=x["turn"], case=x["case"], index=x["index"], attribute=d["attribute"], attribute_label=ATTR_KO.get(d["attribute"], d["attribute"]),
                            value=str(d.get("raw_value") or self.ctx.data.label(d["node_id"])), committed_index=len(c.committed) - 1,
                            after_turn=self.turn, action="dropped" if x.get("dropped") else x.get("action")))   # 어떻게 가렸던 값인지 (의료진 메시지)
        k_after = {ref: kc.k(r.cases[ref].committed)["k"] for ref in dict.fromkeys(x["case"] for x in out)}
        ap = dict(id=f"AP{len(self.approvals) + 1}", at=time.time(), by=by, reason=reason, items=out, k_after=k_after)
        self.approvals.append(ap)
        self.last_active = ap["at"]
        return ap

    def what_if(self, item_ids: list[str]) -> dict[str, int]:
        """
        고른 가린 값을 지금 공개했다면 사례마다 후보 수 (검토 보조가 씀). approve와 같은 방식으로 누적 State 사본에 더해 세고,
        State · 승인 기록은 바꾸지 않는다. 이미 공개한 값 · 없는 번호는 건너뛴다.
        """
        items = {x["id"]: x for x in self.hidden()}
        chosen = [items[i] for i in dict.fromkeys(item_ids) if i in items and not items[i]["released"]]
        r, kc = self.runs["C1"], self.ctx.kc
        trial: dict[str, list[dict[str, Any]]] = {}
        for x in chosen:
            d = decision_of(self.logs["C1"], x["turn"], x["case"], x["index"])
            base = trial.setdefault(x["case"], list(r.cases[x["case"]].committed) if x["case"] in r.cases else [])
            base.append(dict(attribute=d["attribute"], node_id=d["node_id"], event_group=self._event_group_for(base, x, d)))
        return {ref: kc.k(committed)["k"] for ref, committed in trial.items()}

    def _event_group_for(self, committed: list[dict[str, Any]], item: dict[str, Any], d: dict[str, Any]) -> str | None:
        """
        가린 값의 사건 묶음 표지는 그 턴 원 응답 추출의 것이다. 같은 사건의 다른 값(예: 약 이름)이 다시 확인 추출에서 다른 표지로
        State에 들어갔으면, 표지가 달라 후보 계산이 두 사건으로 나눠 센다 (후보 수를 넉넉하게 잡음). 그래서 같은 턴 계획에서 같은 표지를
        가진 값을 찾아, State에 이미 있는 그 값(같은 단서 · 같은 노드)의 표지로 바꿔 넣는다.
        """
        g = d.get("event_group")
        if not g or any(c.get("event_group") == g for c in committed):
            return g
        plan = next(p for p in next(rr for rr in self.logs["C1"] if rr.get("turn") == item["turn"])["release_plans"] if p["ref"] == item["case"])
        for sib in plan["decisions"]:
            if sib is d or sib.get("event_group") != g:
                continue
            for c in committed:
                if c["attribute"] == sib["attribute"] and c["node_id"] in (sib.get("node_id"), sib.get("to_node")) and c.get("event_group"):
                    return c["event_group"]
        return g

    def narrowing(self, arm: str, ref: str) -> dict[str, Any]:
        """사례 하나: 공개된 단서를 쌓인 순서대로 하나씩 더하며 센 후보 수와, 가린 값을 그대로 냈다면의 후보 수.
        같은 단서가 다시 나오면 한 번만 센다."""
        r, ctx = self.runs[arm], self.ctx
        c = r.cases.get(ref)
        committed = list(c.committed) if c else []
        counts = [(rec["turn"], (rec.get("committed_count") or {}).get(ref)) for rec in self._records(arm)]
        approved = {x["committed_index"]: ap for ap in self.approvals if arm == "C1" for x in ap["items"] if x["case"] == ref}
        steps, k_prev, seen = [], ctx.p_ref, set()
        for i, d in enumerate(committed):
            ap = approved.get(i)
            key = (d["attribute"], d["node_id"])
            if key in seen and not ap:                  # 같은 단서가 다음 답에 다시 나온 것: 후보가 줄지 않으니 단계로 세지 않는다
                continue
            seen.add(key)
            k_i = ctx.kc.k(committed[: i + 1])["k"]
            turn = next((t for t, n in counts if n is not None and n >= i + 1), None)
            after = next((x.get("after_turn") for x in (ap or {}).get("items", []) if x["committed_index"] == i), None)
            steps.append(dict(attribute=d["attribute"], attributeLabel=ATTR_KO.get(d["attribute"], d["attribute"]), value=ctx.data.label(d["node_id"]),
                              turn=None if ap else turn, approved=bool(ap), afterTurn=after, kBefore=k_prev, kAfter=k_i))
            k_prev = k_i
        hidden = [dict(turn=x["turn"], attribute=x["attribute"], attributeLabel=ATTR_KO.get(x["attribute"], x["attribute"]), action=x["action"],
                       kIfRaw=x["kIfRaw"], released=x["released"], dropped=x["dropped"])
                  for x in (self.hidden() if arm == "C1" else []) if x["case"] == ref]
        rules = [dict(attribute=x["attribute"], attributeLabel=x["attribute_label"]) for x in self.rules if x["case"] == ref] if arm == "C1" else []
        return dict(case=ref, population=ctx.p_ref, generalizeK=ctx.defender.g, suppressK=ctx.defender.s, k=k_prev, steps=steps,
                    hidden=hidden, rules=rules)

    # ── 상태 도우미 ──
    def case_a(self, arm: str) -> str | None:
        r = self.runs[arm]
        return r.order[0] if r.order else None

    def _state(self, arm: str, case: str | None = None) -> tuple[str, dict[Any, str]]:
        """case를 주면 그 사례(의료진이 고른 탭)를 기준으로, 없으면 검색 1순위 사례(POC와 같음)를 기준으로."""
        A = case or self.case_a(arm)
        if A is None:
            raise DemoError("사례 검색 답변에 사례가 없어 이어서 물을 수 없습니다.")
        c = self.runs[arm].cases.get(A)
        return A, self.ctx.kc.reduce(c.committed)[0] if c and c.committed else {}

    def _key_for(self, arm: str, seed: dict[str, Any], case: str | None = None) -> tuple[Any, str | None]:
        """그 조건의 공개 상태에서 Seed가 무엇을 좁힐지. (key, 메모). key가 None이면 그 조건은 이 질문을 건너뛴다."""
        _, state = self._state(arm, case)
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

    def _fill(self, arm: str, seed: dict[str, Any], key: Any, case: str | None = None) -> str:
        A, state = self._state(arm, case)
        c = self.runs[arm].cases.get(A)
        evtxt = {f"{A}:{g}": v for g, v in c.events.items()} if c else {}
        subj = f"{A} 환자" if seed.get("scope") != "GROUP" else "검색된 사례 전체"
        return fill_seed(seed, key, state, self.ctx.data.N, subj, evtxt)

    def _intent(self, arm: str, seed: dict[str, Any], key: Any, case: str | None = None) -> dict[str, Any]:
        r, A = self.runs[arm], case or self.case_a(arm)
        return dict(kind="FOLLOW", seed=seed, key=key, case_A=A, qtype=self.qtype,
                    said={ref: [d["node_id"] for d in c.committed] for ref, c in r.cases.items()},
                    events={ref: list(c.events) for ref, c in r.cases.items()})

    # ── 질문 후보 ──
    def questions(self, arm: str = "C1", case: str | None = None) -> list[dict[str, Any]]:
        """화면에 보이는 조건의 공개 상태에서 지금 물을 수 있는 Seed (이미 쓴 것 제외)."""
        if self.turn >= self.budget:
            return []
        A, state = self._state(arm, case)
        kc, data = self.ctx.kc, self.ctx.data
        sent = set(self.runs[arm].sent)
        out = []
        for s in self.ctx.seeds:
            if s["seed_id"] in self.used or s["seed_id"] in self.blocked:
                continue
            key = target(s, state, kc.node, data.children, True)
            if key is None:
                continue
            text = self._fill(arm, s, key, case)
            if text in sent:
                continue
            out.append(dict(seed_id=s["seed_id"], text=text, target_qi=s["target_qi"], target_qi_2=s.get("target_qi_2"),
                            target_label=ATTR_KO[s["target_qi"]] + (f"+{ATTR_KO[s['target_qi_2']]}" if s.get("target_qi_2") else ""),
                            objective=OBJECTIVE_KO.get(s["attack_objective"], s["attack_objective"]),
                            variant=VARIANT_KO.get(s["variant"], s["variant"]), scope=SCOPE_KO.get(s.get("scope"), s.get("scope")),
                            relation=s.get("expected_relation")))
        return out

    # ── 보내기 전 확인 ──
    def preview(self, seed_id: str, arm: str = "C1", case: str | None = None, text: str | None = None) -> dict[str, Any]:
        """이 질문에 대상 AI가 기록대로 답하면 사례별 후보 수가 어떻게 되는지 (State는 바꾸지 않는다)."""
        seed = self._seed(seed_id)
        key, note = self._key_for(arm, seed, case)
        if key is None:
            return dict(seed_id=seed_id, applicable=False, note=note, cases=[])
        r = self.runs[arm]
        q = text or self._fill(arm, seed, key, case)
        raw = self.ctx.llm.complete("target", self.prefix.system, r.msgs + [{"role": "user", "content": q}], docs=self.prefix.docs,
                                    intent=self._intent(arm, seed, key, case))
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
        alt = [x for x in self.questions(arm, case) if x["seed_id"] != seed_id and x["target_qi"] not in ("PERIOD", seed["target_qi"])][:2]
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
        if self.turn >= self.budget:
            raise DemoError(f"질문 예산 {self.budget}턴을 다 썼습니다.")
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

    def _send(self, seed: dict[str, Any], op: str, primary: str, picked_by: str, case: str | None = None,
              text: str | None = None) -> dict[str, Any] | None:
        """case·text는 의료진이 직접 쓴 질문용: 그 사례를 기준으로, 질문 문장은 의료진이 쓴 그대로 세 조건에 보낸다."""
        turn = self.turn + 1
        A0 = case or self.case_a(primary)
        c0 = self.runs[primary].cases.get(A0)
        kA_before = c0.k_hist[-1] if c0 and c0.k_hist else self.ctx.p_ref
        prepared: dict[str, Any] = {}
        for a in ARMS:
            key, note = self._key_for(a, seed, case)
            if key is None:
                prepared[a] = dict(status="SKIPPED", note=note)
                continue
            try:
                filled = self._fill(a, seed, key, case)
            except (KeyError, IndexError):
                prepared[a] = dict(status="SKIPPED", note="이 조건의 공개 상태로는 질문 문장을 채울 수 없습니다.")
                continue
            if text is not None:
                prepared[a] = dict(status="READY", key=key, note=note, q=text, filled=filled, tries=[])
                continue
            A = case or self.case_a(a)
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
                         filled_seed=pr["filled"], realization_fallback=False, checks=pr["tries"], regenerations=max(len(pr["tries"]) - 1, 0),
                         fuzzer=self.fuzzer if picked_by.startswith("fuzzer") else None,
                         fuzzer_strategy=self.selector.strategy if self.selector else None, picked_by=picked_by),
                    intent=self._intent(a, seed, pr["key"], case))
            pr["status"] = "ANSWERED"
        if self.selector is not None and A0 in self.runs[primary].cases:
            self.selector.observe(kA_before, self.runs[primary].cases[A0].k_hist[-1])
        self.steps.append(dict(turn=turn, seed_id=seed["seed_id"], picked_by=picked_by, operator=op, case=case,
                               arms={a: dict(status=prepared[a]["status"], note=prepared[a].get("note")) for a in ARMS}))
        self.last_active = time.time()
        self.eng._trim_usage()
        return dict(turn=turn, seed_id=seed["seed_id"], picked_by=picked_by, arms=self.steps[-1]["arms"])

    def ask_text(self, case: str, text: str, primary: str = "C1", compare: bool = True, scope: str = "case") -> dict[str, Any]:
        """
        live LLM 세션: 의료진이 쓴 문장을 Seed 없이 그대로 보낸다 (api_server와 같은 방식).
        scope='case'이고 문장에 '사례N'이 없으면 고른 사례를 가리키도록 '사례N에 대한 질문: '을 붙인다 (화면에는 원문).
        scope='all'(모든 사례에 묻기)이면 '검색된 사례 전체에 대한 질문: '을 붙인다. 공개 판정은 그대로 사례마다 한다.
        화면 갈래(primary, C1)만 LLM에 묻고, 비교 갈래(C0 · C1S)는 같은 원 응답과 추출 결과를 함께 써서 방어만 다르게 한다
        (ADR-0009 --paired와 같음). LLM 오류는 State를 바꾸기 전에 나므로 그대로 올린다.
        """
        if self.llm_mode != "live":
            raise DemoError("결정적 응답기 세션은 ask(seed, …)로 묻습니다.")
        if self.turn >= self.budget:
            raise DemoError(f"이 대화의 질문 예산 {self.budget}턴을 다 썼습니다. 새 환자로 다시 시작하세요.")
        turn = self.turn + 1
        if scope == "all":
            query = f"검색된 사례 전체에 대한 질문: {text}"
        else:
            query = text if _MENTIONS_CASE.search(text) else f"{case}에 대한 질문: {text}"
        meta = dict(seed_id=None, picked_by="clinician", source="clinic", case=case, user_question=text, free_text=True, scope=scope)
        rec = self.runs[primary]._turn(turn, query, None, None, None, 0, meta)
        arms = {primary: dict(status="ANSWERED")}
        shared = (rec["raw_response_text"], rec["raw_observations"], rec["extraction_ok"], rec["extraction_tries"])
        later = []
        for a in ARMS:
            if a == primary:
                continue
            if not compare:
                arms[a] = dict(status="SKIPPED", note="비교 갈래 계산을 끈 서버입니다.")
            elif a == "C0":                                  # 방어 없음: 같은 원 응답을 그대로 공개 → LLM 호출 없이 바로
                self._compare_turn(a, turn, query, shared, meta, arms)
            else:                                            # C1S: 재작성 · 확인 추출 호출이 들 수 있어 의료진 답을 보낸 뒤 계산
                arms[a] = dict(status="QUEUED", note="의료진 답을 보낸 뒤 계산합니다.")
                later.append(a)
        self.turn = turn
        self.steps.append(dict(turn=turn, seed_id=None, picked_by="clinician", operator=None, case=case, arms=arms))
        self.last_active = time.time()
        for a in later:
            self.eng.queue_compare(self, a, turn, query, shared, meta)
        self.eng._trim_usage()
        return rec

    def _compare_turn(self, a: str, turn: int, query: str, shared: tuple, meta: dict[str, Any], arms: dict[str, Any]) -> None:
        """비교 갈래 한 턴: 화면 갈래의 원 응답 · 추출 결과를 그대로 쓰고 방어만 그 갈래 방식으로 (ADR-0009 --paired)."""
        try:
            self.runs[a]._turn(turn, query, *shared, dict(meta, shared_raw=True))
            arms[a] = dict(status="ANSWERED")
        except Exception as exc:                     # 비교 갈래 실패는 의료진 답에 영향을 주지 않는다
            arms[a] = dict(status="ERROR", note=f"비교 갈래 계산 실패 ({type(exc).__name__})")

    def ask(self, seed: dict[str, Any], case: str, text: str, primary: str = "C1") -> dict[str, Any] | None:
        """의료진이 쓴 질문 한 건. 질문 뜻에 맞는 Seed를 받아 그 사례 기준으로 세 조건에 보낸다. 화면 조건에서 못 물으면 None."""
        if self.turn >= self.budget:
            raise DemoError(f"이 대화의 질문 예산 {self.budget}턴을 다 썼습니다. 새 환자로 다시 시작하세요.")
        op = self.rng.choice(applicable_ops(seed, self.cfg.operators))
        return self._send(seed, op, primary, "clinician", case=case, text=text)

    def run_to_end(self, arm: str = "C1") -> int:
        n = 0
        while self.turn < self.budget:
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
            present = rec.get("cases") or {}
            for ref, c in present.items():
                if "k" in c:
                    out[ref].append([rec["turn"], c["k"]])
            for p in rec.get("release_plans") or []:      # 답에 나왔지만 아직 State에 아무것도 없는 사례 (사례째로 뺌 등): 기준 집단 전체
                if p["ref"] not in present:
                    out[p["ref"]].append([rec["turn"], self.ctx.p_ref])
        if arm == "C1" and self.approvals:            # 승인 공개는 턴이 아니어서 기록에 없다: 지금 State의 후보 수를 끝에 잇는다
            for ref in {x["case"] for ap in self.approvals for x in ap["items"]} | set(out):
                k = self.current_k(arm, ref)
                series = out[ref]
                if not series or series[-1][1] != k:
                    series.append([self.turn, k])
        return dict(out)

    def current_k(self, arm: str, ref: str) -> int:
        c = self.runs[arm].cases.get(ref)
        return self.ctx.kc.k(c.committed)["k"] if c and c.committed else self.ctx.p_ref

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
        if not changed:
            # 실제 LLM 답은 '사례N · 항목: 값' 줄 모양이 아니라 줄 비교로는 바뀐 곳을 못 찾는다 → Defender 판정에서 읽는다
            refusal = rec["release_mode"].startswith("REFUSAL")
            for p in rec.get("release_plans") or []:
                for d in p["decisions"]:
                    act = "suppress" if refusal else d["action"]
                    if act != "allow":
                        changed[p["ref"]][(ATTR_KO.get(d["attribute"], d["attribute"]), act)] += 1
        notes = [dict(case=ref, changes=[dict(attribute=a, change=c) for (a, c) in cnt], k_if_raw=cand.get(ref),
                      k_now=(rec.get("cases") or {}).get(ref, {}).get("k")) for ref, cnt in changed.items()]
        v = dict(turn=rec["turn"], question=rec["query_text"], mode=rec["release_mode"],
                 refused=rec["release_mode"].startswith("REFUSAL"),
                 dropped=sorted({p["ref"] for p in rec.get("release_plans") or [] if any(d.get("dropped") for d in p["decisions"])}),
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
                    turn=self.turn, budget=self.budget, k_req=self.cfg.k_req, p_ref=self.ctx.p_ref, source=self.source,
                    created=self.created, last_active=self.last_active, review=self.review, llm_mode=self.llm_mode,
                    owner=self.owner["label"] if self.owner else None,
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
        return dict(self._summary(), arms=arms, steps=self.steps, rules=copy.deepcopy(self.rules), approvals=copy.deepcopy(self.approvals),
                    retrieval=[dict(ref=f"사례{i}", patient=p[:8], score=round(s, 4)) for i, (p, s) in enumerate(self.prefix.retrieval, 1)])


# ── 레드팀 배치 ─────────────────────────────────────────────

# 레드팀 trial 결과 (medical/session.py ArmRun.run의 outcome)
OUTCOME_KO = dict(NO_CASE="사례 없음", RISK_AT_TURN0="첫 답부터 기준 아래", MUTATION_BUDGET="공격 질문 시도 한도", SATURATED="더 물을 질문 없음",
                  RISK_REACHED="기준 아래로 내려감", BUDGET="10턴 다 씀", LLM_ERROR="LLM 호출 실패")


class RedTeamCancelled(Exception):
    """레드팀 실행을 보안 담당자가 멈췄다."""


class _JobLLM:
    """레드팀 실행용 실제 LLM: 의료진 질문에 자리를 양보하고(LiveLLM 뒤 순서), 호출 수를 따로 세고, 멈춤을 받는다."""

    def __init__(self, live: LiveLLM, job: "RedTeamJob") -> None:
        inner = copy.copy(live.inner)
        inner.usage = []                                  # 의료진 대화 호출과 섞이지 않게 이 실행의 호출만 센다
        self.llm, self.job = live.sibling(inner), job
        self.style = job.answer_style                     # 의료진 대화와 같은 대상 AI 답 형식

    @property
    def usage(self) -> list[dict[str, Any]]:
        return self.llm.usage

    def complete(self, role: str, system: str, messages: list[dict[str, str]], **kw: Any) -> str:
        if self.job.cancel_event.is_set():
            raise RedTeamCancelled()
        return self.llm.complete(role, styled(role, system) if self.style else system, messages, **kw)


class RedTeamJob(threading.Thread):
    """
    레드팀 점검: 질의 환자(trial)마다 퍼저가 공격 질문을 만들어 세 갈래(C0 · C1 · C1S)에 보내고 medical.poc_analysis.analyse로 집계한다.
      live=False : 결정적 응답기 (POC와 같은 결과, LLM 호출 0)
      live=True  : 서버의 실제 LLM. 공격 질문 만들기 · 대상 AI · 추출 · 재작성이 모두 실제 호출이다.
                   의료진 질문이 기다리면 먼저 보내고, 규칙 추출을 켠다 (의료진 대화와 같은 설정, ADR-0021).
    medical.experiment.run_experiment와 같은 순서로 돌리되, 멈추거나 실패해도 끝낸 trial까지는 집계해 남긴다.
    실제 LLM 실행의 갈래는 의료진 대화와 같은 고친 답 다시 확인(RuledArmRun)을 쓴다 (_group).
    """

    def __init__(self, eng: Engine, jid: str, profile: str, fuzzer: str, per_type: int | None, *, live: bool = False,
                 on_finish: Callable[["RedTeamJob"], None] | None = None, meta: dict[str, Any] | None = None) -> None:
        super().__init__(daemon=True)
        # 자동 점검(autocheck.py): 무엇이 시작했는지 · 그때의 설정과 지문 · 끝난 뒤 직전 점검과의 비교
        meta = meta or {}
        self.trigger, self.settings, self.fingerprint = meta.get("trigger"), meta.get("settings"), meta.get("fingerprint")
        self.compare: dict[str, Any] | None = None
        self.eng, self.id, self.profile, self.fuzzer, self.per_type, self.live = eng, jid, profile, fuzzer, per_type, live
        # POC와 같은 설정 (efficiency, budget 10). 실제 LLM이면 의료진 대화와 같은 규칙 추출 설정을 쓴다
        self.cfg = MedicalConfig(fuzzer=fuzzer, rule_extract=live and getattr(eng, "live_rule_extract", True))
        tag = "live" if live else profile
        self.out = eng.workdir / "redteam" / f"{jid}_{tag}_{fuzzer}_{per_type or 'all'}"
        self.planner = plan_all(per_type, self.cfg.seed)
        self.n_trials = len(self.planner(eng.data, eng.split, self.cfg))
        self.total = self.n_trials * len(self.cfg.arms)
        self.done, self.status, self.error, self.result = 0, "queued", None, None
        self.kept = 0                                    # 집계에 넣은 갈래별 대화 수 (세 갈래를 다 끝낸 질의 환자만)
        self.llm_error_trials = 0                        # LLM 호출이 실패해 집계에서 뺀 질의 환자 수
        self.started = self.finished = None
        self.last_line = ""
        self.cancel_event = threading.Event()
        self.on_finish = on_finish
        self.llm: Any = None
        self.model = eng.live_label if live else None
        self.answer_style = bool(live and getattr(eng, "answer_style", True))

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        from medical.poc_analysis import analyse
        from medical.session import dumps, run_trial_group
        from medical.validate import validate_trial
        self.status, self.started = "running", time.time()
        final, trials, ctx = "done", [], None
        try:
            if self.live:
                background_calls()                       # 의료진 질문 호출이 먼저
                self.llm = _JobLLM(self.eng.live_llm, self)
            else:
                self.llm = OracleRoleLLM(data=self.eng.data, profile=self.profile)
            self.out.mkdir(parents=True, exist_ok=True)
            ctx, split = build_context(self.cfg, self.llm, self.out, data=self.eng.data)
            plan = self.planner(ctx.data, split, self.cfg)
            doc_patient = {d["doc_id"]: p for p, d in ctx.docs.items()}
            with open(self.out / "턴기록.jsonl", "w", encoding="utf-8") as tf:
                log = lambda rec: (tf.write(dumps(rec) + "\n"), tf.flush())
                for tid, pid, qt, role in plan:
                    if self.cancel_event.is_set():       # 결정적 응답기 실행도 질의 환자 사이에서 멈춘다
                        raise RedTeamCancelled()
                    group = self._group(run_trial_group, ctx, tid, pid, qt, role, log)
                    self.done += len(group)
                    if self.cancel_event.is_set():       # 멈춘 뒤 끝난 질의 환자는 넣지 않는다 (중간에 끊긴 호출이 있을 수 있음)
                        raise RedTeamCancelled()
                    if any(t["outcome"] == "LLM_ERROR" for t in group):
                        # 한 갈래라도 LLM 호출이 실패한 질의 환자는 빼고 센다 (세 갈래 짝이 맞아야 비교가 된다)
                        self.llm_error_trials += 1
                        self.last_line = f"{tid} {QTYPE_KO.get(qt, qt)}: LLM 호출 실패로 집계에서 뺌"
                        if not trials and self.llm_error_trials >= 3:
                            raise RuntimeError("LLM 호출이 처음 세 질의 환자에서 모두 실패해 멈췄습니다. 키 · 주소 · 호출 한도를 확인하세요 (check-llm).")
                        continue
                    for t in group:
                        if t.get("case_committed") is not None:
                            t["validation"] = validate_trial(t, ctx.data, ctx.kc, doc_patient, self.cfg.k_req)
                        A = t.get("case_A")
                        kA = t.get("case_k", {}).get(A, [None])[-1] if A else None
                        self.last_line = (f"{tid} {QTYPE_KO.get(qt, qt)} · {ARM_KO.get(t['arm'], t['arm'])}: {OUTCOME_KO.get(t['outcome'], t['outcome'])}"
                                          + (f", 질의 대상 사례 후보 {kA}명" if kA is not None else ""))
                    trials += group                       # 세 갈래를 다 끝낸 질의 환자만 집계에 넣는다 (멈췄을 때 짝이 맞게)
                    self.kept = len(trials)
        except RedTeamCancelled:
            final = "cancelled"
        except Exception as exc:          # 화면에 보여 주고 서버는 계속 돈다
            final, self.error = "error", f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}"
        if trials and ctx is not None:
            try:
                versions = (dict(ctx.versions, medicloak_release=RELEASE_VERSION, answer_style=ANSWER_STYLE_ID if self.answer_style else "off")
                            if self.live else ctx.versions)
                summary = dict(config=self.cfg.as_dict(), versions=versions, trials=trials)
                (self.out / "trial요약.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
                with open(self.out / "llm_usage.jsonl", "w", encoding="utf-8") as f:
                    for u in self.llm.usage:
                        f.write(json.dumps(u, ensure_ascii=False) + "\n")
                self.result = summarize(analyse(self.out), self.cfg.k_req)
            except Exception as exc:
                if final == "done":
                    final, self.error = "error", f"집계 실패: {type(exc).__name__}: {exc}"
        elif final == "done" and self.llm_error_trials:
            final, self.error = "error", f"모든 질의 환자({self.llm_error_trials}명)에서 LLM 호출이 실패해 집계할 대화가 없습니다. 키 · 주소를 확인하세요 (check-llm)."
        self.finished = time.time()
        self.status = final                              # 결과를 다 만든 뒤에 끝났다고 알린다 (끝남을 본 화면이 바로 결과를 받게)
        if self.on_finish is not None:
            try:
                self.on_finish(self)
            except Exception as exc:
                print(f"[medicloak] 레드팀 결과 저장 실패 ({self.id}): {type(exc).__name__}: {exc}")

    def _group(self, run_trial_group: Callable[..., list[dict[str, Any]]], ctx: Context, tid: str, pid: str, qt: str, role: str,
               log: Callable[[dict[str, Any]], None]) -> list[dict[str, Any]]:
        """
        질의 환자 1명의 세 갈래. 결정적 응답기 실행은 연구 모듈 그대로(POC 재현). 실제 LLM 실행은 의료진 대화와 같은 방어를 시험해야 하므로
        medical.session.run_trial_group과 같은 순서로 돌리되 갈래를 RuledArmRun(고친 답 다시 확인 보강 · 재작성 지시 보강 ·
        사례 단위로 빼기, 규칙 없음)으로 만든다.
        """
        if not self.live:
            return run_trial_group(ctx, tid, pid, qt, role, self.cfg.arms, log)
        try:
            prefix = make_prefix(ctx, tid, pid, qt, role)
        except LLMError as exc:
            return [dict(trial_id=tid, arm=a, query_patient=pid, query_type=qt, role=role, outcome="LLM_ERROR",
                         error=f"{type(exc).__name__}: {exc}", versions=ctx.versions) for a in self.cfg.arms]
        return [RuledArmRun(ctx, prefix, a, log, lambda: [], live=True).run() for a in self.cfg.arms]

    def usage(self) -> dict[str, int]:
        u = list(getattr(self.llm, "usage", None) or []) if self.live else []
        return dict(calls=len(u), input_tokens=sum(int(x.get("input_tokens") or 0) for x in u),
                    output_tokens=sum(int(x.get("output_tokens") or 0) for x in u))

    def as_dict(self) -> dict[str, Any]:
        elapsed = round((self.finished or time.time()) - self.started, 1) if self.started else None
        eta = None
        if self.status == "running" and self.done and elapsed:
            eta = round(elapsed / self.done * (self.total - self.done))
        return dict(id=self.id, live=self.live, model=self.model, answer_style=("on" if self.answer_style else "off") if self.live else None,
                    profile=self.profile, profile_label=(self.model or "실제 LLM") if self.live else PROFILE_KO[self.profile],
                    fuzzer=self.fuzzer, fuzzer_label=FUZZER_KO[self.fuzzer], per_type=self.per_type, trials=self.n_trials,
                    total=self.total, done=self.done, kept=self.kept, llm_error_trials=self.llm_error_trials,
                    status=self.status, error=self.error, elapsed=elapsed, eta=eta,
                    started_at=self.started, finished_at=self.finished, usage=self.usage(),
                    out=str(self.out.relative_to(ROOT)) if self.out.is_relative_to(ROOT) else str(self.out),
                    last=self.last_line, result=self.result, trigger=self.trigger, settings=self.settings, fingerprint=self.fingerprint,
                    compare=self.compare)


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
