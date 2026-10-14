# 실행 기록에서 대상별 대화를 읽는다
#
# 질문을 만든 갈래(lead arm, 보통 C0)의 턴만 쓴다. --paired 실행에서는 다른 갈래도 같은 질문과 같은 원래 답변을
# 쓰므로 원래 답변에서 뽑은 관찰은 갈래와 무관하다. 다른 갈래의 기록은 실제 실행과의 일치 확인에만 쓴다.
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orchestrator.trace_reader import arm_of, iter_sessions
from qi_extractor.schema import InferenceMode, RawObservation


@dataclass(frozen=True)
class RecordedTurn:
    """
    raw               → 원래 답변에서 뽑은 관찰 (정규화 전)
    recorded          → 실행 당시 정규화 결과 (raw_normalized 그대로)
    extraction_failed → 추출이 실패한 턴 (방어 갈래에서는 거절로 처리된다)
    usage             → 이 턴의 대상 AI·추출 호출 지연(ms)과 토큰
    """
    turn: int
    raw: tuple[RawObservation, ...]
    recorded: tuple[dict[str, Any], ...]
    extraction_failed: bool
    usage: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class LiveArm:
    """실제 실행에서 한 갈래가 턴마다 남긴 공개 State와 공개 경로 (일치 확인용)"""
    states: tuple[dict[str, str], ...]
    paths: tuple[str, ...]
    rewrite_ms: tuple[float, ...]


@dataclass(frozen=True)
class Dialogue:
    run_id: str
    target_id: str
    turns: tuple[RecordedTurn, ...]
    live: dict[str, LiveArm] = field(default_factory=dict)

    @property
    def unit(self) -> str:
        return f"{self.run_id}:{self.target_id}"


@dataclass(frozen=True)
class RunInfo:
    run_id: str
    lead_arm: str
    arms: tuple[str, ...]
    k_req: int | None
    population: str | None
    config: dict[str, Any]


def _raw_observation(item: dict[str, Any], turn: int) -> RawObservation:
    return RawObservation(
        observation_id=item["observation_id"],
        attribute=item["attribute"],
        raw_value=item.get("raw_value") or "",
        value_en=item.get("value_en"),
        inference_mode=InferenceMode(item.get("inference_mode") or "EXPLICIT"),
        confidence=int(item.get("confidence") or 0),
        evidence_spans=(),
        source_turn=int(item.get("source_turn") or turn),
    )


def _usage(item: dict[str, Any]) -> dict[str, float]:
    target, extraction = item.get("target") or {}, item.get("raw_extraction") or {}
    return {
        "target_ms": float(target.get("latency_ms") or 0.0),
        "extraction_ms": float(extraction.get("latency_ms") or 0.0),
        "target_in": float(target.get("input_tokens") or 0), "target_out": float(target.get("output_tokens") or 0),
        "extraction_in": float(extraction.get("input_tokens") or 0),
        "extraction_out": float(extraction.get("output_tokens") or 0),
        "mutation_in": float((item.get("attack") or {}).get("mutation_input_tokens") or 0),
        "mutation_out": float((item.get("attack") or {}).get("mutation_output_tokens") or 0),
    }


def read_run_info(run_dir: Path) -> RunInfo:
    config_path = run_dir / "run_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    config["_run_dir"] = str(run_dir)
    arms = tuple(config.get("arms") or ())
    risk = config.get("risk") or {}
    k_req = risk.get("k_req") or (risk.get("risk_threshold") + 1 if risk.get("risk_threshold") is not None else None)
    population = config.get("population") or {}
    pop_name = None
    if population.get("size"):
        pop_name = ("synthpai-300" if population.get("mode") == "base" else f"indep-{population['size']}")
    return RunInfo(run_dir.name, arms[0] if arms else "", arms, k_req, pop_name, config)


def load_dialogues(run_dir: Path) -> tuple[RunInfo, list[Dialogue]]:
    """
    input : run_dir (runs/<실행 이름>. trace.jsonl이 있어야 한다)
    output : (실행 정보, 대상별 대화 목록)

    대상·갈래마다 마지막으로 끝난 세션을 쓴다. LLM 오류로 멈춘 세션은 뺀다.
    lead arm은 run_config의 첫 갈래, 없으면 questions_from 표시가 없는 갈래다.
    """
    info = read_run_info(run_dir)
    latest: dict[tuple[str, str], Any] = {}
    followers: set[str] = set()
    for session in iter_sessions(run_dir / "trace.jsonl"):
        if not session.turns:
            continue
        head = session.turns[0]
        arm = arm_of(head) or ""
        if head.get("questions_from"):
            followers.add(arm)
        stop = (session.end or {}).get("stop_reason")
        if not session.finished or stop == "LLM_ERROR":
            continue
        latest[(head.get("target_id"), arm)] = session

    arms = sorted({arm for _, arm in latest})
    lead = info.lead_arm or next((arm for arm in arms if arm not in followers), arms[0] if arms else "")
    info = RunInfo(info.run_id, lead, info.arms or tuple(arms), info.k_req, info.population, info.config)

    dialogues: list[Dialogue] = []
    for (target_id, arm), session in sorted(latest.items(), key=lambda kv: _natural(kv[0][0])):
        if arm != lead:
            continue
        turns = []
        for item in session.turns:
            turn = int(item.get("turn") or len(turns) + 1)
            extraction = item.get("raw_extraction") or {}
            failed = bool(item.get("raw_extraction_error")) or not extraction
            raw = tuple(_raw_observation(o, turn) for o in extraction.get("observations") or ())
            turns.append(RecordedTurn(turn, raw, tuple(item.get("raw_normalized") or ()), failed, _usage(item)))
        live = {}
        for other in arms:
            other_session = latest.get((target_id, other))
            if other_session is None:
                continue
            states, paths, rewrite_ms = [], [], []
            for item in other_session.turns:
                states.append(dict(((item.get("commit") or {}).get("state_after")) or {}))
                release = item.get("release") or {}
                paths.append(str(release.get("path") or "ALLOWED"))
                rewrite_ms.extend(float(((r.get("rewrite") or {}).get("latency_ms")) or 0.0)
                                  for r in release.get("rounds") or ())
            live[other] = LiveArm(tuple(states), tuple(paths), tuple(rewrite_ms))
        dialogues.append(Dialogue(info.run_id, target_id, tuple(turns), live))
    return info, dialogues


def load_strata(paths: list[Path]) -> dict[str, str]:
    """target_selection.json 파일들에서 {대상 → 층(rich/sparse)}"""
    strata: dict[str, str] = {}
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in data.get("targets") or ():
            if item.get("target_id") and item.get("stratum"):
                strata[item["target_id"]] = item["stratum"]
    return strata


def _natural(target_id: str) -> tuple[str, int]:
    digits = "".join(ch for ch in str(target_id) if ch.isdigit())
    return str(target_id).rstrip("0123456789"), int(digits or 0)
