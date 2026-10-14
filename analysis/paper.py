# 표·그림·보고서·재현 정보를 만든다
from __future__ import annotations

import csv
import json
import math
import platform
import subprocess
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Sequence

import matplotlib
import numpy as np

from analysis import figures, stats
from analysis.dialogues import Dialogue, RunInfo
from analysis.pipeline import Plan, Settings
from analysis.populations import PopulationBank, file_sha256
from analysis.simulate import Condition, Context, UnitResult

KST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _pct(value: float) -> str:
    return "-" if value is None or (isinstance(value, float) and math.isnan(value)) else f"{100 * value:.1f}%"


def _num(value: float, digits: int = 0) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    return f"{value:,.{digits}f}"


def _write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        if rows:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    return path


def _table(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return "\n".join(lines)


class PaperBuilder:
    def __init__(self, settings: Settings, runs: Sequence[RunInfo], dialogues: Sequence[Dialogue], plan: Plan,
                 results: dict[Condition, list[UnitResult]], consistency: dict[Condition, list[UnitResult]],
                 context: Context, strata: dict[str, str], out: Path, lang: str) -> None:
        self.s, self.runs, self.dialogues, self.plan = settings, runs, dialogues, plan
        self.results, self.consistency, self.context = results, consistency, context
        self.strata, self.out, self.lang = strata, out, lang
        self.files: list[Path] = []
        self.bank: PopulationBank = context.bank

    # ── 조건 찾기 ───────────────────────────────────────

    def main(self, arm: str) -> list[UnitResult]:
        return next(self.results[c] for c in self.plan.groups["main"] if c.arm == arm)

    def find(self, group: str, **match: Any) -> list[UnitResult]:
        for condition in self.plan.groups[group]:
            if all(getattr(condition, key) == value for key, value in match.items()):
                return self.results[condition]
        raise KeyError(f"{group}: {match}")

    # ── 전체 ────────────────────────────────────────────

    def build(self) -> Path:
        self.out.mkdir(parents=True, exist_ok=True)
        sections = [self._header(), self._consistency(), self._main(), self._tradeoff(), self._population(),
                    self._miss(), self._generalization(), self._stability(), self._overhead(), self._figures(),
                    self._cautions()]
        self._per_unit_csv()
        report = self.out / "paper_report.md"
        report.write_text("\n\n".join(sections) + "\n", encoding="utf-8")
        self.files.append(report)
        self._manifest()
        return report

    # ── 1. 실행 정보 ────────────────────────────────────

    def _header(self) -> str:
        units = len(self.dialogues)
        targets = sorted({d.target_id for d in self.dialogues})
        rich = sum(1 for t in targets if self.strata.get(t) == "rich")
        sparse = sum(1 for t in targets if self.strata.get(t) == "sparse")
        turns = sum(len(d.turns) for d in self.dialogues)
        strata = (f", 단서 충분 {rich}명 / 부족 {sparse}명" if rich or sparse else ", 층 정보 없음 (--targets-file로 지정)")
        rows = [
            ["사용한 실행", ", ".join(r.run_id for r in self.runs)],
            ["분석 단위 (실행×대상)", f"{units}개 (대상 {len(targets)}명{strata})"],
            ["대화 턴", f"{turns}턴"],
            ["평가 기준", f"1 ≤ k_val < {self.s.eval_k} 이면 위반"],
            ["본 결과 기준 집단", f"{self.s.main_population} ({self.bank.index(self.s.main_population).size:,}명)"],
            ["정규화", "현재 해석 규칙으로 다시 정규화" if self.s.normalization == "current" else "실행 당시 정규화 그대로"],
            ["부트스트랩", f"{self.s.resamples:,}회, 대상 단위 묶음 추출, 난수 {self.s.seed}"],
            ["LLM 호출", "0회 (기록만으로 계산)"],
        ]
        return "# 논문용 분석 결과\n\n" + _table(["항목", "값"], rows)

    # ── 2. 재현성: 실제 실행과의 일치 ───────────────────

    def _consistency(self) -> str:
        rows, csv_rows = [], []
        by_unit = {d.unit: d for d in self.dialogues}
        for condition, units in self.consistency.items():
            validator = self.context.validator(condition.population)
            same_turns = total_turns = same_violation = same_intervention = intervention_turns = compared = 0
            for unit in units:
                live = by_unit[unit.unit].live.get(condition.arm)
                if live is None:
                    continue
                compared += 1
                live_k = [validator.validate(unit.target_id, state).k_val for state in live.states]
                sim_k = [t.k_val for t in unit.turns]
                total_turns += min(len(live_k), len(sim_k))
                same_turns += sum(1 for a, b in zip(live_k, sim_k) if a == b)
                live_violated = any(1 <= k < condition.eval_k for k in live_k)
                same_violation += live_violated == unit.violated
                live_int = [path in ("REWRITTEN", "REFUSAL") for path in live.paths]
                sim_int = [t.intervened or t.refused for t in unit.turns]
                intervention_turns += min(len(live_int), len(sim_int))
                same_intervention += sum(1 for a, b in zip(live_int, sim_int) if a == b)
            if not compared:
                continue
            row = {"arm": condition.arm, "k_req": condition.k_req, "population": condition.population,
                   "units": compared, "turn_k_match": same_turns / total_turns,
                   "violation_match": same_violation / compared,
                   "intervention_match": same_intervention / intervention_turns}
            csv_rows.append(row)
            rows.append([condition.arm, compared, _pct(row["turn_k_match"]), _pct(row["violation_match"]),
                         _pct(row["intervention_match"])])
        self.files.append(_write_csv(self.out / "tables" / "consistency.csv", csv_rows))
        if not rows:
            return "## 1. 재현성 확인\n\n비교할 실제 실행 기록(다른 갈래)이 없어 건너뛰었다."
        return ("## 1. 재현성 확인: 기록 재계산 vs 실제 실행\n\n"
                "실제 실행과 같은 설정(실행 당시 정규화, 같은 k_req와 기준 집단)으로 기록만 다시 판정해, "
                "실제 실행이 턴마다 남긴 공개 State의 k_val과 비교했다. 일치율이 높을수록 "
                "아래의 조건 변경 분석(같은 기록을 다른 설정으로 다시 판정)을 실제 실행의 대용으로 쓸 근거가 된다.\n\n"
                + _table(["갈래", "단위", "턴별 k_val 일치", "대상별 위반 판정 일치", "턴별 개입 여부 일치"], rows))

    # ── 3. 본 결과 ──────────────────────────────────────

    def _arm_row(self, arm: str, units: list[UnitResult], seed: int) -> tuple[list[Any], dict[str, Any]]:
        summary = stats.summarize(units)
        low, high = stats.rate_interval(units, resamples=self.s.resamples, seed=seed)
        cells = [arm, f"{summary['violations']}/{summary['units']} ({_pct(summary['violation_rate'])})",
                 f"{_pct(low)}–{_pct(high)}",
                 f"{_num(summary['median_min_k'])} [{_num(summary['q1_min_k'])}–{_num(summary['q3_min_k'])}]",
                 _num(summary["median_first_violation"], 1), _pct(summary["risk_turn_share"]),
                 _pct(summary["preserved_share"]), _pct(summary["retention"]),
                 f"{summary['intervened_turns']}/{summary['refused_turns']}"]
        return cells, {"arm": arm, **summary, "violation_low": low, "violation_high": high}

    def _main(self) -> str:
        rows, csv_rows = [], []
        for number, arm in enumerate(("C0", "C1S", "C1")):
            cells, row = self._arm_row(arm, self.main(arm), self.s.seed + number)
            rows.append(cells)
            csv_rows.append(row)
        self.files.append(_write_csv(self.out / "tables" / "main_results.csv", csv_rows))

        pairs, pair_rows = [], []
        for number, (a, b) in enumerate((("C0", "C1"), ("C1S", "C1"), ("C0", "C1S"))):
            result = stats.paired(self.main(a), self.main(b), resamples=self.s.resamples, seed=self.s.seed + 10 + number)
            pair_rows.append({"comparison": f"{a} vs {b}", **result})
            pairs.append([f"{a} − {b}", f"{_pct(result['rate_diff'])} [{_pct(result['rate_diff_low'])}, "
                          f"{_pct(result['rate_diff_high'])}]", f"{result['only_a']} / {result['only_b']}",
                          f"{result['mcnemar_p']:.3f}",
                          f"{result['log10_gap_median']:.2f} [{result['log10_gap_low']:.2f}, {result['log10_gap_high']:.2f}]"])
        self.files.append(_write_csv(self.out / "tables" / "paired_tests.csv", pair_rows))

        for arm in ("C0", "C1S", "C1"):
            self.files.append(_write_csv(self.out / "tables" / f"trajectory_{arm}.csv", stats.trajectory(self.main(arm))))
        return ("## 2. 본 결과 (표 1)\n\n"
                f"설정: 기준 집단 {self.s.main_population}, Defender k_req = 평가 기준 = {self.s.eval_k}.\n\n"
                + _table(["갈래", "위반 대상", "95% CI", "최소 k_val 중앙값 [사분위]", "첫 위반 턴(중앙값)",
                          "위험 턴 비율", "원문 유지 턴", "정보 유지율", "개입/거절 턴"], rows)
                + "\n\n짝 비교 (같은 대상, 같은 질문)\n\n"
                + _table(["비교", "위반 비율 차이 [95% CI]", "한쪽만 위반 (앞/뒤)", "exact McNemar p",
                          "log10 최소 k 차이(뒤−앞) 중앙값 [95% CI]"], pairs)
                + "\n\n- 위험 턴 비율: 전체 턴 중 그 턴의 누적 공개 상태가 평가 기준 미만이었던 턴의 비율. "
                  "대상 수가 적을 때 위반 여부(대상 단위)보다 촘촘한 지표다.\n"
                  "- 정보 유지율: 새로 공개될 뻔한 정보 중 공개된 정도 (그대로 1, 한 단계 일반화는 부분, 억제 0).\n"
                  "- log10 최소 k 차이: 대상마다 두 조건의 최소 후보 수를 로그로 비교한 값. 1이면 10배 차이.")

    # ── 4. 보호–유용성 ──────────────────────────────────

    def _tradeoff(self) -> str:
        series: dict[str, list[dict[str, Any]]] = {"C1": [], "C1S": [], "C1-g0": [], "STATIC": [], "C0": []}
        csv_rows = []
        for condition in self.plan.groups["tradeoff"]:
            summary = stats.summarize(self.results[condition])
            if condition.arm == "C0":
                name, label = "C0", "C0"
            elif condition.arm == "STATIC":
                name, label = "STATIC", f"G{condition.static_level}"
            elif condition.max_generalization == 0:
                name, label = "C1-g0", f"k{condition.k_req}"
            else:
                name, label = condition.arm, f"k{condition.k_req}"
            point = {"label": label, "k_req": condition.k_req if condition.arm in ("C1", "C1S") else None,
                     "worst_k": summary["worst_min_k"], "median_k": summary["median_min_k"],
                     "retention": 100 * summary["retention"], "violation": 100 * summary["violation_rate"],
                     "risk_turns": 100 * summary["risk_turn_share"], "preserved": 100 * summary["preserved_share"],
                     "zero_match": summary["reason_zero_match"], "below_floor": summary["reason_below_floor"]}
            series[name].append(point)
            csv_rows.append({"series": name, "static_level": condition.static_level if condition.arm == "STATIC" else "",
                             "max_generalization": condition.max_generalization, **point})
        if series["STATIC"]:
            series["STATIC"] = [dict(series["C0"][0], label="G0")] + series["STATIC"]
        self.files.append(_write_csv(self.out / "tables" / "tradeoff.csv", csv_rows))

        c1 = series["C1"]
        position = stats.knee([(math.log10(max(p["worst_k"], 1)), p["retention"]) for p in c1])
        self.knee_point = c1[position] if position is not None else None
        compliant = next((p for p in c1 if p["worst_k"] >= self.s.eval_k), None)
        self.series = series

        def row(p: dict[str, Any]) -> list[Any]:
            return [p["label"], _num(p["worst_k"]), _num(p["median_k"]), f"{p['retention']:.1f}%",
                    f"{p['preserved']:.1f}%", f"{p['violation']:.1f}%", f"{p['zero_match']} / {p['below_floor']}"]

        header = ["설정", "최악 대상의 최소 k", "최소 k 중앙값", "정보 유지율", "원문 유지 턴",
                  f"위반 (k<{self.s.eval_k})", "개입 이유 0명/기준미달"]
        notes = []
        if compliant:
            notes.append(f"- 모든 대상이 평가 기준 k ≥ {self.s.eval_k}를 지킨 가장 낮은 운영 설정: **{compliant['label']}** "
                         f"(정보 유지율 {compliant['retention']:.1f}%).")
        if self.knee_point:
            notes.append(f"- 곡선의 무릎점 (가로축 log k, 세로축 정보 유지율. 양 끝을 잇는 직선에서 가장 먼 점, Kneedle 방식): "
                         f"**{self.knee_point['label']}** (최악 대상 k {self.knee_point['worst_k']:,.0f}, "
                         f"유지율 {self.knee_point['retention']:.1f}%). 이보다 k_req를 올리면 얻는 보호에 비해 잃는 정보가 커진다.")
        notes.append("- 개입 이유: '0명'은 새 답변이 후보를 0명으로 만드는 경우(대개 틀린 단서가 섞인 경우)로 k_req와 무관하게 막는다. "
                     "'기준미달'은 k_req 아래로 좁히는 경우다. 운영 k_req를 바꾸면 뒤쪽만 달라진다.")
        notes.append("- 고정 일반화(G)는 위험과 무관하게 모든 새 값을 올리므로, 같은 보호 수준에서 정보를 얼마나 더 잃는지 비교한다.")
        return ("## 3. 보호–유용성 균형 (표 2, 그림 2)\n\n"
                f"Defender의 운영 k_req만 바꿔 같은 기록을 다시 판정했다. 보호는 '최악 대상의 최소 k'(모든 대상이 대화 내내 "
                f"보장받은 최소 후보 수), 유용성은 정보 유지율이다. 위반 열은 평가 기준(k < {self.s.eval_k})으로 셌다.\n\n"
                "누적 방어 (C1)\n\n" + _table(header, [row(p) for p in c1])
                + "\n\n누적 방어, 억제만 (일반화 없이 값을 빼기만 함)\n\n" + _table(header, [row(p) for p in series["C1-g0"]])
                + "\n\n턴별 방어 (C1S)\n\n" + _table(header, [row(p) for p in series["C1S"]])
                + "\n\n고정 일반화 (새 값을 모두 G단계 위로 올림, G0 = 방어 없음)\n\n"
                + _table(header, [row(p) for p in series["STATIC"]])
                + "\n\n" + "\n".join(notes))

    # ── 5. 민감도 ───────────────────────────────────────

    def _population(self) -> str:
        rows, csv_rows = [], []
        for name in self.s.populations:
            for arm in ("C0", "C1S", "C1"):
                summary = stats.summarize(self.find("population", arm=arm, population=name))
                csv_rows.append({"population": name, "arm": arm, "size": self.bank.index(name).size,
                                 "violation_pct": 100 * summary["violation_rate"],
                                 "risk_turn_pct": 100 * summary["risk_turn_share"],
                                 "retention_pct": 100 * summary["retention"], "median_min_k": summary["median_min_k"]})
            line = {r["arm"]: r for r in csv_rows if r["population"] == name}
            rows.append([name, f"{self.bank.index(name).size:,}", f"{line['C0']['violation_pct']:.0f}%",
                         f"{line['C1S']['violation_pct']:.0f}%", f"{line['C1']['violation_pct']:.0f}%",
                         f"{line['C1']['retention_pct']:.1f}%", _num(line["C0"]["median_min_k"]),
                         _num(line["C1"]["median_min_k"])])
        self.population_rows = csv_rows
        self.files.append(_write_csv(self.out / "tables" / "sensitivity_population.csv", csv_rows))
        check = self.bank.association_table(self.s.populations)
        self.files.append(_write_csv(self.out / "tables" / "population_check.csv", check))
        check_rows = [[r["population"], f"{r['size']:,}", f"{100 * r['same_country_rate']:.1f}%"] for r in check]
        return ("## 4. 민감도 (표 3, 그림 3)\n\n### 4.1 기준 집단\n\n"
                + _table(["기준 집단", "인원", "C0 위반", "C1S 위반", "C1 위반", "C1 정보 유지율", "C0 최소 k 중앙값",
                          "C1 최소 k 중앙값"], rows)
                + "\n\n기준 집단의 현실성 점검: 출생 국가와 거주 국가가 같은 사람의 비율 "
                  f"(원본 300명 = {100 * self.bank.same_country_rate:.1f}%)\n\n"
                + _table(["기준 집단", "인원", "출생 국가 = 거주 국가"], check_rows)
                + "\n\n- indep: 합성 인원의 속성을 서로 독립으로 만든 현재 집단. joint: 같은 사람들의 출생 국가를 원본 비율에 맞춰 "
                  "거주 국가로 바꾼 비교용 집단.")

    def _miss(self) -> str:
        rows, csv_rows = [], []
        for rate in self.s.miss_rates:
            units = [r for c in self.plan.groups["miss"] if c.miss_rate == rate for r in [self.results[c]]]
            rates = [stats.violation_rate(u) for u in units]
            retention = [stats.summarize(u)["retention"] for u in units]
            low, high = (np.percentile(rates, [2.5, 97.5]) if len(rates) > 1 else (rates[0], rates[0]))
            row = {"miss_rate": rate, "seeds": len(units), "violation_pct": 100 * mean(rates),
                   "low_pct": 100 * float(low), "high_pct": 100 * float(high), "retention_pct": 100 * mean(retention)}
            csv_rows.append(row)
            rows.append([f"{100 * rate:.0f}%", len(units), f"{row['violation_pct']:.1f}%",
                         f"{row['low_pct']:.0f}–{row['high_pct']:.0f}%", f"{row['retention_pct']:.1f}%"])
        self.miss_rows = csv_rows
        self.miss_reference = 100 * stats.violation_rate(self.main("C0"))
        self.files.append(_write_csv(self.out / "tables" / "sensitivity_miss.csv", csv_rows))
        return ("### 4.2 추출 누락\n\nDefender가 원래 답변의 관찰 중 일부를 보지 못했다고 가정했다. 못 본 값은 그대로 공개되고 "
                "공격자는 그것까지 본다. 비율마다 누락을 무작위로 정한 반복의 평균과 2.5–97.5 백분위다.\n\n"
                + _table(["누락 비율", "반복", "C1 위반 대상 (평균)", "반복 간 범위", "정보 유지율"], rows)
                + f"\n\n참고: 방어 없음(C0)의 위반 비율 = {self.miss_reference:.1f}%")

    def _generalization(self) -> str:
        csv_rows = []
        for condition in self.plan.groups["generalization"]:
            summary = stats.summarize(self.results[condition])
            csv_rows.append({"k_req": condition.k_req, "max_generalization": condition.max_generalization,
                             "violation_pct": 100 * summary["violation_rate"], "retention_pct": 100 * summary["retention"],
                             "worst_min_k": summary["worst_min_k"], "generalized": summary["generalized"],
                             "suppressed": summary["suppressed"]})
        self.generalization_rows = csv_rows
        self.files.append(_write_csv(self.out / "tables" / "sensitivity_generalization.csv", csv_rows))
        levels = list(dict.fromkeys(r["max_generalization"] for r in csv_rows))
        ks = list(dict.fromkeys(r["k_req"] for r in csv_rows))

        def name(g: int | None) -> str:
            return "제한 없음 (본 설정)" if g is None else ("0 (억제만)" if g == 0 else str(g))

        rows = []
        for g in levels:
            cells = [name(g)]
            for k in ks:
                r = next(x for x in csv_rows if x["max_generalization"] == g and x["k_req"] == k)
                cells.append(f"{r['retention_pct']:.1f}% / {_num(r['worst_min_k'])} / {r['generalized']}·{r['suppressed']}")
            rows.append(cells)
        return ("### 4.3 최대 일반화 단계\n\nDefender가 값을 한 단계씩 넓힐 수 있는 한도를 바꿨다. 칸마다 "
                "정보 유지율 / 최악 대상의 최소 k / 일반화·억제 횟수다.\n\n"
                + _table(["최대 단계"] + [f"운영 k_req {k}" for k in ks], rows)
                + "\n\n- 일반화가 억제보다 늘 정보를 더 남기는 것은 아니다. 앞 턴에서 넓혀서 남긴 값이 뒤 턴의 공개를 더 막을 수 "
                  "있기 때문이다 (경로 의존).")

    # ── 6. 표본 크기 ────────────────────────────────────

    def _stability(self) -> str:
        targets = len({d.target_id for d in self.dialogues})
        sizes = sorted({n for n in (3, 5, 10, 20, 30, 50, targets) if 2 <= n <= max(targets, 2)})
        result = stats.stability(self.main("C0"), self.main("C1"), sizes, resamples=min(self.s.resamples, 2000),
                                 seed=self.s.seed + 20)
        self.files.append(_write_csv(self.out / "tables" / "stability.csv", result))
        rows = [[r["targets"], f"{100 * r['mean_diff']:.1f}%", f"{100 * r['low']:.1f}% – {100 * r['high']:.1f}%",
                 f"{100 * r['width']:.1f}%p"] for r in result]
        return ("## 5. 대상 수에 따른 추정의 안정성 (표 4)\n\n"
                f"지금 가진 {targets}명에서 n명을 복원 추출해 C0−C1 위반 비율 차이를 다시 계산했다. 구간 폭이 줄어드는 정도로 "
                "대상을 몇 명까지 늘려야 하는지 가늠한다. 대상이 늘어난 뒤 다시 돌리면 실제 값으로 바뀐다.\n\n"
                + _table(["대상 수", "차이 평균", "95% 범위", "범위 폭"], rows))

    # ── 7. 실사용 부담 ──────────────────────────────────

    def _overhead(self) -> str:
        turns = [t for d in self.dialogues for t in d.turns]

        def avg(key: str) -> float:
            values = [t.usage.get(key, 0.0) for t in turns if t.usage.get(key)]
            return mean(values) if values else math.nan

        rewrite = [ms for d in self.dialogues for arm in ("C1",) for ms in (d.live.get(arm).rewrite_ms if d.live.get(arm) else ())
                   if ms]
        c1 = self.main("C1")
        defense_ms = mean([t.defense_ms for r in c1 for t in r.turns]) if c1 else math.nan
        intervene = stats.summarize(c1)["intervened_turns"] / max(1, stats.summarize(c1)["turns"])
        rewrite_ms = mean(rewrite) if rewrite else math.nan
        added = avg("extraction_ms") + defense_ms + intervene * ((rewrite_ms if rewrite else 0) + avg("extraction_ms"))
        rows = [
            ["대상 AI 응답 (방어와 무관)", _num(avg("target_ms")), _num(avg("target_in")), _num(avg("target_out"))],
            ["정보 추출 (매 턴, 방어에 필요)", _num(avg("extraction_ms")), _num(avg("extraction_in")), _num(avg("extraction_out"))],
            ["위험 계산·Defender 판단 (CPU)", _num(defense_ms, 1), "0", "0"],
            [f"재작성 (개입한 턴만, 실제 {len(rewrite)}회)", _num(rewrite_ms), "-", "-"],
        ]
        csv_rows = [{"stage": r[0], "latency_ms": r[1], "input_tokens": r[2], "output_tokens": r[3]} for r in rows]
        csv_rows.append({"stage": "추가 지연 추정 (턴당)", "latency_ms": _num(added), "input_tokens": "", "output_tokens": ""})
        self.files.append(_write_csv(self.out / "tables" / "overhead.csv", csv_rows))
        return ("## 6. 실사용 부담 (표 5)\n\n턴 하나의 평균 지연(ms)과 토큰. 실험에서 질문 생성(Fuzzer)은 공격자 쪽이므로 빼고, "
                "서비스에 붙였을 때 늘어나는 부분만 본다.\n\n"
                + _table(["단계", "지연 (ms)", "입력 토큰", "출력 토큰"], rows)
                + f"\n\n- 개입 비율 {_pct(intervene)}를 반영한 턴당 추가 지연 추정: 약 {_num(added)} ms "
                  f"(추출 + 판단 + 개입 비율 × (재작성 + 재추출)). 대상 AI 응답 시간 대비 "
                  f"{_pct(added / avg('target_ms')) if avg('target_ms') else '-'}.\n"
                  "- 재추출 지연은 기록되지 않아 추출 평균으로 대신했다.")

    # ── 8. 그림 ─────────────────────────────────────────

    def _figures(self) -> str:
        figure_dir = self.out / "figures"
        figure_dir.mkdir(parents=True, exist_ok=True)
        lang = figures.choose_language(self.lang)
        max_turn = max(len(d.turns) for d in self.dialogues)
        trajectories = {arm: stats.trajectory(self.main(arm)) for arm in ("C0", "C1S", "C1")}
        survivals = {arm: stats.survival(self.main(arm), max_turn) for arm in ("C0", "C1S", "C1")}
        self.files += figures.fig1(trajectories, survivals, self.s.eval_k, lang, figure_dir)
        self.files += figures.fig2(self.series, self.knee_point, self.s.eval_k, lang, figure_dir)
        self.files += figures.fig3(self.population_rows, self.miss_rows, self.miss_reference,
                                   self.generalization_rows, lang, figure_dir)
        return ("## 7. 그림\n\n"
                "- `figures/fig1_risk_trajectory` (a) 턴마다 남은 후보 수의 중앙값과 사분위 범위, 붉은 점선이 평가 기준. "
                "(b) 턴 t까지 한 번이라도 기준 아래로 내려간 대상의 비율.\n"
                "- `figures/fig2_privacy_utility` 가로 정보 유지율, 세로 위반 대상 비율. 왼쪽 아래가 아니라 **오른쪽 아래**가 "
                "좋은 방향(정보는 많이 남기고 위반은 적게)이다. 점 옆 숫자는 운영 k_req, 붉은 원은 무릎점.\n"
                "- `figures/fig3_sensitivity` (a) 기준 집단을 바꿨을 때 갈래별 위반 비율 (b) Defender가 관찰을 놓친 비율에 따른 "
                "누적 방어의 위반 비율 (c) 일반화 허용 단계에 따른 정보 유지율과 위반 비율.\n\n"
                "PNG(300dpi)와 PDF(벡터) 두 형식으로 저장했다.")

    # ── 9. 해석 시 주의 ─────────────────────────────────

    def _cautions(self) -> str:
        return ("## 8. 이 결과를 쓸 때 함께 적어야 할 가정\n\n"
                "1. **이상적 재작성 가정**: 조건을 바꾼 재계산에서는 Defender가 허용·일반화한 값만 공개된다고 본다. "
                "실제 재작성과의 차이는 1절의 일치율로 확인한다.\n"
                "2. **같은 원래 답변**: 모든 조건이 같은 질문과 같은 원래 답변을 쓴다 (짝 설계). 방어가 다음 질문을 바꾸는 효과는 "
                "이 분석 범위 밖이다.\n"
                "3. **추출기 의존**: 원래 답변에서 추출기가 놓친 단서는 어느 조건에서도 계산되지 않는다. 4.2절은 Defender 쪽 누락만 "
                "모의한 것이다.\n"
                "4. **합성 데이터와 기준 집단**: 대상·글·기준 집단이 모두 합성이며, k는 기준 집단 안의 후보 수일 뿐 실제 신원 확인을 "
                "뜻하지 않는다. 4.1절처럼 기준 집단의 구성에 따라 절대값이 크게 달라진다.\n"
                "5. **범위 밖**: 생성 전 규칙 주입(경량 언러닝, C2·C3)과 변형 재공격은 이 분석에 포함되지 않는다.")

    # ── 파일 ────────────────────────────────────────────

    def _per_unit_csv(self) -> None:
        rows = []
        for condition, units in self.results.items():
            for unit in units:
                summary = stats.summarize([unit])
                rows.append({"condition": condition.label, "population": condition.population,
                             "miss_rate": condition.miss_rate, "miss_seed": condition.miss_seed,
                             "unit": unit.unit, "target_id": unit.target_id,
                             "stratum": self.strata.get(unit.target_id, ""), "min_k_val": unit.min_k_val,
                             "violated": unit.violated, "first_violation": unit.first_violation or "",
                             "retention": summary["retention"], "intervened_turns": summary["intervened_turns"]})
        self.files.append(_write_csv(self.out / "tables" / "per_unit.csv", rows))
        turn_rows = [{"condition": c.label, "unit": u.unit, **asdict(t)}
                     for c in self.plan.groups["main"] for u in self.results[c] for t in u.turns]
        self.files.append(_write_csv(self.out / "tables" / "per_turn_main.csv", turn_rows))

    def _manifest(self) -> None:
        def git(*args: str) -> str | None:
            try:
                return subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True,
                                      check=True).stdout.strip()
            except (OSError, subprocess.CalledProcessError):
                return None

        master = self.bank.master
        inputs = {}
        for run in self.runs:
            trace = Path(run.config.get("_run_dir", "")) / "trace.jsonl" if run.config.get("_run_dir") else None
            if trace and trace.exists():
                inputs[f"{run.run_id}/trace.jsonl"] = file_sha256(trace)
        for label, path in (("population_base", master.base_path), ("population_synth", master.synth_path)):
            if path and Path(path).exists():
                inputs[label] = file_sha256(path)
        alias = PROJECT_ROOT / "ontology" / "data"
        for path in sorted(alias.glob("*")) if alias.exists() else ():
            if path.is_file():
                inputs[f"ontology/data/{path.name}"] = file_sha256(path)
        manifest = {
            "created_at": datetime.now(KST).isoformat(),
            "git": {"commit": git("rev-parse", "HEAD"), "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
                    "dirty": bool(git("status", "--porcelain"))},
            "settings": self.s.to_dict(),
            "runs": [{"run_id": r.run_id, "lead_arm": r.lead_arm, "arms": list(r.arms), "k_req": r.k_req,
                      "population": r.population,
                      "model": r.config.get("model"), "prompts": r.config.get("prompts"),
                      "temperature": r.config.get("temperature")} for r in self.runs],
            "units": [d.unit for d in self.dialogues],
            "populations": {name: {"size": self.bank.index(name).size, "fingerprint": self.bank.fingerprint(name)}
                            for name in self.s.populations},
            "same_country_rate_original": self.bank.same_country_rate,
            "inputs_sha256": inputs,
            "environment": {"python": platform.python_version(), "numpy": np.__version__,
                            "matplotlib": matplotlib.__version__},
            "outputs_sha256": {str(p.relative_to(self.out)): file_sha256(p) for p in self.files
                               if p.exists() and p.suffix != ".pdf"},
            "llm_calls": 0,
        }
        path = self.out / "manifest.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
