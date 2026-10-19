# LLM 역할 인터페이스 (하네스 명세 §11-1)
#
# 역할: doc_writer · target · mutator · checker · extractor · rewriter(Defender 재작성, 본 연구 추가)
#   target   : system = 대상 AI 시스템 프롬프트(검색 사례 5건 포함), messages = 대화 이력 (다중 턴)
#   나머지   : system = 채운 전체 프롬프트, messages = [] → user 메시지 하나로 보낸다
# 온도는 설정값(기본 0)을 모든 역할에 명시적으로 보낸다. 호출마다 역할·모델·토큰·지연을 usage에 남긴다.
#
# MockRoleLLM은 배선 확인 전용이다. 추출기가 문서 사실표를 몰래 읽으므로(정답 누출) 결과 숫자에는 의미가 없다.
# 실제 구현은 **kw(docs·facts·response·plan)를 절대 쓰지 않는다.

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from medical.documents import template_doc

MAX_TOKENS = dict(doc_writer=4096, target=1200, mutator=300, checker=300, extractor=2048, rewriter=1500)


class RoleLLM(Protocol):
    usage: list[dict[str, Any]]

    def complete(self, role: str, system: str, messages: list[dict[str, str]], **kw: Any) -> str: ...


@dataclass
class ClientRoleLLM:
    """core.llm_client.LLMClient로 실제 모델을 부른다. models: 역할별 모델 (없으면 .env LLM_MODEL)."""
    client: Any
    models: dict[str, str] = field(default_factory=dict)
    temperature: float = 0.0
    usage: list[dict[str, Any]] = field(default_factory=list)

    def complete(self, role: str, system: str, messages: list[dict[str, str]], **kw: Any) -> str:
        model = self.models.get(role) or None
        if role == "target":
            resp = self.client.chat(messages, system_prompt=system, max_tokens=MAX_TOKENS[role],
                                    temperature=self.temperature, model=model)
        else:
            resp = self.client.chat([{"role": "user", "content": system}], max_tokens=MAX_TOKENS[role],
                                    temperature=self.temperature, model=model)
        self.usage.append(dict(role=role, model=resp.model, input_tokens=resp.input_tokens, output_tokens=resp.output_tokens,
                               latency_ms=round(resp.latency_ms, 1), attempts=resp.attempts, truncated=resp.truncated))
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

    def complete(self, role: str, system: str, messages: list[dict[str, str]], **kw: Any) -> str:
        self.usage.append(dict(role=role, model="mock", input_tokens=0, output_tokens=0, latency_ms=0.0, attempts=1, truncated=False))
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
