# 분석 조건 묶음을 만들고 실행한다
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from analysis.dialogues import Dialogue, RunInfo
from analysis.simulate import Condition, Context, UnitResult, simulate


@dataclass(frozen=True)
class Settings:
    """
    eval_k          → 위반을 세는 평가 기준 (논문 기준 k_req = 5)
    main_population → 본 결과에 쓰는 기준 집단
    k_sweep         → 보호–유용성 곡선에서 바꿔 보는 Defender 운영 k_req 값들
    populations     → 민감도: 기준 집단 변형들
    static_levels   → 고정 일반화 기준선의 단계들
    generalization  → 민감도: Defender의 최대 일반화 단계들 (None은 본 설정이라 따로 넣지 않는다)
    miss_rates / miss_seeds → 민감도: 추출 누락 비율과 반복 횟수
    """
    eval_k: int = 5
    main_population: str = "indep-300000"
    k_sweep: tuple[int, ...] = (2, 3, 5, 10, 20, 50, 100, 200)
    populations: tuple[str, ...] = ("synthpai-300", "indep-3000", "indep-30000", "indep-300000", "joint-300000")
    static_levels: tuple[int, ...] = (1, 2, 3)
    generalization: tuple[int, ...] = (0, 1, 2)
    generalization_k: tuple[int, ...] = (5, 20, 50, 100)
    matched_k: tuple[int, ...] = (3, 5, 10, 20)
    matched_populations: tuple[str, ...] = ("synthpai-300", "indep-300000")
    turn_cuts: tuple[int, ...] = (4, 6, 8, 10, 12)
    miss_rates: tuple[float, ...] = (0.0, 0.1, 0.2, 0.3, 0.5)
    miss_seeds: int = 20
    normalization: str = "current"
    resamples: int = 5000
    seed: int = 7

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass
class Plan:
    groups: dict[str, list[Condition]] = field(default_factory=dict)

    @property
    def conditions(self) -> list[Condition]:
        seen: dict[Condition, None] = {}
        for conditions in self.groups.values():
            for condition in conditions:
                seen.setdefault(condition)
        return list(seen)


def build_plan(settings: Settings) -> Plan:
    k, pop, norm = settings.eval_k, settings.main_population, settings.normalization

    def c(arm: str, k_req: int = k, population: str = pop, **extra: Any) -> Condition:
        return Condition(arm, k_req, k, population, normalization=norm, **extra)

    plan = Plan()
    plan.groups["main"] = [c("C0"), c("C1S"), c("C1")]
    plan.groups["tradeoff"] = (
        [c("C0")]
        + [c("C1", k_req) for k_req in settings.k_sweep]
        + [c("C1S", k_req) for k_req in settings.k_sweep]
        + [c("C1", k_req, max_generalization=0) for k_req in settings.k_sweep]
        + [c("STATIC", static_level=level) for level in settings.static_levels]
    )
    plan.groups["population"] = [c(arm, population=p) for p in settings.populations for arm in ("C0", "C1S", "C1")]
    plan.groups["generalization"] = [c("C1", k_req, max_generalization=g)
                                     for k_req in settings.generalization_k for g in (*settings.generalization, None)]
    plan.groups["matched_k"] = [Condition(arm, k_value, k_value, population, normalization=norm)
                                for population in settings.matched_populations for k_value in settings.matched_k
                                for arm in ("C0", "C1S", "C1")]
    plan.groups["miss"] = [c("C1", miss_rate=rate, miss_seed=seed)
                           for rate in settings.miss_rates for seed in (range(settings.miss_seeds) if rate else (0,))]
    return plan


def consistency_conditions(info: RunInfo, fallback_k: int, fallback_population: str) -> list[Condition]:
    """실제 실행과 같은 설정(실행 당시 정규화·k_req·기준 집단)으로 다시 판정할 조건"""
    k_req = info.k_req or fallback_k
    population = info.population or fallback_population
    return [Condition(arm, k_req, k_req, population, normalization="recorded")
            for arm in ("C0", "C1S", "C1") if arm in info.arms or not info.arms]


def execute(dialogues: Sequence[Dialogue], conditions: Sequence[Condition], context: Context,
            progress: Callable[[int, int, Condition], None] | None = None) -> dict[Condition, list[UnitResult]]:
    results: dict[Condition, list[UnitResult]] = {}
    for number, condition in enumerate(conditions, 1):
        results[condition] = [simulate(d, condition, context) for d in dialogues]
        if progress:
            progress(number, len(conditions), condition)
    return results
