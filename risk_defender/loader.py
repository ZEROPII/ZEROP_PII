# Synthea 기반 의료 데이터를 읽어서 QI를 추출하는 파일
# 기본: user_patient_profiles_576.json (미리 처리된 파일)
# 노드 계층(노드_v0.9.csv)은 매칭/일반화에 여전히 필요하다.

from __future__ import annotations

import csv
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schema import DEFAULT_QI_ORDER, normalize_qi_value

# 모듈 수준 노드 레지스트리: node_id → {attribute, canonical_label, parent_id, depth}
NODE_REGISTRY: dict[str, dict[str, Any]] = {}

# 프로젝트 내 데이터 기본 경로
_DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_NODE_PATH = _DATA_DIR / "노드_v0.9.csv"
DEFAULT_EVENT_PATH = _DATA_DIR / "사건연결표_v0.9.csv"
DEFAULT_PROFILES_PATH = _DATA_DIR / "user_patient_profiles_576.json"

# event_type → QI 키 매핑 (CSV에서 직접 로드할 때 사용)
_EVENT_TYPE_TO_QI: dict[str, str] = {
    "CONDITION": "DX",
    "PROCEDURE": "PROC",
    "PROCEDURE_HISTORY": "PROC",  # 과거 시술 이력도 PROC으로 포함
    "MEDICATION": "MED",
    "CAREPLAN": "PLAN",
}


@dataclass(frozen=True)
class PersonaRecord:
    person_id: str
    username: str | None
    qis: dict[str, Any]
    raw_profile: dict[str, Any]
    source_texts: list[str]


def load_node_registry(path: str | Path = DEFAULT_NODE_PATH) -> dict[str, dict[str, Any]]:
    """노드 테이블을 읽어 NODE_REGISTRY를 채우고 반환한다."""
    global NODE_REGISTRY
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"노드 파일을 찾을 수 없음: {path}")

    registry: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            node_id = row["node_id"].strip()
            registry[node_id] = {
                "attribute": row.get("attribute", "").strip(),
                "canonical_label": row.get("canonical_label", "").strip(),
                "parent_id": row.get("parent_id", "").strip() or None,
                "depth": int(row.get("depth") or 0),
            }

    NODE_REGISTRY = registry
    return registry


def load_population(
    profiles_path: str | Path = DEFAULT_PROFILES_PATH,
    node_path: str | Path = DEFAULT_NODE_PATH,
) -> list[PersonaRecord]:
    """미리 처리된 JSON에서 576명 환자 프로필을 로드한다.
    node_path의 노드 계층은 매칭/일반화에 필요하므로 항상 로드한다.
    """
    load_node_registry(node_path)

    profiles_path = Path(profiles_path)
    if not profiles_path.exists():
        raise FileNotFoundError(f"환자 프로필 파일을 찾을 수 없음: {profiles_path}")

    with profiles_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    return [
        PersonaRecord(
            person_id=entry["person_id"],
            username=None,
            qis=entry["qis"],
            raw_profile={},
            source_texts=[],
        )
        for entry in raw
    ]


def load_expanded_population(
    profiles_path: str | Path = DEFAULT_PROFILES_PATH,
    node_path: str | Path = DEFAULT_NODE_PATH,
    synth_path: str | Path | None = None,
) -> list[PersonaRecord]:
    """load_population의 별칭. 인터페이스 호환성 유지용."""
    return load_population(profiles_path, node_path)


