"""
log_schema.py  (스키마 v7.2)
=====================================================================
Privacy Fuzzer + Adaptive Defender 평가용 "로그 스키마 + 로더(어댑터)".

이 파일이 하는 일 (3가지)
  1) 로그 한 줄/한 건이 어떤 필드를 가져야 하는지 정의한다. (TurnRecord, TrialRecord)
  2) 허용되는 값(조건 C0~C3, 위험 상태 4종 등)을 상수로 정의하고 검증한다.
  3) 팀 파이프라인의 실제 파일(중첩 구조)과 평탄(flat) 구조를 모두 읽는 어댑터를 제공한다.

v7.1 -> v7.2 변경점
  - [추가] k_val_candidate / case_k_val_candidate : "방어 '전' 후보 응답"의 k.
           과잉 차단을 "방어 후 k"로 재면 방어 성공 턴이 과잉 차단으로 잡히는 오류가 있었다.
  - [추가] path_id / source_path_id : 재공격 trial을 원래 위험 경로에 연결(k 재발률 분모용).
  - [추가] RISK_STATES : 설계보고서 §11.23 Path Validation Status 5종 + NONE (기존엔 "NOT_RISK" 기본값 하나뿐).
  - [추가] unmapped(CueLabel), rule_id, reexposed, mutation_valid, tokens/latency 등.
  - [수정] CueLabel.from_dict : JSON에 모르는 키가 더 있어도 깨지지 않고 무시한다.
  - [수정] 한글 파일명 대신 ASCII 이름을 우선 탐색하고, 모든 파일 I/O에 encoding="utf-8" 명시.
  - [추가] 중첩 구조(validation.k_val 등) <-> 평탄 구조 어댑터(adapt_turn / adapt_trial).
  - [추가] CONDITIONS / PHASES 등 상수 검증(validate_*).

  확인 필요 (코드에 가정으로 박아둠, 아래 "ASSUMPTION" 표시)
  - validation.labels 가 trial 단위인지 turn 단위인지  -> _distribute_trial_labels() 참고
  - validation.flag 값의 의미(평가 불가 표시)         -> _flag_means_unevaluable() 참고
  - turn 번호는 1부터 시작한다고 가정(평가의 max_turn 필터가 turn<=max_turn 이므로)
"""
from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


# ---------------------------------------------------------------------------
# 1. 허용 값 상수 (오타 방지용. validate_*에서 검사한다)
# ---------------------------------------------------------------------------
CONDITIONS = ("C0", "C1", "C1S", "C2", "C3")
#  C0 무방어 / C1 Defender / C1S Stateless 대조군 / C2 Unlearning-only / C3 Defender+Unlearning

PHASES = ("MAIN", "3A", "3B")
#  MAIN 본실험 / 3A 방어 효과 재검증(Replay) / 3B 경량 언러닝 재검증

REPLAY_TYPES = ("NONE", "EXACT", "PARAPHRASE", "REORDER")
#  NONE 재공격 아님 / EXACT 원 질문 그대로 / PARAPHRASE 바꾼 표현 / REORDER 바꾼 순서

UNLEARN_STAGES = ("NA", "PRE", "POST")  # NA = 언러닝과 무관한 trial

RISK_STATES = (
    # 설계보고서 §11.23 Path Validation Status (그대로 사용) + "NONE"(위험 후보가 아닌 trial/턴)
    "NONE",                       # 위험 후보 아님 (기본값)
    "RUNTIME_HIGH_RISK_CANDIDATE",  # 실행 중 k_run 기준 위험 후보 (정답 확인 전)
    "PENDING_VALIDATION",         # 사후 검증 대기
    "VALIDATED_HIGH_RISK",        # 정답으로 확인된 위험 (1 <= k_val < k_req)  <- 규칙/재발률 분모
    "VALIDATED_NOT_HIGH_RISK",    # 검증했더니 위험 아님 (추출기 오탐/위험 과대평가 분석 자료)
    "ZERO_MATCH_QUARANTINED",     # k_run=0 격리 (성공 아님, 검증 후 재분류)
)
LEGACY_RISK_STATES = {"NOT_RISK": "NONE", "CONFIRMED_RISK": "VALIDATED_HIGH_RISK",
                      "CANDIDATE_RISK": "RUNTIME_HIGH_RISK_CANDIDATE",
                      "ZERO_MATCH_QUARANTINE": "ZERO_MATCH_QUARANTINED"}  # v7.2 초안 값 호환

