# python -m medicloak … : MediCloak 운영 모드 (로그인 · 역할 분리 · DB · 가상 EMR · .env의 실제 LLM)
#
#   python -m medicloak init [--reset]        DB를 만들고 가상 EMR(Synthea 합성 환자)을 넣고 데모 계정을 만든다
#   python -m medicloak serve [--llm real]    서버를 켠다 (명령을 생략하면 serve). DB가 없으면 init부터 한다
#   python -m medicloak check-llm             .env를 읽어 실제 LLM에 짧은 요청을 한 번 보낸다 (키 값은 출력하지 않음)
#   python -m medicloak users …               계정 목록 · 추가 · 비밀번호 바꾸기
#
# 기본 위치: runs/medicloak/ (medicloak.db · demo_accounts.txt · emr_snapshot/ · engine/). runs/는 커밋하지 않는다.

from __future__ import annotations

import argparse
import getpass
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = ROOT / "runs" / "medicloak"
DEFAULT_DB = HOME / "medicloak.db"


def _store(db: Path):
    from webdemo.backend.store import Store
    return Store(db)


def _print_accounts(made, out_file: Path) -> None:
    print("[medicloak] 데모 계정을 만들었습니다 (이 비밀번호는 지금 한 번만 보여 줍니다)")
    for username, pw, role in made:
        print(f"    {username:<10} {'의료진' if role == 'clinician' else '보안 담당자':<7} {pw}")
    print(f"[medicloak] 같은 내용을 {out_file} 에 적었습니다 (권한 600). 바꾸려면 python -m medicloak users passwd <아이디>")


