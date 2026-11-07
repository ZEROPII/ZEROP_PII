# python -m medicloak … : MediCloak 운영 모드 (로그인 · 역할 분리 · DB · 가상 EMR · .env의 실제 LLM)
#
#   python -m medicloak init [--reset]        DB를 만들고 가상 EMR(Synthea 합성 환자)을 넣고 처음 쓸 계정을 만든다
#   python -m medicloak serve [--llm real]    서버를 켠다 (명령을 생략하면 serve). DB가 없으면 init부터 한다
#   python -m medicloak check-llm             .env를 읽어 실제 LLM에 짧은 요청을 한 번 보낸다 (키 값은 출력하지 않음)
#   python -m medicloak users …               계정 목록 · 추가 · 비밀번호 바꾸기
#
# 기본 위치: runs/medicloak/ (medicloak.db · initial_accounts.txt · emr_snapshot/ · engine/). runs/는 커밋하지 않는다.

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
ACCOUNTS_FILE = "initial_accounts.txt"            # init이 처음 쓸 계정을 적는 파일 (DB 폴더)
LEGACY_ACCOUNTS_FILE = "demo_accounts.txt"       # 예전 init이 쓴 이름


def _store(db: Path):
    from webdemo.backend.store import Store
    return Store(db)


def _print_accounts(made, out_file: Path) -> None:
    print("[medicloak] 처음 쓸 계정 셋을 만들었습니다 (이 비밀번호는 지금 한 번만 보여 줍니다)")
    for username, pw, role in made:
        print(f"    {username:<10} {'의료진' if role == 'clinician' else '보안 담당자':<7} {pw}")
    print(f"[medicloak] 같은 내용을 {out_file} 에 적었습니다 (권한 600). 바꾸려면 python -m medicloak users passwd <아이디>")


def accounts_file(folder: Path) -> Path | None:
    """init이 처음 쓸 계정을 적은 파일. 예전 이름(demo_accounts.txt)으로 만든 것도 찾는다."""
    return next((p for p in (folder / ACCOUNTS_FILE, folder / LEGACY_ACCOUNTS_FILE) if p.exists()), None)


def init(db: Path, *, reset: bool = False, initial_password: str | None = None, quiet: bool = False) -> None:
    from webdemo.backend import emr
    from webdemo.backend.auth import ensure_initial_accounts
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
            print(f"[medicloak] EMR 데이터가 이미 들어 있습니다 (환자 {store.count('emr_patient'):,}명 · 사건 {store.count('emr_event'):,}건)")
        out_file = db.parent / ACCOUNTS_FILE
        pw = initial_password or os.environ.get("MEDICLOAK_INITIAL_PASSWORD") or os.environ.get("MEDICLOAK_DEMO_PASSWORD") or None
        made = ensure_initial_accounts(store, pw, out_file)
        if made:
            _print_accounts(made, out_file)
        elif not quiet:
            print(f"[medicloak] 계정이 이미 있습니다 ({store.count('app_user')}개). 목록: python -m medicloak users")
    finally:
        store.close()


