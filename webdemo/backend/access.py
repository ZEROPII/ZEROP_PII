# EMR 접근 관리 (운영 모드): 담당 배정 · 담당 외 예외 열람 · 차트 접근 기록 (ADR-0034)
#
#   담당 배정   외래 환자마다 담당 의료진(한 명 이상). 처음에는 규칙으로 나눈다: 환자 번호 순서대로, 담당 환자가 가장 적은
#              의료진 계정에 하나씩 (같으면 먼저 만든 계정). 서버를 켤 때 담당이 없는 외래 환자가 있으면 같은 규칙으로 채운다.
#              바꾸기는 명령으로: python -m medicloak assign add|remove|auto (cli.py). 바꾼 일은 감사 기록에 남는다.
#   예외 열람   담당이 아닌 환자는 목록에 나오지 않는다. 협진 · 당직처럼 꼭 봐야 하면 환자 번호와 사유(분류 + 직접 쓴 설명)를 적어
#              GRANT_HOURS시간 동안 연다 (break-glass). 연 일은 감사 기록과 접근 기록에 남고, 보안 담당자가 사후 검토한다.
#              serve --break-glass off면 열 수 없다 (담당 환자만).
#   접근 기록   차트 열람 · 진료 지원 AI 열기 · 거부 · 예외 열람 · 보안 담당자 열람을 환자마다 남긴다 (emr_access).
#              감사 기록(audit)에는 보안에 중요한 일(거부 · 예외 열람 · 검토 · 보안 담당자 열람 · 배정 변경)만 같이 남긴다.
#
# 환자 번호(fhir_id)는 보안 담당자 화면에 그대로 내보내지 않는다. 화면은 기호(P-xxxxxx, monitor.tag)로만 보이고,
# 차트와 번호는 사유를 적은 열람 때만 보인다.

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from typing import Any, Iterable

from medical.data import QUERY_POOL
from webdemo.backend.store import Store

GRANT_HOURS = 12.0
NOTE_MIN = 5                       # 직접 쓴 사유 설명의 최소 글자 수
REASON_KO = {"consult": "협진", "on_call": "당직 · 응급", "other": "기타"}
REVIEW_KO = {"ok": "적절함", "flag": "확인 필요 (열람 끝냄)"}
ACTION_KO = {"chart": "차트 열람", "fhir": "EMR 연동(FHIR) 조회", "launch": "진료 지원 AI 열기", "denied": "담당 외라 막음",
             "break_glass": "예외 열람 시작", "reveal": "보안 담당자 차트 열람"}
VIA_KO = {"assigned": "담당", "break_glass": "예외 열람", "security": "보안 담당자"}
FHIR_DEDUP = 600.0                 # 같은 의료진이 같은 환자를 FHIR로 이 초 안에 또 읽으면 한 번으로 센다
AUTO_ACTOR = "담당 배정 규칙 (자동)"
NUMBER = re.compile(r"^[0-9a-f]{8}([0-9a-f-]{0,28})$")


class NotAssigned(Exception):
    """담당 환자도 아니고 예외 열람 중도 아니다."""


def tag_key(store: Store) -> bytes:
    """환자 기호를 만드는 비밀 열쇠 (DB meta에 한 번 만들어 둔다. 서버와 명령줄이 같은 열쇠를 쓴다)."""
    k = store.get_meta("subject_tag_key")
    if not k:
        k = secrets.token_hex(16)
        store.set_meta("subject_tag_key", k)
    return k.encode()


def subject_tag(key: bytes, number: str) -> str:
    """환자 번호(앞 8자리) → 기호 'P-3f9a1c'. 같은 번호는 늘 같은 기호, 기호만으로는 번호를 알 수 없다 (monitor.tag)."""
    return "P-" + hmac.new(key, str(number)[:8].encode(), hashlib.sha256).hexdigest()[:6]


def write_audit(store: Store, action: str, actor: str, **kw: Any) -> dict[str, Any]:
    """서버 밖(명령줄)에서 감사 기록 한 건. 켜 둔 서버와 번호가 겹치면 마지막 번호 다음으로 다시 쓴다."""
    for _ in range(5):
        n = store.max_seq("audit") + 1
        e = dict(id=f"A{n:04d}", at=time.time(), actor=actor, action=action, session=None, trial=None, **kw)
        try:
            store.add_audit(e, n)
            return e
        except sqlite3.IntegrityError:
            continue
    raise RuntimeError("감사 기록을 쓰지 못했습니다 (번호가 계속 겹칩니다).")