FACT_LABELS = ("CORRECT", "LESS_PRECISE", "INCORRECT")  # INCORRECT = 환각
RELEASE_MODES = ("PASSTHROUGH", "ALLOWED", "REWRITTEN", "REFUSAL")
MODIFIED_MODES = ("REWRITTEN", "REFUSAL")  # "방어가 응답을 건드렸다"로 보는 모드

CASE_UNRESOLVED = "UNRESOLVED"  # 어느 사례(A/B/..)의 단서인지 못 정한 경우의 case_id

FILENAMES = {
    "trials": ("trial_summary.json", "trial요약.json"),
    "turns": ("turn_log.jsonl", "턴기록.jsonl"),
    "docs": ("rag_docs.jsonl", "RAG문서.jsonl"),
    "facts": ("fact_table.csv", "사실표.csv"),
    "usage": ("llm_usage.jsonl",),
}


class SchemaError(ValueError):
    """strict=True 로 읽을 때 스키마 위반이 있으면 발생."""


# ---------------------------------------------------------------------------
# 2. 레코드 정의
# ---------------------------------------------------------------------------
@dataclass
class CueLabel:
    """응답에서 추출한 '단서(cue)' 1개에 대한 채점 결과. (정확도는 단서 단위로 채점)"""

    cue_type: str = "UNKNOWN"          # 예: DX / PROC / MED / AGE ...
    label: str = "CORRECT"             # FACT_LABELS 중 하나
    case_id: Optional[str] = None      # "A","B",... 또는 CASE_UNRESOLVED(사례 표기 실패)
    in_other_retrieved_doc: bool = False  # 정답 사례가 아니라 '다른 검색 문서'의 사실이면 True (사례 혼동)
    unmapped: bool = False             # 진단명 한국어 번역/정규화 실패(UNMAPPED)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CueLabel":
        """모르는 키는 무시한다. (기존 CueLabel(**c) 는 키가 더 있으면 TypeError)"""
        known = {f.name for f in fields(cls)}
        # 팀 로그가 'case' 또는 'cue_label' 같은 다른 이름을 쓸 가능성에 대한 최소 호환
        d = dict(d)
        if "label" not in d and "cue_label" in d:
            d["label"] = d["cue_label"]
        if "case_id" not in d and "case" in d:
            d["case_id"] = d["case"]
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class TurnRecord:
    """턴 1개의 기록 (턴기록.jsonl 한 줄)."""

    trial_id: str
    turn: int                                   # 1부터 시작한다고 가정
    target_id: str = ""
    condition: str = "C0"
    phase: str = "MAIN"
    question_type: str = "UNKNOWN"              # MED / PROC / COURSE ... (질문 유형별 정확도 분해용)
    replay_type: str = "NONE"
    unlearn_stage: str = "NA"

    # --- k 값 (k_run = 추정, k_val = 정답으로 검증된 값) ---
    k_run: Optional[int] = None
    k_val: Optional[int] = None                 # 방어 '후'(실제 공개된 응답) 기준 검증 k
    k_val_candidate: Optional[int] = None       # [v7.2] 방어 '전' 후보 응답 기준 검증 k
    case_k_val: Dict[str, Optional[int]] = field(default_factory=dict)            # {"A":k,...} 방어 후
    case_k_val_candidate: Dict[str, Optional[int]] = field(default_factory=dict)  # [v7.2] 방어 전

    # --- 응답 채점 ---
    cue_labels: List[CueLabel] = field(default_factory=list)
    expected_cues: Optional[int] = None         # 답에 있어야 했던 단서 수 (누락률 분모)
    omitted_cues: Optional[int] = None          # 그중 빠뜨린 수 (누락률 분자)
    no_case: bool = False                       # "비슷한 사례 없음"이라고 답했는가
    refused: bool = False                       # 거절했는가
    release_mode: str = "PASSTHROUGH"
    utility: Optional[float] = None             # 공개 QI 유지율 등 유용성 (0~1)

    # --- 공격/위험 ---
    mutation_attempts: int = 0
    mutation_valid: int = 0
    k_decreased: Optional[bool] = None
    reexposed: Optional[bool] = None            # 언러닝 후 단서가 다시 노출됐는가 (3B)
    risk_state: str = "NONE"
    rule_id: Optional[str] = None               # 적용된 방어 규칙 ID (규칙 적중률용, 선택)
    path_id: Optional[str] = None

    # --- 비용 ---
    latency_ms: Optional[float] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None

    evaluable: bool = True                      # False면 정답 대조 불가(통계에서 제외)
    trial_id: str
    turn: int 
    cue_labels: List[CueLabel] = field(default_factory=list)
    # (중략... 나머지 필드들)

    def get_cue_accuracy(self) -> float:
        """이 턴에 속한 여러 단서들의 평균 정확도를 계산합니다."""
        if not self.cue_labels:
            return 0.0
        correct_count = sum(1 for cue in self.cue_labels if cue.label == "CORRECT")
        return correct_count / len(self.cue_labels)

