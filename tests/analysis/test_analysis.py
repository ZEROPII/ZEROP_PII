from __future__ import annotations

import ast
from pathlib import Path

import pytest

from analysis.dialogues import Dialogue, RecordedTurn, _raw_observation
from analysis.populations import PopulationBank, PopulationSpec
from analysis.simulate import Condition, Context, simulate
from analysis import stats
from ontology.defender import DeltaItem, plan_release
from tests.orchestrator.sample_data import TARGET_ID, make_population

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def context() -> Context:
    return Context(PopulationBank(population=make_population()))


def _turn(number: int, *items: tuple[str, str, str]) -> RecordedTurn:
    raw = tuple(_raw_observation({"observation_id": f"t{number}-o{i}", "attribute": attribute, "raw_value": raw_value,
                                  "value_en": value_en, "inference_mode": "EXPLICIT", "confidence": 5,
                                  "source_turn": number}, number)
                for i, (attribute, raw_value, value_en) in enumerate(items, 1))
    return RecordedTurn(number, raw, (), False)


def _dialogue() -> Dialogue:
    # 취리히 거주(3명) → 소프트웨어 엔지니어(대상 1명만 남음) → 새 정보 없음
    return Dialogue("run", TARGET_ID, (
        _turn(1, ("LOC", "취리히", "Zurich")),
        _turn(2, ("OCCP", "소프트웨어 엔지니어", "software engineer")),
        _turn(3),
    ))


def test_population_spec_names() -> None:
    assert PopulationSpec.parse("indep-30000").size == 30000
    with pytest.raises(ValueError):
        PopulationSpec.parse("indep-100")
    with pytest.raises(ValueError):
        PopulationSpec.parse("random-300")


def test_no_defense_reaches_one_candidate(context: Context) -> None:
    result = simulate(_dialogue(), Condition("C0", 2, 2, "synthpai-300"), context)
    assert [t.k_val for t in result.turns] == [3, 1, 1]
    assert result.violated and result.first_violation == 2
    assert all(not t.intervened for t in result.turns)


def test_cumulative_defense_keeps_floor_and_per_turn_does_not(context: Context) -> None:
    cumulative = simulate(_dialogue(), Condition("C1", 2, 2, "synthpai-300"), context)
    per_turn = simulate(_dialogue(), Condition("C1S", 2, 2, "synthpai-300"), context)
    assert not cumulative.violated and min(t.k_val for t in cumulative.turns) >= 2
    assert cumulative.turns[1].intervened and cumulative.turns[1].retained < 1
    assert per_turn.violated and not per_turn.turns[1].intervened   # 직업 하나만 보면 4명이라 통과시킨다


def test_suppress_only_never_generalizes(context: Context) -> None:
    result = simulate(_dialogue(), Condition("C1", 2, 2, "synthpai-300", max_generalization=0), context)
    assert sum(t.generalized for t in result.turns) == 0
    assert not result.violated


def test_static_generalization_lowers_retention(context: Context) -> None:
    result = simulate(_dialogue(), Condition("STATIC", 2, 2, "synthpai-300", static_level=1), context)
    assert all(t.retained < t.delta for t in result.turns if t.delta)
    assert result.turns[0].generalized == 1


def test_missed_observations_are_released(context: Context) -> None:
    missed = simulate(_dialogue(), Condition("C1", 2, 2, "synthpai-300", miss_rate=1.0), context)
    assert missed.violated and sum(t.missed for t in missed.turns) == 2


def test_plan_release_limit(context: Context) -> None:
    index = context.bank.index("synthpai-300")
    node = context.bank.parser.parse("LOC", "Zurich, Switzerland").node_id
    delta = [DeltaItem("o1", "LOC", node)]
    state = {"OCCP": context.bank.parser.parse("OCCP", "software engineer").node_id}
    limited = plan_release(index, state, delta, k_req=4, max_generalization=0)
    assert all(item.released_node in (None, node) for item in limited.items)
    assert plan_release(index, state, delta, k_req=4).items == plan_release(index, state, delta, k_req=4,
                                                                            max_generalization=None).items


def test_knee_and_bootstrap_are_deterministic(context: Context) -> None:
    assert stats.knee([(0, 100), (1, 95), (2, 30), (3, 20)]) == 1
    assert stats.knee([(0, 1), (1, 1)]) is None
    units = [simulate(_dialogue(), Condition("C0", 2, 2, "synthpai-300"), context)] * 3
    first = stats.rate_interval(units, resamples=200, seed=3)
    assert first == stats.rate_interval(units, resamples=200, seed=3) == (1.0, 1.0)


def test_runtime_packages_do_not_import_analysis() -> None:
    for package in ("orchestrator", "adapters", "attack", "core", "normalizer", "ontology", "qi_extractor",
                    "target_llm", "validation"):
        for path in (ROOT / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                         else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                assert not any(n == "analysis" or n.startswith("analysis.") for n in names), path
