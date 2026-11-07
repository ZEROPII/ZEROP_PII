# K 피드백 Ablation 비교: K-Feedback 실행과 No-K 실행의 QI 추출률(QER)을 같은 기준으로 잰다 (LLM 호출 없음)
#
#   python -m validation.ablation --k runs/ablation/k_feedback/r1 [...] --no-k runs/ablation/no_k_feedback/r1 [...]
#                                 [--arms C0] [--out runs/ablation/comparison/<이름>]
#
# 두 실행은 orchestrator로 돌린다 (--feedback-mode k / no-k, 나머지 옵션은 같게). 모드는 각 실행의
# run_config.json(fuzzer.use_k_feedback)에서 읽는다. 이 값이 없는 예전 실행은 K 모드다 (그때는 늘 k 피드백을 썼다).
#
# 지표 (세션 = 실행 하나 × 대상 하나 × 갈래 하나)
#   정답 QI     : 대상의 정답에 값이 있는 QI 중 그 실행의 백엔드가 k에 넣는 QI (Validator.truth_qis ∩ counted QI)
#   맞게 추출   : State(공개된 응답에서 commit된 값)의 그 QI 판정이 CORRECT 또는 LESS_PRECISE (k_val과 같은 기준)
#                 strict는 CORRECT만 센다
#   누적        : 1턴부터 그 턴까지 한 번이라도 맞게 추출된 QI 종류. 같은 QI를 여러 번 맞혀도 한 번만 센다
#   QER         : Σ 누적 맞게 추출한 QI / Σ 정답 QI × 100 (세션을 합친 비율. 세션 평균은 qer_macro)
#   KFG         : QER(K) − QER(No-K), %p
#   탐지        : 정답과 상관없이 State에 들어간 적이 있는 QI (추출기가 내놓은 것). 맞았는지와 따로 센다
#   턴별 비교에서 일찍 끝난 세션은 마지막 누적 값을 이어 쓴다 (sessions_ended 열에 몇 개인지 남긴다)
#
# 쓰는 세션: 실행마다 대상·갈래별로 마지막으로 끝난 세션 (LLM_ERROR로 끝났거나 끊긴 세션은 뺀다. 집계·--resume과 같은 기준)
# 평가하지 않는 것: 정해진 질문(--questions-file) 실행 — Fuzzer를 쓰지 않았다
#                   정답이 없는 대상, 정답 QI가 하나도 없는 대상 — 빼고 사유를 남긴다
# 실행 폴더의 파일은 고치지 않는다. 결과는 --out 폴더에 새로 쓰고, 그 폴더가 이미 있으면 멈춘다.

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from core.config import PROJECT_ROOT
from core.schemas import QI_TYPE_SET, QI_TYPES, RISK_DEFENDER_QI_TYPES
from orchestrator.trace_reader import arm_of, iter_sessions
from validation.validator import UnknownTargetError, Validator, Verdict, VALID_VERDICTS

K_MODE, NO_K_MODE = "k", "no-k"
MODES = (NO_K_MODE, K_MODE)
MODE_NAMES = {K_MODE: "K-Feedback", NO_K_MODE: "No-K"}
DEFAULT_OUT_ROOT = PROJECT_ROOT / "runs" / "ablation" / "comparison"

# 두 모드에서 같아야 하는 run_config 항목 (fuzzer의 피드백 설정은 다른 것이 맞으므로 뺀다)
FAIRNESS_KEYS = ("target_ids", "arms", "backend.name", "max_turns", "rng_seed", "risk", "gate", "prompts",
                 "temperature", "model", "population", "retriever", "seed_registry",
                 "llm_settings.llm_model", "llm_settings.llm_max_tokens")
FUZZER_MODE_KEYS = ("use_k_feedback", "no_k_strategy")
# FuzzerAdapter가 아니라 정해진 질문을 그대로 던진 턴 (orchestrator ReplayFuzzer의 label)
REPLAYED_REASONS = ("REPLAY", "PAIRED", "FIXED", "RECORDED")


# ──────────────────────────────────────────────────────────────
# 실행 읽기
# ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RunInfo:
    run_id: str
    run_dir: Path
    config: dict[str, Any]
    mode: str
    sessions: tuple[tuple[str, str, tuple[dict[str, Any], ...]], ...]   # (target_id, arm, turn 줄들)
    issues: tuple[str, ...]

    @property
    def backend(self) -> str:
        return (self.config.get("backend") or {}).get("name", "risk_defender")

    @property
    def counted_qis(self) -> frozenset[str]:
        return QI_TYPE_SET if self.backend == "ontology_d1" else RISK_DEFENDER_QI_TYPES


