# 교차 점검: main의 risk_defender(이유진, 프로필 대조) k와 전달 묶음 kcalc(사건 단위) k가 같은 값을 내는가 (LLM 0)
#
# 의료 실행의 Defender는 risk_defender의 판정 정책을 쓰되 k는 kcalc로 센다 (medical/defense.py).
# risk_defender를 그대로 붙일 수 있는지 판단하려고, 같은 공개 묶음을 두 계산기에 넣어 k를 비교한다.
#
# 공개 묶음 만들기 (결정적, seed 고정)
#   환자 한 명과 그 환자의 사건 하나(진단·시술·처방·관리 계획 중 나이·시작일이 있는 것)를 고른다.
#   그 사건에 대해 성별 + 지역 + 코드 + 그 사건 당시 나이 + 시작일을 공개한 상태를 세 수준으로 만든다.
#     L0 기록 그대로   : 도시, 코드 원래 노드, 나이(1세), 날짜(일)
#     L1 한 단계 넓게   : 주, 코드 부모, 5세 구간, 월
#     L2 두 단계 넓게   : 주, 코드 조부모, 10세 구간, 연
#   두 사건 묶음(같은 환자의 서로 다른 사건 둘, 기록 그대로)도 따로 센다.
# 비교 대상
#   kcalc (기준)          : 사건 묶음 하나에 코드·나이·날짜를 함께 둔다
#   risk_defender + 프로필 : expected = {SEX, REGION, <QI>: [{code, age, date}]}  (risk.calculate_k 그대로 호출)
#      main 프로필(user_patient_profiles_576.json, 같은 코드 사건 하나만 남김) / 사건 기반 프로필 v2(사건마다 묶음)
#   risk_defender + v2 + 나이·날짜 조상 매칭 : _matches_event_entry가 코드처럼 나이·날짜도 조상 일치를 허용했을 때 (이 파일 안의 대조용 함수, 원본은 바꾸지 않음)
# 결과: 수준별 k 일치율, 정답 환자가 후보에 들어 있는 비율, 위험 판정(1 ≤ k < 5) 일치율

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from medical.bundle.kcalc import KCalc
from medical.config import MedicalPaths
from medical.data import MedicalData

CODE_QI = {"CONDITION": "DX", "PROCEDURE": "PROC", "PROCEDURE_HISTORY": "PROC", "MEDICATION": "MED", "CAREPLAN": "PLAN"}
LEVELS = ("L0", "L1", "L2")


def _up(data: MedicalData, node: str, n: int) -> str:
    chain = data.anc(node)
    return chain[min(n, len(chain) - 2)] if len(chain) > 1 else node     # 루트(무제약)까지는 올리지 않는다


def _age_at(data: MedicalData, node: str, level: str) -> str:
    want = {"L0": "AGE_Y", "L1": "AGE5_", "L2": "AGE10_"}[level]
    return next((a for a in data.anc(node) if a.startswith(want)), node)


def _period_at(data: MedicalData, node: str, level: str) -> str:
    want = {"L0": "_DAY_", "L1": "_MONTH_", "L2": "_YEAR_"}[level]
    return next((a for a in data.anc(node) if want in a), node)


