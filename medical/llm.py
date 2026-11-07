# LLM 역할 인터페이스 (하네스 명세 §11-1)
#
# 역할: doc_writer · target · mutator · checker · extractor · rewriter(Defender 재작성, 본 연구 추가)
#   target   : system = 대상 AI 시스템 프롬프트(검색 사례 5건 포함), messages = 대화 이력 (다중 턴)
#   나머지   : system = 채운 전체 프롬프트, messages = [] → user 메시지 하나로 보낸다
# 온도는 설정값(기본 0)을 모든 역할에 명시적으로 보낸다. 호출마다 역할·모델·토큰·지연을 usage에 남긴다.
#
# MockRoleLLM은 배선 확인 전용이다. 추출기가 문서 사실표를 몰래 읽으므로(정답 누출) 결과 숫자에는 의미가 없다.
# 실제 구현은 **kw(docs·facts·response·plan)를 절대 쓰지 않는다.
#
# 호출 연결 키 (v3 진단): usage 한 줄마다 call_id(실행 안 순번)와 tag(trial_id·arm·turn·purpose·attempt)를 남긴다.
#   tag는 세션이 호출 직전에 set_tag()로 정한다. 기록 전용이며 요청 내용에는 영향이 없다.
# TTFT: core.llm_client는 비스트리밍 requests.post라 첫 토큰 시각을 관측할 수 없다. 전체 응답 시간을 TTFT로 쓰지 않는다.

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from medical.documents import template_doc

# extractor: 2048 → 2560. 근거: run_20261107_151400 llm_usage.jsonl 추출 호출 251건의 P99 = 2048(상한 도달, 잘림 162건)
#   ceil(2048 × 1.25) = 2560 (개발자 추가요청 v3 §2-2-2). 잘린 값은 상한에서 검열된 값이므로 2560은 하한 추정이다.
#   원 응답 추출 실패 156회 시도가 모두 잘림이었다 (검증_메모.md). target(1200)은 실험 조건이라 바꾸지 않았다.
MAX_TOKENS = dict(doc_writer=4096, target=1200, mutator=300, checker=300, extractor=2560, rewriter=1500)
TTFT_STATUS = "NOT_OBSERVABLE_NON_STREAMING"
TTFT_NOTE = ("core.llm_client.LLMClient는 /v1/messages를 비스트리밍(requests.post, stream 없음)으로 호출하므로 첫 토큰 도착 시각을 관측할 수 없다. "
             "전체 응답 시간(latency_ms, sec_*)을 TTFT로 쓰지 않는다. 계측하려면 payload에 stream=true를 넣고 SSE를 읽어 "
             "첫 content_block_delta(text) 수신 시각 - 요청 시작 시각을 기록해야 한다 (LLMClient·LLMResponse 변경 필요). "
             "배포 경로 TTFT는 C0=대상 AI 첫 토큰, C1·C1S=공개 답 첫 토큰(추출·방어 뒤)이므로 갈래별 정의도 따로 정해야 한다.")


class RoleLLM(Protocol):
    usage: list[dict[str, Any]]

    def complete(self, role: str, system: str, messages: list[dict[str, str]], **kw: Any) -> str: ...


def set_tag(llm: Any, **tag: Any) -> None:
    """다음 호출들의 기록용 연결 키를 바꾼다 (None 값은 지운다). tag 속성이 없는 LLM이면 아무것도 안 한다."""
    cur = getattr(llm, "tag", None)
    if isinstance(cur, dict):
        cur.update(tag)
        for k in [k for k, v in cur.items() if v is None]:
            del cur[k]


def _record(llm: Any, role: str, **fields: Any) -> dict[str, Any]:
    rec = dict(call_id=len(llm.usage) + 1, role=role, **fields, **dict(getattr(llm, "tag", {}) or {}))
    llm.usage.append(rec)
    return rec


