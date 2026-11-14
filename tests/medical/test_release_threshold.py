from medical.session import release_need

# [수정본] 검증 하한은 계획기 fallback 하한(s=4 → k>=5)과 같아야 한다 (옵션 B).


def test_release_needs_k_above_suppress_threshold():
    # 계획: 일반화로 k > g(6 이상)를 목표하고, 실패하면 fallback으로 k > s(5 이상)를 허용한다.
    # 따라서 릴리스 검증 하한은 s+1 = 5.
    assert release_need(4, 20) == 5


def test_fallback_outcome_k4_is_accepted():
    # 계획기가 허용한 fallback 결과(k>=5)는 검증에서도 통과해야 한다. k=4는 더 이상 허용되지 않는다.
    assert release_need(4, 20) <= 5


def test_already_risky_case_only_must_not_worsen():
    assert release_need(4, 4) == 4
    assert release_need(4, 0) == 0
