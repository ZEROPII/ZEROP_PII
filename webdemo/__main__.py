# python -m webdemo [--build] [--host 127.0.0.1] [--port 8000] [--trial T0014] [--no-sim]
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"


def build_frontend() -> None:
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("npm이 없습니다. Node.js 18 이상을 설치한 뒤 다시 실행하세요 (https://nodejs.org).")
    if not (FRONTEND / "node_modules").exists():
        print("[webdemo] 프런트엔드 패키지를 설치합니다 (처음 한 번, 1분 안팎)")
        subprocess.run([npm, "install", "--no-audit", "--no-fund"], cwd=FRONTEND, check=True)
    print("[webdemo] 화면을 빌드합니다 (npm run build:demo)")
    subprocess.run([npm, "run", "build:demo"], cwd=FRONTEND, check=True)


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m webdemo", description="Zero PII 의료 AI 데모 (의료진 화면 + 보안 관제, LLM 호출 없음, API 키 불필요)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--build", action="store_true", help="시작 전에 frontend/를 빌드한다 (npm 필요)")
    ap.add_argument("--trial", default=None, help="의료진 화면에서 처음 보여 줄 질의 환자 (기본 T0014)")
    ap.add_argument("--no-sim", action="store_true", help="관제 화면용 레드팀 시뮬레이션 대화를 만들지 않는다")
    ap.add_argument("--workdir", default=None, help="엔진·레드팀 실행 기록을 둘 폴더 (기본: runs/webdemo)")
    a = ap.parse_args()
    if a.workdir:
        os.environ["WEBDEMO_WORKDIR"] = a.workdir
    if a.trial:
        os.environ["WEBDEMO_TRIAL"] = a.trial
    if a.no_sim:
        os.environ["WEBDEMO_NO_SIM"] = "1"
    if a.build:
        try:
            build_frontend()
        except subprocess.CalledProcessError as exc:
            raise SystemExit(f"프런트엔드 빌드에 실패했습니다 (종료 코드 {exc.returncode}). 위 오류를 확인하세요.")
    try:
        import uvicorn
    except ImportError:
        raise SystemExit("uvicorn이 없습니다: pip install -r webdemo/requirements.txt")
    if not (FRONTEND / "dist" / "index.html").exists():
        print("[webdemo] 화면 파일(frontend/dist)이 없습니다. python -m webdemo --build 로 한 번 빌드하세요. 지금은 API만 켭니다.", file=sys.stderr)
    print(f"[webdemo] 데이터를 올리는 중입니다 (10초 안팎). 준비되면 http://{a.host}:{a.port} 를 여세요.")
    uvicorn.run("webdemo.backend.app:app", host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
