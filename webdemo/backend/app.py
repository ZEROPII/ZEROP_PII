# 데모 API (FastAPI). 빌드한 프런트엔드(frontend/dist)도 같은 서버가 내보낸다.
#
#   의료진 화면 (frontend/ 계약, api_server와 같은 경로)
#     GET  /api/workspace · /api/protection-policy · /api/patient-context · /api/cases?patientContextId= · /api/risk-states
#     GET  /api/cases/{id}/session · /disclosures · /policy-decision · /suggestions
#     POST /api/cases/{id}/messages · /preflight          POST /api/session/reset {trialId}     GET /api/clinic/patients
#     GET  /api/clinic/messages · POST /api/clinic/messages {kind, text, caseId}   보안 담당자와 주고받는 메시지 (세부 정보 요청 · 답장)
#   보안 담당자 관제
#     GET  /api/monitor/overview · /api/monitor/sessions/{sid} · /api/monitor/audit
#     POST /api/monitor/sessions/{sid}/reveal {reason} · /review {action, note} · /messages {kind, text, case}   GET …/messages
#   레드팀·결과
#     POST /api/redteam · GET /api/redteam/{id} · GET /api/poc (webdemo/data/poc_summary.json, 2026-10-23 POC 집계)
#   평가 지표 대시보드: GET /eval/ (eval_demo/ 정적 페이지)
#   의료 용어 RAG: GET /api/terminology/status · /search · /{node_id} · 목록, POST /api/terminology/detect (medical/terminology_api.py)
#   세션 직접 조작 (POC 재현·테스트용)
#     /api/meta · /api/patients · /api/sessions …

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from medical.config import ROOT
from medical.terminology_api import terminology_router
from webdemo.backend.clinic import ClinicDesk, Conflict, NotFound
from webdemo.backend.engine import ARMS, DemoError, Engine, summarize
from webdemo.backend.monitor import REVIEW_KO, Monitor

HERE = Path(__file__).resolve().parent
DIST = Path(os.environ.get("WEBDEMO_DIST") or ROOT / "frontend" / "dist")
POC_FILE = HERE.parent / "data" / "poc_summary.json"
EVAL_DIR = ROOT / "eval_demo"
FEATURED = ("T0014", "T0010", "T0024", "T0036", "T0005", "T0016", "T0037", "T0001")


class NewSession(BaseModel):
    trial_id: str = Field(..., examples=["T0014"])
    profile: str = "staged"
    fuzzer: str = "uniform"


class Step(BaseModel):
    seed_id: str | None = None          # 없으면 퍼저가 고른다
    arm: str = "C1"


class Preview(BaseModel):
    seed_id: str
    arm: str = "C1"


class Job(BaseModel):
    profile: str = "staged"
    fuzzer: str = "uniform"
    per_type: int | None = 10           # 조회 유형마다 질의 환자 수. None이면 전원(296명)


class MessageIn(BaseModel):
    sessionId: str
    question: str
    clientMessageId: str


class PreflightIn(BaseModel):
    sessionId: str
    question: str


class ResetIn(BaseModel):
    trialId: str | None = None


class RevealIn(BaseModel):
    reason: str = Field(..., min_length=2, max_length=200)


class ReviewIn(BaseModel):
    action: str
    note: str | None = Field(None, max_length=500)


class ClinicNoteIn(BaseModel):
    """의료진 → 보안 담당자. kind: access_request(세부 정보 요청) · reply(확인 요청에 답장)."""
    kind: str = "access_request"
    text: str = Field(..., min_length=2, max_length=500)
    caseId: str | None = None


class SecurityNoteIn(BaseModel):
    """보안 담당자 → 의료진. kind: reply(답장) · check_request(확인 요청). case는 '사례1' 같은 사례 표시."""
    kind: str = "reply"
    text: str = Field(..., min_length=2, max_length=500)
    case: str | None = None


