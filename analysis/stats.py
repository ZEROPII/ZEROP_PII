# 요약 통계
#
# 단위(unit)는 "실행:대상" 하나다. 같은 대상을 여러 번 실행했다면(반복 실험) 부트스트랩에서 대상 단위로
# 묶어 뽑는다 (cluster bootstrap). 같은 대상의 반복을 독립 표본으로 부풀리지 않기 위해서다.
from __future__ import annotations

import math
from collections import defaultdict
from statistics import median
from typing import Callable, Sequence

import numpy as np

from analysis.simulate import UnitResult
from orchestrator.report import mcnemar_exact


def summarize(results: Sequence[UnitResult]) -> dict[str, float]:
    """한 조건의 결과 묶음 → 표 한 줄"""
    turns = [t for r in results for t in r.turns]
    delta = sum(t.delta for t in turns)
    eval_k = results[0].condition.eval_k if results else 0
    first = [r.first_violation for r in results if r.first_violation is not None]
    mins = [r.min_k_val for r in results]
    return {
        "units": len(results),
        "violations": sum(r.violated for r in results),
        "violation_rate": _rate(sum(r.violated for r in results), len(results)),
        "median_min_k": float(median(mins)) if mins else math.nan,
        "q1_min_k": float(np.percentile(mins, 25)) if mins else math.nan,
        "q3_min_k": float(np.percentile(mins, 75)) if mins else math.nan,
        "median_first_violation": float(median(first)) if first else math.nan,
        "turns": len(turns),
        "risk_turn_share": _rate(sum(1 for t in turns if 1 <= t.k_val < eval_k), len(turns)),
        "intervened_turns": sum(t.intervened for t in turns),
        "refused_turns": sum(t.refused for t in turns),
        "preserved_share": _rate(sum(1 for t in turns if not t.intervened and not t.refused), len(turns)),
        "delta_items": delta,
        "retention": (sum(t.retained for t in turns) / delta) if delta else 1.0,
        "suppressed": sum(t.suppressed for t in turns),
        "generalized": sum(t.generalized for t in turns),
        "k_run_zero_turns": sum(1 for t in turns if t.k_run == 0),
        "reason_zero_match": sum(1 for t in turns if t.reason == "NEW_ZERO_MATCH"),
        "reason_below_floor": sum(1 for t in turns if t.reason == "BELOW_FLOOR"),
        "worst_min_k": float(min(mins)) if mins else math.nan,
    }


