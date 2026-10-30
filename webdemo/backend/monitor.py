# 보안 담당자 관제 화면용 집계 (/api/monitor)
#
# 대화 하나(Session)마다 의료진 화면에 실제로 나간 조건(C1)의 판정을 모아 상태를 정한다.
#   특정 시도 막음(danger) : 그대로 답했다면 후보가 가림 기준(3명) 이하로 줄었을 단서를 가렸다
#   넓혀서 답함(caution)   : 가린 것은 없고 넓은 범주로 바꾼 단서가 있다
#   이상 없음(safe)        : 모두 그대로 답했다
# '같은 환자 반복 질문'은 한 사례에서 가림이 두 번 이상 나온 대화다.
# 원 응답·가린 원래 값·환자 번호는 기본으로 지워서 보내고, 사유를 남긴 열람(reveal)에서만 보낸다. 열람·검토는 감사 기록에 남는다.

from __future__ import annotations

import collections
import copy
import itertools
import threading
import time
from typing import Any

from webdemo.backend.engine import ARM_KO, Engine, Session

LIVE_ARM = "C1"
SOURCE_KO = dict(clinic="의료진 화면", simulation="레드팀 시뮬레이션", manual="데모 세션")
STATUS_KO = dict(danger="특정 시도 막음", caution="넓혀서 답함", safe="이상 없음")
REVIEW_KO = dict(reviewed="검토 완료", ask_clinician="의료진에게 확인 요청", add_rule="질문 패턴을 규칙에 추가")
ACTOR = "보안 담당자 (데모)"
SIM_TRIALS = ("T0010", "T0015", "T0036", "T0024", "T0016", "T0005")


