# python -m webdemo [--host 127.0.0.1] [--port 8000]
from __future__ import annotations

import argparse
import os


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m webdemo", description="의료 POC 데모 웹앱 (LLM 호출 없음, API 키 불필요)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--workdir", default=None, help="엔진·레드팀 실행 기록을 둘 폴더 (기본: runs/webdemo)")
    a = ap.parse_args()
    if a.workdir:
        os.environ["WEBDEMO_WORKDIR"] = a.workdir
    try:
        import uvicorn
    except ImportError:
        raise SystemExit("uvicorn이 없습니다: pip install -r webdemo/requirements.txt")
    print(f"[webdemo] 데이터를 올리는 중입니다 (10초 안팎). 준비되면 http://{a.host}:{a.port} 를 여세요.")
    uvicorn.run("webdemo.backend.app:app", host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
