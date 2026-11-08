"""
오래 걸리는 POST(진료 지원 AI 열기 · 질문 · 사례 보고서)가 창 · 프록시의 유휴 제한에 끊기지 않게 한다 (ADR-0044).

macOS 데스크톱 앱 창(pywebview → WKWebView)은 응답이 60초 동안 한 바이트도 오지 않으면 요청을 끊는다. 실제 LLM으로 첫 답을
만들거나 답을 고쳐 쓰면 60초를 넘길 수 있어, 서버는 끝까지 만들었는데 화면은 '서버에 연결할 수 없습니다'를 보였다
(2026-11-08 점검, 웹 브라우저에서는 끊기지 않음). Cloudflare 같은 프록시의 응답 대기 제한(100초)도 같다.

  - FIRST_WAIT초 안에 끝나면 전과 같은 응답(상태 코드 · 머리글 그대로).
  - 넘으면 200으로 먼저 열고 EVERY초마다 공백 한 칸을 보낸 뒤 JSON 본문을 보낸다 (JSON 앞의 공백은 읽는 쪽이 무시한다).
    이때 오류는 상태 코드 대신 본문 {"detail", "_status", "_state"}로 보낸다. 앞단(api/types.ts streamedFailure)이 오류로 바꾼다.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Callable

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response, StreamingResponse

FIRST_WAIT = 20.0
EVERY = 10.0
STREAM_HEADER = "X-MediCloak-Stream"
STATE_HEADER = "X-MediCloak-State"


def _finish(box: dict[str, Any]) -> JSONResponse:
    if "err" in box:
        raise box["err"]
    if "exc" in box:
        raise box["exc"]
    return JSONResponse(content=jsonable_encoder(box["ok"]))


def run(fn: Callable[[], Any], *, first: float | None = None, every: float | None = None) -> Response:
    """fn을 따로 돌리고, 오래 걸리면 공백으로 연결을 살려 둔 채 결과를 보낸다. fn이 낸 HTTPException은 그대로 오류가 된다."""
    first = FIRST_WAIT if first is None else first
    every = EVERY if every is None else every
    box: dict[str, Any] = {}
    done = threading.Event()

    def work() -> None:
        try:
            box["ok"] = fn()
        except HTTPException as exc:
            box["err"] = exc
        except BaseException as exc:                     # noqa: BLE001 — 받는 쪽(_finish)이 다시 낸다
            box["exc"] = exc
        finally:
            done.set()

    threading.Thread(target=work, name="medicloak-long-request", daemon=True).start()
    if done.wait(first):
        return _finish(box)

    def stream():
        while not done.wait(every):
            yield b" "
        try:
            yield _finish(box).body
        except HTTPException as exc:
            state = (exc.headers or {}).get(STATE_HEADER)
            yield json.dumps({"detail": exc.detail, "_status": exc.status_code, "_state": state}, ensure_ascii=False).encode("utf-8")
        except BaseException:                            # noqa: BLE001
            yield json.dumps({"detail": "서버에서 요청을 처리하지 못했습니다.", "_status": 500, "_state": None}, ensure_ascii=False).encode("utf-8")

    return StreamingResponse(stream(), media_type="application/json", headers={"Cache-Control": "no-store", STREAM_HEADER: "1"})
