# 데스크톱 앱 (ADR-0039): 폴더 · 주소 · .env 쓰기 · 잠금 · 서버 스레드 · 시작 화면 흐름 (pywebview 대신 가짜 창)
import argparse
import inspect
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from dotenv import dotenv_values
from fastapi import FastAPI

from medicloak import desktop, paths
from medicloak.cli import _print_accounts, main


def test_app_folders_per_platform(monkeypatch, tmp_path):
    home = Path("/Users/kim")
    assert paths.user_data_dir("darwin", {}, home) == home / "Library" / "Application Support" / "MediCloak"
    assert paths.user_data_dir("win32", {"APPDATA": r"C:\Users\kim\AppData\Roaming"}, home) == Path(r"C:\Users\kim\AppData\Roaming") / "MediCloak"
    assert paths.user_data_dir("linux", {}, home) == home / ".local" / "share" / "medicloak"
    assert paths.user_data_dir("linux", {"XDG_DATA_HOME": "/data"}, home) == Path("/data/medicloak")
    assert paths.app_home({}) == paths.ROOT / "runs" / "medicloak"                    # 저장소에서는 runs/medicloak
    assert paths.app_home({"MEDICLOAK_HOME": str(tmp_path)}) == tmp_path
    assert paths.default_env_file(tmp_path) is None                                     # 저장소: 루트의 .env (core/config.py 기본)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert paths.is_frozen() and paths.default_env_file(tmp_path) == tmp_path / ".env"  # 묶은 앱: 앱 데이터 폴더
    assert paths.app_home({}) == paths.user_data_dir(env={})


def test_server_url_and_port():
    assert desktop.server_url("medicloak.example.org") == "https://medicloak.example.org"
    assert desktop.server_url(" http://10.0.0.5:8000/ ") == "http://10.0.0.5:8000"
    assert desktop.server_url("https://h.example.org/medicloak/") == "https://h.example.org/medicloak"
    assert desktop.server_url("HTTPS://A.example.org") == "https://A.example.org"
    for bad in ("", "not a url", "ftp://x.org", "https://a b.org", "javascript:alert(1)"):
        assert desktop.server_url(bad) is None, bad
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        busy = s.getsockname()[1]
        got = desktop.pick_port("127.0.0.1", busy)
        assert got != busy and got > 0                                                   # 쓰는 포트면 다른 빈 포트
    assert desktop.pick_port("127.0.0.1", got) == got