def load_population_from_csv(
    event_path: str | Path = DEFAULT_EVENT_PATH,
    node_path: str | Path = DEFAULT_NODE_PATH,
    *,
    seed: int | None = 42,
    max_per_qi: int = 5,
) -> list[PersonaRecord]:
    """사건연결표 CSV를 직접 읽어 환자별 PersonaRecord를 생성한다.

    seed=None이면 모든 이벤트를 수집(제한 없음).
    seed가 주어지면 환자별로 1~max_per_qi개 샘플링(재현 가능).
    """
    load_node_registry(node_path)

    event_path = Path(event_path)
    if not event_path.exists():
        raise FileNotFoundError(f"사건연결표 파일을 찾을 수 없음: {event_path}")

    patient_events: dict[str, list[dict[str, str]]] = {}
    with event_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            pid = row["patient_id"].strip()
            patient_events.setdefault(pid, []).append(dict(row))

    rng = random.Random(seed) if seed is not None else None

    records: list[PersonaRecord] = []
    for pid, events in patient_events.items():
        qis = _aggregate_patient_qis(events, rng=rng, max_per_qi=max_per_qi)
        records.append(PersonaRecord(
            person_id=pid,
            username=None,
            qis=qis,
            raw_profile={},
            source_texts=[],
        ))

    return records


def _aggregate_patient_qis(
    events: list[dict[str, str]],
    *,
    rng: "random.Random | None" = None,
    max_per_qi: int = 5,
    min_per_qi: int = 1,
    qi_count_weights: "list[float] | None" = None,
) -> dict[str, Any]:
    """환자의 이벤트 목록에서 QI 딕셔너리를 추출한다.

    DX/PROC/MED/PLAN은 {"code", "age", "date"} 번들 리스트로 수집한다.
    rng가 주어지면 1~max_per_qi 범위에서 랜덤 샘플링, 없으면 전체 수집.
    PERIOD는 독립 필드 없이 각 이벤트 번들의 "date" 키로 내포된다.
    """
    from .schema import MULTI_VALUE_QIS  # noqa: PLC0415

    sorted_events = sorted(events, key=lambda e: e.get("start") or "")

    first = sorted_events[0]
    raw_qis: dict[str, Any] = {
        "SEX": first.get("sex_node") or None,
        "REGION": first.get("region_node") or None,
    }

    # 이벤트별 번들 수집 (code 기준 중복 제거, 날짜순)
    multi_pool: dict[str, list[dict[str, str]]] = {qi: [] for qi in MULTI_VALUE_QIS}
    seen_codes: dict[str, set[str]] = {qi: set() for qi in MULTI_VALUE_QIS}

    for event in sorted_events:
        etype = event.get("event_type", "").strip()
        qi_key = _EVENT_TYPE_TO_QI.get(etype)
        if not qi_key:
            continue
        code_node = (event.get("code_node") or "").strip()
        if not code_node or code_node in seen_codes[qi_key]:
            continue
        seen_codes[qi_key].add(code_node)
        entry: dict[str, str] = {"code": code_node}
        age_node = (event.get("age_node") or "").strip()
        period_node = (event.get("period_start_node") or "").strip()
        period_end_node = (event.get("period_end_node") or "").strip()
        if age_node:
            entry["age"] = age_node
        if period_node:
            entry["date"] = period_node
        if period_end_node:
            entry["date_end"] = period_end_node
        multi_pool[qi_key].append(entry)

    # qi_count_weights 기본값: avg 2.6 타깃 (1~5)
    weights = qi_count_weights or [0.25, 0.25, 0.25, 0.15, 0.10]

    for qi_key, pool in multi_pool.items():
        if not pool:
            raw_qis[qi_key] = None
            continue
        if rng is not None:
            n = rng.choices(range(min_per_qi, max_per_qi + 1), weights=weights)[0]
            n = min(n, len(pool))
            raw_qis[qi_key] = pool[:n]
        else:
            raw_qis[qi_key] = pool

    result: dict[str, Any] = {}
    for qi_type in DEFAULT_QI_ORDER:
        raw = raw_qis.get(qi_type)
        if qi_type in MULTI_VALUE_QIS:
            if raw:
                result[qi_type] = raw
        else:
            normalized = normalize_qi_value(qi_type, raw)
            if normalized is not None:
                result[qi_type] = normalized
    return result