def _rate(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else math.nan


# ── 부트스트랩 ───────────────────────────────────────────

def _clusters(units: Sequence[UnitResult]) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = defaultdict(list)
    for position, unit in enumerate(units):
        groups[unit.target_id].append(position)
    return groups


def bootstrap(results_by_arm: dict[str, Sequence[UnitResult]], statistic: Callable[[dict[str, list[UnitResult]]], float],
              *, resamples: int, seed: int) -> tuple[float, float]:
    """
    input : results_by_arm (갈래 → 같은 순서의 단위 결과. 짝 비교를 위해 단위 순서가 같아야 한다),
            statistic (뽑힌 묶음 → 값), resamples, seed
    output : 95% 백분위 신뢰구간 (낮은 값, 높은 값)
    """
    first = next(iter(results_by_arm.values()))
    clusters = list(_clusters(first).values())
    if not clusters:
        return math.nan, math.nan
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(resamples):
        picked = rng.integers(0, len(clusters), len(clusters))
        positions = [p for c in picked for p in clusters[c]]
        sample = {arm: [results[p] for p in positions] for arm, results in results_by_arm.items()}
        value = statistic(sample)
        if not math.isnan(value):
            values.append(value)
    if not values:
        return math.nan, math.nan
    low, high = np.percentile(values, [2.5, 97.5])
    return float(low), float(high)


def violation_rate(results: Sequence[UnitResult]) -> float:
    return _rate(sum(r.violated for r in results), len(results))


def paired(a: Sequence[UnitResult], b: Sequence[UnitResult], *, resamples: int, seed: int) -> dict[str, float]:
    """
    두 조건의 짝 비교 (단위 순서가 같아야 한다)
    output : 위반 비율 차이(a−b)와 신뢰구간, 엇갈린 짝 수, exact McNemar p, log10(최소 k) 차이(b−a)의 중앙값과 신뢰구간
    """
    if [r.unit for r in a] != [r.unit for r in b]:
        raise ValueError("짝 비교는 같은 단위 순서여야 합니다.")
    only_a = sum(1 for x, y in zip(a, b) if x.violated and not y.violated)
    only_b = sum(1 for x, y in zip(a, b) if y.violated and not x.violated)
    diff = violation_rate(a) - violation_rate(b)
    low, high = bootstrap({"a": a, "b": b}, lambda s: violation_rate(s["a"]) - violation_rate(s["b"]),
                          resamples=resamples, seed=seed)

    def log_gap(s: dict[str, list[UnitResult]]) -> float:
        gaps = [math.log10(max(y.min_k_val, 1)) - math.log10(max(x.min_k_val, 1)) for x, y in zip(s["a"], s["b"])]
        return float(median(gaps)) if gaps else math.nan

    gap = log_gap({"a": list(a), "b": list(b)})
    gap_low, gap_high = bootstrap({"a": a, "b": b}, log_gap, resamples=resamples, seed=seed + 1)
    return {"rate_diff": diff, "rate_diff_low": low, "rate_diff_high": high, "only_a": only_a, "only_b": only_b,
            "mcnemar_p": mcnemar_exact(only_a, only_b), "log10_gap_median": gap,
            "log10_gap_low": gap_low, "log10_gap_high": gap_high}


def rate_interval(results: Sequence[UnitResult], *, resamples: int, seed: int) -> tuple[float, float]:
    return bootstrap({"x": results}, lambda s: violation_rate(s["x"]), resamples=resamples, seed=seed)


# ── 곡선 ─────────────────────────────────────────────────

def trajectory(results: Sequence[UnitResult]) -> list[dict[str, float]]:
    """턴별 k_val의 중앙값과 사분위 (그 턴까지 대화가 이어진 단위만)"""
    by_turn: dict[int, list[int]] = defaultdict(list)
    for r in results:
        for t in r.turns:
            by_turn[t.turn].append(t.k_val)
    rows = []
    for turn in sorted(by_turn):
        values = by_turn[turn]
        rows.append({"turn": turn, "median": float(median(values)), "q1": float(np.percentile(values, 25)),
                     "q3": float(np.percentile(values, 75)), "min": float(min(values)), "n": len(values)})
    return rows


def survival(results: Sequence[UnitResult], max_turn: int) -> list[dict[str, float]]:
    """턴 t까지 한 번이라도 위반한 단위의 비율 (누적)"""
    rows = []
    for turn in range(1, max_turn + 1):
        hit = sum(1 for r in results if r.first_violation is not None and r.first_violation <= turn)
        rows.append({"turn": turn, "violated_share": _rate(hit, len(results))})
    return rows


def knee(points: Sequence[tuple[float, float]]) -> int | None:
    """
    input : (x, y) 점들 (설정 순서대로. 예: x = 정보 유지율, y = 위반 비율)
    output : 무릎점의 위치 (양 끝을 잇는 직선에서 가장 먼 점. Kneedle 방식). 점이 셋 미만이면 None

    두 축을 0~1로 맞춘 뒤 거리를 잰다. 값의 범위가 0이면 그 축은 무시한다.
    """
    if len(points) < 3:
        return None
    xs, ys = np.array([p[0] for p in points], float), np.array([p[1] for p in points], float)

    def scale(v: np.ndarray) -> np.ndarray:
        span = v.max() - v.min()
        return (v - v.min()) / span if span else np.zeros_like(v)

    x, y = scale(xs), scale(ys)
    start, end = np.array([x[0], y[0]]), np.array([x[-1], y[-1]])
    line = end - start
    norm = np.linalg.norm(line)
    if norm == 0:
        return None
    distances = np.abs(line[0] * (y - start[1]) - line[1] * (x - start[0])) / norm
    best = int(np.argmax(distances))
    return best if distances[best] > 0 else None


def stability(a: Sequence[UnitResult], b: Sequence[UnitResult], sizes: Sequence[int], *, resamples: int,
              seed: int) -> list[dict[str, float]]:
    """
    대상 수에 따른 추정의 흔들림. 대상 n명을 복원 추출해 위반 비율 차이(a−b)를 다시 계산한다.
    output : n마다 평균, 2.5/97.5 백분위, 구간 폭
    """
    clusters = list(_clusters(a).values())
    rng = np.random.default_rng(seed)
    rows = []
    for n in sizes:
        values = []
        for _ in range(resamples):
            picked = rng.integers(0, len(clusters), n)
            positions = [p for c in picked for p in clusters[c]]
            values.append(violation_rate([a[p] for p in positions]) - violation_rate([b[p] for p in positions]))
        low, high = np.percentile(values, [2.5, 97.5])
        rows.append({"targets": n, "mean_diff": float(np.mean(values)), "low": float(low), "high": float(high),
                     "width": float(high - low)})
    return rows


# ── 짝 순위 검정 ─────────────────────────────────────────

def per_target(results: Sequence[UnitResult], value: Callable[[UnitResult], float]) -> dict[str, float]:
    """대상별 평균 (같은 대상을 여러 번 실행했으면 평균을 한 값으로 쓴다)"""
    groups: dict[str, list[float]] = defaultdict(list)
    for r in results:
        groups[r.target_id].append(value(r))
    return {target: float(np.mean(values)) for target, values in groups.items()}


def wilcoxon_exact(differences: Sequence[float]) -> dict[str, float]:
    """
    input : 짝 차이들 (뒤 조건 − 앞 조건)
    output : 0이 아닌 짝 수, 양의 순위합, 양측 exact p (동순위는 평균 순위. 0인 차이는 뺀다)

    순위를 두 배로 해 정수로 만든 뒤 부호 배치의 분포를 동적계획으로 센다 (scipy 없이 정확한 값).
    """
    values = [float(d) for d in differences if abs(d) > 1e-12]
    n = len(values)
    if n == 0:
        return {"n": 0, "w_plus": 0.0, "p": 1.0}
    order = sorted(range(n), key=lambda i: abs(values[i]))
    ranks = [0.0] * n
    position = 0
    while position < n:
        end = position
        while end + 1 < n and abs(abs(values[order[end + 1]]) - abs(values[order[position]])) < 1e-12:
            end += 1
        for i in range(position, end + 1):
            ranks[order[i]] = (position + end) / 2 + 1
        position = end + 1
    doubled = [int(round(2 * r)) for r in ranks]
    w_plus = sum(d for d, v in zip(doubled, values) if v > 0)
    total = sum(doubled)
    counts = {0: 1}
    for rank in doubled:
        nxt: dict[int, int] = defaultdict(int)
        for value, count in counts.items():
            nxt[value] += count
            nxt[value + rank] += count
        counts = nxt
    observed = min(w_plus, total - w_plus)
    tail = sum(count for value, count in counts.items() if value <= observed)
    p = min(1.0, 2 * tail / 2 ** n)
    return {"n": n, "w_plus": w_plus / 2, "p": p}


def holm(pvalues: dict[str, float]) -> dict[str, float]:
    """Holm–Bonferroni 보정 p (여러 비교를 한 묶음으로 볼 때)"""
    ordered = sorted(pvalues.items(), key=lambda kv: kv[1])
    adjusted, running = {}, 0.0
    for rank, (name, p) in enumerate(ordered):
        running = max(running, min(1.0, (len(ordered) - rank) * p))
        adjusted[name] = running
    return adjusted


# ── Defender 판단의 정확도 ──────────────────────────────

def decisions(results: Sequence[UnitResult]) -> dict[str, float]:
    """
    턴마다 정답 기준으로 "막아야 했는가"(원래 답변을 그대로 내면 1 ≤ k_val < 평가 기준)와 "막았는가"를 대조한다.
    추출이 실패해 거절한 턴은 막은 것으로 센다.
    """
    tp = fp = fn = tn = 0
    fp_reasons: dict[str, int] = defaultdict(int)
    for r in results:
        eval_k = r.condition.eval_k
        for t in r.turns:
            needed = 1 <= t.k_val_raw < eval_k
            acted = t.intervened or t.refused
            if needed and acted:
                tp += 1
            elif needed:
                fn += 1
            elif acted:
                fp += 1
                fp_reasons[t.reason or ("REFUSAL" if t.refused else "OTHER")] += 1
            else:
                tn += 1
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": _rate(tp, tp + fp), "recall": _rate(tp, tp + fn),
            "over_block_rate": _rate(fp, fp + tn), "accuracy": _rate(tp + tn, tp + fp + fn + tn),
            "fp_zero_match": fp_reasons.get("NEW_ZERO_MATCH", 0), "fp_below_floor": fp_reasons.get("BELOW_FLOOR", 0),
            "fp_refusal": fp_reasons.get("REFUSAL", 0)}


