# MediCloak API (FastAPI). 빌드한 프런트엔드(frontend/dist)도 같은 서버가 내보낸다.
#
# 두 가지로 켠다
#   데모    python -m webdemo     로그인 없음 · 결정적 응답기 · 메모리에만 기록. 화면 하나가 대화 하나를 쓴다.
#   운영    python -m medicloak   로그인 · 역할 분리 · DB(가상 EMR · 기록) · .env의 실제 LLM. 의료진 계정마다 대화를 따로 쓴다.
#
#   의료진 화면 (frontend/ 계약, api_server와 같은 경로) — 언제나 위험 숫자를 지워서 보낸다 (redact.py)
#     GET  /api/workspace · /api/protection-policy · /api/patient-context · /api/cases?patientContextId= · /api/risk-states
#     GET  /api/cases/{id}/session · /disclosures · /suggestions          (판정 근거 /policy-decision은 403)
#     POST /api/cases/{id}/messages · /preflight          POST /api/session/reset {trialId}
#     GET  /api/clinic/messages · POST /api/clinic/messages {kind, text, caseId}   보안 담당자와 주고받는 메시지
#     GET  /api/clinic/history                           이 계정의 지난 대화 (운영 모드)
#     GET  /api/clinic/patients                          데모 환자 목록 (데모 모드만)
#   가상 EMR (운영 모드, 의료진)
#     GET  /api/emr/worklist · POST /api/emr/launch {fhirId, purpose}     GET /fhir/metadata · /fhir/Patient · /fhir/{자원}?patient=
#   보안 담당자
#     GET  /api/watch                                    의료진 대화 목록 (지난 대화 포함)
#     GET  /api/watch/{대화}/…                           그 대화의 의료진 화면 계약을 숫자 그대로 (위와 같은 경로, 읽기 전용)
#     GET  /api/monitor/overview · /policy · /sessions/{sid} · /audit
#     POST /api/monitor/sessions/{sid}/reveal {reason} · /review {action, note} · /messages {kind, text, case}   GET …/messages
#     GET · POST /api/monitor/sessions/{sid}/assist   검토 보조 초안 (세부 정보 요청이 오면 뒤에서 만든다. 보내지는 않는다)
#     POST /api/redteam · GET /api/redteam/{id} · GET /api/poc     평가 지표 대시보드 GET /eval/
#   로그인 (운영 모드)
#     POST /api/auth/login {username, password} · /api/auth/logout     GET /api/auth/me
#   함께 쓰는 것: GET /api/health · 의료 용어 RAG /api/terminology/…

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core.llm_client import LLMError
from medical.config import ROOT
from medical.terminology_api import terminology_router
from webdemo.backend import redact
from webdemo.backend.assist import ReviewAssistant
from webdemo.backend.autocheck import ACTOR as AUTO_ACTOR, AUTO_FUZZER, AUTO_PER_TYPE, AutoRedteam
from webdemo.backend.auth import COOKIE, ROLE_KO, SESSION_TTL, Auth, LoginBlocked, roles_for, route_path, user_view
from webdemo.backend.clinic import ArchivedConversation, ClinicConversation, ClinicDesk, Conflict, DeskRegistry, NotFound
from webdemo.backend.engine import ARMS, DemoError, Engine, summarize
from webdemo.backend.fhir import FEATURED, OutpatientEmr, fhir_router, find_trial, worklist
from webdemo.backend.monitor import REVIEW_KO, Monitor
from webdemo.backend.persist import Persist
from webdemo.backend.review import RELEASE_VERSION

HERE = Path(__file__).resolve().parent
DIST = Path(os.environ.get("WEBDEMO_DIST") or ROOT / "frontend" / "dist")
POC_FILE = HERE.parent / "data" / "poc_summary.json"
EVAL_DIR = ROOT / "eval_demo"
PRODUCT_LOCATION = "MediCloak 외래 진료 지원"
# 운영 모드: 의료진 대화는 EMR에서 환자를 열 때 시작한다 (기본 환자를 저절로 열지 않음). 열린 대화가 없으면 409와 이 머리글.
NO_CONVERSATION = "열린 진료 지원 AI 대화가 없습니다. 외래 진료 목록에서 환자를 열어 주세요."
NO_CONVERSATION_HEADERS = {"X-MediCloak-State": "no-conversation"}


@dataclass
class Product:
    """운영 모드 설정 (python -m medicloak serve가 만든다)."""
    store: Any                              # webdemo.backend.store.Store
    auth: bool = True
    compare: bool = True                    # 실제 LLM 대화에서도 C0 · C1S 비교 갈래를 계산 (원 응답은 같이 씀, C1S 재작성 호출이 더 들 수 있음)
    keep: int | None = 12                   # 의료진마다 메모리에 둘 대화 수 (넘으면 DB 스냅숏으로만 남김)
    cookie_secure: bool = False             # https로만 쿠키를 보낼지 (역방향 프록시 뒤 https 운영이면 켠다)
    location_label: str = PRODUCT_LOCATION
    auto_redteam: str = "off"               # change: 설정(판정 규칙 판 · 답 형식 · 모델 · 규칙 추출)이 마지막 점검과 다르면 켤 때 점검을 돌린다
    auto_daily: str | None = None           # 'HH:MM': 매일 그 시각에도 점검 (autocheck.py)


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
    llm: str = "auto"                   # live(서버의 실제 LLM) · oracle(결정적 응답기) · auto(실제 LLM이 있으면 live)


class MessageIn(BaseModel):
    sessionId: str
    question: str
    clientMessageId: str
    scope: str = "case"                     # case: 고른 사례에 묻기 · all: 찾은 사례 전체에 묻기 (실제 LLM 대화)


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


