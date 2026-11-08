"""
오래 걸리는 POST가 데스크톱 앱 창(WKWebView, 60초 유휴 제한)에서 끊기지 않게 공백으로 연결을 살려 두는지 (ADR-0044).
"""

from __future__ import annotations

import json
import time

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from webdemo.backend import keepalive


def make_app() -> FastAPI:
    app = FastAPI()

    @app.post("/quick")
    def quick():
        return keepalive.run(lambda: {"ok": 1}, first=1.0, every=0.05)

    @app.post("/quick-error")
    def quick_error():
        def fail():
            raise HTTPException(409, "질문을 멈췄습니다.", headers={"X-MediCloak-State": "stopped"})
        return keepalive.run(fail, first=1.0, every=0.05)

    @app.post("/slow")
    def slow():
        return keepalive.run(lambda: (time.sleep(0.4), {"answer": "현재까지 계속 처방되고 있습니다"})[1], first=0.05, every=0.05)

    @app.post("/slow-error")
    def slow_error():
        def fail():
            time.sleep(0.3)
            raise HTTPException(409, "질문을 멈췄습니다.", headers={"X-MediCloak-State": "stopped"})
        return keepalive.run(fail, first=0.05, every=0.05)

    @app.post("/slow-crash")
    def slow_crash():
        def fail():
            time.sleep(0.2)
            raise RuntimeError("환자 기록이 들어 있을 수 있는 내부 오류")
        return keepalive.run(fail, first=0.05, every=0.05)

    return app


def test_quick_requests_answer_as_before():
    c = TestClient(make_app())
    r = c.post("/quick")
    assert r.status_code == 200 and r.json() == {"ok": 1} and keepalive.STREAM_HEADER not in r.headers
    r = c.post("/quick-error")
    assert r.status_code == 409 and r.headers["X-MediCloak-State"] == "stopped" and r.json()["detail"] == "질문을 멈췄습니다."


def test_slow_requests_keep_the_connection_alive_with_spaces():
    c = TestClient(make_app())
    r = c.post("/slow")
    assert r.status_code == 200 and r.headers[keepalive.STREAM_HEADER] == "1"
    assert r.text.startswith(" ") and r.text.strip().startswith("{")           # 공백 뒤에 JSON
    assert json.loads(r.text) == {"answer": "현재까지 계속 처방되고 있습니다"}


def test_slow_failures_travel_in_the_body():
    c = TestClient(make_app())
    body = json.loads(c.post("/slow-error").text)
    assert body == {"detail": "질문을 멈췄습니다.", "_status": 409, "_state": "stopped"}
    crash = json.loads(c.post("/slow-crash").text)
    assert crash["_status"] == 500 and "환자" not in crash["detail"]            # 내부 오류 문장은 내보내지 않는다
