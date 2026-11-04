# 보안 담당자 관제 화면용 집계 (/api/monitor)
#
# 대화 하나(Session)마다 의료진 화면에 실제로 나간 조건(C1)의 판정을 모아 상태를 정한다.
#   특정 시도 막음(danger) : 그대로 답했다면 후보가 가림 기준(3명) 이하로 줄었을 단서를 가렸다
#   넓혀서 답함(caution)   : 가린 것은 없고 넓은 범주로 바꾼 단서가 있다
#   이상 없음(safe)        : 모두 그대로 답했다
# '같은 환자 반복 질문'은 한 사례에서 가림이 두 번 이상 나온 대화다.
# 원 응답·가린 원래 값·환자 번호는 기본으로 지워서 보내고, 사유를 남긴 열람(reveal)에서만 보낸다. 열람·검토는 감사 기록에 남는다.
#
# 의료진 ↔ 보안 담당자 메시지 (Session.messages)
#   의료진: 세부 정보 요청(access_request) · 답장(reply)     보안 담당자: 확인 요청(check_request) · 답장(reply)
#   마지막 메시지를 의료진이 보냈으면 보안 담당자가 답할 차례다 → 검토 필요 목록 맨 위로 올린다.
#   '의료진에게 확인 요청' 검토 표시는 확인 요청 메시지를 함께 보낸다 (의료진 화면에 도착하고, 의료진이 답할 수 있다).
#   메시지는 원래 값을 담지 않는다. 의료진이 무엇이 필요한지 쓰고, 보안 담당자가 처리 결과를 답한다.

from __future__ import annotations

import collections
import copy
import itertools
import re
import threading
import time
from typing import Any

from webdemo.backend.engine import ARM_KO, Engine, Session

LIVE_ARM = "C1"
SOURCE_KO = dict(clinic="의료진 화면", simulation="레드팀 시뮬레이션", manual="데모 세션")
STATUS_KO = dict(danger="특정 시도 막음", caution="넓혀서 답함", safe="이상 없음")
REVIEW_KO = dict(reviewed="검토 완료", ask_clinician="의료진에게 확인 요청", add_rule="질문 패턴을 규칙에 추가")
ACTOR = "보안 담당자 (데모)"
CLINICIAN = "의료진 (데모)"
SIM_TRIALS = ("T0010", "T0015", "T0036", "T0024", "T0016", "T0005")

MSG_KINDS = dict(clinician=("access_request", "reply"), security=("check_request", "reply"))
MSG_KIND_KO = dict(access_request="세부 정보 요청", check_request="확인 요청", reply="답장")
# 메시지마다 감사 기록 action. 보안 담당자의 확인 요청은 검토 표시(ask_clinician)와 같은 이름을 쓴다.
MSG_AUDIT = {("clinician", "access_request"): "access_request", ("clinician", "reply"): "clinician_reply",
             ("security", "check_request"): "ask_clinician", ("security", "reply"): "security_reply"}
CHECK_DEFAULT = "이 대화에서 같은 사례의 세부 정보를 여러 번 물으셨습니다. 진료에 필요한 내용이었는지 알려 주세요."
FLAG_KO = dict(access_request="의료진 세부 정보 요청", reply="의료진 답장 도착")
_CASE_REF = re.compile(r"사례\d+")


