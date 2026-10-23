# Privacy State와 QI 데이터 구조를 정의하는 파일
# 현재까지 어떤 QI가 쌓였는지 관리하는 파일

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


DEFAULT_QI_ORDER = [
    "AGE",
    "SEX",
    "REGION",
    "DX",
    "PROC",
    "MED",
    "PLAN",
]

# 한 사람당 여러 값을 가질 수 있는 QI — {"code", "age", "date"} 번들 리스트로 저장
# PERIOD는 독립 필드 없이 각 이벤트 번들의 "date" 필드로 내포됨
MULTI_VALUE_QIS: frozenset[str] = frozenset({"DX", "PROC", "MED", "PLAN"})

DIRECT_IDENTIFIER_FIELDS = {"patient_id"}
QIStatus = Literal["committed", "pending", "conflict", "rejected"]


@dataclass(frozen=True)
class QIObservation:
    qi_type: str
    value: Any
    source_turn: int | None = None
    confidence: float | None = None
    source: str | None = None


@dataclass
class PrivacyState:
    target_id: str
    session_id: str
    turn: int = 0
    qis: dict[str, dict[str, Any]] = field(default_factory=dict)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    pending: list[dict[str, Any]] = field(default_factory=list)

    def committed_qis(self) -> dict[str, Any]:
        return {
            qi_type: entry["value"]
            for qi_type, entry in self.qis.items()
            if entry.get("status") == "committed"
        }

    def copy(self) -> "PrivacyState":
        return PrivacyState(
            target_id=self.target_id,
            session_id=self.session_id,
            turn=self.turn,
            qis={key: dict(value) for key, value in self.qis.items()},
            conflicts=[dict(value) for value in self.conflicts],
            pending=[dict(value) for value in self.pending],
        )


def update_state(
    state: PrivacyState,
    observations: list[QIObservation],
    *,
    min_confidence: float = 0.5,
) -> PrivacyState:
    next_state = state.copy()

    for observation in observations:
        qi_type = observation.qi_type
        normalized = normalize_qi_value(qi_type, observation.value)
        event = {
            "qi_type": qi_type,
            "value": normalized,
            "source_turn": observation.source_turn,
            "confidence": observation.confidence,
            "source": observation.source,
        }

        if qi_type not in DEFAULT_QI_ORDER or normalized in (None, ""):
            event["reason"] = "unsupported_or_empty_qi"
            next_state.pending.append(event)
            continue

        if observation.confidence is not None and observation.confidence < min_confidence:
            event["reason"] = "low_confidence"
            next_state.pending.append(event)
            continue

        # 다중값 QI: {"code","age","date"} 번들 리스트에 추가 (code 기준 중복 제거)
        if qi_type in MULTI_VALUE_QIS:
            new_values: list[Any] = normalized if isinstance(normalized, list) else [normalized]
            existing = next_state.qis.get(qi_type)
            if existing is None:
                next_state.qis[qi_type] = {
                    **event,
                    "value": list(new_values),
                    "status": "committed",
                    "history": [event],
                }
            else:
                current_list: list[Any] = existing.get("value", [])
                added = False
                for v in new_values:
                    if not _is_duplicate_event(v, current_list):
                        current_list.append(v)
                        added = True
                existing["value"] = current_list
                existing.setdefault("history", []).append(
                    {**event, "reason": "appended" if added else "same_value"}
                )
            continue

        existing = next_state.qis.get(qi_type)
        if existing is None:
            next_state.qis[qi_type] = {
                **event,
                "status": "committed",
                "history": [event],
            }
            continue

        existing_value = existing.get("value")
        if existing_value == normalized:
            existing.setdefault("history", []).append({**event, "reason": "same_value"})
            continue

        if is_more_specific(qi_type, normalized, existing_value):
            existing.setdefault("history", []).append(
                {**event, "reason": "more_specific_update", "previous_value": existing_value}
            )
            existing.update(event)
            existing["status"] = "committed"
            continue

        if is_more_specific(qi_type, existing_value, normalized):
            existing.setdefault("history", []).append(
                {**event, "reason": "less_specific_ignored", "kept_value": existing_value}
            )
            continue

        next_state.conflicts.append(
            {
                **event,
                "reason": "conflicting_value",
                "existing_value": existing_value,
            }
        )

    return next_state


def normalize_qi_value(qi_type: str, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        # 번들 이벤트: code 필드 필수, age·date는 있으면 유지
        code = (value.get("code") or "").strip()
        if not code:
            return None
        result: dict[str, str] = {"code": code}
        age = (value.get("age") or "").strip()
        date = (value.get("date") or "").strip()
        date_end = (value.get("date_end") or "").strip()
        if age:
            result["age"] = age
        if date:
            result["date"] = date
        if date_end:
            result["date_end"] = date_end
        return result
    if isinstance(value, str):
        normalized = value.strip()
        return normalized if normalized else None
    return value


def _is_duplicate_event(v: Any, current_list: list[Any]) -> bool:
    """code 기준 중복 여부 확인."""
    v_code = v.get("code") if isinstance(v, dict) else v
    for e in current_list:
        e_code = e.get("code") if isinstance(e, dict) else e
        if e_code == v_code:
            return True
    return False


def is_more_specific(qi_type: str, candidate: Any, existing: Any) -> bool:
    """노드 계층 depth 기준으로 candidate가 existing보다 더 구체적인지 확인."""
    if candidate in (None, "") or existing in (None, ""):
        return False
    if str(candidate) == str(existing):
        return False
    try:
        from .loader import NODE_REGISTRY  # noqa: PLC0415
    except ImportError:
        return False
    c_depth = NODE_REGISTRY.get(str(candidate), {}).get("depth", -1)
    e_depth = NODE_REGISTRY.get(str(existing), {}).get("depth", -1)
    return c_depth > e_depth