def sample_cases(data: MedicalData, n: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    pids = data.patients()
    out = []
    while len(out) < n:
        pid = rng.choice(pids)
        evs = [e for e in data.by_pat[pid] if e["event_type"] in CODE_QI and e["age_node"] and e["period_start_node"]]
        if len(evs) < 2:
            continue
        e1, e2 = rng.sample(evs, 2)
        out.append(dict(pid=pid, events=[e1, e2]))
    return out


def disclosures(data: MedicalData, case: dict[str, Any], level: str, n_events: int = 1) -> tuple[list[dict], dict[str, Any]]:
    """(kcalc 입력, risk_defender expected) 한 쌍."""
    e0 = case["events"][0]
    step = LEVELS.index(level)
    region = e0["region_node"] if step == 0 else _up(data, e0["region_node"], 1)
    kc_in = [dict(attribute="SEX", node_id=e0["sex_node"], event_group=None),
             dict(attribute="REGION", node_id=region, event_group=None)]
    rd: dict[str, Any] = {"SEX": e0["sex_node"], "REGION": region}
    for i, e in enumerate(case["events"][:n_events]):
        qi = CODE_QI[e["event_type"]]
        code, age, date = _up(data, e["code_node"], step), _age_at(data, e["age_node"], level), _period_at(data, e["period_start_node"], level)
        g = f"g{i}"
        kc_in += [dict(attribute=qi, node_id=code, event_group=g), dict(attribute="AGE", node_id=age, event_group=g),
                  dict(attribute="PERIOD", node_id=date, event_group=g)]
        rd.setdefault(qi, []).append({"code": code, "age": age, "date": date})
    return kc_in, rd


def _ancestor_entry_match(entry: Any, expected: Any) -> bool:
    """대조용: 나이·날짜도 코드처럼 '같거나 expected가 조상'이면 일치로 본다 (risk_defender.risk._matches_single 재사용)."""
    from risk_defender.risk import _matches_single
    if not isinstance(entry, dict):
        return _matches_single(entry, expected)
    if not isinstance(expected, dict):
        return _matches_single(entry.get("code", ""), str(expected))
    codes = entry.get("codes") or [entry.get("code", "")]
    if "code" in expected and not any(_matches_single(c, expected["code"]) for c in codes):
        return False
    for f in ("age", "date"):
        if f in expected and not (entry.get(f) and _matches_single(entry[f], expected[f])):
            return False
    return True


def run_crosscheck(paths: MedicalPaths, profiles: dict[str, Path], n: int = 300, seed: int = 20261023, k_req: int = 5) -> dict[str, Any]:
    import risk_defender.risk as rr
    from risk_defender.loader import load_population

    data = MedicalData(paths)
    kc = KCalc(paths.nodes, paths.events)                       # 576명 전체 (risk_defender 프로필과 같은 모집단)
    cases = sample_cases(data, n, seed)
    pops = {name: load_population(p, paths.nodes) for name, p in profiles.items()}   # 노드는 v0.10 (분기 단계 포함)
    variants = [(name, False) for name in pops] + [(name, True) for name in pops if name == "v2"]
    res: dict[str, Any] = {"n_cases": n, "seed": seed, "levels": {}}
    orig = rr._matches_event_entry
    try:
        for level, n_ev in [("L0", 1), ("L1", 1), ("L2", 1), ("L0", 2)]:
            key = level if n_ev == 1 else "L0_two_events"
            rows = []
            for c in cases:
                kin, rd = disclosures(data, c, level, n_ev)
                k_ref = kc.k(kin)["k"]
                in_ref = c["pid"] in kc.candidates(kin)
                row = dict(pid=c["pid"], k_kcalc=k_ref, target_in_kcalc=in_ref)
                for name, patched in variants:
                    rr._matches_event_entry = _ancestor_entry_match if patched else orig
                    r = rr.calculate_k(pops[name], rd)
                    tag = name + ("+anc" if patched else "")
                    row[f"k_{tag}"] = r.k
                    row[f"target_in_{tag}"] = c["pid"] in r.candidate_ids
                rows.append(row)
            is_r = lambda k: 1 <= k < k_req
            summ: dict[str, Any] = {"target_in_kcalc": sum(r["target_in_kcalc"] for r in rows) / n,
                                    "k_kcalc_median": sorted(r["k_kcalc"] for r in rows)[n // 2]}
            for name, patched in variants:
                tag = name + ("+anc" if patched else "")
                summ[tag] = dict(
                    k_equal=sum(r[f"k_{tag}"] == r["k_kcalc"] for r in rows) / n,
                    k_zero=sum(r[f"k_{tag}"] == 0 for r in rows) / n,
                    target_in=sum(r[f"target_in_{tag}"] for r in rows) / n,
                    risk_agree=sum(is_r(r[f"k_{tag}"]) == is_r(r["k_kcalc"]) for r in rows) / n,
                    k_median=sorted(r[f"k_{tag}"] for r in rows)[n // 2])
            res["levels"][key] = dict(summary=summ, rows=rows[:20])
    finally:
        rr._matches_event_entry = orig
    return res


def label_roundtrip(paths: MedicalPaths, n_per_attr: int = 300, seed: int = 20261023) -> dict[str, Any]:
    """Defender가 일반화할 때 쓰는 이름(data.label(상위 노드))을 정규화기에 다시 넣으면 같은 노드로 돌아오는가.
    돌아오지 않으면 재작성 답변을 다시 추출·정규화하는 확인 단계에서 그 값이 빠져(UNMAPPED) k가 실제보다 크게 나온다."""
    from medical.bundle.normalize_bridge import Normalizer
    data = MedicalData(paths)
    nz = Normalizer(paths.nodes, paths.alias)
    rng = random.Random(seed)
    by_attr: dict[str, set[str]] = {}
    for e in data.E:
        qi = CODE_QI.get(e["event_type"])
        for att, node in ((qi, e["code_node"]), ("AGE", e["age_node"]), ("PERIOD", e["period_start_node"]), ("REGION", e["region_node"])):
            if att and node:
                for a in data.anc(node)[:-1]:          # 루트 제외 (억제로 기록하므로 이름이 답변에 나오지 않음)
                    by_attr.setdefault(att, set()).add(a)
    out: dict[str, Any] = {}
    for att, nodes in sorted(by_attr.items()):
        pick = rng.sample(sorted(nodes), min(n_per_attr, len(nodes)))
        ok, miss = 0, []
        for nid in pick:
            lab = data.label(nid)
            role = "_".join(nid.split("_")[1:3]) if att == "PERIOD" else None
            ob = dict(attribute=att, raw_value=lab, evidence_spans=[lab], subject="TARGET_PATIENT", case_ref="사례1",
                      context_status="UNSPECIFIED", time_role=role, med_assertion="PRESCRIBED")
            r = nz.normalize(ob, lab)
            if r["node_id"] == nid:
                ok += 1
            elif len(miss) < 8:
                miss.append(dict(node_id=nid, label=lab, got=r["node_id"], status=r["mapping_status"]))
        lvl = {}
        for nid in pick:
            lv = data.N[nid].get("level") or "?"
            lvl[lv] = lvl.get(lv, 0) + 1
        out[att] = dict(n=len(pick), roundtrip_ok=ok / len(pick), examples_failed=miss, levels=lvl)
    return out


def main() -> None:
    import argparse
    from medical.config import ROOT
    ap = argparse.ArgumentParser()
    ap.add_argument("--profiles-v2", required=True, help="사건 기반 프로필 v2 JSON (user_patient_profiles_576_v2.json)")
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    paths = MedicalPaths()
    profiles = {"main576": ROOT / "risk_defender" / "data" / "user_patient_profiles_576.json", "v2": Path(a.profiles_v2)}
    res = dict(k_compare=run_crosscheck(paths, profiles, a.n), label_roundtrip=label_roundtrip(paths))
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for lv, v in res["k_compare"]["levels"].items():
        print(lv, json.dumps(v["summary"], ensure_ascii=False))
    for att, v in res["label_roundtrip"].items():
        print(att, v["n"], round(v["roundtrip_ok"], 3), v["examples_failed"][:3])


if __name__ == "__main__":
    main()
