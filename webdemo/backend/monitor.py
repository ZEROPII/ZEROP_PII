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
#
# DB(store)가 있으면 (python -m medicloak)
#   감사 기록 · 메시지는 쓰는 즉시 DB에 넣고, 번호(A0001 · M0001)는 DB의 마지막 번호 다음부터 잇는다.
#   서버를 다시 켜기 전의 의료진 대화는 ArchivedSession으로 목록 · 상세에 남는다 (읽기와 검토 표시만, 메시지는 보낼 수 없음).
#   누가 했는지(actor)는 로그인한 계정 이름으로 남긴다.

from __future__ import annotations

import collections
import copy
import itertools
import re
import sqlite3
import threading
import time
from typing import Any, Callable

from webdemo.backend.auth import actor_label
from webdemo.backend.clinic import Conflict
from webdemo.backend.engine import ARM_KO, Engine, Session

LIVE_ARM = "C1"
SOURCE_KO = dict(clinic="의료진 화면", simulation="레드팀 시뮬레이션", manual="데모 세션")
STATUS_KO = dict(danger="특정 시도 막음", caution="넓혀서 답함", safe="이상 없음")
REVIEW_KO = dict(reviewed="검토 완료", ask_clinician="의료진에게 확인 요청", add_rule="질문 패턴을 규칙에 추가")
ACTOR = "보안 담당자 (데모)"
CLINICIAN = "의료진 (데모)"
SIM_TRIALS = ("T0010", "T0015", "T0036", "T0024", "T0016", "T0005")
AUDIT_LIMIT = 2000

MSG_KINDS = dict(clinician=("access_request", "reply"), security=("check_request", "reply", "release"))
MSG_KIND_KO = dict(access_request="세부 정보 요청", check_request="확인 요청", reply="답장", release="공개 승인")
# 메시지마다 감사 기록 action. 보안 담당자의 확인 요청은 검토 표시(ask_clinician)와 같은 이름을 쓴다.
MSG_AUDIT = {("clinician", "access_request"): "access_request", ("clinician", "reply"): "clinician_reply",
             ("security", "check_request"): "ask_clinician", ("security", "reply"): "security_reply", ("security", "release"): "approve_release"}
CHECK_DEFAULT = "이 대화에서 같은 사례의 세부 정보를 여러 번 물으셨습니다. 진료에 필요한 내용이었는지 알려 주세요."
FLAG_KO = dict(access_request="의료진 세부 정보 요청", reply="의료진 답장 도착")
ARCHIVED_PENDING = "답하지 못한 요청 (지난 대화)"
# 관제 화면의 공개 승인 메시지: 열람 전에는 값 대신 이 문장 (의료진에게는 값이 그대로 간다)
RELEASE_MASKED = "세부 정보 요청을 승인해 가린 값을 이 대화에서 공개했습니다. 공개한 값은 원문 열람 뒤에 보입니다."