def test_write_env_keeps_other_lines_and_is_private(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# 연결 정보\nLLM_API_BASE=https://old.example.org\nLLM_TIMEOUT_SEC=90\n", encoding="utf-8")
    desktop.write_env(env, dict(LLM_API_BASE="https://llm.example.org/v1", LLM_MODEL="model a", LLM_API_KEY="sk-test#1"))
    text = env.read_text(encoding="utf-8")
    assert text.startswith("# 연결 정보\n") and "LLM_TIMEOUT_SEC=90" in text and "old.example.org" not in text
    assert dotenv_values(env) == {"LLM_API_BASE": "https://llm.example.org/v1", "LLM_TIMEOUT_SEC": "90", "LLM_MODEL": "model a", "LLM_API_KEY": "sk-test#1"}
    if os.name == "posix":
        assert env.stat().st_mode & 0o777 == 0o600
    s = desktop.llm_settings(env)
    assert s == dict(base="https://llm.example.org/v1", model="model a", keySet=True, ready=True)      # 키 값은 돌려주지 않는다
    assert desktop.llm_settings(tmp_path / "없음.env")["ready"] is False or os.environ.get("LLM_API_KEY")


def test_instance_lock_lets_one_server_per_folder(tmp_path):
    first, second = desktop.InstanceLock(tmp_path), desktop.InstanceLock(tmp_path)
    assert first.acquire() and not second.acquire()
    first.write(state="ready", url="http://127.0.0.1:8123")
    assert second.info() == dict(pid=os.getpid(), state="ready", url="http://127.0.0.1:8123")
    first.release()
    assert second.info() == {} and second.acquire()
    second.release()


def _fake_prepare(made=(), fail=None, delay=0.0):
    def prepare(a, *, log, step, show_passwords):
        assert show_passwords is False                       # 창 앱은 비밀번호를 기록에 남기지 않는다
        if fail:
            raise SystemExit(fail)
        for k in ("db", "llm", "engine"):
            step(k)
            time.sleep(delay)
        app = FastAPI()

        @app.get("/api/health")
        def health():
            return dict(product="MediCloak", status="ok", llm=a.llm)

        return app, dict(made=list(made), accounts=Path(a.db).parent / "initial_accounts.txt")
    return prepare


def _args(tmp_path, **kw):
    d = dict(db=str(tmp_path / "medicloak.db"), env_file=str(tmp_path / ".env"), llm=None, server=None, setup=False, host="127.0.0.1", port=0)
    d.update(kw)
    return argparse.Namespace(**d)


def test_local_server_runs_in_a_thread_and_stops(tmp_path):
    steps = []
    srv = desktop.LocalServer(_args(tmp_path, llm="oracle"), on_step=steps.append, log=lambda s: None, prepare=_fake_prepare()).start()
    assert srv.wait(15) and srv.url.startswith("http://127.0.0.1:")
    assert steps == ["db", "llm", "engine", "server"] and desktop.health(srv.url)["llm"] == "oracle"
    srv.stop()
    assert not srv.thread.is_alive() and desktop.health(srv.url, timeout=1) is None


def test_local_server_reports_setup_errors(tmp_path):
    srv = desktop.LocalServer(_args(tmp_path, llm="real"), log=lambda s: None,
                              prepare=_fake_prepare(fail="[medicloak] 대상 AI를 준비하지 못했습니다: LLM_API_KEY가 비어 있습니다")).start()
    assert srv.wait(10) is False and "LLM_API_KEY" in srv.error


# ── 가짜 pywebview: 창 하나, start()는 창이 닫힐 때까지 막힌다 ──

class _Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, fn):
        self.handlers.append(fn)
        return self

    def fire(self):
        for h in self.handlers:
            h()


class _Window:
    def __init__(self, kw):
        self.kw = kw
        self.api = kw["js_api"]
        self.events = SimpleNamespace(loaded=_Event(), closed=_Event())
        self.scripts, self.urls = [], []
        self.gone = threading.Event()

    def evaluate_js(self, script):
        self.scripts.append(script)

    def load_url(self, url):
        self.urls.append(url)

    def destroy(self):
        self.events.closed.fire()
        self.gone.set()

    def create_confirmation_dialog(self, title, message):
        self.scripts.append(f"dialog:{title}")
        return True

    def shown(self, view):
        return any(s.startswith(f'window.MC && MC.show("{view}"') for s in self.scripts)


class _Webview:
    def __init__(self):
        self.settings = {}
        self.window = None

    def create_window(self, title, **kw):
        self.window = _Window(kw)
        return self.window

    def start(self, func=None, **kw):
        self.start_kw = kw
        self.window.events.loaded.fire()
        threading.Thread(target=func, daemon=True).start()
        self.window.gone.wait(30)


def _until(pred, t=15.0):
    end = time.monotonic() + t
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def _run(app):
    t = threading.Thread(target=app.run, daemon=True)
    t.start()
    assert _until(lambda: app.window is not None)
    return t


