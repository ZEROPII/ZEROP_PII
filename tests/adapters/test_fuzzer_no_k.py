# FuzzerConfig.use_k_feedback 테스트 — No-K 갈래에서 k가 다음 질문에 닿지 않는지, 기본은 기존 동작 그대로인지
# Mutation LLM만 가짜로 바꾸고 한재이 파트 함수는 실제 것을 쓴다.

from __future__ import annotations

import argparse

import pytest

from adapters.fuzzer_adapter import MUTATION_STRATEGIES, FuzzerConfig
from attack.selector import AttackStateView
from fuzzer.fuzzer_mutation import generate_next_mutation
from orchestrator.__main__ import NO_K_MODE, K_MODE, fuzzer_config_from_args
from tests.adapters.test_fuzzer_adapter import EMPTY, make_adapter, registry, reply  # noqa: F401  (fixture)

# k 변화 시나리오: K 모드라면 전략·새 Seed 시작이 모두 달라지는 값들
K_SCRIPTS = {
    "improved": [(300_000, 100_000), (100_000, 90_000), (90_000, 2)],
    "zero_match": [(300_000, 0), (0, 0), (0, 0)],
    "unchanged": [(300_000, 300_000), (300_000, 300_000), (300_000, 300_000)],
    "worse": [(100, 300), (300, 900), (900, 2_000)],
}


def run_session(registry, script, **config):
    adapter, client = make_adapter(registry, *[reply(f"질문 {n}") for n in range(1, 5)], **config)
    steps = [adapter.next_query(EMPTY)]
    for k_before, k_after in script:
        adapter.observe(k_before, k_after)
        steps.append(adapter.next_query(EMPTY))
    return steps, client


def test_default_config_keeps_k_feedback():
    config = FuzzerConfig()
    assert config.use_k_feedback is True
    assert config.describes["use_k_feedback"] is True and config.describes["no_k_strategy"] is None


@pytest.mark.parametrize("name", list(K_SCRIPTS))
def test_explicit_k_mode_matches_default(registry, name):
    default, default_client = run_session(registry, K_SCRIPTS[name])
    explicit, explicit_client = run_session(registry, K_SCRIPTS[name], use_k_feedback=True)
    assert [s.to_log_dict() for s in default] == [s.to_log_dict() for s in explicit]
    assert default_client.calls == explicit_client.calls


def test_no_k_questions_do_not_depend_on_k(registry):
    """k가 어떻게 변해도 No-K는 같은 Seed·같은 전략·같은 Mutation LLM 입력을 낸다."""
    runs = {name: run_session(registry, script, use_k_feedback=False) for name, script in K_SCRIPTS.items()}
    logs = {name: [s.to_log_dict() for s in steps] for name, (steps, _) in runs.items()}
    calls = {name: client.calls for name, (_, client) in runs.items()}
    first = next(iter(K_SCRIPTS))
    assert all(log == logs[first] for log in logs.values())
    assert all(call == calls[first] for call in calls.values())


def test_k_mode_questions_do_depend_on_k(registry):
    """대조: 같은 시나리오들에서 K 모드는 전략·새 Seed 시작이 달라진다 (위 테스트가 의미 있는 비교인지 확인)."""
    paths = {name: [(s.reset_reason, s.strategy) for s in run_session(registry, script)[0]]
             for name, script in K_SCRIPTS.items()}
    assert len({tuple(path) for path in paths.values()}) > 1
    assert paths["zero_match"][1] == ("ABORT", None)
    assert paths["unchanged"][2] == ("STALE", None)          # unchanged 2번 → 새 Seed


def test_no_k_uses_fixed_strategy_and_same_mutation_code(registry):
    steps, client = run_session(registry, K_SCRIPTS["zero_match"], use_k_feedback=False)
    assert steps[0].reset_reason == "FIRST_TURN"
    for previous, step in zip(steps, steps[1:]):
        assert step.reset_reason is None and step.strategy == "diversify" and step.feedback_status is None
        assert step.seed_id == steps[0].seed_id
        assert step.mutation_instruction == generate_next_mutation(previous.query, "diversify")
    assert [call["user_prompt"] for call in client.calls[1:]] == [s.mutation_instruction for s in steps[1:]]


def test_no_k_never_sends_k_to_mutation_llm(registry):
    _, client = run_session(registry, [(123_457, 98_765)] * 3, use_k_feedback=False)
    text = " ".join(call["user_prompt"] + call["system_prompt"] for call in client.calls)
    assert "123457" not in text and "98765" not in text


def test_no_k_observe_still_reports_feedback_for_the_log(registry):
    adapter, _ = make_adapter(registry, reply("질문"), reply("질문 2"), use_k_feedback=False)
    adapter.next_query(EMPTY)
    assert adapter.observe(300_000, 0).status == "invalid"          # 기록용 판정은 그대로
    assert adapter.next_query(EMPTY).reset_reason is None            # 그러나 ABORT로 이어지지 않는다


def test_no_k_still_restarts_when_seed_is_no_longer_applicable(registry):
    """공개 State로 정해지는 새 Seed 시작(SEED_NOT_APPLICABLE)은 k와 무관하므로 No-K에서도 그대로다."""
    adapter, _ = make_adapter(registry, reply("질문"), reply("질문 2"), use_k_feedback=False)
    first = adapter.next_query(EMPTY)                                 # O1 Seed
    adapter.observe(300_000, 300_000)
    disclosed = AttackStateView({first.target_qi: "Switzerland" if first.target_qi == "LOC" else "x"}, 1)
    assert adapter.next_query(disclosed).reset_reason == "SEED_NOT_APPLICABLE"


def test_no_k_ignores_missing_observe(registry):
    adapter, _ = make_adapter(registry, reply("q1"), reply("q2"), use_k_feedback=False)
    adapter.next_query(EMPTY)
    assert adapter.next_query(AttackStateView({}, 1)).reset_reason is None


def test_no_k_strategy_must_be_a_mutation_strategy():
    assert set(MUTATION_STRATEGIES) == {"intensify", "refine", "diversify", "revert", "exploit"}
    with pytest.raises(ValueError):
        FuzzerConfig(use_k_feedback=False, no_k_strategy="abort")


@pytest.mark.parametrize("strategy", ["refine", "exploit"])
def test_no_k_strategy_can_be_chosen(registry, strategy):
    steps, _ = run_session(registry, K_SCRIPTS["improved"], use_k_feedback=False, no_k_strategy=strategy)
    assert {s.strategy for s in steps[1:]} == {strategy}


# ── 명령행 ────────────────────────────────────────────────

def args_of(**values):
    return argparse.Namespace(**{"plain_mutation": False, "feedback_mode": K_MODE, "no_k_strategy": "diversify",
                                 **values})


def test_cli_default_keeps_previous_config():
    assert fuzzer_config_from_args(args_of()) is None
    plain = fuzzer_config_from_args(args_of(plain_mutation=True))
    assert plain.use_k_feedback is True and plain.balance_qis is False


def test_cli_no_k_mode():
    config = fuzzer_config_from_args(args_of(feedback_mode=NO_K_MODE, no_k_strategy="refine"))
    assert config.use_k_feedback is False and config.no_k_strategy == "refine"
    assert config.target_scope_note == FuzzerConfig().target_scope_note      # 다른 설정은 기본값 그대로
    plain = fuzzer_config_from_args(args_of(feedback_mode=NO_K_MODE, plain_mutation=True))
    assert plain.use_k_feedback is False and plain.balance_qis is False
