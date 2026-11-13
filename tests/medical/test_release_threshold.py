from medical.session import release_need

K_REQ = 5


def test_release_must_reach_k_req():
    # 위반 판정은 1 <= k < k_req. k_req 이상이면 위반이 아니므로 k=5 릴리스는 허용.
    assert release_need(K_REQ, 20) == 5


def test_release_at_k4_is_rejected():
    # 계획기 fallback(k > 3)이 만든 k=4 릴리스는 지표에서 위반이므로 검증이 거절해야 한다.
    assert release_need(K_REQ, 20) > 4


def test_already_risky_case_only_must_not_worsen():
    assert release_need(K_REQ, 3) == 3
    assert release_need(K_REQ, 0) == 0
