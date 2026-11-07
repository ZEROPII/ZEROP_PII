# MediCloak 저장소 (SQLite 파일 하나). 서버를 다시 켜도 남아야 하는 것을 둔다.
#
#   가상 EMR   emr_node(온톨로지 노드) · emr_patient(환자) · emr_event(진료 사건). Synthea 합성 데이터를 CSV에서 옮긴다 (emr.py)
#   계정       app_user · auth_session (비밀번호는 PBKDF2 해시, 세션은 토큰의 SHA-256만 저장)
#   기록       conversation(의료진 대화 스냅숏) · turn_record(턴 기록, 원 응답 포함 · 서버 안에서만)
#              thread_message(의료진 ↔ 보안 담당자) · audit(감사 기록)
#   공개 원장  disclosure_ledger: 과거 환자마다 의료진 대화가 내보낸 단서(노드)와 대화 · 계정 · 시각 (ledger.py, ADR-0032)
#   EMR 접근   emr_assignment(외래 환자 ↔ 담당 의료진) · emr_grant(담당 외 예외 열람, 사유 · 기한 · 검토) ·
#              emr_access(차트 열람 · 거부 등 접근 기록) (access.py, ADR-0034)
#              emr_regno(외래 환자 등록번호 '26-4821') · emr_consult(담당 의료진이 보낸 협진 의뢰) (access.py, ADR-0036)
#
# 쓰기는 연결 하나를 잠금으로 줄 세운다. 데모 · 시범 운영 규모(동시 사용자 수십 명)에서 충분하다.
# 원 응답과 가린 원래 값은 turn_record · conversation.security_json에만 있고, 이 값은 보안 담당자 API에서도
# 사유를 남긴 열람(reveal) 때만 내보낸다 (monitor.mask).

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS emr_node (
  node_id TEXT PRIMARY KEY, attribute TEXT, canonical_label TEXT, parent_id TEXT, depth TEXT, review_status TEXT,
  standard_code TEXT, time_role TEXT, calendar_basis TEXT, level TEXT, k_patients TEXT, seq INTEGER
);
CREATE TABLE IF NOT EXISTS emr_patient (
  patient_id TEXT PRIMARY KEY, fhir_id TEXT UNIQUE, sex_node TEXT, region_node TEXT, birth_year INTEGER,
  cohort TEXT, n_events INTEGER
);
CREATE TABLE IF NOT EXISTS emr_event (
  event_id TEXT PRIMARY KEY, patient_id TEXT, event_type TEXT, encounter_id TEXT, code TEXT, code_node TEXT, start TEXT,
  stop TEXT, time_basis TEXT, period_start_node TEXT, period_end_node TEXT, age_years_at_start TEXT, age_node TEXT,
  sex_node TEXT, region_node TEXT, code_nodes TEXT, map_trace TEXT, record_date TEXT, context TEXT, seq INTEGER
);
CREATE INDEX IF NOT EXISTS emr_event_patient ON emr_event (patient_id, event_type);

CREATE TABLE IF NOT EXISTS app_user (
  user_id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('clinician', 'security')), department TEXT,
  pw_salt TEXT NOT NULL, pw_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at REAL
);
CREATE TABLE IF NOT EXISTS auth_session (
  token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES app_user(user_id),
  created_at REAL, expires_at REAL, last_seen REAL
);

