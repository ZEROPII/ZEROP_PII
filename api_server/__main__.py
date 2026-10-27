# python -m api_server [--dry-run] [--arm C0|C1|C1S] [--trial T0001] [--host 127.0.0.1] [--port 8000]
#
# 실제 LLM 모드는 루트 .env(LLM_API_KEY · LLM_API_BASE · LLM_MODEL)를 읽는다. 키 값은 출력·기록하지 않는다.
# --dry-run 은 medical.llm.MockRoleLLM(배선 확인용 가짜 LLM)을 쓴다. 이때 숫자는 연구 결과로서 의미가 없다.

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from api_server.engine import ApiSettings, ResearchWorkspace


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m api_server")
    ap.add_argument("--dry-run", action="store_true", help="가짜 LLM (토큰 0, 숫자 의미 없음)")
    ap.add_argument("--arm", choices=["C0", "C1", "C1S"], default="C1")
    ap.add_argument("--trial", default="T0001", help="연구 계획(plan_trials)의 trial id = 질의 환자")
    ap.add_argument("--out", default=None, help="서버 쪽 기록 폴더 (기본 runs/api/session_<시각>)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--cors", default="http://localhost:5173,http://127.0.0.1:5173", help="허용 Origin (쉼표 구분, 빈 값이면 끔)")
    a = ap.parse_args(argv)

    import uvicorn
    from api_server.app import create_app

    settings = ApiSettings(llm="dry-run" if a.dry_run else "real", arm=a.arm, trial_id=a.trial, out=Path(a.out) if a.out else None)
    print("연구 컨텍스트를 준비합니다 (문서·kcalc 적재, 약 10초)…", flush=True)
    ws = ResearchWorkspace(settings)          # 시작 때 한 번 만들어 설정 오류를 바로 알린다
    print(f"준비 완료: arm={settings.arm} llm={settings.llm} trial={settings.trial_id} P_ref={ws.ctx.p_ref} 기록={ws.out}", flush=True)
    first = [ws]                              # 첫 호출은 미리 만든 것, /api/session/reset 뒤로는 새로 만든다
    app = create_app(settings, workspace_factory=lambda: first.pop() if first else ResearchWorkspace(settings),
                     cors_origins=[o for o in a.cors.split(",") if o.strip()])
    uvicorn.run(app, host=a.host, port=a.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
