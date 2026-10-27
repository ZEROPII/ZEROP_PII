# FastAPI 경로. frontend/src/api/httpApi.ts 의 경로·응답 모양과 같다 (접두사 /api).
#
# 오류 본문에는 의료 데이터를 넣지 않는다 (상태 코드와 짧은 사유만). LLM 호출 실패는 502로, State는 바뀌지 않는다.

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api_server.engine import ApiSettings, Conflict, NotFound, ResearchWorkspace, usage_summary, write_usage
from core.llm_client import LLMError
from medical.terminology import get_db

log = logging.getLogger("api_server")


class MessageIn(BaseModel):
    sessionId: str
    question: str
    clientMessageId: str


class PreflightIn(BaseModel):
    sessionId: str
    question: str


def create_app(settings: ApiSettings | None = None, *, workspace_factory: Callable[[], ResearchWorkspace] | None = None,
               cors_origins: list[str] | None = None) -> FastAPI:
    settings = settings or ApiSettings()
    factory = workspace_factory or (lambda: ResearchWorkspace(settings))
    holder: dict[str, ResearchWorkspace] = {}

    def ws() -> ResearchWorkspace:
        if "ws" not in holder:
            holder["ws"] = factory()
        return holder["ws"]

    def guard(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except NotFound:
            raise HTTPException(404, "존재하지 않는 사례 또는 환자 맥락입니다.")
        except Conflict as exc:
            raise HTTPException(409, str(exc))
        except LLMError as exc:
            log.warning("LLM 호출 실패: %s", type(exc).__name__)
            raise HTTPException(502, f"연구 모듈 LLM 호출 실패 ({type(exc).__name__}). 이번 질문은 State에 반영되지 않았습니다.")

    r = APIRouter(prefix="/api")

    @r.get("/health")
    def health() -> dict[str, Any]:
        w = ws()
        return dict(status="ok", arm=w.settings.arm, llm=w.settings.llm, trial=w.settings.trial_id, turns=w.turn, usage=usage_summary(w))

    @r.get("/workspace")
    def workspace() -> dict[str, Any]:
        return ws().environment()

    @r.get("/protection-policy")
    def protection_policy() -> dict[str, Any]:
        return ws().policy()

    @r.get("/patient-context")
    def patient_context() -> dict[str, Any]:
        return ws().patient_context()

    @r.get("/cases")
    def cases(patientContextId: str) -> list[dict[str, Any]]:
        return guard(lambda: ws().similar_cases(patientContextId))

    @r.get("/cases/{case_id}/session")
    def session(case_id: str) -> dict[str, Any]:
        return guard(lambda: ws().conversation(case_id))

    @r.post("/cases/{case_id}/messages")
    def messages(case_id: str, body: MessageIn) -> dict[str, Any]:
        if not body.question.strip():
            raise HTTPException(422, "질문이 비어 있습니다.")
        w = ws()
        try:
            return guard(lambda: w.ask(case_id, body.sessionId, body.question, body.clientMessageId))
        finally:
            write_usage(w)

    @r.post("/cases/{case_id}/preflight")
    def preflight(case_id: str, body: PreflightIn) -> dict[str, Any]:
        return guard(lambda: ws().preflight(case_id, body.sessionId, body.question))

    @r.get("/risk-states")
    def risk_states() -> list[dict[str, Any]]:
        w = ws()
        return [w.risk_state(cid) for cid in w.cases]

    @r.get("/cases/{case_id}/disclosures")
    def disclosures(case_id: str) -> dict[str, Any]:
        return guard(lambda: ws().disclosures(case_id))

    @r.get("/cases/{case_id}/policy-decision")
    def policy_decision(case_id: str) -> dict[str, Any]:
        return guard(lambda: ws().policy_decision(case_id))

    # ── 의료 용어 RAG (관리자용) ────────────────────────────

    @r.get("/terminology/search")
    def terminology_search(q: str, attribute: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """키워드로 용어 검색. attribute 필터: DX·MED·PROC"""
        if not q.strip():
            raise HTTPException(422, "검색어가 비어 있습니다.")
        return get_db().search(q.strip(), limit=min(limit, 100), attribute=attribute or None)

    @r.get("/terminology/{node_id:path}")
    def terminology_get(node_id: str) -> dict[str, Any]:
        """node_id로 단건 조회 + 일반화 체인 포함."""
        term = get_db().get(node_id)
        if term is None:
            raise HTTPException(404, "해당 node_id가 terminology DB에 없습니다.")
        term["generalization_chain"] = get_db().generalization_chain(node_id)
        return term

    @r.get("/terminology")
    def terminology_list(
        attribute: str | None = None,
        review_status: str | None = None,
        is_sensitive: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """전체 목록 (페이지네이션). 관리자 검토 화면용."""
        return get_db().list_terms(
            attribute=attribute or None,
            review_status=review_status or None,
            is_sensitive=is_sensitive,
            limit=min(limit, 200),
            offset=offset,
        )

    @r.post("/session/reset")
    def reset() -> dict[str, Any]:
        """새 대화(빈 State)로 다시 시작. 이전 기록 폴더는 그대로 남는다."""
        holder.pop("ws", None)
        w = ws()
        return dict(status="ok", workspaceId=w.workspace_id, log=str(w.out))

    app = FastAPI(title="ZEROOP2 Clinical Case Finder API", version="0.1.0")
    app.include_router(r)
    if cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_credentials=True, allow_methods=["GET", "POST"],
                           allow_headers=["Content-Type", "Accept"])
    return app