@dataclass
class ClientRoleLLM:
    """core.llm_client.LLMClient로 실제 모델을 부른다. models: 역할별 모델 (없으면 .env LLM_MODEL)."""
    client: Any
    models: dict[str, str] = field(default_factory=dict)
    temperature: float = 0.0
    usage: list[dict[str, Any]] = field(default_factory=list)
    tag: dict[str, Any] = field(default_factory=dict)

    def complete(self, role: str, system: str, messages: list[dict[str, str]], **kw: Any) -> str:
        model = self.models.get(role) or None
        if role == "target":
            resp = self.client.chat(messages, system_prompt=system, max_tokens=MAX_TOKENS[role],
                                    temperature=self.temperature, model=model)
        else:
            resp = self.client.chat([{"role": "user", "content": system}], max_tokens=MAX_TOKENS[role],
                                    temperature=self.temperature, model=model)
        _record(self, role, model=resp.model, input_tokens=resp.input_tokens, output_tokens=resp.output_tokens,
                latency_ms=round(resp.latency_ms, 1), attempts=resp.attempts, truncated=resp.truncated,
                stop_reason=resp.stop_reason, max_tokens=MAX_TOKENS[role], ttft_ms=None)
        return resp.text


@dataclass
class MockRoleLLM:
    """
    배선 확인용 가짜.
      doc_writer : 대체 문서 형식 그대로
      target     : 사례1 문서의 문장을 대화 턴 수에 맞춰 하나씩 말함 (갈래가 달라도 같은 턴에는 같은 문장)
      mutator    : 원 질문 그대로 / checker : 모두 통과
      extractor  : 사례1 문서 사실표에서 답변에 그대로 있는 표현을 찾음 (정답 누출)
      rewriter   : Defender 계획대로 결정적으로 바꿈 (plan 인자)
    """
    usage: list[dict[str, Any]] = field(default_factory=list)
    tag: dict[str, Any] = field(default_factory=dict)

    def complete(self, role: str, system: str, messages: list[dict[str, str]], **kw: Any) -> str:
        _record(self, role, model="mock", input_tokens=0, output_tokens=0, latency_ms=0.0, attempts=1, truncated=False,
                stop_reason="end_turn", max_tokens=MAX_TOKENS[role], ttft_ms=None)
        if role == "doc_writer":
            return "\n".join(template_doc(kw["facts"]))
        if role == "target":
            d = kw["docs"][0]
            lines = [ln for ln in d["text"].splitlines() if ln.startswith("[") and ln[1:2].isdigit()]
            i = (sum(1 for m in messages if m["role"] == "user") - 1) % len(lines)
            return "사례1: " + re.sub(r"^\[\d+\]\s*", "", lines[i])
        if role == "mutator":
            m = re.search(r"\[원 질문\] (.*)", system)
            return m.group(1) if m else ""
        if role == "checker":
            return json.dumps({k: True for k in ("same_target_qi", "same_objective", "same_subject", "no_new_value",
                                                 "not_more_specific", "operator_followed")})
        if role == "extractor":
            d, r = kw["docs"][0], kw["response"]
            obs = []
            for f in d["fact_rows"]:
                if f["span_text"] and f["span_text"] in r:
                    o = dict(attribute=f["attribute"], raw_value=f["span_text"], evidence_spans=[f["span_text"]], inference_mode="EXPLICIT",
                             confidence=5, case_ref="사례1", subject="TARGET_PATIENT", context_status="UNSPECIFIED",
                             event_ref=("e_" + f["event_id"]) if f["event_id"] else None)
                    if f["attribute"] == "PERIOD":
                        o["time_role"] = "_".join(f["node_id"].split("_")[1:3])
                    if f["attribute"] == "MED":
                        o["med_assertion"] = "PRESCRIBED"
                    obs.append(o)
            return json.dumps(obs, ensure_ascii=False)
        if role == "rewriter":
            from medical.defense import apply_changes_deterministic   # 순환 import 방지
            return apply_changes_deterministic(kw["response"], kw["plan"])
        raise ValueError(role)
