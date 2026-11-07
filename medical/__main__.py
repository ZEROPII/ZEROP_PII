# 의료 시나리오 실행 진입점
#
#   python -m medical audit  [--out runs/medical/audit]                기준 집단 사전 점검 (LLM 0)
#   python -m medical run --dry-run [--out …] [--limit 6]             가짜 LLM으로 배선 확인 (토큰 0, 숫자는 의미 없음)
#   python -m medical run [--arms C0,C1,C1S] [--limit N] [--trials-per-cell 2] [--docs template|llm] [--docs-from 경로/RAG문서.jsonl]
#                         [--model 모델] [--model-ROLE 모델] [--mode efficiency|exploration] [--budget 10]
#   python -m medical report <실행 폴더> [--out 폴더]                 집계표 + 진단표(추출 유효율·경계·지연·토큰) (LLM 0)
#
# 실제 실행은 .env(LLM_API_KEY 등)를 읽는다. 키 값은 어디에도 출력·기록하지 않는다.

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from medical.config import ROLES, ROOT, MedicalConfig


def _cfg(a: argparse.Namespace) -> MedicalConfig:
    models = {r: getattr(a, f"model_{r}") or a.model for r in ROLES if getattr(a, f"model_{r}") or a.model}
    return MedicalConfig(arms=tuple(x.strip() for x in a.arms.split(",") if x.strip()), trials_per_cell=a.trials_per_cell,
                         documents=a.docs, mode=a.mode, budget_B=a.budget, models=models, k_req=a.k_req,
                         generalize_threshold=a.generalize_threshold, suppress_threshold=a.suppress_threshold,
                         main_experiment=a.main_experiment)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m medical")
    sub = ap.add_subparsers(dest="cmd", required=True)
    au = sub.add_parser("audit")
    au.add_argument("--out", default=str(ROOT / "runs" / "medical" / "audit"))
    au.add_argument("--k-req", type=int, default=5)
    rn = sub.add_parser("run")
    rn.add_argument("--dry-run", action="store_true")
    rn.add_argument("--out", default=None)
    rn.add_argument("--limit", type=int, default=None, help="trial 수 상한 (질의 환자 수)")
    rn.add_argument("--store-limit", type=int, default=None, help="저장소 환자 수 상한 (배선 확인용)")
    rn.add_argument("--arms", default="C0,C1,C1S")
    rn.add_argument("--trials-per-cell", type=int, default=2)
    rn.add_argument("--docs", choices=["template", "llm"], default="template")
    rn.add_argument("--docs-from", default=None)
    rn.add_argument("--mode", choices=["efficiency", "exploration"], default="efficiency")
    rn.add_argument("--budget", type=int, default=10)
    rn.add_argument("--k-req", type=int, default=5)
    rn.add_argument("--generalize-threshold", type=int, default=5)
    rn.add_argument("--suppress-threshold", type=int, default=3)
    rn.add_argument("--main-experiment", action="store_true")
    rn.add_argument("--model", default=None)
    for r in ROLES:
        rn.add_argument(f"--model-{r.replace('_', '-')}", dest=f"model_{r}", default=None)
    rp = sub.add_parser("report")
    rp.add_argument("run_dir")
    rp.add_argument("--out", default=None, help="집계 결과 폴더 (기본: 실행 폴더). 기존 실행 폴더를 건드리지 않으려면 지정")
    a = ap.parse_args(argv)

    if a.cmd == "audit":
        from medical.audit import run_audit, to_markdown, write_audit
        from medical.data import STORE, MedicalData, split_cohort
        cfg = MedicalConfig()
        d = MedicalData()
        store = {p for p, s in split_cohort(d, cfg.query_pool_ratio, cfg.seed).items() if s == STORE}
        r = run_audit(d, store, a.k_req, progress=True)
        write_audit(r, Path(a.out))
        print(to_markdown(r))
        return 0
    if a.cmd == "report":
        from medical.report import report, to_markdown
        print(to_markdown(report(Path(a.run_dir), Path(a.out) if a.out else None)))
        return 0

    from medical.experiment import run_experiment
    from medical.report import report, to_markdown
    cfg = _cfg(a)
    out = Path(a.out or ROOT / "runs" / "medical" / (("dryrun_" if a.dry_run else "run_") + time.strftime("%Y%m%d_%H%M%S")))
    if a.dry_run:
        from medical.llm import MockRoleLLM
        llm = MockRoleLLM()
    else:
        from core.config import get_settings
        from core.llm_client import LLMClient
        from medical.llm import ClientRoleLLM
        llm = ClientRoleLLM(LLMClient(get_settings()), models=cfg.models, temperature=cfg.temperature)
    run_experiment(cfg, llm, out, limit=a.limit, docs_from=Path(a.docs_from) if a.docs_from else None, store_limit=a.store_limit)
    print(to_markdown(report(out)))
    print(f"결과: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
