# 후보군 k와 재식별 위험도를 계산하는 파일

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .loader import PersonaRecord
from .schema import PrivacyState, QIObservation, update_state


@dataclass(frozen=True)
class CandidateSetResult:
    k: int
    candidate_ids: list[str]
    risk: float
    matched_qis: dict[str, Any]


@dataclass(frozen=True)
class ProjectedRiskResult:
    k_before: int
    k_after: int
    risk_before: float
    risk_after: float
    risk_gain: float
    risky: bool
    state_after: PrivacyState
    candidate_ids_before: list[str]
    candidate_ids_after: list[str]


def calculate_k(
    population: list[PersonaRecord],
    state_or_qis: PrivacyState | dict[str, Any],
) -> CandidateSetResult:
    qis = (
        state_or_qis.committed_qis()
        if isinstance(state_or_qis, PrivacyState)
        else state_or_qis
    )

    candidates = [
        persona
        for persona in population
        if _matches_all_qis(persona.qis, qis)
    ]
    k = len(candidates)
    risk = 1.0 / k if k > 0 else 0.0
    return CandidateSetResult(
        k=k,
        candidate_ids=[candidate.person_id for candidate in candidates],
        risk=risk,
        matched_qis=dict(qis),
    )


def evaluate_projected_risk(
    population: list[PersonaRecord],
    current_state: PrivacyState,
    candidate_qis: list[QIObservation],
    *,
    threshold: int,
    min_confidence: float = 0.5,
) -> ProjectedRiskResult:
    before = calculate_k(population, current_state)
    state_after = update_state(
        current_state,
        candidate_qis,
        min_confidence=min_confidence,
    )
    after = calculate_k(population, state_after)
    return ProjectedRiskResult(
        k_before=before.k,
        k_after=after.k,
        risk_before=before.risk,
        risk_after=after.risk,
        risk_gain=after.risk - before.risk,
        risky=after.k <= threshold if after.k > 0 else True,
        state_after=state_after,
        candidate_ids_before=before.candidate_ids,
        candidate_ids_after=after.candidate_ids,
    )


def _matches_all_qis(persona_qis: dict[str, Any], query_qis: dict[str, Any]) -> bool:
    for qi_type, expected in query_qis.items():
        actual = persona_qis.get(qi_type)
        if not _matches_qi(qi_type, actual, expected):
            return False
    return True


def _matches_qi(qi_type: str, actual: Any, expected: Any) -> bool:
    """QI 매칭.
    - expected가 리스트(누적 관찰): 모든 항목이 actual에 하나씩 매칭되어야 True (AND)
    - actual이 번들 dict 리스트: 원소 중 하나라도 expected와 매칭되면 True (OR)
    - 단일 값: 노드 동일 또는 expected가 actual의 조상이면 True
    """
    if actual is None or expected is None:
        return False

    if isinstance(expected, list):
        return all(_matches_qi(qi_type, actual, exp_item) for exp_item in expected)

    if isinstance(actual, list):
        return any(_matches_event_entry(elem, expected) for elem in actual)

    return _matches_single(actual, expected)


def _matches_event_entry(entry: Any, expected: Any) -> bool:
    """이벤트 번들(dict or str)과 expected(dict or str) 매칭.
    expected가 dict이면 명시된 필드(code/age/date)를 모두 충족해야 True.
    expected가 str이면 code 필드와만 비교.
    """
    if isinstance(entry, dict):
        code = entry.get("code", "")
        if isinstance(expected, dict):
            if "code" in expected and not _matches_single(code, expected["code"]):
                return False
            if "age" in expected and entry.get("age") != expected["age"]:
                return False
            if "date" in expected and entry.get("date") != expected["date"]:
                return False
            return True
        return _matches_single(code, str(expected))
    return _matches_single(entry, expected)


def _matches_single(actual: Any, expected: Any) -> bool:
    """단일 노드 매칭: 동일하거나 expected가 actual의 조상이면 True."""
    actual_text = str(actual).strip()
    expected_text = str(expected).strip()
    if actual_text == expected_text:
        return True
    from .loader import NODE_REGISTRY  # noqa: PLC0415
    return _is_ancestor_or_equal(expected_text, actual_text, NODE_REGISTRY)


def _is_ancestor_or_equal(query: str, patient: str, registry: dict[str, Any]) -> bool:
    """query가 patient 노드의 조상(혹은 동일)이면 True."""
    current = registry.get(patient, {}).get("parent_id")
    while current:
        if current == query:
            return True
        current = registry.get(current, {}).get("parent_id")
    return False
