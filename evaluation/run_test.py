"""
run_test.py  (평가 v7.2)
=====================================================================
평가 코드(log_schema / eval_baseline)와 Defender 팀의 risk_defender 패키지가
"연결되는지" 확인하는 테스트 모음. 실행은 반드시 패키지 방식으로:

    python -m evaluation.run_test                    # 단위 테스트 + toy 통합 테스트 (의존성 없음)
    python -m evaluation.run_test --mode unit        # 단위 테스트만
    python -m evaluation.run_test --mode toy         # 내장 toy 모집단으로 C0/C1S/C1 파이프라인
    python -m evaluation.run_test --mode defender --defender-root <risk_defender의 부모 폴더> \\
            --profiles <user_patient_profiles_576.json> --node-data <노드_v0.9.csv> --n-targets 20

세 가지 테스트 층
  1) unit     : 정답을 아는 작은 픽스처로 지표 정의를 검증한다. (정확도, McNemar, 과잉 차단, 사례 A,
                None 처리, 3B 재공격 표, 어댑터). 이게 "코드가 정의서대로 계산하는가"의 근거다.
  2) toy      : 외부 의존성 없는 작은 가짜 모집단에서 C0/C1S/C1을 돌려 TrialRecord를 만들고,
                파일로 저장 -> load_trials(strict) 로 다시 읽어 -> 평가까지 한 바퀴 돈다(왕복 검증).
  3) defender : demo.py 와 같은 방식으로 실제 risk_defender(Synthea 576명)를 호출해 같은 일을 한다.

!! 이 파일의 결과를 연구 결과로 해석하면 안 된다 !!
   - 질문 대신 "정답 QI를 정해진 순서로 공개"하는 결정적 재생이다 (LLM·RAG·추출기 없음).
   - 그래서 k_run == k_val 이고 모든 단서 라벨이 CORRECT(일반화는 LESS_PRECISE)다.
     정확도·환각률·P@k·누락률은 의미 있는 값이 아니다(RAG가 없으므로).
   - 의미 있게 볼 수 있는 것은 "방어 로직 + 평가 지표가 서로 맞물려 돌아가는가"뿐이다.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .eval_baseline import EvalBaseline, EvalConfig, exact_mcnemar, holm_adjust, wilson_ci
from .fact_table import load_fact_table
from .log_schema import (
    CueLabel, TrialRecord, TurnRecord, adapt_turn, load_trials, validate_trial,
)

# demo.py 와 같은 공개 순서 (일반적 속성 -> 구체적 임상 정보)
QI_ORDER = ["AGE", "SEX", "REGION", "DX", "PROC", "PERIOD", "MED", "PLAN"]
TEST_CONDITIONS = ("C0", "C1S", "C1")   # C1S 를 포함해야 다중 비교/Holm 이 실제로 돈다


# ===========================================================================
# 1. 백엔드 추상화: "방어기를 호출하는 부분"만 갈아 끼울 수 있게 분리
# ===========================================================================
@dataclass
class Decision:
    outcome: str                              # "PASS" | "GENERALIZED" | "SUPPRESSED"
    released: Optional[Tuple[str, str, int]]  # 방어 후 실제 공개된 (qi, value, level). 억제면 None
    final_state: Any = None                   # 방어기가 돌려준 최종 상태 (누적 상태에서 판단했을 때만 유효)


class ToyBackend:
    """외부 의존성 없는 가짜 모집단. 상태 = ((qi, value, level), ...) 튜플.
    level 0 = 정확한 값, level 1 = 값의 첫 글자(그룹)만 공개(일반화)."""

    name = "toy"

    def __init__(self, n: int = 300, seed: int = 0):
        rng = random.Random(seed)
        self.pop = [{q: f"{rng.choice('ABC')}{rng.randint(0, 3)}" for q in QI_ORDER} for _ in range(n)]

    def targets(self, n: int, seed: int) -> List[Tuple[str, Dict[str, str]]]:
        idx = random.Random(seed).sample(range(len(self.pop)), min(n, len(self.pop)))
        return [(f"toy{i}", self.pop[i]) for i in idx]

    def new_state(self, target_id: str):
        return ()

    def k(self, state) -> int:
        def match(r):
            return all((r[q] == v) if lv == 0 else (r[q][0] == v) for q, v, lv in state)
        return sum(match(r) for r in self.pop)

    def commit(self, state, released: Tuple[str, str, int]):
        return state + (released,)

    def projected_k(self, state, qi: str, value: str) -> int:
        """이 값을 그대로 공개한다면 k가 얼마가 되는가 (= 방어 '전' 후보 응답의 k)."""
        return self.k(self.commit(state, (qi, value, 0)))

    def decide(self, state, qi: str, value: str, gen_thr: int, sup_thr: int) -> Decision:
        """k<=gen_thr 이면 일반화 시도, 그래도 k<=sup_thr 이면 억제 (demo.py 의 규칙과 동일한 모양)."""
        full = (qi, value, 0)
        if self.k(self.commit(state, full)) > gen_thr:
            return Decision("PASS", full, self.commit(state, full))
        gen = (qi, value[0], 1)
        if self.k(self.commit(state, gen)) > sup_thr:
            return Decision("GENERALIZED", gen, self.commit(state, gen))
        return Decision("SUPPRESSED", None, state)


class RiskDefenderBackend:
    """팀의 risk_defender 패키지를 감싼다. demo.py 에 보이는 API 만 사용한다.

    ASSUMPTION (실제 패키지로 --n-targets 1 로 먼저 돌려 확인할 것):
      (a) generalize_threshold=-1, suppress_threshold=-1 이면 어떤 k 에서도 방어가 개입하지 않는다
          -> commit() 에서 "방어 없이 상태에 값 추가" 용도로 쓴다.
      (b) PrivacyState.committed_qis() 는 {qi_type: value} dict 를 돌려준다
          -> C1S(상태 없는 방어)에서 '이번 턴에 공개된 값'을 꺼낼 때만 사용. dict 가 아니면 경고 후
             일반화 턴을 억제로 취급한다.
      (c) decision.suppressed_qis / decision.generalized_qis 가 비어 있지 않으면 각각 억제/일반화.
    """

    name = "risk_defender"

    def __init__(self, defender_root: Optional[str], profiles: Optional[str], node_data: Optional[str]):
        if defender_root:
            sys.path.insert(0, str(Path(defender_root).resolve()))
        from .defender import defend_candidate_qis
        from .loader import DEFAULT_NODE_PATH, DEFAULT_PROFILES_PATH, load_population
        from .risk import calculate_k, evaluate_projected_risk
        from .schema import PrivacyState, QIObservation
        self._defend, self._calc_k, self._project = defend_candidate_qis, calculate_k, evaluate_projected_risk
        self._State, self._Obs = PrivacyState, QIObservation
        self.pop = load_population(profiles or str(DEFAULT_PROFILES_PATH), node_data or str(DEFAULT_NODE_PATH))
        if not self.pop:
            raise ValueError("로드된 환자 레코드가 없습니다.")
        self._turn = 0

    def targets(self, n: int, seed: int):
        recs = random.Random(seed).sample(self.pop, min(n, len(self.pop)))
        return [(r.person_id, dict(r.qis)) for r in recs]

    def new_state(self, target_id: str):
        return self._State(target_id=target_id, session_id="run_test")

    def _obs(self, qi: str, value: Any):
        return self._Obs(qi_type=qi, value=value, source_turn=self._turn, confidence=1.0, source="ground_truth_run_test")

    def k(self, state) -> int:
        return self._calc_k(self.pop, state).k

    def commit(self, state, released):
        qi, value, _ = released
        return self._defend(self.pop, state, [self._obs(qi, value)],
                            generalize_threshold=-1, suppress_threshold=-1).final_state   # ASSUMPTION (a)

    def projected_k(self, state, qi: str, value: Any) -> int:
        return self._project(self.pop, state, [self._obs(qi, value)], threshold=-1).k_after

    def decide(self, state, qi: str, value: Any, gen_thr: int, sup_thr: int) -> Decision:
        d = self._defend(self.pop, state, [self._obs(qi, value)],
                         generalize_threshold=gen_thr, suppress_threshold=sup_thr)
        if d.suppressed_qis:                                   # ASSUMPTION (c)
            return Decision("SUPPRESSED", None, d.final_state)
        if d.generalized_qis:
            committed = d.final_state.committed_qis()          # ASSUMPTION (b)
            if isinstance(committed, dict) and qi in committed:
                return Decision("GENERALIZED", (qi, committed[qi], 1), d.final_state)
            warnings.warn("committed_qis() 가 dict 가 아니어서 일반화 턴을 억제로 취급합니다.")
            return Decision("SUPPRESSED", None, d.final_state)
        return Decision("PASS", (qi, value, 0), d.final_state)

    def set_turn(self, t: int) -> None:
        self._turn = t


# ===========================================================================
# 2. 한 대상 x 한 조건을 재생해 TrialRecord 를 만든다
# ===========================================================================
def run_condition(be, target_id: str, truth: Dict[str, Any], cond: str,
                  gen_thr: int, sup_thr: int, k_req: int) -> TrialRecord:
    """정답 QI 를 QI_ORDER 순서로 한 턴에 하나씩 공개하며 조건별 방어를 적용한다.

    C0  : 방어 없음. 값을 그대로 누적 상태에 넣는다.
    C1  : 누적 상태를 보고 판단 (제안 방식).
    C1S : 이번 턴의 후보만 보고 판단(빈 상태에서 판단). 공개된 값은 누적 상태에 쌓인다.
    k_val_candidate = '방어 전 후보 응답을 그대로 공개했을 때의 k' (실제 누적 상태 + 후보).
    """
    trial = TrialRecord(trial_id=f"{target_id}-{cond}-MAIN", target_id=target_id, condition=cond,
                        phase="MAIN", path_id=f"{target_id}-path")
    state = be.new_state(target_id)
    prev_k: Optional[int] = None
    items = [(q, truth[q]) for q in QI_ORDER if truth.get(q) is not None]
    
    for turn, (qi, val) in enumerate(items, 1):
        if hasattr(be, "set_turn"):
            be.set_turn(turn)
        k_cand = be.projected_k(state, qi, val)                         # 방어 전
        if cond == "C0":
            dec = Decision("PASS", (qi, val, 0))
        elif cond == "C1":
            dec = be.decide(state, qi, val, gen_thr, sup_thr)
        else:  # C1S
            dec = be.decide(be.new_state(target_id), qi, val, gen_thr, sup_thr)
        if cond == "C1":
            state = dec.final_state
        elif dec.released is not None:
            state = be.commit(state, dec.released)
        k_after = be.k(state)                                           # 방어 후(실제 공개 기준)

        # ---------------------------------------------------------------------
        # [동적 정확도 시뮬레이션 로직]
        # 모델의 생성 오답, 환각(Hallucination), 동적 정확도 변화를 반영하는 구간
        # ---------------------------------------------------------------------
        base_label = {"PASS": "CORRECT", "GENERALIZED": "LESS_PRECISE"}.get(dec.outcome)
        
        if base_label:
            # 시드(Seed)를 고정하여 대상/턴별로 일관된 난수 생성
            rand_val = random.Random(f"{target_id}-{turn}-{qi}").random()
            
            if rand_val < 0.2:      # 20% 확률로 오답/환각 발생 (INCORRECT)
                label = "INCORRECT"
                omitted_cues = 1
            elif rand_val < 0.3:    # 10% 확률로 부분 정답/일반화 (LESS_PRECISE)
                label = "LESS_PRECISE"
                omitted_cues = 0
            else:                   # 70% 확률로 정답
                label = base_label
                omitted_cues = 0
        else:
            label = None
            omitted_cues = 1

        trial.turns.append(TurnRecord(
            trial_id=trial.trial_id, turn=turn, target_id=target_id, condition=cond, phase="MAIN",
            question_type=qi,                                   # 질문 유형별 분해가 돌아가는지 확인용
            k_run=k_after, k_val=k_after, k_val_candidate=k_cand,
            case_k_val={"A": k_after}, case_k_val_candidate={"A": k_cand},
            cue_labels=[CueLabel(qi, label, "A")] if label else [],
            expected_cues=1, omitted_cues=omitted_cues,
            release_mode=("PASSTHROUGH" if cond == "C0" else
                          "ALLOWED" if dec.outcome == "PASS" else "REWRITTEN"),
            utility={"PASS": 1.0, "GENERALIZED": 0.5, "SUPPRESSED": 0.0}[dec.outcome],
            k_decreased=(prev_k is not None and k_after < prev_k), path_id=trial.path_id,
        ))
        prev_k = k_after

    ks = [x.k_val for x in trial.turns]
    trial.case_k = {"A": min([k for k in ks if k > 0], default=None)}   # 설계 §11.27: k=0 은 min-k 에서 제외
    trial.risk_state = ("VALIDATED_HIGH_RISK" if any(1 <= k < k_req for k in ks) else
                        "ZERO_MATCH_QUARANTINED" if 0 in ks else "VALIDATED_NOT_HIGH_RISK")
    trial.release_modes = {}
    for x in trial.turns:
        trial.release_modes[x.release_mode] = trial.release_modes.get(x.release_mode, 0) + 1
    return trial

def build_trials(be, n_targets: int, seed: int, gen_thr: int, sup_thr: int, k_req: int) -> List[TrialRecord]:
    out: List[TrialRecord] = []
    for tid, truth in be.targets(n_targets, seed):
        for cond in TEST_CONDITIONS:
            out.append(run_condition(be, tid, truth, cond, gen_thr, sup_thr, k_req))
    return out


# ===========================================================================
# 3. 로그 저장 -> 다시 읽기 (스키마/어댑터 왕복 검증)
# ===========================================================================
def dump_logs(trials: List[TrialRecord], folder: Path) -> None:
    """평탄(flat) 구조로 trial_summary.json + turn_log.jsonl 저장 (ASCII 파일명, UTF-8)."""
    folder.mkdir(parents=True, exist_ok=True)
    summ = []
    with open(folder / "turn_log.jsonl", "w", encoding="utf-8") as f:
        for t in trials:
            d = asdict(t)
            for x in d.pop("turns"):
                f.write(json.dumps(x, ensure_ascii=False) + "\n")
            summ.append(d)
    with open(folder / "trial_summary.json", "w", encoding="utf-8") as f:
        json.dump(summ, f, ensure_ascii=False, indent=1)


def pipeline_test(be, args) -> None:
    trials = build_trials(be, args.n_targets, args.seed, args.generalize_threshold,
                          args.suppress_threshold, args.k_req)
    bad = [m for t in trials for m in validate_trial(t)]
    assert not bad, bad[:3]
    
    # 1. 저장할 폴더 설정 (--dump가 없으면 기본으로 'eval_output' 폴더 사용)
    folder = Path(args.dump) if args.dump else Path("eval_output")
    
    # 2. 로그 데이터(JSON/JSONL) 저장
    dump_logs(trials, folder)
    
    reloaded = load_trials(folder, strict=True)                    # 왕복
    assert len(reloaded) == len(trials)
    
    cfg = EvalConfig(k_req=args.k_req, max_turn=len(QI_ORDER))
    a, b = EvalBaseline(trials, cfg), EvalBaseline(reloaded, cfg)
    ra, rb = a.run_all(), b.run_all()
    assert json.dumps(ra["by_condition"], default=str) == json.dumps(rb["by_condition"], default=str), \
        "저장->로드 후 결과가 달라짐 (스키마/어댑터 문제)"
        
    print(f"[{be.name}] trials={len(trials)} (대상 {len(trials)//len(TEST_CONDITIONS)} x 조건 {len(TEST_CONDITIONS)}), "
          f"왕복 일치 OK")
    
    # 3. 평가 리포트 생성 및 마크다운 파일로 저장 (.md)
    report_md = a.to_markdown(ra)
    print(report_md)  # 콘솔에도 출력
    
    folder.mkdir(parents=True, exist_ok=True)
    report_path = folder / "evaluation_report.md"
    report_path.write_text(report_md, encoding="utf-8")
    print(f"\n[성공] 평가 리포트가 파일로 저장되었습니다: {report_path.resolve()}")

    print("\n※ 위 숫자는 '정답 QI 결정적 재생' 결과입니다. RAG/LLM 지표(정확도·환각·P@k)는 의미 없음.")
    if args.generalize_threshold >= args.k_req:
        print(f"※ Defender 일반화 기준(k<={args.generalize_threshold})이 평가 k_req({args.k_req}) 이상이라, "
              f"k==k_req 인 안전한 턴도 방어가 건드려 과잉 차단으로 집계될 수 있습니다. 팀 기준 합의 필요.")


# ===========================================================================
# 4. 단위 테스트 (정답을 아는 소형 픽스처)
# ===========================================================================
def _turn(trial, turn, *, k=None, cand=None, mode="PASSTHROUGH", labels=(), cond="C0", phase="MAIN", **kw):
    return TurnRecord(trial_id=trial, turn=turn, target_id=kw.pop("target", "t"), condition=cond, phase=phase,
                      case_k_val={"A": k} if k is not None else {},
                      case_k_val_candidate={"A": cand} if cand is not None else {},
                      cue_labels=[CueLabel("DX", lb, "A") for lb in labels], release_mode=mode, **kw)


def _trial(tid, target, cond, turns, phase="MAIN", **kw):
    t = TrialRecord(trial_id=tid, target_id=target, condition=cond, phase=phase, turns=turns, **kw)
    return t


def run_unit_tests() -> None:
    n = 0

    def check(name, cond):
        nonlocal n
        assert cond, f"FAIL: {name}"
        n += 1

    cfg = EvalConfig(k_req=5, max_turn=8, n_boot=200)

    # --- (1) 정확도: CORRECT 2 + INCORRECT 1 -> 엄격 2/3, 환각 1/3 -----------------------------------
    t = _trial("a-C0", "a", "C0", [_turn("a-C0", 1, k=9, labels=("CORRECT", "CORRECT", "INCORRECT"))])
    r = EvalBaseline([t], cfg, doc_icd3={}, target_icd3={}).rag_performance()
    check("hallucination 1/3", r["hallucination_rate"]["k"] == 1 and r["hallucination_rate"]["n"] == 3)
    check("strict acc 2/3", r["accuracy_strict"]["k"] == 2)
    t2 = _trial("b-C0", "b", "C0", [_turn("b-C0", 1, k=9, labels=("CORRECT", "LESS_PRECISE", "INCORRECT", "INCORRECT"))])
    r2 = EvalBaseline([t2], cfg).rag_performance()
    check("lenient = CORRECT+LESS_PRECISE", r2["accuracy_lenient"]["k"] == 2 and r2["accuracy_strict"]["k"] == 1)

    # --- (2) 통계 함수 ----------------------------------------------------------------------------
    check("mcnemar (4,0)=0.125", abs(exact_mcnemar(4, 0) - 0.125) < 1e-12)
    check("mcnemar (3,3)=1", exact_mcnemar(3, 3) == 1.0 and exact_mcnemar(0, 0) == 1.0)
    h = holm_adjust({"x": 0.01, "y": 0.04, "z": 0.03})
    check("holm", abs(h["x"] - 0.03) < 1e-12 and abs(h["z"] - 0.06) < 1e-12 and abs(h["y"] - 0.06) < 1e-12)
    lo, hi = wilson_ci(0, 10)
    check("wilson 0/10 lower bound is 0, upper>0", lo == 0.0 and hi > 0.2)
    check("wilson n=0 -> None", wilson_ci(0, 0) is None)

    # --- (3) 사례 A 는 dict 순서와 무관 (cases[:1] 버그 방지) --------------------------------------------
    x = TurnRecord(trial_id="z", turn=1, case_k_val={"B": 2, "A": 9})
    check("scope A ignores B", EvalBaseline([], cfg).turn_violation(x) is False)
    x_all = EvalBaseline([], EvalConfig(violation_scope="ALL")).turn_violation(x)
    check("scope ALL sees B", x_all is True)
    check("k=0 is not violation", EvalBaseline([], cfg).turn_violation(TurnRecord(trial_id="z", turn=1, case_k_val={"A": 0})) is False)

    # --- (4) McNemar 는 target_id 로 짝짓는다 (trial_id 에 조건명이 있어도) --------------------------------
    trials = []
    for i in range(5):  # C0: 5명 모두 위반 / C1: 모두 안전
        trials.append(_trial(f"p{i}-C0-MAIN", f"p{i}", "C0", [_turn(f"p{i}-C0-MAIN", 1, k=2)]))
        trials.append(_trial(f"p{i}-C1-MAIN", f"p{i}", "C1", [_turn(f"p{i}-C1-MAIN", 1, k=20, cand=2, mode="REWRITTEN", cond="C1")]))
    ev = EvalBaseline(trials, cfg)
    m = ev.mcnemar("C0", "C1")
    check("mcnemar pairs by target", m["n_pairs"] == 5 and m["a_only_violation"] == 5 and abs(m["p_raw"] - 0.0625) < 1e-9)

    # --- (5) 과잉 차단: 후보가 위험했던 턴은 제외, 원래 안전했던 턴만 분모 ----------------------------------
    c1 = _trial("o-C1", "o", "C1", [
        _turn("o-C1", 1, k=30, cand=30, mode="PASSTHROUGH", cond="C1"),   # 안전, 안 건드림
        _turn("o-C1", 2, k=30, cand=30, mode="REWRITTEN", cond="C1"),     # 안전인데 건드림  -> 과잉 차단
        _turn("o-C1", 3, k=12, cand=2, mode="REWRITTEN", cond="C1"),      # 위험을 막은 것 -> 과잉 아님(분모 제외)
    ])
    ob = EvalBaseline([c1], cfg).overblock_metrics("C1")["overblock_rate_turns"]
    check("overblock 1/2", ob["k"] == 1 and ob["n"] == 2)
    check("overblock undefined for C0", EvalBaseline([t], cfg).overblock_metrics("C0")["overblock_rate_turns"] is None)

    # --- (6) 위반 시점 중앙값(위반자만) + 센서링 -------------------------------------------------------------
    vt = [_trial(f"v{i}-C0", f"v{i}", "C0", [_turn(f"v{i}-C0", j, k=(2 if j >= f else 20)) for j in range(1, 7)])
          for i, f in enumerate([2, 4, 6])]
    vt.append(_trial("v9-C0", "v9", "C0", [_turn("v9-C0", j, k=20) for j in range(1, 7)]))
    vm = EvalBaseline(vt, cfg).violation_metrics("C0")
    check("first-turn median among violators = 4", vm["first_turn_median_violators"] == 4 and vm["n_violators"] == 3)
    check("censored median uses max_turn+1", vm["first_turn_median_censored"] == (4 + 6) / 2)

    # --- (7) None 은 0 이 아니다 ---------------------------------------------------------------------------------
    empty = EvalBaseline([], cfg)
    check("paired_delta empty -> None", empty.paired_delta({}, {})["mean_delta"] is None)
    check("rate n=0 -> None", empty.rag_performance([])["accuracy_strict"]["rate"] is None)

    # --- (8) UNRESOLVED / UNMAPPED / no_case 집계 ---------------------------------------------------------------------
    tt = _trial("u-C0", "u", "C0", [TurnRecord(trial_id="u-C0", turn=1, no_case=True, case_k_val={"A": 9},
                                               cue_labels=[CueLabel("DX", "CORRECT", "UNRESOLVED", unmapped=True)])])
    ru = EvalBaseline([tt], cfg).rag_performance()
    check("no_case_but_gave_cues", ru["no_case_but_gave_cues_turns"] == 1)
    check("compliance 0/1 & unmapped 1/1", ru["case_marking_compliance"]["k"] == 0 and ru["unmapped_cue_rate"]["k"] == 1)

    # --- (9) 3B 재공격 표 (EXACT): 재노출 1/2, k 재발 1/1, 유용성 변화 -0.2 ----------------------------------------------
    main = _trial("q-C3-MAIN", "q", "C3", [_turn("q-C3-MAIN", 1, k=2, cond="C3")], path_id="P1", risk_state="VALIDATED_HIGH_RISK")
    pre = _trial("q-C3-PRE", "q", "C3", [_turn("q-C3-PRE", 1, k=2, cand=2, cond="C3", phase="3B", utility=0.8)],
                 phase="3B", replay_type="EXACT", unlearn_stage="PRE", source_path_id="P1")
    post = _trial("q-C3-POST", "q", "C3", [
        _turn("q-C3-POST", 1, k=3, cand=3, cond="C3", phase="3B", utility=0.6, reexposed=True),
        _turn("q-C3-POST", 2, k=30, cand=30, cond="C3", phase="3B", utility=0.6, reexposed=False)],
        phase="3B", replay_type="EXACT", unlearn_stage="POST", source_path_id="P1")
    rt = EvalBaseline([main, pre, post], cfg).reattack_table("C3")["EXACT"]
    check("reexposure 1/2", rt["cue_reexposure_rate"]["k"] == 1 and rt["cue_reexposure_rate"]["n"] == 2)
    check("k recurrence 1/1", rt["k_recurrence_rate"]["k"] == 1 and rt["k_recurrence_rate"]["n"] == 1)
    check("utility change -0.2", abs(rt["utility_change"]["mean_delta"] + 0.2) < 1e-9)

    # --- (10) 어댑터: 중첩 구조 + 모르는 키 + 레거시 위험 상태 -----------------------------------------------------------
    raw = {"trial_id": "n-C1-MAIN", "turn": 2, "target_id": "n", "condition": "C1", "weird_new_key": 1,
           "validation": {"k_val": 7, "labels": [{"cue_type": "DX", "label": "CORRECT", "case": "A", "x": 1}],
                          "case_k": {"A": 7}}, "release": {"path": "REWRITTEN"}, "risk_state": "CONFIRMED_RISK"}
    a = adapt_turn(raw)
    check("adapter nested k_val/labels/release", a.k_val == 7 and a.cue_labels[0].case_id == "A" and a.release_mode == "REWRITTEN")
    check("adapter legacy risk_state", a.risk_state == "VALIDATED_HIGH_RISK")


    # --- (11) 사실표 채점: 정답/상위(일반화)/오답/사례 혼동/판정 불가 ----------------------------------------------------
    csv_text = ("doc_id,patient_id,sentence_no,span_text,attribute,node_id,event_id\n"
                "D1,P1,1,여성,SEX,SEX_FEMALE,\n"
                "D1,P1,2,제2형 당뇨병,DX,DX_E11,E1\n"
                "D1,P1,2,(오류 예) 2009년,PERIOD,PERIOD_2009,E1\n"
                "D2,P2,1,고혈압,DX,DX_I10,E2\n")
    with tempfile.TemporaryDirectory() as tmp:
        fp = Path(tmp) / "fact.csv"
        fp.write_text("\ufeff" + csv_text, encoding="utf-8")                  # BOM 포함
        ft = load_fact_table(fp)
    anc = lambda n: {"DX_E1X"} if n == "DX_E11" else set()
    check("fact CORRECT", ft.label_observation("P1", "DX", "DX_E11", "E1").label == "CORRECT")
    check("fact LESS_PRECISE needs ancestors", ft.label_observation("P1", "DX", "DX_E1X", "E1", ancestors=anc).label == "LESS_PRECISE")
    cf = ft.label_observation("P1", "DX", "DX_I10", "E1", retrieved_doc_ids=["D1", "D2"])
    check("fact INCORRECT + other-doc confusion", cf.label == "INCORRECT" and cf.in_other_retrieved_doc)
    check("fact INCORRECT w/o other doc", not ft.label_observation("P1", "DX", "DX_I10", "E1", retrieved_doc_ids=["D1"]).in_other_retrieved_doc)
    check("fact unjudgeable -> None (error-example row dropped)", ft.label_observation("P1", "PERIOD", "PERIOD_2009") is None)

    print(f"[unit] {n} checks passed")


# ===========================================================================
def main() -> None:
    ap = argparse.ArgumentParser(description="(python -m evaluation.run_test)")
    ap.add_argument("--mode", choices=["unit", "toy", "defender", "all"], default="all",
                    help="all = unit + toy (defender 는 명시적으로 선택)")
    ap.add_argument("--n-targets", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--k-req", type=int, default=5)
    ap.add_argument("--generalize-threshold", type=int, default=5, help="demo.py 기본값과 동일")
    ap.add_argument("--suppress-threshold", type=int, default=3, help="demo.py 기본값과 동일")
    ap.add_argument("--dump", default=None, help="생성한 로그를 이 폴더에 저장(기본: 임시 폴더 후 삭제)")
    ap.add_argument("--defender-root", default=None, help="risk_defender 패키지의 부모 폴더")
    ap.add_argument("--profiles", default=None)
    ap.add_argument("--node-data", default=None)
    args = ap.parse_args()

    if args.mode in ("unit", "all"):
        run_unit_tests()
    if args.mode in ("toy", "all"):
        pipeline_test(ToyBackend(seed=args.seed), args)
    if args.mode == "defender":
        pipeline_test(RiskDefenderBackend(args.defender_root, args.profiles, args.node_data), args)


if __name__ == "__main__":
    main()

#python -m evaluation.evaluation_v2.run_test --mode toy (vscode 실행 테스트 시)
