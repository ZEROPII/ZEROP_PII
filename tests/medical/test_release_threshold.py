from medical.session import release_need


def test_release_needs_k_above_generalize_threshold():
    # 계획은 k <= g 이면 위험으로 보고 k > g 가 될 때까지 일반화한다 → 릴리스 후 k >= g+1 이어야 한다.
    assert release_need(5, 20) == 6


def test_release_at_k4_is_rejected_when_threshold_is_5():
    # 이전 구현은 need=min(s+1, k)=4 라서 k=4 릴리스가 통과했다. 지표(1 ≤ k < 5 위반)와 충돌.
    assert release_need(5, 20) > 4


def test_already_risky_case_only_must_not_worsen():
    assert release_need(5, 3) == 3
    assert release_need(5, 0) == 0
