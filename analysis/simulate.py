# 같은 관찰을 조건만 바꿔 다시 판정한다
#
# 갈래 (arm)
#   C0      → 방어 없음. 원래 답변의 관찰을 모두 공개한다
#   C1      → 누적 방어. 지금까지 공개된 State 위에서 Defender가 판단한다 (실험의 제안 방식)
#   C1S     → 턴별 방어. 빈 State에서 이번 답변만 보고 판단한다 (대조군)
#   STATIC  → 고정 일반화. 방어 판단 없이 새 값을 모두 s단계 위로 올려 공개한다 (전통적 일반화 기준선)
#
# 조건 (Condition)
#   k_req              → Defender가 지키려는 값 (운영 설정)
#   eval_k             → 위반을 세는 평가 기준. 운영 설정을 바꿔도 같은 잣대로 비교하려고 따로 둔다
#   population         → 기준 집단 변형 이름 (populations.py)
#   max_generalization → Defender가 한 값을 올릴 수 있는 최대 단계 (None = 제한 없음)
#   static_level       → STATIC 갈래의 고정 단계
#   miss_rate / miss_seed → 추출 누락 모의. Defender가 관찰의 이 비율을 보지 못한 채 판단하고,
#                           보지 못한 값은 그대로 공개된다 (공격자는 본다)
#   normalization      → current (현재 해석 규칙으로 다시 정규화) / recorded (실행 당시 정규화 그대로)
#
# 공개 가정: Defender가 허용·일반화한 값만 공개된다 (이상적 재작성). 실제 재작성과의 차이는 consistency로 본다.
#
# 정보 유지량 (유용성 지표)
#   새 공개분 하나마다 1 − (올린 단계 / 올릴 수 있는 최대 단계). 그대로면 1, 억제면 0.
#   올릴 수 있는 단계는 그 갈래의 실제 공개 State 기준으로 센다 (이미 공개된 값 위로는 정보가 없으므로).
#   Defender의 information_loss와 같은 정의다.
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field, replace
from typing import Any, Sequence

from adapters.ontology_risk import OntologyRiskSession
from adapters.risk_adapter import RiskConfig
from analysis.dialogues import Dialogue
from analysis.populations import PopulationBank
from normalizer.normalizer import MappingReason, MappingStatus, NormalizedObservation
from ontology.defender import DeltaItem, _ladder
from ontology.normalizer import OntologyNormalizer
from validation.validator import OntologyValidator

ARMS = ("C0", "C1S", "C1", "STATIC")


@dataclass(frozen=True)
class Condition:
    arm: str
    k_req: int
    eval_k: int
    population: str
    max_generalization: int | None = None
    static_level: int = 0
    miss_rate: float = 0.0
    miss_seed: int = 0
    normalization: str = "current"

    def __post_init__(self) -> None:
        if self.arm not in ARMS:
            raise ValueError(f"알 수 없는 갈래: {self.arm}")
        if self.k_req < 1 or self.eval_k < 1:
            raise ValueError("k_req와 eval_k는 1 이상이어야 합니다.")

    @property
    def label(self) -> str:
        if self.arm == "STATIC":
            return f"STATIC-G{self.static_level}"
        if self.arm == "C0":
            return "C0"
        extra = "" if self.max_generalization is None else f"-g{self.max_generalization}"
        return f"{self.arm}-k{self.k_req}{extra}"


@dataclass(frozen=True)
class TurnResult:
    turn: int
    k_run: int
    k_val: int
    delta: int              # 새 공개분 수 (이 갈래의 공개 State 기준)
    retained: float         # 새 공개분의 정보 유지량 합
    intervened: bool
    refused: bool
    suppressed: int
    generalized: int
    missed: int
    defense_ms: float
    reason: str | None = None   # 개입 이유 (NEW_ZERO_MATCH / BELOW_FLOOR / CONFLICT)


