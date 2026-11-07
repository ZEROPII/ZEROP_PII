# 데스크톱 앱 (ADR-0039): python -m medicloak app
#
#   창(pywebview) 하나에 MediCloak 화면을 띄운다. 서버(uvicorn)는 같은 프로세스의 다른 스레드에서 돈다.
#   창을 닫으면 서버도 멈춘다. pywebview가 없으면 기본 브라우저로 연다 (--browser도 같음).
#
#   연결 방식 셋 (처음 켤 때 시작 화면에서 고르고 desktop.json에 남긴다):
#     이 컴퓨터에서 켜기   .env의 실제 LLM으로 서버를 켠다. 연결 정보가 없으면 시작 화면에서 받아 .env에 쓴다 (권한 600)
#     키 없이 둘러보기     결정적 응답기(--llm oracle)로 켠다
#     병원 서버에 연결     이 컴퓨터에서는 서버를 켜지 않고 그 주소를 창으로 연다 (--server)
#   명령줄에 --server · --llm을 주면 저장한 방식보다 앞선다. --setup이면 시작 화면부터 다시 (묶은 앱: open -a MediCloak --args --setup).
#   메뉴의 '처음 설정 다시 하기'는 다음에 켤 때 시작 화면부터 열게 남긴다 (.env에 연결 정보가 다 있어도).
#
#   같은 데이터 폴더로 두 번 켜면 두 번째 창은 서버를 새로 켜지 않고 켜져 있는 서버에 붙는다 (잠금 파일).
#   묶은 앱(PyInstaller)은 화면 출력을 데이터 폴더의 logs/medicloak-app.log에 적는다. 비밀번호와 API 키는 적지 않는다.

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Callable

from medicloak.paths import is_frozen

CONFIG_FILE = "desktop.json"
LOCK_FILE = "medicloak-app.lock"
INFO_FILE = "medicloak-app.json"          # 켜 둔 서버의 주소 (잠금 파일과 따로: Windows는 잠근 파일을 다른 프로세스가 읽지 못한다)
LOG_DIR = "logs"
LOG_FILE = "medicloak-app.log"
LOG_MAX = 5 * 1024 * 1024
START_PAGE = Path(__file__).with_name("desktop_start.html")
ROLE_KO = {"clinician": "의료진", "security": "보안 담당자"}
LLM_KEYS = ("LLM_API_BASE", "LLM_MODEL", "LLM_API_KEY")
WINDOW = dict(width=1440, height=900, min_size=(1024, 680))


# ── 작은 도구 ─────────────────────────────────────────

def pick_port(host: str = "127.0.0.1", preferred: int = 8000) -> int:
    """preferred가 비어 있으면 그것을, 아니면 운영체제가 고른 빈 포트."""
    for port in ([preferred] if preferred else []) + [0]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
            except OSError:
                continue
            return s.getsockname()[1]
    raise OSError("빈 포트를 찾지 못했습니다")


def server_url(text: str) -> str | None:
    """사용자가 적은 서버 주소를 'https://host[:port][/path]' 꼴로. 맞지 않으면 None. 스킴이 없으면 https."""
    t = (text or "").strip()
    if not t:
        return None
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", t):
        t = "https://" + t
    m = re.match(r"^(https?)://([^/\s:?#]+)(:\d{1,5})?(/[^\s?#]*)?$", t, re.I)
    if not m:
        return None
    return f"{m.group(1).lower()}://{m.group(2)}{m.group(3) or ''}{(m.group(4) or '').rstrip('/')}"


def health(url: str, timeout: float = 4.0) -> dict[str, Any] | None:
    """url이 MediCloak 서버면 /api/health 응답, 아니면 None."""
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/health", timeout=timeout) as r:      # noqa: S310 (http · https만 받는다)
            body = json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return None
    return body if isinstance(body, dict) and body.get("product") == "MediCloak" else None