def qi_retention(results: Sequence[UnitResult]) -> dict[str, tuple[float, int]]:
    """QI별 (정보 유지율, 새 공개분 수)"""
    sums: dict[str, list[float]] = defaultdict(list)
    for r in results:
        for t in r.turns:
            for attribute, value in t.qi_retained:
                sums[attribute].append(value)
    return {attribute: (float(np.mean(values)), len(values)) for attribute, values in sums.items()}


# ── 표본 크기 ───────────────────────────────────────────

def mcnemar_power(n: int, p_first_only: float, p_second_only: float, alpha: float = 0.05) -> float:
    """
    대상 n명에서 exact McNemar가 alpha 아래로 나올 확률 (정확 계산).
    p_first_only / p_second_only → 한 대상이 첫 조건에서만 / 둘째 조건에서만 위반할 확률
    """
    discordant = p_first_only + p_second_only
    if discordant <= 0:
        return 0.0
    share = p_first_only / discordant
    power = 0.0
    for d in range(n + 1):
        p_d = math.comb(n, d) * discordant ** d * (1 - discordant) ** (n - d)
        if p_d < 1e-15:
            continue
        for b in range(d + 1):
            if mcnemar_exact(b, d - b) < alpha:
                power += p_d * math.comb(d, b) * share ** b * (1 - share) ** (d - b)
    return power