@dataclass(frozen=True)
class UnitResult:
    """한 대상(실행·대상)을 한 조건으로 끝까지 판정한 결과"""
    unit: str
    run_id: str
    target_id: str
    condition: Condition
    turns: tuple[TurnResult, ...]

    @property
    def min_k_val(self) -> int:
        valid = [t.k_val for t in self.turns if t.k_val > 0]
        return min(valid) if valid else 0

    @property
    def violated(self) -> bool:
        return any(1 <= t.k_val < self.condition.eval_k for t in self.turns)

    @property
    def first_violation(self) -> int | None:
        return next((t.turn for t in self.turns if 1 <= t.k_val < self.condition.eval_k), None)

    @property
    def zero_turns(self) -> int:
        return sum(1 for t in self.turns if t.k_val == 0)


@dataclass
class Context:
    """조건 사이에 함께 쓰는 것들 (기준 집단, 정규화 결과, 검증기)"""
    bank: PopulationBank
    _normalized: dict[tuple[str, int, str], tuple[NormalizedObservation, ...]] = field(default_factory=dict)
    _validators: dict[str, OntologyValidator] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.normalizer = OntologyNormalizer(self.bank.ontology, self.bank.parser)

    def validator(self, population: str) -> OntologyValidator:
        if population not in self._validators:
            self._validators[population] = OntologyValidator(self.bank.index(population), self.bank.master)
        return self._validators[population]

    def observations(self, dialogue: Dialogue, index: int, mode: str) -> tuple[NormalizedObservation, ...]:
        key = (dialogue.unit, index, mode)
        if key not in self._normalized:
            turn = dialogue.turns[index]
            if mode == "recorded":
                self._normalized[key] = tuple(_from_record(item) for item in turn.recorded)
            elif mode == "current":
                self._normalized[key] = self.normalizer.normalize_all(turn.raw)
            else:
                raise ValueError(f"알 수 없는 정규화 방식: {mode}")
        return self._normalized[key]


def _from_record(item: dict[str, Any]) -> NormalizedObservation:
    return NormalizedObservation(
        observation_id=item["observation_id"], attribute=item["attribute"], raw_value=item.get("raw_value") or "",
        value_en=item.get("value_en"), confidence=int(item.get("confidence") or 0),
        source_turn=int(item.get("source_turn") or 0), status=MappingStatus(item.get("status") or "UNMAPPED"),
        reason=MappingReason(item.get("reason") or "NOT_IN_REFERENCE"), canonical_value=item.get("canonical_value"),
    )