def read_env(path: Path) -> dict[str, str]:
    from dotenv import dotenv_values
    return {k: v for k, v in dotenv_values(path).items() if v} if path.exists() else {}


def write_env(path: Path, values: dict[str, str]) -> None:
    """values의 키만 바꾸거나 더한다. 다른 줄(주석 · 선택 설정)은 그대로 둔다. 파일 권한은 600."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    left = dict(values)
    out = []
    for line in lines:
        m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if m and m.group(1) in left:
            out.append(f"{m.group(1)}={_env_value(left.pop(m.group(1)))}")
        else:
            out.append(line)
    out += [f"{k}={_env_value(v)}" for k, v in left.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)


def _env_value(v: str) -> str:
    v = v.replace("\n", "").strip()
    return f'"{v}"' if re.search(r"[\s#'\"]", v) else v


def llm_settings(env_file: Path | None) -> dict[str, Any]:
    """.env(와 셸 환경변수)에서 LLM 연결 정보를 본다. 키 값은 돌려주지 않는다."""
    vals = read_env(env_file) if env_file else {}
    got = {k: os.environ.get(k) or vals.get(k) or "" for k in LLM_KEYS}
    return dict(base=got["LLM_API_BASE"], model=got["LLM_MODEL"], keySet=bool(got["LLM_API_KEY"]),
                ready=all(got.values()))


def load_config(home: Path) -> dict[str, Any]:
    try:
        cfg = json.loads((home / CONFIG_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return cfg if isinstance(cfg, dict) else {}


def save_config(home: Path, cfg: dict[str, Any]) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / CONFIG_FILE).write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def open_path(path: Path) -> None:
    """파일 탐색기(Finder)로 폴더를 연다."""
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif os.name == "nt":
        os.startfile(str(path))          # type: ignore[attr-defined]  # noqa: S606
    else:
        subprocess.Popen(["xdg-open", str(path)])


class InstanceLock:
    """같은 데이터 폴더로 서버를 둘 켜지 않게 하는 잠금. 잠근 프로세스가 끝나면 운영체제가 풀어 준다. 주소는 INFO_FILE에 적는다."""

    def __init__(self, home: Path) -> None:
        self.path = home / LOCK_FILE
        self.info_path = home / INFO_FILE
        self._f: io.TextIOWrapper | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        f = open(self.path, "a+", encoding="utf-8")       # noqa: SIM115 (잠금을 쥔 동안 열어 둔다)
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self._f = f
        self.write(state="starting")
        return True

    def write(self, **info: Any) -> None:
        if self._f is not None:
            self.info_path.write_text(json.dumps(dict(pid=os.getpid(), **info)), encoding="utf-8")

    def info(self) -> dict[str, Any]:
        try:
            d = json.loads(self.info_path.read_text(encoding="utf-8") or "{}")
        except (OSError, ValueError):
            return {}
        return d if isinstance(d, dict) else {}

    def release(self) -> None:
        if self._f is None:
            return
        with contextlib.suppress(OSError):
            self.info_path.unlink()
        with contextlib.suppress(OSError):
            if os.name == "nt":
                import msvcrt
                self._f.seek(0)
                msvcrt.locking(self._f.fileno(), msvcrt.LK_UNLCK, 1)
        self._f.close()
        self._f = None


def redirect_output(home: Path) -> Path:
    """묶은 앱: print를 기록 파일로 보낸다 (창 앱은 터미널이 없고, Windows에서는 sys.stdout이 None). 5MB를 넘으면 한 번 돌린다."""
    log = home / LOG_DIR / LOG_FILE
    log.parent.mkdir(parents=True, exist_ok=True)
    if log.exists() and log.stat().st_size > LOG_MAX:
        log.replace(log.with_suffix(".log.1"))
    f = open(log, "a", encoding="utf-8", buffering=1)      # noqa: SIM115 (앱이 끝날 때까지 쓴다)
    with contextlib.suppress(OSError):
        os.chmod(log, 0o600)
    f.write(f"\n── {time.strftime('%Y-%m-%d %H:%M:%S')} MediCloak 앱 시작 (pid {os.getpid()})\n")
    sys.stdout = sys.stderr = f
    return log


# ── 이 컴퓨터의 서버 ───────────────────────────────────

class LocalServer:
    """cli.prepare()로 앱을 만들고 uvicorn을 다른 스레드에서 돌린다. 창을 닫으면 stop()."""

    def __init__(self, a: argparse.Namespace, *, on_step: Callable[[str], None] = lambda k: None, log: Callable[[str], None] = print,
                 prepare: Callable[..., Any] | None = None) -> None:
        self.a = a
        self.on_step = on_step
        self.log = log
        self._prepare = prepare
        self.ready = threading.Event()
        self.done = threading.Event()
        self.error: str | None = None
        self.info: dict[str, Any] = {}
        self.url = ""
        self._server: Any = None
        self._stop = False
        self.thread = threading.Thread(target=self._run, name="medicloak-server", daemon=True)

    def start(self) -> "LocalServer":
        self.thread.start()
        return self

    def _run(self) -> None:
        try:
            import uvicorn
            prepare = self._prepare
            if prepare is None:
                from medicloak.cli import prepare
            app, self.info = prepare(self.a, log=self.log, step=self.on_step, show_passwords=False)
            if self._stop:
                return
            self.on_step("server")
            for attempt in range(2):                         # 고른 포트를 그새 다른 프로그램이 잡았으면 한 번 더 고른다
                port = pick_port(self.a.host, self.a.port if attempt == 0 else 0)
                self._server = uvicorn.Server(uvicorn.Config(app, host=self.a.host, port=port, log_level="warning"))
                self.url = f"http://{self.a.host}:{port}"
                t = threading.Thread(target=self._serve, name="medicloak-uvicorn", daemon=True)
                t.start()
                while t.is_alive() and not self._server.started and not self._stop:
                    time.sleep(0.05)
                if self._server.started:
                    self.log(f"[medicloak] 준비되었습니다: {self.url}")
                    self.ready.set()
                    t.join()
                    return
                if self._stop:
                    return
            raise OSError(f"서버를 {self.a.host}에 열지 못했습니다 (포트를 다른 프로그램이 쓰고 있습니다)")
        except SystemExit as exc:                            # prepare()가 알린 설정 오류 (메시지에 키 값 없음)
            self.error = str(exc.code) if exc.code not in (None, 0) else "서버가 멈췄습니다"
        except BaseException as exc:                         # noqa: BLE001 (창에 보이고 기록에 남긴다)
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            if self.error:
                self.log(f"[medicloak] 켜지 못했습니다: {self.error}")
            self.done.set()

    def _serve(self) -> None:
        with contextlib.suppress(SystemExit):                # 열지 못하면 uvicorn이 sys.exit(1)을 부른다
            self._server.run()

    def wait(self, timeout: float | None = None) -> bool:
        """준비되면 True, 실패하거나 멈추면 False."""
        end = None if timeout is None else time.monotonic() + timeout
        while not self.ready.is_set() and not self.done.is_set():
            if end is not None and time.monotonic() > end:
                return False
            time.sleep(0.05)
        return self.ready.is_set()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop = True
        if self._server is not None:
            self._server.should_exit = True
        self.thread.join(timeout)


# ── 창 ────────────────────────────────────────────────

class StartApi:
    """
    시작 화면의 단추 (window.pywebview.api). pywebview가 부를 때마다 다른 스레드라 오래 걸려도 창이 멈추지 않는다.
    pywebview는 창에 열린 모든 페이지에 이 API를 넣는다. 앱 화면(또는 병원 서버)을 연 뒤에는 받지 않는다:
    그 페이지의 스크립트가 .env(LLM 주소 · 키)를 고쳐 쓰거나 폴더를 열지 못하게.
    """

    def __init__(self, app: "DesktopApp") -> None:
        self._app = app

    def _off(self) -> bool:
        return self._app.opened

    def choose_local(self, data: dict[str, Any]) -> dict[str, Any]:
        return dict(ok=False, message="") if self._off() else self._app.choose_local(data or {})

    def choose_oracle(self) -> dict[str, Any]:
        return dict(ok=False, message="") if self._off() else self._app.choose_oracle()

    def choose_server(self, url: str) -> dict[str, Any]:
        return dict(ok=False, message="") if self._off() else self._app.choose_server(url or "")

    def go(self) -> None:
        if not self._off():
            self._app.go()

    def retry(self) -> None:
        if not self._off():
            self._app.retry()

    def setup_again(self) -> None:
        if not self._off():
            self._app.setup_again()

    def open_folder(self, which: str) -> None:
        if not self._off():
            self._app.open_folder(which)


class DesktopApp:
    """시작 화면 → (처음 설정) → 서버 준비 → (처음 쓸 계정) → MediCloak 화면. pywebview 창 하나를 다룬다."""

    def __init__(self, a: argparse.Namespace, webview: Any, *, home: Path, prepare: Callable[..., Any] | None = None,
                 health_fn: Callable[[str], dict[str, Any] | None] = health, opener: Callable[[Path], None] = open_path,
                 check: Callable[..., bool] | None = None) -> None:
        self.a = a
        self.webview = webview
        self.home = home
        self.env_file = Path(a.env_file) if a.env_file else _repo_env()
        self._prepare = prepare
        self._health = health_fn
        self._open = opener
        self._check = check
        self.window: Any = None
        self.server: LocalServer | None = None
        self.lock = InstanceLock(home)
        self.loaded = threading.Event()
        self._go = threading.Event()
        self._busy = threading.Lock()
        self.url = ""
        self.opened = False                                  # 시작 화면을 떠나 앱 화면(또는 병원 서버)을 열었는지
        self.closed = False
        self.config = load_config(home)

    # 창에서 부르는 JS
    def js(self, fn: str, *args: Any) -> None:
        if self.window is None or self.closed:
            return
        self.loaded.wait(15)
        with contextlib.suppress(Exception):                 # 창이 이미 닫히는 중
            self.window.evaluate_js(f"window.MC && MC.{fn}({', '.join(json.dumps(x, ensure_ascii=False) for x in args)})")

    def show(self, view: str, data: dict[str, Any] | None = None) -> None:
        self.js("show", view, data or {})

    def load(self, url: str) -> None:
        self.url = url
        self.opened = True
        if self.window is not None and not self.closed:
            self.window.load_url(url)

    # 시작
    def run(self) -> None:
        wv = self.webview
        self.window = wv.create_window("MediCloak", html=START_PAGE.read_text(encoding="utf-8"), js_api=StartApi(self),
                                       text_select=True, zoomable=True, background_color="#F4F5F9", **WINDOW)
        self.window.events.loaded += lambda *_: self.loaded.set()
        self.window.events.closed += lambda *_: self.mark_closed()
        with contextlib.suppress(Exception):                 # 아래 설정 키가 없는 판의 pywebview
            wv.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        try:
            wv.start(self.flow, private_mode=False, storage_path=str(self.home / "webview"), menu=self.menu())
        finally:
            self.shutdown()                                  # 창이 모두 닫히면 start()가 돌아온다

    def menu(self) -> list[Any]:
        try:
            from webview.menu import Menu, MenuAction, MenuSeparator
        except ImportError:
            return []
        return [Menu("MediCloak", [
            MenuAction("브라우저로 열기", self.open_in_browser),
            MenuAction("데이터 폴더 열기", lambda: self.open_folder("home")),
            MenuAction("기록 폴더 열기", lambda: self.open_folder("logs")),
            MenuSeparator(),
            MenuAction("처음 설정 다시 하기", self.menu_setup_again),
        ])]

    def flow(self) -> None:
        """창이 뜬 뒤 다른 스레드에서: 어떤 방식으로 열지 정하고 연다."""
        self.loaded.wait(15)
        a = self.a
        if a.server:
            self.open_remote(a.server, save=False)
        elif a.setup:
            self.show_setup()
        elif a.llm:
            self.start_local(a.llm)
        elif self.config.get("setup"):                     # 메뉴의 '처음 설정 다시 하기' (.env가 다 있어도 처음 설정부터)
            self.show_setup()
        elif self.config.get("mode") == "server" and self.config.get("server"):
            self.open_remote(self.config["server"], save=False)
        elif self.config.get("llm") == "oracle":
            self.start_local("oracle")
        elif llm_settings(self.env_file)["ready"]:
            self.start_local("real")
        else:
            self.show_setup()

    def show_setup(self) -> None:
        s = llm_settings(self.env_file)
        self.show("setup", dict(base=s["base"], model=s["model"], keySet=s["keySet"], envFile=str(self.env_file),
                                server=self.config.get("server", "")))

    # 시작 화면의 고르기
    def choose_local(self, data: dict[str, Any]) -> dict[str, Any]:
        base, model, key = (str(data.get(k) or "").strip() for k in ("base", "model", "key"))
        have = llm_settings(self.env_file)
        if not server_url(base) or not base.lower().startswith(("http://", "https://")):
            return dict(ok=False, message="API 주소를 http:// 또는 https://로 시작하게 적으세요.")
        if not model:
            return dict(ok=False, message="모델 이름을 적으세요.")
        if not key and not have["keySet"]:
            return dict(ok=False, message="API 키를 적으세요.")
        values = dict(LLM_API_BASE=base, LLM_MODEL=model)
        if key:
            values["LLM_API_KEY"] = key
        write_env(self.env_file, values)
        if data.get("test"):
            lines: list[str] = []
            check = self._check
            if check is None:
                from webdemo.backend.live import check_llm as check
            ok = check(str(self.env_file), send=True, out=lines.append)
            if not ok:
                why = next((x for x in lines if x.startswith("[")), "연결을 확인하지 못했습니다.")
                return dict(ok=False, canSkip=True, message=f"{why}\n주소 · 모델 · 키를 확인하세요. 네트워크 문제라면 '확인 없이 시작'으로 켤 수 있습니다.")
        self.save(mode="local", llm="real")
        threading.Thread(target=self.start_local, args=("real",), daemon=True).start()
        return dict(ok=True)

    def choose_oracle(self) -> dict[str, Any]:
        self.save(mode="local", llm="oracle")
        threading.Thread(target=self.start_local, args=("oracle",), daemon=True).start()
        return dict(ok=True)

    def choose_server(self, text: str) -> dict[str, Any]:
        url = server_url(text)
        if not url:
            return dict(ok=False, message="서버 주소를 https://로 시작하는 꼴로 적으세요 (예: https://medicloak.example.org).")
        if not self._health(url):
            return dict(ok=False, message="이 주소에서 MediCloak 서버를 찾지 못했습니다. 주소와 네트워크(병원 내부망 · VPN)를 확인하세요.")
        self.save(mode="server", server=url)
        self.load(url)
        return dict(ok=True)

    def save(self, **cfg: Any) -> None:
        self.config = dict(cfg)
        save_config(self.home, self.config)

    # 이 컴퓨터에서 켜기
    def start_local(self, llm: str) -> None:
        if not self._busy.acquire(blocking=False):           # 이미 켜는 중
            return
        try:
            self._start_local(llm)
        finally:
            self._busy.release()

    def _start_local(self, llm: str) -> None:
        if not self.lock.acquire():
            self.attach_running()
            return
        self.show("loading")
        self.a.llm = llm
        self.server = LocalServer(self.a, on_step=lambda k: self.js("step", k), prepare=self._prepare).start()
        if not self.server.wait():
            err = self.server.error or "서버가 멈췄습니다."
            self.server = None
            self.lock.release()
            if not self.closed:
                self.show("error", dict(message=err))
            return
        self.lock.write(state="ready", url=self.server.url)
        made = self.server.info.get("made") or []
        if made:
            self._go.clear()
            self.show("accounts", dict(file=str(self.server.info.get("accounts") or ""),
                                       accounts=[dict(username=u, password=p, role=ROLE_KO.get(r, r)) for u, p, r in made]))
            self._go.wait()
        self.load(self.server.url)

    def attach_running(self) -> None:
        """다른 창(같은 데이터 폴더)이 서버를 켜 두었으면 그 서버를 연다. 아직 준비 중이면 잠깐 기다린다."""
        self.show("loading", dict(note="다른 MediCloak 창이 이 데이터 폴더로 서버를 켜 두었습니다. 그 서버에 연결합니다."))
        end = time.monotonic() + 120
        while time.monotonic() < end and not self.closed:
            url = self.lock.info().get("url")
            if url and self._health(url):
                self.load(url)
                return
            time.sleep(1)
        if not self.closed:
            self.show("error", dict(message="다른 MediCloak이 이 데이터 폴더를 쓰고 있지만 응답하지 않습니다.\n"
                                            "켜 둔 MediCloak 창을 닫고 다시 켜세요.", retry=True))

    # 병원 서버에 연결
    def open_remote(self, text: str, *, save: bool) -> None:
        url = server_url(text)
        self.show("loading", dict(remote=True))
        self.js("step", "remote")
        if url and self._health(url):
            if save:
                self.save(mode="server", server=url)
            self.load(url)
            return
        self.show("error", dict(message=f"{text} 에서 MediCloak 서버를 찾지 못했습니다.\n"
                                        "주소와 네트워크(병원 내부망 · VPN)를 확인하세요.", retry=True))

    # 단추 · 메뉴
    def go(self) -> None:
        self._go.set()

    def retry(self) -> None:
        threading.Thread(target=self.flow, daemon=True).start()

    def setup_again(self) -> None:
        self.a.server = None
        self.a.llm = None
        self.show_setup()

    def menu_setup_again(self) -> None:
        self.save(setup=True)
        msg = "다음에 켤 때 처음 설정 화면이 나옵니다. 저장한 LLM 연결 정보는 지우지 않습니다."
        with contextlib.suppress(Exception):
            self.window.create_confirmation_dialog("처음 설정 다시 하기", msg)

    def open_folder(self, which: str) -> None:
        self._open(self.home / LOG_DIR if which == "logs" else self.home)

    def open_in_browser(self) -> None:
        if self.url:
            webbrowser.open(self.url)

    def mark_closed(self) -> None:
        """창이 닫힘 (창 스레드에서 불린다: 여기서는 표시만 하고, 서버는 shutdown에서 멈춘다)."""
        self.closed = True
        self._go.set()

    def shutdown(self) -> None:
        self.mark_closed()
        if self.server is not None:
            self.server.stop()
            self.server = None
        self.lock.release()


def _repo_env() -> Path:
    from core.config import DEFAULT_ENV_FILE
    return Path(DEFAULT_ENV_FILE)


def _load_webview() -> Any | None:
    try:
        import webview
    except ImportError:
        return None
    return webview


# ── 창 없이 (브라우저 · 점검) ──────────────────────────

def run_headless(a: argparse.Namespace, home: Path, *, open_browser: bool) -> None:
    """창 없이: --server면 브라우저로 그 주소를 열고 끝. 아니면 서버를 켜고 Ctrl+C(또는 SIGTERM)까지 돈다."""
    if a.server:
        url = server_url(a.server)
        if not url:
            raise SystemExit(f"[medicloak] 서버 주소가 맞지 않습니다: {a.server}")
        if not health(url):
            raise SystemExit(f"[medicloak] {url} 에서 MediCloak 서버를 찾지 못했습니다")
        print(f"[medicloak] 병원 서버를 엽니다: {url}")
        if open_browser:
            webbrowser.open(url)
        return
    lock = InstanceLock(home)
    if not lock.acquire():
        url = lock.info().get("url")
        if url and health(url):
            print(f"[medicloak] 이미 켜져 있는 MediCloak이 있습니다: {url}")
            if open_browser:
                webbrowser.open(url)
            return
        raise SystemExit(f"[medicloak] 다른 MediCloak이 이 데이터 폴더({home})를 쓰고 있습니다")
    a.llm = a.llm or ("oracle" if load_config(home).get("llm") == "oracle" else "real")
    stop = threading.Event()
    with contextlib.suppress(ValueError):                    # 주 스레드가 아니면 신호를 받지 않는다
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
    srv = LocalServer(a, log=print).start()
    try:
        if not srv.wait():
            raise SystemExit(f"[medicloak] 켜지 못했습니다: {srv.error}")
        lock.write(state="ready", url=srv.url)
        made, acc = srv.info.get("made") or [], srv.info.get("accounts")
        if made and not is_frozen():                         # 터미널에서 켰을 때만 비밀번호를 한 번 보인다
            print("[medicloak] 처음 쓸 계정 (이 비밀번호는 지금 한 번만 보여 줍니다)")
            for u, p, r in made:
                print(f"    {u:<10} {ROLE_KO.get(r, r):<7} {p}")
        if acc:
            print(f"[medicloak] 처음 쓸 계정 파일: {acc}")
        if open_browser:
            webbrowser.open(srv.url)
        while not stop.is_set() and not srv.done.is_set():
            stop.wait(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        srv.stop()
        lock.release()
        print("[medicloak] 멈췄습니다")


def _quiet_terminal() -> bool:
    """터미널 없이 켜졌는지 (Finder · 시작 메뉴에서 연 묶은 앱, Windows 창 앱은 sys.stdout이 None)."""
    out = sys.stdout
    return out is None or not (hasattr(out, "isatty") and out.isatty())


def _exit_when_idle(grace: float = 5.0) -> None:
    """서버를 멈춘 뒤에도 남은 일(뒤에서 돌던 점검 · 미리 만들기의 LLM 호출)이 grace초 안에 끝나지 않으면 기다리지 않고 끝낸다."""
    end = time.monotonic() + grace
    for t in threading.enumerate():
        if t is threading.current_thread() or t.daemon:
            continue
        t.join(max(0.0, end - time.monotonic()))
    if any(t.is_alive() and not t.daemon for t in threading.enumerate() if t is not threading.current_thread()):
        for f in (sys.stdout, sys.stderr):
            with contextlib.suppress(Exception):
                f.flush()
        os._exit(0)


def run_app(a: argparse.Namespace) -> None:
    """python -m medicloak app"""
    home = Path(a.db).parent
    home.mkdir(parents=True, exist_ok=True)
    if is_frozen() and _quiet_terminal():
        redirect_output(home)
    webview = None if (a.no_window or a.browser) else _load_webview()
    if webview is None:
        if not (a.no_window or a.browser):
            print("[medicloak] pywebview가 없어 기본 브라우저로 엽니다 (창으로 열려면 pip install -r medicloak/requirements-desktop.txt)")
        run_headless(a, home, open_browser=not a.no_window)
    else:
        try:
            DesktopApp(a, webview, home=home).run()
        except Exception as exc:                             # noqa: BLE001 (창을 띄우지 못함: Linux에 GTK · Qt가 없을 때 등)
            print(f"[medicloak] 창을 띄우지 못해 기본 브라우저로 엽니다 ({type(exc).__name__}: {exc})")
            run_headless(a, home, open_browser=True)
    _exit_when_idle()
