# MediCloak 로그인 · 권한
#
#   비밀번호 : PBKDF2-HMAC-SHA256 (반복 200,000회, 사용자마다 16바이트 salt). 원문은 어디에도 남기지 않는다.
#   세션     : 로그인하면 임의 토큰(32바이트)을 HttpOnly 쿠키(mc_session, SameSite=Lax)로 준다. 12시간이 지나거나
#              60분 동안 쓰지 않으면 끝난다. DB에는 토큰의 SHA-256만 둔다 (DB가 새어도 세션을 가로챌 수 없다).
#   역할     : clinician(의료진) · security(보안 담당자). 경로 접두사마다 들어올 수 있는 역할을 정한다 (ROUTE_ROLES).
#              의료진은 의료진 화면 API와 가상 EMR만, 보안 담당자는 관제 · 의료진 대화 분석 · 레드팀만 쓴다.
#              검사는 두 곳에서 한다: 미들웨어(라우팅과 같은 경로 = root_path를 뗀 경로)와, 실제로 맞은 경로 틀에 붙인 의존성.
#   로그인 제한 : 같은 계정+주소 10분에 5번, 같은 계정(주소 무관) 10분에 20번 틀리면 막는다 (429). 시도는 비밀번호를
#              확인하기 전에 먼저 세므로 동시에 보내도 넘지 못한다. 비밀번호 해시는 동시에 4개까지만 돌린다 (CPU 보호).
#              실패도 감사 기록에 남긴다 (없는 아이디는 입력값을 남기지 않는다: 아이디 칸에 비밀번호를 잘못 친 경우).

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from webdemo.backend.store import Store

ITERATIONS = 200_000
COOKIE = "mc_session"
SESSION_TTL = 12 * 3600
IDLE_TIMEOUT = 60 * 60
FAIL_WINDOW = 600
FAIL_LIMIT = 5                 # 같은 계정 + 같은 주소
ACCOUNT_FAIL_LIMIT = 20        # 같은 계정 (주소가 바뀌어도)
HASH_SLOTS = 4                 # 동시에 돌리는 로그인 비밀번호 해시 수
ROLES = ("clinician", "security")
ROLE_KO = dict(clinician="의료진", security="보안 담당자")

# 경로 접두사 → 들어올 수 있는 역할 (위에서부터 처음 맞는 것). None은 로그인 없이 연다.
ROUTE_ROLES: tuple[tuple[str, frozenset[str] | None], ...] = (
    ("/api/auth/", None),
    ("/api/health", None),
    ("/api/terminology/", frozenset(ROLES)),
    ("/api/monitor/", frozenset({"security"})),
    ("/api/watch", frozenset({"security"})),
    ("/api/redteam", frozenset({"security"})),
    ("/api/poc", frozenset({"security"})),
    ("/api/sessions", frozenset({"security"})),
    ("/api/meta", frozenset({"security"})),
    ("/api/patients", frozenset({"security"})),
    ("/api/", frozenset({"clinician"})),          # 의료진 화면 계약 (/api/workspace, /api/cases/…, /api/clinic/…, /api/emr/…)
    ("/fhir/", frozenset({"clinician"})),
    ("/eval", frozenset({"security"})),
)

# 처음 쓸 계정 (python -m medicloak init 이 계정이 없을 때 한 번 만든다)
INITIAL_USERS = (
    ("doctor1", "김서연", "clinician", "내과"),
    ("doctor2", "박준호", "clinician", "가정의학과"),
    ("privacy1", "이하늘", "security", "개인정보보호팀"),
)


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), ITERATIONS)
    return salt, h.hex()


def verify_password(password: str, salt: str, pw_hash: str) -> bool:
    return hmac.compare_digest(hash_password(password, salt)[1], pw_hash)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def roles_for(path: str) -> frozenset[str] | None | bool:
    """경로에 필요한 역할. None: 로그인 없이 · False: 규칙 없음(화면 파일 등, 로그인 없이)."""
    for prefix, roles in ROUTE_ROLES:
        if path == prefix.rstrip("/") or path.startswith(prefix):
            return roles
    return False