def _missed(unit: str, turn: int, observation_id: str, rate: float, seed: int) -> bool:
    if rate <= 0:
        return False
    digest = hashlib.sha256(f"{seed}:{unit}:{turn}:{observation_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2 ** 64 < rate


def risk_config(k_req: int) -> RiskConfig:
    threshold = k_req - 1
    return RiskConfig(risk_threshold=threshold, generalize_threshold=max(RiskConfig().generalize_threshold, threshold))


def simulate(dialogue: Dialogue, condition: Condition, context: Context) -> UnitResult:
    """
    input : dialogue (기록된 대화), condition, context
    output : UnitResult (턴마다 k_run, k_val, 정보 유지량, 개입 여부)
    """
    index = context.bank.index(condition.population)
    validator = context.validator(condition.population)
    session = OntologyRiskSession(index, dialogue.target_id, f"sim-{dialogue.unit}-{condition.label}",
                                  risk_config(condition.k_req), max_generalization=condition.max_generalization)
    results: list[TurnResult] = []

    for position, turn in enumerate(dialogue.turns):
        observations = context.observations(dialogue, position, condition.normalization)
        state = session.committed_qis
        delta = _delta(session, observations)
        defense_ms = 0.0
        refused = intervened = False
        suppressed = generalized = missed = 0
        reason = None
        released: list[NormalizedObservation]

        if condition.arm == "C0":
            released = list(observations)
            retained = float(len(delta))
        elif condition.arm == "STATIC":
            released, retained, generalized, suppressed = _static(index, state, observations, delta,
                                                                  condition.static_level)
            intervened = bool(generalized or suppressed)
        elif turn.extraction_failed:
            released, retained, refused = [], 0.0, True       # 실제 gate와 같이 확인할 수 없는 답은 내보내지 않는다
        else:
            seen = [o for o in observations
                    if not _missed(dialogue.unit, turn.turn, o.observation_id, condition.miss_rate, condition.miss_seed)]
            unseen = [o for o in observations if o not in seen]
            missed = len(unseen)
            judge = session if condition.arm == "C1" else session.fresh()
            started = time.perf_counter()
            outcome = judge.defend(seen)
            defense_ms = (time.perf_counter() - started) * 1000
            allowed = set(outcome.allowed_ids)
            lifted = {key: node for key, _, _, node in outcome.generalized}
            released = [o for o in seen if o.observation_id in allowed]
            released += [replace(o, canonical_value=lifted[o.observation_id]) for o in seen if o.observation_id in lifted]
            released += unseen
            generalized, suppressed = len(lifted), len(outcome.suppressed_ids)
            intervened = bool(lifted or outcome.suppressed_ids)
            reason = (outcome.defense_log[0].get("intervention_reason") if outcome.defense_log else None) if intervened else None
            retained = _retained(index, state, delta, {o.observation_id: o.canonical_value for o in released})

        delta_count = len(delta)
        session.commit(released)
        k_val = validator.validate(dialogue.target_id, session.committed_qis).k_val
        results.append(TurnResult(turn.turn, session.k_current, k_val, delta_count, retained, intervened, refused,
                                  suppressed, generalized, missed, defense_ms, reason))
    return UnitResult(dialogue.unit, dialogue.run_id, dialogue.target_id, condition, tuple(results))


def _delta(session: OntologyRiskSession, observations: Sequence[NormalizedObservation]) -> list[DeltaItem]:
    """이 갈래의 공개 State 기준 새 공개분 (QI당 하나)"""
    selection = session.select(observations)
    _, delta_by_qi, _ = session._apply(session.committed_qis, selection.accepted)
    return [DeltaItem(qi.source or "", qi.qi_type, str(qi.value)) for qi in delta_by_qi.values()]


def _retained(index, state: dict[str, str], delta: Sequence[DeltaItem], released: dict[str, str | None]) -> float:
    total = 0.0
    for item in delta:
        ladder = _ladder(index, state, item)
        limit = len(ladder) - 1
        node = released.get(item.key)
        if node is None or limit == 0:
            continue
        if node in ladder:
            total += 1 - ladder.index(node) / limit
        else:
            # 같은 QI의 다른 관찰로 공개된 경우: 그 값이 사다리 위 어디에 있는지 본다
            hit = next((step for step, rung in enumerate(ladder)
                        if rung is not None and index.ontology.is_same_or_descendant(node, rung)), None)
            total += 0.0 if hit is None else 1 - hit / limit
    return total


def _static(index, state: dict[str, str], observations: Sequence[NormalizedObservation], delta: Sequence[DeltaItem],
            level: int) -> tuple[list[NormalizedObservation], float, int, int]:
    """새 공개분을 모두 level단계 위로 올린다. 사다리 끝(억제)에 닿으면 뺀다."""
    plan: dict[str, str | None] = {}
    generalized = suppressed = 0
    retained = 0.0
    for item in delta:
        ladder = _ladder(index, state, item)
        limit = len(ladder) - 1
        step = min(level, limit)
        plan[item.key] = ladder[step]
        if ladder[step] is None:
            suppressed += 1
        elif step > 0:
            generalized += 1
        retained += (1 - step / limit) if limit else 0.0
    released = []
    for o in observations:
        if o.observation_id in plan:
            if plan[o.observation_id] is not None:
                released.append(replace(o, canonical_value=plan[o.observation_id]))
        elif not o.is_mapped:
            released.append(o)
        # 새 공개분이 아닌 관찰(이미 공개된 값과 같거나 넓은 값)은 정보를 더하지 않으므로 빼도 같다
    return released, retained, generalized, suppressed
