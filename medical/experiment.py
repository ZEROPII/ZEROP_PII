# 의료 실험 실행기: 문서 준비 → trial 계획 → 갈래별 실행 → 평가 → 기록 (하네스 명세 §2·§5.1·§12)
#
# 산출물 (out 폴더)
#   코호트분리.csv · RAG문서.jsonl · 사실표.csv · run_meta.json      : 실행 시작 때
#   턴기록.jsonl                                                     : 한 줄 = 한 턴 (갈래 표시 포함, 원 응답과 공개 응답을 함께 보관)
#   trial요약.json                                                   : trial × 갈래 요약 + validation (평가 전용 필드 포함)
#   llm_usage.jsonl                                                  : 호출마다 역할·모델·토큰·지연
# retrieved_doc_ids·patient_id·validation은 평가 저장소에만 둔다. 실행 중 질문 쪽 코드는 읽지 않는다 (설계 §2.27).

from __future__ import annotations

import hashlib
import json
import random
import time
from pathlib import Path
from typing import Any, Callable

from medical.attack import load_case_queries, load_seeds
from medical.bundle.kcalc import KCalc
from medical.bundle.normalize_bridge import Normalizer
from medical.config import ROOT, MedicalConfig, MedicalPaths
from medical.data import QUERY_POOL, STORE, MedicalData, split_cohort, write_split
from medical.defense import MedicalDefender
from medical.grouping import GroupRepairKC
from medical.documents import load_documents, make_document, save_documents, facts_prompt_block
from medical.llm import RoleLLM
from medical.prompts import PROMPT_VERSION, PROMPTS, REWRITER_VERSION, prompt_hashes
from medical.retrieval import QTYPES, code_sets, query_binding
from medical.session import Context, dumps, run_trial_group
from medical.validate import validate_trial


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def plan_trials(data: MedicalData, split: dict[str, str], cfg: MedicalConfig, limit: int | None = None) -> list[tuple[str, str, str, str]]:
    """유형 3 × 역할 2 = 6칸, 칸마다 trials_per_cell명을 그 유형에 해당하는 질의 환자 중 비복원 무작위 (명세 §5.1)."""
    rng = random.Random(cfg.seed)
    pool = sorted(p for p, s in split.items() if s == QUERY_POOL)
    plan: list[tuple[str, str, str]] = []
    for qt in QTYPES:
        elig = [p for p in pool if query_binding(data, p, qt, random.Random(0))]
        for role in ("DOCTOR", "RESEARCHER"):
            for p in rng.sample(elig, min(cfg.trials_per_cell, len(elig))):
                plan.append((p, qt, role))
    out = [(f"T{i:04d}", p, qt, role) for i, (p, qt, role) in enumerate(plan, 1)]
    return out[:limit] if limit else out