def route_path(scope: dict[str, Any]) -> str:
    """
    라우터가 경로를 맞출 때 쓰는 경로 (Starlette get_route_path와 같음): root_path를 뗀 경로.
    uvicorn --root-path나 하위 경로 프록시 뒤에서 request.url.path에는 앞 경로가 붙어 있어, 그것으로 역할을 검사하면
    규칙에 맞지 않아 그냥 지나간다.
    """
    path: str = scope.get("path", "")
    root: str = scope.get("root_path", "") or ""
    if not root or not path.startswith(root):
        return path
    if path == root:
        return "/"
    if path[len(root)] == "/":
        return path[len(root):]
    return path


def user_view(u: Any) -> dict[str, Any]:
    return dict(userId=u["user_id"], username=u["username"], displayName=u["display_name"], role=u["role"],
                roleLabel=ROLE_KO.get(u["role"], u["role"]), department=u["department"])


def user_dict(u: Any) -> dict[str, Any]:
    """엔진 · 관제 쪽에서 쓰는 사용자 (sqlite Row → dict)."""
    return dict(user_id=u["user_id"], username=u["username"], display_name=u["display_name"], role=u["role"], department=u["department"])


def actor_label(user: dict[str, Any] | None, fallback: str) -> str:
    if not user:
        return fallback
    return f"{user['display_name']} ({ROLE_KO.get(user['role'], user['role'])} · {user['username']})"


class LoginBlocked(Exception):
    def __init__(self, wait: float) -> None:
        super().__init__(f"로그인을 잠시 막았습니다. {int(wait // 60) + 1}분 뒤 다시 시도하세요.")
        self.wait = wait


