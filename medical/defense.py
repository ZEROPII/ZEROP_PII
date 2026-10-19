# 의료 Defender: risk_defender(이유진) 판정 정책 + kcalc(사건 단위 k)
#
# 판정 정책은 risk_defender/defender.py(2026-10-14 main)의 defend_candidate_qis·_find_safe_generalization과 같다.
#   1) 이번 답변의 새 공개를 모두 넣은 projected k > generalize_threshold(5)  → 그대로 허용 (allow)
#      (k = 0도 위험으로 본다. risk_defender evaluate_projected_risk와 같은 판정)
#   2) 위험하면 공개 하나씩 차례로:
#      - 원래 값으로 넣었을 때 k <= suppress_threshold(3)            → 억제 (일반화 시도 안 함)
#      - 아니면 [원래 값, 부모, 조부모, …] 중 처음으로 k > 5가 되는 값 → 일반화 (원래 값이면 허용)
#      - 5를 넘는 값이 없으면 처음으로 k > 3이 되는 값               → 그 값으로 일반화
#      - 그것도 없으면                                              → 억제
#      앞에서 허용·일반화한 값은 다음 공개를 판단할 때 State에 들어간 것으로 본다.
# 바뀐 점은 k를 세는 방법뿐이다: 환자 프로필 대조(risk_defender.calculate_k) 대신 kcalc 사건 단위 계산.
#   같은 사건 묶음의 진단·나이·날짜는 한 사건이 함께 만족해야 하고, 일반화도 그 사건의 값만 넓힌다.
# 루트(ANY)까지 올라간 일반화는 제약이 없는 값이라 '말하지 않음'과 같다 → 억제로 기록한다 (설계 §4.21, §6.18).
#
# 사례(과거 환자)가 여러 명이면 사례마다 따로 판정한다. 대상 AI가 꺼낸 모든 사례가 보호 대상이다.
#   C1  : 그 사례의 누적 State(앞선 공개)를 기준으로 판정
#   C1S : 매 턴 빈 State에서 판정 (누적 State의 기여를 보기 위한 대조군). 실제 State 기록·평가는 C1과 같다.

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from medical.bundle.kcalc import KCalc
from medical.data import MedicalData

ALLOW, GENERALIZE, SUPPRESS = "allow", "generalize", "suppress"
SUPPRESSED_MARK = "(비공개)"


@dataclass
class Decision:
    disclosure: dict[str, Any]        # kcalc 입력 (원래 값)
    source: dict[str, Any]            # 원 Observation (raw_value·evidence_spans)
    action: str
    to_node: str | None               # allow면 원래 노드, generalize면 바꾼 노드, suppress면 None
    k_raw: int                        # 이 공개를 원래 값으로 넣었을 때의 k
    steps: int = 0                    # 일반화 단계 수
    max_steps: int = 0                # 원래 노드에서 루트까지 단계 수

    @property
    def utility(self) -> float:
        """공개 QI 유지율: 그대로 1, 일반화 1 − 단계/최대 단계, 억제 0 (SynthPAI 논문 지표와 같은 정의)."""
        if self.action == ALLOW:
            return 1.0
        if self.action == SUPPRESS or not self.max_steps:
            return 0.0
        return round(1.0 - self.steps / self.max_steps, 4)

    def as_dict(self) -> dict[str, Any]:
        return dict(attribute=self.disclosure["attribute"], node_id=self.disclosure["node_id"], event_group=self.disclosure["event_group"],
                    raw_value=self.source.get("raw_value"), action=self.action, to_node=self.to_node, k_raw=self.k_raw,
                    steps=self.steps, max_steps=self.max_steps, utility=self.utility)


@dataclass
class CasePlan:
    ref: str
    k_before: int
    k_projected: int
    risky: bool
    decisions: list[Decision] = field(default_factory=list)
    k_final: int | None = None

    @property
    def changes(self) -> list[Decision]:
        return [d for d in self.decisions if d.action != ALLOW]

    def as_dict(self) -> dict[str, Any]:
        return dict(ref=self.ref, k_before=self.k_before, k_projected=self.k_projected, risky=self.risky, k_final=self.k_final,
                    decisions=[d.as_dict() for d in self.decisions])


