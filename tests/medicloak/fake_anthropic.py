# 테스트용 가짜 Anthropic Messages API (core.llm_client.LLMClient의 session 자리에 끼운다).
#
# 실제 키 · 네트워크 없이 '--llm real' 경로(ClientRoleLLM → LLMClient → HTTP)를 끝까지 돌리기 위한 것.
#   대상 AI   : 첫 질문(턴 0, 사례 검색)에는 사례마다 진단 하나와 처방 약 하나를 한 줄씩 답한다 (주진단과 같은 진단을 고름).
#               그 뒤 질문에는 질문이 가리킨 사례 문서에서 처방 약 하나와 첫 처방 시작일을 문장으로 답한다 (실제 LLM처럼 줄 형식 없음)
#   추출기    : 답에 나온 진단(DX) · 약 이름(MED) · 날짜(PERIOD, MEDICATION_START)를 JSON 배열에 담는다. 약과 그 날짜는 같은 사건(e1).
#               '(비공개)'로 바뀐 값은 단서로 내지 않는다.
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
    def __init__(self, *, fail_status: int | None = None, delay: float = 0.0, drop_date: bool = True, period_in_med: bool = False,
                 drop_labels: bool = False, echo_lower: str | None = None, heed_retry: bool = False,
                 ages: dict[str, str] | None = None, broken_extract: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail_status = fail_status
        self.delay = delay
        self.drop_date = drop_date
        self.period_in_med = period_in_med
        self.drop_labels = drop_labels              # 재작성기가 '사례N' 표기를 떨어뜨리는 경우를 흉내 낸다
        # 첫 답 끝에 그 사례의 약을 소문자로 한 번 더 적는다 (실제 LLM의 '주목할 점' 문장처럼, 글자 그대로 치환으로는 안 지워지는 반복)
        self.echo_lower = echo_lower
        self.heed_retry = heed_retry                # 재작성기가 다시 고칠 때 알려 준 '남은 표현'을 지운다
        self.ages = dict(ages or {})                # '나이'를 물으면 사례마다 이 글자로 답한다 ('33-38세' 같은 범위)
        self.broken_extract = broken_extract        # 추출기가 JSON이 아닌 답을 낸다 (첫 답 거절)
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
            if m is None and len(p["messages"]) == 1:
                return self._retrieval_answer(system, self.echo_lower)
            n = m.group(1) if m else "1"
            if "나이" in user and self.ages.get(f"사례{n}"):
                return f"사례{n} 환자는 당시 {self.ages[f'사례{n}']}였습니다."
            block = system.split(f"[사례{n}]")[1].split("\n\n[사례")[0]
            d = re.search(r"처방 약: (.+?)\.\n\[\d+\] 위 약 첫 처방 시작일: (\d{4}-\d{2}-\d{2})", block)
            if d:
                return f"사례{n} 환자는 {d.group(1)}를 처방받았고, 첫 처방 시작일은 {d.group(2)}입니다."
            return f"사례{n} 기록에는 처방 약이 없습니다."
        if user.startswith("너는 의료 대화의 정보 추출기다"):
            if self.broken_extract:
                return "추출하지 못했습니다"
            resp = user.split("[이번 답변]")[-1]
            obs = []
            for m in re.finditer(r"(사례\d+) 환자의 진단은 (.+?)(?:이고, (.+?)를 처방받았습니다|입니다)", resp):
                if m.group(2) != "(비공개)":
                    obs.append(dict(attribute="DX", raw_value=m.group(2), evidence_spans=[m.group(2)], inference_mode="EXPLICIT", confidence=5,
                                    case_ref=m.group(1), subject="TARGET_PATIENT", context_status="HISTORY", event_ref="dx1"))
                if m.group(3) and m.group(3) != "(비공개)":
                    obs.append(dict(attribute="MED", raw_value=m.group(3), evidence_spans=[m.group(3)], inference_mode="EXPLICIT", confidence=5,
                                    case_ref=m.group(1), subject="TARGET_PATIENT", context_status="HISTORY", event_ref="e1",
                                    med_assertion="PRESCRIBED"))
            for m in re.finditer(r"(사례\d+) 환자는 당시 (\S+세)였습니다", resp):
                obs.append(dict(attribute="AGE", raw_value=m.group(2), evidence_spans=[m.group(2)], inference_mode="EXPLICIT", confidence=5,
                                case_ref=m.group(1), subject="TARGET_PATIENT", context_status="HISTORY"))
            for m in re.finditer(r"(사례\d+) 환자는 (.+?)를 처방받았(?:고|습니다)", resp):
                if any(o["case_ref"] == m.group(1) and o["attribute"] == "MED" for o in obs):
                    continue                                                  # 한 답에서 같은 사례의 약은 처음 것만 적는다
                obs.append(dict(attribute="MED", raw_value=m.group(2), evidence_spans=[m.group(2)], inference_mode="EXPLICIT", confidence=5,
                                case_ref=m.group(1), subject="TARGET_PATIENT", context_status="HISTORY", event_ref="e1", med_assertion="PRESCRIBED"))
                end = resp.find("\n", m.end())
                rest = resp[m.end(): end if end >= 0 else len(resp)]          # 같은 줄의 날짜만 이 약의 날짜로 본다
                if self.period_in_med:
                    dm = _DATE.search(rest)
                    if dm:
                        obs[-1]["period_start"] = dm.group(0)
                    continue
                for dm in _DATE.finditer(rest):
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
            if self.heed_retry:
                left = re.findall(r"'([^']+)'", "".join(re.findall(r"남은 표현: ([^\n]*)", head)))
                resp = "\n".join(ln for ln in resp.splitlines() if not any(v in ln for v in left))
            if self.drop_labels:
                resp = re.sub(r"사례\d+\s*", "", resp)
            return resp
        return "확인"

    @staticmethod
    def _retrieval_answer(system: str, echo: str | None = None) -> str:
        panel = system.split("[현재 환자 맥락]", 1)[1].split("[검색된 사례]", 1)[0]
        main = re.search(r"주진단: (.+)", panel)
        lines, tail = [], None
        for n, block in re.findall(r"\[사례(\d+)\]\n(.*?)(?=\n\n\[사례|\Z)", system.split("[검색된 사례]", 1)[1], re.S):
            dxs = re.findall(r"\] 진단: (.+?)\.\n", block)
            dx = next((d for d in dxs if main and d in main.group(1)), dxs[0] if dxs else None)
            med = re.search(r"\] 처방 약: (.+?)\.\n", block)
            if dx and med:
                lines.append(f"사례{n} 환자의 진단은 {dx}이고, {med.group(1)}를 처방받았습니다.")
            elif dx:
                lines.append(f"사례{n} 환자의 진단은 {dx}입니다.")
            if echo == f"사례{n}" and med:
                tail = f"참고로 사례{n} 환자는 {med.group(1).lower()}를 처방받았습니다."
        return "\n".join(lines + ([tail] if tail else []))
