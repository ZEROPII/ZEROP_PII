"""
2026-11-08 사용자 입장 최종 점검에서 고친 것 (ADR-0043).

- 후보 수: 원장(다른 대화) 값과 맞지 않는 이 대화의 새 값이 사건 묶음 보정에서 빠져, 이 대화만으로 후보 1명인 값을
  후보 4명으로 보고 그대로 낸 일 → OwnStateKC (이 대화 값 먼저, 이 대화 값만 센 수 · 거꾸로 센 수 가운데 작은 쪽).
- 답 글: '종료일에 도달하지 않았습니다' 같은 기록 말투, 값을 빼고 남은 '사례1 환자는 거주했습니다', 횟수 범위의 '이상 이상'.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from webdemo.backend import textguard as G
from webdemo.backend.engine import Session
from webdemo.backend.live import ANSWER_STYLE, ANSWER_STYLE_ID
from webdemo.backend.review import OwnStateKC, RuleDefender


class RepairKC:
    """값마다 가진 환자 집합으로 센다. 겹치는 환자가 없으면 앞의 값을 믿고 뒤의 값을 뺀다 (GroupRepairKC의 보정과 같은 방향)."""

    data = "data"

    def __init__(self, sets: dict[str, set[str]]) -> None:
        self.sets = sets
        self.calls: list[list[str]] = []

    def k(self, ds: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls.append([d["node_id"] for d in ds])
        alive: set[str] | None = None
        flags: list[str] = []
        for d in ds:
            s = self.sets[d["node_id"]]
            nxt = s if alive is None else alive & s
            if alive is not None and not nxt:
                flags.append(f"CONFLICT_DROPPED:{d['node_id']}")
                continue
            alive = nxt
        return dict(k=len(alive or ()), flags=flags)


def v(node: str, **kw: Any) -> dict[str, Any]:
    return dict(attribute="PERIOD", node_id=node, **kw)


PEOPLE = {f"p{i}" for i in range(1, 10)}


def test_ledger_values_no_longer_push_out_this_conversations_new_value():
    """원장 값과 맞지 않는 새 값이 보정에서 빠지면 후보 4명(고치기 전: 그대로 냄). 이 대화 값만 센 1명을 쓴다(가림)."""
    base = RepairKC({"NEW": {"p1"}, "OLD": {"p2", "p3", "p4", "p5"}})
    assert base.k([v("OLD", prior=True), v("NEW")])["k"] == 4          # 고치기 전: 새 값이 빠졌다
    kc = OwnStateKC(base)
    assert kc.k([v("OLD", prior=True), v("NEW")])["k"] == 1
    assert base.calls[1:] == [["OLD", "NEW"], ["NEW"]]                  # 원장 먼저(판정 전과 같은 차례) → 보정이 있어 이 대화 값만


def test_ledger_order_is_kept_without_repair():
    """보정이 없으면 한 번만 센다 (원장을 뒤에 붙이는 차례는 원장 묶음 보정을 매번 다시 해 열기가 52초까지 늘었다)."""
    base = RepairKC({"NEW": {"p1", "p2"}, "OLD": {"p1", "p2", "p3"}})
    assert OwnStateKC(base).k([v("OLD", prior=True), v("NEW")]) == dict(k=2, flags=[])
    assert base.calls == [["OLD", "NEW"]]


def test_this_conversation_alone_wins_when_smaller():
    class Stub:
        def k(self, ds: list[dict[str, Any]]) -> dict[str, Any]:
            ids = tuple(d["node_id"] for d in ds)
            return dict(k={("B", "A"): 6, ("A",): 2}[ids], flags=["REGROUPED:x"] if len(ids) > 1 else [])

    assert OwnStateKC(Stub()).k([v("B", prior=True), v("A")])["k"] == 2


def test_repaired_own_values_are_also_counted_newest_first():
    base = RepairKC({"A": {"p1", "p2", "p3", "p4", "p5"}, "B": {"p6"}})
    assert base.k([v("A"), v("B")])["k"] == 5                           # 보정이 B를 뺐다
    assert OwnStateKC(base).k([v("A"), v("B")])["k"] == 1               # 거꾸로 세면 A가 빠져 1명 → 작은 쪽


def test_without_ledger_or_repair_the_count_is_unchanged():
    base = RepairKC({"A": PEOPLE, "B": {"p1", "p2", "p3"}})
    kc = OwnStateKC(base)
    assert kc.k([v("A"), v("B")]) == dict(k=3, flags=[]) and len(base.calls) == 1
    assert kc.data == "data"                                            # 나머지 속성은 그대로 넘긴다


def test_rule_defender_wraps_the_count_once():
    base = RepairKC({"A": PEOPLE})
    inner = SimpleNamespace(kc=base)
    RuleDefender(inner, lambda ref: set())
    RuleDefender(inner, lambda ref: set())
    assert isinstance(inner.kc, OwnStateKC) and inner.kc.base is base


def test_k_global_takes_this_conversation_alone_after_repair():
    base = RepairKC({"NEW": {"p1"}, "OLD": {"p2", "p3", "p4", "p5"}})
    fake = SimpleNamespace(runs=dict(C1=SimpleNamespace(cases=dict(사례1=SimpleNamespace(committed=[v("NEW")])))),
                           prior=lambda ref: [v("OLD")], ctx=SimpleNamespace(kc=base, p_ref=99))
    assert Session.k_global(fake, "사례1") == 1
    empty = SimpleNamespace(runs=dict(C1=SimpleNamespace(cases={})), prior=lambda ref: [], ctx=SimpleNamespace(kc=base, p_ref=99))
    assert Session.k_global(empty, "사례1") == 99


def test_end_record_wording_reads_as_ongoing_care():
    cases = {
        "사례1의 metformin 500 MG Oral Tablet은 종료일에 도달하지 않았습니다.": "사례1의 metformin 500 MG Oral Tablet은 현재까지 계속 처방되고 있습니다.",
        "사례2의 처방은 아직 종료되지 않았습니다.": "사례2의 처방은 현재까지 이어지고 있습니다.",
        "사례3의 관리 계획은 종료되지 않았습니다.": "사례3의 관리 계획은 현재까지 계속 진행되고 있습니다.",
        "사례1의 진단은 종료 기록 없이 이어졌습니다.": "사례1의 진단은 현재까지 이어지고 있습니다.",
        "- 사례1 처방: lisinopril 10 MG Oral Tablet (종료 기록 없음)": "- 사례1 처방: lisinopril 10 MG Oral Tablet (현재까지 계속 처방 중)",
        "사례1 환자는 1998년 12월부터 처방되어 종료 기록이 없습니다.": "사례1 환자는 1998년 12월부터 현재까지 계속 처방되고 있습니다.",
    }
    for raw, want in cases.items():
        out, edits = G.natural_wording(raw)
        assert out == want, raw
        assert edits and all(e["kind"] == "wording" for e in edits)
        assert "종료" not in out and "도달" not in out and "복용" not in out


def test_gaps_left_by_removed_values_are_tidied():
    assert G.tidy_gaps("사례1 환자는 거주했습니다. 사례1 환자는 30~39세에 진단받았습니다.")[0] == (
        "사례1 환자의 거주 지역은 비공개입니다. 사례1 환자는 30~39세에 진단받았습니다.")
    assert G.tidy_gaps("사례1: 시작하여 3회 처방되었습니다.")[0] == "사례1: 3회 처방되었습니다."
    assert G.tidy_gaps("기록에 없음. 사례2는 관리 계획을 받았습니다.")[0] == "사례2는 관리 계획을 받았습니다."
    assert G.tidy_gaps("기록에 없음.")[0] == "기록에 없습니다."
    assert G.tidy_gaps("사례1 환자는 2010년 3월에 진단받았습니다.") == ("사례1 환자는 2010년 3월에 진단받았습니다.", [])
    out, edits = G.post_release("사례1 환자는 거주했습니다.", 5)
    assert out == "사례1 환자의 거주 지역은 비공개입니다." and [e["kind"] for e in edits] == ["gap"]


def test_count_ranges_keep_their_bound_words_once():
    assert G.coarsen_counts("사례1은 5회 이상 처방되었습니다.", 5)[0] == "사례1은 4회 이상 처방되었습니다."
    assert G.coarsen_counts("사례1은 10회 넘게 처방되었습니다.", 5)[0] == "사례1은 10회 이상 처방되었습니다."
    assert G.coarsen_counts("사례1은 7회 처방되었습니다.", 5)[0] == "사례1은 4~9회 처방되었습니다."
    assert G.coarsen_counts("사례1은 3회 이하 처방되었습니다.", 5) == ("사례1은 3회 이하 처방되었습니다.", [])
    assert G.coarsen_counts("사례1은 12회 이하 처방되었습니다.", 5) == ("사례1은 12회 이하 처방되었습니다.", [])
    for raw in ("5회 이상", "10회 넘게", "3회 이하"):
        assert "이상 이상" not in G.coarsen_counts(f"사례1은 {raw} 처방되었습니다.", 5)[0]


def test_answer_style_v2_names_the_wording_to_use():
    assert ANSWER_STYLE_ID.startswith("short-v2:")
    assert "현재까지 계속 처방되고 있습니다" in ANSWER_STYLE and "종료일에 도달하지 않았습니다" in ANSWER_STYLE
    assert "괄호로 덧붙이지 않습니다" in ANSWER_STYLE


def test_oracle_names_the_items_it_did_not_answer():
    """시연 모드(LLM 없음)는 질문마다 정해 둔 항목만 답한다. 답하지 않은 항목은 따로 물으라고 적는다 (진단은 세지 않음)."""
    from webdemo.backend import intent as I
    from webdemo.backend.clinic import oracle_left, oracle_left_text
    age = dict(release_plans=[dict(decisions=[dict(attribute="AGE")])])
    assert oracle_left(I.parse("사례1 환자는 몇 살 때 진단받았고 어디에 살았나요?"), age) == ["REGION"]
    assert oracle_left_text(["REGION"]) == "시연 모드는 질문마다 정해 둔 항목만 답합니다. 거주지는 따로 물어 주세요."
    assert oracle_left_text(["REGION", "SEX"]).endswith("거주지 · 성별은 따로 물어 주세요.")
    both = dict(release_plans=[dict(decisions=[dict(attribute="REGION"), dict(attribute="PERIOD")])])
    assert oracle_left(I.parse("사례1 환자의 거주 지역과 그 진료를 받은 시점을 알려 주세요."), both) == []
