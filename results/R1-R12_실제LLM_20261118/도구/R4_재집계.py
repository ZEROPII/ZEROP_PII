#!/usr/bin/env python3
"""R4 재집계 (LLM 호출 0): 기존 실행 기록의 턴마다 원 응답 관찰을 지금 코드로 다시 보고, 수정된 두 규칙이 걸리는지 센다.

저장소 루트(ZEROP_PII, 최종 커밋)에서:
  python3 -B R4_재집계.py <실행 폴더> [...] [--out 결과.md]

다시 보는 것: medical.session.ArmRun.release()가 맨 앞에서 하는 것과 같은
  raw_view = view_of(원 응답 관찰, 원 응답, 질문, 정규화 v2)  (기록의 raw_observations · raw_response_text · query_text)
  - UNCLEAR 규칙 (302e51e · 4629f50): unattributed_sensitive(raw_view)
      사례 번호 없는(UNCLEAR) 관찰 중 사례에 귀속하면 MAPPED가 될 질의 외 정보가 있으면 걸림. subject=OTHER · 일반 권고는 안 걸림
  - 귀속 미매핑 규칙 (a6b8516): unmapped_attributed(raw_view)
      사례에 귀속됐지만 정규화가 UNMAPPED인 질의 외 관찰이 있으면 걸림 (가이드의 'k 밖 공개 570건'은 대부분 이쪽)
  걸리면 제품(webdemo)은 답 전체를 거절하고, 연구 하네스(ArmRun)는 그 값만 '(비공개)'로 가린 뒤 다시 확인한다.
수정 전 코드(기록 당시)에는 두 규칙이 없었으므로, '걸리는 턴 중 원래 공개된 턴'이 수정으로 달라지는 턴이다.
기록 파일과 저장소 파일은 읽기만 한다.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from medical.config import MedicalConfig, MedicalPaths                          # noqa: E402
from medical.normalize_ext import VERSION as NORM_VERSION, make_normalizer      # noqa: E402
from medical.tracking import (UNCLEAR, case_ref_of, is_marker_only, unattributed_sensitive, unmapped_attributed,  # noqa: E402
                              view_of)

RELEASED = {"RAW", "REWRITTEN", "REWRITTEN_FALLBACK", "REWRITTEN_PATCHED"}
STR_KEYS = {"attribute", "raw_value", "case_ref", "subject", "time_role", "inference_mode", "context_status", "event_ref"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    nz = make_normalizer(MedicalPaths(), "v2", min_confidence=MedicalConfig.min_confidence)
    L = ["# R4 재집계: 수정된 공개 규칙을 기존 기록에 다시 적용 (LLM 호출 0)", "",
         f"정규화 v2 (normalize_ext {NORM_VERSION}) · 저장소 {Path.cwd().name}", "",
         "| 기록 | 갈래 | 턴 | 원래 공개된 턴 (그중 RAW) | UNCLEAR 관찰 (과거 사례 쪽) · 있는 턴 | UNCLEAR 규칙이 걸리는 턴 · 그중 원래 공개 · 그중 RAW | 귀속 미매핑 규칙이 걸리는 턴 · 그중 원래 공개 · 그중 RAW | 귀속 미매핑 관찰 (원래 공개된 턴의 것) | 둘 중 하나라도: 원래 공개 · 그중 RAW |",
         "|---|---|---|---|---|---|---|---|---|"]
    detail, fails = [], []
    for run in a.runs:
        run = Path(run).expanduser()
        agg: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        for line in (run / "턴기록.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("turn") is None:
                continue
            arm, mode = r.get("arm"), r.get("release_mode")
            obs = [o for o in (r.get("raw_observations") or []) if isinstance(o, dict)]
            raw, q = r.get("raw_response_text") or "", r.get("query_text") or ""
            c = agg[arm]
            c["turns"] += 1
            rel = mode in RELEASED
            c["released"] += rel
            c["raw"] += mode == "RAW"
            unc = [o for o in obs if case_ref_of(o) == UNCLEAR]
            c["unclear"] += len(unc)
            c["unclear_past"] += sum(o.get("subject") != "OTHER" for o in unc)
            c["unclear_turns"] += bool(unc)
            if not obs:
                continue
            # 옛 기록(하네스 v0.1)은 한 칸에 목록이 든 관찰이 있다 (예: time_role=['…']). 첫 값으로 맞춰 다시 본다
            obs = [{k: (next((x for x in val if isinstance(x, str)), None) if isinstance(val, list) and k in STR_KEYS else val)
                    for k, val in o.items()} for o in obs]
            try:
                v = view_of(obs, raw, q, nz)
            except Exception as exc:          # 다시 보지 못한 턴은 따로 센다
                c["replay_failed"] += 1
                c[f"fail:{type(exc).__name__}"] += 1
                continue
            u, m = unattributed_sensitive(v), unmapped_attributed(v)
            n_unm = sum(1 for ref, os_ in v.normalized.items() if ref != UNCLEAR for o in os_
                        if o.get("mapping_status") == "UNMAPPED" and o.get("subject") != "OTHER" and not is_marker_only(o.get("raw_value")))
            c["unm_obs"] += n_unm
            c["unm_obs_rel"] += n_unm if rel else 0
            for key, hit in (("u", u), ("m", m), ("any", u or m)):
                c[f"{key}_turns"] += hit
                c[f"{key}_rel"] += hit and rel
                c[f"{key}_raw"] += hit and mode == "RAW"
            if u:
                detail.append(f"| {run.name} | {r.get('trial_id')} | {arm} | {r.get('turn')} | {mode} | "
                              f"{', '.join(sorted({str(o.get('attribute')) for o in unc}))} |")
        for arm, c in sorted(agg.items()):
            L.append(f"| {run.name} | {arm} | {c['turns']} | {c['released']} ({c['raw']}) | {c['unclear']} ({c['unclear_past']}) · {c['unclear_turns']} | "
                     f"{c['u_turns']} · {c['u_rel']} · {c['u_raw']} | {c['m_turns']} · {c['m_rel']} · {c['m_raw']} | {c['unm_obs']} ({c['unm_obs_rel']}) | {c['any_rel']} · {c['any_raw']} |")
            if c["replay_failed"]:
                fails.append(f"{run.name} {arm}: 다시 보지 못한 턴 {c['replay_failed']}개 "
                             + ", ".join(f"{k[5:]} {n}" for k, n in c.items() if k.startswith("fail:")))
    if fails:
        L += ["", "다시 보지 못한 턴: " + " · ".join(fails)]
    L += ["", "## UNCLEAR 규칙이 걸리는 턴", "",
          "| 기록 | trial | 갈래 | 턴 | 원래 공개 방식 | UNCLEAR 속성 |", "|---|---|---|---|---|---|", *(detail or ["| (없음) | | | | | |"]), "",
          "- C0는 방어가 없는 갈래라 규칙이 걸려도 공개 방식은 그대로다(참고로만 센다). 바뀌는 것은 C1 · C1S다.",
          "- '원래 공개'는 RAW · REWRITTEN · REWRITTEN_FALLBACK · REWRITTEN_PATCHED. 걸리는 원래 공개 턴은 제품에서는 거절로,",
          "  연구 하네스에서는 그 값만 가린 공개(다시 확인 통과 시) 또는 거절로 바뀐다.",
          "- 기록 당시 코드와 지금 코드는 정규화기도 다르다(지금이 더 많이 읽는다). 그래서 같은 관찰도 지금은 MAPPED일 수 있다."]
    text = "\n".join(L) + "\n"
    print(text)
    if a.out:
        Path(a.out).expanduser().write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