CREATE TABLE IF NOT EXISTS conversation (
  conv_id TEXT PRIMARY KEY, user_id INTEGER, owner_label TEXT, source TEXT, trial_id TEXT, patient_fhir_id TEXT,
  llm_mode TEXT, started_at REAL, last_active REAL, turns INTEGER DEFAULT 0, review_json TEXT,
  row_json TEXT, security_json TEXT, clinic_json TEXT
);
CREATE TABLE IF NOT EXISTS turn_record (
  conv_id TEXT, arm TEXT, turn INTEGER, at REAL, record_json TEXT, PRIMARY KEY (conv_id, arm, turn)
);
CREATE TABLE IF NOT EXISTS thread_message (
  msg_id TEXT PRIMARY KEY, seq INTEGER, conv_id TEXT, at REAL, sender TEXT, kind TEXT, kind_label TEXT,
  case_ref TEXT, text TEXT, actor TEXT, user_id INTEGER
);
CREATE INDEX IF NOT EXISTS thread_message_conv ON thread_message (conv_id, seq);
CREATE TABLE IF NOT EXISTS audit (
  audit_id TEXT PRIMARY KEY, seq INTEGER, at REAL, user_id INTEGER, actor TEXT, action TEXT, conv_id TEXT, trial TEXT,
  detail_json TEXT
);
CREATE TABLE IF NOT EXISTS redteam_run (
  job_id TEXT PRIMARY KEY, started_at REAL, finished_at REAL, status TEXT, job_json TEXT
);
CREATE TABLE IF NOT EXISTS disclosure_ledger (
  entry_id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT NOT NULL, conv_id TEXT, user_id INTEGER, at REAL,
  kind TEXT, turn INTEGER, attribute TEXT, node_id TEXT, event_label TEXT
);
CREATE INDEX IF NOT EXISTS disclosure_ledger_patient ON disclosure_ledger (patient_id, at);
CREATE TABLE IF NOT EXISTS emr_assignment (
  fhir_id TEXT NOT NULL, user_id INTEGER NOT NULL REFERENCES app_user(user_id), assigned_at REAL, assigned_by TEXT,
  PRIMARY KEY (fhir_id, user_id)
);
CREATE INDEX IF NOT EXISTS emr_assignment_user ON emr_assignment (user_id);
CREATE TABLE IF NOT EXISTS emr_grant (
  grant_id INTEGER PRIMARY KEY AUTOINCREMENT, fhir_id TEXT NOT NULL, user_id INTEGER NOT NULL REFERENCES app_user(user_id),
  reason TEXT NOT NULL, note TEXT, created_at REAL NOT NULL, expires_at REAL NOT NULL, ended_at REAL,
  review TEXT, review_note TEXT, reviewed_at REAL, reviewed_by TEXT, consult_id INTEGER
);
CREATE INDEX IF NOT EXISTS emr_grant_user ON emr_grant (user_id, expires_at);
CREATE TABLE IF NOT EXISTS emr_regno (
  fhir_id TEXT PRIMARY KEY, regno TEXT NOT NULL UNIQUE, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS emr_consult (
  consult_id INTEGER PRIMARY KEY AUTOINCREMENT, fhir_id TEXT NOT NULL, from_user INTEGER NOT NULL REFERENCES app_user(user_id),
  to_user INTEGER NOT NULL REFERENCES app_user(user_id), note TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', opened_at REAL, closed_at REAL, close_note TEXT
);
CREATE INDEX IF NOT EXISTS emr_consult_to ON emr_consult (to_user, status);
CREATE INDEX IF NOT EXISTS emr_consult_from ON emr_consult (from_user, created_at);
CREATE TABLE IF NOT EXISTS emr_access (
  access_id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, user_id INTEGER, fhir_id TEXT NOT NULL, action TEXT NOT NULL,
  via TEXT, grant_id INTEGER, detail TEXT
);
CREATE INDEX IF NOT EXISTS emr_access_patient ON emr_access (fhir_id, at);
CREATE INDEX IF NOT EXISTS emr_access_user ON emr_access (user_id, fhir_id, action, at);
"""


def _default(o: Any) -> Any:
    if isinstance(o, (set, frozenset)):
        return sorted(o, key=str)
    return str(o)


def _dumps(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False, default=_default)


class Store:
    def __init__(self, path: Path | str = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=30)
        self.conn.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            self._add_columns()
        if self.get_meta("schema_version") is None:
            self.set_meta("schema_version", SCHEMA_VERSION)

    #: 나중에 더한 칸 (이미 있는 DB 파일에는 ALTER TABLE로 붙인다. CREATE TABLE IF NOT EXISTS는 있는 표를 바꾸지 않는다)
    ADDED_COLUMNS = {"emr_grant": [("consult_id", "INTEGER")]}

    def _add_columns(self) -> None:
        for table, cols in self.ADDED_COLUMNS.items():
            have = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            for name, typ in cols:
                if name not in have:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")

    # ── 기본 ──
    def q(self, sql: str, args: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, tuple(args)).fetchall()

    def one(self, sql: str, args: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self.lock:
            return self.conn.execute(sql, tuple(args)).fetchone()

    def x(self, sql: str, args: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self.lock:
            return self.conn.execute(sql, tuple(args))

    def many(self, sql: str, rows: Iterable[Iterable[Any]]) -> None:
        with self.lock:
            self.conn.execute("BEGIN")
            try:
                self.conn.executemany(sql, rows)
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def close(self) -> None:
        with self.lock:
            self.conn.close()

    def get_meta(self, key: str) -> str | None:
        r = self.one("SELECT value FROM meta WHERE key = ?", (key,))
        return r["value"] if r else None

    def set_meta(self, key: str, value: str) -> None:
        self.x("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    def count(self, table: str) -> int:
        return self.one(f"SELECT COUNT(*) AS n FROM {table}")["n"]          # table은 코드 안 상수만 넘긴다

    # ── 계정 ──
    def add_user(self, username: str, display_name: str, role: str, department: str | None, salt: str, pw_hash: str) -> int:
        cur = self.x("INSERT INTO app_user (username, display_name, role, department, pw_salt, pw_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (username, display_name, role, department, salt, pw_hash, time.time()))
        return int(cur.lastrowid)

    def set_password(self, username: str, salt: str, pw_hash: str) -> bool:
        return self.x("UPDATE app_user SET pw_salt = ?, pw_hash = ? WHERE username = ?", (salt, pw_hash, username)).rowcount > 0

    def user_by_name(self, username: str) -> sqlite3.Row | None:
        return self.one("SELECT * FROM app_user WHERE username = ?", (username,))

    def user_by_id(self, user_id: int) -> sqlite3.Row | None:
        return self.one("SELECT * FROM app_user WHERE user_id = ?", (user_id,))

    def users(self) -> list[sqlite3.Row]:
        return self.q("SELECT * FROM app_user ORDER BY role, user_id")

    # ── 로그인 세션 ──
    def add_session(self, token_hash: str, user_id: int, ttl: float) -> None:
        now = time.time()
        self.x("INSERT INTO auth_session (token_hash, user_id, created_at, expires_at, last_seen) VALUES (?, ?, ?, ?, ?)",
               (token_hash, user_id, now, now + ttl, now))

    def session_user(self, token_hash: str, idle: float | None = None) -> sqlite3.Row | None:
        """유효한 세션의 사용자. idle을 주면 그 초 동안 쓰지 않은 세션도 끝난 것으로 본다."""
        now = time.time()
        return self.one("SELECT u.*, s.expires_at, s.last_seen FROM auth_session s JOIN app_user u ON u.user_id = s.user_id "
                        "WHERE s.token_hash = ? AND s.expires_at > ? AND s.last_seen > ? AND u.active = 1",
                        (token_hash, now, now - idle if idle else 0))

    def touch_session(self, token_hash: str) -> None:
        self.x("UPDATE auth_session SET last_seen = ? WHERE token_hash = ?", (time.time(), token_hash))

    def drop_session(self, token_hash: str) -> None:
        self.x("DELETE FROM auth_session WHERE token_hash = ?", (token_hash,))

    def purge_sessions(self, idle: float | None = None) -> None:
        now = time.time()
        self.x("DELETE FROM auth_session WHERE expires_at <= ? OR last_seen <= ?", (now, now - idle if idle else 0))

    # ── 감사 기록 ──
    def add_audit(self, e: dict[str, Any], seq: int) -> None:
        detail = {k: v for k, v in e.items() if k not in ("id", "at", "user_id", "actor", "action", "session", "trial")}
        self.x("INSERT INTO audit (audit_id, seq, at, user_id, actor, action, conv_id, trial, detail_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
               (e["id"], seq, e["at"], e.get("user_id"), e["actor"], e["action"], e.get("session"), e.get("trial"), _dumps(detail)))

    def audit_entries(self, limit: int | None = None) -> list[dict[str, Any]]:
        """오래된 것부터. limit을 주면 최근 limit건만."""
        out = []
        rows = self.q("SELECT * FROM (SELECT * FROM audit ORDER BY seq DESC LIMIT ?) ORDER BY seq", (limit if limit else -1,))
        for r in rows:
            out.append(dict(json.loads(r["detail_json"] or "{}"), id=r["audit_id"], at=r["at"], user_id=r["user_id"], actor=r["actor"],
                            action=r["action"], session=r["conv_id"], trial=r["trial"]))
        return out

    def max_seq(self, table: str) -> int:
        r = self.one(f"SELECT MAX(seq) AS m FROM {table}")                 # table은 코드 안 상수만 넘긴다
        return int(r["m"] or 0)

    # ── 메시지 ──
    def add_message(self, conv_id: str, m: dict[str, Any], seq: int, user_id: int | None) -> None:
        self.x("INSERT INTO thread_message (msg_id, seq, conv_id, at, sender, kind, kind_label, case_ref, text, actor, user_id) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
               (m["id"], seq, conv_id, m["at"], m["sender"], m["kind"], m["kind_label"], m.get("case"), m["text"], m["actor"], user_id))

    def messages_of(self, conv_id: str) -> list[dict[str, Any]]:
        return [dict(id=r["msg_id"], at=r["at"], sender=r["sender"], kind=r["kind"], kind_label=r["kind_label"], case=r["case_ref"],
                     text=r["text"], actor=r["actor"]) for r in self.q("SELECT * FROM thread_message WHERE conv_id = ? ORDER BY seq", (conv_id,))]

    # ── 레드팀 실행 (실제 LLM 점검 결과는 다시 켜도 리포트에 남긴다) ──
    def save_run(self, job: dict[str, Any]) -> None:
        self.x("INSERT OR REPLACE INTO redteam_run (job_id, started_at, finished_at, status, job_json) VALUES (?, ?, ?, ?, ?)",
               (job["id"], job.get("started_at"), job.get("finished_at"), job["status"], _dumps(job)))

    def runs(self) -> list[dict[str, Any]]:
        return [json.loads(r["job_json"]) for r in self.q("SELECT job_json FROM redteam_run ORDER BY started_at")]

    # ── 공개 원장 (ledger.py) ──
    _LEDGER_COLS = ("patient_id", "conv_id", "user_id", "at", "kind", "turn", "attribute", "node_id", "event_label")

    def add_ledger(self, rows: list[dict[str, Any]]) -> None:
        self.many(f"INSERT INTO disclosure_ledger ({', '.join(self._LEDGER_COLS)}) VALUES ({', '.join('?' for _ in self._LEDGER_COLS)})",
                  [tuple(r.get(c) for c in self._LEDGER_COLS) for r in rows])

    def ledger_entries(self, since: float | None = None) -> list[dict[str, Any]]:
        """오래된 것부터. since를 주면 그 시각 뒤의 기록만."""
        rows = self.q("SELECT * FROM disclosure_ledger" + (" WHERE at >= ?" if since is not None else "") + " ORDER BY entry_id",
                      (since,) if since is not None else ())
        return [{c: r[c] for c in self._LEDGER_COLS} for r in rows]

    def set_ledger_user(self, conv_id: str, user_id: int) -> None:
        self.x("UPDATE disclosure_ledger SET user_id = ? WHERE conv_id = ? AND user_id IS NULL", (user_id, conv_id))

    # ── 대화 ──
    def save_conversation(self, conv_id: str, **cols: Any) -> None:
        """있으면 고치고 없으면 만든다. *_json 열은 dict를 받아 JSON으로 넣는다."""
        cols = {k: (_dumps(v) if k.endswith("_json") and v is not None else v) for k, v in cols.items()}
        with self.lock:
            exists = self.conn.execute("SELECT 1 FROM conversation WHERE conv_id = ?", (conv_id,)).fetchone()
            if exists:
                if cols:
                    sets = ", ".join(f"{k} = ?" for k in cols)
                    self.conn.execute(f"UPDATE conversation SET {sets} WHERE conv_id = ?", (*cols.values(), conv_id))
            else:
                names = ["conv_id", *cols]
                self.conn.execute(f"INSERT INTO conversation ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
                                  (conv_id, *cols.values()))

    def conversation(self, conv_id: str) -> dict[str, Any] | None:
        r = self.one("SELECT * FROM conversation WHERE conv_id = ?", (conv_id,))
        return _conv(r) if r else None

    def conversations(self, source: str | None = None) -> list[dict[str, Any]]:
        rows = self.q("SELECT * FROM conversation" + (" WHERE source = ?" if source else "") + " ORDER BY started_at", (source,) if source else ())
        return [_conv(r) for r in rows]

    def add_turn(self, conv_id: str, arm: str, turn: int, rec: dict[str, Any]) -> None:
        self.x("INSERT OR REPLACE INTO turn_record (conv_id, arm, turn, at, record_json) VALUES (?, ?, ?, ?, ?)",
               (conv_id, arm, turn, time.time(), _dumps(rec)))

    def turns_of(self, conv_id: str, arm: str) -> list[dict[str, Any]]:
        return [json.loads(r["record_json"]) for r in self.q("SELECT record_json FROM turn_record WHERE conv_id = ? AND arm = ? ORDER BY turn",
                                                             (conv_id, arm))]


def _conv(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    for k in ("review_json", "row_json", "security_json", "clinic_json"):
        d[k[:-5]] = json.loads(d.pop(k)) if d.get(k) else None
    return d