class Auth:
    def __init__(self, store: Store, *, ttl: float = SESSION_TTL, idle: float = IDLE_TIMEOUT) -> None:
        self.store = store
        self.ttl = ttl
        self.idle = idle
        self._fails: dict[tuple[str, str], list[float]] = {}          # (아이디, 주소) → 시도 시각
        self._account: dict[str, list[float]] = {}                    # 아이디 → 시도 시각
        self._lock = threading.Lock()
        self._hash = threading.BoundedSemaphore(HASH_SLOTS)

    # ── 로그인 ──
    def _begin(self, key: tuple[str, str]) -> float:
        """
        막혔는지 보고, 아니면 이번 시도를 실패로 먼저 센다 (맞으면 _ok가 지운다). 비밀번호 확인 전에 세야 동시에 보낸
        요청들이 모두 검사를 지나 버리지 않는다. 오래된 기록과 빈 열쇠는 여기서 치운다.
        """
        now = time.time()
        with self._lock:
            if len(self._fails) > 5000 or len(self._account) > 5000:
                self._fails = {k: v for k, v in self._fails.items() if v and now - v[-1] < FAIL_WINDOW}
                self._account = {k: v for k, v in self._account.items() if v and now - v[-1] < FAIL_WINDOW}
            fails = [t for t in self._fails.get(key, []) if now - t < FAIL_WINDOW]
            acct = [t for t in self._account.get(key[0], []) if now - t < FAIL_WINDOW]
            if len(fails) >= FAIL_LIMIT or len(acct) >= ACCOUNT_FAIL_LIMIT:
                first = (fails if len(fails) >= FAIL_LIMIT else acct)[0]
                self._fails[key], self._account[key[0]] = fails, acct
                raise LoginBlocked(FAIL_WINDOW - (now - first))
            fails.append(now)
            acct.append(now)
            self._fails[key], self._account[key[0]] = fails, acct
            return now

    def _ok(self, key: tuple[str, str], at: float) -> None:
        with self._lock:
            self._fails.pop(key, None)
            acct = [t for t in self._account.get(key[0], []) if t != at]
            if acct:
                self._account[key[0]] = acct
            else:
                self._account.pop(key[0], None)

    def login(self, username: str, password: str, client: str = "-") -> tuple[str, dict[str, Any]] | None:
        """맞으면 (토큰, 사용자), 틀리면 None. 막혔으면 LoginBlocked."""
        username = (username or "").strip()
        key = (username.lower(), client)
        at = self._begin(key)
        if not self._hash.acquire(timeout=10):           # 해시가 밀려 있으면 기다리게 하지 않고 잠시 뒤 다시
            raise LoginBlocked(30)
        try:
            u = self.store.user_by_name(username)
            # 없는 계정 · 쓰지 않는 계정도 해시를 한 번 돌린다 (걸리는 시간으로 계정이 있는지 알 수 없게)
            if u is not None:
                pw_ok = verify_password(password or "", u["pw_salt"], u["pw_hash"])
            else:
                hash_password(password or "")
                pw_ok = False
        finally:
            self._hash.release()
        if not (u and u["active"] and pw_ok):
            return None
        self._ok(key, at)
        token = secrets.token_urlsafe(32)
        self.store.purge_sessions(self.idle)
        self.store.add_session(token_hash(token), u["user_id"], self.ttl)
        return token, user_dict(u)

    def known(self, username: str) -> bool:
        """감사 기록에 아이디를 그대로 남겨도 되는지 (있는 계정만)."""
        return self.store.user_by_name((username or "").strip()) is not None

    def user_of(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        th = token_hash(token)
        u = self.store.session_user(th, idle=self.idle)
        if u is None:
            return None
        if time.time() - (u["last_seen"] or 0) > 60:
            self.store.touch_session(th)
        return user_dict(u)

    def logout(self, token: str | None) -> None:
        if token:
            self.store.drop_session(token_hash(token))


# ── 계정 만들기 ──

def add_user(store: Store, username: str, display_name: str, role: str, department: str | None, password: str) -> int:
    if role not in ROLES:
        raise ValueError(f"역할은 {', '.join(ROLES)} 중 하나입니다.")
    if len(password) < 8:
        raise ValueError("비밀번호는 8자 이상이어야 합니다.")
    if store.user_by_name(username) is not None:
        raise ValueError(f"이미 있는 계정입니다: {username}")
    salt, h = hash_password(password)
    return store.add_user(username, display_name, role, department, salt, h)


def set_password(store: Store, username: str, password: str) -> None:
    if len(password) < 8:
        raise ValueError("비밀번호는 8자 이상이어야 합니다.")
    salt, h = hash_password(password)
    if not store.set_password(username, salt, h):
        raise ValueError(f"없는 계정입니다: {username}")
    store.x("DELETE FROM auth_session WHERE user_id = (SELECT user_id FROM app_user WHERE username = ?)", (username,))


def ensure_initial_accounts(store: Store, password: str | None = None, out_file: Path | None = None) -> list[tuple[str, str, str]] | None:
    """
    계정이 하나도 없을 때만 처음 쓸 계정 셋을 만든다. 비밀번호는 password 하나를 같이 쓰고,
    없으면 계정마다 임의로 만든다. 만든 계정 [(아이디, 비밀번호, 역할)]을 돌려주고 out_file에 적는다 (권한 600).
    이미 계정이 있으면 None.
    """
    if store.count("app_user") > 0:
        return None
    made = []
    for username, name, role, dept in INITIAL_USERS:
        pw = password or secrets.token_urlsafe(9)
        add_user(store, username, name, role, dept, pw)
        made.append((username, pw, role))
    if out_file is not None:
        out_file.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# MediCloak 처음 계정 (python -m medicloak init 이 만든 파일, 커밋하지 마세요. 비밀번호를 바꾼 뒤 지워도 됩니다)",
                 "# 비밀번호 바꾸기: python -m medicloak users passwd <아이디>", ""]
        lines += [f"{u}\t{ROLE_KO[r]}\t{pw}" for u, pw, r in made]
        out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            out_file.chmod(0o600)
        except OSError:
            pass
    return made
