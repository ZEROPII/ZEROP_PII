#!/usr/bin/env python3
"""한 턴 처리 시간 측정 (발표 결과 ⑥: 질문부터 최종 답변까지).

    python scripts/measure_latency.py                          실제 LLM(.env), 유형마다 2명, 갈래 C0 · C1, 8턴(턴 0~7)
    python scripts/measure_latency.py --per-type 1             호출을 줄여 먼저 확인
    python scripts/measure_latency.py --llm oracle --per-type all   LLM 없음: k 계산 · 판정 시간만 (호출 0)
    python scripts/measure_latency.py --summarize runs/latency/<폴더>  기록으로 표만 다시 만들기

실제 LLM 레드팀(webdemo.backend.engine.RedTeamJob._group)과 같은 경로로 돈다.
  make_prefix → RuledArmRun(live=True).run(). 규칙 추출 켬, 대상 AI 답 형식 켬, 모델은 서버와 같은 설정
  (.env LLM_MODEL, --extractor-model · --rewriter-model은 serve와 같은 뜻). 동시 호출 1.
연구 모듈(medical/)과 제품 코드는 바꾸지 않는다. 이 프로세스 안에서만 시간 재는 감싸기를 끼운다.
  - LLM 호출: 역할 · 단계(answer · extract · rewrite · recheck · attack) · 갈래 · 턴을 붙인다.
    latency_ms는 LLM 클라이언트가 잰 마지막 요청의 응답 시간(대기 · 실패한 재시도 제외),
    wall_ms는 호출 하나를 부르고 받을 때까지(간격 대기 · 재시도 · 잘림 뒤 다시 부르기 포함).
  - 판정: RuleDefender.plan_case + change_lines (안에서 부르는 GroupRepairKC.k 포함)
  - k 계산: GroupRepairKC.k 한 번 (판정 · 다시 확인 · 기록용으로 나눠 센다). 결과 캐시가 있어 같은 공개 묶음은 빠르다.
  - 정규화: Normalizer.normalize (추출 결과 → 노드)
  - 턴 전체: ArmRun._turn 한 번 (대상 AI 답 → 추출 → 판정 → 재작성 · 다시 확인 → 기록). 공격 질문 만들기는 넣지 않는다.
    턴 0의 대상 AI 답 · 추출은 갈래가 나눠 쓰는 첫 답(make_prefix)에서 한 번 한다 → 따로 센다.

산출물 (out 폴더)
  run_meta.json    build_context 기록 + measurement(커밋 · 명령 · 모델 · CPU · 설정)
  llm_usage.jsonl  응답마다 role · model · 토큰 · latency_ms (하네스와 같은 형식) + wall_ms · arm · trial_id · turn · phase
                   실행 중 바로 쓴다. 응답 없이 실패한 호출은 llm_errors.jsonl에 따로 남긴다.
  턴시간.jsonl     턴마다 전체 시간과 단계별 시간
  턴기록.jsonl · trial요약.json   하네스 기록 (결과 ③ 계산에도 쓸 수 있음)
  시간요약.md · 시간요약.json      표
키 값은 어디에도 출력 · 기록하지 않는다.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PHASE_KO = dict(answer="대상 AI 답", extract="단서 추출", rewrite="재작성", recheck="다시 확인 추출", attack="공격 질문 만들기 · 확인",
                docs="문서 생성")
ROLE_ORDER = ("target", "extractor", "rewriter", "mutator", "checker", "doc_writer")


# ── 시간 재기 ────────────────────────────────────────────────────────

class Clock:
    """지금 어디(갈래 · 턴 · 단계)에 있는지와 턴 하나의 시간을 모은다. 한 스레드에서만 쓴다."""

    def __init__(self, usage_file: Path | None, turn_file: Path | None, error_file: Path | None = None) -> None:
        self.arm: str | None = None
        self.trial: str | None = None
        self.turn: int | None = None
        self.where = "setup"               # setup · prefix · turn · plan · release · verify · post · between
        self.cur: dict[str, Any] | None = None
        self.prefix: dict[str, Any] | None = None
        self.turns: list[dict[str, Any]] = []
        self.prefixes: list[dict[str, Any]] = []
        self._kdepth = 0
        self._uf = open(usage_file, "a", encoding="utf-8") if usage_file else None
        self._tf = open(turn_file, "a", encoding="utf-8") if turn_file else None
        self._ef = open(error_file, "a", encoding="utf-8") if error_file else None

    def close(self) -> None:
        for f in (self._uf, self._tf, self._ef):
            if f:
                f.close()

    @staticmethod
    def _blank() -> dict[str, Any]:
        return dict(llm={}, decide_ms=0.0, plan_calls=0, kcalc_ms=collections.Counter(), kcalc_calls=collections.Counter(),
                    normalize_ms=0.0, verify_ms=0.0, verify_calls=0, release_ms=0.0)

    def phase_of(self, role: str) -> str:
        if role in ("mutator", "checker"):
            return "attack"
        if role == "doc_writer":
            return "docs"
        if role == "target":
            return "answer"
        if role == "rewriter":
            return "rewrite"
        if role == "extractor":
            return "recheck" if self.where == "verify" else "extract"
        return role

    def _bucket(self) -> dict[str, Any] | None:
        if self.where == "prefix":
            return self.prefix
        if self.where in ("turn", "plan", "release", "verify", "post"):
            return self.cur
        return None

    def add_llm(self, role: str, wall_ms: float, rows: list[dict[str, Any]], error: str | None) -> None:
        phase = self.phase_of(role)
        turn = self.turn
        if self.where == "between" and turn is not None:
            turn += 1                                      # 턴 사이의 공격 질문 만들기는 다음 턴의 질문이다
        tag = dict(arm=self.arm if self.where != "prefix" else "shared", trial_id=self.trial, turn=turn, phase=phase)
        if not rows and self._ef:                          # 실패해 응답이 없는 호출은 llm_errors.jsonl에 따로 (usage는 하네스 형식 그대로)
            self._ef.write(json.dumps(dict(role=role, error=error, wall_ms=round(wall_ms, 1), **tag), ensure_ascii=False) + "\n")
            self._ef.flush()
        for i, r in enumerate(rows):
            r.update(tag)
            if i == len(rows) - 1:
                r.update(wall_ms=round(wall_ms, 1), api_calls_in_wall=len(rows))
            if self._uf:
                self._uf.write(json.dumps(r, ensure_ascii=False) + "\n")
        if self._uf:
            self._uf.flush()
        b = self._bucket()
        if b is not None:
            s = b["llm"].setdefault(phase, dict(wall_ms=0.0, latency_ms=0.0, calls=0, api_calls=0))
            s["wall_ms"] += wall_ms
            s["latency_ms"] += sum(float(r.get("latency_ms") or 0) for r in rows)
            s["calls"] += 1
            s["api_calls"] += sum(1 for r in rows if r.get("latency_ms") is not None)

    def kcalc(self, ms: float) -> None:
        stage = {"plan": "decide", "verify": "recheck", "release": "release", "post": "record", "turn": "record",
                 "prefix": "prefix"}.get(self.where, "other")
        b = self._bucket()
        if b is not None:
            b["kcalc_ms"][stage] += ms
            b["kcalc_calls"][stage] += 1

    def normalized(self, ms: float) -> None:
        b = self._bucket()
        if b is not None:
            b["normalize_ms"] += ms

    def begin_prefix(self, trial: str) -> None:
        self.trial, self.turn, self.arm, self.where = trial, 0, None, "prefix"
        self.prefix = dict(self._blank(), kind="prefix", trial_id=trial, t0=time.perf_counter())

    def end_prefix(self) -> None:
        p = self.prefix
        p["total_ms"] = round((time.perf_counter() - p.pop("t0")) * 1000, 1)
        self.prefixes.append(_plain(p))
        if self._tf:
            self._tf.write(json.dumps(_plain(p), ensure_ascii=False) + "\n")
            self._tf.flush()
        self.where = "between"

    def begin_turn(self, arm: str, trial: str, turn: int, shared_answer: bool) -> None:
        self.arm, self.trial, self.turn, self.where = arm, trial, turn, "turn"
        self.cur = dict(self._blank(), kind="turn", arm=arm, trial_id=trial, turn=turn, shared_answer=shared_answer)

    def end_turn(self, total_s: float, rec: dict[str, Any] | None, error: str | None) -> None:
        c = self.cur
        c["total_ms"] = round(total_s * 1000, 1)
        if rec is not None:
            c["mode"] = rec.get("release_mode")
            c["n_cases"] = len(rec.get("release_plans") or [])
            c["n_decisions"] = sum(len(p.get("decisions") or []) for p in rec.get("release_plans") or [])
            c["n_changes"] = len(rec.get("release_changes") or [])
            c["rewrite_attempts"] = len(rec.get("release_attempts") or [])
            c["extraction_tries"] = rec.get("extraction_tries")
            c["release_extraction_tries"] = rec.get("release_extraction_tries")
        if error:
            c["error"] = error
        llm_wall = sum(v["wall_ms"] for v in c["llm"].values())
        c["llm_wall_ms"] = round(llm_wall, 1)
        c["other_ms"] = round(c["total_ms"] - llm_wall - c["decide_ms"] - c["normalize_ms"]
                              - c["kcalc_ms"].get("recheck", 0) - c["kcalc_ms"].get("record", 0), 1)
        row = _plain(c)
        self.turns.append(row)
        if self._tf:
            self._tf.write(json.dumps(row, ensure_ascii=False) + "\n")
            self._tf.flush()
        self.cur, self.where = None, "between"


def _plain(d: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in d.items():
        if isinstance(v, collections.Counter):
            v = {a: round(b, 3) if isinstance(b, float) else b for a, b in v.items()}
        elif isinstance(v, float):
            v = round(v, 3)
        elif isinstance(v, dict):
            v = {a: ({x: round(y, 1) if isinstance(y, float) else y for x, y in b.items()} if isinstance(b, dict) else b)
                 for a, b in v.items()}
        out[k] = v
    return out


class TimingLLM:
    """가장 안쪽 LLM(ClientRoleLLM · OracleRoleLLM)을 감싸 호출마다 시간과 단계를 남긴다."""

    def __init__(self, inner: Any, clock: Clock) -> None:
        self.inner, self.clock = inner, clock

    @property
    def usage(self) -> list[dict[str, Any]]:
        return self.inner.usage

    def complete(self, role: str, system: str, messages: list[dict[str, str]], **kw: Any) -> str:
        n0 = len(self.inner.usage)
        t0 = time.perf_counter()
        err = None
        try:
            return self.inner.complete(role, system, messages, **kw)
        except Exception as exc:
            err = type(exc).__name__
            raise
        finally:
            self.clock.add_llm(role, (time.perf_counter() - t0) * 1000, self.inner.usage[n0:], err)


class StyleLLM:
    """레드팀 실행(_JobLLM)과 같이 대상 AI 지시문에 답 형식을 붙인다."""

    def __init__(self, inner: Any, on: bool) -> None:
        self.inner, self.on = inner, on

    @property
    def usage(self) -> list[dict[str, Any]]:
        return self.inner.usage

    def complete(self, role: str, system: str, messages: list[dict[str, str]], **kw: Any) -> str:
        from webdemo.backend.live import styled
        return self.inner.complete(role, styled(role, system) if self.on else system, messages, **kw)


def install_timers(ctx: Any, clock: Clock) -> Any:
    """
    k 계산 · 정규화(이 문맥의 인스턴스)와 판정(RuleDefender 클래스, 이 프로세스 안에서만)에 시간 재기를 끼운다.
    돌려주는 함수를 부르면 클래스에 끼운 것을 원래대로 되돌린다.
    """
    from webdemo.backend.review import RuleDefender

    kc, nz = ctx.kc, ctx.nz
    k_orig, n_orig = kc.k, nz.normalize

    def k_timed(ds: Any) -> Any:
        if clock._kdepth:
            return k_orig(ds)
        clock._kdepth += 1
        t0 = time.perf_counter()
        try:
            return k_orig(ds)
        finally:
            clock._kdepth -= 1
            clock.kcalc((time.perf_counter() - t0) * 1000)

    def normalize_timed(*a: Any, **kw: Any) -> Any:
        t0 = time.perf_counter()
        try:
            return n_orig(*a, **kw)
        finally:
            clock.normalized((time.perf_counter() - t0) * 1000)

    kc.k = k_timed
    nz.normalize = normalize_timed

    plan_orig, lines_orig = RuleDefender.plan_case, RuleDefender.change_lines

    def wrap(fn: Any) -> Any:
        def timed(self: Any, *a: Any, **kw: Any) -> Any:
            prev = clock.where
            clock.where = "plan"
            t0 = time.perf_counter()
            try:
                return fn(self, *a, **kw)
            finally:
                ms = (time.perf_counter() - t0) * 1000
                clock.where = prev
                if clock.cur is not None:
                    clock.cur["decide_ms"] += ms
                    if fn is plan_orig:
                        clock.cur["plan_calls"] += 1
        return timed

    RuleDefender.plan_case = wrap(plan_orig)
    RuleDefender.change_lines = wrap(lines_orig)

    def uninstall() -> None:
        RuleDefender.plan_case, RuleDefender.change_lines = plan_orig, lines_orig

    return uninstall


def timed_arm_class(clock: Clock) -> type:
    from webdemo.backend.review import RuledArmRun

    class TimedArmRun(RuledArmRun):
        def _turn(self, turn, query, raw, raw_obs, raw_ok, n_raw_ext, meta, intent=None):   # type: ignore[override]
            clock.begin_turn(self.arm, self.p.trial_id, turn, shared_answer=raw is not None)
            t0 = time.perf_counter()
            rec, err = None, None
            try:
                rec = super()._turn(turn, query, raw, raw_obs, raw_ok, n_raw_ext, meta, intent)
                return rec
            except Exception as exc:
                err = type(exc).__name__
                raise
            finally:
                clock.end_turn(time.perf_counter() - t0, rec, err)

        def release(self, query, raw, raw_obs, raw_ok):     # type: ignore[override]
            clock.where = "release"
            t0 = time.perf_counter()
            try:
                return super().release(query, raw, raw_obs, raw_ok)
            finally:
                if clock.cur is not None:
                    clock.cur["release_ms"] += (time.perf_counter() - t0) * 1000
                clock.where = "post"

        def _verify(self, query, text):                    # type: ignore[override]
            prev = clock.where
            clock.where = "verify"
            t0 = time.perf_counter()
            try:
                return super()._verify(query, text)
            finally:
                if clock.cur is not None:
                    clock.cur["verify_ms"] += (time.perf_counter() - t0) * 1000
                    clock.cur["verify_calls"] += 1
                clock.where = prev

    return TimedArmRun


# ── 환경 기록 ────────────────────────────────────────────────────────

def cpu_info() -> dict[str, Any]:
    info: dict[str, Any] = dict(system=platform.system(), release=platform.release(), machine=platform.machine(),
                                processor=platform.processor(), cpu_count=os.cpu_count(), python=platform.python_version())
    try:
        if sys.platform == "darwin":
            run = lambda *c: subprocess.run(list(c), capture_output=True, text=True, timeout=5, check=False).stdout.strip()
            info["cpu"] = run("sysctl", "-n", "machdep.cpu.brand_string")
            info["memory_gb"] = round(int(run("sysctl", "-n", "hw.memsize") or 0) / 2**30, 1)
            info["macos"] = platform.mac_ver()[0]
        elif Path("/proc/cpuinfo").exists():
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.startswith("model name"):
                    info["cpu"] = line.split(":", 1)[1].strip()
                    break
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal"):
                    info["memory_gb"] = round(int(line.split()[1]) / 2**20, 1)
                    break
    except Exception:          # 기록용이라 실패해도 측정은 한다
        pass
    return info


def git_info() -> dict[str, Any]:
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    run = lambda *c: subprocess.run(["git", *c], cwd=ROOT, capture_output=True, text=True, timeout=10, env=env, check=False).stdout.strip()
    try:
        changed = [ln[3:] for ln in run("status", "--porcelain", "--untracked-files=no").splitlines()]
        return dict(commit=run("rev-parse", "HEAD"), branch=run("rev-parse", "--abbrev-ref", "HEAD"),
                    modified_tracked_files=[f for f in changed if not f.endswith(".pyc")])
    except Exception:
        return {}


# ── 집계 ────────────────────────────────────────────────────────────

def pctl(xs: list[float], q: float) -> float | None:
    """선형 보간 백분위수 (numpy 기본 · 엑셀 PERCENTILE.INC와 같음)."""
    xs = sorted(xs)
    if not xs:
        return None
    pos = (len(xs) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def stats(xs: list[float]) -> dict[str, Any]:
    xs = [float(x) for x in xs if x is not None]
    if not xs:
        return dict(n=0, mean=None, median=None, p95=None, min=None, max=None)
    return dict(n=len(xs), mean=sum(xs) / len(xs), median=pctl(xs, 0.5), p95=pctl(xs, 0.95), min=min(xs), max=max(xs))


def fmt(v: float | None, unit: str = "s") -> str:
    if v is None:
        return "-"
    if unit == "s":
        return f"{v / 1000:.2f}"
    return f"{v:.2f}" if v < 100 else f"{v:.0f}"


def row(name: str, s: dict[str, Any], unit: str = "s", extra: str = "") -> str:
    return f"| {name} | {s['n']} | {fmt(s['mean'], unit)} | {fmt(s['median'], unit)} | {fmt(s['p95'], unit)} | {fmt(s['max'], unit)} |{extra}"


def summarize(out: Path) -> dict[str, Any]:
    meta = json.loads((out / "run_meta.json").read_text(encoding="utf-8")) if (out / "run_meta.json").exists() else {}
    m = meta.get("measurement", {})
    usage = [json.loads(x) for x in (out / "llm_usage.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()] \
        if (out / "llm_usage.jsonl").exists() else []
    trows = [json.loads(x) for x in (out / "턴시간.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()] \
        if (out / "턴시간.jsonl").exists() else []
    errors = [json.loads(x) for x in (out / "llm_errors.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()] \
        if (out / "llm_errors.jsonl").exists() else []
    turns = [r for r in trows if r.get("kind") == "turn"]
    prefixes = [r for r in trows if r.get("kind") == "prefix"]
    res: dict[str, Any] = dict(out=str(out), roles={}, phases={}, arms={}, turn0={}, changed={}, decide={}, kcalc={})
    L: list[str] = []
    L.append(f"# 한 턴 처리 시간 측정 ({out.name})\n")
    if m:
        L.append(f"- 커밋: `{m.get('git', {}).get('commit', '?')}` ({m.get('git', {}).get('branch', '?')})"
                 + (f", 바뀐 추적 파일 {len(m['git'].get('modified_tracked_files') or [])}개" if m.get("git") else ""))
        L.append(f"- 명령: `{m.get('command', '')}`")
        L.append(f"- LLM: {m.get('llm')} · 설정 모델 {json.dumps(m.get('models_configured', {}), ensure_ascii=False)}")
        s = m.get("llm_settings") or {}
        if s:
            L.append(f"- LLM 클라이언트 설정: 요청 간 최소 간격 {s.get('llm_min_interval_sec')}초 · timeout {s.get('llm_timeout_sec')}초 · "
                     f"재시도 {s.get('llm_max_retries')}번 · 동시 호출 1")
        L.append(f"- 실행 조건: 갈래 {m.get('arms')} · 유형마다 {m.get('per_type')}명(질의 환자 {m.get('trials')}명) · "
                 f"턴 0~{m.get('budget')} · 퍼저 {m.get('fuzzer')} · 규칙 추출 {'켬' if m.get('rule_extract') else '끔'} · "
                 f"답 형식 {m.get('answer_style')}")
        c = m.get("cpu") or {}
        L.append(f"- 환경: {c.get('cpu') or c.get('processor') or c.get('machine')} · 코어 {c.get('cpu_count')} · "
                 f"메모리 {c.get('memory_gb')}GB · {c.get('system')} {c.get('macos') or c.get('release')} · Python {c.get('python')}")
        L.append(f"- 시작 {m.get('started_at')} · 끝 {m.get('finished_at') or '(중간에 멈춤)'}")
    L.append("\n시간 단위는 초. p95는 선형 보간 백분위수. n이 작으면 p95는 최댓값 근처의 한두 값으로 정해진다.\n")

    # 1) 역할별 (요청서 표: 역할 · 모델 · 호출 수 · 평균 · 중앙값 · p95)
    L.append("## 1. 역할별 LLM 응답 시간 (llm_usage.jsonl의 latency_ms)\n")
    L.append("| 역할 | 모델 | 호출 수 | 평균 | 중앙값 | p95 | 최대 | wall 평균 | wall p95 | 출력 토큰 평균 |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    by_role: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for u in usage:
        by_role[u.get("role")].append(u)
    for e in errors:
        by_role.setdefault(e.get("role"), [])
    for role in sorted(by_role, key=lambda r: ROLE_ORDER.index(r) if r in ROLE_ORDER else 99):
        us = by_role[role]
        lat = stats([u["latency_ms"] for u in us if u.get("latency_ms") is not None])
        wall = stats([u["wall_ms"] for u in us if u.get("wall_ms") is not None])
        models = sorted({str(u.get("model")) for u in us if u.get("model")})
        outk = [u["output_tokens"] for u in us if u.get("output_tokens") is not None]
        errs = sum(1 for e in errors if e.get("role") == role)
        out_mean = sum(outk) / len(outk) if outk else None
        res["roles"][role] = dict(models=models, latency=lat, wall=wall, errors=errs, output_tokens_mean=out_mean)
        calls = f"{lat['n']}" + (f" (실패 {errs})" if errs else "")
        L.append(f"| {role} | {', '.join(models) or '-'} | {calls} | {fmt(lat['mean'])} | {fmt(lat['median'])} | {fmt(lat['p95'])} | "
                 f"{fmt(lat['max'])} | {fmt(wall['mean'])} | {fmt(wall['p95'])} | {'-' if out_mean is None else f'{out_mean:.0f}'} |")

    # 2) 단계별 (추출을 원 답 추출과 다시 확인 추출로 나눔)
    L.append("\n## 2. 단계별 LLM 응답 시간\n")
    L.append("| 단계 | 호출 수 | 평균 | 중앙값 | p95 | 최대 |")
    L.append("| --- | --- | --- | --- | --- | --- |")
    for ph in ("answer", "extract", "rewrite", "recheck", "attack", "docs"):
        xs = [u["latency_ms"] for u in usage if u.get("phase") == ph and u.get("latency_ms") is not None]
        if not xs:
            continue
        s = stats(xs)
        res["phases"][ph] = s
        L.append(row(PHASE_KO.get(ph, ph), s))

    # 3) 판정 · k 계산 (LLM 없음)
    L.append("\n## 3. k 계산 · 판정 시간 (LLM 없음)\n")
    L.append("잰 곳: `RuleDefender.plan_case` + `change_lines` (안의 `MedicalDefender.plan_case` → `GroupRepairKC.k` 포함), 턴마다 모든 사례 합. "
             "`GroupRepairKC.k`는 한 번 부를 때마다. 시간 단위는 ms.\n")
    L.append("| 항목 | 턴 수 | 평균 | 중앙값 | p95 | 최대 | 턴마다 k 호출 수 평균 | k 1회 평균 |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for arm in sorted({t["arm"] for t in turns if t.get("plan_calls")}):
        ts = [t for t in turns if t["arm"] == arm and t.get("plan_calls")]
        s = stats([t["decide_ms"] for t in ts])
        kn = sum((t.get("kcalc_calls") or {}).get("decide", 0) for t in ts)
        km = sum((t.get("kcalc_ms") or {}).get("decide", 0) for t in ts)
        pc = [t["plan_calls"] for t in ts]
        res["decide"][arm] = dict(s, plan_calls_mean=sum(pc) / len(pc), kcalc_calls_mean=kn / len(ts), kcalc_per_call_ms=km / kn if kn else None)
        L.append(row(f"판정 ({arm}, 판정한 턴)", s, "ms", extra=f" {kn / len(ts):.1f} | {fmt(km / kn if kn else None, 'ms')} |"))
    for st, name in (("recheck", "다시 확인의 k 재계산 (다시 확인한 턴)"), ("record", "기록용 k (사례마다 후보 수, 모든 턴)")):
        ts = [t for t in turns if (t.get("kcalc_calls") or {}).get(st)]
        if not ts:
            continue
        s = stats([t["kcalc_ms"][st] for t in ts])
        kn = sum(t["kcalc_calls"][st] for t in ts)
        km = sum(t["kcalc_ms"][st] for t in ts)
        res["kcalc"][st] = dict(s, calls_mean=kn / len(ts), per_call_ms=km / kn)
        L.append(row(name, s, "ms", extra=f" {kn / len(ts):.1f} | {fmt(km / kn, 'ms')} |"))
    norm = stats([t["normalize_ms"] for t in turns if t.get("normalize_ms")])
    res["kcalc"]["normalize_per_turn"] = norm
    L.append(row("정규화 (추출 결과 → 노드, 모든 턴)", norm, "ms", extra=" - | - |"))
    for arm in sorted({t["arm"] for t in turns}):
        ts = [t for t in turns if t["arm"] == arm and not t.get("shared_answer")]
        if ts:
            s = stats([t["total_ms"] - t.get("llm_wall_ms", 0) for t in ts])
            res["kcalc"][f"non_llm_per_turn_{arm}"] = s
            L.append(row(f"LLM 호출을 뺀 턴 시간 전체 ({arm}, 턴 1 이후)", s, "ms", extra=" - | - |"))
    if res["decide"]:
        L.append("\n판정은 사례마다 한 번이다. 바꿀 것이 있는 턴은 최소 공개 단위만 맞추면 되는지 먼저 보고, 아니면 공개 단계에서 한 번 더 판정한다.")

    # 4) 재작성 · 다시 확인 (바꾼 턴만)
    L.append("\n## 4. 재작성 · 다시 확인 시간 (바꾼 턴만)\n")
    L.append("공개 단계 시간에서 판정 시간을 뺀 값 = 재작성 호출 + 다시 확인(추출 + 정규화 + k 재계산) + 값 치환 · 사례 빼기.\n")
    L.append("| 공개 방식 | 턴 수 | 평균 | 중앙값 | p95 | 최대 | 재작성 평균 | 다시 확인 평균 | 다시 확인 횟수 평균 |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    changed = [t for t in turns if t.get("mode") and t["mode"] != "RAW" and t.get("arm") != "C0"]
    groups = collections.defaultdict(list)
    for t in changed:
        groups[t["mode"]].append(t)
    groups["(바꾼 턴 전체)"] = changed
    for mode, ts in groups.items():
        if not ts:
            continue
        s = stats([t["release_ms"] - t["decide_ms"] for t in ts])
        rw = [t["llm"].get("rewrite", {}).get("wall_ms", 0) for t in ts]
        vf = [t["verify_ms"] for t in ts]
        vc = [t["verify_calls"] for t in ts]
        res["changed"][mode] = dict(s, rewrite_mean=sum(rw) / len(rw), verify_mean=sum(vf) / len(vf), verify_calls_mean=sum(vc) / len(vc))
        L.append(row(mode, s, extra=f" {sum(rw) / len(rw) / 1000:.2f} | {sum(vf) / len(vf) / 1000:.2f} | {sum(vc) / len(vc):.1f} |"))

    # 5) 턴 전체 (갈래별)
    L.append("\n## 5. 턴 전체 시간 (갈래별)\n")
    L.append("턴 1 이후(턴마다 대상 AI 답이 새로 생기는 턴). `ArmRun._turn` 한 번의 시작~끝. 공격 질문 만들기는 넣지 않는다.\n")
    L.append("| 갈래 | 턴 수 | 평균 | 중앙값 | p95 | 최대 | 대상 AI 답 | 추출 | 판정 | 재작성 | 다시 확인 | 정규화 · 기록 · 기타 |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for arm in sorted({t["arm"] for t in turns}, key=lambda a: ("C0", "C1", "C1S").index(a) if a in ("C0", "C1", "C1S") else 9):
        ts = [t for t in turns if t["arm"] == arm and not t.get("shared_answer")]
        if not ts:
            continue
        s = stats([t["total_ms"] for t in ts])
        mean = lambda f, ts=ts: sum(f(t) for t in ts) / len(ts) / 1000
        parts = dict(answer=mean(lambda t: t["llm"].get("answer", {}).get("wall_ms", 0)),
                     extract=mean(lambda t: t["llm"].get("extract", {}).get("wall_ms", 0)),
                     decide=mean(lambda t: t["decide_ms"]),
                     rewrite=mean(lambda t: t["llm"].get("rewrite", {}).get("wall_ms", 0)),
                     recheck=mean(lambda t: t["verify_ms"]))
        parts["rest"] = s["mean"] / 1000 - sum(parts.values())
        api = mean(lambda t: sum(v.get("latency_ms", 0) for v in t["llm"].values()))
        wall = mean(lambda t: t.get("llm_wall_ms", 0))
        res["arms"][arm] = dict(s, parts=parts, llm_latency_mean=api, llm_wall_mean=wall,
                                modes=dict(collections.Counter(t.get("mode") for t in ts)))
        L.append(row(arm, s, extra=" " + " | ".join(f"{parts[k]:.2f}" for k in ("answer", "extract", "decide", "rewrite", "recheck", "rest")) + " |"))
    for arm, r in res["arms"].items():
        L.append(f"\n- {arm}: 턴 평균 {r['mean'] / 1000:.2f}초 중 LLM 호출 {r['llm_wall_mean']:.2f}초"
                 f"(서버 응답 시간 합 {r['llm_latency_mean']:.2f}초, 차이는 요청 간격 대기 · 실패한 재시도). 공개 방식 {r['modes']}")

    # 6) 턴 0
    if prefixes:
        L.append("\n## 6. 턴 0 (사례 검색 첫 답)\n")
        L.append("첫 답의 대상 AI 답 · 추출은 갈래가 나눠 쓴다(한 번). 갈래마다 다른 것은 공개 단계뿐이다.\n")
        L.append("| 항목 | n | 평균 | 중앙값 | p95 | 최대 |")
        L.append("| --- | --- | --- | --- | --- | --- |")
        a = stats([p["llm"].get("answer", {}).get("wall_ms", 0) for p in prefixes])
        e = stats([p["llm"].get("extract", {}).get("wall_ms", 0) for p in prefixes])
        res["turn0"]["answer"], res["turn0"]["extract"] = a, e
        L.append(row("첫 답 대상 AI", a))
        L.append(row("첫 답 추출", e))
        for arm in sorted({t["arm"] for t in turns if t.get("shared_answer")}):
            s = stats([t["total_ms"] for t in turns if t["arm"] == arm and t.get("shared_answer")])
            res["turn0"][arm] = s
            L.append(row(f"{arm} 턴 0 나머지 (공개 단계 · 기록)", s))

    L.append("\n## 7. 턴 합과 단계 합이 다른 까닭\n")
    L.append("- wall과 latency_ms: latency_ms는 마지막 요청의 서버 응답 시간이다. wall은 .env의 요청 간 최소 간격 대기, "
             "실패한 요청의 재시도 · 대기, 답이 잘려 출력 한도를 늘려 다시 부른 시간을 포함한다.")
    L.append("- 추출 형식이 틀리면 같은 답을 다시 추출한다(최대 3번). 재작성은 두 번까지 시도하고 매번 다시 확인 추출을 한다.")
    L.append("- 바꿀 것이 있는 턴은 판정을 두 번 한다(최소 공개 단위만 바꾸면 되는지 먼저 보고, 아니면 공개 단계에서 다시).")
    L.append("- 정규화 · 기록용 k(사례마다 후보 수와 방어 전 후보 수)는 '기타'에 들어간다. 호출은 한 번에 하나씩(동시 호출 1)이라 병렬로 겹치는 시간은 없다.")
    text = "\n".join(L) + "\n"
    (out / "시간요약.md").write_text(text, encoding="utf-8")
    (out / "시간요약.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return dict(res, text=text)


# ── 실행 ────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python scripts/measure_latency.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--llm", choices=("real", "oracle"), default="real")
    ap.add_argument("--per-type", default="2", help="질의 유형마다 질의 환자 수 (all = 전원)")
    ap.add_argument("--arms", default="C0,C1")
    ap.add_argument("--budget", type=int, default=7, help="이어지는 턴 수. 7이면 턴 0~7 (발표 결과 ①·③의 8턴)")
    ap.add_argument("--fuzzer", choices=("uniform", "feedback"), default="uniform")
    ap.add_argument("--mode", choices=("efficiency", "exploration"), default="efficiency")
    ap.add_argument("--answer-style", choices=("on", "off"), default="on")
    ap.add_argument("--no-rule-extract", action="store_true")
    ap.add_argument("--extractor-model", default=None)
    ap.add_argument("--rewriter-model", default=None)
    ap.add_argument("--env-file", default=None)
    ap.add_argument("--timeout", type=float, default=180.0, help="LLM 요청 timeout 초 (.env 값보다 작으면 이 값)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--summarize", default=None, metavar="폴더", help="측정 없이 기록으로 표만 다시 만든다")
    a = ap.parse_args(argv)

    if a.summarize:
        print(summarize(Path(a.summarize))["text"])
        return 0

    import dataclasses

    from core.llm_client import LLMError
    from medical.config import MedicalConfig
    from medical.data import MedicalData
    from medical.experiment import build_context
    from medical.session import dumps, make_prefix
    from medical.simulate import plan_all
    from medical.validate import validate_trial
    from webdemo.backend.live import ANSWER_STYLE_ID

    per_type = None if a.per_type == "all" else int(a.per_type)
    arms = tuple(x.strip() for x in a.arms.split(",") if x.strip())
    out = Path(a.out or ROOT / "runs" / "latency" / f"{time.strftime('%Y%m%d_%H%M%S')}_{a.llm}")
    out.mkdir(parents=True, exist_ok=True)
    data = MedicalData()
    cfg = MedicalConfig(arms=arms, fuzzer=a.fuzzer, mode=a.mode, budget_B=a.budget, rule_extract=not a.no_rule_extract)
    role_models = {r: m for r, m in dict(extractor=a.extractor_model, rewriter=a.rewriter_model).items() if m}
    measurement: dict[str, Any] = dict(command=" ".join(["python", "scripts/measure_latency.py", *(argv if argv is not None else sys.argv[1:])]),
                                       llm=a.llm, arms=list(arms), per_type=a.per_type, budget=a.budget, fuzzer=a.fuzzer, mode=a.mode,
                                       rule_extract=cfg.rule_extract, answer_style=ANSWER_STYLE_ID if a.answer_style == "on" else "off",
                                       concurrency=1, path="RedTeamJob._group과 같음: make_prefix → RuledArmRun(live=True).run()",
                                       git=git_info(), cpu=cpu_info(), started_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    if a.llm == "real":
        from core.config import get_settings
        from core.llm_client import LLMClient
        from medical.llm import ClientRoleLLM
        st = get_settings(a.env_file)
        st = dataclasses.replace(st, llm_timeout_sec=max(st.llm_timeout_sec, a.timeout))
        d = st.describe()
        measurement["llm_settings"] = {k: d[k] for k in ("llm_model", "llm_max_tokens", "llm_timeout_sec", "llm_max_retries", "llm_min_interval_sec")}
        measurement["models_configured"] = {r: role_models.get(r, st.llm_model) for r in ("target", "extractor", "rewriter", "mutator", "checker")}
        inner = ClientRoleLLM(LLMClient(st), models=role_models, temperature=cfg.temperature)
    else:
        from medical.simulate import OracleRoleLLM
        measurement["models_configured"] = {"all": "oracle (LLM 호출 없음)"}
        inner = OracleRoleLLM(data=data, profile="staged")
        a.answer_style = "off"
        measurement["answer_style"] = "off (결정적 응답기)"

    for f in ("llm_usage.jsonl", "턴시간.jsonl", "llm_errors.jsonl"):
        (out / f).write_text("", encoding="utf-8")
    clock = Clock(out / "llm_usage.jsonl", out / "턴시간.jsonl", out / "llm_errors.jsonl")
    llm = StyleLLM(TimingLLM(inner, clock), a.answer_style == "on")
    print(f"[측정] 준비 중 (기준 집단 · 문서) → {out}")
    ctx, split = build_context(cfg, llm, out, data=data)
    uninstall = install_timers(ctx, clock)
    Arm = timed_arm_class(clock)
    plan = plan_all(per_type, cfg.seed)(ctx.data, split, cfg)
    measurement["trials"] = len(plan)

    def save_meta(finished: bool) -> None:
        meta = json.loads((out / "run_meta.json").read_text(encoding="utf-8"))
        if finished:
            measurement["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        meta["measurement"] = measurement
        (out / "run_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    save_meta(False)
    print(f"[측정] 질의 환자 {len(plan)}명 × 갈래 {','.join(arms)} · 턴 0~{a.budget} · LLM {a.llm}"
          + (f" (모델 {measurement['models_configured']['target']}"
             + "".join(f", {r} {m}" for r, m in role_models.items()) + ")" if a.llm == "real" else ""))
    doc_patient = {dd["doc_id"]: p for p, dd in ctx.docs.items()}
    trials: list[dict[str, Any]] = []
    t_start = time.time()
    finished = False
    try:
        with open(out / "턴기록.jsonl", "w", encoding="utf-8") as tf:
            log = lambda rec: (tf.write(dumps(rec) + "\n"), tf.flush())
            failed = 0
            for i, (tid, pid, qt, role) in enumerate(plan, 1):
                clock.begin_prefix(tid)
                try:
                    prefix = make_prefix(ctx, tid, pid, qt, role)
                except LLMError as exc:                 # 레드팀 실행과 같이 그 질의 환자는 빼고 다음으로
                    failed += 1
                    print(f"[측정] {i}/{len(plan)} {tid}: 첫 답 LLM 호출 실패 ({type(exc).__name__}) → 뺌")
                    if failed >= 3 and not trials:
                        raise SystemExit("LLM 호출이 처음 세 질의 환자에서 모두 실패했습니다. 키 · 주소 · 호출 한도를 확인하세요 (python -m medicloak check-llm).") from exc
                    continue
                finally:
                    clock.end_prefix()
                for arm in arms:
                    t = Arm(ctx, prefix, arm, log, list, live=True).run()          # 보안 담당자 규칙 없음 (레드팀과 같음)
                    clock.where = "between"
                    if t.get("case_committed") is not None:
                        t["validation"] = validate_trial(t, ctx.data, ctx.kc, doc_patient, cfg.k_req)
                    trials.append(t)
                    n_calls = len(inner.usage)
                    print(f"[측정] {i}/{len(plan)} {tid} {qt} {arm}: {t['outcome']} 턴 {t.get('turns')} · "
                          f"누적 {time.time() - t_start:.0f}초 · LLM 호출 {n_calls}번")
        finished = True
    except KeyboardInterrupt:
        print("\n[측정] 멈춤. 끝난 턴까지 집계합니다.")
    finally:
        uninstall()
        clock.close()
        from webdemo.backend.review import RELEASE_VERSION
        versions = dict(ctx.versions, medicloak_release=RELEASE_VERSION, answer_style=measurement["answer_style"])   # 레드팀 실행 기록과 같은 꼴
        summary = dict(config=cfg.as_dict(), versions=versions, trials=trials)
        (out / "trial요약.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        save_meta(finished)
    r = summarize(out)
    print(r["text"])
    print(f"결과: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
