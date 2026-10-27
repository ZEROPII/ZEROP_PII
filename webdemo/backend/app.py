# 데모 API (FastAPI). 프론트엔드(webdemo/frontend)도 같은 서버가 정적 파일로 내보낸다.
#
#   의료진 화면      GET  /api/sessions/{id}/clinician?arm=C1     공개된 답만 (원 응답·원래 값 없음)
#   보안 담당자 화면 GET  /api/sessions/{id}/security             세 조건의 원 응답·Defender 판정·k·Validated k
#   레드팀 배치      POST /api/redteam · GET /api/redteam/{id}    medical.experiment를 그대로 돌림
#   저장된 POC 결과  GET  /api/poc                                webdemo/data/poc_summary.json (2026-10-23 POC 집계)

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from webdemo.backend.engine import ARMS, DemoError, Engine, summarize

HERE = Path(__file__).resolve().parent
FRONTEND = HERE.parent / "frontend"
POC_FILE = HERE.parent / "data" / "poc_summary.json"


class NewSession(BaseModel):
    trial_id: str = Field(..., examples=["T0014"])
    profile: str = "staged"
    fuzzer: str = "uniform"


class Step(BaseModel):
    seed_id: str | None = None          # 없으면 퍼저가 고른다
    arm: str = "C1"                     # 질문 후보·퍼저 선택에 쓰는 조건 (화면에 보이는 조건)


class Preview(BaseModel):
    seed_id: str
    arm: str = "C1"


class Job(BaseModel):
    profile: str = "staged"
    fuzzer: str = "uniform"
    per_type: int | None = 10           # 조회 유형마다 질의 환자 수. None이면 전원(296명)


def create_app(engine: Engine | None = None) -> FastAPI:
    state: dict[str, Engine] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state["engine"] = engine or Engine(Path(os.environ["WEBDEMO_WORKDIR"]) if os.environ.get("WEBDEMO_WORKDIR") else None)
        yield

    app = FastAPI(title="ZEROP_PII 의료 데모", version="0.1", lifespan=lifespan)

    def eng() -> Engine:
        return state["engine"]

    def arm_ok(arm: str) -> str:
        if arm not in ARMS:
            raise HTTPException(400, f"arm은 {', '.join(ARMS)} 중 하나입니다.")
        return arm

    def sess(sid: str):
        try:
            return eng().session(sid)
        except KeyError:
            raise HTTPException(404, f"없는 세션입니다: {sid} (서버를 다시 켜면 세션이 지워집니다)")

    @app.exception_handler(DemoError)
    async def demo_error(_, exc: DemoError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        return eng().meta()

    @app.get("/api/patients")
    def patients() -> list[dict[str, Any]]:
        return eng().patients()

    @app.post("/api/sessions")
    def new_session(body: NewSession) -> dict[str, Any]:
        s = eng().new_session(body.trial_id, body.profile, body.fuzzer)
        return dict(id=s.id)

    @app.get("/api/sessions")
    def sessions() -> list[dict[str, Any]]:
        return [s._summary() for s in eng().sessions.values()]

    @app.get("/api/sessions/{sid}/clinician")
    def clinician(sid: str, arm: str = Query("C1")) -> dict[str, Any]:
        with eng().lock:
            return sess(sid).clinician_view(arm_ok(arm))

    @app.get("/api/sessions/{sid}/security")
    def security(sid: str) -> dict[str, Any]:
        with eng().lock:
            return sess(sid).security_view()

    @app.get("/api/sessions/{sid}/questions")
    def questions(sid: str, arm: str = Query("C1")) -> list[dict[str, Any]]:
        with eng().lock:
            return sess(sid).questions(arm_ok(arm))

    @app.post("/api/sessions/{sid}/preview")
    def preview(sid: str, body: Preview) -> dict[str, Any]:
        with eng().lock:
            return sess(sid).preview(body.seed_id, arm_ok(body.arm))

    @app.post("/api/sessions/{sid}/turns")
    def turn(sid: str, body: Step) -> dict[str, Any]:
        with eng().lock:
            return sess(sid).step(body.seed_id, arm_ok(body.arm))

    @app.post("/api/sessions/{sid}/run")
    def run_all(sid: str, arm: str = Query("C1")) -> dict[str, Any]:
        with eng().lock:
            s = sess(sid)
            n = s.run_to_end(arm_ok(arm))
            return dict(turns_added=n, turn=s.turn)

    @app.post("/api/redteam")
    def start_job(body: Job) -> dict[str, Any]:
        return eng().start_job(body.profile, body.fuzzer, body.per_type).as_dict()

    @app.get("/api/redteam")
    def jobs() -> list[dict[str, Any]]:
        return [dict(j.as_dict(), result=None) for j in eng().jobs.values()]

    @app.get("/api/redteam/{jid}")
    def job(jid: str) -> dict[str, Any]:
        if jid not in eng().jobs:
            raise HTTPException(404, jid)
        return eng().jobs[jid].as_dict()

    @app.get("/api/poc")
    def poc() -> dict[str, Any]:
        if not POC_FILE.exists():
            raise HTTPException(404, "webdemo/data/poc_summary.json이 없습니다.")
        raw = json.loads(POC_FILE.read_text(encoding="utf-8"))
        out = {name: summarize(v) for name, v in raw.items() if isinstance(v, dict) and "arms" in v}
        out["fuzzer_compare"] = {k.replace("fuzzer_compare_", ""): v for k, v in raw.items() if k.startswith("fuzzer_compare_")}
        return out

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(FRONTEND / "index.html")

    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
    return app


app = create_app()          # uvicorn webdemo.backend.app:app