class RuleIn(BaseModel):
    """보안 담당자 규칙: 이 대화에서 case('사례1')의 attribute(DX · MED · PERIOD …)는 늘 가림."""
    case: str = Field(..., pattern=r"^사례\d+$")
    attribute: str
    note: str | None = Field(None, max_length=300)


class ApproveIn(BaseModel):
    """세부 정보 요청 승인: 가린 값 id(/hidden의 id) 목록과 공개 사유."""
    items: list[str] = Field(..., min_length=1, max_length=50)
    reason: str = Field(..., min_length=5, max_length=300)


class LoginIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class LaunchIn(BaseModel):
    fhirId: str = Field(..., min_length=1, max_length=64)
    purpose: str = Field(..., examples=["PRESCRIPTION"])


def create_app(engine: Engine | None = None, *, trial: str | None = None, simulations: bool | None = None,
               product: Product | None = None) -> FastAPI:
    state: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        eng = engine or Engine(Path(os.environ["WEBDEMO_WORKDIR"]) if os.environ.get("WEBDEMO_WORKDIR") else None)
        store = product.store if product else None
        persist = Persist(store, eng) if store is not None else None
        mon = Monitor(eng, store, on_session_change=persist.save_session if persist else None)
        mon.assistant = ReviewAssistant(eng, mon.log)          # 세부 정보 요청이 오면 검토 초안을 만든다 (assist.py)
        registry = DeskRegistry(eng, trial=trial or os.environ.get("WEBDEMO_TRIAL") or "T0014",
                                llm_mode="live" if eng.live_ctx is not None else "oracle",
                                compare=product.compare if product else True,
                                location_label=product.location_label if product else "MediCloak 데모 (Synthea 합성 환자)",
                                on_change=persist.save if persist else None, keep=product.keep if persist else None,
                                on_evict=persist.evict if persist else None, archive=persist.archive if persist else None,
                                lazy=persist is not None)
        if persist is not None:
            persist.monitor, persist.registry = mon, registry
            eng.on_compare_done = persist.save_session          # 뒤에서 계산한 비교 갈래(C1S)도 DB에 남긴다
        state.update(engine=eng, monitor=mon, registry=registry, persist=persist, store=store,
                     auth=Auth(store) if product and product.auth else None,
                     emr=OutpatientEmr(store) if store is not None else None, worklist=None)
        if state["auth"] is None:
            state["clinic"] = registry.desk_for(None)          # 데모: 화면 하나 = 대화 하나
        if store is not None:                                 # 서버가 꺼질 때 돌고 있던 레드팀 실행은 끊긴 것으로 남긴다
            for x in store.runs():
                if x.get("status") in ("queued", "running"):
                    store.save_run(dict(x, status="interrupted", error="서버를 다시 켜는 동안 끊겼습니다. 끝낸 trial도 집계하지 못했습니다."))
        # 자동 레드팀 점검: 설정이 마지막 점검과 다르면 '유형마다 1명' 점검을 뒤에서 시작하고, 끝나면 직전 점검과 비교한다 (autocheck.py)
        state["auto"] = AutoRedteam(eng, all_runs, start_live_job, mon.log,
                                    on_change=bool(product and product.auto_redteam == "change"), daily=product.auto_daily if product else None)
        state["auto"].on_start()
        if product is not None and state["auto"].decision != "off":
            print(f"[medicloak] 자동 레드팀 점검: {state['auto'].decision_text}")
        sims = simulations if simulations is not None else os.environ.get("WEBDEMO_NO_SIM") != "1"
        if sims and product is None:                 # 운영 모드 관제에는 실제 의료진 대화만 둔다 (레드팀은 레드팀 화면에서 따로 돌림)
            mon.seed_simulations()
        if product is not None:
            try:                                         # LLM을 기다리는 질문이 동기 요청 일꾼을 모두 잡지 않게 여유를 둔다
                import anyio.to_thread
                anyio.to_thread.current_default_thread_limiter().total_tokens = 100
            except Exception:
                pass
        yield
        state["auto"].stop()
        # 끌 때: 뒤에서 계산 중인 비교 갈래(C1S)를 잠시 기다려 DB에 남긴다 (못 끝낸 것은 '대기'로 남는다)
        if eng.compare_pending():
            eng.wait_compare(20)

    # 운영 모드에서는 API 문서(/docs · /openapi.json)를 열지 않는다
    docs = dict(docs_url=None, redoc_url=None, openapi_url=None) if product is not None else {}
    app = FastAPI(title="MediCloak 의료 AI", version="0.3", lifespan=lifespan, **docs)

    def eng() -> Engine:
        return state["engine"]

    def mon() -> Monitor:
        return state["monitor"]

    def reg() -> DeskRegistry:
        return state["registry"]

    def user_of(request: Request) -> dict[str, Any] | None:
        return getattr(request.state, "user", None)

    def desk(request: Request) -> ClinicDesk:
        if state["auth"] is None:
            return state["clinic"]
        return reg().desk_for(user_of(request))

    def opened(request: Request) -> ClinicDesk:
        """운영 모드에서는 열린 대화가 있어야 한다 (없으면 409). 데모는 처음부터 기본 환자 대화가 있다."""
        d = desk(request)
        if state["auth"] is not None and d.peek() is None:
            raise HTTPException(409, NO_CONVERSATION, headers=NO_CONVERSATION_HEADERS)
        return d

    def cur(request: Request) -> ClinicConversation:
        return opened(request).current

    def arm_ok(arm: str) -> str:
        if arm not in ARMS:
            raise HTTPException(400, f"arm은 {', '.join(ARMS)} 중 하나입니다.")
        return arm

    def sess(sid: str):
        try:
            return eng().session(sid)
        except KeyError:
            a = mon().archived(sid)
            if a is not None:
                return a
            raise HTTPException(404, f"없는 대화입니다: {sid}" + ("" if state["store"] is not None else " (데모 서버는 다시 켜면 대화가 지워집니다)"))

    def guard(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except NotFound:
            raise HTTPException(404, "없는 사례 또는 환자 맥락입니다.")
        except Conflict as exc:
            raise HTTPException(409, str(exc))
        except DemoError as exc:
            raise HTTPException(400, str(exc))
        except LLMError as exc:
            raise HTTPException(502, f"대상 AI 호출에 실패했습니다 ({type(exc).__name__}). 대화 상태는 바뀌지 않았습니다.")
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @app.exception_handler(DemoError)
    async def demo_error(_, exc: DemoError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    # ── 로그인 · 역할 (운영 모드) ─────────────────────────
    @app.middleware("http")
    async def access(request: Request, call_next):
        a: Auth | None = state.get("auth")
        request.state.user = None
        if a is None:
            return await call_next(request)
        token = request.cookies.get(COOKIE)
        user = a.user_of(token) if token else None
        request.state.user = user
        need = roles_for(route_path(request.scope))            # 라우터가 맞추는 경로 (root_path를 뗀 것)
        if need is False or need is None:
            return await call_next(request)
        if user is None:
            return JSONResponse(status_code=401, content={"detail": "로그인이 필요합니다."})
        if user["role"] not in need:
            other = " · ".join(ROLE_KO[r] for r in sorted(need))
            return JSONResponse(status_code=403, content={"detail": f"{other} 계정만 쓸 수 있습니다. 지금은 {ROLE_KO[user['role']]} 계정입니다."})
        return await call_next(request)

    def client_of(request: Request) -> str:
        return request.client.host if request.client else "-"

    def require_access(request: Request) -> None:
        """
        API 라우터마다 붙이는 두 번째 검사: 실제로 맞은 경로 틀(예: /api/monitor/sessions/{sid})로 역할을 다시 본다.
        미들웨어 검사가 배포 방식(앞 경로, 프록시)에 따라 빗나가도 여기서 막힌다.
        """
        if state.get("auth") is None:
            return
        route = request.scope.get("route")
        need = roles_for(getattr(route, "path", None) or route_path(request.scope))
        if need is None:
            return
        user = user_of(request)
        if user is None:
            raise HTTPException(401, "로그인이 필요합니다.")
        if need is False or user["role"] not in need:
            raise HTTPException(403, "이 계정으로는 쓸 수 없는 기능입니다.")

    def attempt_label(a: Auth, username: str) -> str:
        # 없는 아이디는 입력값을 남기지 않는다 (아이디 칸에 비밀번호를 잘못 친 경우 감사 기록에 비밀번호가 남지 않게)
        name = username.strip()[:64]
        return f"{name} (로그인 시도)" if a.known(name) else "없는 아이디 (로그인 시도)"

    auth_r = APIRouter(prefix="/api/auth")

    @auth_r.post("/login")
    def login(body: LoginIn, request: Request, response: Response) -> dict[str, Any]:
        a: Auth | None = state["auth"]
        if a is None:
            raise HTTPException(404, "로그인 없는 데모 서버입니다.")
        try:
            got = a.login(body.username, body.password, client_of(request))
        except LoginBlocked as exc:
            mon().log("login_blocked", None, actor=attempt_label(a, body.username), client=client_of(request))
            raise HTTPException(429, str(exc))
        if got is None:
            mon().log("login_failed", None, actor=attempt_label(a, body.username), client=client_of(request))
            raise HTTPException(401, "아이디 또는 비밀번호가 맞지 않습니다.")
        token, user = got
        response.set_cookie(COOKIE, token, max_age=int(SESSION_TTL), httponly=True, samesite="lax",
                            secure=bool(product and product.cookie_secure) or request.url.scheme == "https", path="/")
        mon().log("login", None, user=user, client=client_of(request))
        return dict(user=user_view_of(user))

    @auth_r.post("/logout")
    def logout(request: Request, response: Response) -> dict[str, Any]:
        a: Auth | None = state["auth"]
        if a is None:
            raise HTTPException(404, "로그인 없는 데모 서버입니다.")
        user = user_of(request)
        a.logout(request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE, path="/")
        if user:
            mon().log("logout", None, user=user)
        return dict(status="ok")

    @auth_r.get("/me")
    def me(request: Request) -> dict[str, Any]:
        if state["auth"] is None:
            raise HTTPException(404, "로그인 없는 데모 서버입니다.")
        user = user_of(request)
        if user is None:
            raise HTTPException(401, "로그인이 필요합니다.")
        return dict(user=user_view_of(user))

    def user_view_of(u: dict[str, Any]) -> dict[str, Any]:
        return user_view(dict(u))

    app.include_router(auth_r)

    # ── 의료진 화면 (숫자 없음) ───────────────────────────
    guarded = [Depends(require_access)]
    r = APIRouter(prefix="/api", dependencies=guarded)

    @r.get("/health")
    def health() -> dict[str, Any]:
        e = eng()
        live = e.live_ctx is not None
        out = dict(status="ok", backend="medicloak" if state["store"] is not None else "webdemo", product="MediCloak", release=RELEASE_VERSION,
                   target=e.live_label if live else "결정적 응답기 (LLM 없음)", monitor=True, simulations=mon().sim_status,
                   auth=state["auth"] is not None,
                   llm=dict(mode="live" if live else "oracle", label=e.live_label, live=live,
                            waiting=e.live_llm.waiting if e.live_llm is not None else 0, compare_pending=e.compare_pending()))
        if state["auth"] is None:
            out["trialId"] = state["clinic"].session.trial_id
        if state["persist"] is not None:
            out["persist"] = dict(errors=state["persist"].errors)
        return out

    @r.get("/workspace")
    def workspace(request: Request) -> dict[str, Any]:
        env = cur(request).environment()
        u = user_of(request)
        if u:
            env = dict(env, roleLabel=f"{u['display_name']} · {u.get('department') or '의료진'}")
        return env

    @r.get("/protection-policy")
    def protection_policy(request: Request) -> dict[str, Any]:
        return redact.policy(cur(request).policy())

    @r.get("/patient-context")
    def patient_context(request: Request) -> dict[str, Any]:
        return cur(request).patient_context()

    @r.get("/cases")
    def cases(patientContextId: str, request: Request) -> list[dict[str, Any]]:
        return guard(lambda: cur(request).similar_cases(patientContextId))

    @r.get("/cases/{case_id}/session")
    def conversation(case_id: str, request: Request) -> dict[str, Any]:
        return redact.conversation(guard(lambda: cur(request).conversation(case_id)))

    # 질문을 보내고 답을 기다리는 동안의 진행 (의료진마다). 화면 갈래(C1)의 실제 LLM 호출만 센다 (live.CallWatchLLM).
    asking: dict[str, dict[str, Any]] = {}
    asking_lock = threading.Lock()
    ask_step_ko = dict(target="진료 지원 AI가 답을 쓰고 있습니다", extractor="답에서 환자를 알아볼 수 있는 단서를 찾고 있습니다",
                       recheck="고친 답을 다시 확인하고 있습니다", rewriter="가릴 값을 고쳐 쓰고 있습니다")

    @r.post("/cases/{case_id}/messages")
    def ask(case_id: str, body: MessageIn, request: Request) -> dict[str, Any]:
        if not body.question.strip():
            raise HTTPException(422, "질문이 비어 있습니다.")
        d = opened(request)
        key = launch_key(request)
        st = dict(started=time.time(), label="질문을 보내고 있습니다", calls=0, extracted=False)

        def on_call(role: str, n: int) -> None:
            step = ("recheck" if st["extracted"] else "extractor") if role == "extractor" else role
            st["extracted"] = st["extracted"] or role == "extractor"
            st.update(label=ask_step_ko.get(step, st["label"]), calls=n)

        watcher = getattr(getattr(d.peek(), "session", None), "watcher", None)
        if watcher is not None:
            watcher.watch, watcher.calls = on_call, 0
        with asking_lock:
            asking[key] = st
        try:
            out = guard(lambda: d.ask(case_id, body.sessionId, body.question, body.clientMessageId, body.scope))
        finally:
            if watcher is not None:
                watcher.watch = None
            with asking_lock:
                if asking.get(key) is st:
                    asking.pop(key)
        p = out["assistantMessage"]["protection"]
        mon().log("clinic_question", d.current.session, user=user_of(request), actor="의료진", case=d.current.ref_of(case_id),
                  turn=out["assistantMessage"].get("engineTurn"), release=p.get("releaseMode"), scope=body.scope,
                  protected=sum(t["action"] != "allow" for t in p.get("transformations", [])))
        return redact.send_result(out)

    @r.get("/clinic/progress")
    def clinic_progress(request: Request) -> dict[str, Any]:
        """질문에 답하는 중이면 지금 단계 · 실제 LLM 호출 수 · 걸린 초. 엔진 잠금을 쓰지 않는다."""
        with asking_lock:
            st = asking.get(launch_key(request))
            if st is None:
                return dict(active=False)
            return dict(active=True, label=st["label"], calls=st["calls"], elapsed=round(time.time() - st["started"], 1))

    @r.post("/cases/{case_id}/preflight")
    def preflight(case_id: str, body: PreflightIn, request: Request) -> dict[str, Any]:
        c = cur(request)
        return redact.preflight(guard(lambda: c.preflight(case_id, body.sessionId, body.question)), live=c.live)

    @r.get("/cases/{case_id}/suggestions")
    def suggestions(case_id: str, request: Request) -> list[dict[str, Any]]:
        return guard(lambda: cur(request).suggestions(case_id))

    @r.get("/risk-states")
    def risk_states(request: Request) -> list[dict[str, Any]]:
        return [redact.risk(x) for x in cur(request).risk_states()]

    @r.get("/cases/{case_id}/disclosures")
    def disclosures(case_id: str, request: Request) -> dict[str, Any]:
        return redact.disclosures(guard(lambda: cur(request).disclosures(case_id)))

    @r.get("/cases/{case_id}/policy-decision")
    def policy_decision(case_id: str) -> dict[str, Any]:
        raise HTTPException(403, "판정 근거(후보 수 · 기준값)는 보안 담당자 화면에서만 볼 수 있습니다.")

    @r.post("/session/reset")
    def reset(request: Request, body: ResetIn | None = None) -> dict[str, Any]:
        d = opened(request)
        tid = (body.trialId if body else None) or d.session.trial_id
        guard(lambda: d.start(tid))
        mon().log("clinic_start", d.session, user=user_of(request), actor="의료진")
        return dict(status="ok", workspaceId=d.workspace_id, trialId=tid)

    @r.get("/clinic/messages")
    def clinic_messages(request: Request) -> list[dict[str, Any]]:
        d = desk(request)
        if state["auth"] is not None and d.peek() is None:
            return []                         # 머리줄 알림이 주기적으로 묻는다. 열린 대화가 없으면 메시지도 없다
        return d.current.messages()

    @r.post("/clinic/messages")
    def post_clinic_message(body: ClinicNoteIn, request: Request) -> list[dict[str, Any]]:
        c = cur(request)
        ref = guard(lambda: c.ref_of(body.caseId)) if body.caseId else None
        guard(lambda: mon().post_message(c.session, "clinician", body.kind, body.text, ref, user=user_of(request)))
        return c.messages()

    @r.get("/clinic/patients")
    def clinic_patients() -> list[dict[str, Any]]:
        if state["emr"] is not None:
            raise HTTPException(404, "운영 모드에서는 EMR 외래 목록(/api/emr/worklist)에서 환자를 고릅니다.")
        out = []
        for p in eng().patients():
            panel = {x["label"]: x["value"] for x in p["panel"]}
            out.append(dict(trialId=p["trial_id"], qtypeLabel=p["qtype_label"], featured=p["trial_id"] in FEATURED,
                            ageSex=panel.get("연령 / 성별"), mainDx=panel.get("주진단"), item=panel.get("고려 중인 처치")))
        return out

    @r.get("/clinic/history")
    def clinic_history(request: Request) -> list[dict[str, Any]]:
        """이 의료진의 대화 목록 (지금 대화 · 지난 대화). 숫자 없이 언제 · 어떤 환자 · 질문 몇 번."""
        d = desk(request)
        out, seen = [], set()
        with eng().lock:
            for conv in list(d.history.values()):
                s = conv.session
                pc = conv.patient_context()
                out.append(dict(id=s.id, trialId=s.trial_id, startedAt=s.created, lastActive=s.last_active, questions=s.turn,
                                patient=f"{pc['ageSexLabel']} · {pc['primaryDiagnosis']}", purpose=pc["queryPurpose"],
                                current=conv is d.peek(), archived=False))
                seen.add(s.id)
        store, u = state["store"], user_of(request)
        if store is not None and u is not None:
            for c in store.conversations("clinic"):
                if c["user_id"] != u["user_id"] or c["conv_id"] in seen or not c.get("clinic") or not c.get("turns"):
                    continue
                pc = c["clinic"]["patient"]
                out.append(dict(id=c["conv_id"], trialId=c["trial_id"], startedAt=c["started_at"], lastActive=c["last_active"],
                                questions=c["turns"], patient=f"{pc['ageSexLabel']} · {pc['primaryDiagnosis']}", purpose=pc["queryPurpose"],
                                current=False, archived=True))
        out.sort(key=lambda x: (not x["current"], -(x["lastActive"] or 0)))
        return out

    # ── 가상 EMR (운영 모드) ─────────────────────────────
    def emr() -> OutpatientEmr:
        if state["emr"] is None:
            raise HTTPException(404, "EMR 연동은 운영 모드(python -m medicloak)에서만 켜집니다.")
        return state["emr"]

    @r.get("/emr/worklist")
    def emr_worklist() -> list[dict[str, Any]]:
        e = emr()
        if state["worklist"] is None:
            with eng().lock:
                state["worklist"] = worklist(eng(), e)
        return state["worklist"]

    # 진료 지원 AI를 여는 동안의 진행 (의료진마다). 첫 답은 실제 LLM을 차례로 여러 번 부르므로 화면이 지금 단계를 보여 준다.
    launching: dict[str, dict[str, Any]] = {}
    launching_lock = threading.Lock()
    step_ko = dict(target="진료 지원 AI가 비슷한 사례를 정리하고 있습니다", extractor="답에서 환자를 알아볼 수 있는 단서를 찾고 있습니다",
                   recheck="고친 답을 다시 확인하고 있습니다", rewriter="가릴 값을 고쳐 쓰고 있습니다")

    def launch_key(request: Request) -> str:
        u = user_of(request)
        return str(u.get("id") or u.get("username")) if u else "-"

    @r.post("/emr/launch")
    def emr_launch(body: LaunchIn, request: Request) -> dict[str, Any]:
        emr()
        tid = find_trial(eng(), body.fhirId, body.purpose)
        d = desk(request)
        key = launch_key(request)
        st = dict(started=time.time(), label="비슷한 과거 사례를 찾고 있습니다", calls=0, extracted=False)

        def on_call(role: str, n: int) -> None:
            step = ("recheck" if st["extracted"] else "extractor") if role == "extractor" else role
            st["extracted"] = st["extracted"] or role == "extractor"
            st.update(label=step_ko.get(step, st["label"]), calls=n)

        with launching_lock:
            launching[key] = st
        try:
            guard(lambda: d.start(tid, launch=dict(fhirId=body.fhirId, purpose=body.purpose), on_call=on_call))
        finally:
            with launching_lock:
                if launching.get(key) is st:
                    launching.pop(key)
        mon().log("emr_launch", d.session, user=user_of(request), actor="의료진", purpose=body.purpose)
        return dict(status="ok", workspaceId=d.workspace_id, trialId=tid, seconds=round(time.time() - st["started"], 1), calls=st["calls"])

    @r.get("/emr/launch/progress")
    def emr_launch_progress(request: Request) -> dict[str, Any]:
        """여는 중이면 지금 단계 · 실제 LLM 호출 수 · 걸린 초. 엔진 잠금을 쓰지 않는다 (여는 요청과 따로 돈다)."""
        with launching_lock:
            st = launching.get(launch_key(request))
            if st is None:
                return dict(active=False)
            return dict(active=True, label=st["label"], calls=st["calls"], elapsed=round(time.time() - st["started"], 1))

    # ── 보안 담당자: 의료진 대화를 숫자와 함께 (읽기 전용) ──
    w = APIRouter(prefix="/api/watch", dependencies=guarded)

    def conv_of(sid: str) -> ClinicConversation | ArchivedConversation:
        try:
            return reg().lookup(sid)
        except NotFound:
            raise HTTPException(404, f"없는 의료진 대화입니다: {sid}")

    @w.get("")
    def watch_list() -> list[dict[str, Any]]:
        rows = [x for x in mon().overview()["sessions"] if x["source"] == "clinic"]
        current = reg().current_ids()
        out = [dict(id=x["id"], trialId=x["trial_id"], owner=x.get("owner"), qtypeLabel=x["qtype_label"], turns=x["turns"],
                    lastActive=x["last_active"], created=x["created"], status=x["status"], statusLabel=x["status_label"],
                    archived=bool(x.get("archived")), current=x["id"] in current, pendingRequest=x["pending_request"],
                    llmMode=x.get("llm_mode")) for x in rows]
        out.sort(key=lambda x: (not x["current"], x["archived"], -(x["lastActive"] or 0)))
        return out

    @w.get("/{sid}/workspace")
    def w_workspace(sid: str) -> dict[str, Any]:
        return conv_of(sid).environment()

    @w.get("/{sid}/protection-policy")
    def w_policy(sid: str) -> dict[str, Any]:
        return conv_of(sid).policy()

    @w.get("/{sid}/patient-context")
    def w_patient(sid: str) -> dict[str, Any]:
        return conv_of(sid).patient_context()

    @w.get("/{sid}/cases")
    def w_cases(sid: str, patientContextId: str) -> list[dict[str, Any]]:
        c = conv_of(sid)
        return guard(lambda: c.similar_cases(patientContextId))

    @w.get("/{sid}/risk-states")
    def w_risks(sid: str) -> list[dict[str, Any]]:
        return conv_of(sid).risk_states()

    @w.get("/{sid}/cases/{case_id}/session")
    def w_conversation(sid: str, case_id: str) -> dict[str, Any]:
        c = conv_of(sid)
        return guard(lambda: c.conversation(case_id))

    @w.get("/{sid}/cases/{case_id}/disclosures")
    def w_disclosures(sid: str, case_id: str) -> dict[str, Any]:
        c = conv_of(sid)
        return guard(lambda: c.disclosures(case_id))

    @w.get("/{sid}/cases/{case_id}/policy-decision")
    def w_decision(sid: str, case_id: str) -> dict[str, Any]:
        c = conv_of(sid)
        with eng().lock:
            return guard(lambda: c.policy_decision(case_id))

    @w.get("/{sid}/cases/{case_id}/narrowing")
    def w_narrowing(sid: str, case_id: str) -> dict[str, Any]:
        c = conv_of(sid)
        with eng().lock:
            return guard(lambda: c.narrowing(case_id))

    @w.get("/{sid}/cases/{case_id}/suggestions")
    def w_suggestions(sid: str, case_id: str) -> list[dict[str, Any]]:
        c = conv_of(sid)
        return guard(lambda: c.suggestions(case_id))

    @w.post("/{sid}/cases/{case_id}/preflight")
    def w_preflight(sid: str, case_id: str, body: PreflightIn) -> dict[str, Any]:
        c = conv_of(sid)
        return guard(lambda: c.preflight(case_id, body.sessionId, body.question))

    # ── 관제 ─────────────────────────────────────────────
    @r.get("/monitor/overview")
    def overview() -> dict[str, Any]:
        return mon().overview()

    @r.get("/monitor/policy")
    def monitor_policy() -> dict[str, Any]:
        e = eng()
        d = e.ctx["staged"].defender
        return dict(modeLabel=e.live_label if e.live_ctx is not None else "결정적 응답기 (LLM 없음)", arm="C1",
                    stateModeLabel="누적 판정 (대화 전체 기억)", minK=d.g, suppressK=d.s, populationSize=e.ctx["staged"].p_ref, source="backend",
                    kReq=e.cfg.k_req, llmLive=e.live_ctx is not None, ruleExtract=bool(e.live_ctx is not None and e.live_ctx.cfg.rule_extract), compare=product.compare if product else True,
                    answerStyle=bool(e.live_ctx is not None and e.answer_style),
                    auth=state["auth"] is not None, persist=state["store"] is not None, llmUsage=e.live_usage(),
                    autoRedteam=dict(onChange=state["auto"].on_change and state["auto"].enabled, daily=state["auto"].daily if state["auto"].enabled else None,
                                     decisionText=state["auto"].decision_text))

    @r.get("/monitor/sessions/{sid}")
    def monitor_session(sid: str) -> dict[str, Any]:
        return mon().detail(sess(sid))

    @r.post("/monitor/sessions/{sid}/reveal")
    def reveal(sid: str, body: RevealIn, request: Request) -> dict[str, Any]:
        return mon().reveal(sess(sid), body.reason.strip(), user=user_of(request))

    @r.post("/monitor/sessions/{sid}/review")
    def review(sid: str, body: ReviewIn, request: Request) -> dict[str, Any]:
        if body.action not in REVIEW_KO:
            raise HTTPException(422, f"action은 {', '.join(REVIEW_KO)} 중 하나입니다.")
        s = sess(sid)
        return guard(lambda: mon().review(s, body.action, body.note, user=user_of(request)))

    @r.get("/monitor/sessions/{sid}/messages")
    def security_thread(sid: str) -> dict[str, Any]:
        return mon().thread(sess(sid))          # 원문을 열람한 상세를 다시 받지 않고 메시지만 새로 고칠 때

    @r.post("/monitor/sessions/{sid}/messages")
    def post_security_message(sid: str, body: SecurityNoteIn, request: Request) -> dict[str, Any]:
        if body.kind == "release":
            raise HTTPException(422, "공개 승인은 /approve로 값을 골라 보냅니다.")
        s = sess(sid)
        guard(lambda: mon().post_message(s, "security", body.kind, body.text, body.case, user=user_of(request)))
        return mon().thread(s)

    # ── 검토 반영: 규칙 · 공개 승인 ──
    @r.post("/monitor/sessions/{sid}/rules")
    def add_rule(sid: str, body: RuleIn, request: Request) -> dict[str, Any]:
        s = sess(sid)
        if not getattr(s, "archived", False) and getattr(s, "source", None) == "clinic" and sid not in reg().current_ids():
            raise HTTPException(409, "의료진이 이미 다른 환자를 열어 이 대화에는 다음 질문이 없습니다.")
        guard(lambda: mon().add_rule(s, body.case, body.attribute, body.note, user=user_of(request)))
        return mon().detail(s)

    @r.delete("/monitor/sessions/{sid}/rules/{rule_id}")
    def remove_rule(sid: str, rule_id: str, request: Request) -> dict[str, Any]:
        s = sess(sid)
        try:
            guard(lambda: mon().remove_rule(s, rule_id, user=user_of(request)))
        except KeyError:
            raise HTTPException(404, f"없는 규칙입니다: {rule_id}")
        return mon().detail(s)

    def current_conv(sid: str) -> ClinicConversation | None:
        """의료진이 지금 보고 있는 대화만 (지난 대화에 공개하면 의료진 화면에 보이지 않는다)."""
        return reg().live(sid) if sid in reg().current_ids() else None

    @r.get("/monitor/sessions/{sid}/hidden")
    def hidden(sid: str) -> list[dict[str, Any]]:
        return mon().hidden(sess(sid))

    @r.post("/monitor/sessions/{sid}/approve")
    def approve(sid: str, body: ApproveIn, request: Request) -> dict[str, Any]:
        s = sess(sid)
        conv = current_conv(sid) if not getattr(s, "archived", False) else None
        ap = guard(lambda: mon().approve(s, conv, body.items, body.reason, user=user_of(request)))
        shown = dict(ap, items=[dict(x, value=None) for x in ap["items"]])          # 값은 열람 뒤 상세에서만
        return dict(approval=shown, detail=mon().detail(s))

    # ── 검토 보조: 세부 정보 요청의 검토 초안 (assist.py). 보내는 일은 하지 않는다 ──
    @r.get("/monitor/sessions/{sid}/assist")
    def assist_state(sid: str) -> dict[str, Any]:
        return mon().assist_state(sess(sid))

    @r.post("/monitor/sessions/{sid}/assist")
    def assist_run(sid: str) -> dict[str, Any]:
        s = sess(sid)
        return guard(lambda: mon().assist_run(s))

    @r.get("/monitor/audit")
    def audit() -> list[dict[str, Any]]:
        return list(reversed(mon().audit_entries()))

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
        # 의료진 대화는 빼고 보낸다 (질의 환자 번호가 들어 있고, 관제 화면에서 사유를 남긴 열람으로만 원문을 본다)
        return [s._summary() for s in list(eng().sessions.values()) if s.source != "clinic"]

    @r.get("/sessions/{sid}/clinician")
    def clinician(sid: str, arm: str = Query("C1")) -> dict[str, Any]:
        with eng().lock:
            return live_session(sid).clinician_view(arm_ok(arm))

    @r.get("/sessions/{sid}/security")
    def security(sid: str) -> dict[str, Any]:
        with eng().lock:
            return live_session(sid).security_view()

    @r.get("/sessions/{sid}/questions")
    def questions(sid: str, arm: str = Query("C1")) -> list[dict[str, Any]]:
        with eng().lock:
            return live_session(sid).questions(arm_ok(arm))

    @r.post("/sessions/{sid}/preview")
    def preview(sid: str, body: Preview) -> dict[str, Any]:
        with eng().lock:
            return live_session(sid).preview(body.seed_id, arm_ok(body.arm))

    @r.post("/sessions/{sid}/turns")
    def turn(sid: str, body: Step) -> dict[str, Any]:
        with eng().lock:
            s = live_session(sid)
            if s.llm_mode == "live":
                raise HTTPException(409, "실제 LLM 의료진 대화는 의료진 화면에서만 이어 묻습니다.")
            return s.step(body.seed_id, arm_ok(body.arm))

    @r.post("/sessions/{sid}/run")
    def run_all(sid: str, arm: str = Query("C1")) -> dict[str, Any]:
        with eng().lock:
            s = live_session(sid)
            if s.llm_mode == "live":
                raise HTTPException(409, "실제 LLM 의료진 대화는 의료진 화면에서만 이어 묻습니다.")
            n = s.run_to_end(arm_ok(arm))
            return dict(turns_added=n, turn=s.turn)

    def live_session(sid: str):
        """
        세션 직접 조작(POC 재현 · 테스트)용. 의료진 대화는 여기서 열거나 바꿀 수 없다: 이 경로는 원 응답 · 비교 조건의 답을
        가리지 않고 보내며(사유 · 감사 기록 없이), /turns · /run은 의료진 대화에 질문을 더해 버린다.
        의료진 대화는 /api/monitor/sessions/{sid}(가린 상세 · 사유를 남긴 열람)와 /api/watch/{sid}로 본다.
        """
        try:
            s = eng().session(sid)
        except KeyError:
            raise HTTPException(404, f"없는 대화입니다: {sid}")
        if s.source == "clinic":
            raise HTTPException(403, "의료진 대화는 관제(/api/monitor/sessions/…) · 의료진 대화 분석(/api/watch/…)에서 봅니다.")
        return s

    # ── 레드팀·결과 ──────────────────────────────────────
    def save_run(job: Any) -> None:
        if state["store"] is not None:
            state["store"].save_run(job.as_dict())

    def stored_runs() -> dict[str, dict[str, Any]]:
        store = state["store"]
        return {x["id"]: x for x in store.runs()} if store is not None else {}

    def all_runs() -> list[dict[str, Any]]:
        out = stored_runs()
        out.update({jid: j.as_dict() for jid, j in eng().jobs.items()})          # 메모리에 있는 실행이 더 새 상태
        return list(out.values())

    def finish_run(job: Any) -> None:
        """점검이 끝나면 직전 점검과 비교해 붙이고(실제 LLM) 저장한다."""
        auto = state.get("auto")
        if auto is not None:
            try:
                auto.finished(job)
            except Exception as exc:
                print(f"[medicloak] 레드팀 비교 실패 ({job.id}): {type(exc).__name__}: {exc}")
        save_run(job)

    def start_live_job(trigger: str, *, per_type: int | None = AUTO_PER_TYPE, fuzzer: str = AUTO_FUZZER,
                       user: dict[str, Any] | None = None) -> Any:
        """실제 LLM 점검을 시작한다. 그때의 설정 · 지문을 기록에 남긴다 (자동 점검 · 직접 실행 같이)."""
        meta = state["auto"].meta(trigger) if state.get("auto") is not None else dict(trigger=trigger)
        job = eng().start_job("staged", fuzzer, per_type, live=True, on_finish=finish_run, meta=meta)
        save_run(job)
        mon().log("redteam_start", None, user=user, actor=None if user else AUTO_ACTOR, job=job.id, per_type=per_type, fuzzer=fuzzer,
                  llm="live", trigger=trigger)
        return job

    @r.post("/redteam")
    def start_job(body: Job, request: Request) -> dict[str, Any]:
        if body.llm not in ("auto", "live", "oracle"):
            raise HTTPException(422, "llm은 auto · live · oracle 중 하나입니다.")
        live = body.llm == "live" or (body.llm == "auto" and eng().live_llm is not None)
        if live:
            if eng().live_llm is None:
                raise HTTPException(400, "이 서버에는 실제 LLM이 설정되어 있지 않습니다 (--llm real).")
            return guard(lambda: start_live_job("manual", per_type=body.per_type, fuzzer=body.fuzzer, user=user_of(request))).as_dict()
        job = eng().start_job(body.profile, body.fuzzer, body.per_type, live=False, on_finish=finish_run)
        save_run(job)
        j = job.as_dict()
        mon().log("redteam_start", None, user=user_of(request), job=j["id"], per_type=body.per_type, fuzzer=body.fuzzer, llm="oracle")
        return j

    @r.post("/redteam/{jid}/cancel")
    def cancel_job(jid: str, request: Request) -> dict[str, Any]:
        j = eng().jobs.get(jid)
        if j is None:
            raise HTTPException(404, jid)
        if j.status not in ("queued", "running"):
            raise HTTPException(409, "이미 끝난 실행입니다.")
        j.cancel()
        mon().log("redteam_cancel", None, user=user_of(request), job=jid, done=j.done, total=j.total)
        return j.as_dict()

    @r.get("/redteam")
    def jobs() -> list[dict[str, Any]]:
        return [dict(x, result=None) for x in sorted(all_runs(), key=lambda x: x.get("started_at") or 0, reverse=True)]

    @r.get("/redteam/auto")
    def auto_status() -> dict[str, Any]:
        """자동 점검 설정 · 이번에 켤 때 한 일 · 도는 점검 · 마지막 비교와 경고 (autocheck.py)."""
        return state["auto"].status()

    @r.get("/redteam/{jid}")
    def job(jid: str) -> dict[str, Any]:
        if jid in eng().jobs:
            return eng().jobs[jid].as_dict()
        x = stored_runs().get(jid)
        if x is None:
            raise HTTPException(404, jid)
        return x

    @r.get("/poc")
    def poc() -> dict[str, Any]:
        if not POC_FILE.exists():
            raise HTTPException(404, "webdemo/data/poc_summary.json이 없습니다.")
        raw = json.loads(POC_FILE.read_text(encoding="utf-8"))
        out = {name: summarize(v) for name, v in raw.items() if isinstance(v, dict) and "arms" in v}
        out["fuzzer_compare"] = {k.replace("fuzzer_compare_", ""): v for k, v in raw.items() if k.startswith("fuzzer_compare_")}
        return out

    app.include_router(w)
    app.include_router(fhir_router(emr), dependencies=guarded)
    app.include_router(terminology_router(), dependencies=guarded)   # 의료 용어 RAG (/api/terminology/…). 아래 '없는 경로'보다 먼저

    @r.api_route("/{rest:path}", methods=["GET", "POST"])
    def unknown(rest: str):
        raise HTTPException(404, f"없는 API 경로입니다: /api/{rest}")

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


NO_BUILD_HTML = """<!doctype html><html lang="ko"><meta charset="utf-8"><title>MediCloak</title>
<body style="font-family:system-ui,sans-serif;max-width:640px;margin:64px auto;padding:0 16px;line-height:1.7;color:#161827">
<h1 style="font-size:22px">화면 파일이 아직 없습니다</h1>
<p>API 서버는 켜져 있습니다. 화면을 보려면 다른 터미널에서 프런트엔드를 한 번 빌드한 뒤 이 페이지를 새로 고치세요.</p>
<pre style="background:#ECEEF4;padding:12px 14px;border-radius:10px">cd frontend
npm install
npm run build:demo</pre>
<p>개발 서버로 띄우려면 <code>npm run dev:demo</code> 후 http://localhost:5173 을 여세요.</p></body></html>"""


app = create_app()          # uvicorn webdemo.backend.app:app