class MedicalDefender:
    def __init__(self, kc: KCalc, data: MedicalData, *, generalize_threshold: int = 5, suppress_threshold: int = 3) -> None:
        if suppress_threshold > generalize_threshold:
            raise ValueError("suppress_threshold는 generalize_threshold 이하여야 합니다.")
        self.kc, self.data = kc, data
        self.g, self.s = generalize_threshold, suppress_threshold

    def risky(self, k: int) -> bool:
        return k <= self.g      # k = 0 포함 (risk_defender와 같은 판정)

    def plan_case(self, ref: str, basis: list[dict[str, Any]], new: list[dict[str, Any]], sources: list[dict[str, Any]]) -> CasePlan:
        """
        input : basis (판정 기준 State: C1은 그 사례의 누적 공개, C1S는 빈 목록), new (이번 답변의 공개), sources (new와 같은 순서의 Observation)
        output: CasePlan (공개마다 allow / generalize / suppress)
        """
        k = lambda ds: self.kc.k(ds)["k"]
        k_before = k(basis) if basis else len(self.kc.by_pat)
        k_proj = k(basis + new) if new else k_before
        plan = CasePlan(ref, k_before, k_proj, risky=bool(new) and self.risky(k_proj))
        if not plan.risky:
            plan.decisions = [Decision(d, s, ALLOW, d["node_id"], k_proj, 0, self.data.depth(d["node_id"])) for d, s in zip(new, sources)]
            plan.k_final = k_proj
            return plan
        working = list(basis)
        for d, src in zip(new, sources):
            node = d["node_id"]
            max_steps = self.data.depth(node)
            k_raw = k(working + [d])
            chosen: str | None = None
            if k_raw > self.s:
                chain = self.data.anc(node)                 # [원래 값, 부모, …, 루트]
                for cand in chain:
                    if k(working + [dict(d, node_id=cand)]) > self.g:
                        chosen = cand
                        break
                if chosen is None:
                    for cand in chain:
                        if k(working + [dict(d, node_id=cand)]) > self.s:
                            chosen = cand
                            break
            if chosen is None or self.data.is_root(chosen):
                plan.decisions.append(Decision(d, src, SUPPRESS, None, k_raw, max_steps, max_steps))
                continue
            steps = chain.index(chosen)
            action = ALLOW if steps == 0 else GENERALIZE
            plan.decisions.append(Decision(d, src, action, chosen, k_raw, steps, max_steps))
            working.append(dict(d, node_id=chosen))
        plan.k_final = k(working) if working else len(self.kc.by_pat)
        return plan

    def change_lines(self, plans: list[CasePlan]) -> list[dict[str, Any]]:
        """재작성기에 넘길 변경 목록 (사례·원래 표현·근거 문장·바꿀 표현). 정답은 들어가지 않는다."""
        out = []
        for p in plans:
            for d in p.changes:
                out.append(dict(case_ref=p.ref, attribute=d.disclosure["attribute"], raw_value=str(d.source.get("raw_value", "")),
                                evidence_spans=list(d.source.get("evidence_spans") or []), action=d.action,
                                to_label=self.data.label(d.to_node) if d.to_node else None))
        return out


def format_changes(changes: list[dict[str, Any]]) -> str:
    lines = []
    for i, c in enumerate(changes, 1):
        where = f"{c['case_ref']}의 {c['attribute']} '{c['raw_value']}'"
        if c["action"] == GENERALIZE:
            lines.append(f"{i}. {where} → 넓게: '{c['to_label']}'")
        else:
            lines.append(f"{i}. {where} → 빼기")
    return "\n".join(lines)


def apply_changes_deterministic(response: str, changes: list[dict[str, Any]]) -> str:
    """
    LLM 재작성이 검사를 통과하지 못할 때의 대체: 원래 표현을 넓은 표현 또는 '(비공개)'로 글자 그대로 바꾼다.
    원래 표현이 답변에 없으면 근거 문장(evidence span)을 통째로 바꾼다.
    """
    out = response
    for c in sorted(changes, key=lambda c: -len(c["raw_value"])):
        rep = c["to_label"] if c["action"] == GENERALIZE else SUPPRESSED_MARK
        if c["raw_value"] and c["raw_value"] in out:
            out = out.replace(c["raw_value"], rep)
            continue
        for sp in sorted(c["evidence_spans"], key=len, reverse=True):
            if sp and sp in out:
                out = out.replace(sp, rep)
    return re.sub(r"(\(비공개\)[\s,]*){2,}", SUPPRESSED_MARK + " ", out)
