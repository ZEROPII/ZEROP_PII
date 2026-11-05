# 의료진 화면 API에서 재식별 위험 숫자를 지운다 (ADR-0020 남은 일 · ADR-0021).
#
# 의료진 화면은 처음부터 후보 수 · 기준값을 그리지 않았지만, 응답 JSON에는 남아 있어 개발자 도구로 볼 수 있었다.
# 이제 의료진 화면 API(/api/…)는 언제나 이 모듈을 거쳐 보낸다 (데모 모드 · 운영 모드 모두).
#   지우는 것 : 후보 수 k · kBefore · kAfter · currentK · projectedK · 기준값(minK · suppressK) · 기준 집단 크기,
#               숫자가 든 설명 문장(protection.explanation · levelDescription · 공개 이력 description · 보내기 전 message)
#   남기는 것 : 무엇을 어떻게 보였는지 (그대로 · 범위 · 비공개), 공개된 값, 세부 정보 제한 여부(disclosureAllowed)
# 숫자가 필요한 판정 근거(policy-decision)는 의료진 API에서 403이고, 보안 담당자 API(/api/watch/{대화})에서만 준다.

from __future__ import annotations

from typing import Any

from medical.defense import ALLOW, GENERALIZE, SUPPRESS

LIMITED = "세부 정보 제한"
OPEN = "제한 없음"


def risk(r: dict[str, Any]) -> dict[str, Any]:
    allowed = bool(r.get("disclosureAllowed", True))
    # 위험 단계(위험 · 추가 공개 제한 · 여유)도 후보 수 구간이므로 두 단계로만 알린다.
    return dict(r, k=None, riskLevel="safe" if allowed else "caution", statusLabel=OPEN if allowed else LIMITED)


def _safe_desc(action: str, value: str | None) -> str:
    if action == GENERALIZE:
        return f"범위로 공개: {value}" if value else "범위로 공개"
    if action == SUPPRESS:
        return "비공개"
    return value or "그대로 공개"


def transformation(t: dict[str, Any]) -> dict[str, Any]:
    out = dict(t, levelDescription=_safe_desc(t["action"], t.get("disclosedValue")))
    out.pop("kIfRaw", None)
    return out


def protection(p: dict[str, Any] | None) -> dict[str, Any] | None:
    if p is None:
        return None
    out = dict(p, kBefore=None, kAfter=None, explanation=None, transformations=[transformation(t) for t in p.get("transformations", [])])
    out.pop("checks", None)                 # 고친 답을 다시 확인한 기록(후보 수 · 필요한 수)은 보안 담당자 화면에서만
    return out


def message(m: dict[str, Any]) -> dict[str, Any]:
    if m.get("protection") is None:
        return m
    return dict(m, protection=protection(m["protection"]))


def conversation(c: dict[str, Any]) -> dict[str, Any]:
    return dict(c, messages=[message(m) for m in c["messages"]])


def entry(e: dict[str, Any]) -> dict[str, Any]:
    action = e["action"]
    value = e.get("value")
    if action == ALLOW and value is None:
        value = e.get("description")
    return dict(e, description=_safe_desc(action, value), value=None if action == SUPPRESS else value)


def disclosures(d: dict[str, Any]) -> dict[str, Any]:
    return dict(d, entries=[entry(e) for e in d["entries"]])


def preflight(a: dict[str, Any], *, live: bool = False) -> dict[str, Any]:
    out = dict(a, currentK=None, projectedK=None, message=None)
    # estimate('oracle')는 숫자가 아니라 '기록대로 답한다면 미리 센 것'이라는 표시다. 의료진 화면이 확정처럼 말하지 않게 남긴다 (ADR-0031)
    out["estimate"] = "oracle" if a.get("estimate") == "oracle" else None
    if live and a.get("understood") is False:
        # 실제 LLM은 어떤 문장이든 답하므로 '묻는 항목을 찾지 못함'으로 막지 않는다. 보내면 서버가 판정한다.
        out["supported"] = False
    return out


def policy(p: dict[str, Any]) -> dict[str, Any]:
    return dict(p, minK=None, suppressK=None, populationSize=None)


def send_result(r: dict[str, Any]) -> dict[str, Any]:
    return dict(r, userMessage=message(r["userMessage"]), assistantMessage=message(r["assistantMessage"]), riskState=risk(r["riskState"]),
                newDisclosures=[entry(e) for e in r["newDisclosures"]], relatedRiskStates=[risk(x) for x in r.get("relatedRiskStates") or []])


# 의료진 응답에 남으면 안 되는 키 (테스트와 점검 스크립트가 쓴다)
NUMBER_KEYS = ("k", "kBefore", "kAfter", "currentK", "projectedK", "minK", "suppressK", "populationSize", "kIfRaw", "need")


def leaked_numbers(obj: Any, path: str = "") -> list[str]:
    """응답 JSON에서 숫자가 남은 위험 숫자 키의 경로 목록 (비어 있어야 한다)."""
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else k
            if k in NUMBER_KEYS and isinstance(v, (int, float)) and not isinstance(v, bool):
                out.append(p)
            out += leaked_numbers(v, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += leaked_numbers(v, f"{path}[{i}]")
    return out
