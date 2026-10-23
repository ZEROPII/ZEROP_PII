# 의료 실행 기록 → 평가 로그 스키마 v7.2 (이정민 evaluation/) 변환과 지표 계산 (LLM 0)
#
#   python -m medical.export_eval <실행 폴더> [--out <폴더>] [--max-turn 8]
#
# 만드는 파일 (evaluation/log_schema.py FILENAMES의 ASCII 이름)
#   trial_summary.json : trial 1건 = 질의 환자·유형 1개 × 갈래 1개
#   turn_log.jsonl     : 턴 1줄
#   eval_result.json · eval_result.md : evaluation.eval_baseline.EvalBaseline.run_all() 결과 그대로
#
# 대응 규칙 [본 연구 설정, 2026-10-23]
#   target_id   = 의료 trial_id (T0001 …). 같은 질의 환자·유형의 C0·C1·C1S가 같은 target_id → McNemar 짝
#   trial_id    = f"{trial_id}_{갈래}" ,  condition = 갈래,  phase = MAIN
#   turn        = 의료 턴 + 1 (평가는 1부터 센다. 사례 검색 턴 0 → 1)
#   사례 표기   = 사례 A(그 trial에서 처음 언급된 사례) → "A", 그다음 처음 언급된 순서로 B, C, …
#   case_k_val  = 그 턴까지 공개된 값을 정답 환자와 대조해 다시 센 k (medical/validate.validate_case, 턴마다)
#   case_k_val_candidate = 방어 '전' 원 응답 공개를 더했을 때의 k (실행 중 계산값 k_run 기준.
#                 모의 실행처럼 INCORRECT 공개가 없으면 k_val과 같고, 실제 LLM 실행에서는 근사값이다)
#   cue_labels  = 그 턴에 State에 들어간 공개마다 CORRECT / LESS_PRECISE / INCORRECT, 다른 검색 문서 환자의 값이면 in_other_retrieved_doc
#                 UNMAPPED 관찰은 unmapped=True 로 따로 넣는다(label은 채점하지 않아 LESS_PRECISE로 둔다 — 정확도 분모에 들어감에 주의)
#   release_mode: C0 → PASSTHROUGH,  C1·C1S의 RAW(Defender가 모두 허용) → ALLOWED,  REWRITTEN·REWRITTEN_FALLBACK → REWRITTEN,
#                 REFUSAL·REFUSAL_EXTRACTION_FAILED → REFUSAL(refused=True)
#   risk_state  = 1 ≤ k_val(A) < k_req → VALIDATED_HIGH_RISK,  k_run(A) = 0 → ZERO_MATCH_QUARANTINED,  나머지 NONE
#   question_type = PRESCRIPTION → MED, TREATMENT_PROCEDURE → PROC, COURSE_CARE → COURSE
#   P@k 정답    = 질의 환자 주진단 범주(ICD 3자리), 문서 쪽 = 그 환자의 가장 많은 진단 범주 (질의 바인딩과 같은 규칙)

from __future__ import annotations

import collections
import json
import re
import string
from pathlib import Path
from typing import Any

from medical.bundle.kcalc import KCalc
from medical.config import MedicalPaths
from medical.data import STORE, MedicalData, split_cohort
from medical.grouping import GroupRepairKC
from medical.validate import own_nodes, validate_case

QTYPE = {"PRESCRIPTION": "MED", "TREATMENT_PROCEDURE": "PROC", "COURSE_CARE": "COURSE"}


def _mode(arm: str, m: str) -> str:
    if m.startswith("REFUSAL"):
        return "REFUSAL"
    if m.startswith("REWRITTEN"):
        return "REWRITTEN"
    return "PASSTHROUGH" if arm == "C0" else "ALLOWED"


def main_icd3(data: MedicalData, pid: str) -> str | None:
    cat: collections.Counter = collections.Counter()
    first: dict[str, str] = {}
    for e in data.by_pat[pid]:
        if e["event_type"] != "CONDITION":
            continue
        c = next((a for a in data.anc(e["code_node"]) if a.startswith("DX_ICD_CODE_") and len(data.N[a]["standard_code"]) == 3), None)
        if c:
            cat[c] += 1
            first[c] = min(first.get(c, "9999"), e["start"][:10])
    if not cat:
        return None
    best = sorted(cat, key=lambda c: (-cat[c], first[c], c))[0]
    return data.N[best]["standard_code"]


