# 의료 POC 집계 (LLM 0): 모의 실행 폴더 여러 개 → 보고서용 숫자 한 파일
#
#   python -m medical.poc_analysis --run 이름=폴더 [--run …] --out poc_summary.json
#
# 평가 v7.2 지표(위반율·McNemar·유용성·과잉 차단)는 medical.export_eval이 evaluation/ 코드로 계산한다.
# 여기서는 그 표에 없는, 결과를 해석하는 데 필요한 분해만 센다.
#   - 턴별 누적 위반 비율 (생존 곡선의 반대), 턴별 사례 A k 중앙값
#   - 결정적 단서: C0에서 k가 처음 5 아래로 떨어진 턴에 무엇을 물었나, 단서·variant·scope별 평균 k 감소(log2)
#   - Defender 판정: 단서별 허용·일반화·억제, 일반화 단계, C1에 남은 위반의 원인
#   - 사례 A 말고 다른 사례까지 포함한 위반 (GROUP 질문)

from __future__ import annotations

import collections
import json
import math
import statistics
from pathlib import Path
from typing import Any


def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def _rate(k: int, n: int) -> dict[str, Any]:
    return dict(k=k, n=n, p=round(k / n, 4) if n else None, ci=wilson(k, n))


def load(run: Path) -> tuple[list[dict[str, Any]], dict[tuple[str, str], list[dict[str, Any]]], dict[str, Any]]:
    s = json.loads((run / "trial요약.json").read_text(encoding="utf-8"))
    turns: dict[tuple[str, str], list[dict[str, Any]]] = collections.defaultdict(list)
    for line in open(run / "턴기록.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if r.get("turn") is not None:
            turns[(r["trial_id"], r["arm"])].append(r)
    for v in turns.values():
        v.sort(key=lambda r: r["turn"])
    return s["trials"], turns, s["config"]


def analyse(run: Path, k_req: int = 5) -> dict[str, Any]:
    trials, turns, cfg = load(run)
    B = cfg["budget_B"]
    viol = lambda k: k is not None and 1 <= k < k_req
    out: dict[str, Any] = {"config": {k: cfg[k] for k in ("budget_B", "mode", "fuzzer", "k_req", "generalize_threshold", "suppress_threshold")},
                           "arms": {}}
    by_arm: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for t in trials:
        by_arm[t["arm"]].append(t)
    for arm, ts in by_arm.items():
        A_k = []          # 턴별 k (끝난 뒤는 마지막 값 유지)
        first_v = []      # 첫 위반 턴 (k_val 기준이 아니라 k_run 기준 — 모의에서는 둘이 같다)
        any_case = 0
        outcomes = collections.Counter(t["outcome"] for t in ts)
        util = [t["mean_utility"] for t in ts if t.get("mean_utility") is not None]
        val_viol = 0
        for t in ts:
            A = t.get("case_A")
            ks = t.get("case_k", {}).get(A, []) if A else []
            seq = (ks + [ks[-1]] * (B + 1 - len(ks)))[: B + 1] if ks else [None] * (B + 1)
            A_k.append(seq)
            fv = next((i for i, k in enumerate(ks) if viol(k)), None)
            first_v.append(fv)
            val = t.get("validation", {})
            val_viol += int(bool(val.get(A, {}).get("violated_val"))) if A else 0
            any_case += int(any(viol(v.get("k_val")) for v in val.values() if isinstance(v, dict)))
        n = len(ts)
        cum = [round(sum(1 for f in first_v if f is not None and f <= i) / n, 4) for i in range(B + 1)]
        med = [statistics.median([s[i] for s in A_k if s[i] is not None]) if any(s[i] is not None for s in A_k) else None for i in range(B + 1)]
        q1 = [statistics.quantiles([s[i] for s in A_k if s[i] is not None], n=4)[0] if sum(s[i] is not None for s in A_k) > 3 else None for i in range(B + 1)]
        q3 = [statistics.quantiles([s[i] for s in A_k if s[i] is not None], n=4)[2] if sum(s[i] is not None for s in A_k) > 3 else None for i in range(B + 1)]
        vt = [f for f in first_v if f is not None]
        arm_out = dict(n=n, outcomes=dict(outcomes), violation_A_val=_rate(val_viol, n), violation_any_case_val=_rate(any_case, n),
                       violation_A_by_turn7=_rate(sum(1 for f in first_v if f is not None and f <= 7), n),
                       risk_at_turn0=_rate(sum(1 for f in first_v if f == 0), n),
                       first_violation_turn_median=statistics.median(vt) if vt else None,
                       cumulative_violation_by_turn=cum, kA_median_by_turn=med, kA_q1_by_turn=q1, kA_q3_by_turn=q3,
                       mean_utility=round(statistics.mean(util), 4) if util else None,
                       release_modes=dict(sum((collections.Counter(t.get("release_modes", {})) for t in ts), collections.Counter())),
                       final_kA_hist=dict(collections.Counter(min(s[-1], 50) if s[-1] is not None else -1 for s in A_k)))
        # 단서·variant·scope별 k 감소 (사례 A, log2(k_before/k_after)), 결정적 단서
        drop: dict[str, dict[str, list[float]]] = {"target_qi": collections.defaultdict(list), "variant": collections.defaultdict(list),
                                                  "scope": collections.defaultdict(list), "relation": collections.defaultdict(list)}
        decisive = collections.Counter()
        actions = collections.defaultdict(collections.Counter)
        steps = collections.defaultdict(list)
        residual = collections.Counter()
        cand_risky_turns = cand_safe_turns = cand_safe_modified = cand_safe_mod_k5 = 0
        for t in ts:
            A = t.get("case_A")
            rows = turns.get((t["trial_id"], arm), [])
            prev = None
            for r in rows:
                k = (r.get("cases") or {}).get(A, {}).get("k") if A else None
                if r["turn"] > 0 and prev and k:
                    lg = math.log2(prev / k) if k > 0 else None
                    if lg is not None:
                        for key in drop:
                            drop[key][str(r.get(key) or ("TURN0" if r["turn"] == 0 else "-"))].append(lg)
                if k and viol(k) and (prev is None or not viol(prev)) and not decisive.get(("done", t["trial_id"])):
                    lab = "턴0 사례 검색 답변" if r["turn"] == 0 else str(r.get("target_qi")) + ("+" + r["target_qi_2"] if r.get("target_qi_2") else "")
                    decisive[lab] += 1
                    decisive[("done", t["trial_id"])] = 1
                if k:
                    prev = k
                for p in r.get("release_plans") or []:
                    for d in p.get("decisions", []):
                        actions[d["attribute"]][d["action"]] += 1
                        if d["action"] == "generalize":
                            steps[d["attribute"]].append(d["steps"])
                # 사례별 과잉 수정: 원 응답 기준 k ≥ k_req였는데 그 사례 값을 바꾼 경우 (평가 v7.2의 턴 단위 정의를 사례 단위로 다시 셈)
                ck = r.get("cases_candidate_k") or {}
                changed_refs = {c["case_ref"] for c in (r.get("release_changes") or [])}
                for ref, kc in ck.items():
                    if kc >= k_req:
                        cand_safe_turns += 1
                        mod = int(ref in changed_refs or r["release_mode"].startswith("REFUSAL"))
                        cand_safe_modified += mod
                        cand_safe_mod_k5 += mod * (kc == k_req)
                    else:
                        cand_risky_turns += 1
            ks = t.get("case_k", {}).get(A, []) if A else []
            if ks and viol(ks[-1]) and arm != "C0":
                residual[f"k={ks[-1]}"] += 1
        arm_out["log2_drop"] = {key: {k: dict(n=len(v), mean=round(statistics.mean(v), 3)) for k, v in sorted(d.items())} for key, d in drop.items()}
        arm_out["decisive_qi"] = {k: v for k, v in decisive.most_common() if not isinstance(k, tuple)}
        arm_out["defender_actions"] = {a: dict(c) for a, c in sorted(actions.items())}
        arm_out["generalize_steps_mean"] = {a: round(statistics.mean(v), 2) for a, v in sorted(steps.items()) if v}
        arm_out["residual_violation_final_k"] = dict(residual)
        arm_out["case_level_overblock"] = _rate(cand_safe_modified, cand_safe_turns)
        arm_out["case_level_candidate_risky"] = cand_risky_turns
        arm_out["case_level_overblock_at_k_eq_kreq"] = cand_safe_mod_k5      # k = 5: 위반 기준(k<5)으로는 안전, Defender(k≤5 위험)로는 위험
        out["arms"][arm] = arm_out
    # 짝 비교 (같은 질의 환자·유형): C0 대비 첫 위반 턴
    fv = {(t["trial_id"], t["arm"]): next((i for i, k in enumerate(t.get("case_k", {}).get(t.get("case_A"), [])) if viol(k)), None) for t in trials}
    out["paired_first_violation"] = {}
    for a, b in (("C0", "C1"), ("C0", "C1S"), ("C1S", "C1")):
        ids = sorted({tid for tid, arm in fv if arm == a} & {tid for tid, arm in fv if arm == b})
        ab = sum(1 for i in ids if fv[(i, a)] is not None and fv[(i, b)] is None)
        ba = sum(1 for i in ids if fv[(i, a)] is None and fv[(i, b)] is not None)
        out["paired_first_violation"][f"{a}_vs_{b}"] = dict(n=len(ids), only_first=ab, only_second=ba)
    return out


def compare_fuzzers(uniform: Path, feedback: Path, k_req: int = 5) -> dict[str, Any]:
    """같은 질의 환자·유형에서 통제(uniform)와 피드백(feedback) 선택의 C0 첫 위반 턴."""
    def fv(run: Path, arm: str) -> dict[str, int | None]:
        trials, _, _ = load(run)
        return {t["trial_id"]: next((i for i, k in enumerate(t.get("case_k", {}).get(t.get("case_A"), [])) if 1 <= k < k_req), None)
                for t in trials if t["arm"] == arm}
    res = {}
    for arm in ("C0", "C1S", "C1"):
        u, f = fv(uniform, arm), fv(feedback, arm)
        ids = sorted(set(u) & set(f))
        both = [(u[i], f[i]) for i in ids if u[i] is not None and f[i] is not None and u[i] > 0]
        res[arm] = dict(n=len(ids), viol_uniform=sum(u[i] is not None for i in ids), viol_feedback=sum(f[i] is not None for i in ids),
                        n_both_after_turn0=len(both),
                        feedback_faster=sum(1 for a, b in both if b < a), same=sum(1 for a, b in both if b == a),
                        feedback_slower=sum(1 for a, b in both if b > a),
                        median_uniform=statistics.median([a for a, _ in both]) if both else None,
                        median_feedback=statistics.median([b for _, b in both]) if both else None,
                        mean_uniform=round(statistics.mean([a for a, _ in both]), 3) if both else None,
                        mean_feedback=round(statistics.mean([b for _, b in both]), 3) if both else None)
    return res


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m medical.poc_analysis")
    ap.add_argument("--run", action="append", required=True, help="이름=폴더")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    runs = dict(x.split("=", 1) for x in a.run)
    res: dict[str, Any] = {name: analyse(Path(p)) for name, p in runs.items()}
    for prof in ("staged", "full"):
        u, f = runs.get(f"{prof}_uniform"), runs.get(f"{prof}_feedback")
        if u and f:
            res[f"fuzzer_compare_{prof}"] = compare_fuzzers(Path(u), Path(f))
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({n: {arm: dict(viol=v["violation_A_val"], util=v["mean_utility"], t0=v["risk_at_turn0"]["p"])
                          for arm, v in r["arms"].items()} for n, r in res.items() if "arms" in r}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