def serve(a: argparse.Namespace) -> None:
    from webdemo.backend.autocheck import valid_daily
    try:                                                # 무거운 준비 전에 옵션부터 확인한다
        daily = valid_daily(a.auto_redteam_daily)
    except ValueError as exc:
        raise SystemExit(f"[medicloak] {exc}") from None
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
        live_llm, label = make_live_llm(a.llm, cfg, a.env_file, role_models=dict(extractor=a.extractor_model, rewriter=a.rewriter_model))
    except Exception as exc:          # core.config.ConfigError (변수 이름만 담김) 등
        raise SystemExit(f"[medicloak] 대상 AI를 준비하지 못했습니다: {exc}\n"
                         f"  .env에 LLM_API_KEY · LLM_API_BASE · LLM_MODEL이 있는지 확인하세요 (python -m medicloak check-llm).\n"
                         f"  키 없이 화면만 보려면 --llm oracle 로 켜세요.")
    if a.build:
        from webdemo.__main__ import build_frontend
        try:
            build_frontend(prefix="[medicloak]")
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
    from webdemo.backend.ledger import DisclosureLedger
    ledger = DisclosureLedger(store, window_days=a.ledger_window_days) if a.ledger == "on" else None
    eng = Engine(db.parent / "engine", log=lambda s: print(s.replace("[webdemo]", "[medicloak]", 1)), paths=paths, live_llm=live_llm, live_label=label, first_id=first,
                 llm_concurrency=a.llm_concurrency, live_rule_extract=not a.no_rule_extract, answer_style=a.answer_style == "on",
                 recent_visit=a.visit == "recent", ledger=ledger, input_gate=a.input_gate == "on",
                 answer_budget=a.answer_budget if a.answer_budget > 0 else None, sensitivity=a.sensitivity == "on", strict_k=a.strict_k)
    pr = eng.protections()
    print("[medicloak] 보강 (ADR-0032): 공개 원장 " + (f"켬 · {a.ledger_window_days:g}일" if ledger is not None else "끔")
          + f" · 입력 게이팅 {'켬' if eng.input_gate else '끔'} · 답 시간 예산 " + (f"{eng.answer_budget:g}초" if eng.answer_budget else "끔")
          + " · 민감도 등급 " + (f"켬 (후보 {a.strict_k}명 · 검색 제외 {pr['sensitivity']['excludedPatients']}명)" if eng.sensitivity else "끔"))
    auto = a.auto_redteam if a.llm == "real" else "off"                 # 결정적 응답기 · 연결 점검 모드는 점검할 실제 LLM이 없다
    product = Product(store=store, compare=not a.no_compare, keep=a.keep, cookie_secure=a.cookie_secure,
                      auto_redteam=auto, auto_daily=daily if a.llm == "real" else None, prefetch=a.prefetch == "on")
    app = create_app(eng, simulations=False, product=product)          # 운영 모드: 환자는 EMR에서 열 때 정해진다
    if not (DIST / "index.html").exists():
        print("[medicloak] 화면 파일(frontend/dist)이 없습니다. --build 를 붙여 한 번 빌드하세요. 지금은 API만 켭니다.", file=sys.stderr)
    acc = accounts_file(db.parent)
    print(f"[medicloak] 준비되었습니다: http://{a.host}:{a.port}" + (f"  (처음 쓸 계정: {acc})" if acc else ""))
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


