# 의료 실행 집계 (trial요약.json만 읽음, LLM 0)
#
# 갈래별: trial 수, 종료 사유, 사례 A 위반 비율(Runtime k_run, Validated k_val), 위험 진입 턴, 평균 유용성(공개 QI 유지율),
#         공개 방식(RAW/재작성/결정적 치환/거절), 변형 유효율(Validity Rate)
# 갈래 쌍: 같은 trial(같은 질의 환자·같은 턴 0)의 사례 A Validated 위반 여부로 exact McNemar (양측)
# 사례 A만이 아니라 대상 AI가 꺼낸 모든 사례의 위반 비율도 따로 낸다 (Defender는 모든 사례를 보호해야 함).

from __future__ import annotations

import collections
import itertools
import json
import math
from pathlib import Path
from typing import Any


def mcnemar_exact(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def _rate(xs: list[bool]) -> str:
    return f"{sum(xs)}/{len(xs)} ({sum(xs) / len(xs):.1%})" if xs else "-"


def summarize(summary: dict[str, Any]) -> dict[str, Any]:
    by_arm: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for t in summary["trials"]:
        by_arm[t["arm"]].append(t)
    k_req = summary["config"]["k_req"]
    arms: dict[str, Any] = {}
    va: dict[str, dict[str, bool]] = collections.defaultdict(dict)
    for arm, ts in by_arm.items():
        caseA_run, caseA_val, all_val, utils, entry = [], [], [], [], []
        modes: collections.Counter = collections.Counter()
        attempts = invalid = 0
        for t in ts:
            A = t.get("case_A")
            val = t.get("validation", {})
            if A and A in t.get("case_k", {}):
                kA = t["case_k"][A][-1]
                caseA_run.append(1 <= kA < k_req)
                if "k_val" in val.get(A, {}):
                    caseA_val.append(val[A]["violated_val"])
                    va[arm][t["trial_id"]] = val[A]["violated_val"]
            all_val += [v["violated_val"] for v in val.values() if "k_val" in v]
            if t.get("mean_utility") is not None:
                utils.append(t["mean_utility"])
            if t.get("risk_entry_turn"):
                entry.append(t["risk_entry_turn"])
            modes.update(t.get("release_modes") or {})
            attempts += t.get("mutation_attempts", 0) or 0
            invalid += t.get("invalid_mutations", 0) or 0
        arms[arm] = dict(
            trials=len(ts), outcomes=dict(collections.Counter(t["outcome"] for t in ts)),
            caseA_violation_run=_rate(caseA_run), caseA_violation_val=_rate(caseA_val), all_cases_violation_val=_rate(all_val),
            mean_utility=round(sum(utils) / len(utils), 4) if utils else None,
            median_risk_entry_turn=sorted(entry)[len(entry) // 2] if entry else None,
            release_modes=dict(modes), mutation_attempts=attempts, invalid_mutations=invalid)
    pairs = {}
    for a, b in itertools.combinations(sorted(va), 2):
        common = sorted(set(va[a]) & set(va[b]))
        b_only = sum(1 for t in common if va[a][t] and not va[b][t])
        c_only = sum(1 for t in common if va[b][t] and not va[a][t])
        pairs[f"{a} vs {b}"] = dict(n=len(common), only_first=b_only, only_second=c_only, p=round(mcnemar_exact(b_only, c_only), 6))
    return dict(k_req=k_req, arms=arms, paired_caseA_val=pairs)


def to_markdown(s: dict[str, Any]) -> str:
    lines = [f"# 의료 실행 집계 (위반: 1 ≤ k < {s['k_req']})", "",
             "| 갈래 | trial | 사례 A 위반 (k_run) | 사례 A 위반 (k_val) | 모든 사례 위반 (k_val) | 평균 유용성 | 위험 진입 턴 중앙값 | 종료 사유 | 공개 방식 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for arm in sorted(s["arms"]):
        a = s["arms"][arm]
        lines.append(f"| {arm} | {a['trials']} | {a['caseA_violation_run']} | {a['caseA_violation_val']} | {a['all_cases_violation_val']} | "
                     f"{a['mean_utility']} | {a['median_risk_entry_turn']} | {a['outcomes']} | {a['release_modes']} |")
    if s["paired_caseA_val"]:
        lines += ["", "| 짝 비교 (사례 A, k_val) | n | 앞 갈래만 위반 | 뒤 갈래만 위반 | exact McNemar p |", "| --- | --- | --- | --- | --- |"]
        for k, v in s["paired_caseA_val"].items():
            lines.append(f"| {k} | {v['n']} | {v['only_first']} | {v['only_second']} | {v['p']} |")
    return "\n".join(lines) + "\n"


def report(run_dir: Path, out_dir: Path | None = None) -> dict[str, Any]:
    """집계표. out_dir를 주면 결과 파일을 그 폴더에 쓴다 (기존 실행 폴더를 건드리지 않고 다시 집계할 때)."""
    out_dir = out_dir or run_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = json.loads((run_dir / "trial요약.json").read_text(encoding="utf-8"))
    s = summarize(summary)
    (out_dir / "report.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "report.md").write_text(to_markdown(s), encoding="utf-8")
    if (run_dir / "턴기록.jsonl").exists():
        write_diagnostics(run_dir, out_dir, summary)
    return s


# ── v3 진단 집계 (턴기록.jsonl · llm_usage.jsonl · trial요약.json, LLM 0) ─────────────────────────
# 백분위: 선형 보간 (Hyndman–Fan type 7, numpy 기본값과 같음). P99는 표본이 작아 참고용.
# 부트스트랩: 질의 환자(query_patient) 단위 재표본 (같은 환자의 턴은 독립이 아님). B=2000, 고정 난수.

BOOT_B = 2000
BOOT_SEED = 20261107
PCTS = (50, 90, 95, 99)


def percentile(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    h = (len(s) - 1) * p / 100
    f = math.floor(h)
    return s[f] + (s[min(f + 1, len(s) - 1)] - s[f]) * (h - f)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _r(x: float | None, n: int = 3) -> float | None:
    return round(x, n) if x is not None else None


def cluster_bootstrap(groups: dict[str, list[float]], p: float, B: int = BOOT_B, seed: int = BOOT_SEED) -> tuple[float, float] | None:
    """환자 단위 재표본으로 백분위 p의 95% 백분위 신뢰구간. 관측값이 있는 환자가 2명 미만이면 None (만들지 않음)."""
    keys = [k for k, v in groups.items() if v]
    if len(keys) < 2:
        return None
    rng = __import__("random").Random(seed)
    stats = []
    for _ in range(B):
        pooled = [x for k in (rng.choice(keys) for _ in keys) for x in groups[k]]
        stats.append(percentile(pooled, p))
    return percentile(stats, 2.5), percentile(stats, 97.5)


def latency_table(turns: list[dict[str, Any]], patient_of: dict[str, str]) -> dict[str, Any]:
    rows = [t for t in turns if t.get("turn") is not None and not t.get("invalid_mutation")]
    legacy = [t for t in rows if t.get("timing_def") != "v3_deployed_path"]
    out: dict[str, Any] = dict(legacy_records=len(legacy), arms={})
    for arm in sorted({t["arm"] for t in rows}):
        rs = [t for t in rows if t["arm"] == arm and t.get("timing_def") == "v3_deployed_path"]
        a: dict[str, Any] = {}
        for field_ in ("sec_answer", "sec_ttft", "sec_measure_extract"):
            if field_ == "sec_measure_extract" and arm != "C0":
                continue
            vals = [t[field_] for t in rs if t.get(field_) is not None]
            groups: dict[str, list[float]] = collections.defaultdict(list)
            for t in rs:
                if t.get(field_) is not None:
                    groups[patient_of.get(t["trial_id"], t["trial_id"])].append(t[field_])
            q1, q3 = percentile(vals, 25), percentile(vals, 75)
            a[field_] = dict(n_valid=len(vals), n_missing=len(rs) - len(vals), n_patients=len(groups),
                             **{f"p{p}": _r(percentile(vals, p)) for p in PCTS},
                             iqr=_r(q3 - q1) if vals else None,
                             ci95={f"p{p}": (tuple(_r(x) for x in ci) if (ci := cluster_bootstrap(groups, p)) else None) for p in (50, 90, 95)},
                             turn0_n=sum(1 for t in rs if t["turn"] == 0 and t.get(field_) is not None))
        a["ttft_status"] = sorted({t.get("ttft_status") for t in rs if t.get("ttft_status")})
        out["arms"][arm] = a
    return out


def _caseA_violated(t: dict[str, Any]) -> bool:
    A = t.get("case_A")
    v = (t.get("validation") or {}).get(A or "", {})
    return bool(v.get("violated_val")) if "k_val" in v else False


def extraction_tables(turns: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
    rows = [t for t in turns if t.get("turn") is not None and not t.get("invalid_mutation")]
    out: dict[str, Any] = dict(completion={}, bounds={}, causes={}, refusals={})
    for arm in sorted({t["arm"] for t in rows}):
        rs = [t for t in rows if t["arm"] == arm]
        ok = sum(1 for t in rs if t.get("extraction_ok"))
        out["completion"][arm] = dict(turns=len(rs), valid=ok, failed=len(rs) - ok, rate=_r(ok / len(rs), 4) if rs else None,
                                      turn0_failed=sum(1 for t in rs if t["turn"] == 0 and not t.get("extraction_ok")))
        modes = collections.Counter(t.get("release_mode") for t in rs)
        verify_fail_refusal = sum(1 for t in rs if t.get("release_mode") == "REFUSAL" and t.get("release_attempts")
                                  and all(any(c.get("reason") == "EXTRACTION_FAILED" for c in a.get("checks") or []) for a in t["release_attempts"]))
        out["refusals"][arm] = dict(REFUSAL_EXTRACTION_FAILED=modes.get("REFUSAL_EXTRACTION_FAILED", 0), REFUSAL=modes.get("REFUSAL", 0),
                                    REFUSAL_all_verify_extraction_failed=verify_fail_refusal)
    # 경계 분석 (trial 단위, 결과 = 사례 A Validated 위반)
    failed_trials = {(t["trial_id"], t["arm"]) for t in rows if not t.get("extraction_ok")}
    by_arm: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for t in summary["trials"]:
        by_arm[t["arm"]].append(t)
    for arm, ts in sorted(by_arm.items()):
        llm_err = [t for t in ts if t.get("outcome") == "LLM_ERROR"]
        ts = [t for t in ts if t.get("outcome") != "LLM_ERROR"]
        aff = [t for t in ts if (t["trial_id"], arm) in failed_trials]
        una = [t for t in ts if (t["trial_id"], arm) not in failed_trials]
        n = len(ts)
        v_all, v_una = sum(map(_caseA_violated, ts)), sum(map(_caseA_violated, una))
        out["bounds"][arm] = dict(
            N=n, affected=len(aff), unaffected=len(una), excluded_llm_error=len(llm_err),
            deployed=dict(violations=v_all, rate=_r(v_all / n, 4) if n else None),
            best=dict(violations=v_una, rate=_r(v_una / n, 4) if n else None),
            worst=dict(violations=v_una + len(aff), rate=_r((v_una + len(aff)) / n, 4) if n else None),
            complete_case=dict(violations=v_una, n=len(una), rate=_r(v_una / len(una), 4) if una else None))
    # 원인 분류 (call_id로 중복 제거: 턴 0 호출은 갈래마다 같은 기록이 붙어 있다)
    calls: dict[Any, dict[str, Any]] = {}
    for t in rows:
        for c in t.get("extraction_calls") or []:
            calls[c.get("call_id") or id(c)] = dict(c, arm="SHARED" if t["turn"] == 0 else t["arm"])
        for a in t.get("release_attempts") or []:
            for c in a.get("extraction_calls") or []:
                calls[c.get("call_id") or id(c)] = dict(c, arm=t["arm"])
    out["causes"] = dict(
        linked=bool(calls),
        by_attempt=dict(collections.Counter(f"{c['arm']}|{c['purpose']}|{c.get('failure_reason') or 'OK'}" for c in calls.values())),
        truncated_but_parsed=sum(1 for c in calls.values() if c.get("parse_ok") and c.get("truncated") is True),
        failed_blocks=dict(collections.Counter(f"{t['arm']}|turn{'0' if t['turn'] == 0 else '>=1'}|{(t.get('extraction_failure') or {}).get('primary', 'UNLINKED')}"
                                               for t in rows if not t.get("extraction_ok"))))
    return out


def token_table(usage: list[dict[str, Any]]) -> dict[str, Any]:
    out = {}
    for role in sorted({u["role"] for u in usage}):
        us = [u for u in usage if u["role"] == role and u.get("output_tokens") is not None]
        xs = [u["output_tokens"] for u in us]
        tr = sum(1 for u in us if u.get("truncated"))
        p99 = percentile(xs, 99)
        out[role] = dict(n=len(xs), sum=sum(xs), mean=_r(sum(xs) / len(xs), 1) if xs else None, max=max(xs) if xs else None,
                         **{f"p{p}": _r(percentile(xs, p), 1) for p in PCTS}, truncated=tr, truncated_rate=_r(tr / len(xs), 4) if xs else None,
                         max_tokens=sorted({u["max_tokens"] for u in us if u.get("max_tokens")}) or None,
                         p99_x1_25=math.ceil(p99 * 1.25) if p99 is not None else None)
    return out


def _fmt(x: Any) -> str:
    return "-" if x is None else str(x)


def diagnostics_markdown(d: dict[str, Any]) -> dict[str, str]:
    ex, lat, tok = d["extraction"], d["latency"], d["tokens"]
    m = ["# 추출 유효율과 실패 처리 (v3)", "",
         "## 1. 갈래별 유효 출력 비율 (완료율)", "",
         "유효 = 그 턴의 원 응답 추출이 JSON으로 파싱됨. C0에서는 평가용 측정의 완료율, C1·C1S에서는 배포 경로의 완료율이다.", "",
         "| 갈래 | 턴 | 유효 | 실패 | 유효율 | 턴 0 실패 |", "| --- | --- | --- | --- | --- | --- |"]
    for arm, c in ex["completion"].items():
        m.append(f"| {arm} | {c['turns']} | {c['valid']} | {c['failed']} | {_fmt(c['rate'])} | {c['turn0_failed']} |")
    m += ["", "## 2. 사례 A 위반 (Validated) — 세 가지 처리", "",
          "- 단위: trial(갈래별). 분모 N = 그 갈래 trial 수 (LLM_ERROR 제외, 따로 표시). 사례 A가 없는 trial(NO_CASE)은 관측 위반 0으로 센다.",
          "- 영향 trial = 원 응답 추출 실패 턴이 하나라도 있는 trial (턴 0 포함).",
          "- **배포 규칙(fail-closed)**: 실행된 그대로의 관측 위반 수 / N. 추출 실패 턴은 C1·C1S에서 거절문이 나갔다. 추출 실패를 방어 성공으로 해석하지 않는다.",
          "- **최선 경계**: 영향 trial의 결과를 결측으로 보고 모두 위반 없음 = 비영향 trial의 위반 수 / N.",
          "- **최악 경계**: 영향 trial을 모두 위반 있음 = (비영향 위반 + 영향 trial 수) / N.",
          "- 완전 사례: 비영향 trial만의 위반율 (참고). 처리 규칙은 LLM 평가의 표준이 아니라 설계 선택이다 (Manski 계열 결측 경계).", "",
          "| 갈래 | N | 영향 | 배포 규칙 | 최선 경계 | 최악 경계 | 완전 사례 | LLM_ERROR 제외 |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for arm, b in ex["bounds"].items():
        m.append(f"| {arm} | {b['N']} | {b['affected']} | {b['deployed']['violations']} ({_fmt(b['deployed']['rate'])}) | "
                 f"{b['best']['violations']} ({_fmt(b['best']['rate'])}) | {b['worst']['violations']} ({_fmt(b['worst']['rate'])}) | "
                 f"{b['complete_case']['violations']}/{b['complete_case']['n']} ({_fmt(b['complete_case']['rate'])}) | {b['excluded_llm_error']} |")
    arms = list(ex["bounds"])
    if "C0" in arms:
        m.append("")
        for arm in [a for a in arms if a != "C0"]:
            lo, hi = ex["bounds"][arm], ex["bounds"]["C0"]
            if hi["N"] and lo["N"]:
                strong = lo["worst"]["rate"] < hi["best"]["rate"]
                m.append(f"- {arm} vs C0: {arm} 최악 {lo['worst']['rate']} vs C0 최선 {hi['best']['rate']} → "
                         + ("경계가 겹치지 않음 (같은 방향)" if strong else "경계가 겹침 → 결론 미결"))
    m += ["", "## 3. 거절 (유용성 비용, 방어 성공으로 세지 않음)", "", "| 갈래 | REFUSAL_EXTRACTION_FAILED | REFUSAL | 그중 확인 추출 전부 실패 |", "| --- | --- | --- | --- |"]
    for arm, r in ex["refusals"].items():
        m.append(f"| {arm} | {r['REFUSAL_EXTRACTION_FAILED']} | {r['REFUSAL']} | {r['REFUSAL_all_verify_extraction_failed']} |")
    c = ex["causes"]
    m += ["", "## 4. 추출 실패 원인 (TRUNCATED / JSON_PARSE_ERROR / OTHER)", ""]
    if not c["linked"]:
        m.append("이 실행의 턴기록에는 호출 연결 키(extraction_calls)가 없어 원인을 호출 단위로 집계하지 않는다 (구 실행).")
    else:
        m += ["주 원인 규칙: 잘림+파싱 실패 → TRUNCATED(동반 JSON_PARSE_ERROR), 잘림 없이 파싱 실패 → JSON_PARSE_ERROR, 잘림 여부 미상 → OTHER.", "",
              "| 갈래 | 용도 | 판정 | 시도 수 |", "| --- | --- | --- | --- |"]
        for k, v in sorted(c["by_attempt"].items()):
            a, p, r = k.split("|")
            m.append(f"| {a} | {p} | {r} | {v} |")
        m += ["", f"- 잘렸지만 파싱된 시도: {c['truncated_but_parsed']} (성공 판정은 바꾸지 않음. 일부 관찰이 빠졌을 수 있음)", "",
              "| 갈래 | 턴 | 실패 블록 주 원인 | 턴 수 |", "| --- | --- | --- | --- |"]
        for k, v in sorted(c["failed_blocks"].items()):
            a, tn, r = k.split("|")
            m.append(f"| {a} | {tn} | {r} | {v} |")
    L = ["# 응답 시간 (배포 경로, v3)", "",
         "- 정의: C0 = sec_target + sec_release, C1·C1S = sec_target + sec_extract + sec_release. C0 원 응답 추출은 평가용(sec_measure_extract)으로 합계에서 뺀다.",
         "- 턴 0 포함. 턴 0의 대상 AI·추출 시간은 갈래 간 공유된 1회 실측값이다.",
         "- 백분위 선형 보간(type 7). P99는 표본이 작아 참고용. 95% CI = 질의 환자 단위 부트스트랩(B=2000). 환자 2명 미만이면 CI 없음.",
         "- TTFT는 비스트리밍 호출이라 관측 불가 (값을 만들지 않음). 전체 응답 시간을 TTFT로 쓰지 않는다.", ""]
    if lat["legacy_records"]:
        L += [f"※ v3 정의가 아닌 기록 {lat['legacy_records']}턴은 집계에서 뺐다 (구 정의·턴 0 누락).", ""]
    L += ["| 갈래 | 지표 | 유효 | 누락 | 턴0 | P50 | P90 | P95 | P99(참고) | IQR | P50 CI | P90 CI | P95 CI |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for arm, a in lat["arms"].items():
        for f in ("sec_ttft", "sec_answer", "sec_measure_extract"):
            if f not in a:
                continue
            x = a[f]
            name = {"sec_ttft": "TTFT", "sec_answer": "배포 경로 전체", "sec_measure_extract": "평가용 추출(합계 제외)"}[f]
            L.append(f"| {arm} | {name} | {x['n_valid']} | {x['n_missing']} | {x['turn0_n']} | {_fmt(x['p50'])} | {_fmt(x['p90'])} | {_fmt(x['p95'])} | "
                     f"{_fmt(x['p99'])} | {_fmt(x['iqr'])} | {_fmt(x['ci95']['p50'])} | {_fmt(x['ci95']['p90'])} | {_fmt(x['ci95']['p95'])} |")
        if a.get("ttft_status"):
            L.append(f"| {arm} | TTFT 상태 | {', '.join(a['ttft_status'])} | | | | | | | | | | |")
    T = ["# 출력 토큰 분포 (llm_usage.jsonl)", "", "백분위 선형 보간(type 7). 잘린 호출의 토큰 수는 상한에서 검열된 값이므로 실제 필요 길이가 아니다.", "",
         "| 역할 | 호출 | 평균 | P50 | P90 | P95 | P99 | 최대 | 잘림 | 잘림 비율 | max_tokens | ceil(P99×1.25) |",
         "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for role, t in tok.items():
        T.append(f"| {role} | {t['n']} | {_fmt(t['mean'])} | {_fmt(t['p50'])} | {_fmt(t['p90'])} | {_fmt(t['p95'])} | {_fmt(t['p99'])} | "
                 f"{_fmt(t['max'])} | {t['truncated']} | {_fmt(t['truncated_rate'])} | {_fmt(t['max_tokens'])} | {_fmt(t['p99_x1_25'])} |")
    return {"extraction_summary.md": "\n".join(m) + "\n", "latency_summary.md": "\n".join(L) + "\n", "token_usage_summary.md": "\n".join(T) + "\n"}


def diagnostics(run_dir: Path, summary: dict[str, Any] | None = None) -> dict[str, Any]:
    summary = summary or json.loads((run_dir / "trial요약.json").read_text(encoding="utf-8"))
    turns = _jsonl(run_dir / "턴기록.jsonl")
    patient_of = {t["trial_id"]: t.get("query_patient") for t in summary["trials"]}
    return dict(extraction=extraction_tables(turns, summary), latency=latency_table(turns, patient_of),
                tokens=token_table(_jsonl(run_dir / "llm_usage.jsonl")))


def write_diagnostics(run_dir: Path, out_dir: Path, summary: dict[str, Any] | None = None) -> dict[str, Any]:
    d = diagnostics(run_dir, summary)
    (out_dir / "diagnostics.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    for name, text in diagnostics_markdown(d).items():
        (out_dir / name).write_text(text, encoding="utf-8")
    return d