@dataclass
class TrialRecord:
    """trial 1개 = (대상 1명 x 조건 1개 x 단계 1개) 의 세션 요약 + 턴 목록."""

    trial_id: str
    target_id: str
    condition: str = "C0"
    phase: str = "MAIN"
    replay_type: str = "NONE"
    unlearn_stage: str = "NA"
    path_id: Optional[str] = None               # 이 trial이 속한 위험 경로
    source_path_id: Optional[str] = None        # 재공격이면 '원본' 위험 경로 id
    outcome: str = ""
    risk_state: str = "NONE"
    case_k: Dict[str, Optional[int]] = field(default_factory=dict)
    retrieved_doc_ids: List[str] = field(default_factory=list)
    retrieval_scores: List[float] = field(default_factory=list)
    binding: Any = None
    mean_utility: Optional[float] = None
    release_modes: Dict[str, int] = field(default_factory=dict)
    mutation_attempts: int = 0
    mutation_valid: int = 0
    evaluable: bool = True
    turns: List[TurnRecord] = field(default_factory=list)

    def get_all_cues(self) -> List[CueLabel]:
        """트라이얼 내 모든 턴의 단서들을 하나의 리스트로 합쳐서 반환합니다."""
        all_cues = []
        for turn in self.turns:
            all_cues.extend(turn.cue_labels)
        return all_cues


# ---------------------------------------------------------------------------
# 3. 검증
# ---------------------------------------------------------------------------
def _check(value: str, allowed: Iterable[str], name: str, where: str, out: List[str]) -> None:
    if value not in allowed:
        out.append(f"{where}: {name}='{value}' (허용: {tuple(allowed)})")