class EmrAccess:
    def __init__(self, store: Store, *, break_glass: bool = True, hours: float = GRANT_HOURS) -> None:
        self.store = store
        self.break_glass = break_glass
        self.hours = hours

    # ── 대상 ──
    def outpatients(self) -> list[str]:
        return [r["fhir_id"] for r in self.store.q("SELECT fhir_id FROM emr_patient WHERE cohort = ? ORDER BY fhir_id", (QUERY_POOL,))]

    def is_outpatient(self, fhir_id: str) -> bool:
        return self.store.one("SELECT 1 FROM emr_patient WHERE fhir_id = ? AND cohort = ?", (fhir_id, QUERY_POOL)) is not None

    def resolve(self, number: str) -> str | None:
        """화면의 환자 번호(앞 8자리) 또는 전체 id → 외래 환자 id. 외래 환자가 아니거나 여럿이 맞으면 None."""
        n = (number or "").strip().lower()
        if not NUMBER.match(n):
            return None
        rows = self.store.q("SELECT fhir_id FROM emr_patient WHERE cohort = ? AND fhir_id LIKE ? LIMIT 2", (QUERY_POOL, n + "%"))
        return rows[0]["fhir_id"] if len(rows) == 1 else None

    def clinicians(self) -> list[Any]:
        return self.store.q("SELECT * FROM app_user WHERE role = 'clinician' AND active = 1 ORDER BY user_id")

    # ── 담당 배정 ──
    def fill(self, *, reset: bool = False, by: str = AUTO_ACTOR) -> dict[str, Any]:
        """
        담당이 없는 외래 환자를 규칙으로 나눈다 (reset이면 모두 지우고 처음부터). 환자 번호 순서대로, 지금 담당 환자가 가장 적은
        의료진 계정에 (같으면 먼저 만든 계정). 반환: 새로 배정한 수와 계정마다 담당 수.
        """
        docs = self.clinicians()
        if not docs:
            return dict(assigned=0, counts={})
        now = time.time()
        conn = self.store.conn
        with self.store.lock:                      # 지우기와 다시 채우기를 한 트랜잭션으로 (켜 둔 서버가 빈 배정을 보지 않게)
            conn.execute("BEGIN IMMEDIATE")
            try:
                if reset:
                    conn.execute("DELETE FROM emr_assignment")
                have = {r["fhir_id"] for r in conn.execute("SELECT DISTINCT fhir_id FROM emr_assignment")}
                load = {d["user_id"]: 0 for d in docs}
                for r in conn.execute("SELECT user_id, COUNT(*) AS n FROM emr_assignment GROUP BY user_id"):
                    if r["user_id"] in load:
                        load[r["user_id"]] = r["n"]
                rows = []
                for fid in self.outpatients():
                    if fid in have:
                        continue
                    uid = min(load, key=lambda u: (load[u], u))
                    load[uid] += 1
                    rows.append((fid, uid, now, by))
                conn.executemany("INSERT INTO emr_assignment (fhir_id, user_id, assigned_at, assigned_by) VALUES (?, ?, ?, ?)", rows)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        names = {d["user_id"]: d["username"] for d in docs}
        return dict(assigned=len(rows), counts={names[u]: n for u, n in load.items()})

    def assign(self, fhir_id: str, user_id: int, by: str) -> bool:
        """담당 의료진을 더한다. 이미 담당이면 False."""
        cur = self.store.x("INSERT OR IGNORE INTO emr_assignment (fhir_id, user_id, assigned_at, assigned_by) VALUES (?, ?, ?, ?)",
                           (fhir_id, user_id, time.time(), by))
        return cur.rowcount > 0

    def unassign(self, fhir_id: str, user_id: int) -> bool:
        return self.store.x("DELETE FROM emr_assignment WHERE fhir_id = ? AND user_id = ?", (fhir_id, user_id)).rowcount > 0

    def assigned_ids(self, user_id: int) -> set[str]:
        return {r["fhir_id"] for r in self.store.q("SELECT fhir_id FROM emr_assignment WHERE user_id = ?", (user_id,))}

    def team(self) -> dict[str, list[dict[str, Any]]]:
        """외래 환자 → 담당 의료진 [{username, displayName, department}] (먼저 배정한 순)."""
        out: dict[str, list[dict[str, Any]]] = {}
        for r in self.store.q("SELECT a.fhir_id, u.username, u.display_name, u.department FROM emr_assignment a "
                              "JOIN app_user u ON u.user_id = a.user_id ORDER BY a.assigned_at, u.user_id"):
            out.setdefault(r["fhir_id"], []).append(dict(username=r["username"], displayName=r["display_name"], department=r["department"]))
        return out

    def counts(self) -> list[dict[str, Any]]:
        """의료진 계정마다 담당 환자 수 (중지한 계정도 담당이 남아 있으면 보인다)."""
        rows = self.store.q("SELECT u.user_id, u.username, u.display_name, u.department, u.active, COUNT(a.fhir_id) AS n FROM app_user u "
                            "LEFT JOIN emr_assignment a ON a.user_id = u.user_id WHERE u.role = 'clinician' GROUP BY u.user_id ORDER BY u.user_id")
        return [dict(username=r["username"], displayName=r["display_name"], department=r["department"], active=bool(r["active"]),
                     assigned=r["n"]) for r in rows if r["active"] or r["n"]]

    # ── 예외 열람 (break-glass) ──
    def _grant(self, r: Any, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        active = r["ended_at"] is None and r["expires_at"] > now
        return dict(id=r["grant_id"], fhirId=r["fhir_id"], userId=r["user_id"], reason=r["reason"], reasonLabel=REASON_KO.get(r["reason"], r["reason"]),
                    note=r["note"], createdAt=r["created_at"], expiresAt=r["expires_at"], endedAt=r["ended_at"], active=active,
                    review=r["review"], reviewLabel=REVIEW_KO.get(r["review"] or "", None), reviewNote=r["review_note"],
                    reviewedAt=r["reviewed_at"], reviewedBy=r["reviewed_by"])

    def active_grants(self, user_id: int) -> dict[str, dict[str, Any]]:
        """이 의료진이 지금 열 수 있는 예외 열람 (환자 → 가장 늦게 끝나는 것)."""
        now = time.time()
        out: dict[str, dict[str, Any]] = {}
        for r in self.store.q("SELECT * FROM emr_grant WHERE user_id = ? AND ended_at IS NULL AND expires_at > ? ORDER BY expires_at",
                              (user_id, now)):
            out[r["fhir_id"]] = self._grant(r, now)
        return out

    def open_grant(self, user_id: int, fhir_id: str, reason: str, note: str) -> tuple[dict[str, Any], bool]:
        """예외 열람을 연다. 같은 환자를 이미 열어 두었으면 그것을 돌려준다 (새로 만들지 않음). 반환: (열람, 새로 만들었는지)."""
        if not self.break_glass:
            raise PermissionError("이 서버에서는 담당이 아닌 환자를 열 수 없습니다 (--break-glass off).")
        if reason not in REASON_KO:
            raise ValueError(f"사유 분류는 {', '.join(REASON_KO.values())} 중 하나입니다.")
        note = (note or "").strip()
        if len(note) < NOTE_MIN:
            raise ValueError(f"여는 이유를 한 줄로 써 주세요 ({NOTE_MIN}자 이상).")
        cur = self.active_grants(user_id).get(fhir_id)
        if cur is not None:
            return cur, False
        now = time.time()
        gid = self.store.x("INSERT INTO emr_grant (fhir_id, user_id, reason, note, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                           (fhir_id, user_id, reason, note[:300], now, now + self.hours * 3600)).lastrowid
        return self.grant(gid), True

    def grant(self, grant_id: int) -> dict[str, Any] | None:
        r = self.store.one("SELECT * FROM emr_grant WHERE grant_id = ?", (grant_id,))
        return self._grant(r) if r is not None else None

    def grants(self, *, fhir_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        """예외 열람 목록, 검토하지 않은 것 먼저, 그다음 최근 것부터. 의료진 이름을 붙인다."""
        where, args = ("WHERE g.fhir_id = ?", [fhir_id]) if fhir_id else ("", [])
        rows = self.store.q(f"SELECT g.*, u.username, u.display_name, u.department FROM emr_grant g JOIN app_user u ON u.user_id = g.user_id {where} "
                            f"ORDER BY (g.review IS NOT NULL), g.created_at DESC LIMIT ?", [*args, limit])
        now = time.time()
        return [dict(self._grant(r, now), username=r["username"], displayName=r["display_name"], department=r["department"]) for r in rows]

    def review(self, grant_id: int, action: str, note: str | None, by: str) -> dict[str, Any]:
        """보안 담당자 사후 검토. flag(확인 필요)는 열람을 바로 끝낸다."""
        if action not in REVIEW_KO:
            raise ValueError(f"검토는 {', '.join(REVIEW_KO)} 중 하나입니다.")
        g = self.grant(grant_id)
        if g is None:
            raise KeyError(grant_id)
        now = time.time()
        end = now if action == "flag" and g["endedAt"] is None and g["expiresAt"] > now else g["endedAt"]
        self.store.x("UPDATE emr_grant SET review = ?, review_note = ?, reviewed_at = ?, reviewed_by = ?, ended_at = ? WHERE grant_id = ?",
                     (action, (note or "").strip()[:300] or None, now, by, end, grant_id))
        return self.grant(grant_id)  # type: ignore[return-value]

    def pending(self) -> int:
        return self.store.one("SELECT COUNT(*) AS n FROM emr_grant WHERE review IS NULL")["n"]

    # ── 판단 ──
    def via(self, user_id: int, fhir_id: str) -> tuple[str, dict[str, Any] | None] | None:
        """('assigned', None) · ('break_glass', 열람) · 둘 다 아니면 None. 서버가 예외 열람을 끄면 연 것도 쓰지 않는다."""
        if self.store.one("SELECT 1 FROM emr_assignment WHERE fhir_id = ? AND user_id = ?", (fhir_id, user_id)) is not None:
            return "assigned", None
        if self.break_glass:
            g = self.active_grants(user_id).get(fhir_id)
            if g is not None:
                return "break_glass", g
        return None

    def visible(self, user_id: int) -> dict[str, tuple[str, dict[str, Any] | None]]:
        """이 의료진의 목록에 나올 환자 → (담당 · 예외 열람, 열람)."""
        out: dict[str, tuple[str, dict[str, Any] | None]] = {f: ("assigned", None) for f in self.assigned_ids(user_id)}
        if self.break_glass:
            for f, g in self.active_grants(user_id).items():
                out.setdefault(f, ("break_glass", g))
        return out

    # ── 접근 기록 ──
    def record(self, user_id: int | None, fhir_id: str, action: str, *, via: str | None = None, grant_id: int | None = None,
               detail: str | None = None, dedup: float | None = None) -> bool:
        """한 건 남긴다. dedup초 안에 같은 의료진 · 환자 · 일 · 내용이 있으면 남기지 않는다 (False)."""
        now = time.time()
        detail = (detail or None) and detail[:300]
        with self.store.lock:
            if dedup and self.store.one("SELECT 1 FROM emr_access WHERE user_id IS ? AND fhir_id = ? AND action = ? AND detail IS ? AND at > ?",
                                        (user_id, fhir_id, action, detail, now - dedup)) is not None:
                return False
            self.store.x("INSERT INTO emr_access (at, user_id, fhir_id, action, via, grant_id, detail) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (now, user_id, fhir_id, action, via, grant_id, detail))
        return True

    def history(self, fhir_id: str, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.store.q("SELECT x.*, u.username, u.display_name, u.role FROM emr_access x LEFT JOIN app_user u ON u.user_id = x.user_id "
                            "WHERE x.fhir_id = ? ORDER BY x.at DESC, x.access_id DESC LIMIT ?", (fhir_id, limit))
        return [self._event(r) for r in rows]

    @staticmethod
    def _event(r: Any) -> dict[str, Any]:
        return dict(at=r["at"], action=r["action"], actionLabel=ACTION_KO.get(r["action"], r["action"]), via=r["via"],
                    viaLabel=VIA_KO.get(r["via"] or "", None), grantId=r["grant_id"], detail=r["detail"],
                    username=r["username"], displayName=r["display_name"], role=r["role"])

    def stats(self, since: float) -> dict[str, dict[str, Any]]:
        """환자마다: 마지막 접근(누가 · 무엇을), since 뒤 접근 수 · 거부 수."""
        out: dict[str, dict[str, Any]] = {}
        for r in self.store.q("SELECT fhir_id, COUNT(*) AS n, SUM(action = 'denied') AS denied FROM emr_access WHERE at > ? GROUP BY fhir_id", (since,)):
            out[r["fhir_id"]] = dict(recent=r["n"], denied=r["denied"] or 0, last=None)
        for r in self.store.q("SELECT x.*, u.username, u.display_name, u.role FROM emr_access x LEFT JOIN app_user u ON u.user_id = x.user_id "
                              "WHERE x.access_id IN (SELECT MAX(access_id) FROM emr_access GROUP BY fhir_id)"):
            out.setdefault(r["fhir_id"], dict(recent=0, denied=0, last=None))["last"] = self._event(r)
        return out

    def count_since(self, since: float, actions: Iterable[str]) -> int:
        acts = list(actions)
        return self.store.one(f"SELECT COUNT(*) AS n FROM emr_access WHERE at > ? AND action IN ({', '.join('?' for _ in acts)})",
                              [since, *acts])["n"]

    def describe(self) -> dict[str, Any]:
        """보호 정책 화면 · 상태 점검용."""
        return dict(on=True, breakGlass=self.break_glass, grantHours=self.hours, outpatients=len(self.outpatients()),
                    unassigned=self.store.one("SELECT COUNT(*) AS n FROM emr_patient p WHERE p.cohort = ? AND NOT EXISTS "
                                              "(SELECT 1 FROM emr_assignment a WHERE a.fhir_id = p.fhir_id)", (QUERY_POOL,))["n"],
                    clinicians=self.counts(), pendingReview=self.pending())