def test_first_launch_asks_for_llm_settings_then_opens_the_app(tmp_path, monkeypatch):
    for k in desktop.LLM_KEYS:
        monkeypatch.delenv(k, raising=False)
    wv, checks = _Webview(), []

    def check(env_file, *, send, out):
        checks.append(env_file)
        out("설정을 읽었습니다 (키 값은 보여 주지 않습니다)")
        if len(checks) == 1:
            out("[호출 실패] LLMError: 401")
            return False
        return True

    app = desktop.DesktopApp(_args(tmp_path), wv, home=tmp_path, prepare=_fake_prepare(), check=check, opener=lambda p: None)
    t = _run(app)
    w = wv.window
    assert _until(lambda: w.shown("setup"))
    assert w.kw["text_select"] is True and wv.start_kw["private_mode"] is False                  # 글을 고르고 복사할 수 있고, 화면 설정이 남는다
    assert w.api.choose_local(dict(base="llm.example.org", model="m", key="k"))["ok"] is False    # http(s)로 시작해야 한다
    assert "API 키" in w.api.choose_local(dict(base="https://llm.example.org", model="m", key=""))["message"]
    r = w.api.choose_local(dict(base="https://llm.example.org", model="m", key="sk-1", test=True))
    assert r["ok"] is False and r["canSkip"] and "[호출 실패]" in r["message"] and "sk-1" not in r["message"]
    assert w.api.choose_local(dict(base="https://llm.example.org", model="m", key="", test=True)) == dict(ok=True)   # 저장한 키를 그대로
    assert _until(lambda: w.urls)
    assert w.urls[0].startswith("http://127.0.0.1:") and desktop.health(w.urls[0])["llm"] == "real"
    assert desktop.load_config(tmp_path) == dict(mode="local", llm="real")
    assert dotenv_values(tmp_path / ".env")["LLM_API_KEY"] == "sk-1"
    assert json.loads((tmp_path / desktop.INFO_FILE).read_text())["url"] == w.urls[0]
    # 앱 화면을 연 뒤에는 그 페이지의 스크립트가 시작 화면 API로 .env를 바꾸지 못한다
    assert w.api.choose_local(dict(base="https://evil.example.org", model="m", key="x")) == dict(ok=False, message="")
    assert w.api.choose_server("https://evil.example.org")["ok"] is False and w.urls == w.urls[:1]
    assert dotenv_values(tmp_path / ".env")["LLM_API_BASE"] == "https://llm.example.org"
    w.destroy()
    t.join(15)
    assert not t.is_alive() and app.server is None and not (tmp_path / desktop.INFO_FILE).exists()
    assert desktop.health(w.urls[0], timeout=1) is None                                         # 창을 닫으면 서버도 멈춘다


def test_first_accounts_are_shown_once_before_login(tmp_path):
    wv = _Webview()
    made = [("doctor1", "pw-1", "clinician"), ("privacy1", "pw-3", "security")]
    app = desktop.DesktopApp(_args(tmp_path, llm="oracle"), wv, home=tmp_path, prepare=_fake_prepare(made))
    t = _run(app)
    w = wv.window
    assert _until(lambda: w.shown("accounts"))
    shown = next(s for s in w.scripts if 'MC.show("accounts"' in s)
    assert '"username": "doctor1"' in shown and '"password": "pw-1"' in shown and '"role": "보안 담당자"' in shown
    assert not w.urls                                                                           # '로그인 화면으로'를 누를 때까지
    w.api.go()
    assert _until(lambda: w.urls)
    w.destroy()
    t.join(15)


def test_saved_hospital_server_opens_without_a_local_server(tmp_path):
    desktop.save_config(tmp_path, dict(mode="server", server="https://medicloak.example.org"))
    wv, asked = _Webview(), []
    app = desktop.DesktopApp(_args(tmp_path), wv, home=tmp_path, health_fn=lambda u: asked.append(u) or {"product": "MediCloak"})
    t = _run(app)
    w = wv.window
    assert _until(lambda: w.urls) and w.urls == ["https://medicloak.example.org"] and app.server is None
    assert asked == ["https://medicloak.example.org"] and not (tmp_path / desktop.LOCK_FILE).exists() and not (tmp_path / desktop.INFO_FILE).exists()
    w.destroy()
    t.join(15)