def feedback_mode_of(config: Mapping[str, Any]) -> str:
    return K_MODE if (config.get("fuzzer") or {}).get("use_k_feedback", True) else NO_K_MODE


def load_run(run_dir: str | Path, arms: Sequence[str] | None = None) -> RunInfo:
    """
    input : run_dir (orchestrator 실행 폴더), arms (이 갈래만. None이면 전부)
    output : RunInfo. 평가할 수 없는 실행이면 sessions가 비고 issues에 사유가 남는다
    """
    run_dir = Path(run_dir)
    missing = [name for name in ("run_config.json", "trace.jsonl") if not (run_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"{run_dir}에 {', '.join(missing)}이(가) 없습니다.")
    config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    issues: list[str] = []
    if (config.get("fuzzer") or {}).get("fixed_questions"):
        issues.append(f"{run_dir.name}: 정해진 질문으로 돌린 실행이라 Fuzzer 피드백을 비교할 수 없습니다 (평가 제외).")
        return RunInfo(run_dir.name, run_dir, config, feedback_mode_of(config), (), tuple(issues))

    latest: dict[tuple[str, str], tuple[dict[str, Any], ...]] = {}
    dropped = 0
    for session in iter_sessions(run_dir / "trace.jsonl"):
        if not session.turns:
            continue
        arm = arm_of(session.head)
        if arms and arm not in arms:
            continue
        if not session.finished or session.end.get("stop_reason") == "LLM_ERROR":
            dropped += 1
            continue
        latest[(session.head["target_id"], arm)] = session.turns      # 같은 대상·갈래면 뒤의 것이 남는다
    if dropped:
        issues.append(f"{run_dir.name}: 끊겼거나 LLM_ERROR로 끝난 세션 {dropped}개를 뺐습니다.")
    sessions = tuple((target_id, arm, turns) for (target_id, arm), turns in latest.items())
    return RunInfo(run_dir.name, run_dir, config, feedback_mode_of(config), sessions, tuple(issues))


# ──────────────────────────────────────────────────────────────
# 세션 하나의 QI 추출
# ──────────────────────────────────────────────────────────────

@dataclass
class SessionExtraction:
    run_id: str
    mode: str
    arm: str
    target_id: str
    truth: frozenset[str]
    turn_rows: list[dict[str, Any]] = field(default_factory=list)
    correct: dict[str, int] = field(default_factory=dict)          # QI → 처음 맞게 추출된 턴
    correct_strict: dict[str, int] = field(default_factory=dict)
    detected: dict[str, int] = field(default_factory=dict)         # QI → 처음 State에 들어간 턴 (정답 QI 안에서)

    @property
    def turns(self) -> int:
        return len(self.turn_rows)

    def cumulative_at(self, turn: int, strict: bool = False) -> int:
        found = self.correct_strict if strict else self.correct
        return sum(1 for first in found.values() if first <= turn)

    def new_at(self, turn: int) -> int:
        return sum(1 for first in self.correct.values() if first == turn)


def extract_session(run: RunInfo, target_id: str, arm: str, turns: Sequence[dict[str, Any]],
                    validator: Validator) -> SessionExtraction:
    truth = validator.truth_qis(target_id) & run.counted_qis
    result = SessionExtraction(run.run_id, run.mode, arm, target_id, truth)
    for item in turns:
        turn = item["turn"]
        state = item["commit"]["state_after"]
        verdicts = validator.validate(target_id, state).verdicts if state else {}
        new = []
        for qi in sorted(truth & set(verdicts), key=QI_TYPES.index):
            result.detected.setdefault(qi, turn)
            if verdicts[qi] in VALID_VERDICTS and qi not in result.correct:
                result.correct[qi] = turn
                new.append(qi)
            if verdicts[qi] is Verdict.CORRECT:
                result.correct_strict.setdefault(qi, turn)
        attack = item.get("attack") or {}
        cumulative = len(result.correct)
        result.turn_rows.append({
            "run_id": run.run_id,
            "feedback_mode": run.mode,
            "arm": arm,
            "target_id": target_id,
            "turn": turn,
            "seed_id": attack.get("seed_id"),
            "qi_type": attack.get("target_qi"),
            "strategy": attack.get("strategy"),
            "reset_reason": attack.get("reset_reason"),
            "k_feedback_used": (run.mode == K_MODE and turn > 1
                                and attack.get("reset_reason") not in REPLAYED_REASONS),
            "k_before": item["commit"]["k_before"],
            "k_value": item["commit"]["k_after"],
            "feedback_status": item.get("feedback_status"),
            "qi_extracted": "|".join(new),
            "qi_new": len(new),
            "qi_cumulative": cumulative,
            "qi_total": len(truth),
            "qi_extraction_rate": _pct(cumulative, len(truth)),
            "qi_detected_cumulative": len(result.detected),
            "qi_incorrect_in_state": "|".join(sorted(qi for qi, v in verdicts.items() if v is Verdict.INCORRECT)),
        })
    return result


# ──────────────────────────────────────────────────────────────
# 비교
# ──────────────────────────────────────────────────────────────

@dataclass
class Comparison:
    runs: list[RunInfo]
    sessions: list[SessionExtraction]
    issues: list[str]
    fairness: list[dict[str, Any]]

    def arms(self) -> list[str]:
        return sorted({s.arm for s in self.sessions})

    def of(self, mode: str, arm: str) -> list[SessionExtraction]:
        return [s for s in self.sessions if s.mode == mode and s.arm == arm]

    # ── 표 ────────────────────────────────────────────

    def summary_rows(self) -> list[dict[str, Any]]:
        rows = []
        for arm in self.arms():
            by_mode = {mode: _summary(self.of(mode, arm)) for mode in MODES}
            for mode in MODES:
                rows.append({"arm": arm, "feedback_mode": mode, **by_mode[mode]})
            rows.append({"arm": arm, "feedback_mode": "KFG(%p)", **_gain(by_mode[K_MODE], by_mode[NO_K_MODE])})
        return rows

    def qi_type_rows(self) -> list[dict[str, Any]]:
        rows = []
        for arm in self.arms():
            for qi in QI_TYPES:
                row: dict[str, Any] = {"arm": arm, "qi_type": qi}
                for mode in MODES:
                    pool = [s for s in self.of(mode, arm) if qi in s.truth]
                    hit = sum(1 for s in pool if qi in s.correct)
                    row[f"{mode}_sessions"] = len(pool)
                    row[f"{mode}_extracted"] = hit
                    row[f"{mode}_qer"] = _pct(hit, len(pool))
                    row[f"{mode}_detected"] = sum(1 for s in pool if qi in s.detected)
                if not row[f"{K_MODE}_sessions"] and not row[f"{NO_K_MODE}_sessions"]:
                    continue
                row["kfg_pp"] = _diff(row[f"{K_MODE}_qer"], row[f"{NO_K_MODE}_qer"])
                rows.append(row)
        return rows

    def turn_rows(self) -> list[dict[str, Any]]:
        rows = []
        for arm in self.arms():
            last = max((s.turns for s in self.sessions if s.arm == arm), default=0)
            for turn in range(1, last + 1):
                row: dict[str, Any] = {"arm": arm, "turn": turn}
                for mode in MODES:
                    pool = [s for s in self.of(mode, arm) if s.truth]
                    total = sum(len(s.truth) for s in pool)
                    cumulative = sum(s.cumulative_at(turn) for s in pool)
                    row[f"{mode}_sessions"] = len(pool)
                    row[f"{mode}_sessions_ended"] = sum(1 for s in pool if s.turns < turn)
                    row[f"{mode}_qi_new"] = sum(s.new_at(turn) for s in pool)
                    row[f"{mode}_qi_cumulative"] = cumulative
                    row[f"{mode}_qi_total"] = total
                    row[f"{mode}_qer"] = _pct(cumulative, total)
                row["kfg_pp"] = _diff(row[f"{K_MODE}_qer"], row[f"{NO_K_MODE}_qer"])
                rows.append(row)
        return rows

    def paired_rows(self, resamples: int = 2000, rng_seed: int = 0) -> list[dict[str, Any]]:
        """
        대상 단위 짝 비교: 두 모드에 모두 있는 대상마다 (반복 실행은 대상 안에서 합쳐) QER 차이를 구하고,
        그 평균과 대상 재표본 95% 구간을 낸다.
        """
        rows = []
        for arm in self.arms():
            per_target: dict[str, dict[str, tuple[int, int]]] = {}
            for s in self.sessions:
                if s.arm != arm or not s.truth:
                    continue
                hit, total = per_target.setdefault(s.target_id, {}).get(s.mode, (0, 0))
                per_target[s.target_id][s.mode] = (hit + len(s.correct), total + len(s.truth))
            diffs = [100 * (m[K_MODE][0] / m[K_MODE][1] - m[NO_K_MODE][0] / m[NO_K_MODE][1])
                     for m in per_target.values() if K_MODE in m and NO_K_MODE in m]
            row: dict[str, Any] = {"arm": arm, "paired_targets": len(diffs)}
            if diffs:
                rng = random.Random(rng_seed)
                means = sorted(sum(rng.choices(diffs, k=len(diffs))) / len(diffs) for _ in range(resamples))
                row.update({
                    "mean_kfg_pp": round(sum(diffs) / len(diffs), 2),
                    "ci95_low_pp": round(means[int(0.025 * resamples)], 2),
                    "ci95_high_pp": round(means[int(0.975 * resamples) - 1], 2),
                    "targets_k_better": sum(1 for d in diffs if d > 0),
                    "targets_tied": sum(1 for d in diffs if d == 0),
                    "targets_no_k_better": sum(1 for d in diffs if d < 0),
                })
            rows.append(row)
        return rows

    def session_rows(self) -> list[dict[str, Any]]:
        rows = []
        for s in self.sessions:
            for qi in sorted(s.truth, key=QI_TYPES.index):
                rows.append({"run_id": s.run_id, "feedback_mode": s.mode, "arm": s.arm, "target_id": s.target_id,
                             "qi_type": qi, "extracted": qi in s.correct, "first_turn": s.correct.get(qi),
                             "extracted_strict": qi in s.correct_strict, "detected": qi in s.detected,
                             "turns": s.turns})
        return rows


def compare(k_runs: Sequence[RunInfo], no_k_runs: Sequence[RunInfo],
            validator_of: Any) -> Comparison:
    """
    input : k_runs / no_k_runs (load_run 결과), validator_of (RunInfo → 그 실행에 맞는 Validator)
    output : Comparison
    """
    issues: list[str] = []
    for expected, runs in ((K_MODE, k_runs), (NO_K_MODE, no_k_runs)):
        for run in runs:
            if run.mode != expected:
                raise ValueError(f"{run.run_id}는 {MODE_NAMES[run.mode]} 실행인데 "
                                 f"{MODE_NAMES[expected]} 쪽에 들어 있습니다 (run_config.json의 fuzzer.use_k_feedback).")
    runs = [*k_runs, *no_k_runs]
    sessions: list[SessionExtraction] = []
    for run in runs:
        issues.extend(run.issues)
        validator = validator_of(run) if run.sessions else None
        for target_id, arm, turns in run.sessions:
            try:
                extraction = extract_session(run, target_id, arm, turns, validator)
            except UnknownTargetError:
                issues.append(f"{run.run_id}/{target_id}/{arm}: 기준 집단에 정답이 없는 대상이라 뺐습니다.")
                continue
            if not extraction.truth:
                issues.append(f"{run.run_id}/{target_id}/{arm}: 정답 QI(백엔드가 세는 QI 중 값이 있는 것)가 없어 뺐습니다.")
                continue
            sessions.append(extraction)
    for mode in MODES:
        if not any(s.mode == mode for s in sessions):
            issues.append(f"{MODE_NAMES[mode]} 쪽에 평가할 수 있는 세션이 없습니다. KFG를 계산할 수 없습니다.")
    return Comparison(runs, sessions, issues, fairness_check(k_runs, no_k_runs))


def fairness_check(k_runs: Sequence[RunInfo], no_k_runs: Sequence[RunInfo]) -> list[dict[str, Any]]:
    """두 모드의 실행 설정 중 같아야 하는 항목을 비교한다. 반복 실행이면 값들의 묶음(순서 무시)을 비교한다."""
    rows = []
    keys = [*FAIRNESS_KEYS, *(f"fuzzer.{key}" for key in _fuzzer_keys([*k_runs, *no_k_runs]))]
    for key in keys:
        values = {mode: sorted(_dump(_lookup(run.config, key)) for run in runs)
                  for mode, runs in ((K_MODE, k_runs), (NO_K_MODE, no_k_runs))}
        rows.append({"key": key, "same": values[K_MODE] == values[NO_K_MODE],
                     K_MODE: " ; ".join(dict.fromkeys(values[K_MODE])),
                     NO_K_MODE: " ; ".join(dict.fromkeys(values[NO_K_MODE]))})
    return rows


# ──────────────────────────────────────────────────────────────
# 파일 쓰기
# ──────────────────────────────────────────────────────────────

def write_outputs(comparison: Comparison, out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=False)
    turn_level = [row for s in comparison.sessions for row in s.turn_rows]
    tables = {
        "ablation_turns.csv": turn_level,
        "ablation_session_qi.csv": comparison.session_rows(),
        "ablation_summary.csv": comparison.summary_rows(),
        "ablation_by_qi_type.csv": comparison.qi_type_rows(),
        "ablation_by_turn.csv": comparison.turn_rows(),
        "ablation_paired.csv": comparison.paired_rows(),
        "ablation_fairness.csv": comparison.fairness,
    }
    written = []
    for name, rows in tables.items():
        written.append(_write_csv(out / name, rows))
    report = out / "ablation_report.md"
    report.write_text(to_markdown(comparison), encoding="utf-8")
    written.append(report)
    figure = plot_cumulative(comparison.turn_rows(), out / "ablation_cumulative_qer.png")
    if figure is not None:
        written.append(figure)
    (out / "manifest.json").write_text(json.dumps({
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "runs": [{"run_id": run.run_id, "path": _relative(run.run_dir), "feedback_mode": run.mode,
                  "sessions": len(run.sessions)} for run in comparison.runs],
        "issues": comparison.issues,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    written.append(out / "manifest.json")
    return written


def plot_cumulative(turn_rows: Sequence[dict[str, Any]], path: Path) -> Path | None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    arms = sorted({row["arm"] for row in turn_rows})
    if not arms:
        return None
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    styles = {K_MODE: "-", NO_K_MODE: "--"}
    for arm in arms:
        rows = [row for row in turn_rows if row["arm"] == arm]
        for mode in MODES:
            points = [(row["turn"], row[f"{mode}_qer"]) for row in rows if row[f"{mode}_qer"] is not None]
            if points:
                ax.plot(*zip(*points), styles[mode], marker="o", label=f"{MODE_NAMES[mode]} ({arm})")
    ax.set_xlabel("Turn")
    ax.set_ylabel("Cumulative QI extraction rate (%)")
    ax.set_ylim(0, 100)
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def to_markdown(comparison: Comparison) -> str:
    lines = ["# K 피드백 Ablation 비교 (QI 추출률)", ""]
    lines += ["## 실행", "", "| 실행 | 모드 | 평가 세션 |", "|---|---|---|"]
    counts: dict[str, int] = {}
    for s in comparison.sessions:
        counts[s.run_id] = counts.get(s.run_id, 0) + 1
    lines += [f"| {run.run_id} | {MODE_NAMES[run.mode]} | {counts.get(run.run_id, 0)} |" for run in comparison.runs]

    lines += ["", "## 전체 비교", "",
              "| 갈래 | 모드 | 세션 | 정답 QI | 맞게 추출(고유) | QER | QER strict | QER 세션 평균 | 탐지 |",
              "|---|---|---|---|---|---|---|---|---|"]
    for row in comparison.summary_rows():
        name = MODE_NAMES.get(row["feedback_mode"], row["feedback_mode"])
        lines.append(f"| {row['arm']} | {name} | {_cell(row.get('sessions'))} | {_cell(row.get('qi_total'))} "
                     f"| {_cell(row.get('qi_correct'))} | {_cell(row['qer'], '%')} | {_cell(row['qer_strict'], '%')} "
                     f"| {_cell(row['qer_macro'], '%')} | {_cell(row.get('qi_detected'))} |")

    lines += ["", "## 대상 단위 짝 비교 (KFG, 대상 재표본 95% 구간)", "",
              "| 갈래 | 짝 대상 | 평균 KFG | 95% 구간 | K 우세 / 같음 / No-K 우세 |", "|---|---|---|---|---|"]
    for row in comparison.paired_rows():
        if "mean_kfg_pp" in row:
            lines.append(f"| {row['arm']} | {row['paired_targets']} | {row['mean_kfg_pp']:+.2f}%p "
                         f"| [{row['ci95_low_pp']:+.2f}, {row['ci95_high_pp']:+.2f}] "
                         f"| {row['targets_k_better']} / {row['targets_tied']} / {row['targets_no_k_better']} |")
        else:
            lines.append(f"| {row['arm']} | 0 | 평가 불가 (두 모드에 같은 대상이 없음) | - | - |")

    lines += ["", "## QI 유형별", "", "| 갈래 | QI | No-K | K-Feedback | KFG |", "|---|---|---|---|---|"]
    for row in comparison.qi_type_rows():
        lines.append(f"| {row['arm']} | {row['qi_type']} "
                     f"| {_cell(row[f'{NO_K_MODE}_qer'], '%')} ({row[f'{NO_K_MODE}_extracted']}/{row[f'{NO_K_MODE}_sessions']}) "
                     f"| {_cell(row[f'{K_MODE}_qer'], '%')} ({row[f'{K_MODE}_extracted']}/{row[f'{K_MODE}_sessions']}) "
                     f"| {_cell(row['kfg_pp'], '%p', signed=True)} |")

    lines += ["", "## 턴별 누적 QER", "", "| 갈래 | 턴 | No-K 신규 | No-K 누적 | No-K QER | K 신규 | K 누적 | K QER | KFG |",
              "|---|---|---|---|---|---|---|---|---|"]
    for row in comparison.turn_rows():
        lines.append(f"| {row['arm']} | {row['turn']} | {row[f'{NO_K_MODE}_qi_new']} | {row[f'{NO_K_MODE}_qi_cumulative']} "
                     f"| {_cell(row[f'{NO_K_MODE}_qer'], '%')} | {row[f'{K_MODE}_qi_new']} | {row[f'{K_MODE}_qi_cumulative']} "
                     f"| {_cell(row[f'{K_MODE}_qer'], '%')} | {_cell(row['kfg_pp'], '%p', signed=True)} |")

    different = [row for row in comparison.fairness if not row["same"]]
    lines += ["", "## 실험 조건 일치 확인", ""]
    if different:
        lines += ["두 모드에서 다음 설정이 다릅니다. 이 차이도 QER 차이에 섞여 있을 수 있습니다.", "",
                  "| 항목 | K-Feedback | No-K |", "|---|---|---|"]
        lines += [f"| {row['key']} | {row[K_MODE]} | {row[NO_K_MODE]} |" for row in different]
    else:
        lines.append(f"비교한 {len(comparison.fairness)}개 설정이 모두 같습니다 (Fuzzer 피드백 설정만 다름).")

    lines += ["", "## 평가 불가·제외 사유", ""]
    lines += [f"- {issue}" for issue in comparison.issues] or ["- 없음"]
    lines += ["", "## 정의", "",
              "- 정답 QI: 대상의 정답에 값이 있고 백엔드가 k에 넣는 QI. 맞게 추출: State 값의 판정이 CORRECT·LESS_PRECISE "
              "(strict는 CORRECT만). 같은 QI는 한 번만 센다.",
              "- QER = Σ 누적 맞게 추출한 고유 QI / Σ 정답 QI × 100. KFG = QER(K-Feedback) − QER(No-K) (%p).",
              "- 탐지: 정답과 관계없이 State에 들어간 적이 있는 정답 QI 종류 (추출기 결과). 맞았는지와 따로 센다.",
              "- State는 공개된 응답에서 commit된 값이다. C1·C1S에서는 Defender가 막은 값이 들어가지 않는다.",
              "- 턴별 표에서 일찍 끝난 세션은 마지막 누적 값을 이어 쓴다 (ablation_by_turn.csv의 *_sessions_ended)."]
    return "\n".join(lines) + "\n"


# ──────────────────────────────────────────────────────────────
# 내부 함수
# ──────────────────────────────────────────────────────────────

def _summary(sessions: Sequence[SessionExtraction]) -> dict[str, Any]:
    total = sum(len(s.truth) for s in sessions)
    correct = sum(len(s.correct) for s in sessions)
    strict = sum(len(s.correct_strict) for s in sessions)
    rates = [100 * len(s.correct) / len(s.truth) for s in sessions if s.truth]
    return {
        "sessions": len(sessions),
        "targets": len({s.target_id for s in sessions}),
        "qi_total": total,
        "qi_correct": correct,
        "qi_correct_strict": strict,
        "qi_detected": sum(len(s.detected) for s in sessions),
        "qer": _pct(correct, total),
        "qer_strict": _pct(strict, total),
        "qer_macro": round(sum(rates) / len(rates), 2) if rates else None,
    }


def _gain(k: Mapping[str, Any], no_k: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _diff(k[key], no_k[key]) for key in ("qer", "qer_strict", "qer_macro")}


def _pct(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 2) if whole else None


def _diff(a: float | None, b: float | None) -> float | None:
    return round(a - b, 2) if a is not None and b is not None else None


def _cell(value: Any, unit: str = "", signed: bool = False) -> str:
    if value is None:
        return "평가 불가"
    if isinstance(value, float):
        return f"{value:+.2f}{unit}" if signed else f"{value:.2f}{unit}"
    return f"{value}{unit}"


def _lookup(config: Mapping[str, Any], dotted: str) -> Any:
    value: Any = config
    for part in dotted.split("."):
        value = value.get(part) if isinstance(value, Mapping) else None
    if dotted == "target_ids" and isinstance(value, list):
        return sorted(value)
    return value


def _fuzzer_keys(runs: Iterable[RunInfo]) -> list[str]:
    keys: dict[str, None] = {}
    for run in runs:
        keys.update(dict.fromkeys(run.config.get("fuzzer") or {}))
    return [key for key in keys if key not in FUZZER_MODE_KEYS]


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> Path:
    fieldnames: dict[str, None] = {}
    for row in rows:
        fieldnames.update(dict.fromkeys(row))
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)
    return path


def _relative(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return Path(path).name


# ──────────────────────────────────────────────────────────────
# 실행
# ──────────────────────────────────────────────────────────────

def _validators() -> Any:
    """실행의 기준 집단·백엔드에 맞는 검증기를 만든다 (validation/__main__.py와 같은 규칙). 한 번 만든 것은 다시 쓴다."""
    from adapters.ontology_risk import build_population_index
    from adapters.risk_adapter import PopulationMode, load_reference_population
    from validation.validator import OntologyValidator, RiskDefenderValidator

    populations: dict[str, Any] = {}
    cache: dict[tuple[str, str], Validator] = {}

    def validator_of(run: RunInfo) -> Validator:
        mode = (run.config.get("population") or {}).get("mode", "expanded")
        if mode not in populations:
            populations[mode] = load_reference_population(PopulationMode(mode))
        if (mode, run.backend) not in cache:
            population = populations[mode]
            cache[(mode, run.backend)] = (OntologyValidator(build_population_index(population), population)
                                          if run.backend == "ontology_d1" else RiskDefenderValidator(population))
        return cache[(mode, run.backend)]

    return validator_of


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m validation.ablation",
        description="K-Feedback 실행과 No-K 실행의 QI 추출률을 정답과 대조해 비교한다 (LLM 호출 없음)")
    parser.add_argument("--k", nargs="+", required=True, help="K-Feedback 실행 폴더 (반복 실행이면 여러 개)")
    parser.add_argument("--no-k", nargs="+", required=True, help="No-K 실행 폴더 (반복 실행이면 여러 개)")
    parser.add_argument("--arms", nargs="+", default=None, type=str.upper, help="이 갈래만 비교 (기본: 전부)")
    parser.add_argument("--out", default=None, help=f"결과 폴더 (기본: {_relative(DEFAULT_OUT_ROOT)}/<시각>)")
    args = parser.parse_args(argv)

    out = Path(args.out) if args.out else DEFAULT_OUT_ROOT / datetime.now().strftime("cmp_%Y%m%d_%H%M%S")
    if out.exists():
        print(f"{out}가 이미 있습니다. 이전 결과를 덮어쓰지 않도록 --out을 바꾸세요.")
        return 2
    k_runs = [load_run(path, args.arms) for path in args.k]
    no_k_runs = [load_run(path, args.arms) for path in args.no_k]
    try:
        comparison = compare(k_runs, no_k_runs, _validators())
    except ValueError as exc:
        print(f"중단: {exc}")
        return 2
    written = write_outputs(comparison, out)
    print(to_markdown(comparison))
    print("결과 파일:")
    for path in written:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