def mask_messages(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = copy.deepcopy(msgs)
    for m in out:
        if m.get("kind") == "release":
            m["text"], m["masked"] = RELEASE_MASKED, True
    return out
_CASE_REF = re.compile(r"사례\d+")


class ArchivedSession:
    """DB에 남은 지난 의료진 대화 (서버를 다시 켜기 전). 관제 화면에서 읽기 · 열람 · 검토 표시만 된다."""

    archived = True
    source = "clinic"

    def __init__(self, conv: dict[str, Any], messages: list[dict[str, Any]]) -> None:
        self.db = conv
        self.id = conv["conv_id"]
        self.trial_id = conv["trial_id"]
        self.review = conv.get("review")
        self.messages = messages
        self.last_active = conv.get("last_active") or 0
        self.created = conv.get("started_at") or 0
        self.turn = conv.get("turns") or 0
        self.owner = dict(user_id=conv.get("user_id"), label=conv.get("owner_label")) if conv.get("owner_label") else None


class Monitor:
    def __init__(self, eng: Engine, store: Any = None, *, on_session_change: Callable[[Session], None] | None = None) -> None:
        self.eng = eng
        self.store = store
        self.on_session_change = on_session_change
        self.audit: list[dict[str, Any]] = []
        self._ids = itertools.count((store.max_seq("audit") if store else 0) + 1)
        self._mids = itertools.count((store.max_seq("thread_message") if store else 0) + 1)
        self._seq_lock = threading.Lock()
        self.sim_status = "idle"
        self.assistant: Any = None                  # 검토 보조 (assist.ReviewAssistant). create_app이 붙인다

    # ── 감사 기록 ──
    def log(self, action: str, session: Any = None, *, user: dict[str, Any] | None = None, actor: str | None = None,
            trial: str | None = None, **kw: Any) -> dict[str, Any]:
        """감사 기록 한 건. 대화가 없는 일(첫 답 미리 준비 등)은 trial만 준다."""
        with self._seq_lock:
            n = next(self._ids)
        e = dict(id=f"A{n:04d}", at=time.time(), actor=actor_label(user, actor or ACTOR), action=action,
                 session=session.id if session else None, trial=session.trial_id if session else trial, **kw)
        if user:
            e["user_id"] = user["user_id"]
        self.audit.append(e)
        if len(self.audit) > AUDIT_LIMIT:
            del self.audit[: len(self.audit) - AUDIT_LIMIT]
        if self.store is not None:
            try:
                self.store.add_audit(e, n)
            except sqlite3.IntegrityError:
                # 같은 DB를 쓰는 다른 서버(또는 테스트의 다른 앱)가 같은 번호를 먼저 썼다: DB의 마지막 번호 다음부터 다시 센다
                with self._seq_lock:
                    self._ids = itertools.count(self.store.max_seq("audit") + 1)
                    n = next(self._ids)
                e["id"] = f"A{n:04d}"
                self.store.add_audit(e, n)
        return e

    def audit_entries(self) -> list[dict[str, Any]]:
        """오래된 것부터 (API는 뒤집어 최근 것부터 보낸다)."""
        if self.store is not None:
            return self.store.audit_entries(AUDIT_LIMIT)
        return list(self.audit)

    def _changed(self, s: Any) -> None:
        if self.on_session_change is not None and not getattr(s, "archived", False):
            try:
                self.on_session_change(s)
            except Exception as exc:
                print(f"[medicloak] 대화 {s.id} 저장 실패: {type(exc).__name__}: {exc}")

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
    def row(self, s: Any) -> dict[str, Any]:
        if getattr(s, "archived", False):
            return self._archived_row(s)
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
        if getattr(s, "approvals", None):                # 승인 공개 뒤의 후보 수 (턴 기록 밖에서 State가 바뀌었다)
            refs = set(k_now) | {x["case"] for ap in s.approvals for x in ap["items"]}
            k_now = {ref: s.current_k(LIVE_ARM, ref) for ref in refs}
        focus = min(min_raw, key=lambda ref: (min_raw[ref], ref)) if min_raw else s.case_a(LIVE_ARM)
        if focus and focus not in k_now and hasattr(s, "current_k"):
            k_now[focus] = s.current_k(LIVE_ARM, focus)       # 아직 아무것도 공개되지 않은 사례 (예: 첫 답에서 사례째로 뺌): 기준 집단 전체
        status = "danger" if sup else "caution" if gen else "safe"
        k_req = s.cfg.k_req
        violated = sorted(ref for ref, k in k_now.items() if 1 <= k < k_req)
        repeated = [ref for ref, n in sup_by_case.items() if n >= 2]
        last_q = next((r.get("user_question") or r["query_text"] for r in reversed(recs) if r["turn"] > 0), None)
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
                    request_case=last_msg.get("case") if pending else None,
                    owner=s.owner["label"] if getattr(s, "owner", None) else None, archived=False,
                    llm_mode=getattr(s, "llm_mode", "oracle"))

    def _archived_row(self, a: ArchivedSession) -> dict[str, Any]:
        base = dict(a.db.get("row") or {})
        was_pending = bool(base.get("pending_request"))
        return dict(base, id=a.id, review=a.review, archived=True, pending_request=False, awaiting_clinician=False, request_case=None,
                    needs_review=bool(base.get("needs_review")) and not a.review,
                    flag=ARCHIVED_PENDING if was_pending and not a.review else base.get("flag") if not was_pending else None,
                    owner=a.owner["label"] if a.owner else base.get("owner"))

    def archived(self, sid: str) -> ArchivedSession | None:
        if self.store is None or sid in self.eng.sessions:
            return None
        c = self.store.conversation(sid)
        if c is None or not c.get("row"):
            return None
        return ArchivedSession(c, self.store.messages_of(sid))

    def overview(self) -> dict[str, Any]:
        with self.eng.lock:
            live_ids = set(self.eng.sessions)
            rows = [self.row(s) for s in self.eng.sessions.values()]
        if self.store is not None:
            for c in self.store.conversations("clinic"):
                r = c.get("row")
                if c["conv_id"] in live_ids or not r or (not r.get("turns") and not r.get("messages")):
                    continue                       # 질문 없이 끝난 빈 대화는 목록에 올리지 않는다
                rows.append(self._archived_row(ArchivedSession(c, [])))
        rank = dict(danger=0, caution=1, safe=2)
        rows.sort(key=lambda r: (not r["pending_request"], not r["needs_review"], r.get("archived", False), rank[r["status"]], -r["last_active"]))
        kpi = dict(sessions=len(rows), suppressed=sum(r["suppressed"] for r in rows), generalized=sum(r["generalized"] for r in rows),
                   identified=sum(len(r["violated"]) for r in rows), needs_review=sum(r["needs_review"] for r in rows),
                   blocked_sessions=sum(r["status"] == "danger" for r in rows), requests=sum(r["pending_request"] for r in rows))
        return dict(kpi=kpi, sessions=rows, simulations=self.sim_status, live_arm=LIVE_ARM, live_arm_label=ARM_KO[LIVE_ARM],
                    k_req=self.eng.cfg.k_req, suppress_threshold=self.eng.cfg.suppress_threshold,
                    generalize_threshold=self.eng.cfg.generalize_threshold, p_ref=self.eng.ctx["staged"].p_ref)

    # ── 상세 ──
    def detail(self, s: Any, reveal: bool = False) -> dict[str, Any]:
        if getattr(s, "archived", False):
            v = copy.deepcopy(s.db.get("security") or {})
            row = self._archived_row(s)
            msgs = copy.deepcopy(s.messages)
        else:
            with self.eng.lock:
                v = s.security_view()
                row = self.row(s)
                msgs = copy.deepcopy(s.messages)
        if not reveal:
            v = mask(v)
            msgs = mask_messages(msgs)
        return dict(v, row=row, revealed=reveal, source_label=SOURCE_KO.get(s.source, s.source), live_arm=LIVE_ARM, messages=msgs,
                    archived=bool(getattr(s, "archived", False)), assist=self.assist_state(s))

    def reveal(self, s: Any, reason: str, user: dict[str, Any] | None = None) -> dict[str, Any]:
        self.log("reveal", s, user=user, reason=reason)
        return self.detail(s, reveal=True)

    def review(self, s: Any, action: str, note: str | None, user: dict[str, Any] | None = None) -> dict[str, Any]:
        archived = getattr(s, "archived", False)
        check = None
        if action == "ask_clinician":                    # 표시만 하지 않고 의료진 화면에 확인 요청을 보낸다
            if archived:
                raise Conflict("지난 대화의 의료진에게는 확인 요청을 보낼 수 없습니다. '검토 완료'로 표시하세요.")
            check = (note or "").strip() or CHECK_DEFAULT
            if len(check) < 2:                           # 상태를 바꾸기 전에 검사한다 (표시 · 감사 기록만 남고 메시지가 없는 일이 없게)
                raise ValueError("확인 요청은 2자 이상 써 주세요.")
        s.review = dict(action=action, label=REVIEW_KO[action], at=time.time(), actor=actor_label(user, ACTOR), note=note)
        self.log(action, s, user=user, note=note)
        if archived:
            if self.store is not None:
                self.store.save_conversation(s.id, review_json=s.review)
            return self._archived_row(s)
        if check is not None:
            with self.eng.lock:
                case = self.row(s)["focus_case"]
            self.post_message(s, "security", "check_request", check, case, audit=False, user=user)
        else:
            self._changed(s)
        with self.eng.lock:
            return self.row(s)

    # ── 검토 반영: 규칙 · 공개 승인 (review.py) ──
    def add_rule(self, s: Any, case: str, attribute: str, note: str | None, user: dict[str, Any] | None = None) -> dict[str, Any]:
        if getattr(s, "archived", False):
            raise Conflict("지난 대화에는 규칙을 더할 수 없습니다.")
        if getattr(s, "source", None) != "clinic":
            raise Conflict("규칙은 의료진 대화에만 걸 수 있습니다.")
        with self.eng.lock:
            rule = s.add_rule(case, attribute, by=actor_label(user, ACTOR), note=note)
        self.log("add_rule", s, user=user, case=case, attribute=attribute, note=note)
        self._changed(s)
        return rule

    def remove_rule(self, s: Any, rule_id: str, user: dict[str, Any] | None = None) -> dict[str, Any]:
        if getattr(s, "archived", False):
            raise Conflict("지난 대화의 규칙은 바꿀 수 없습니다.")
        with self.eng.lock:
            rule = s.remove_rule(rule_id)
        self.log("remove_rule", s, user=user, case=rule["case"], attribute=rule["attribute"])
        self._changed(s)
        return rule

    def hidden(self, s: Any) -> list[dict[str, Any]]:
        if getattr(s, "archived", False):
            return []
        with self.eng.lock:
            return s.hidden()

    def approve(self, s: Any, conv: Any, item_ids: list[str], reason: str, user: dict[str, Any] | None = None) -> dict[str, Any]:
        """가린 값을 골라 그 의료진의 그 대화에 공개한다. 공개 승인 메시지(값 포함)를 의료진에게 보내고 감사 기록에 남긴다."""
        if getattr(s, "archived", False):
            raise Conflict("지난 대화의 값은 공개할 수 없습니다.")
        if getattr(s, "source", None) != "clinic":
            raise Conflict("의료진 대화의 값만 공개할 수 있습니다.")
        if conv is None:
            raise Conflict("의료진이 이미 다른 환자를 열어, 이 대화에 공개해도 의료진 화면에 보이지 않습니다. 답장으로 안내해 주세요.")
        reason = (reason or "").strip()
        if len(reason) < 5:
            raise ValueError("공개 사유를 5자 이상 써 주세요.")
        with self.eng.lock:
            ap = s.approve(item_ids, by=actor_label(user, ACTOR), reason=reason)
            text = conv.apply_approval(ap)
        case = ap["items"][0]["case"] if len({x["case"] for x in ap["items"]}) == 1 else None
        self.log("approve_release", s, user=user, reason=reason, case=case,
                 items=[dict(turn=x["turn"], case=x["case"], attribute=x["attribute"]) for x in ap["items"]], k_after=ap["k_after"])
        self.post_message(s, "security", "release", text[:2000], case, audit=False, user=user)
        return ap

    # ── 의료진 ↔ 보안 담당자 메시지 ──
    def post_message(self, s: Any, sender: str, kind: str, text: str, case: str | None = None, *,
                     audit: bool = True, user: dict[str, Any] | None = None) -> dict[str, Any]:
        if getattr(s, "archived", False):
            raise Conflict("지난 대화라 메시지를 보낼 수 없습니다 (서버를 다시 켜기 전 대화는 읽기만 합니다).")
        text = (text or "").strip()
        if kind not in MSG_KINDS.get(sender, ()):
            raise ValueError(f"{sender} 메시지 종류는 {', '.join(MSG_KINDS.get(sender, ()))} 중 하나입니다.")
        limit = 2000 if kind == "release" else 500          # 공개 승인은 고른 값을 모두 적는다
        if not 2 <= len(text) <= limit:
            raise ValueError(f"메시지는 2자 이상 {limit}자 이하로 써 주세요.")
        if case is not None and not _CASE_REF.fullmatch(case):
            raise ValueError(f"사례 표시가 올바르지 않습니다: {case}")
        actor = actor_label(user, ACTOR if sender == "security" else CLINICIAN)
        with self._seq_lock:
            n = next(self._mids)
        m = dict(id=f"M{n:04d}", at=time.time(), sender=sender, kind=kind, kind_label=MSG_KIND_KO[kind],
                 case=case, text=text, actor=actor)
        with self.eng.lock:
            s.messages.append(m)
            s.last_active = m["at"]
        if self.store is not None:
            self.store.add_message(s.id, m, n, user["user_id"] if user else None)
        if audit:
            self.log(MSG_AUDIT[(sender, kind)], s, user=user, actor=ACTOR if sender == "security" else CLINICIAN, note=text, case=case)
        self._changed(s)
        if sender == "clinician" and kind == "access_request" and self.assistant is not None and getattr(s, "source", None) == "clinic":
            try:
                self.assistant.schedule(s, m)           # 검토 초안은 뒤에서 만든다 (요청 응답은 기다리지 않는다)
            except Exception as exc:
                print(f"[medicloak] 검토 보조를 시작하지 못했습니다: {type(exc).__name__}: {exc}")
        return m

    # ── 검토 보조 (assist.py) ──
    def assist_state(self, s: Any) -> dict[str, Any]:
        if getattr(s, "archived", False) or self.assistant is None:
            return dict(status="none")
        return self.assistant.state(s)

    def assist_run(self, s: Any) -> dict[str, Any]:
        if getattr(s, "archived", False):
            raise Conflict("지난 대화에는 검토 초안을 만들 수 없습니다.")
        if self.assistant is None or getattr(s, "source", None) != "clinic":
            raise Conflict("검토 초안은 의료진 대화의 세부 정보 요청에만 만듭니다.")
        try:
            return self.assistant.schedule(s)
        except LookupError as exc:
            raise Conflict(str(exc)) from exc

    def thread(self, s: Any) -> dict[str, Any]:
        """관제 화면의 메시지 목록 (공개 승인 메시지의 값은 지운다. 값은 사유를 남긴 열람의 상세에서 본다)."""
        if getattr(s, "archived", False):
            return dict(messages=mask_messages(s.messages), row=self._archived_row(s))
        with self.eng.lock:
            return dict(messages=mask_messages(s.messages), row=self.row(s))