def test_hospital_server_errors_and_choice(tmp_path):
    wv = _Webview()
    ok = {"https://medicloak.example.org"}
    app = desktop.DesktopApp(_args(tmp_path, setup=True), wv, home=tmp_path, health_fn=lambda u: {"product": "MediCloak"} if u in ok else None)
    t = _run(app)
    w = wv.window
    assert _until(lambda: w.shown("setup"))
    assert "찾지 못했습니다" in w.api.choose_server("https://wrong.example.org")["message"]
    assert w.api.choose_server("medicloak.example.org") == dict(ok=True)
    assert w.urls == ["https://medicloak.example.org"] and desktop.load_config(tmp_path) == dict(mode="server", server="https://medicloak.example.org")
    w.destroy()
    t.join(15)


def test_second_window_attaches_to_the_running_server(tmp_path):
    other = desktop.InstanceLock(tmp_path)
    assert other.acquire()
    other.write(state="ready", url="http://127.0.0.1:8123")
    wv = _Webview()
    app = desktop.DesktopApp(_args(tmp_path, llm="oracle"), wv, home=tmp_path, prepare=_fake_prepare(),
                             health_fn=lambda u: {"product": "MediCloak"} if u == "http://127.0.0.1:8123" else None)
    t = _run(app)
    w = wv.window
    assert _until(lambda: w.urls) and w.urls == ["http://127.0.0.1:8123"] and app.server is None   # 서버를 새로 켜지 않는다
    w.destroy()
    t.join(15)
    assert other.info()["url"] == "http://127.0.0.1:8123"                                         # 다른 창의 잠금은 그대로
    other.release()


def test_setup_error_shows_the_reason_and_can_choose_again(tmp_path):
    wv = _Webview()
    app = desktop.DesktopApp(_args(tmp_path, llm="real"), wv, home=tmp_path,
                             prepare=_fake_prepare(fail="[medicloak] 대상 AI를 준비하지 못했습니다: LLM_MODEL이 비어 있습니다"))
    t = _run(app)
    w = wv.window
    assert _until(lambda: w.shown("error"))
    assert any("LLM_MODEL" in s for s in w.scripts if 'MC.show("error"' in s)
    probe = desktop.InstanceLock(tmp_path)
    assert not (tmp_path / desktop.INFO_FILE).exists() and probe.acquire()                     # 실패하면 잠금을 푼다
    probe.release()
    w.api.setup_again()
    assert _until(lambda: w.shown("setup"))
    app._prepare = _fake_prepare()
    assert w.api.choose_oracle() == dict(ok=True) and _until(lambda: w.urls)
    w.destroy()
    t.join(15)


