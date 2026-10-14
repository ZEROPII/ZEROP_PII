# python -m analysis run_multi10 [다른 실행 ...] [옵션]
#
# LLM을 부르지 않는다. 기록(trace.jsonl)과 기준 집단 파일만 있으면 된다.
# 결과: runs/paper_<첫 실행 이름>/ 아래 paper_report.md, tables/*.csv, figures/*.png·pdf, manifest.json
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from analysis.dialogues import load_dialogues, load_strata
from analysis.paper import PaperBuilder
from analysis.pipeline import Settings, build_plan, consistency_conditions, execute
from analysis.populations import PopulationBank, PopulationSpec
from analysis.simulate import Context

DEFAULT_RUNS_ROOT = Path(__file__).resolve().parent.parent / "runs"


def main(argv: list[str] | None = None) -> int:
    defaults = Settings()
    parser = argparse.ArgumentParser(description="논문용 표와 그림을 기록만으로 만든다 (LLM 호출 없음)")
    parser.add_argument("runs", nargs="+", help="runs/ 아래 실행 폴더 이름 (여러 개면 대상을 합친다. 반복 실행도 가능)")
    parser.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT))
    parser.add_argument("--out", default=None, help="결과 폴더 (기본: runs/paper_<첫 실행>)")
    parser.add_argument("--targets-file", nargs="*", default=[], help="대상 층(rich/sparse)을 읽을 target_selection 파일들")
    parser.add_argument("--eval-k", type=int, default=defaults.eval_k, help="위반 평가 기준 (기본 5 = 논문 기준)")
    parser.add_argument("--main-population", default=defaults.main_population)
    parser.add_argument("--k-sweep", type=int, nargs="+", default=list(defaults.k_sweep))
    parser.add_argument("--populations", nargs="+", default=list(defaults.populations))
    parser.add_argument("--static-levels", type=int, nargs="+", default=list(defaults.static_levels))
    parser.add_argument("--generalization", type=int, nargs="+", default=list(defaults.generalization))
    parser.add_argument("--miss-rates", type=float, nargs="+", default=list(defaults.miss_rates))
    parser.add_argument("--miss-seeds", type=int, default=defaults.miss_seeds)
    parser.add_argument("--normalization", choices=["current", "recorded"], default=defaults.normalization)
    parser.add_argument("--bootstrap", type=int, default=defaults.resamples)
    parser.add_argument("--seed", type=int, default=defaults.seed)
    parser.add_argument("--lang", choices=["auto", "ko", "en"], default="auto", help="그림 글자 (auto: 한글 글꼴이 있으면 ko)")
    parser.add_argument("--quick", action="store_true", help="빠른 점검용 (부트스트랩 500회, 누락 반복 3회)")
    args = parser.parse_args(argv)

    populations = list(dict.fromkeys(args.populations + [args.main_population]))
    for name in populations:
        PopulationSpec.parse(name)
    settings = Settings(
        eval_k=args.eval_k, main_population=args.main_population, k_sweep=tuple(sorted(set(args.k_sweep))),
        populations=tuple(populations), static_levels=tuple(args.static_levels),
        generalization=tuple(args.generalization), miss_rates=tuple(sorted(set([0.0] + args.miss_rates))),
        miss_seeds=3 if args.quick else args.miss_seeds, normalization=args.normalization,
        resamples=500 if args.quick else args.bootstrap, seed=args.seed,
    )

    runs_root = Path(args.runs_root)
    infos, dialogues = [], []
    for name in args.runs:
        run_dir = Path(name) if Path(name).is_dir() else runs_root / name
        if not (run_dir / "trace.jsonl").exists():
            print(f"오류: {run_dir / 'trace.jsonl'} 이 없습니다.", file=sys.stderr)
            return 2
        info, loaded = load_dialogues(run_dir)
        infos.append(info)
        dialogues += loaded
        print(f"------ {info.run_id}: 대상 {len(loaded)}명 (질문 갈래 {info.lead_arm})")
    if not dialogues:
        print("오류: 분석할 대화가 없습니다.", file=sys.stderr)
        return 2
    target_files = [Path(p) for p in args.targets_file] or [p for p in (runs_root / "target_selection.json",) if p.exists()]
    strata = load_strata(target_files)

    started = time.time()
    print("------ 기준 집단 준비 (30만 명 기준 수십 초)")
    context = Context(PopulationBank(seed=settings.seed))
    plan = build_plan(settings)
    conditions = plan.conditions
    print(f"------ 조건 {len(conditions)}개 × 단위 {len(dialogues)}개 판정 (LLM 호출 없음)")

    def progress(number: int, total: int, condition) -> None:
        if number == total or number % 10 == 0:
            print(f"  {number}/{total}  {condition.label} @ {condition.population}  ({time.time() - started:.0f}s)")

    results = execute(dialogues, conditions, context, progress)
    consistency = {}
    for info in infos:
        own = [d for d in dialogues if d.run_id == info.run_id]
        for condition in consistency_conditions(info, 4, "indep-300000"):
            consistency.setdefault(condition, []).extend(execute(own, [condition], context)[condition])

    out = Path(args.out) if args.out else runs_root / f"paper_{infos[0].run_id}"
    builder = PaperBuilder(settings, infos, dialogues, plan, results, consistency, context, strata, out, args.lang)
    report = builder.build()
    print(f"\n완료 ({time.time() - started:.0f}s): {report}")
    print(f"표: {out / 'tables'}  그림: {out / 'figures'}  재현 정보: {out / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