def create_app(engine: Engine | None = None, *, trial: str | None = None, simulations: bool | None = None) -> FastAPI:
    state: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        eng = engine or Engine(Path(os.environ["WEBDEMO_WORKDIR"]) if os.environ.get("WEBDEMO_WORKDIR") else None)
        state["engine"] = eng
        state["monitor"] = Monitor(eng)
        state["clinic"] = ClinicDesk(eng, trial or os.environ.get("WEBDEMO_TRIAL") or "T0014")
        sims = simulations if simulations is not None else os.environ.get("WEBDEMO_NO_SIM") != "1"
        if sims:
            state["monitor"].seed_simulations()
        yield

    app = FastAPI(title="MediCloak 의료 AI 데모", version="0.2", lifespan=lifespan)

    def eng() -> Engine:
        return state["engine"]

    def clinic() -> ClinicDesk:
        return state["clinic"]

    def mon() -> Monitor:
        return state["monitor"]

    def arm_ok(arm: str) -> str:
        if arm not in ARMS:
            raise HTTPException(400, f"arm은 {', '.join(ARMS)} 중 하나입니다.")
        return arm

    def sess(sid: str):
        try:
            return eng().session(sid)
        except KeyError:
            raise HTTPException(404, f"없는 대화입니다: {sid} (서버를 다시 켜면 대화가 지워집니다)")

    def guard(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except NotFound:
            raise HTTPException(404, "없는 사례 또는 환자 맥락입니다.")
        except Conflict as exc:
            raise HTTPException(409, str(exc))
        except DemoError as exc:
            raise HTTPException(400, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @app.exception_handler(DemoError)
    async def demo_error(_, exc: DemoError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    # ── 의료진 화면 ──────────────────────────────────────
    r = APIRouter(prefix="/api")

    @r.get("/health")
    def health() -> dict[str, Any]:
        return dict(status="ok", backend="webdemo", target="결정적 응답기 (LLM 없음)", monitor=True, trialId=clinic().session.trial_id,
                    simulations=mon().sim_status)

    @r.get("/workspace")
    def workspace() -> dict[str, Any]:
        return clinic().environment()

    @r.get("/protection-policy")
    def protection_policy() -> dict[str, Any]:
        return clinic().policy()

    @r.get("/patient-context")
    def patient_context() -> dict[str, Any]:
        return clinic().patient_context()

    @r.get("/cases")
    def cases(patientContextId: str) -> list[dict[str, Any]]:
        return guard(lambda: clinic().similar_cases(patientContextId))

    @r.get("/cases/{case_id}/session")
    def conversation(case_id: str) -> dict[str, Any]:
        return guard(lambda: clinic().conversation(case_id))

    @r.post("/cases/{case_id}/messages")
    def messages(case_id: str, body: MessageIn) -> dict[str, Any]:
        if not body.question.strip():
            raise HTTPException(422, "질문이 비어 있습니다.")
        return guard(lambda: clinic().ask(case_id, body.sessionId, body.question, body.clientMessageId))

    @r.post("/cases/{case_id}/preflight")
    def preflight(case_id: str, body: PreflightIn) -> dict[str, Any]:
        return guard(lambda: clinic().preflight(case_id, body.sessionId, body.question))

    @r.get("/cases/{case_id}/suggestions")
    def suggestions(case_id: str) -> list[dict[str, Any]]:
        return guard(lambda: clinic().suggestions(case_id))

    @r.get("/risk-states")
    def risk_states() -> list[dict[str, Any]]:
        c = clinic()
        return [c.risk_state(cid) for cid in c.slots]

    @r.get("/cases/{case_id}/disclosures")
    def disclosures(case_id: str) -> dict[str, Any]:
        return guard(lambda: clinic().disclosures(case_id))

    @r.get("/cases/{case_id}/policy-decision")
    def policy_decision(case_id: str) -> dict[str, Any]:
        return guard(lambda: clinic().policy_decision(case_id))

    @r.post("/session/reset")
    def reset(body: ResetIn | None = None) -> dict[str, Any]:
        tid = (body.trialId if body else None) or clinic().session.trial_id
        guard(lambda: clinic().start(tid))
        mon().log("clinic_start", clinic().session, actor="의료진 (데모)")
        return dict(status="ok", workspaceId=clinic().workspace_id, trialId=tid)

    @r.get("/clinic/messages")
    def clinic_messages() -> list[dict[str, Any]]:
        return clinic().messages()

    @r.post("/clinic/messages")
    def post_clinic_message(body: ClinicNoteIn) -> list[dict[str, Any]]:
        c = clinic()
        ref = guard(lambda: c.ref_of(body.caseId)) if body.caseId else None
        guard(lambda: mon().post_message(c.session, "clinician", body.kind, body.text, ref))
        return c.messages()

    @r.get("/clinic/patients")
    def clinic_patients() -> list[dict[str, Any]]:
        out = []
        for p in eng().patients():
            panel = {x["label"]: x["value"] for x in p["panel"]}
            out.append(dict(trialId=p["trial_id"], qtypeLabel=p["qtype_label"], featured=p["trial_id"] in FEATURED,
                            ageSex=panel.get("연령 / 성별"), mainDx=panel.get("주진단"), item=panel.get("고려 중인 처치")))
        return out

    # ── 관제 ─────────────────────────────────────────────
    @r.get("/monitor/overview")
    def overview() -> dict[str, Any]:
        return mon().overview()

    @r.get("/monitor/sessions/{sid}")
    def monitor_session(sid: str) -> dict[str, Any]:
        return mon().detail(sess(sid))

    @r.post("/monitor/sessions/{sid}/reveal")
    def reveal(sid: str, body: RevealIn) -> dict[str, Any]:
        return mon().reveal(sess(sid), body.reason.strip())

    @r.post("/monitor/sessions/{sid}/review")
    def review(sid: str, body: ReviewIn) -> dict[str, Any]:
        if body.action not in REVIEW_KO:
            raise HTTPException(422, f"action은 {', '.join(REVIEW_KO)} 중 하나입니다.")
        s = sess(sid)
        return guard(lambda: mon().review(s, body.action, body.note))

    @r.get("/monitor/sessions/{sid}/messages")
    def security_thread(sid: str) -> dict[str, Any]:
        return mon().thread(sess(sid))          # 원문을 열람한 상세를 다시 받지 않고 메시지만 새로 고칠 때

    @r.post("/monitor/sessions/{sid}/messages")
    def post_security_message(sid: str, body: SecurityNoteIn) -> dict[str, Any]:
        s = sess(sid)
        guard(lambda: mon().post_message(s, "security", body.kind, body.text, body.case))
        return mon().thread(s)

    @r.get("/monitor/audit")
    def audit() -> list[dict[str, Any]]:
        return list(reversed(mon().audit))

    # ── 세션 직접 조작 (POC 재현·테스트) ─────────────────
    @r.get("/meta")
    def meta() -> dict[str, Any]:
        return eng().meta()

    @r.get("/patients")
    def patients() -> list[dict[str, Any]]:
        return eng().patients()

    @r.post("/sessions")
    def new_session(body: NewSession) -> dict[str, Any]:
        s = eng().new_session(body.trial_id, body.profile, body.fuzzer)
        return dict(id=s.id)

    @r.get("/sessions")
    def sessions() -> list[dict[str, Any]]:
        return [s._summary() for s in eng().sessions.values()]

    @r.get("/sessions/{sid}/clinician")
    def clinician(sid: str, arm: str = Query("C1")) -> dict[str, Any]:
        with eng().lock:
            return sess(sid).clinician_view(arm_ok(arm))

    @r.get("/sessions/{sid}/security")
    def security(sid: str) -> dict[str, Any]:
        with eng().lock:
            return sess(sid).security_view()

    @r.get("/sessions/{sid}/questions")
    def questions(sid: str, arm: str = Query("C1")) -> list[dict[str, Any]]:
        with eng().lock:
            return sess(sid).questions(arm_ok(arm))

    @r.post("/sessions/{sid}/preview")
    def preview(sid: str, body: Preview) -> dict[str, Any]:
        with eng().lock:
            return sess(sid).preview(body.seed_id, arm_ok(body.arm))

    @r.post("/sessions/{sid}/turns")
    def turn(sid: str, body: Step) -> dict[str, Any]:
        with eng().lock:
            return sess(sid).step(body.seed_id, arm_ok(body.arm))

    @r.post("/sessions/{sid}/run")
    def run_all(sid: str, arm: str = Query("C1")) -> dict[str, Any]:
        with eng().lock:
            s = sess(sid)
            n = s.run_to_end(arm_ok(arm))
            return dict(turns_added=n, turn=s.turn)

    # ── 레드팀·결과 ──────────────────────────────────────
    @r.post("/redteam")
    def start_job(body: Job) -> dict[str, Any]:
        j = eng().start_job(body.profile, body.fuzzer, body.per_type).as_dict()
        mon().log("redteam_start", None, job=j["id"], per_type=body.per_type, fuzzer=body.fuzzer)
        return j

    @r.get("/redteam")
    def jobs() -> list[dict[str, Any]]:
        return [dict(j.as_dict(), result=None) for j in eng().jobs.values()]

    @r.get("/redteam/{jid}")
    def job(jid: str) -> dict[str, Any]:
        if jid not in eng().jobs:
            raise HTTPException(404, jid)
        return eng().jobs[jid].as_dict()

    @r.get("/poc")
    def poc() -> dict[str, Any]:
        if not POC_FILE.exists():
            raise HTTPException(404, "webdemo/data/poc_summary.json이 없습니다.")
        raw = json.loads(POC_FILE.read_text(encoding="utf-8"))
        out = {name: summarize(v) for name, v in raw.items() if isinstance(v, dict) and "arms" in v}
        out["fuzzer_compare"] = {k.replace("fuzzer_compare_", ""): v for k, v in raw.items() if k.startswith("fuzzer_compare_")}
        return out

    @r.api_route("/{rest:path}", methods=["GET", "POST"])
    def unknown(rest: str):
        raise HTTPException(404, f"없는 API 경로입니다: /api/{rest}")

    app.include_router(terminology_router())       # 의료 용어 RAG (/api/terminology/…). 아래 r의 '없는 경로' 처리보다 먼저
    app.include_router(r)

    # ── 평가 지표 대시보드 (eval_demo/, 빌드 없는 정적 페이지) ──
    if (EVAL_DIR / "index.html").exists():
        @app.get("/eval", include_in_schema=False)
        def eval_root() -> RedirectResponse:
            return RedirectResponse("/eval/")          # 상대 경로(style.css 등)가 맞게 열리도록

        app.mount("/eval", StaticFiles(directory=EVAL_DIR, html=True), name="eval")

    # ── 화면 (frontend/dist) ─────────────────────────────
    if (DIST / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

        @app.get("/{path:path}")
        def spa(path: str) -> FileResponse:
            f = DIST / path
            if path and f.is_file() and DIST in f.resolve().parents:
                return FileResponse(f)
            return FileResponse(DIST / "index.html")          # React Router 경로(/monitor 등)는 index.html이 처리
    else:
        @app.get("/{path:path}")
        def no_build(path: str) -> HTMLResponse:
            return HTMLResponse(NO_BUILD_HTML, status_code=200)

    return app


NO_BUILD_HTML = """<!doctype html><html lang="ko"><meta charset="utf-8"><title>MediCloak 데모</title>
<body style="font-family:system-ui,sans-serif;max-width:640px;margin:64px auto;padding:0 16px;line-height:1.7;color:#161827">
<h1 style="font-size:22px">화면 파일이 아직 없습니다</h1>
<p>API 서버는 켜져 있습니다. 화면을 보려면 다른 터미널에서 프런트엔드를 한 번 빌드한 뒤 이 페이지를 새로 고치세요.</p>
<pre style="background:#ECEEF4;padding:12px 14px;border-radius:10px">cd frontend
npm install
npm run build:demo</pre>
<p>개발 서버로 띄우려면 <code>npm run dev:demo</code> 후 http://localhost:5173 을 여세요.</p></body></html>"""


app = create_app()          # uvicorn webdemo.backend.app:app
