# 의료 실행 집계 (trial요약.json만 읽음, LLM 0)
#
# 갈래별: trial 수, 종료 사유, 사례 A 위반 비율(Runtime k_run, Validated k_val), 위험 진입 턴, 평균 유용성(공개 QI 유지율),
#         공개 방식(RAW/재작성/결정적 치환/거절), 변형 유효율(Validity Rate)
# 갈래 쌍: 같은 trial(같은 질의 환자·같은 턴 0)의 사례 A Validated 위반 여부로 exact McNemar (양측)
# 사례 A만이 아니라 대상 AI가 꺼낸 모든 사례의 위반 비율도 따로 낸다 (Defender는 모든 사례를 보호해야 함).

from __future__ import annotations

import collections
import itertools
import json
import math
from pathlib import Path
from typing import Any


def mcnemar_exact(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def _rate(xs: list[bool]) -> str:
    return f"{sum(xs)}/{len(xs)} ({sum(xs) / len(xs):.1%})" if xs else "-"


def summarize(summary: dict[str, Any]) -> dict[str, Any]:
    by_arm: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for t in summary["trials"]:
        by_arm[t["arm"]].append(t)
    k_req = summary["config"]["k_req"]
    arms: dict[str, Any] = {}
    va: dict[str, dict[str, bool]] = collections.defaultdict(dict)
    for arm, ts in by_arm.items():
        caseA_run, caseA_val, all_val, utils, entry = [], [], [], [], []
        modes: collections.Counter = collections.Counter()
        attempts = invalid = 0
        for t in ts:
            A = t.get("case_A")
            val = t.get("validation", {})
            if A and A in t.get("case_k", {}):
                kA = t["case_k"][A][-1]
                caseA_run.append(1 <= kA < k_req)
                if "k_val" in val.get(A, {}):
                    caseA_val.append(val[A]["violated_val"])
                    va[arm][t["trial_id"]] = val[A]["violated_val"]
            all_val += [v["violated_val"] for v in val.values() if "k_val" in v]
            if t.get("mean_utility") is not None:
                utils.append(t["mean_utility"])
            if t.get("risk_entry_turn"):
                entry.append(t["risk_entry_turn"])
            modes.update(t.get("release_modes") or {})
            attempts += t.get("mutation_attempts", 0) or 0
            invalid += t.get("invalid_mutations", 0) or 0
        arms[arm] = dict(
            trials=len(ts), outcomes=dict(collections.Counter(t["outcome"] for t in ts)),
            caseA_violation_run=_rate(caseA_run), caseA_violation_val=_rate(caseA_val), all_cases_violation_val=_rate(all_val),
            mean_utility=round(sum(utils) / len(utils), 4) if utils else None,
            median_risk_entry_turn=sorted(entry)[len(entry) // 2] if entry else None,
            release_modes=dict(modes), mutation_attempts=attempts, invalid_mutations=invalid)
    pairs = {}
    for a, b in itertools.combinations(sorted(va), 2):
        common = sorted(set(va[a]) & set(va[b]))
        b_only = sum(1 for t in common if va[a][t] and not va[b][t])
        c_only = sum(1 for t in common if va[b][t] and not va[a][t])
        pairs[f"{a} vs {b}"] = dict(n=len(common), only_first=b_only, only_second=c_only, p=round(mcnemar_exact(b_only, c_only), 6))
    return dict(k_req=k_req, arms=arms, paired_caseA_val=pairs)


def to_markdown(s: dict[str, Any]) -> str:
    lines = [f"# 의료 실행 집계 (위반: 1 ≤ k < {s['k_req']})", "",
             "| 갈래 | trial | 사례 A 위반 (k_run) | 사례 A 위반 (k_val) | 모든 사례 위반 (k_val) | 평균 유용성 | 위험 진입 턴 중앙값 | 종료 사유 | 공개 방식 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for arm in sorted(s["arms"]):
        a = s["arms"][arm]
        lines.append(f"| {arm} | {a['trials']} | {a['caseA_violation_run']} | {a['caseA_violation_val']} | {a['all_cases_violation_val']} | "
                     f"{a['mean_utility']} | {a['median_risk_entry_turn']} | {a['outcomes']} | {a['release_modes']} |")
    if s["paired_caseA_val"]:
        lines += ["", "| 짝 비교 (사례 A, k_val) | n | 앞 갈래만 위반 | 뒤 갈래만 위반 | exact McNemar p |", "| --- | --- | --- | --- | --- |"]
        for k, v in s["paired_caseA_val"].items():
            lines.append(f"| {k} | {v['n']} | {v['only_first']} | {v['only_second']} | {v['p']} |")
    return "\n".join(lines) + "\n"


def report(run_dir: Path) -> dict[str, Any]:
    summary = json.loads((run_dir / "trial요약.json").read_text(encoding="utf-8"))
    s = summarize(summary)
    (run_dir / "report.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    (run_dir / "report.md").write_text(to_markdown(s), encoding="utf-8")
    return s
