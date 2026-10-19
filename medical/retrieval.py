# 대상 AI 앞단: 유사 환자 검색(하네스 명세 §4.1)과 질의 환자 바인딩(§5)
#
# 검색: ExpRAG식 코드 집합 유사도. DX(CONDITION code)·MED(RxNorm)·PROC(PROCEDURE·PROCEDURE_HISTORY code)를
#   원 코드 그대로 쓰고, 점수 = (J_DX + J_MED + J_PROC) / 3. 상위 k명, 동점은 patient_id 오름차순.
#   질의 환자는 기준일(index_date)까지의 사건만. trial마다 턴 0에 한 번만 검색한다.
# 바인딩: 질의 환자의 대표 진단 범주(ICD 3자리), 기준 사건 당시 10년 구간, 성별, 유형별 관련 항목 하나.
#   질문에 넣은 질의 환자 값은 사례 환자의 공개로 세지 않는다 (추출기 subject=OTHER).

from __future__ import annotations

import collections
import random
from typing import Any

from medical.data import MedicalData

QTYPES = ("PRESCRIPTION", "TREATMENT_PROCEDURE", "COURSE_CARE")
_AXIS = {"CONDITION": "DX", "MEDICATION": "MED", "PROCEDURE": "PROC", "PROCEDURE_HISTORY": "PROC"}


def _d10(ts: str) -> str:
    return ts[:10] if ts else ""


def code_sets(events: list[dict[str, str]], until: str | None = None) -> dict[str, set[str]]:
    s: dict[str, set[str]] = {"DX": set(), "MED": set(), "PROC": set()}
    for e in events:
        if until and (_d10(e["start"]) or _d10(e["record_date"])) > until:
            continue
        t = _AXIS.get(e["event_type"])
        if t:
            s[t].add(e["code"])
    return s


def similarity(a: dict[str, set[str]], b: dict[str, set[str]]) -> float:
    def j(x: set[str], y: set[str]) -> float:
        return len(x & y) / len(x | y) if (x | y) else 0.0
    return sum(j(a[t], b[t]) for t in ("DX", "MED", "PROC")) / 3


def retrieve(q_sets: dict[str, set[str]], store_sets: dict[str, dict[str, set[str]]], k: int) -> list[tuple[str, float]]:
    ranked = sorted(store_sets.items(), key=lambda kv: (-similarity(q_sets, kv[1]), kv[0]))[:k]
    return [(p, round(similarity(q_sets, s), 6)) for p, s in ranked]


def query_binding(data: MedicalData, pid: str, qtype: str, rng: random.Random) -> dict[str, Any] | None:
    """명세 §5. 관련 항목이 없거나 진단 범주가 없으면 None (그 유형의 trial에서 제외)."""
    cond = [e for e in data.by_pat[pid] if e["event_type"] == "CONDITION"]
    cat: dict[str, list[dict[str, str]]] = collections.defaultdict(list)
    for e in cond:
        c = next((a for a in data.anc(e["code_node"]) if a.startswith("DX_ICD_CODE_") and len(data.N[a]["standard_code"]) == 3), None)
        if c:
            cat[c].append(e)
    if not cat:
        return None
    main = sorted(cat, key=lambda c: (-len(cat[c]), min(_d10(e["start"]) for e in cat[c]), c))[0]
    idx = min(cat[main], key=lambda e: (_d10(e["start"]), e["event_id"]))
    day, age = _d10(idx["start"]), int(idx["age_years_at_start"])
    ev = data.by_pat[pid]

    def lab_of(e: dict[str, str], prefix: str) -> str | None:
        a = next((x for x in data.anc(e["code_node"]) if x.startswith(prefix)), None)
        return data.label(a) if a else None

    def med_of(e: dict[str, str]) -> str:   # 성분(IN) → 성분+제형(DF) → 약 이름 그대로
        return lab_of(e, "MED_IN_") or lab_of(e, "MED_DF_") or data.label(e["code_node"])

    if qtype == "PRESCRIPTION":
        items = [med_of(e) for e in ev if e["event_type"] == "MEDICATION" and _d10(e["start"]) <= day and (not e["stop"] or _d10(e["stop"]) >= day)]
    elif qtype == "TREATMENT_PROCEDURE":
        items = [lab_of(e, "PROC_GROUP_") for e in ev if e["event_type"] == "PROCEDURE" and _d10(e["start"]) >= day]
    else:
        items = [med_of(e) for e in ev if e["event_type"] == "MEDICATION" and _d10(e["start"]) >= day] + \
                [data.label(e["code_node"]) for e in ev if e["event_type"] == "CAREPLAN" and _d10(e["start"]) >= day]
    clean = sorted({i for i in items if i})
    if not clean:
        return None
    return dict(QUERY_AGE_BAND=("10세 미만" if age < 10 else f"{age // 10 * 10}대"),
                QUERY_SEX="남성" if ev[0]["sex_node"] == "SEX_MALE" else "여성",
                QUERY_MAIN_DX=data.label(main), QUERY_RELATED_ITEM=rng.choice(clean),
                index_event=idx["event_id"], index_date=day, main_dx_node=main)


def fill_case_query(template: str, binding: dict[str, Any]) -> str:
    out = template
    for k, v in binding.items():
        if k.startswith("QUERY_"):
            out = out.replace(f"[{k}]", str(v))
    return out
