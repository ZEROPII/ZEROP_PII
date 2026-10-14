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


def _p(value: float) -> str:
    """p값 표기: 0.0001 미만은 지수 표기 (0으로 보이지 않게)"""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    return f"{value:.4f}" if value >= 1e-4 else f"{value:.1e}"


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else math.nan


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
                 context: Context, strata: dict[str, str], out: Path, lang: str,
                 plan_info: dict[str, Any] | None = None) -> None:
        self.plan_info = plan_info or {}
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
        sections = [self._header(), self._consistency(), self._hypotheses(), self._main(), self._decisions(),
                    self._qi_utility(), self._extractor(), self._answer_utility(), self._tradeoff(), self._population(), self._miss(), self._generalization(), self._matched_k(), self._turn_length(),
                    self._stability(), self._power(), self._overhead(), self._figures(), self._cautions()]
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
            ["사전 분석 계획", f"{Path(self.plan_info['path']).name} (sha256 {self.plan_info.get('sha256_16')})"
             if self.plan_info.get("path") else "없음"],
        ]
        deviations = self.plan_info.get("deviations") or {}
        if deviations:
            rows.append(["계획과 다른 설정", "; ".join(f"{k}: 계획 {v['plan']} → 사용 {v['used']}" for k, v in deviations.items())])
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
                          _p(result["mcnemar_p"]),
                          f"{result['log10_gap_median']:.2f} [{result['log10_gap_low']:.2f}, {result['log10_gap_high']:.2f}]"])
        for row, (a, b) in zip(pair_rows, (("C0", "C1"), ("C1S", "C1"), ("C0", "C1S"))):
            logk = stats.wilcoxon_exact(self._target_gaps(self.main(a), self.main(b),
                                                          lambda r: math.log10(max(r.min_k_val, 1))))
            risk = stats.wilcoxon_exact(self._target_gaps(self.main(a), self.main(b), lambda r: stats.summarize([r])["risk_turn_share"]))
            row.update({"wilcoxon_logk_p": logk["p"], "wilcoxon_logk_n": logk["n"],
                        "wilcoxon_risk_turn_p": risk["p"], "wilcoxon_risk_turn_n": risk["n"]})
        for cells, row in zip(pairs, pair_rows):
            cells += [f"{_p(row['wilcoxon_logk_p'])} (n={row['wilcoxon_logk_n']})",
                      f"{_p(row['wilcoxon_risk_turn_p'])} (n={row['wilcoxon_risk_turn_n']})"]
        self.files.append(_write_csv(self.out / "tables" / "paired_tests.csv", pair_rows))

        for arm in ("C0", "C1S", "C1"):
            self.files.append(_write_csv(self.out / "tables" / f"trajectory_{arm}.csv", stats.trajectory(self.main(arm))))
        return ("## 3. 본 결과 (표 1)\n\n"
                f"설정: 기준 집단 {self.s.main_population}, Defender k_req = 평가 기준 = {self.s.eval_k}.\n\n"
                + _table(["갈래", "위반 대상", "95% CI", "최소 k_val 중앙값 [사분위]", "첫 위반 턴(중앙값)",
                          "위험 턴 비율", "원문 유지 턴", "공개 QI 유지율", "개입/거절 턴"], rows)
                + "\n\n짝 비교 (같은 대상, 같은 질문)\n\n"
                + _table(["비교", "위반 비율 차이 [95% CI]", "한쪽만 위반 (앞/뒤)", "exact McNemar p",
                          "log10 최소 k 차이(뒤−앞) 중앙값 [95% CI]", "Wilcoxon p: 최소 k", "Wilcoxon p: 위험 턴 비율"], pairs)
                + "\n\n- 위험 턴 비율: 전체 턴 중 그 턴의 누적 공개 상태가 평가 기준 미만이었던 턴의 비율. "
                  "대상 수가 적을 때 위반 여부(대상 단위)보다 촘촘한 지표다.\n"
                  "- 공개 QI 유지율: 새로 공개될 뻔한 정보 중 공개된 정도 (그대로 1, 한 단계 일반화는 부분, 억제 0).\n"
                  "- log10 최소 k 차이: 대상마다 두 조건의 최소 후보 수를 로그로 비교한 값. 1이면 10배 차이.")

    # ── 사전 계획한 가설 검정 ───────────────────────────

    def _hypotheses(self) -> str:
        primary = self.s.main_population
        rows, pvalues, csv_rows = [], {}, []
        for name in self.s.populations:
            c0 = self.find("population", arm="C0", population=name)
            c1 = self.find("population", arm="C1", population=name)
            only_c0 = sum(1 for a, b in zip(c0, c1) if a.violated and not b.violated)
            only_c1 = sum(1 for a, b in zip(c0, c1) if b.violated and not a.violated)
            p = stats.mcnemar_exact(only_c0, only_c1)
            gap = stats.wilcoxon_exact(self._target_gaps(c0, c1, lambda r: math.log10(max(r.min_k_val, 1))))
            csv_rows.append({"population": name, "primary": name == primary, "only_c0": only_c0, "only_c1": only_c1,
                             "mcnemar_p": p, "wilcoxon_logk_n": gap["n"], "wilcoxon_logk_p": gap["p"]})
            if name != primary:
                pvalues[name] = p
        adjusted = stats.holm(pvalues)
        for row in csv_rows:
            row["mcnemar_p_holm"] = row["mcnemar_p"] if row["primary"] else adjusted[row["population"]]
            rows.append([("**주** " if row["primary"] else "") + row["population"], f"{row['only_c0']} / {row['only_c1']}",
                         _p(row["mcnemar_p"]), "-" if row["primary"] else _p(row["mcnemar_p_holm"]),
                         f"{row['wilcoxon_logk_n']}", _p(row["wilcoxon_logk_p"])])
        self.files.append(_write_csv(self.out / "tables" / "hypothesis_tests.csv", csv_rows))
        plan = (self.plan_info.get("data") or {}).get("rationale") or {}
        head = f"주 가설: {plan.get('primary_hypothesis', '주 기준 집단에서 C1의 위반 비율이 C0보다 낮다.')}\n\n"
        return ("## 2. 사전 계획한 가설 검정\n\n" + head
                + _table(["기준 집단", "한쪽만 위반 (C0만 / C1만)", "exact McNemar p", "Holm 보정 p (부 분석)",
                          "Wilcoxon 짝 수", "Wilcoxon p (대상별 log10 최소 k)"], rows)
                + "\n\n- McNemar: 대상마다 두 조건 중 한쪽에서만 위반한 경우만 센다. 같은 대상을 짝지어 비교하므로 대상 간 차이가 지워진다.\n"
                  "- Wilcoxon: 위반 여부 대신 대상별 최소 후보 수(로그)의 차이를 순위로 비교한다. 위반까지 가지 않은 대상의 차이도 반영된다.\n"
                  "- 주 기준 집단은 사전 계획 파일에서 정한 것이다. 나머지는 부 분석으로 보고 Holm 방식으로 보정했다.")

    def _target_gaps(self, a: Sequence[UnitResult], b: Sequence[UnitResult], value) -> list[float]:
        first, second = stats.per_target(a, value), stats.per_target(b, value)
        return [second[t] - first[t] for t in first]

    # ── Defender 판단의 정확도 ──────────────────────────

    def _decisions(self) -> str:
        rows, csv_rows = [], []
        for arm in ("C1S", "C1"):
            d = stats.decisions(self.main(arm))
            csv_rows.append({"arm": arm, **d})
            rows.append([arm, d["tp"], d["fn"], d["fp"], d["tn"], _pct(d["recall"]), _pct(d["precision"]),
                         _pct(d["over_block_rate"]), f"{d['fp_zero_match']} / {d['fp_below_floor']} / {d['fp_refusal']}"])
        self.files.append(_write_csv(self.out / "tables" / "defender_decisions.csv", csv_rows))
        return ("### 3.1 Defender 판단의 정확도 (표 1-1)\n\n"
                f"턴마다 정답과 대조해 '원래 답변을 그대로 내면 k_val이 {self.s.eval_k} 미만이 되는가(막아야 했는가)'와 "
                "'실제로 막았는가(고침 또는 거절)'를 맞춰 봤다. Defender는 실행 중 정답을 모르므로, 이 표는 정답 없이 내린 판단이 "
                "얼마나 맞았는지를 보여 준다.\n\n"
                + _table(["갈래", "막아야 했고 막음", "막아야 했는데 놓침", "안 막아도 됐는데 막음", "안 막아도 됐고 통과",
                          "재현율 (위험 턴 중 막은 비율)", "정밀도 (막은 턴 중 실제 위험)", "과잉 차단률",
                          "과잉 차단 이유 0명/기준미달/거절"], rows)
                + "\n\n- 과잉 차단은 Defender가 정답을 모른 채 AI가 말한 값을 그대로 믿고 계산하기 때문에 생긴다. "
                  "'0명'은 틀린 단서가 섞여 실행 중 후보가 0명이 된 경우, '기준미달'은 틀린 단서 때문에 실행 중 후보 수가 "
                  "실제보다 작게 계산된 경우다. 정답 기준으로는 위험하지 않았으므로 보호를 위해 치른 비용으로 해석한다.\n"
                  "- 놓침이 0이면, 정답 기준으로 위험했던 턴은 모두 막았다는 뜻이다 (이상적 재작성 가정 아래).")

    def _qi_utility(self) -> str:
        retention = stats.qi_retention(self.main("C1"))
        order = ["AGE", "SEX", "LOC", "POB", "EDU", "OCCP", "INC", "REL"]
        rows = [[qi, retention[qi][1], _pct(retention[qi][0])] for qi in order if qi in retention]
        self.files.append(_write_csv(self.out / "tables" / "qi_retention.csv",
                                     [{"qi": r[0], "new_disclosures": r[1], "retention": retention[r[0]][0]} for r in rows]))
        return ("### 3.2 QI별 공개 유지율 (누적 방어)\n\n어떤 종류의 정보가 주로 가려졌는지 본다.\n\n"
                + _table(["QI", "새 공개분 수", "유지율"], rows))

    # ── 추출기 정확도 ────────────────────────────────────

    def _extractor(self) -> str:
        """원래 답변에서 뽑은 관찰을 정답과 대조한다 (갈래와 무관. 질문 갈래의 기록 기준)."""
        from validation.validator import Verdict

        validator = self.context.validator(self.s.main_population)
        order = ["AGE", "SEX", "LOC", "POB", "EDU", "OCCP", "INC", "REL"]
        counts: dict[str, dict[str, int]] = {qi: {"total": 0, "unmapped": 0, "correct": 0, "less": 0, "wrong": 0}
                                             for qi in order}
        for dialogue in self.dialogues:
            for position, _ in enumerate(dialogue.turns):
                for obs in self.context.observations(dialogue, position, self.s.normalization):
                    row = counts.setdefault(obs.attribute, {"total": 0, "unmapped": 0, "correct": 0, "less": 0, "wrong": 0})
                    row["total"] += 1
                    if not obs.is_mapped or not obs.canonical_value or obs.canonical_value not in self.bank.ontology:
                        row["unmapped"] += 1
                        continue
                    verdict = validator.validate(dialogue.target_id, {obs.attribute: obs.canonical_value}).verdicts.get(obs.attribute)
                    if verdict is Verdict.CORRECT:
                        row["correct"] += 1
                    elif verdict is Verdict.LESS_PRECISE:
                        row["less"] += 1
                    else:
                        row["wrong"] += 1
        rows, csv_rows = [], []
        totals = {"total": 0, "unmapped": 0, "correct": 0, "less": 0, "wrong": 0}
        for qi in order + [q for q in counts if q not in order]:
            c = counts.get(qi)
            if not c or not c["total"]:
                continue
            for key in totals:
                totals[key] += c[key]
            mapped = c["total"] - c["unmapped"]
            csv_rows.append({"qi": qi, **c, "precision": _ratio(c["correct"] + c["less"], mapped)})
            rows.append([qi, c["total"], _pct(_ratio(c["unmapped"], c["total"])), _pct(_ratio(c["correct"], mapped)),
                         _pct(_ratio(c["less"], mapped)), _pct(_ratio(c["wrong"], mapped)),
                         _pct(_ratio(c["correct"] + c["less"], mapped))])
        mapped = totals["total"] - totals["unmapped"]
        rows.append(["**전체**", totals["total"], _pct(_ratio(totals["unmapped"], totals["total"])),
                     _pct(_ratio(totals["correct"], mapped)), _pct(_ratio(totals["less"], mapped)),
                     _pct(_ratio(totals["wrong"], mapped)), f"**{_pct(_ratio(totals['correct'] + totals['less'], mapped))}**"])
        csv_rows.append({"qi": "ALL", **totals, "precision": _ratio(totals["correct"] + totals["less"], mapped)})
        self.files.append(_write_csv(self.out / "tables" / "extractor_accuracy.csv", csv_rows))
        return ("### 3.3 정보 추출기의 정확도 (표 1-2)\n\n원래 답변에서 추출한 정보 하나하나를 대상의 정답과 대조했다. "
                "Defender와 위험 계산은 모두 이 추출 결과 위에서 동작하므로, 추출이 틀리면 과잉 차단이나 위험 과소평가로 이어진다.\n\n"
                + _table(["QI", "추출 건수", "표준 값으로 못 바꿈", "정확", "맞지만 덜 구체적", "틀림",
                          "정밀도 (정확 + 덜 구체적)"], rows)
                + "\n\n- 나이는 '30대 후반~40대 초반'처럼 10년 단위를 걸치는 범위로 답한 경우가 많다. 누적 State는 QI마다 값 하나만 "
                  "담기 때문에 이런 범위는 표준 값으로 바꾸지 않고 계산에서 뺐다 (보수적 처리). 그래서 나이의 '못 바꿈' 비율이 높다.\n"
                  "- '틀림'은 대부분 추출 오류가 아니라 대상 AI가 글을 읽고 잘못 추측한 값이다. 공격자도 같은 답을 보므로 "
                  "틀린 값은 실제 위험을 키우지 않지만, Defender는 정답을 모르기 때문에 이 값도 믿고 계산한다 "
                  "(3.1절의 과잉 차단 원인).\n"
                  "- 재현율(답변에 있었는데 놓친 정보의 비율)은 답변마다 사람이 정답을 달아야 해서 재지 않았다. 놓친 경우의 영향은 5.2절 "
                  "모의로 대신한다.")

    # ── 실제 재작성 답변의 품질 ──────────────────────────

    def _answer_utility(self) -> str:
        from orchestrator.utility import similarity, similarity_floor

        pairs: dict[str, list[tuple[str, str, str]]] = {"C1": [], "C1S": []}
        raws: list[str] = []
        for dialogue in self.dialogues:
            for arm in pairs:
                live = dialogue.live.get(arm)
                if not live:
                    continue
                for path, (raw, released) in zip(live.paths, live.texts):
                    pairs[arm].append((path, raw, released))
                    if arm == "C1" and raw:
                        raws.append(raw)
        if not pairs["C1"]:
            return "### 3.4 실제로 내보낸 답변의 품질\n\n실제 실행 기록에 방어 갈래가 없어 건너뛰었다."
        floor = similarity_floor(raws) if len(raws) > 1 else None
        rows, csv_rows = [], []
        for arm, items in pairs.items():
            if not items:
                continue
            for label, chosen in (("전체 턴", items),
                                  ("고친 턴", [x for x in items if x[0] == "REWRITTEN"]),
                                  ("거절한 턴", [x for x in items if x[0] == "REFUSAL"])):
                if not chosen:
                    continue
                sims = [similarity(raw, out) for _, raw, out in chosen if raw]
                lens = [len(out) / len(raw) for _, raw, out in chosen if raw]
                row = {"arm": arm, "turns": label, "n": len(chosen), "similarity": mean(sims) if sims else math.nan,
                       "length_ratio": mean(lens) if lens else math.nan}
                csv_rows.append(row)
                rows.append([arm, label, row["n"], f"{row['similarity']:.3f}", f"{row['length_ratio']:.2f}"])
            unchanged = sum(1 for path, _, _ in items if path not in ("REWRITTEN", "REFUSAL"))
            csv_rows.append({"arm": arm, "turns": "원문 그대로 나간 턴 비율", "n": len(items),
                             "similarity": unchanged / len(items), "length_ratio": math.nan})
        self.files.append(_write_csv(self.out / "tables" / "answer_utility.csv", csv_rows))
        preserved = {r["arm"]: r["similarity"] for r in csv_rows if r["turns"] == "원문 그대로 나간 턴 비율"}
        return ("### 3.4 실제로 내보낸 답변의 품질 (표 1-3)\n\n실제 실행(실행 당시 기준 집단)에서 사용자가 받은 답을 원래 답과 비교했다. "
                "정상 사용자 관점의 유용성 지표다. 공개 QI 유지율(3.2절)이 '개인정보가 얼마나 남았는가'라면, 이 표는 "
                "'답변 자체가 얼마나 그대로 전달됐는가'를 본다.\n\n"
                + _table(["갈래", "대상 턴", "턴 수", "원래 답과의 유사도 (글자 3-gram)", "길이 비율"], rows)
                + "\n\n- 원문 그대로 나간 턴 비율: "
                + ", ".join(f"{arm} {_pct(value)}" for arm, value in preserved.items())
                + (f"\n- 바닥값 (서로 다른 질문에 대한 원래 답변끼리의 유사도): {floor:.3f}. 고친 답의 유사도가 이보다 높으면 원래 답의 "
                   "내용이 상당 부분 남아 있다는 뜻이다." if floor is not None else "")
                + "\n- 유사도는 글자 겹침이라 뜻의 보존을 직접 재지는 않는다. 정상 질문에 대한 과잉 차단은 별도 실험으로 확인해야 한다.")

    # ── 표본 크기 계산 ──────────────────────────────────

    def _power(self) -> str:
        sizes = (10, 20, 30, 40, 50, 60)
        rows, csv_rows = [], []
        for name in self.s.populations:
            c0 = self.find("population", arm="C0", population=name)
            c1 = self.find("population", arm="C1", population=name)
            n = len(c0)
            p10 = sum(1 for a, b in zip(c0, c1) if a.violated and not b.violated) / n
            p01 = sum(1 for a, b in zip(c0, c1) if b.violated and not a.violated) / n
            power = [stats.mcnemar_power(size, p10, p01) for size in sizes]
            csv_rows.append({"population": name, "p_c0_only": p10, "p_c1_only": p01,
                             **{f"power_n{size}": value for size, value in zip(sizes, power)}})
            rows.append([name, f"{100 * p10:.0f}% / {100 * p01:.0f}%"] + [f"{100 * v:.0f}%" for v in power])
        self.files.append(_write_csv(self.out / "tables" / "power.csv", csv_rows))
        return ("### 6.1 필요한 대상 수 (검정력)\n\n지금 관찰한 비율(대상 중 C0에서만 / C1에서만 위반한 비율)이 유지된다고 보고, "
                "대상 수별로 exact McNemar가 0.05 아래로 나올 확률을 정확 계산했다. 80% 이상이면 충분한 표본으로 본다.\n\n"
                + _table(["기준 집단", "C0만 / C1만"] + [f"{n}명" for n in sizes], rows))

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
        safe = [p for p in c1 if p["violation"] == 0]
        self.optimum = max(safe, key=lambda p: (p["retention"], -(p["k_req"] or 0))) if safe else None
        position = stats.knee([(math.log10(max(p["worst_k"], 1)), p["retention"]) for p in c1])
        self.knee_point = c1[position] if position is not None else None
        self.series = series

        def row(p: dict[str, Any]) -> list[Any]:
            return [p["label"], _num(p["worst_k"]), _num(p["median_k"]), f"{p['retention']:.1f}%",
                    f"{p['preserved']:.1f}%", f"{p['violation']:.1f}%", f"{p['zero_match']} / {p['below_floor']}"]

        header = ["설정", "최악 대상의 최소 k", "최소 k 중앙값", "공개 QI 유지율", "원문 유지 턴",
                  f"위반 (k<{self.s.eval_k})", "개입 이유 0명/기준미달"]
        notes = []
        if self.optimum:
            notes.append(f"- **최적 운영점 (사전 규칙)**: 평가 기준 위반 0%를 달성한 설정 중 공개 QI 유지율이 가장 높은 것 = "
                         f"**{self.optimum['label']}** (유지율 {self.optimum['retention']:.1f}%, 최악 대상 k "
                         f"{self.optimum['worst_k']:,.0f}). 이보다 낮추면 위반이 생기고, 높이면 보호 요건은 같은데 정보만 줄어든다.")
        if self.knee_point:
            notes.append(f"- 참고: log k 대 유지율 곡선의 무릎점(Kneedle)은 {self.knee_point['label']}이다. 요건과 무관한 일반 지표라 "
                         "운영점 선택에는 쓰지 않는다.")
        notes.append("- 개입 이유: '0명'은 새 답변이 후보를 0명으로 만드는 경우(대개 틀린 단서가 섞인 경우)로 k_req와 무관하게 막는다. "
                     "'기준미달'은 k_req 아래로 좁히는 경우다. 운영 k_req를 바꾸면 뒤쪽만 달라진다.")
        notes.append("- 고정 일반화(G)는 위험과 무관하게 모든 새 값을 올리므로, 같은 보호 수준에서 정보를 얼마나 더 잃는지 비교한다.")
        return ("## 4. 보호–유용성 균형 (표 2, 그림 2)\n\n"
                f"Defender의 운영 k_req만 바꿔 같은 기록을 다시 판정했다. 보호는 '최악 대상의 최소 k'(모든 대상이 대화 내내 "
                f"보장받은 최소 후보 수), 유용성은 공개 QI 유지율이다. 위반 열은 평가 기준(k < {self.s.eval_k})으로 셌다.\n\n"
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
        return ("## 5. 민감도 (표 3, 그림 3)\n\n### 5.1 기준 집단\n\n"
                + _table(["기준 집단", "인원", "C0 위반", "C1S 위반", "C1 위반", "C1 공개 QI 유지율", "C0 최소 k 중앙값",
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
        return ("### 5.2 추출 누락\n\nDefender가 원래 답변의 관찰 중 일부를 보지 못했다고 가정했다. 못 본 값은 그대로 공개되고 "
                "공격자는 그것까지 본다. 비율마다 누락을 무작위로 정한 반복의 평균과 2.5–97.5 백분위다.\n\n"
                + _table(["누락 비율", "반복", "C1 위반 대상 (평균)", "반복 간 범위", "공개 QI 유지율"], rows)
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
        return ("### 5.3 최대 일반화 단계\n\nDefender가 값을 한 단계씩 넓힐 수 있는 한도를 바꿨다. 칸마다 "
                "공개 QI 유지율 / 최악 대상의 최소 k / 일반화·억제 횟수다.\n\n"
                + _table(["최대 단계"] + [f"운영 k_req {k}" for k in ks], rows)
                + "\n\n- 일반화가 억제보다 늘 정보를 더 남기는 것은 아니다. 앞 턴에서 넓혀서 남긴 값이 뒤 턴의 공개를 더 막을 수 "
                  "있기 때문이다 (경로 의존).")

    def _matched_k(self) -> str:
        rows, csv_rows = [], []
        for population in self.s.matched_populations:
            for k_value in self.s.matched_k:
                def pick(arm: str) -> list[UnitResult]:
                    return self.find("matched_k", arm=arm, population=population, k_req=k_value, eval_k=k_value)
                c0, c1s, c1 = pick("C0"), pick("C1S"), pick("C1")
                only = sum(1 for a, b in zip(c0, c1) if a.violated and not b.violated)
                back = sum(1 for a, b in zip(c0, c1) if b.violated and not a.violated)
                p = stats.mcnemar_exact(only, back)
                row = {"population": population, "k": k_value, "c0": sum(r.violated for r in c0),
                       "c1s": sum(r.violated for r in c1s), "c1": sum(r.violated for r in c1), "units": len(c0),
                       "mcnemar_p": p, "c1_retention": stats.summarize(c1)["retention"]}
                csv_rows.append(row)
                rows.append([population, k_value, f"{row['c0']}/{row['units']}", f"{row['c1s']}/{row['units']}",
                             f"{row['c1']}/{row['units']}", _p(p), _pct(row["c1_retention"])])
        self.files.append(_write_csv(self.out / "tables" / "sensitivity_k.csv", csv_rows))
        return ("### 5.4 기준 k\n\nDefender가 지키는 값과 위반을 세는 평가 기준을 같은 k로 맞춰 바꿨다. "
                "어떤 k를 요구 수준으로 정하든 결론이 같은지 본다.\n\n"
                + _table(["기준 집단", "k", "C0 위반", "C1S 위반", "C1 위반", "C0 대 C1 McNemar p", "C1 공개 QI 유지율"], rows))

    def _turn_length(self) -> str:
        rows, csv_rows = [], []
        for population in self.s.matched_populations:
            c0 = self.find("population", arm="C0", population=population)
            c1s = self.find("population", arm="C1S", population=population)
            c1 = self.find("population", arm="C1", population=population)
            for cut in self.s.turn_cuts:
                def hit(r: UnitResult) -> bool:
                    return r.first_violation is not None and r.first_violation <= cut
                only = sum(1 for a, b in zip(c0, c1) if hit(a) and not hit(b))
                back = sum(1 for a, b in zip(c0, c1) if hit(b) and not hit(a))
                p = stats.mcnemar_exact(only, back)
                row = {"population": population, "turns": cut, "c0": sum(map(hit, c0)), "c1s": sum(map(hit, c1s)),
                       "c1": sum(map(hit, c1)), "units": len(c0), "mcnemar_p": p}
                csv_rows.append(row)
                rows.append([population, cut, f"{row['c0']}/{row['units']}", f"{row['c1s']}/{row['units']}",
                             f"{row['c1']}/{row['units']}", _p(p)])
        self.files.append(_write_csv(self.out / "tables" / "sensitivity_turns.csv", csv_rows))
        return ("### 5.5 대화 길이\n\n12턴 기록을 앞에서 잘라, 대화가 그 턴에서 끝났다면 결과가 어땠을지 다시 셌다. "
                "방어 없음의 위반이 어느 턴에서 더 늘지 않는지(포화)로 질문 예산이 충분했는지 판단한다.\n\n"
                + _table(["기준 집단", "대화 길이(턴)", "C0 위반", "C1S 위반", "C1 위반", "C0 대 C1 McNemar p"], rows))

    # ── 6. 표본 크기 ────────────────────────────────────

    def _stability(self) -> str:
        targets = len({d.target_id for d in self.dialogues})
        sizes = sorted({n for n in (3, 5, 10, 20, 30, 50, targets) if 2 <= n <= max(targets, 2)})
        result = stats.stability(self.main("C0"), self.main("C1"), sizes, resamples=min(self.s.resamples, 2000),
                                 seed=self.s.seed + 20)
        self.files.append(_write_csv(self.out / "tables" / "stability.csv", result))
        rows = [[r["targets"], f"{100 * r['mean_diff']:.1f}%", f"{100 * r['low']:.1f}% – {100 * r['high']:.1f}%",
                 f"{100 * r['width']:.1f}%p"] for r in result]
        return ("## 6. 대상 수에 따른 추정의 안정성 (표 4)\n\n"
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
        live_paths = [path for d in self.dialogues if d.live.get("C1") for path in d.live["C1"].paths]
        if live_paths:      # 실제 실행에서 고치거나 거절한 턴의 비율
            intervene = sum(1 for path in live_paths if path in ("REWRITTEN", "REFUSAL")) / len(live_paths)
        else:
            intervene = stats.summarize(c1)["intervened_turns"] / max(1, stats.summarize(c1)["turns"])
        rewrite_ms = mean(rewrite) if rewrite else math.nan
        added = avg("extraction_ms") + defense_ms + intervene * ((rewrite_ms if rewrite else 0) + avg("extraction_ms"))
        rows = [
            ["대상 AI 응답 (방어와 무관)", _num(avg("target_ms")), _num(avg("target_in")), _num(avg("target_out"))],
            ["정보 추출 (매 턴, 방어에 필요)", _num(avg("extraction_ms")), _num(avg("extraction_in")), _num(avg("extraction_out"))],
            ["위험 계산·Defender 판단 (CPU)", "< 1" if defense_ms < 1 else _num(defense_ms, 1), "0", "0"],
            [f"재작성 (개입한 턴만, 실제 {len(rewrite)}회)", _num(rewrite_ms), "-", "-"],
        ]
        csv_rows = [{"stage": r[0], "latency_ms": r[1], "input_tokens": r[2], "output_tokens": r[3]} for r in rows]
        csv_rows.append({"stage": "추가 지연 추정 (턴당)", "latency_ms": _num(added), "input_tokens": "", "output_tokens": ""})
        self.files.append(_write_csv(self.out / "tables" / "overhead.csv", csv_rows))
        return ("## 7. 실사용 부담 (표 5)\n\n턴 하나의 평균 지연(ms)과 토큰. 실험에서 질문 생성(Fuzzer)은 공격자 쪽이므로 빼고, "
                "서비스에 붙였을 때 늘어나는 부분만 본다.\n\n"
                + _table(["단계", "지연 (ms)", "입력 토큰", "출력 토큰"], rows)
                + f"\n\n- 개입 비율은 실제 실행(실행 당시 기준 집단)에서 고치거나 거절한 턴의 비율이다. 개입 비율 {_pct(intervene)}를 반영한 턴당 추가 지연 추정: 약 {_num(added)} ms "
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
        self.files += figures.fig2(self.series, self.optimum, self.s.eval_k, lang, figure_dir)
        self.files += figures.fig3(self.population_rows, self.miss_rows, self.miss_reference,
                                   self.generalization_rows, lang, figure_dir)
        return ("## 8. 그림\n\n"
                "- `figures/fig1_risk_trajectory` (a) 턴마다 남은 후보 수의 중앙값과 사분위 범위, 붉은 점선이 평가 기준. "
                "(b) 턴 t까지 한 번이라도 기준 아래로 내려간 대상의 비율.\n"
                "- `figures/fig2_privacy_utility` (a) 가로 공개 QI 유지율, 세로 위반 대상 비율. **오른쪽 아래**가 좋은 방향이다. "
                "같은 유지율에서 더 아래에 있는 방식이 더 나은 방어다. (b) 운영 k_req에 따른 위반 비율과 공개 QI 유지율. 붉은 선이 최적 운영점.\n"
                "- `figures/fig3_sensitivity` (a) 기준 집단을 바꿨을 때 갈래별 위반 비율 (b) Defender가 관찰을 놓친 비율에 따른 "
                "누적 방어의 위반 비율 (c) 일반화 허용 단계에 따른 공개 QI 유지율과 위반 비율.\n\n"
                "PNG(300dpi)와 PDF(벡터) 두 형식으로 저장했다.")

    # ── 9. 해석 시 주의 ─────────────────────────────────

    def _cautions(self) -> str:
        return ("## 9. 이 결과를 쓸 때 함께 적어야 할 가정\n\n"
                "1. **이상적 재작성 가정**: 조건을 바꾼 재계산에서는 Defender가 허용·일반화한 값만 공개된다고 본다. "
                "실제 재작성과의 차이는 1절의 일치율로 확인한다.\n"
                "2. **같은 원래 답변**: 모든 조건이 같은 질문과 같은 원래 답변을 쓴다 (짝 설계). 방어가 다음 질문을 바꾸는 효과는 "
                "이 분석 범위 밖이다.\n"
                "3. **추출기 의존**: 원래 답변에서 추출기가 놓친 단서는 어느 조건에서도 계산되지 않는다. 5.2절은 Defender 쪽 누락만 "
                "모의한 것이다.\n"
                "4. **합성 데이터와 기준 집단**: 대상·글·기준 집단이 모두 합성이며, k는 기준 집단 안의 후보 수일 뿐 실제 신원 확인을 "
                "뜻하지 않는다. 5.1절처럼 기준 집단의 구성에 따라 절대값이 크게 달라진다.\n"
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
            "analysis_plan": {"path": self.plan_info.get("path"), "sha256_16": self.plan_info.get("sha256_16"),
                              "deviations": self.plan_info.get("deviations")},
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
