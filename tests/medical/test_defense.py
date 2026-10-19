# 의료 Defender: risk_defender 정책(5·3)을 kcalc 사건 단위 k로 판정하는지
from __future__ import annotations

import collections

import pytest

from medical.defense import ALLOW, GENERALIZE, SUPPRESS, SUPPRESSED_MARK, MedicalDefender, apply_changes_deterministic, format_changes
from tests.medical.conftest import EXAMPLE_PID

D = lambda a, n, g=None: {"attribute": a, "node_id": n, "event_group": g}
SRC = lambda raw: {"raw_value": raw, "evidence_spans": [raw]}


@pytest.fixture(scope="module")
def defender(kc, data):
    return MedicalDefender(kc, data, generalize_threshold=5, suppress_threshold=3)


def test_allow_when_projected_k_above_generalize_threshold(defender):
    p = defender.plan_case("사례1", [], [D("SEX", "SEX_FEMALE")], [SRC("여성")])
    assert not p.risky and p.k_projected > 5
    assert [d.action for d in p.decisions] == [ALLOW]
    assert p.decisions[0].utility == 1.0


def test_rare_city_is_suppressed_without_generalization(defender, kc, data):
    """도시 하나만으로 k ≤ 3이면 일반화 없이 바로 억제 (risk_defender suppress_threshold 규칙)."""
    by_city = collections.Counter(e["region_node"] for p, evs in data.by_pat.items() for e in evs[:1])
    city = next(c for c, n in by_city.items() if n == 1)
    p = defender.plan_case("사례1", [], [D("REGION", city)], [SRC("어느 도시")])
    assert p.risky and p.decisions[0].action == SUPPRESS and p.decisions[0].k_raw <= 3
    assert p.decisions[0].utility == 0.0 and p.decisions[0].to_node is None


def test_same_event_age_is_generalized_up_the_chain(defender, kc, data):
    """'당뇨병 진단 당시 60세'처럼 사건 단위로 좁혀지면 그 사건의 나이만 위로 넓힌다."""
    found = None
    for pid, evs in data.by_pat.items():
        for e in evs:
            if e["event_type"] == "CONDITION" and e["age_node"]:
                base = [D("DX", e["code_node"], "e")]
                k_raw = kc.k(base + [D("AGE", e["age_node"], "e")])["k"]
                k_dx = kc.k(base)["k"]
                if 3 < k_raw <= 5 and k_dx > 5:
                    found = (base, e["age_node"])
                    break
        if found:
            break
    assert found, "예시 사건을 찾지 못함"
    base, age = found
    p = defender.plan_case("사례1", base, [D("AGE", age, "e")], [SRC("나이")])
    d = p.decisions[0]
    assert p.risky and d.action == GENERALIZE
    assert d.to_node in data.anc(age)[1:] and not data.is_root(d.to_node)
    assert kc.k(base + [D("AGE", d.to_node, "e")])["k"] > 5
    assert 0 < d.utility < 1 and d.utility == round(1 - d.steps / d.max_steps, 4)


def test_c1s_basis_is_empty_and_ignores_history(defender, data):
    """C1S(빈 State)는 앞선 공개를 보지 않으므로 같은 새 공개를 허용할 수 있다. C1은 누적 State로 막는다."""
    e0 = data.by_pat[EXAMPLE_PID][0]
    history = [D("REGION", e0["region_node"])]
    new = [D("SEX", e0["sex_node"])]
    c1 = defender.plan_case("사례1", history, new, [SRC("여성")])
    c1s = defender.plan_case("사례1", [], new, [SRC("여성")])
    assert c1s.decisions[0].action == ALLOW
    assert c1.k_projected <= c1s.k_projected


def test_zero_projected_k_is_treated_as_risky(defender):
    p = defender.plan_case("사례1", [], [D("SEX", "SEX_MALE"), D("SEX", "SEX_FEMALE")], [SRC("남성"), SRC("여성")])
    # 모순값은 kcalc가 충돌로 격리하므로 k가 0이 되지 않는다 (C08). 위험 판정은 k > 5라 허용.
    assert p.k_projected > 5 and not p.risky


def test_change_lines_and_deterministic_rewrite(defender, data):
    by_city = collections.Counter(evs[0]["region_node"] for evs in data.by_pat.values())
    city = next(c for c, n in by_city.items() if n == 1)
    label = data.N[city]["canonical_label"]
    plan = defender.plan_case("사례1", [], [D("REGION", city)], [SRC(label)])
    ch = defender.change_lines([plan])
    assert ch and ch[0]["action"] == SUPPRESS
    text = f"사례1 환자는 {label}에 거주했고 당뇨병이 있었습니다."
    out = apply_changes_deterministic(text, ch)
    assert label not in out and SUPPRESSED_MARK in out and "당뇨병" in out
    assert "사례1" in format_changes(ch) and "빼기" in format_changes(ch)


def test_thresholds_must_be_ordered(kc, data):
    with pytest.raises(ValueError):
        MedicalDefender(kc, data, generalize_threshold=3, suppress_threshold=5)
