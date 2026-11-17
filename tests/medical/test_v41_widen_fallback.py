"""[실험 v4.1] 넓히기 되돌리기: 넓힌 계획의 모든 시도가 막히면 넓히기 없는 계획으로 한 번 더 시도한다."""
from __future__ import annotations

from types import SimpleNamespace

from medical.session import ArmRun, Release, _empty_view


def _plan(ref, *pairs):
    return SimpleNamespace(ref=ref, decisions=[SimpleNamespace(action=a, to_node=n) for a, n in pairs])


def _rel(mode, tag):
    return Release(f"text-{tag}", _empty_view(), mode, [dict(ref="사례1", tag=tag)], [], [dict(mode="REWRITTEN", ok=mode != "REFUSAL", tag=tag)],
                   0.5 if mode != "REFUSAL" else 0.0, 2)


class _Run(ArmRun):
    pass


def _run(widen=("PERIOD",), kind=ArmRun, plans_widen=None, plans_plain=None, results=None):
    run = kind.__new__(kind)
    run.ctx = SimpleNamespace(defender=SimpleNamespace(widen_first=widen))
    calls = []

    def plan_all(view, no_widen=False):
        calls.append(("plan", no_widen, run.ctx.defender.widen_first))
        return plans_plain if no_widen else plans_widen

    def release_plans(query, raw, view, masks, plans):
        calls.append(("release", plans is plans_plain))
        return results[len([c for c in calls if c[0] == "release"]) - 1]

    run._plan_all, run._release_plans = plan_all, release_plans
    return run, calls


W = [_plan("사례1", ("generalize", "PERIOD_YEAR_2018"), ("allow", "DX_A"))]
P = [_plan("사례1", ("suppress", None), ("allow", "DX_A"))]


def test_refusal_with_widened_plan_retries_without_widening():
    run, calls = _run(plans_widen=W, plans_plain=P, results=[_rel("REWRITTEN", "p")])
    out = run._widen_fallback("q", "raw", None, [], W, _rel("REFUSAL", "w"))
    assert out.mode == "REWRITTEN" and out.text == "text-p"
    assert out.plans[0]["widen_fallback"] is True and out.extraction_tries == 4
    assert [a["phase"] for a in out.attempts] == ["widen", "no_widen"]
    assert [c for c in calls if c[0] == "release"] == [("release", True)]          # 넓히기 없는 계획으로 한 번


def test_no_retry_when_released_or_plans_are_the_same_or_no_widening():
    ok = _rel("REWRITTEN", "w")
    run, _ = _run(plans_widen=W, plans_plain=P, results=[])
    assert run._widen_fallback("q", "raw", None, [], W, ok) is ok                 # 통과했으면 그대로
    run, calls = _run(plans_widen=W, plans_plain=W, results=[])
    ref = _rel("REFUSAL", "w")
    assert run._widen_fallback("q", "raw", None, [], W, ref) is ref and not [c for c in calls if c[0] == "release"]
    run, _ = _run(widen=(), plans_widen=W, plans_plain=P, results=[])
    assert run._widen_fallback("q", "raw", None, [], W, ref) is ref               # 넓히기를 안 켰으면 그대로
    run, _ = _run(kind=_Run, plans_widen=W, plans_plain=P, results=[])
    assert run._widen_fallback("q", "raw", None, [], W, ref) is ref               # 제품(하위 클래스)은 쓰지 않는다


def test_plan_all_turns_widening_off_only_while_planning():
    from medical.session import ArmRun as AR
    run = AR.__new__(AR)
    seen = []
    d = SimpleNamespace(widen_first=("PERIOD", "AGE"))
    d.plan_case = lambda ref, basis, new, src: seen.append(d.widen_first) or ref
    run.ctx = SimpleNamespace(defender=d)
    run.arm, run.cases = "C1S", {}
    view = SimpleNamespace(case_refs=["사례1"], disclosures={"사례1": []}, sources={"사례1": []})
    assert run._plan_all(view, no_widen=True) == ["사례1"] and seen == [()]
    assert d.widen_first == ("PERIOD", "AGE")
    run._plan_all(view)
    assert seen[-1] == ("PERIOD", "AGE")