class Monitor:
    def __init__(self, eng: Engine) -> None:
        self.eng = eng
        self.audit: list[dict[str, Any]] = []
        self._ids = itertools.count(1)
        self.sim_status = "idle"

    # ── 감사 기록 ──
    def log(self, action: str, session: Session | None = None, **kw: Any) -> dict[str, Any]:
        e = dict(id=f"A{next(self._ids):04d}", at=time.time(), actor=kw.pop("actor", ACTOR), action=action,
                 session=session.id if session else None, trial=session.trial_id if session else None, **kw)
        self.audit.append(e)
        return e

    # ── 시작할 때 돌리는 시뮬레이션 대화 ──
    def seed_simulations(self, trials: tuple[str, ...] = SIM_TRIALS, turns: int = 6) -> threading.Thread:
        def work() -> None:
            self.sim_status = "running"
            try:
                for tid in trials:
                    s = self.eng.new_session(tid, source="simulation")
                    for _ in range(turns):
                        with self.eng.lock:
                            try:
                                s.step(None, LIVE_ARM)
                            except Exception:
                                break
                        time.sleep(0.05)          # 화면 요청이 잠금을 기다리다 굶지 않게 한 턴마다 양보한다
                    s.last_active = time.time()
                self.sim_status = "done"
            except Exception as exc:          # 관제 화면은 시뮬레이션 없이도 돈다
                self.sim_status = f"error: {exc}"
        t = threading.Thread(target=work, daemon=True)
        t.start()
        return t

    # ── 대화 하나 요약 ──
    def row(self, s: Session) -> dict[str, Any]:
        recs = [r for r in s.logs[LIVE_ARM] if r.get("turn") is not None]
        sup = gen = 0
        sup_by_case: collections.Counter = collections.Counter()
        min_raw: dict[str, int] = {}
        for r in recs:
            cand = r.get("cases_candidate_k") or {}
            for p in r.get("release_plans") or []:
                acts = [d["action"] for d in p["decisions"]]
                sup += acts.count("suppress")
                gen += acts.count("generalize")
                if "suppress" in acts:
                    sup_by_case[p["ref"]] += 1
                kr = cand.get(p["ref"])
                if kr is not None and any(a != "allow" for a in acts):
                    min_raw[p["ref"]] = min(kr, min_raw.get(p["ref"], kr))
        k_now = {}
        for r in recs:
            for ref, c in (r.get("cases") or {}).items():
                if "k" in c:
                    k_now[ref] = c["k"]
        focus = min(min_raw, key=lambda ref: (min_raw[ref], ref)) if min_raw else s.case_a(LIVE_ARM)
        status = "danger" if sup else "caution" if gen else "safe"
        k_req = s.cfg.k_req
        violated = sorted(ref for ref, k in k_now.items() if 1 <= k < k_req)
        repeated = [ref for ref, n in sup_by_case.items() if n >= 2]
        last_q = next((r["query_text"] for r in reversed(recs) if r["turn"] > 0), None)
        return dict(id=s.id, trial_id=s.trial_id, source=s.source, source_label=SOURCE_KO.get(s.source, s.source),
                    qtype_label=s._summary()["qtype_label"], turns=s.turn, suppressed=sup, generalized=gen,
                    status=status, status_label=STATUS_KO[status], focus_case=focus,
                    k_if_raw=min_raw.get(focus) if focus else None, k_now=k_now.get(focus) if focus else None,
                    repeated=repeated, flag="같은 환자 반복 질문" if repeated else None, violated=violated,
                    last_question=last_q, last_active=s.last_active, created=s.created,
                    review=s.review, needs_review=bool(repeated) and not s.review)

    def overview(self) -> dict[str, Any]:
        with self.eng.lock:
            rows = [self.row(s) for s in self.eng.sessions.values()]
        rank = dict(danger=0, caution=1, safe=2)
        rows.sort(key=lambda r: (not r["needs_review"], rank[r["status"]], -r["last_active"]))
        kpi = dict(sessions=len(rows), suppressed=sum(r["suppressed"] for r in rows), generalized=sum(r["generalized"] for r in rows),
                   identified=sum(len(r["violated"]) for r in rows), needs_review=sum(r["needs_review"] for r in rows),
                   blocked_sessions=sum(r["status"] == "danger" for r in rows))
        return dict(kpi=kpi, sessions=rows, simulations=self.sim_status, live_arm=LIVE_ARM, live_arm_label=ARM_KO[LIVE_ARM],
                    k_req=self.eng.cfg.k_req, suppress_threshold=self.eng.cfg.suppress_threshold,
                    generalize_threshold=self.eng.cfg.generalize_threshold)

    # ── 상세 ──
    def detail(self, s: Session, reveal: bool = False) -> dict[str, Any]:
        with self.eng.lock:
            v = s.security_view()
            row = self.row(s)
        if not reveal:
            v = mask(v)
        return dict(v, row=row, revealed=reveal, source_label=SOURCE_KO.get(s.source, s.source), live_arm=LIVE_ARM)

    def reveal(self, s: Session, reason: str) -> dict[str, Any]:
        self.log("reveal", s, reason=reason)
        return self.detail(s, reveal=True)

    def review(self, s: Session, action: str, note: str | None) -> dict[str, Any]:
        s.review = dict(action=action, label=REVIEW_KO[action], at=time.time(), actor=ACTOR, note=note)
        self.log(action, s, note=note)
        return self.row(s)


def mask(view: dict[str, Any]) -> dict[str, Any]:
    """원 응답, 가리거나 넓힌 원래 값, 환자 번호, 비교 조건의 답을 지운다. 의료진 화면에 나간 답(C1 released)만 남긴다."""
    v = copy.deepcopy(view)
    v["patient"] = None
    for r in v.get("retrieval", []):
        r["patient"] = None
    for name, a in v["arms"].items():
        for val in a.get("validation", {}).values():
            val["patient"] = None
        for t in a["turns"]:
            t["raw"] = None
            if name != LIVE_ARM:                        # 비교 조건(방어 없음 등)의 답에는 원래 값이 그대로 있다
                t["released"] = None
                for ln in t.get("lines", []) + t.get("raw_lines", []):
                    if "case" in ln:
                        ln["value"] = None
            changed = {(ln.get("case"), ln.get("field")) for ln in t.get("lines", []) if ln.get("change")}
            for ln in t.get("raw_lines", []):
                if (ln.get("case"), ln.get("field")) in changed:
                    ln["value"] = None
            for p in t.get("decisions", []):
                for it in p["items"]:
                    if it["action"] != "allow":
                        it["raw_value"] = None
    return v