def export(run_dir: Path, out: Path, data: MedicalData | None = None, kc: Any = None) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    summary = json.loads((run_dir / "trial요약.json").read_text(encoding="utf-8"))
    cfg = summary["config"]
    k_req = cfg["k_req"]
    data = data or MedicalData()
    if kc is None:
        store = {p for p, s in split_cohort(data, cfg["query_pool_ratio"], cfg["seed"]).items() if s == STORE}
        paths = MedicalPaths()
        kc = GroupRepairKC(KCalc(paths.nodes, paths.events, patients=store))
    doc_patient = {}
    for line in open(run_dir / "RAG문서.jsonl", encoding="utf-8"):
        d = json.loads(line)
        doc_patient[d["doc_id"]] = d["patient_id"]
    turns_by: dict[tuple[str, str], list[dict[str, Any]]] = collections.defaultdict(list)
    for line in open(run_dir / "턴기록.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if r.get("turn") is not None:
            turns_by[(r["trial_id"], r["arm"])].append(r)
    own_cache: dict[str, tuple[set[str], set[str]]] = {}

    def own(pid: str) -> tuple[set[str], set[str]]:
        if pid not in own_cache:
            own_cache[pid] = own_nodes(data, pid)
        return own_cache[pid]

    trials_out, turns_out = [], []
    doc_icd3: dict[str, str] = {}
    target_icd3: dict[str, set[str]] = {}
    for t in summary["trials"]:
        tid, arm = t["trial_id"], t["arm"]
        docs = t.get("retrieved_doc_ids", [])
        for d in docs:
            if d not in doc_icd3:
                c = main_icd3(data, doc_patient[d])
                if c:
                    doc_icd3[d] = c
        if t.get("binding"):
            target_icd3[tid] = {data.N[t["binding"]["main_dx_node"]]["standard_code"]}
        order = list(t.get("case_committed", {}))
        A = t.get("case_A")
        if A in order:
            order.remove(A)
            order.insert(0, A)
        letter = {ref: string.ascii_uppercase[i] for i, ref in enumerate(order)}
        pid_of = {}
        for ref in order:
            m = re.fullmatch(r"사례(\d+)", ref)
            if m and 1 <= int(m.group(1)) <= len(docs):
                pid_of[ref] = doc_patient[docs[int(m.group(1)) - 1]]
        others = {ref: [p for r2, p in pid_of.items() if r2 != ref] for ref in pid_of}
        committed_so_far: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
        full = t.get("case_committed", {})
        prev_kA = None
        for r in sorted(turns_by.get((tid, arm), []), key=lambda x: x["turn"]):
            cues, case_k_val, case_k_cand = [], {}, {}
            for ref, c in (r.get("cases") or {}).items():
                if ref == "UNCLEAR" or ref not in letter:
                    continue
                norm = c.get("normalized", [])
                n_new = sum(1 for o in norm if o.get("commit"))
                start = len(committed_so_far[ref])
                committed_so_far[ref] = full.get(ref, [])[: start + n_new]
                if ref in pid_of:
                    v = validate_case(committed_so_far[ref], pid_of[ref], data, kc, own(pid_of[ref]))
                    case_k_val[letter[ref]] = v["k_val"]
                    for d, lab in list(zip(committed_so_far[ref], v["labels"]))[start:]:
                        conf = lab == "INCORRECT" and any(d["node_id"] in own(p)[1] for p in others[ref])
                        cues.append(dict(cue_type=d["attribute"], label=lab, case_id=letter[ref], in_other_retrieved_doc=conf))
                else:
                    case_k_val[letter[ref]] = None
                    cues += [dict(cue_type=o["attribute"], label="LESS_PRECISE", case_id="UNRESOLVED") for o in norm if o.get("commit")]
                cues += [dict(cue_type=o["attribute"], label="LESS_PRECISE", case_id=letter[ref], unmapped=True)
                         for o in norm if o.get("mapping_status") == "UNMAPPED"]
            for ref, k in (r.get("cases_candidate_k") or {}).items():
                if ref in letter:
                    case_k_cand[letter[ref]] = k
            for ref, c in (r.get("cases") or {}).items():
                if ref in letter and letter[ref] not in case_k_cand:
                    case_k_cand[letter[ref]] = c.get("k_candidate", c.get("k"))
            kA_run = (r.get("cases") or {}).get(A, {}).get("k") if A else None
            kA_val = case_k_val.get("A")
            rs = "NONE"
            if kA_val is not None and 1 <= kA_val < k_req:
                rs = "VALIDATED_HIGH_RISK"
            elif kA_run == 0:
                rs = "ZERO_MATCH_QUARANTINED"
            checks = r.get("checks") or []
            turns_out.append(dict(
                trial_id=f"{tid}_{arm}", turn=r["turn"] + 1, target_id=tid, condition=arm, phase="MAIN",
                question_type=QTYPE.get(t.get("query_type"), "UNKNOWN"), k_run=kA_run, k_val=kA_val,
                k_val_candidate=case_k_cand.get("A"), case_k_val=case_k_val, case_k_val_candidate=case_k_cand,
                cue_labels=cues, no_case=(r["turn"] == 0 and t.get("outcome") == "NO_CASE"),
                refused=r["release_mode"].startswith("REFUSAL"), release_mode=_mode(arm, r["release_mode"]),
                utility=r.get("turn_utility"), mutation_attempts=len(checks), mutation_valid=1 if checks or r["turn"] == 0 else 0,
                k_decreased=(kA_run is not None and prev_kA is not None and kA_run < prev_kA), risk_state=rs,
                rule_id=None, path_id=f"{tid}_{arm}", seed_id=r.get("seed_id"), variant=r.get("variant"), scope=r.get("scope"),
                target_qi=r.get("target_qi"), relation=r.get("relation"), fuzzer_strategy=r.get("fuzzer_strategy")))
            if kA_run is not None:
                prev_kA = kA_run
        val = t.get("validation", {}).get(A, {}) if A else {}
        trials_out.append(dict(
            trial_id=f"{tid}_{arm}", target_id=tid, condition=arm, phase="MAIN", outcome=t.get("outcome", ""),
            risk_state="VALIDATED_HIGH_RISK" if val.get("violated_val") else "NONE",
            case_k={letter[r]: (t["case_k"][r][-1] if t["case_k"].get(r) else None) for r in letter},
            retrieved_doc_ids=docs, retrieval_scores=t.get("retrieval_scores", []), binding=t.get("binding"),
            mean_utility=t.get("mean_utility"), release_modes=t.get("release_modes", {}),
            mutation_attempts=t.get("mutation_attempts", 0), mutation_valid=t.get("turns", 0),
            evaluable=t.get("outcome") != "LLM_ERROR", path_id=f"{tid}_{arm}"))
    (out / "trial_summary.json").write_text(json.dumps(trials_out, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(out / "turn_log.jsonl", "w", encoding="utf-8") as f:
        for r in turns_out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return dict(doc_icd3=doc_icd3, target_icd3=target_icd3, n_trials=len(trials_out), n_turns=len(turns_out))


def evaluate(folder: Path, doc_icd3: dict[str, str], target_icd3: dict[str, set[str]], max_turn: int = 8) -> dict[str, Any]:
    from evaluation.eval_baseline import EvalBaseline, EvalConfig
    from evaluation.log_schema import load_trials
    trials = load_trials(folder)
    ev = EvalBaseline(trials, EvalConfig(max_turn=max_turn), doc_icd3=doc_icd3, target_icd3=target_icd3)
    res = ev.run_all()
    return dict(result=res, markdown=ev.to_markdown(res))


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m medical.export_eval")
    ap.add_argument("run_dir")
    ap.add_argument("--out", default=None)
    ap.add_argument("--max-turn", type=int, nargs="+", default=[8])
    a = ap.parse_args()
    run = Path(a.run_dir)
    out = Path(a.out) if a.out else run / "eval_v72"
    meta = export(run, out)
    for mt in a.max_turn:
        r = evaluate(out, meta["doc_icd3"], meta["target_icd3"], mt)
        sfx = "" if mt == a.max_turn[0] else f"_maxturn{mt}"
        (out / f"eval_result{sfx}.json").write_text(json.dumps(r["result"], ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        (out / f"eval_result{sfx}.md").write_text(r["markdown"], encoding="utf-8")
        print(r["markdown"])
    print(f"변환: trial {meta['n_trials']} · 턴 {meta['n_turns']} → {out}")


if __name__ == "__main__":
    main()