def validate_turn(t: TurnRecord) -> List[str]:
    """문제 목록을 돌려준다(빈 리스트면 정상)."""
    p: List[str] = []
    w = f"turn {t.trial_id}#{t.turn}"
    _check(t.condition, CONDITIONS, "condition", w, p)
    _check(t.phase, PHASES, "phase", w, p)
    _check(t.replay_type, REPLAY_TYPES, "replay_type", w, p)
    _check(t.unlearn_stage, UNLEARN_STAGES, "unlearn_stage", w, p)
    _check(t.risk_state, RISK_STATES, "risk_state", w, p)
    _check(t.release_mode, RELEASE_MODES, "release_mode", w, p)
    for c in t.cue_labels:
        _check(c.label, FACT_LABELS, "cue.label", w, p)
    if t.omitted_cues is not None and t.expected_cues is not None and t.omitted_cues > t.expected_cues:
        p.append(f"{w}: omitted_cues({t.omitted_cues}) > expected_cues({t.expected_cues})")
    return p


def validate_trial(t: TrialRecord) -> List[str]:
    p: List[str] = []
    w = f"trial {t.trial_id}"
    _check(t.condition, CONDITIONS, "condition", w, p)
    _check(t.phase, PHASES, "phase", w, p)
    _check(t.replay_type, REPLAY_TYPES, "replay_type", w, p)
    _check(t.unlearn_stage, UNLEARN_STAGES, "unlearn_stage", w, p)
    _check(t.risk_state, RISK_STATES, "risk_state", w, p)
    for x in t.turns:
        p.extend(validate_turn(x))
    return p


# ---------------------------------------------------------------------------
# 4. 어댑터: 실제 팀 로그(중첩) / 평탄 구조 -> 위 dataclass
# ---------------------------------------------------------------------------
def _g(d: Any, path: str, default: Any = None) -> Any:
    """'a.b.c' 경로로 중첩 dict를 안전하게 읽는다. 중간에 끊기면 default."""
    cur = d
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def _first(*vals: Any) -> Any:
    """None이 아닌 첫 값. (0이나 빈 dict를 'or'로 잃어버리지 않기 위해 or 대신 사용)"""
    for v in vals:
        if v is not None:
            return v
    return None


def _flag_means_unevaluable(flag: Any) -> bool:
    """ASSUMPTION: validation.flag 에 'UNEVALUABLE' 류 문자열이 들어오면 평가 불가로 본다.
    팀 파이프라인의 실제 flag 값 목록을 확인한 뒤 이 함수만 고치면 된다."""
    return isinstance(flag, str) and "UNEVAL" in flag.upper()


def _distribute_trial_labels(trial_raw: Dict[str, Any], by_turn: Dict[int, List[dict]]) -> None:
    """ASSUMPTION: validation.labels 의 단위가 불확실하므로 3가지 모양을 모두 받는다.
       (a) dict  {"1":[...], "2":[...]}  -> 턴 키로 분배
       (b) list  of dict with "turn" key -> 그 턴으로 분배
       (c) 키 없는 list                  -> 분배 불가: 경고만 하고 버린다(잘못 붙이는 것보다 안전)
    """
    labels = _g(trial_raw, "validation.labels")
    if labels is None:
        return
    if isinstance(labels, dict):
        for k, v in labels.items():
            by_turn.setdefault(int(k), []).extend(v)
    elif isinstance(labels, list):
        if labels and all(isinstance(x, dict) and "turn" in x for x in labels):
            for x in labels:
                by_turn.setdefault(int(x["turn"]), []).append(x)
        elif labels:
            warnings.warn(
                f"trial {trial_raw.get('trial_id')}: validation.labels 가 턴 정보 없는 리스트라 "
                "턴에 분배하지 못했습니다. (trial 단위 라벨인지 팀에 확인 필요)"
            )


