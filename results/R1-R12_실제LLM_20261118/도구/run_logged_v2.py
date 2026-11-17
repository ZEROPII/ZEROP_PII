#!/usr/bin/env python3
"""`python3 -m medical run ...`을 그대로 돌리면서 팀원 가이드(3-1)에 맞춘 기록을 더 남긴다 (판정 · 호출 내용은 바꾸지 않음).

저장소 루트(ZEROP_PII)에서, medical 명령 인자를 그대로 뒤에 붙인다:
  caffeinate -i python3 run_logged_v2.py run --arms C0,C1,C1S --limit 8 --budget 7 --suppress-threshold 3 \
      --normalizer v2 --docs template --model claude-haiku-4-5-20251001 --out <새 폴더>

medical이 만드는 파일(run_meta.json · trial요약.json · 턴기록.jsonl · llm_usage.jsonl · report.md 등)에 더해
  실행정보.json          커밋 해시 · 브랜치 · 작업 트리 변경 여부 · 명령 전체 · 시작 · 종료 시각 · 모델 · 끝난 상태 · 호출 합계
                         (run_meta.json에는 커밋 해시 · 명령 · 종료 시각이 없어서 따로 둔다. run_meta.json은 고치지 않는다)
  llm_errors.jsonl       응답 없이 실패한 LLM 호출 (역할 · 오류 종류와 앞부분). 오류가 없으면 빈 파일
  추출입출력.jsonl       추출기 호출마다 입력 · 출력 원문 · 해석 성공 여부 · 토큰
  trial체크포인트.jsonl  trial이 끝날 때마다 그 trial 요약 한 줄 (중간에 멈춰도 끝난 trial은 남음)
  llm_usage_진행.jsonl   LLM 호출마다 역할 · 토큰 (중간에 멈춰도 합계를 셀 수 있음)

medical/ 코드는 고치지 않는다 (run_meta.json의 코드 해시가 그대로 남는다). .env의 키는 읽지도 출력하지도 않는다
(모델 이름만 설정에서 읽는다).
"""
from __future__ import annotations

import json
import os
import platform
import shlex
import subprocess
import sys
import time
from pathlib import Path

PRICE_IN, PRICE_OUT = 1.0, 5.0          # Claude Haiku 4.5 정가 ($ / 100만 토큰). 실제 청구 금액은 대시보드에서 확인


def git(*args: str) -> str:
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True, timeout=30,
                           env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
        return r.stdout.strip()
    except Exception:
        return ""


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def opt(argv: list[str], name: str, default: str) -> str:
    return argv[argv.index(name) + 1] if name in argv else default