def users(a: argparse.Namespace) -> None:
    from webdemo.backend import auth
    store = _store(Path(a.db))
    try:
        if a.users_cmd in (None, "list"):
            rows = store.users()
            if not rows:
                print("계정이 없습니다. python -m medicloak init 으로 처음 쓸 계정을 만드세요.")
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
    ap = argparse.ArgumentParser(prog="python -m medicloak", description="MediCloak: 진료 지원 AI 개인정보 보호 (로그인 · EMR 연동 · 실제 LLM)")
    ap.add_argument("--db", default=str(DEFAULT_DB), help=f"DB 파일 (기본 {DEFAULT_DB.relative_to(ROOT)})")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("init", help="DB · EMR 데이터 · 처음 쓸 계정 준비")
    p.add_argument("--reset", action="store_true", help="기존 DB(대화 · 감사 기록 포함)를 지우고 새로 만든다")
    p.add_argument("--initial-password", default=None, help="처음 계정 셋이 같이 쓸 비밀번호 (없으면 계정마다 임의로 만든다)")
    p.add_argument("--demo-password", dest="initial_password", help=argparse.SUPPRESS)          # 예전 이름

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
        init(Path(a.db), reset=a.reset, initial_password=a.initial_password)
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
                   help="의료진 대화의 대상 AI: real(.env의 실제 모델, 기본) · dry-run(연결 점검, LLM을 부르지 않음) · oracle(결정적 응답기)")
    p.add_argument("--env-file", **(kw or dict(default=None)), help="읽을 .env (기본: 저장소 루트의 .env)")
    p.add_argument("--llm-concurrency", type=int, **(kw or dict(default=1)), help="동시에 보내는 LLM 요청 수 (기본 1)")
    p.add_argument("--build", action="store_true", **(kw or {}), help="시작 전에 frontend/를 빌드한다 (npm 필요)")
    p.add_argument("--no-compare", action="store_true", **(kw or {}), help="의료진 대화에서 비교 갈래(C0 · C1S)를 계산하지 않는다 (호출 줄이기)")
    p.add_argument("--keep", type=int, **(kw or dict(default=12)), help="의료진마다 메모리에 둘 대화 수 (넘으면 DB에만)")
    p.add_argument("--cookie-secure", action="store_true", **(kw or {}), help="https로만 로그인 쿠키를 보낸다 (https 운영)")
    p.add_argument("--no-rule-extract", action="store_true", **(kw or {}),
                   help="실제 LLM 대화에서 나이 · 날짜 규칙 추출을 끈다 (기본은 켬, ADR-0021)")
    p.add_argument("--extractor-model", **(kw or dict(default=None)), help="추출기(단서 뽑기 · 다시 확인)만 다른 모델로 (빠른 모델 권장, 기본: .env LLM_MODEL)")
    p.add_argument("--rewriter-model", **(kw or dict(default=None)), help="재작성기만 다른 모델로 (기본: .env LLM_MODEL)")
    p.add_argument("--answer-style", choices=("on", "off"), **(kw or dict(default="on")),
                   help="실제 LLM 대상 AI에 짧은 답 형식을 붙인다: 의료진 대화와 레드팀에 같이 (기본 on, ADR-0025)")
    p.add_argument("--auto-redteam", choices=("change", "off"), **(kw or dict(default="change")),
                   help="change: 판정 규칙 판 · 답 형식 · 모델 · 규칙 추출이 마지막 점검과 다르면 켤 때 '유형마다 1명' 레드팀을 뒤에서 돌리고 "
                        "직전 점검과 비교한다 (기본, --llm real일 때만). off: 끔 (ADR-0028)")
    p.add_argument("--auto-redteam-daily", metavar="HH:MM", **(kw or dict(default=None)),
                   help="매일 이 시각(서버 시계)에도 '유형마다 1명' 레드팀을 돌린다 (기본: 안 함)")
    p.add_argument("--prefetch", choices=("on", "off"), **(kw or dict(default="on")),
                   help="on: 외래 목록에서 환자 · 진료 목적을 고르면 첫 답을 뒤에서 미리 만들어 '열기'를 짧게 한다 (기본, ADR-0029). "
                        "off: 열 때만 부른다 (고르기만 하고 열지 않은 환자의 호출이 없다)")
    p.add_argument("--visit", choices=("recent", "research"), **(kw or dict(default="recent")),
                   help="의료진 대화의 진료 기준: recent(진료 목적마다 가장 최근 진료, 기본, ADR-0029) · "
                        "research(연구 계획 기준: 가장 많이 나온 진단 범주의 첫 진료)")
    # 연구자 4인 검토 보강 (ADR-0032). 모두 의료진 대화에만 걸고, 레드팀 · 연구 실행은 그대로 둔다
    p.add_argument("--ledger", choices=("on", "off"), **(kw or dict(default="on")),
                   help="on: 같은 과거 환자에 대해 다른 대화 · 다른 의료진이 이미 공개한 값까지 합쳐 판정한다 (과거 환자 단위 공개 원장, 기본). "
                        "off: 대화마다 따로 (예전 동작)")
    p.add_argument("--ledger-window-days", type=float, **(kw or dict(default=90.0)),
                   help="공개 원장에서 합쳐 볼 기간(일, 기본 90). 0이면 기간 없이 모두")
    p.add_argument("--input-gate", choices=("on", "off"), **(kw or dict(default="on")),
                   help="on: 대상 AI에 지금 공개할 수 있는 값만 넣는다 (나머지는 넓히거나 '(비공개)', 기본). off: 사례 문서 원문 그대로 (예전 동작)")
    p.add_argument("--answer-budget", type=float, **(kw or dict(default=45.0)),
                   help="한 답의 공개 처리 시간 예산(초, 기본 45). 넘기면 재작성 · 다시 확인을 멈추고 답 대신 안내 문장을 보낸다. 0이면 끔")
    p.add_argument("--sensitivity", choices=("on", "off"), **(kw or dict(default="on")),
                   help="on: 정신 건강 · 물질 사용 · 생식 · HIV 값은 후보가 --strict-k명 이상일 때만 내고, 미성년 시기 물질 사용 장애 "
                        "과거 환자는 유사 사례 검색에서 뺀다 (기본). off: 예전 동작")
    p.add_argument("--strict-k", type=int, **(kw or dict(default=10)), help="민감 값을 내보낼 수 있는 최소 후보 수 (기본 10)")


def _defaults(a: argparse.Namespace) -> argparse.Namespace:
    for k, v in dict(host="127.0.0.1", port=8000, llm="real", env_file=None, llm_concurrency=1, build=False,
                     no_compare=False, keep=12, cookie_secure=False, no_rule_extract=False, answer_style="on",
                     extractor_model=None, rewriter_model=None, auto_redteam="change", auto_redteam_daily=None,
                     prefetch="on", visit="recent", ledger="on", ledger_window_days=90.0, input_gate="on", answer_budget=45.0,
                     sensitivity="on", strict_k=10).items():
        if not hasattr(a, k):
            setattr(a, k, v)
    return a