def test_logs_go_to_the_data_folder_without_passwords(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    log = tmp_path / desktop.LOG_DIR / desktop.LOG_FILE
    log.parent.mkdir(parents=True)
    log.write_bytes(b"x" * (desktop.LOG_MAX + 1))
    assert desktop.redirect_output(tmp_path) == log
    print("[medicloak] 서버 시작")
    sys.stdout.flush()
    assert log.with_suffix(".log.1").exists() and "서버 시작" in log.read_text(encoding="utf-8")
    lines = []
    _print_accounts([("doctor1", "pw-secret", "clinician")], tmp_path / "initial_accounts.txt", lines.append, show_passwords=False)
    assert lines and "pw-secret" not in " ".join(lines) and "initial_accounts.txt" in lines[0]


def test_cli_app_command(monkeypatch, tmp_path):
    got = {}
    monkeypatch.setattr(desktop, "run_app", lambda a: got.update(vars(a)))
    main(["--db", str(tmp_path / "m.db"), "app", "--no-window", "--server", "medicloak.example.org"])
    assert got["cmd"] == "app" and got["no_window"] and got["server"] == "medicloak.example.org"
    assert got["llm"] is None and got["port"] == 8000 and got["env_file"] is None     # --llm을 주지 않으면 저장한 방식 · .env를 본다
    main(["--db", str(tmp_path / "m.db"), "app", "--llm", "oracle", "--setup"])
    assert got["llm"] == "oracle" and got["setup"] is True
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    main(["--db", str(tmp_path / "m.db"), "app"])
    assert got["env_file"] == str(paths.app_home() / ".env")                         # 묶은 앱: 앱 데이터 폴더의 .env


def test_window_arguments_match_pywebview():
    webview = pytest.importorskip("webview")
    inspect.signature(webview.create_window).bind("MediCloak", html="<p>", js_api=object(), text_select=True, zoomable=True,
                                                  background_color="#F4F5F9", **desktop.WINDOW)
    inspect.signature(webview.start).bind(lambda: None, private_mode=False, storage_path="/tmp/x", menu=[])
    from webview.menu import Menu, MenuAction, MenuSeparator  # noqa: F401  (메뉴를 만들 수 있다)
    app = desktop.DesktopApp(argparse.Namespace(env_file=None), None, home=Path("/tmp"))
    assert [m.title for m in app.menu()] == ["MediCloak"]


def test_packaged_entry_defaults_to_the_app():
    import importlib.util
    spec = importlib.util.spec_from_file_location("medicloak_app", paths.ROOT / "packaging" / "medicloak_app.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.argv([]) == ["app"] and m.argv(["-psn_0_12345"]) == ["app"]                 # Finder에서 두 번 누름
    assert m.argv(["--llm", "oracle"]) == ["app", "--llm", "oracle"]
    assert m.argv(["users", "list"]) == ["users", "list"]                                # 명령은 python -m medicloak과 같다
    assert m.argv(["--db", "/x/m.db"]) == ["--db", "/x/m.db", "app"]
    assert m.argv(["--db", "/x/m.db", "users", "list"]) == ["--db", "/x/m.db", "users", "list"]
    assert m.argv(["--help"]) == ["--help"]


def test_web_manifest_and_icons():
    import struct
    pub = paths.ROOT / "frontend" / "public"
    man = json.loads((pub / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert man["display"] == "standalone" and man["start_url"] == "/" and man["short_name"] == "MediCloak"
    for icon in man["icons"]:
        png = (pub / icon["src"].lstrip("/")).read_bytes()
        w, h = struct.unpack(">II", png[16:24])                                        # PNG IHDR 너비 · 높이
        assert png[:8] == b"\x89PNG\r\n\x1a\n" and icon["sizes"] == f"{w}x{h}"
    assert any(i.get("purpose") == "maskable" for i in man["icons"])
    html = (paths.ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert 'rel="manifest"' in html and "cdn.jsdelivr.net" not in html                  # 글꼴도 앱 안에서 (인터넷 없이 열린다)
    for f in ("MediCloak.icns", "MediCloak.ico"):
        assert (paths.ROOT / "packaging" / "icons" / f).stat().st_size > 10_000


def test_menu_setup_again_opens_setup_next_time_even_with_llm_settings(tmp_path):
    desktop.write_env(tmp_path / ".env", dict(LLM_API_BASE="https://llm.example.org", LLM_MODEL="m", LLM_API_KEY="k"))
    desktop.save_config(tmp_path, dict(mode="local", llm="oracle"))
    first = desktop.DesktopApp(_args(tmp_path), None, home=tmp_path)
    first.window = _Window(dict(js_api=None))
    first.menu_setup_again()
    assert desktop.load_config(tmp_path) == dict(setup=True) and any("dialog:" in s for s in first.window.scripts)
    wv = _Webview()
    app = desktop.DesktopApp(_args(tmp_path), wv, home=tmp_path, prepare=_fake_prepare())
    t = _run(app)
    assert _until(lambda: wv.window.shown("setup")) and app.server is None           # .env가 다 있어도 처음 설정부터
    assert wv.window.api.choose_oracle() == dict(ok=True) and _until(lambda: wv.window.urls)
    assert desktop.load_config(tmp_path) == dict(mode="local", llm="oracle")           # 고르면 표시는 지워진다
    wv.window.destroy()
    t.join(15)
