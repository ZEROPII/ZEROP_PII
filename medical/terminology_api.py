"""
의료 용어 API (FastAPI 라우터) — api_server(실제 LLM)와 webdemo(데모 서버)가 같은 경로로 쓴다.

  GET  /api/terminology/status                      DB 상태 (용어 수 · 설명 채운 수 · 검토 수)
  GET  /api/terminology/search?q=&attribute=&limit=  검색 (이유진 경로와 같음, 앞부분 · 부분 일치 · 별칭 · 코드 검색 추가)
  POST /api/terminology/detect {texts, view}         답변 문장 속 용어 위치와 요약 카드 (화면 자동 표시용)
  GET  /api/terminology?attribute=&review_status=&is_sensitive=&limit=&offset=   목록 (이유진 경로와 같음)
  GET  /api/terminology/{node_id}                    카드: 설명 + 일반화 체인 + 별칭 (이유진 경로와 같음)
모든 경로에 view=security|clinician (기본 security = 이유진 API와 같은 필드). clinician은 기준 집단 환자 수를 뺀다.
LLM은 부르지 않는다. 요청 본문(답변 문장)은 기록하지 않는다.
"""

from __future__ import annotations

from typing import Any, Callable, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from medical.term_service import TermService, get_service

View = Literal["security", "clinician"]


class DetectIn(BaseModel):
    texts: list[str] = Field(..., max_length=80)
    view: View = "security"


def terminology_router(service: Callable[[], TermService] = get_service) -> APIRouter:
    r = APIRouter(prefix="/api/terminology", tags=["terminology"])

    def svc() -> TermService:
        s = service()
        if not s.available:
            raise HTTPException(503, f"용어 DB를 열 수 없습니다. {s.status()['build_command']} 로 만드세요.")
        return s

    @r.get("/status")
    def status() -> dict[str, Any]:
        return service().status()

    @r.get("/search")
    def search(q: str, attribute: str | None = None, limit: int = 20, view: View = "security") -> list[dict[str, Any]]:
        if not q.strip():
            raise HTTPException(422, "검색어가 비어 있습니다.")
        return svc().search(q, attribute=attribute or None, limit=max(1, min(limit, 100)), view=view)

    @r.post("/detect")
    def detect(body: DetectIn) -> dict[str, Any]:
        texts = [t[:20000] for t in body.texts]
        return svc().detect(texts, view=body.view)

    @r.get("")
    def list_terms(attribute: str | None = None, review_status: str | None = None, is_sensitive: bool | None = None,
                   limit: int = 50, offset: int = 0, view: View = "security") -> dict[str, Any]:
        return svc().list_terms(attribute=attribute or None, review_status=review_status or None, is_sensitive=is_sensitive,
                                limit=max(1, min(limit, 200)), offset=max(0, offset), view=view)

    @r.get("/{node_id:path}")
    def card(node_id: str, view: View = "security") -> dict[str, Any]:
        c = svc().card(node_id, view=view)
        if c is None:
            raise HTTPException(404, "해당 node_id가 terminology DB에 없습니다.")
        return c

    return r
