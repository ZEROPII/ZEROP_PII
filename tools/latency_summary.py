#!/usr/bin/env python3
"""
결과 ⑥ 응답 시간 집계기 (표준 라이브러리만 사용).

사용법
  python latency_summary.py <실행폴더1> [<실행폴더2> ...] [--out 결과폴더] [--boot 1000]

여러 폴더를 넣으면 한꺼번에 합친다 (순서를 바꾼 블록을 함께 넣는다).
각 폴더의 `턴기록.jsonl`(sec_answer)과 `trial요약.json`(outcome)을 읽는다.

집계 단위
  - 대상: 턴 1 이상 (턴 0은 갈래 간 공유라서 제외)
  - 값: sec_answer = 질문 전송 후 공개 답변 완성까지 걸린 초 (C0는 대상 AI 답, C1은 방어 포함)
  - 재표본: 질의 환자(trial) 단위 부트스트랩. 같은 환자의 턴은 독립이 아니기 때문.
  - C1 − C0 차이는 두 갈래에 모두 있는 환자만 짝지어 재표본한다.

출력 (결과폴더, 기본값 ./latency_out)
  latency_summary.md : 갈래별 중앙값, IQR, p95, p95 95% 신뢰구간, 턴 수, 실패 수, C1−C0 차이
  latency_by_turn.csv: 턴 번호별 갈래 중앙값·p95
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
from collections import defaultdict
from pathlib import Path


def load_run(run: Path) -> tuple[list[dict], dict[str, int]]:
    turns_path = run / "턴기록.jsonl"
    if not turns_path.exists():
        raise SystemExit(f"턴기록.jsonl이 없습니다: {turns_path}")
    rows = []
    for line in turns_path.open(encoding="utf-8"):
        if line.strip():
            rows.append(json.loads(line))
    fails: dict[str, int] = defaultdict(int)
    summ = run / "trial요약.json"
    if summ.exists():
        for t in json.loads(summ.read_text(encoding="utf-8")).get("trials", []):
            if t.get("outcome") == "LLM_ERROR":
                fails[t.get("arm", "?")] += 1
    return rows, fails


def pct(xs: list[float], q: float) -> float:
    """최근접 순위 분위수."""
    s = sorted(xs)
    if not s:
        return float("nan")
    k = max(0, min(len(s) - 1, int(round(q * len(s) + 0.5)) - 1))
    return s[k]


def stats(xs: list[float]) -> dict[str, float]:
    if not xs:
        return dict(n=0, median=float("nan"), q1=float("nan"), q3=float("nan"), p95=float("nan"))
    qs = statistics.quantiles(xs, n=4, method="inclusive") if len(xs) >= 2 else [xs[0]] * 3
    return dict(n=len(xs), median=statistics.median(xs), q1=qs[0], q3=qs[2], p95=pct(xs, 0.95))


def boot_ci(by_trial: dict[str, list[float]], fn, B: int, rng: random.Random) -> tuple[float, float]:
    trials = [t for t in by_trial if by_trial[t]]
    if not trials:
        return float("nan"), float("nan")
    vals = []
    for _ in range(B):
        pick = [rng.choice(trials) for _ in trials]
        xs = [x for t in pick for x in by_trial[t]]
        if xs:
            vals.append(fn(xs))
    vals.sort()
    if not vals:
        return float("nan"), float("nan")
    lo = vals[int(0.025 * (len(vals) - 1))]
    hi = vals[int(0.975 * (len(vals) - 1))]
    return lo, hi


def paired_diff_ci(a: dict[str, list[float]], b: dict[str, list[float]], fn, B: int, rng: random.Random):
    common = [t for t in a if t in b and a[t] and b[t]]
    if not common:
        return None
    point = fn([x for t in common for x in b[t]]) - fn([x for t in common for x in a[t]])
    diffs = []
    for _ in range(B):
        pick = [rng.choice(common) for _ in common]
        xa = [x for t in pick for x in a[t]]
        xb = [x for t in pick for x in b[t]]
        diffs.append(fn(xb) - fn(xa))
    diffs.sort()
    return point, diffs[int(0.025 * (len(diffs) - 1))], diffs[int(0.975 * (len(diffs) - 1))], len(common)


def main() -> None:
    ap = argparse.ArgumentParser(description="결과 ⑥ 응답 시간 집계")
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--out", default="latency_out")
    ap.add_argument("--boot", type=int, default=1000)
    a = ap.parse_args()
    rng = random.Random(7)

    by_arm: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    by_arm_turn: dict[tuple[str, int], list[float]] = defaultdict(list)
    fails: dict[str, int] = defaultdict(int)
    run_info = []
    for r in a.runs:
        run = Path(r)
        rows, f = load_run(run)
        for k, v in f.items():
            fails[k] += v
        n_run = 0
        for row in rows:
            t = row.get("turn")
            v = row.get("sec_answer")
            if t is None or t < 1 or v is None:
                continue
            arm = row.get("arm", "?")
            trial = str(row.get("trial_id"))  # 질의 환자 = 군집 단위 (블록이 달라도 같은 환자)
            by_arm[arm][trial].append(float(v))
            by_arm_turn[(arm, t)].append(float(v))
            n_run += 1
        run_info.append((run.name, n_run))

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    md = ["# 결과 ⑥ 응답 시간 집계", "", "- 실행 폴더: " + ", ".join(f"{n}({c}턴)" for n, c in run_info),
          "- 턴 1 이상, 질문 전송부터 공개 답변 완성까지 (초). 질의 환자 단위 부트스트랩 " + str(a.boot) + "회.", "",
          "| 갈래 | 턴 수 | 중앙값 [IQR] | p95 | p95 95% 신뢰구간 | 실패 trial |", "| --- | --- | --- | --- | --- | --- |"]
    for arm in sorted(by_arm):
        flat = {t: xs for t, xs in by_arm[arm].items()}
        allx = [x for xs in flat.values() for x in xs]
        s = stats(allx)
        lo, hi = boot_ci(flat, lambda xs: pct(xs, 0.95), a.boot, rng)
        md.append(f"| {arm} | {s['n']} | {s['median']:.2f} [{s['q1']:.2f}, {s['q3']:.2f}] | {s['p95']:.2f} | [{lo:.2f}, {hi:.2f}] | {fails.get(arm, 0)} |")
    if "C0" in by_arm and "C1" in by_arm:
        md += ["", "## C1 − C0 차이 (두 갈래 모두 있는 환자만 짝지어 재표본)", "",
               "| 지표 | 차이 (C1 − C0) | 95% 신뢰구간 | 짝 환자 수 |", "| --- | --- | --- | --- |"]
        for name, fn in [("중앙값", statistics.median), ("p95", lambda xs: pct(xs, 0.95))]:
            res = paired_diff_ci(by_arm["C0"], by_arm["C1"], fn, a.boot, rng)
            if res:
                point, lo, hi, n = res
                md.append(f"| {name} | {point:+.2f} 초 | [{lo:+.2f}, {hi:+.2f}] | {n} |")
    md += ["", "## 해석 주의", "",
           "- 실행 순서 효과를 줄이려면 `--arms C0,C1`과 `--arms C1,C0` 두 블록을 함께 넣는다.",
           "- 턴 수가 갈래마다 다르다 (MediCloak은 위험 시 멈춘다). 턴 번호별 표를 같이 본다.",
           "- 질문 생성(공격 쪽) 시간은 포함하지 않는다."]
    (out / "latency_summary.md").write_text("\n".join(md), encoding="utf-8")

    with (out / "latency_by_turn.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["갈래", "턴", "n", "중앙값", "p95"])
        for (arm, t), xs in sorted(by_arm_turn.items()):
            s = stats(xs)
            w.writerow([arm, t, s["n"], round(s["median"], 3), round(s["p95"], 3)])
    print("\n".join(md))
    print(f"\n결과 저장: {out / 'latency_summary.md'}")


if __name__ == "__main__":
    main()