def adapt_turn(raw: Dict[str, Any], trial_defaults: Optional[Dict[str, Any]] = None) -> TurnRecord:
    """턴 로그 1줄(dict)을 TurnRecord로. 평탄/중첩 구조 모두 지원."""
    td = trial_defaults or {}
    lab_raw = _first(raw.get("cue_labels"), _g(raw, "validation.labels"), [])
    labels = [CueLabel.from_dict(c) for c in lab_raw if isinstance(c, dict)]
    rel = _first(raw.get("release_mode"), _g(raw, "release.path"), "PASSTHROUGH")
    flag = _g(raw, "validation.flag")
    return TurnRecord(
        trial_id=raw.get("trial_id", td.get("trial_id", "")),
        turn=int(raw["turn"]),
        target_id=_first(raw.get("target_id"), td.get("target_id"), ""),
        condition=_first(raw.get("condition"), td.get("condition"), "C0"),
        phase=_first(raw.get("phase"), td.get("phase"), "MAIN"),
        question_type=_first(raw.get("question_type"), "UNKNOWN"),
        replay_type=_first(raw.get("replay_type"), td.get("replay_type"), "NONE"),
        unlearn_stage=_first(raw.get("unlearn_stage"), td.get("unlearn_stage"), "NA"),
        k_run=raw.get("k_run"),
        k_val=_first(raw.get("k_val"), _g(raw, "validation.k_val")),
        k_val_candidate=_first(raw.get("k_val_candidate"), _g(raw, "validation.k_val_candidate")),
        case_k_val=dict(_first(raw.get("case_k_val"), raw.get("case_k"), _g(raw, "validation.case_k"), {})),
        case_k_val_candidate=dict(
            _first(raw.get("case_k_val_candidate"), _g(raw, "validation.case_k_candidate"), {})
        ),
        cue_labels=labels,
        expected_cues=raw.get("expected_cues"),
        omitted_cues=raw.get("omitted_cues"),
        no_case=bool(raw.get("no_case", False)),
        refused=bool(raw.get("refused", False)),
        release_mode=rel,
        utility=_first(raw.get("utility"), raw.get("utility_score")),
        mutation_attempts=int(raw.get("mutation_attempts") or 0),
        mutation_valid=int(raw.get("mutation_valid") or 0),
        k_decreased=raw.get("k_decreased"),
        reexposed=raw.get("reexposed", raw.get("reexposure")),
        risk_state=LEGACY_RISK_STATES.get(_first(raw.get("risk_state"), "NONE"), _first(raw.get("risk_state"), "NONE")),
        rule_id=raw.get("rule_id"),
        path_id=_first(raw.get("path_id"), td.get("path_id")),
        latency_ms=raw.get("latency_ms"),
        tokens_in=raw.get("tokens_in"),
        tokens_out=raw.get("tokens_out"),
        evaluable=bool(raw.get("evaluable", True)) and not _flag_means_unevaluable(flag),
    )


def adapt_trial(raw: Dict[str, Any]) -> TrialRecord:
    """trial요약 1건(dict)을 TrialRecord로(턴은 아직 비어 있음)."""
    flag = _g(raw, "validation.flag")
    return TrialRecord(
        trial_id=raw["trial_id"],
        target_id=raw.get("target_id", ""),
        condition=raw.get("condition", "C0"),
        phase=raw.get("phase", "MAIN"),
        replay_type=raw.get("replay_type", "NONE"),
        unlearn_stage=raw.get("unlearn_stage", "NA"),
        path_id=raw.get("path_id"),
        source_path_id=raw.get("source_path_id"),
        outcome=raw.get("outcome", ""),
        risk_state=LEGACY_RISK_STATES.get(raw.get("risk_state", "NONE"), raw.get("risk_state", "NONE")),
        case_k=dict(_first(raw.get("case_k"), _g(raw, "validation.case_k"), {})),
        retrieved_doc_ids=list(raw.get("retrieved_doc_ids") or []),
        retrieval_scores=list(raw.get("retrieval_scores") or []),
        binding=raw.get("binding"),
        mean_utility=raw.get("mean_utility"),
        release_modes=dict(raw.get("release_modes") or {}),
        mutation_attempts=int(raw.get("mutation_attempts") or 0),
        mutation_valid=int(raw.get("mutation_valid") or 0),
        evaluable=bool(raw.get("evaluable", True)) and not _flag_means_unevaluable(flag),
    )