def mask(view: dict[str, Any]) -> dict[str, Any]:
    """원 응답, 가리거나 넓힌 원래 값, 환자 번호, 비교 조건의 답을 지운다. 의료진 화면에 나간 답(C1 released)만 남긴다."""
    v = copy.deepcopy(view)
    v["patient"] = None
    for r in v.get("retrieval", []):
        r["patient"] = None
    for name, a in (v.get("arms") or {}).items():
        for val in a.get("validation", {}).values():
            val["patient"] = None
        for t in a["turns"]:
            t["raw"] = None
            if name != LIVE_ARM:                        # 비교 조건(방어 없음 등)의 답에는 원래 값이 그대로 있다
                t["released"] = None
                for ln in t.get("lines", []) + t.get("raw_lines", []):
                    if "case" in ln:
                        ln["value"] = None
                    elif "text" in ln:                  # 실제 LLM 답은 '사례N · 항목: 값' 줄 모양이 아니라 글 그대로다
                        ln["text"] = None
            changed = {(ln.get("case"), ln.get("field")) for ln in t.get("lines", []) if ln.get("change")}
            for ln in t.get("raw_lines", []):
                if (ln.get("case"), ln.get("field")) in changed:
                    ln["value"] = None
                elif name == LIVE_ARM and "text" in ln and "case" not in ln:
                    ln["text"] = None                   # 원 응답 줄 (글 그대로인 줄에는 가린 값이 섞여 있을 수 있다)
            for p in t.get("decisions", []):
                for it in p["items"]:
                    if it["action"] != "allow":
                        it["raw_value"] = None
    for ap in v.get("approvals") or []:                 # 승인해 공개한 값도 열람 전에는 지운다 (의료진에게는 나갔다)
        for it in ap["items"]:
            it["value"] = None
    return v
