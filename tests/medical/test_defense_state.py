# 누적 상태 판정: 이미 위험 상태(k ≤ generalize_threshold)인 기준에 새 공개가 없어도 위험으로 본다
from __future__ import annotations

import pytest

from medical.defense import MedicalDefender


@pytest.fixture(scope="module")
def defender(kc, data):
    return MedicalDefender(kc, data, generalize_threshold=5, suppress_threshold=3)


def _risky_basis(kc, data):
    for pid, evs in data.by_pat.items():
        for e in evs:
            if e["event_type"] == "CONDITION" and e["code_node"]:
                base = [{"attribute": "DX", "node_id": e["code_node"], "event_group": "e"}]
                k = kc.k(base)["k"]
                if 1 <= k <= 5:
                    return base
    raise AssertionError("위험 상태 기준을 찾지 못함")


def test_state_already_risky_is_risky_even_without_new_disclosure(defender, kc, data):
    base = _risky_basis(kc, data)
    assert kc.k(base)["k"] <= 5
    p = defender.plan_case("사례1", base, [], [])
    assert p.risky, "이미 k ≤ 5인 누적 상태는 새 단서가 없어도 위험으로 판정해야 한다"
