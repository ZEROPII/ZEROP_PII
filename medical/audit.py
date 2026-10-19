# 기준 집단 사전 점검 (설계보고서 §2.30, §7.22) — 공격·방어 실행 전에 한 번 계산하는 기술통계 (LLM 0)
#
# 질문: 기준 집단(P_ref = RAG 저장소 환자)에서 단서를 1개, 2개, 3개… 공개하면 k가 얼마나 빨리 k_req 아래로 내려가는가.
#   적은 단서만으로 대부분 k < k_req가 된다면 갈래(C0·C1·C1S) 사이 차이가 '위반 도달 여부'로는 잘 안 드러날 수 있다.
#
# 공개 순서 (환자마다 같은 규칙, GT로 고른 값이 아니라 그 환자의 실제 기록값):
#   SEX → REGION → DX(대표 진단) → AGE(그 진단 당시) → PERIOD(그 진단 시작일) → MED(첫 처방) → PLAN(첫 관리 계획)
#   대표 진단 = ICD-10-CM 3자리 범주로 올려 사건 수가 가장 많은 범주의 가장 이른 사건 (하네스 명세 §5 질의 환자 규칙과 같음)
#   사건 단위 단서(DX·AGE·PERIOD)는 같은 사건 묶음으로 넘긴다. MED·PLAN은 각각 다른 사건.
# 넓은 수준(coarse): AGE → 10년 구간, PERIOD → 연도, DX → ICD 3자리 범주, MED → 성분(IN, 없으면 그대로), PLAN 그대로
#   (REGION은 데이터 전체가 한 주(Massachusetts)라 주 수준은 후보를 줄이지 않는다)
#
# 이 계산은 실행 코드가 쓰지 않는다. 해석 기준선으로만 보고한다.

from __future__ import annotations

import collections
import json
import statistics
from pathlib import Path
from typing import Any

from medical.bundle.kcalc import KCalc
from medical.data import MedicalData

ORDER = ("SEX", "REGION", "DX", "AGE", "PERIOD", "MED", "PLAN")


def _icd3(data: MedicalData, node: str) -> str | None:
    return next((a for a in data.anc(node) if a.startswith("DX_ICD_CODE_") and len(data.N[a]["standard_code"]) == 3), None)


def representative_event(data: MedicalData, pid: str) -> dict[str, str] | None:
    cond = [e for e in data.by_pat[pid] if e["event_type"] == "CONDITION"]
    cat: dict[str, list[dict[str, str]]] = collections.defaultdict(list)
    for e in cond:
        c = _icd3(data, e["code_node"])
        if c:
            cat[c].append(e)
    if not cat:
        return cond[0] if cond else None
    main = sorted(cat, key=lambda c: (-len(cat[c]), min(e["start"][:10] for e in cat[c]), c))[0]
    return min(cat[main], key=lambda e: (e["start"][:10], e["event_id"]))


def disclosure_sequence(data: MedicalData, pid: str, coarse: bool = False) -> list[dict[str, Any]]:
    """ORDER 순서의 공개 목록. 없는 단서는 건너뛴다."""
    ev = data.by_pat[pid]
    out: list[dict[str, Any]] = []
    e0 = ev[0]
    out.append(dict(attribute="SEX", node_id=e0["sex_node"], event_group=None))
    if e0["region_node"]:
        out.append(dict(attribute="REGION", node_id=e0["region_node"], event_group=None))
    rep = representative_event(data, pid)
    if rep:
        dx = rep["code_node"]
        if coarse:
            dx = _icd3(data, dx) or dx
        out.append(dict(attribute="DX", node_id=dx, event_group="rep"))
        if rep["age_node"]:
            age = rep["age_node"]
            if coarse:
                age = next((a for a in data.anc(age) if a.startswith("AGE10_")), age)
            out.append(dict(attribute="AGE", node_id=age, event_group="rep"))
        if rep["period_start_node"]:
            per = rep["period_start_node"]
            if coarse:
                per = next((a for a in data.anc(per) if "_YEAR_" in a), per)
            out.append(dict(attribute="PERIOD", node_id=per, event_group="rep"))
    for att, etype, grp in (("MED", "MEDICATION", "med"), ("PLAN", "CAREPLAN", "plan")):
        es = sorted((e for e in ev if e["event_type"] == etype), key=lambda e: (e["start"], e["event_id"]))
        if es:
            n = es[0]["code_node"]
            if coarse and att == "MED":
                n = next((a for a in data.anc(n) if a.startswith("MED_IN_")), n)
            out.append(dict(attribute=att, node_id=n, event_group=grp))
    return out


