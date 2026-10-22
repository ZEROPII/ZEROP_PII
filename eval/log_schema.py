# log_schema.py
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "v7.1"

CONDITIONS = ("C0", "C1", "C1S", "C2", "C3")
PHASES = ("MAIN", "POST_RULE")
REPLAY_TYPES = ("NONE", "EXACT", "PARAPHRASE", "REORDER")
RELEASE_MODES = ("ORIGINAL", "LLM_REWRITE", "DETERMINISTIC_SUBSTITUTION", "REFUSAL")

QUESTION_TYPE_CUES: dict[str, tuple[str, ...]] = {
    "MED": ("MED",),
    "PROC": ("PROC",),
    "PLAN": ("PLAN",),
    "DX": ("DX",),
    "COURSE": ("MED", "PLAN"),
    "AGE": ("AGE",),
    "SEX": ("SEX",),
    "REGION": ("REGION",),
}


@dataclass
class CueLabel:
    case_id: str                        # 사례 ID ("A", "B" 또는 Unresolved시 "?")
    qi_type: str                        # DX / PROC / MED / PLAN / REGION / SEX / AGE
    label: str                          # CORRECT, LESS_PRECISE, INCORRECT, UNRESOLVED_CASE
    in_other_retrieved_doc: bool = False # 다른 검색 문서의 단서인지 여부

@dataclass
class TurnRecord:
    trial_id: str
    target_id: str
    condition: str
    turn: int
    phase: str = "MAIN"
    replay_type: str = "NONE"
    question_type: str = "MED"
    retrieved_doc_ids: list[str] = field(default_factory=list)
    retrieval_scores: list[float] = field(default_factory=list)
    release_mode: str = "ORIGINAL"
    refused: bool = False
    no_case: bool = False
    utility: float | None = None
    k_run: int | None = None
    k_val: int | None = None
    risk_state: str = "NOT_RISK"
    case_k_val: dict[str, int] = field(default_factory=dict)
    unresolved_case_count: int = 0
    cue_labels: list[CueLabel] = field(default_factory=list)
    answered_cue_types: list[str] = field(default_factory=list)
    reexposure: bool | None = None
    k_decreased: bool = False
    mutation_valid: bool | None = None
    latency_ms: float | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None

@dataclass
class TrialRecord:
    trial_id: str
    target_id: str
    condition: str
    phase: str = "MAIN"
    replay_type: str = "NONE"
    outcome: str = "COMPLETED"
    n_turns: int = 0
    mean_utility: float | None = None
    mutation_attempts: int = 0
    config: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

@dataclass
class RagDoc:
    doc_id: str
    icd3: str
    cue_types: list[str] = field(default_factory=list)

class ExperimentLogger:
    TURN_FILE = "턴기록.jsonl"
    TRIAL_FILE = "trial요약.json"

    def __init__(self, out_dir: str | Path):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._trials: list[TrialRecord] = []

    def log_turn(self, rec: TurnRecord) -> None:
        with (self.out_dir / self.TURN_FILE).open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")

    def add_trial(self, rec: TrialRecord) -> None:
        self._trials.append(rec)

    def flush_trials(self) -> None:
        with (self.out_dir / self.TRIAL_FILE).open("w", encoding="utf-8") as f:
            json.dump([asdict(t) for t in self._trials], f, ensure_ascii=False, indent=2)

    def reset(self) -> None:
        for name in (self.TURN_FILE, self.TRIAL_FILE):
            p = self.out_dir / name
            if p.exists():
                p.unlink()
        self._trials = []

def load_trials(path: str | Path) -> list[TrialRecord]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("trials", list(raw.values()))
    return [
        TrialRecord(
            trial_id=str(d["trial_id"]),
            target_id=str(d["target_id"]),
            condition=str(d.get("condition", "C0")),
            phase=d.get("phase", "MAIN"),
            replay_type=d.get("replay_type", "NONE"),
            outcome=str(d.get("outcome", "COMPLETED")),
            n_turns=int(d.get("n_turns", 0)),
            mean_utility=d.get("mean_utility"),
            mutation_attempts=int(d.get("mutation_attempts", 0)),
            config=d.get("config", {}),
        )
        for d in raw
    ]

def load_turns(path: str | Path, trials: Iterable[TrialRecord] | None = None) -> list[TurnRecord]:
    trial_map = {t.trial_id: t for t in (trials or [])}
    turns = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            tid = str(d["trial_id"])
            t_obj = trial_map.get(tid)
            labels = [CueLabel(**c) if isinstance(c, dict) else c for c in d.get("cue_labels", [])]
            turns.append(
                TurnRecord(
                    trial_id=tid,
                    target_id=str(d.get("target_id", t_obj.target_id if t_obj else "")),
                    condition=str(d.get("condition", t_obj.condition if t_obj else "C0")),
                    turn=int(d.get("turn", 0)),
                    phase=d.get("phase", t_obj.phase if t_obj else "MAIN"),
                    replay_type=d.get("replay_type", t_obj.replay_type if t_obj else "NONE"),
                    question_type=d.get("question_type", "MED"),
                    retrieved_doc_ids=list(d.get("retrieved_doc_ids", [])),
                    retrieval_scores=list(d.get("retrieval_scores", [])),
                    release_mode=str(d.get("release_mode", "ORIGINAL")),
                    refused=bool(d.get("refused", False)),
                    no_case=bool(d.get("no_case", False)),
                    utility=d.get("utility"),
                    k_run=d.get("k_run"),
                    k_val=d.get("k_val"),
                    risk_state=d.get("risk_state", "NOT_RISK"),
                    case_k_val=dict(d.get("case_k_val", {})),
                    unresolved_case_count=int(d.get("unresolved_case_count", 0)),
                    cue_labels=labels,
                    answered_cue_types=list(d.get("answered_cue_types", [])),
                    reexposure=d.get("reexposure"),
                    k_decreased=bool(d.get("k_decreased", False)),
                    mutation_valid=d.get("mutation_valid"),
                    latency_ms=d.get("latency_ms"),
                    tokens_in=d.get("tokens_in"),
                    tokens_out=d.get("tokens_out"),
                )
            )
    return turns

def load_docs(path: str | Path) -> dict[str, RagDoc]:
    docs = {}
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            doc_id = str(d.get("doc_id") or d.get("id"))
            docs[doc_id] = RagDoc(
                doc_id=doc_id,
                icd3=str(d.get("icd3", "")),
                cue_types=list(d.get("cue_types", [])),
            )
    return docs