# ---------------------------------------------------------------------------
# 5. 파일 로더
# ---------------------------------------------------------------------------
def find_file(folder: Path, key: str) -> Optional[Path]:
    """FILENAMES[key] 후보를 순서대로 찾는다(ASCII 우선, 한글 폴백)."""
    for name in FILENAMES[key]:
        p = Path(folder) / name
        if p.exists():
            return p
    return None


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                warnings.warn(f"{path.name}:{ln} JSON 오류, 건너뜀: {e}")
    return rows


def load_trials(folder: str | Path, strict: bool = False) -> List[TrialRecord]:
    """폴더에서 trial 요약 + 턴 기록을 읽어 TrialRecord 리스트로 합친다.

    strict=True  : 스키마 위반이 하나라도 있으면 SchemaError (본실험 전 점검용)
    strict=False : 경고만 내고 계속 (탐색용)
    """
    folder = Path(folder)
    tpath, upath = find_file(folder, "trials"), find_file(folder, "turns")
    if tpath is None:
        raise FileNotFoundError(f"{folder} 에서 trial 요약 파일을 찾지 못함 {FILENAMES['trials']}")
    with open(tpath, encoding="utf-8") as f:
        raw_trials = json.load(f)
    if isinstance(raw_trials, dict):  # {"trials":[...]} 또는 {trial_id: {...}} 둘 다 허용
        raw_trials = raw_trials.get("trials") or [
            {"trial_id": k, **v} for k, v in raw_trials.items()
        ]

    raw_turns = _read_jsonl(upath) if upath else []
    turns_by_trial: Dict[str, List[dict]] = {}
    for r in raw_turns:
        turns_by_trial.setdefault(r.get("trial_id", ""), []).append(r)

    trials: List[TrialRecord] = []
    for rt in raw_trials:
        tr = adapt_trial(rt)
        defaults = {
            "trial_id": tr.trial_id, "target_id": tr.target_id, "condition": tr.condition,
            "phase": tr.phase, "replay_type": tr.replay_type,
            "unlearn_stage": tr.unlearn_stage, "path_id": tr.path_id,
        }
        # trial 단위 라벨이 있으면 턴으로 분배 (ASSUMPTION 참고)
        trial_labels: Dict[int, List[dict]] = {}
        _distribute_trial_labels(rt, trial_labels)
        turn_rows = turns_by_trial.get(tr.trial_id, [])
        for r in turn_rows:
            if not r.get("cue_labels") and not _g(r, "validation.labels") and int(r["turn"]) in trial_labels:
                r = {**r, "cue_labels": trial_labels[int(r["turn"])]}
            tr.turns.append(adapt_turn(r, defaults))
        tr.turns.sort(key=lambda x: x.turn)
        trials.append(tr)

    problems = [m for t in trials for m in validate_trial(t)]
    if problems:
        msg = f"스키마 위반 {len(problems)}건 (앞 5건): " + " | ".join(problems[:5])
        if strict:
            raise SchemaError(msg)
        warnings.warn(msg)
    return trials


def load_llm_usage(folder: str | Path) -> Dict[str, Dict[str, float]]:
    """llm_usage.jsonl -> {trial_id: {latency_ms, tokens_in, tokens_out}} (trial별 합계).
    ASSUMPTION: 각 줄이 trial_id, latency_ms, tokens_in, tokens_out 키를 가진다."""
    p = find_file(Path(folder), "usage")
    out: Dict[str, Dict[str, float]] = {}
    if p is None:
        return out
    for r in _read_jsonl(p):
        d = out.setdefault(r.get("trial_id", ""), {"latency_ms": 0.0, "tokens_in": 0, "tokens_out": 0})
        d["latency_ms"] += float(r.get("latency_ms") or 0)
        d["tokens_in"] += int(r.get("tokens_in") or 0)
        d["tokens_out"] += int(r.get("tokens_out") or 0)
    return out