class Monitor:
    def __init__(self, eng: Engine) -> None:
        self.eng = eng
        self.audit: list[dict[str, Any]] = []
        self._ids = itertools.count(1)
        self._mids = itertools.count(1)
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
        last_msg = s.messages[-1] if s.messages else None
        pending = bool(last_msg and last_msg["sender"] == "clinician")          # 보안 담당자가 답할 차례
        awaiting = bool(last_msg and last_msg["sender"] == "security" and last_msg["kind"] == "check_request")
        flag = FLAG_KO[last_msg["kind"]] if pending else "같은 환자 반복 질문" if repeated else None
        return dict(id=s.id, trial_id=s.trial_id, source=s.source, source_label=SOURCE_KO.get(s.source, s.source),
                    qtype_label=s._summary()["qtype_label"], turns=s.turn, suppressed=sup, generalized=gen,
                    status=status, status_label=STATUS_KO[status], focus_case=focus,
                    k_if_raw=min_raw.get(focus) if focus else None, k_now=k_now.get(focus) if focus else None,
                    repeated=repeated, flag=flag, violated=violated,
                    last_question=last_q, last_active=s.last_active, created=s.created,
                    review=s.review, needs_review=(bool(repeated) and not s.review) or pending,
                    messages=len(s.messages), pending_request=pending, awaiting_clinician=awaiting,
                    request_case=last_msg.get("case") if pending else None)

    def overview(self) -> dict[str, Any]:
        with self.eng.lock:
            rows = [self.row(s) for s in self.eng.sessions.values()]
        rank = dict(danger=0, caution=1, safe=2)
        rows.sort(key=lambda r: (not r["pending_request"], not r["needs_review"], rank[r["status"]], -r["last_active"]))
        kpi = dict(sessions=len(rows), suppressed=sum(r["suppressed"] for r in rows), generalized=sum(r["generalized"] for r in rows),
                   identified=sum(len(r["violated"]) for r in rows), needs_review=sum(r["needs_review"] for r in rows),
                   blocked_sessions=sum(r["status"] == "danger" for r in rows), requests=sum(r["pending_request"] for r in rows))
        return dict(kpi=kpi, sessions=rows, simulations=self.sim_status, live_arm=LIVE_ARM, live_arm_label=ARM_KO[LIVE_ARM],
                    k_req=self.eng.cfg.k_req, suppress_threshold=self.eng.cfg.suppress_threshold,
                    generalize_threshold=self.eng.cfg.generalize_threshold)

    # ── 상세 ──
    def detail(self, s: Session, reveal: bool = False) -> dict[str, Any]:
        with self.eng.lock:
            v = s.security_view()
            row = self.row(s)
            msgs = copy.deepcopy(s.messages)
        if not reveal:
            v = mask(v)
        return dict(v, row=row, revealed=reveal, source_label=SOURCE_KO.get(s.source, s.source), live_arm=LIVE_ARM, messages=msgs)

    def reveal(self, s: Session, reason: str) -> dict[str, Any]:
        self.log("reveal", s, reason=reason)
        return self.detail(s, reveal=True)

    def review(self, s: Session, action: str, note: str | None) -> dict[str, Any]:
        check = None
        if action == "ask_clinician":                    # 표시만 하지 않고 의료진 화면에 확인 요청을 보낸다
            check = (note or "").strip() or CHECK_DEFAULT
            if len(check) < 2:                           # 상태를 바꾸기 전에 검사한다 (표시 · 감사 기록만 남고 메시지가 없는 일이 없게)
                raise ValueError("확인 요청은 2자 이상 써 주세요.")
        s.review = dict(action=action, label=REVIEW_KO[action], at=time.time(), actor=ACTOR, note=note)
        self.log(action, s, note=note)
        if check is not None:
            with self.eng.lock:
                case = self.row(s)["focus_case"]
            self.post_message(s, "security", "check_request", check, case, audit=False)
        with self.eng.lock:
            return self.row(s)

    # ── 의료진 ↔ 보안 담당자 메시지 ──
    def post_message(self, s: Session, sender: str, kind: str, text: str, case: str | None = None, *,
                     audit: bool = True) -> dict[str, Any]:
        text = (text or "").strip()
        if kind not in MSG_KINDS.get(sender, ()):
            raise ValueError(f"{sender} 메시지 종류는 {', '.join(MSG_KINDS.get(sender, ()))} 중 하나입니다.")
        if not 2 <= len(text) <= 500:
            raise ValueError("메시지는 2자 이상 500자 이하로 써 주세요.")
        if case is not None and not _CASE_REF.fullmatch(case):
            raise ValueError(f"사례 표시가 올바르지 않습니다: {case}")
        actor = ACTOR if sender == "security" else CLINICIAN
        m = dict(id=f"M{next(self._mids):04d}", at=time.time(), sender=sender, kind=kind, kind_label=MSG_KIND_KO[kind],
                 case=case, text=text, actor=actor)
        with self.eng.lock:
            s.messages.append(m)
            s.last_active = m["at"]
        if audit:
            self.log(MSG_AUDIT[(sender, kind)], s, actor=actor, note=text, case=case)
        return m

    def thread(self, s: Session) -> dict[str, Any]:
        with self.eng.lock:
            return dict(messages=copy.deepcopy(s.messages), row=self.row(s))


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
