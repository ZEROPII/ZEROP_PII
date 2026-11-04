# 테스트용 가짜 Anthropic Messages API (core.llm_client.LLMClient의 session 자리에 끼운다).
#
# 실제 키 · 네트워크 없이 '--llm real' 경로(ClientRoleLLM → LLMClient → HTTP)를 끝까지 돌리기 위한 것.
#   대상 AI   : 질문이 가리킨 사례 문서에서 처방 약 하나와 첫 처방 시작일을 문장으로 답한다 (실제 LLM처럼 줄 형식 없음)
#   추출기    : 답에 나온 약 이름(MED)과 날짜(PERIOD, MEDICATION_START)를 같은 사건(e1)으로 JSON 배열에 담는다
#   재작성기  : [바꿀 표현]대로 고친다 (넓게 → 넓은 표현 그대로, 빼기 → 그 값을 지움)
# fail_status를 주면 그 HTTP 상태로 답한다 (401: 키 오류처럼 바로 실패, 429/5xx: 재시도 뒤 실패).
# period_in_med=True면 추출기가 날짜를 따로 된 PERIOD 단서로 내지 않고 약 항목의 period_start 칸에만 적는다
#   (2026-11-04 실제 claude-haiku-4.5 추출기에서 나온 모양).

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class FakeResponse:
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status_code = status
        self._body = body
        self.text = json.dumps(body, ensure_ascii=False)
        self.headers: dict[str, str] = {}

    def json(self) -> dict[str, Any]:
        return self._body


class FakeAnthropic:
    def __init__(self, *, fail_status: int | None = None, delay: float = 0.0, drop_date: bool = True, period_in_med: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail_status = fail_status
        self.delay = delay
        self.drop_date = drop_date
        self.period_in_med = period_in_med
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def close(self) -> None:
        pass

    def post(self, url: str, headers: dict[str, str] | None = None, json: dict[str, Any] | None = None, timeout: float | None = None):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.calls.append(dict(url=url, headers=dict(headers or {}), payload=json))
        try:
            if self.delay:
                time.sleep(self.delay)
            if self.fail_status:
                return FakeResponse(self.fail_status, {"type": "error", "error": {"type": "authentication_error", "message": "invalid key"}})
            text = self.answer(json or {})
            return FakeResponse(200, {"content": [{"type": "text", "text": text}], "model": (json or {}).get("model"), "stop_reason": "end_turn",
                                      "usage": {"input_tokens": 120, "output_tokens": 30}})
        finally:
            with self.lock:
                self.active -= 1

    def roles(self) -> list[str]:
        out = []
        for c in self.calls:
            p = c["payload"]
            u = p["messages"][-1]["content"]
            out.append("target" if p.get("system") else "extractor" if u.startswith("너는 의료 대화의 정보 추출기다")
                       else "rewriter" if u.startswith("너는 병원 임상 의사결정 지원 AI의 답변을") else "other")
        return out

    # ── 역할별 답 ──
    def answer(self, p: dict[str, Any]) -> str:
        system = p.get("system") or ""
        user = p["messages"][-1]["content"]
        if "[검색된 사례]" in system:
            m = re.search(r"사례\s*(\d+)", user)
            n = m.group(1) if m else "1"
            block = system.split(f"[사례{n}]")[1].split("\n\n[사례")[0]
            d = re.search(r"처방 약: (.+?)\.\n\[\d+\] 위 약 첫 처방 시작일: (\d{4}-\d{2}-\d{2})", block)
            if d:
                return f"사례{n} 환자는 {d.group(1)}를 처방받았고, 첫 처방 시작일은 {d.group(2)}입니다."
            return f"사례{n} 기록에는 처방 약이 없습니다."
        if user.startswith("너는 의료 대화의 정보 추출기다"):
            resp = user.split("[이번 답변]")[-1]
            obs = []
            for m in re.finditer(r"(사례\d+) 환자는 (.+?)를 처방받았고", resp):
                obs.append(dict(attribute="MED", raw_value=m.group(2), evidence_spans=[m.group(2)], inference_mode="EXPLICIT", confidence=5,
                                case_ref=m.group(1), subject="TARGET_PATIENT", context_status="HISTORY", event_ref="e1", med_assertion="PRESCRIBED"))
                if self.period_in_med:
                    dm = _DATE.search(resp[m.end():])
                    if dm:
                        obs[-1]["period_start"] = dm.group(0)
                    continue
                for dm in _DATE.finditer(resp[m.end():]):
                    obs.append(dict(attribute="PERIOD", raw_value=dm.group(0), evidence_spans=[dm.group(0)], inference_mode="EXPLICIT",
                                    confidence=5, case_ref=m.group(1), subject="TARGET_PATIENT", context_status="HISTORY", event_ref="e1",
                                    time_role="MEDICATION_START"))
            return json.dumps(obs, ensure_ascii=False)
        if user.startswith("너는 병원 임상 의사결정 지원 AI의 답변을"):
            head, resp = user.rsplit("[원 답변]", 1)          # 지시문 첫 줄에도 '[원 답변]' · '[바꿀 표현]'이 있어 마지막 것을 쓴다
            changes = head.rsplit("[바꿀 표현]", 1)[1]
            resp = resp.strip()
            for ln in changes.strip().splitlines():
                g = re.search(r"'([^']+)' → 넓게: '([^']+)'", ln)
                if g:
                    resp = resp.replace(g.group(1), g.group(2))
                    continue
                s = re.search(r"'([^']+)' → 빼기", ln)
                if s and self.drop_date:
                    resp = resp.replace(f"를 처방받았고, 첫 처방 시작일은 {s.group(1)}입니다", "를 처방받았습니다").replace(s.group(1), "(비공개)")
            return resp
        return "확인"