def init(db: Path, *, reset: bool = False, demo_password: str | None = None, quiet: bool = False) -> None:
    from webdemo.backend import emr
    from webdemo.backend.auth import ensure_demo_accounts
    if reset and db.exists():
        for p in (db, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")):
            if p.exists():
                p.unlink()
        print(f"[medicloak] 기존 DB를 지웠습니다: {db}")
    store = _store(db)
    try:
        if not emr.is_loaded(store):
            emr.load_csv(store, log=print)
        elif not quiet:
            print(f"[medicloak] 가상 EMR이 이미 들어 있습니다 (환자 {store.count('emr_patient'):,}명 · 사건 {store.count('emr_event'):,}건)")
        out_file = db.parent / "demo_accounts.txt"
        made = ensure_demo_accounts(store, demo_password or os.environ.get("MEDICLOAK_DEMO_PASSWORD") or None, out_file)
        if made:
            _print_accounts(made, out_file)
        elif not quiet:
            print(f"[medicloak] 계정이 이미 있습니다 ({store.count('app_user')}개). 목록: python -m medicloak users")
    finally:
        store.close()


def serve(a: argparse.Namespace) -> None:
    db = Path(a.db)
    from webdemo.backend import emr
    if not db.exists():
        print("[medicloak] DB가 없어 처음 준비를 합니다 (python -m medicloak init)")
        init(db, quiet=True)
    else:
        s0 = _store(db)
        loaded = emr.is_loaded(s0)
        s0.close()
        if not loaded:
            init(db, quiet=True)

    from medical.config import MedicalConfig
    from webdemo.backend.live import make_live_llm
    cfg = MedicalConfig(mode="exploration")
    try:
        live_llm, label = make_live_llm(a.llm, cfg, a.env_file)
    except Exception as exc:          # core.config.ConfigError (변수 이름만 담김) 등
        raise SystemExit(f"[medicloak] 대상 AI를 준비하지 못했습니다: {exc}\n"
                         f"  .env에 LLM_API_KEY · LLM_API_BASE · LLM_MODEL이 있는지 확인하세요 (python -m medicloak check-llm).\n"
                         f"  키 없이 화면만 보려면 --llm oracle 로 켜세요.")
    if a.build:
        from webdemo.__main__ import build_frontend
        try:
            build_frontend()
        except subprocess.CalledProcessError as exc:
            raise SystemExit(f"프런트엔드 빌드에 실패했습니다 (종료 코드 {exc.returncode}). 위 오류를 확인하세요.")
    try:
        import uvicorn
    except ImportError:
        raise SystemExit("uvicorn이 없습니다: pip install -r webdemo/requirements.txt")

    from webdemo.backend.app import DIST, Product, create_app
    from webdemo.backend.engine import Engine
    from webdemo.backend.persist import Persist

    store = _store(db)
    paths = emr.export_csv(store, db.parent / "emr_snapshot", log=print)
    first = Persist(store, None).next_id()          # type: ignore[arg-type]
    print(f"[medicloak] 위험 계산 엔진을 준비합니다 (10초 안팎) · 대상 AI: {label}")
    eng = Engine(db.parent / "engine", paths=paths, live_llm=live_llm, live_label=label, first_id=first,
                 llm_concurrency=a.llm_concurrency)
    product = Product(store=store, compare=not a.no_compare, keep=a.keep, cookie_secure=a.cookie_secure)
    app = create_app(eng, trial=a.trial, simulations=not a.no_sim, product=product)
    if not (DIST / "index.html").exists():
        print("[medicloak] 화면 파일(frontend/dist)이 없습니다. --build 를 붙여 한 번 빌드하세요. 지금은 API만 켭니다.", file=sys.stderr)
    print(f"[medicloak] 준비되었습니다: http://{a.host}:{a.port}  (계정: {db.parent / 'demo_accounts.txt'})")
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


def users(a: argparse.Namespace) -> None:
    from webdemo.backend import auth
    store = _store(Path(a.db))
    try:
        if a.users_cmd in (None, "list"):
            rows = store.users()
            if not rows:
                print("계정이 없습니다. python -m medicloak init 으로 데모 계정을 만드세요.")
            for u in rows:
                print(f"{u['username']:<12} {auth.ROLE_KO[u['role']]:<7} {u['display_name']:<8} {u['department'] or '':<10} {'사용' if u['active'] else '중지'}")
            return
        pw = _read_password(a)
        if a.users_cmd == "add":
            auth.add_user(store, a.username, a.name or a.username, a.role, a.department, pw)
            print(f"계정을 만들었습니다: {a.username} ({auth.ROLE_KO[a.role]})")
        elif a.users_cmd == "passwd":
            auth.set_password(store, a.username, pw)
            print(f"비밀번호를 바꿨습니다: {a.username} (로그인해 있던 세션은 모두 끊었습니다)")
    except ValueError as exc:
        raise SystemExit(str(exc))
    finally:
        store.close()


def _read_password(a: argparse.Namespace) -> str:
    if getattr(a, "password_stdin", False):
        return sys.stdin.readline().rstrip("\n")
    pw = getpass.getpass("새 비밀번호 (8자 이상): ")
    if getpass.getpass("한 번 더: ") != pw:
        raise SystemExit("두 비밀번호가 다릅니다.")
    return pw


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m medicloak", description="MediCloak: 의료 AI 재식별 방어 (로그인 · 가상 EMR · 실제 LLM)")
    ap.add_argument("--db", default=str(DEFAULT_DB), help=f"DB 파일 (기본 {DEFAULT_DB.relative_to(ROOT)})")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("init", help="DB · 가상 EMR · 데모 계정 준비")
    p.add_argument("--reset", action="store_true", help="기존 DB(대화 · 감사 기록 포함)를 지우고 새로 만든다")
    p.add_argument("--demo-password", default=None, help="데모 계정 셋이 같이 쓸 비밀번호 (없으면 계정마다 임의로 만든다)")

    p = sub.add_parser("serve", help="서버 켜기 (기본)")
    _serve_args(p)

    p = sub.add_parser("check-llm", help=".env 설정을 확인하고 실제 LLM에 짧은 요청을 보낸다")
    p.add_argument("--env-file", default=None, help="읽을 .env (기본: 저장소 루트의 .env)")
    p.add_argument("--no-send", action="store_true", help="요청은 보내지 않고 설정만 확인")

    p = sub.add_parser("users", help="계정 관리")
    us = p.add_subparsers(dest="users_cmd")
    us.add_parser("list", help="계정 목록")
    q = us.add_parser("add", help="계정 추가 (비밀번호는 입력받음)")
    q.add_argument("username")
    q.add_argument("--name", default=None, help="화면에 보일 이름")
    q.add_argument("--role", required=True, choices=("clinician", "security"))
    q.add_argument("--department", default=None)
    q.add_argument("--password-stdin", action="store_true", help="비밀번호를 표준 입력 한 줄로 받는다 (스크립트용)")
    q = us.add_parser("passwd", help="비밀번호 바꾸기")
    q.add_argument("username")
    q.add_argument("--password-stdin", action="store_true")

    _serve_args(ap, top=True)
    a = ap.parse_args(argv)
    if a.cmd == "init":
        init(Path(a.db), reset=a.reset, demo_password=a.demo_password)
    elif a.cmd == "check-llm":
        from webdemo.backend.live import check_llm
        raise SystemExit(0 if check_llm(a.env_file, send=not a.no_send) else 1)
    elif a.cmd == "users":
        users(a)
    else:
        serve(_defaults(a))


def _serve_args(p: argparse.ArgumentParser, top: bool = False) -> None:
    # 명령 없이 'python -m medicloak --llm oracle'처럼 써도 serve로 받는다
    kw = dict(default=argparse.SUPPRESS) if top else {}
    p.add_argument("--host", **(kw or dict(default="127.0.0.1")))
    p.add_argument("--port", type=int, **(kw or dict(default=8000)))
    p.add_argument("--llm", choices=("real", "dry-run", "oracle"), **(kw or dict(default="real")),
                   help="의료진 대화의 대상 AI: real(.env의 실제 모델, 기본) · dry-run(배선 확인용 가짜) · oracle(결정적 응답기)")
    p.add_argument("--env-file", **(kw or dict(default=None)), help="읽을 .env (기본: 저장소 루트의 .env)")
    p.add_argument("--llm-concurrency", type=int, **(kw or dict(default=1)), help="동시에 보내는 LLM 요청 수 (기본 1)")
    p.add_argument("--build", action="store_true", **(kw or {}), help="시작 전에 frontend/를 빌드한다 (npm 필요)")
    p.add_argument("--no-sim", action="store_true", **(kw or {}), help="관제 화면용 레드팀 시뮬레이션 대화를 만들지 않는다")
    p.add_argument("--no-compare", action="store_true", **(kw or {}), help="의료진 대화에서 비교 갈래(C0 · C1S)를 계산하지 않는다 (호출 줄이기)")
    p.add_argument("--trial", **(kw or dict(default=None)), help="의료진이 처음 로그인했을 때 열 환자 (기본 T0014)")
    p.add_argument("--keep", type=int, **(kw or dict(default=12)), help="의료진마다 메모리에 둘 대화 수 (넘으면 DB에만)")
    p.add_argument("--cookie-secure", action="store_true", **(kw or {}), help="https로만 로그인 쿠키를 보낸다 (https 운영)")


def _defaults(a: argparse.Namespace) -> argparse.Namespace:
    for k, v in dict(host="127.0.0.1", port=8000, llm="real", env_file=None, llm_concurrency=1, build=False, no_sim=False,
                     no_compare=False, trial=None, keep=12, cookie_secure=False).items():
        if not hasattr(a, k):
            setattr(a, k, v)
    return a
