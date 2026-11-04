# 보안 담당자의 검토를 대화에 반영한다 (ADR-0022).
#
#   규칙 (rules)    : "이 대화에서 사례N의 이 단서 종류는 늘 가림". 의료진 화면 갈래(C1)의 공개 계획과 다시 확인 단계에 같이 건다.
#                     넓히면 기준을 넘는 값이라도 가린다. 고친 답에 그 단서가 남으면 확인을 통과하지 못한다 (재작성 · 규칙 치환 · 거절 순).
#                     비교 갈래(C0 방어 없음 · C1S 턴별 방어)는 연구용 대조군이라 규칙을 걸지 않는다.
#   공개 승인 (approve) : 의료진의 세부 정보 요청에 보안 담당자가 사유를 적고 가린 값을 골라 공개한다.
#                     그 값은 그 의료진의 그 대화에만 나가고, 누적 State(C1)에 더해져 이후 판정에 들어간다
#                     (후보가 기준 아래로 내려가면 그 사례의 다음 답은 더 막힌다).
#   후보가 줄어든 과정 (narrowing) : 사례마다 공개된 단서를 쌓인 순서대로 하나씩 더하며 센 후보 수 (보안 담당자 화면).
#   고친 답 다시 확인 보강 : 연구 모듈의 확인(_verify)은 고친 답을 다시 뽑아 찾은 사례만 센다. 고친 답이 '사례N' 표기를
#                     떨어뜨리면 사례를 못 찾아 확인이 그냥 통과한다. 그래서 (1) 가리거나 넓히기로 한 원래 값이 글자 그대로
#                     남아 있거나 (2) 바꿀 값이 있었는데 사례를 하나도 못 찾고 그 사례 표기도 글에 없으면 통과시키지 않는다
#                     (의료진 화면 갈래 C1 · C1S).
#
# medical/ 연구 모듈은 바꾸지 않는다. Defender는 감싸고(RuleDefender), 갈래는 상속해(RuledArmRun) 확인 단계만 덧붙인다.

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Callable

from medical.defense import ALLOW, SUPPRESS, Decision
from medical.session import ArmRun


class RuleDefender:
    """MedicalDefender를 감싼다. blocked(ref)가 주는 단서 종류는 그 사례에서 늘 가림(SUPPRESS)으로 정한다."""

    def __init__(self, inner: Any, blocked: Callable[[str], set[str]]) -> None:
        self.inner = inner
        self.blocked = blocked
        self.last_plans: list[Any] = []                 # 이번 공개의 계획과 바꿀 값 (RuledArmRun._verify가 다시 확인에 씀)
        self.last_changes: list[dict[str, Any]] = []

    def __getattr__(self, name: str) -> Any:          # kc · data · g · s · risky …
        return getattr(self.inner, name)

    def change_lines(self, plans: list[Any]) -> list[dict[str, Any]]:
        changes = self.inner.change_lines(plans)
        self.last_plans, self.last_changes = list(plans), list(changes)
        return changes

    def plan_case(self, ref: str, basis: list[dict[str, Any]], new: list[dict[str, Any]], sources: list[dict[str, Any]]):
        blocked = self.blocked(ref)
        if not blocked or not any(d["attribute"] in blocked for d in new):
            return self.inner.plan_case(ref, basis, new, sources)
        keep = [i for i, d in enumerate(new) if d["attribute"] not in blocked]
        plan = self.inner.plan_case(ref, basis, [new[i] for i in keep], [sources[i] for i in keep])
        kept = dict(zip(keep, plan.decisions))
        k = lambda ds: self.inner.kc.k(ds)["k"]
        out: list[Decision] = []
        for i, (d, src) in enumerate(zip(new, sources)):
            if i in kept:
                out.append(kept[i])
                continue
            depth = self.inner.data.depth(d["node_id"])
            out.append(Decision(d, src, SUPPRESS, None, k(list(basis) + [d]), depth, depth))
        plan.decisions = out
        plan.risky = True
        return plan