def usage_total(path: Path) -> dict:
    n = tin = tout = 0
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                u = json.loads(line)
                n += 1
                tin += u.get("input_tokens") or 0
                tout += u.get("output_tokens") or 0
    return dict(calls=n, input_tokens=tin, output_tokens=tout, list_price_usd=round(tin / 1e6 * PRICE_IN + tout / 1e6 * PRICE_OUT, 2))


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] != "run" or "--out" not in argv:
        sys.exit("사용법: python3 run_logged_v2.py run <medical run 인자> --out <새 폴더>")
    if "--dry-run" in argv:
        sys.exit("이 기록 도구는 실제 LLM 실행용입니다. --dry-run은 빼 주세요.")
    out = Path(opt(argv, "--out", "")).expanduser().resolve()
    if out.exists() and any(out.iterdir()):
        sys.exit(f"비어 있지 않은 폴더입니다. 새 폴더 이름을 주세요: {out}")
    out.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(Path.cwd()))
    from medical.config import MedicalConfig
    model = opt(argv, "--model", "")
    if not model:
        try:
            from core.config import get_settings
            model = get_settings().llm_model + " (.env)"
        except Exception:
            model = "(.env를 읽지 못함)"
    s = opt(argv, "--suppress-threshold", f"{MedicalConfig.suppress_threshold} (기본값)")
    w = opt(argv, "--widen-first", (",".join(getattr(MedicalConfig, "widen_first", ())) or "없음") + " (기본값)")
    budget = opt(argv, "--budget", "10 (기본값)")
    info = dict(commit=git("rev-parse", "HEAD"), branch=git("rev-parse", "--abbrev-ref", "HEAD"),
                tracked_changes=bool(git("status", "--porcelain", "--untracked-files=no")),
                command="python3 " + shlex.join(sys.argv), medical_command="python3 -m medical " + shlex.join(argv),
                cwd=str(Path.cwd()), started_at=now(), finished_at=None, status="실행 중",
                settings=dict(suppress_threshold=s, generalize_threshold=opt(argv, "--generalize-threshold", "5 (기본값)"),
                              k_req=opt(argv, "--k-req", "5 (기본값)"), arms=opt(argv, "--arms", "C0,C1,C1S (기본값)"),
                              limit=opt(argv, "--limit", "없음"), budget=budget, widen_first=w,
                              normalizer=opt(argv, "--normalizer", "v2 (기본값)"), docs=opt(argv, "--docs", "template (기본값)"),
                              model=model, concurrency=1),
                python=platform.python_version(), machine=f"{platform.system()} {platform.machine()}")
    info_path = out / "실행정보.json"

    def save() -> None:
        info_path.write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")

    save()
    print(f"판정 설정: suppress_threshold={s} · widen_first={w} · 갈래 {info['settings']['arms']} · trial {info['settings']['limit']}"
          f" · 턴 0~{budget.split()[0]} · 모델 {model}", flush=True)
    print(f"커밋 {info['commit'][:7]} ({info['branch']}){' · 추적 파일에 커밋 안 된 변경 있음' if info['tracked_changes'] else ''}"
          f" · 결과 폴더 {out}", flush=True)

    import medical.experiment as ex
    from medical.llm import ClientRoleLLM
    from medical.session import dumps
    from medical.tracking import parse_json

    seq = {"n": 0}
    orig_complete = ClientRoleLLM.complete

    def complete(self, role, system, messages, **kw):
        n0 = len(self.usage)
        try:
            text = orig_complete(self, role, system, messages, **kw)
        except Exception as exc:          # 오류 종류와 앞부분만 남긴다 (LLMClient는 키 · 헤더를 메시지에 넣지 않음)
            with open(out / "llm_errors.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(dict(at=now(), role=role, error=f"{type(exc).__name__}: {str(exc)[:300]}"), ensure_ascii=False) + "\n")
            raise
        calls = self.usage[n0:]
        with open(out / "llm_usage_진행.jsonl", "a", encoding="utf-8") as f:
            for u in calls:
                f.write(json.dumps(u, ensure_ascii=False) + "\n")
        if role == "extractor":
            seq["n"] += 1
            rec = dict(seq=seq["n"], prompt=system, output=text, parsed_ok=parse_json(text, "array") is not None, calls=calls)
            with open(out / "추출입출력.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return text

    ClientRoleLLM.complete = complete

    orig_group = ex.run_trial_group

    def group(ctx, tid, qpid, qtype, role, arms, log):
        res = orig_group(ctx, tid, qpid, qtype, role, arms, log)
        with open(out / "trial체크포인트.jsonl", "a", encoding="utf-8") as f:
            for t in res:
                f.write(dumps(t) + "\n")
        for t in res:
            print(f"  [체크포인트] {t.get('trial_id')} {t.get('arm')}: {t.get('outcome')}"
                  + (f" — {str(t.get('error'))[:120]}" if t.get("error") else ""), flush=True)
        u = usage_total(out / "llm_usage_진행.jsonl")
        print(f"  [누적] 호출 {u['calls']}회 · 정가 약 ${u['list_price_usd']:.2f}", flush=True)
        return res

    ex.run_trial_group = group

    from medical.__main__ import main as medical_main
    code = 1
    try:
        code = medical_main(argv)
        info["status"] = "완료"
        return code
    except KeyboardInterrupt:
        info["status"] = "중단 (Ctrl+C)"
        raise
    except BaseException as exc:
        info["status"] = f"오류로 끝남: {type(exc).__name__}: {str(exc)[:200]}"
        raise
    finally:
        info["finished_at"] = now()
        info["llm_usage"] = usage_total(out / "llm_usage_진행.jsonl")
        (out / "llm_errors.jsonl").touch()
        save()
        u = info["llm_usage"]
        print(f"[기록] {info['status']} · 호출 {u['calls']}회 · 입력 {u['input_tokens']:,} · 출력 {u['output_tokens']:,}"
              f" · 정가 약 ${u['list_price_usd']:.2f} · {info_path}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