def _summary(values: list[int], k_req: int) -> dict[str, Any]:
    if not values:
        return dict(n=0)
    return dict(n=len(values), median=statistics.median(values), p25=sorted(values)[len(values) // 4],
                below_k_req=round(sum(1 for v in values if 1 <= v < k_req) / len(values), 4),
                unique=round(sum(1 for v in values if v == 1) / len(values), 4))


def run_audit(data: MedicalData, patients: set[str], k_req: int = 5, progress: bool = False) -> dict[str, Any]:
    kc = KCalc(data.paths.nodes, data.paths.events, patients=patients)
    result: dict[str, Any] = dict(P_ref=len(kc.by_pat), k_req=k_req, order=list(ORDER), levels={})
    for level, coarse in (("exact", False), ("coarse", True)):
        single = collections.defaultdict(list)
        cumulative = collections.defaultdict(list)
        min_attrs: list[int | None] = []
        missing_self = 0
        for i, pid in enumerate(sorted(patients)):
            seq = disclosure_sequence(data, pid, coarse)
            first_hit = None
            for j, d in enumerate(seq, 1):
                single[d["attribute"]].append(kc.k([d])["k"])
                k = kc.k(seq[:j])["k"]
                cumulative[j].append(k)
                if first_hit is None and 1 <= k < k_req:
                    first_hit = j
            if pid not in kc.candidates(seq):
                missing_self += 1        # 검산: 실제 기록값만 공개했으므로 0이어야 한다
            min_attrs.append(first_hit)
            if progress and i % 50 == 0:
                print(f"  [{level}] {i}/{len(patients)}")
        reached = [m for m in min_attrs if m is not None]
        result["levels"][level] = dict(
            single_attribute={a: _summary(v, k_req) for a, v in single.items()},
            cumulative={str(j): _summary(v, k_req) for j, v in sorted(cumulative.items())},
            min_attributes_to_violation=dict(
                reached=len(reached), never=len(min_attrs) - len(reached),
                distribution=dict(sorted(collections.Counter(reached).items())),
                median=statistics.median(reached) if reached else None),
            target_missing_from_candidates=missing_self,
        )
    return result


def to_markdown(r: dict[str, Any]) -> str:
    lines = [f"# 기준 집단 사전 점검 (P_ref = {r['P_ref']}명, k_req = {r['k_req']})", "",
             "실제 기록값을 정해진 순서(" + " → ".join(r["order"]) + ")로 공개했을 때의 k입니다. 실행 코드는 이 값을 쓰지 않습니다.", ""]
    for level, v in r["levels"].items():
        lines += [f"## {'원래 값' if level == 'exact' else '넓은 수준 (AGE 10년·PERIOD 연도·DX ICD 3자리·MED 성분)'}", "",
                  "| 단서 하나만 공개 | 중앙값 k | 하위 25% k | 1 ≤ k < k_req 비율 | k = 1 비율 |", "| --- | --- | --- | --- | --- |"]
        for a, s in v["single_attribute"].items():
            lines.append(f"| {a} | {s['median']} | {s['p25']} | {s['below_k_req']:.1%} | {s['unique']:.1%} |")
        lines += ["", "| 누적 공개 단서 수 | 환자 수 | 중앙값 k | 1 ≤ k < k_req 비율 |", "| --- | --- | --- | --- |"]
        for j, s in v["cumulative"].items():
            lines.append(f"| {j} | {s['n']} | {s['median']} | {s['below_k_req']:.1%} |")
        m = v["min_attributes_to_violation"]
        lines += ["", f"- 처음 위반(1 ≤ k < k_req)에 도달하는 단서 수: 중앙값 {m['median']}, 분포 {m['distribution']}, 끝까지 도달 안 함 {m['never']}명",
                  f"- 검산 (대상이 자기 후보군에 없는 경우): {v['target_missing_from_candidates']}명", ""]
    return "\n".join(lines)


def write_audit(r: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "reference_audit.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "reference_audit.md").write_text(to_markdown(r), encoding="utf-8")