class RuledArmRun(ArmRun):
    """보안 담당자 규칙을 지키는 갈래. rules()는 [(사례 표기, 단서 종류)]. 규칙이 없으면 ArmRun과 똑같다."""

    def __init__(self, ctx: Any, prefix: Any, arm: str, log: Callable[[dict[str, Any]], None],
                 rules: Callable[[], list[tuple[str, str]]]) -> None:
        self.rules = rules
        super().__init__(ctx, prefix, arm, log)

    def blocked(self, ref: str) -> set[str]:
        return {a for r, a in self.rules() if r == ref}

    @property
    def ctx(self) -> Any:
        return self._ctx

    @ctx.setter
    def ctx(self, c: Any) -> None:
        # 문맥을 바꿔 끼울 때(실제 LLM 문맥 등)마다 Defender를 규칙으로 감싼다
        self._ctx = c if isinstance(c.defender, RuleDefender) else replace(c, defender=RuleDefender(c.defender, self.blocked))

    def _verify(self, query: str, text: str):
        ok, v, checks, n = super()._verify(query, text)
        if not ok or v is None:
            return ok, v, checks, n
        for ref in v.case_refs:
            left = sorted({d["attribute"] for d in v.disclosures[ref]} & self.blocked(ref))
            if left:
                checks.append(dict(ref=ref, rule=left, ok=False))
                ok = False
        d = self._ctx.defender
        changes = getattr(d, "last_changes", None) or []
        if changes:
            # 그대로 내도 되는 값과 같은 글자는 빼고 본다 (다른 사례에 같은 약 이름이 허용된 경우)
            allowed = {str(x.source.get("raw_value") or "") for p in getattr(d, "last_plans", []) for x in p.decisions if x.action == ALLOW}
            left = [c for c in changes if c["raw_value"] and c["raw_value"] not in allowed and _appears(c["raw_value"], text)]
            for c in left:
                checks.append(dict(ref=c["case_ref"], reason="RAW_VALUE_LEFT", attribute=c["attribute"], ok=False))
                ok = False
            # 다시 뽑아도 사례를 하나도 못 찾았고, 바꿀 값이 있던 사례의 'N번 사례' 표기도 글에 없으면 단서가 어느 사례 것인지 셀 수 없다
            if not v.case_refs and not any(_has_label(c["case_ref"], text) for c in changes):
                checks.append(dict(ref=None, reason="NO_CASE_FOUND", ok=False))
                ok = False
        return ok, v, checks, n


def _appears(value: str, text: str) -> bool:
    """값이 글자 그대로 남았는지. 숫자 · 영문이 이어 붙은 경우(15세 속의 5세, 2004-06-160)는 같은 값으로 보지 않는다."""
    return re.search(rf"(?<![0-9A-Za-z]){re.escape(value)}(?![0-9A-Za-z])", text) is not None


def _has_label(ref: str | None, text: str) -> bool:
    """'사례1' 표기가 글에 있는지 ('사례 1'도 같게, '사례10'은 다르게 본다)."""
    m = re.fullmatch(r"사례\s*(\d+)", ref or "")
    return m is not None and re.search(rf"사례\s*0*{int(m.group(1))}(?!\d)", text) is not None


def hidden_items(logs: list[dict[str, Any]], approvals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """의료진 화면 갈래 기록에서 가리거나 넓힌 값 (값 자체는 넣지 않는다). 승인해 공개한 것은 released."""
    released = {(x["turn"], x["case"], x["index"]) for ap in approvals for x in ap["items"]}
    out = []
    for rec in logs:
        if rec.get("turn") is None:
            continue
        refusal = rec["release_mode"].startswith("REFUSAL")
        for p in rec.get("release_plans") or []:
            for i, d in enumerate(p["decisions"]):
                action = SUPPRESS if refusal else d["action"]
                if action == ALLOW:
                    continue
                out.append(dict(id=f"{rec['turn']}:{p['ref']}:{i}", turn=rec["turn"], case=p["ref"], index=i, attribute=d["attribute"],
                                action=action, kIfRaw=d.get("k_raw"), released=(rec["turn"], p["ref"], i) in released))
    return out


def decision_of(logs: list[dict[str, Any]], turn: int, ref: str, index: int) -> dict[str, Any]:
    rec = next(r for r in logs if r.get("turn") == turn)
    plan = next(p for p in rec["release_plans"] if p["ref"] == ref)
    return plan["decisions"][index]
