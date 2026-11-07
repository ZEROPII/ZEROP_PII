#!/usr/bin/env python3
"""R2 검색 전용 덤프 + R4 대상 층화 추출 (RAG 기준 재측정 요청서 2026-11-05). LLM 호출 0.

    python scripts/rag_retrieval_dump.py --out runs/rag/r2_retrieval
    python scripts/rag_retrieval_dump.py --out runs/rag/r2_retrieval --sample 30 --sample-seed 20261106

1) 질의 후보(QUERY_POOL) 115명 × 조회 유형 3을 검색만 한다. 실행(make_prefix)과 같은 검색: 질의 환자의 기준일까지 기록
   (code_sets) → 저장소 461명 문서 상위 5건. 기준일은 난수와 무관하므로 실행과 같은 상위 5건이 나온다.
2) 상위 5건에 한 번이라도 나오는 저장소 환자 = 새 실험의 모집단. 환자별 노출 횟수 · 상위 10명 점유율 · 지니 계수.
3) 기준 희귀도: 그 환자 문서의 원본 단서 몇 개를 공개하면 후보가 5명 아래가 되는가 (최소 개수, rag_common.baseline_rarity).
   - 모든 단서(날짜 · 나이 포함)와 의료 항목만(진단 · 약 · 시술 · 계획 + 성별 · 거주지) 두 가지로 센다.
     정확한 날짜는 거의 한 사람만 가져서 모든 단서 기준은 대부분 1개가 된다 → 층화는 의료 항목 기준으로 한다.
4) 114 vs 115: 질의 후보 중 어느 유형으로도 질의 환자가 될 수 없는 사람과 그 까닭 (연구 계획 plan_all과 같은 규칙).
5) --sample N: 모집단에서 N명 층화 추출 (기준 희귀도 상 · 중 · 하 × 민감 진단 여부 × 노출 상위 10% 여부).
   대상마다 그 사람이 가장 높은 순위로 나오는 (질의 환자, 조회 유형)을 붙인다. 규칙 · 목록 해시를 사전등록.txt에 적는다.

산출: retrieval_dump.csv · exposure.csv · eligibility.csv · 요약.md · 요약.json
      (+ --sample: r4_targets.csv · r4_rule.json · 사전등록.txt · r3_trial_targets.csv(시험 실행용 3명, 희귀도 층마다 한 명))
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rag_common import ROOT, HasIndex, baseline_rarity, sensitive_groups, sha256, write_csv   # noqa: E402

ITEM_ATTRS = ("DX", "MED", "PROC", "PLAN", "SEX", "REGION")


def gini(xs: list[int]) -> float | None:
    xs = sorted(xs)
    n, s = len(xs), sum(xs)
    if not n or not s:
        return None
    return round(sum((2 * i - n + 1) * x for i, x in enumerate(xs)) / (n * s), 4)


def why_not(data: Any, pid: str, qtypes: tuple[str, ...]) -> str:
    from medical.retrieval import query_binding
    cond = [e for e in data.by_pat[pid] if e["event_type"] == "CONDITION"]
    has_cat = any(any(a.startswith("DX_ICD_CODE_") and len(data.N[a]["standard_code"]) == 3 for a in data.anc(e["code_node"])) for e in cond)
    if not has_cat:
        return f"진단 {len(cond)}건이 모두 ICD 세 자리 범주에 닿지 않음 (진단 범주 없음)"
    bad = [qt for qt in qtypes if query_binding(data, pid, qt, random.Random(0)) is None]
    return "기준 진료일에 유형별 관련 항목 없음: " + ", ".join(bad)


def tiers(values: list[float], n_tiers: int = 3) -> list[float]:
    """경계값 (오름차순 n_tiers-1개). 값이 몰리면 경계가 겹칠 수 있다."""
    xs = sorted(values)
    return [xs[min(len(xs) - 1, int(len(xs) * q / n_tiers))] for q in range(1, n_tiers)]


def allocate(sizes: dict[Any, int], n: int) -> dict[Any, int]:
    """비례 배분 (최대 나머지). 비어 있지 않은 층에는 가능하면 1명 이상."""
    total = sum(sizes.values())
    keys = [k for k in sizes if sizes[k] > 0]
    if n >= len(keys):
        base = {k: 1 for k in keys}
        rest = n - len(keys)
    else:
        base = {k: 0 for k in keys}
        rest = n
    want = {k: rest * sizes[k] / total for k in keys}
    got = {k: base[k] + int(want[k]) for k in keys}
    left = n - sum(got.values())
    for k in sorted(keys, key=lambda k: -(want[k] - int(want[k]))):
        if left <= 0:
            break
        if got[k] < sizes[k]:
            got[k] += 1
            left -= 1
    for k in keys:                                       # 층 크기보다 많이 배분되지 않게
        while got[k] > sizes[k]:
            got[k] -= 1
            left += 1
    for k in sorted(keys, key=lambda k: -(sizes[k] - got[k])):
        while left > 0 and got[k] < sizes[k]:
            got[k] += 1
            left -= 1
    return got


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python scripts/rag_retrieval_dump.py")
    ap.add_argument("--out", default=str(ROOT / "runs" / "rag" / "r2_retrieval"))
    ap.add_argument("--sample", type=int, default=0, help="R4 대상 수 (0이면 추출하지 않음)")
    ap.add_argument("--sample-seed", type=int, default=20261106)
    ap.add_argument("--k-req", type=int, default=5)
    a = ap.parse_args(argv)

    from medical.config import MedicalConfig
    from medical.data import QUERY_POOL, MedicalData
    from medical.experiment import build_context
    from medical.retrieval import QTYPES, code_sets, query_binding, retrieve
    from medical.simulate import OracleRoleLLM

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    import measure_latency as ml
    run_info = dict(command=" ".join(["python", "scripts/rag_retrieval_dump.py", *(argv if argv is not None else sys.argv[1:])]),
                    git=ml.git_info(), env=ml.cpu_info(), started_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    data = MedicalData()
    cfg = MedicalConfig()
    ctx, split = build_context(cfg, OracleRoleLLM(data=data, profile="staged"), out, data=data)    # 템플릿 문서 (LLM 없음)
    pool = sorted(p for p, s in split.items() if s == QUERY_POOL)
    store = sorted(ctx.docs)

    dump, elig_rows, valid = [], [], 0
    expo: collections.Counter = collections.Counter()
    best: dict[str, tuple[int, int, str, str]] = {}                 # 저장소 환자 → (순위, 유형 순서, 질의 환자, 유형)
    per_type = collections.Counter()
    for qp in pool:
        oks = []
        for ti, qt in enumerate(QTYPES):
            b = query_binding(data, qp, qt, random.Random(0))
            if b is None:
                continue
            oks.append(qt)
            per_type[qt] += 1
            valid += 1
            ret = retrieve(code_sets(data.by_pat[qp], b["index_date"]), ctx.store_sets, cfg.top_k_retrieval)
            for rank, (sp, score) in enumerate(ret, 1):
                dump.append(dict(query_patient=qp, query_type=qt, index_date=b["index_date"], rank=rank, store_patient_id=sp,
                                 similarity=round(float(score), 6)))
                expo[sp] += 1
                cand = (rank, ti, qp, qt)
                if sp not in best or cand < best[sp]:
                    best[sp] = cand
        elig_rows.append(dict(query_patient=qp, eligible_types=";".join(oks), n_types=len(oks),
                              reason="" if oks else why_not(data, qp, QTYPES)))
    write_csv(out / "retrieval_dump.csv", dump)
    write_csv(out / "eligibility.csv", elig_rows)

    # 기준 희귀도 · 민감 진단
    hx = HasIndex(ctx.kc)
    rows = []
    for sp in sorted(expo, key=lambda p: (-expo[p], p)):
        facts = [(r["attribute"], r["node_id"]) for r in ctx.docs[sp]["fact_rows"] if r.get("attribute") and r.get("node_id") in data.N]
        r_all = baseline_rarity(hx, facts, sp, a.k_req)
        r_items = baseline_rarity(hx, [x for x in facts if x[0] in ITEM_ATTRS], sp, a.k_req)
        sens = sensitive_groups(data, [n for at, n in facts if at in ("DX", "MED", "PROC", "PLAN")])
        rank, _, qp, qt = best[sp]
        rows.append(dict(store_patient_id=sp, exposures=expo[sp], best_rank=rank, best_query_patient=qp, best_query_type=qt,
                         rarity_all_min_clues=r_all["min_clues"], rarity_all_method=r_all["method"],
                         rarity_items_min_clues=r_items["min_clues"], rarity_items_method=r_items["method"],
                         rarity_items_example=" + ".join(r_items["example"] or []), k_single_min=r_items["k_single_min"],
                         sensitive=";".join(sens)))
    n_pop = len(rows)
    top10 = expo.most_common(10)
    slots = sum(expo.values())
    cut = sorted(expo.values(), reverse=True)[max(0, int(round(n_pop * 0.1)) - 1)] if n_pop else 0
    for r in rows:
        r["exposure_tier"] = "상위10%" if r["exposures"] >= cut else "나머지"
    items = [r["rarity_items_min_clues"] for r in rows if r["rarity_items_min_clues"] is not None]
    edges = tiers(items) if items else []

    def tier(v: Any) -> str:
        if v is None:
            return "하"                                   # 의료 항목을 모두 공개해도 5명 아래로 안 내려감 → 가장 덜 드묾
        if len(edges) == 2 and edges[0] == edges[1]:
            return "상" if v < edges[0] else ("중" if v == edges[0] else "하")
        return "상" if v <= edges[0] else ("중" if v <= edges[-1] else "하")

    for r in rows:
        r["rarity_tier"] = tier(r["rarity_items_min_clues"])
        r["sensitive_tier"] = "민감" if r["sensitive"] else "일반"
    write_csv(out / "exposure.csv", rows)

    hist = collections.Counter(expo.values())
    no_q = [r for r in elig_rows if not r["n_types"]]
    summary: dict[str, Any] = dict(
        pool=len(pool), store=len(store), valid_combos=valid, per_type=dict(per_type),
        queries_used=sum(1 for r in elig_rows if r["n_types"]), not_eligible=[dict(query_patient=r["query_patient"], reason=r["reason"]) for r in no_q],
        population=n_pop, coverage=round(n_pop / len(store), 4), slots=slots, top10=[dict(patient_id=p, exposures=n) for p, n in top10],
        top10_share=round(sum(n for _, n in top10) / slots, 4) if slots else None, gini=gini(list(expo.values())),
        histogram={str(k): hist[k] for k in sorted(hist)},
        rarity_all=dict(collections.Counter(str(r["rarity_all_min_clues"]) for r in rows)),
        rarity_items=dict(collections.Counter(str(r["rarity_items_min_clues"]) for r in rows)),
        rarity_items_edges=edges, sensitive=dict(collections.Counter(r["sensitive_tier"] for r in rows)),
        exposure_top10pct_cut=cut, seconds=round(time.time() - t0, 1), run=dict(run_info, finished_at=time.strftime("%Y-%m-%dT%H:%M:%S%z")))

    # R4 대상 층화 추출
    if a.sample:
        rng = random.Random(a.sample_seed)
        strata: dict[tuple[str, str, str], list[dict[str, Any]]] = collections.defaultdict(list)
        for r in rows:
            strata[(r["rarity_tier"], r["sensitive_tier"], r["exposure_tier"])].append(r)
        alloc = allocate({k: len(v) for k, v in strata.items()}, min(a.sample, n_pop))
        picked = []
        for k in sorted(strata):
            got = sorted(rng.sample(sorted(strata[k], key=lambda r: r["store_patient_id"]), alloc.get(k, 0)), key=lambda r: r["store_patient_id"])
            for r in got:
                picked.append(dict(target_patient=r["store_patient_id"], query_patient=r["best_query_patient"], query_type=r["best_query_type"],
                                   rank=r["best_rank"], stratum="/".join(k), rarity_tier=k[0], rarity_items_min_clues=r["rarity_items_min_clues"],
                                   sensitive=r["sensitive"] or "-", exposure_tier=k[2], exposures=r["exposures"]))
        write_csv(out / "r4_targets.csv", picked)
        trial = [next(r for r in picked if r["rarity_tier"] == t) for t in ("상", "중", "하") if any(r["rarity_tier"] == t for r in picked)]
        write_csv(out / "r3_trial_targets.csv", trial[:3])      # R3 시험 실행용 3명 (희귀도 층마다 한 명)
        rule = dict(population="R2 상위 5건에 한 번이라도 나온 저장소 환자 전체", n=len(picked), seed=a.sample_seed,
                    strata="기준 희귀도(의료 항목 기준 최소 단서 수, 3분위: 상=적게 필요) × 민감 진단(생식 · 물질사용 · 암 · 정신 · HIV) × 노출 빈도(상위 10%)",
                    allocation="층 크기 비례 (최대 나머지), 비어 있지 않은 층은 1명 이상", within="층 안에서 seed 난수로 비복원 추출",
                    query="대상마다 그 사람이 가장 높은 순위로 나오는 (질의 환자, 조회 유형). 같으면 유형 순서 · 질의 환자 ID 순",
                    strata_sizes={"/".join(k): len(v) for k, v in sorted(strata.items())}, allocated={"/".join(k): n for k, n in sorted(alloc.items())},
                    exposure_csv_sha256=sha256(out / "exposure.csv"), retrieval_dump_sha256=sha256(out / "retrieval_dump.csv"))
        (out / "r4_rule.json").write_text(json.dumps(rule, ensure_ascii=False, indent=1), encoding="utf-8")
        reg = [f"작성: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
               f"r4_targets.csv  sha256 {sha256(out / 'r4_targets.csv')}",
               f"r4_rule.json    sha256 {sha256(out / 'r4_rule.json')}",
               f"retrieval_dump.csv sha256 {rule['retrieval_dump_sha256']}",
               "실행 전에 이 세 해시를 먼저 보내 주세요 (사전 등록)."]
        (out / "사전등록.txt").write_text("\n".join(reg) + "\n", encoding="utf-8")
        summary["sample"] = dict(n=len(picked), seed=a.sample_seed, allocated=rule["allocated"])

    (out / "요약.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    gi, ev = run_info["git"], run_info["env"]
    L = [f"# R2 검색 전용 덤프 ({out.name})", "",
         f"- 커밋 `{gi.get('commit')}` ({gi.get('branch')}) · 명령 `{run_info['command']}` · {ev.get('system')} {ev.get('macos') or ev.get('release')} · "
         f"Python {ev.get('python')} · 시작 {run_info['started_at']} · {summary['seconds']}초", "",
         f"- 질의 후보 {len(pool)}명 × 조회 유형 {len(QTYPES)} 가운데 질의가 될 수 있는 조합 {valid}개 (유형별 {dict(per_type)})",
         f"- 실제로 질의가 나오는 사람 {summary['queries_used']}명. 빠진 사람:"]
    L += [f"  - `{x['query_patient']}`: {x['reason']}" for x in summary["not_eligible"]] or ["  - 없음"]
    L += ["", f"- 모집단(상위 5건에 한 번이라도 나온 저장소 환자): **{n_pop}명** / {len(store)}명 ({100 * summary['coverage']:.1f}%)",
          f"- 노출 {slots}회 · 상위 10명 점유율 {100 * (summary['top10_share'] or 0):.1f}% · 지니 계수 {summary['gini']}",
          f"- 노출 횟수 히스토그램 {{횟수: 환자 수}}: {json.dumps(summary['histogram'])}",
          "- 상위 10명: " + ", ".join(f"{p[:8]}({n})" for p, n in top10),
          "", "## 기준 희귀도 (원본 단서 몇 개면 후보 5명 아래)", "",
          f"- 모든 단서(날짜 · 나이 포함): {json.dumps(summary['rarity_all'], ensure_ascii=False)}  (정확한 날짜 하나로 거의 한 명이 된다)",
          f"- 의료 항목만(진단 · 약 · 시술 · 계획 · 성별 · 거주지): {json.dumps(summary['rarity_items'], ensure_ascii=False)}  "
          f"(None = 모두 공개해도 5명 아래로 안 내려감) · 층 경계 {edges}",
          "- 사건 연결 없이 센 값이라 실제 최소 개수보다 크거나 같다(상한).",
          f"- 민감 진단(생식 · 물질사용 · 암 · 정신 · HIV): {json.dumps(summary['sensitive'], ensure_ascii=False)}"]
    if a.sample:
        L += ["", f"## R4 대상 {summary['sample']['n']}명 (seed {a.sample_seed})", "",
              "| 층(희귀도/민감/노출) | 층 크기 | 뽑은 수 |", "| --- | --- | --- |"]
        rule = json.loads((out / "r4_rule.json").read_text(encoding="utf-8"))
        L += [f"| {k} | {v} | {rule['allocated'].get(k, 0)} |" for k, v in rule["strata_sizes"].items()]
        L += ["", "해시는 사전등록.txt"]
    (out / "요약.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    print(f"\n저장: {out}  ({summary['seconds']}초)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