def build_context(cfg: MedicalConfig, llm: RoleLLM, out: Path, *, paths: MedicalPaths | None = None,
                  docs_from: Path | None = None, store_limit: int | None = None,
                  data: MedicalData | None = None) -> tuple[Context, dict[str, str]]:
    paths = paths or MedicalPaths()
    data = data or MedicalData(paths)
    split = split_cohort(data, cfg.query_pool_ratio, cfg.seed)
    write_split(split, cfg.seed, out / "코호트분리.csv")
    store = sorted(p for p, s in split.items() if s == STORE)
    if store_limit:
        store = store[:store_limit]
    if docs_from:
        loaded = load_documents(docs_from)
        docs = {p: loaded[p] for p in store}
    else:
        writer = lambda facts: llm.complete("doc_writer", PROMPTS["doc_writer"].format(facts=facts_prompt_block(facts)), [], facts=facts)
        docs = {p: make_document(data, p, mode=cfg.documents, write=writer, max_retries=cfg.max_doc_retries) for p in store}
    save_documents(docs, out)
    # 대상 AI가 여러 사건을 한 줄로 합쳐 말해 생기는 '아무도 맞지 않는 묶음'을 k 계산 전에 나눈다 (medical/grouping.py)
    kc = GroupRepairKC(KCalc(paths.nodes, paths.events, exclude_provisional_atc=cfg.exclude_provisional_atc, patients=set(store)))
    nz = Normalizer(paths.nodes, paths.alias, min_confidence=cfg.min_confidence)
    versions = dict(ontology_version="v0.10", matching_rule_version="kcalc v0.9.1 / normalize_bridge v0.11.1",
                    reference_version=f"events:{_sha(paths.events)[:12]}|split_seed:{cfg.seed}|ratio:{cfg.query_pool_ratio}|P_ref:{len(store)}",
                    seed_registry="v0.13-med", case_query_registry="v0.2-med", harness="medical v0.2 (bundle harness_reference v0.2 + C1/C1S)",
                    defender=f"risk_defender policy g={cfg.generalize_threshold} s={cfg.suppress_threshold} on kcalc", rewriter=REWRITER_VERSION, prompts=PROMPT_VERSION,
                    event_grouping="repair v1 (묶음 단독 k=0이면 나눔, 단독 불일치 값은 k에서 제외)")
    ctx = Context(cfg=cfg, data=data, kc=kc, nz=nz,
                  defender=MedicalDefender(kc, data, generalize_threshold=cfg.generalize_threshold, suppress_threshold=cfg.suppress_threshold),
                  docs=docs, store_sets={p: code_sets(data.by_pat[p]) for p in store},
                  seeds=load_seeds(paths, cfg.main_experiment), case_queries=load_case_queries(paths, cfg.main_experiment),
                  llm=llm, versions=versions)
    code_files = sorted((ROOT / "medical").rglob("*.py"))
    meta = dict(versions=versions, config=cfg.as_dict(), files={k: _sha(Path(v)) for k, v in paths.as_dict().items()},
                code={str(f.relative_to(ROOT)): _sha(f) for f in code_files}, prompts=prompt_hashes(),
                cohort=dict(store=len(store), query_pool=sum(1 for s in split.values() if s == QUERY_POOL)),
                documents=dict(modes={m: sum(1 for d in docs.values() if d["mode"] == m) for m in {d["mode"] for d in docs.values()}}),
                started_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    (out / "run_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return ctx, split


def run_experiment(cfg: MedicalConfig, llm: RoleLLM, out: Path, *, limit: int | None = None, docs_from: Path | None = None,
                   store_limit: int | None = None, data: MedicalData | None = None,
                   progress: Callable[[str], None] = print) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    ctx, split = build_context(cfg, llm, out, docs_from=docs_from, store_limit=store_limit, data=data)
    plan = plan_trials(ctx.data, split, cfg, limit)
    doc_patient = {d["doc_id"]: p for p, d in ctx.docs.items()}
    trials: list[dict[str, Any]] = []
    with open(out / "턴기록.jsonl", "w", encoding="utf-8") as tf:
        log = lambda rec: (tf.write(dumps(rec) + "\n"), tf.flush())
        for tid, p, qt, role in plan:
            for t in run_trial_group(ctx, tid, p, qt, role, cfg.arms, log):
                if t.get("case_committed") is not None:
                    t["validation"] = validate_trial(t, ctx.data, ctx.kc, doc_patient, cfg.k_req)
                trials.append(t)
                A = t.get("case_A")
                progress(f"{tid} {qt} {role} {t['arm']}: {t['outcome']} k_A={t.get('case_k', {}).get(A, [])} "
                         f"k_val={t.get('validation', {}).get(A, {}).get('k_val')} 공개={t.get('release_modes')}")
    summary = dict(config=cfg.as_dict(), versions=ctx.versions, trials=trials)
    (out / "trial요약.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    with open(out / "llm_usage.jsonl", "w", encoding="utf-8") as f:
        for u in ctx.llm.usage:
            f.write(json.dumps(u, ensure_ascii=False) + "\n")
    return summary
