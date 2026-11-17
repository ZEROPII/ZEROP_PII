#!/usr/bin/env python3
"""R3 재현 (LLM 호출 0): 11-05 응답 시간 측정 T0002 턴 0에서 재작성이 두 번 실패해 값 치환으로 간 경우를 다시 만든다.

저장소 루트(ZEROP_PII)에서:
  python3 -B R3_재현_T0002.py ~/KISIA_pj/ZEROP_PII/runs/latency/20261105_213049_real [--out 결과.md]

입력: 그 실행의 턴기록.jsonl에서 T0002 턴 0 (턴 0의 대상 AI 답 · 추출기 출력은 갈래가 함께 쓰므로 C0 기록에 남아 있다).
      그 턴의 C1은 값 치환에서 답이 수천만 자로 불어나 다시 확인 추출이 HTTP 400(prompt is too long)으로 끝났다.
방법: 재작성기가 두 번 실패했다고 보고, 사례에 귀속된 값을 모두 바꾸는 계획으로 값 치환만 돌린다.
  - 예전 동작: 631f4dc 이전 medical/defense.py를 그대로 옮긴 것. 근거가 글자열이면 list()로 글자 단위로 쪼개고,
    길이 제한 없이 바꾼다. 같은 값이 두 사례에 나오면 앞에서 이미 바뀐 값은 답에 없으므로 근거(글자 하나씩)로 간다.
  - 지금 동작: 저장소의 medical.defense(normalize_spans · MIN_SPAN_CHARS · 길이 상한)와
    제품 경로의 근거 정리(webdemo.backend.textguard.clean_spans)를 그대로 쓴다.
  계획 두 가지: (A) 모두 가림, (B) 약은 성분 이름으로 넓히고 나머지는 가림 (11-05 기록의 '약 이름으로 바뀜'과 같은 꼴).
저장소 파일은 읽기만 한다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from medical.defense import MIN_SPAN_CHARS, SUPPRESSED_MARK, apply_changes_deterministic, normalize_spans  # noqa: E402

try:
    from webdemo.backend.textguard import clean_spans                                                       # noqa: E402
except Exception:                       # 제품 코드가 없는 저장소에서도 연구 경로만으로 돌게
    clean_spans = None

STOP = 2_000_000                        # 예전 동작이 이 길이를 넘으면 폭주로 보고 멈춘다 (11-05에는 2,481만 자까지 커졌다)


def old_apply(response: str, changes: list[dict]) -> tuple[str, bool]:
    """631f4dc 이전 apply_changes_deterministic (멈춤 장치만 더함)."""
    out = response
    for c in sorted(changes, key=lambda c: -len(c["raw_value"])):
        rep = c["to_label"] if c["action"] == "generalize" else SUPPRESSED_MARK
        if c["raw_value"] and c["raw_value"] in out:
            out = out.replace(c["raw_value"], rep)
            continue
        for sp in sorted(c["evidence_spans"], key=len, reverse=True):
            if sp and sp in out:
                out = out.replace(sp, rep)
                if len(out) > STOP:
                    return out, True
    return re.sub(r"(\(비공개\)[\s,]*){2,}", SUPPRESSED_MARK + " ", out), False


def plan(obs: list[dict], mode: str) -> list[dict]:
    out = []
    for o in obs:
        if not re.fullmatch(r"사례\d+", str(o.get("case_ref") or "")) or o.get("subject") == "OTHER":
            continue
        raw = str(o.get("raw_value") or "")
        gen = mode == "B" and o.get("attribute") == "MED" and raw
        out.append(dict(case_ref=o["case_ref"], attribute=o.get("attribute"), raw_value=raw, ev=o.get("evidence_spans"),
                        action="generalize" if gen else "suppress", to_label=raw.split()[0] if gen else None))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--trial", default="T0002")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    rec = None
    for line in (Path(a.run_dir).expanduser() / "턴기록.jsonl").read_text(encoding="utf-8").splitlines():
        t = json.loads(line) if line.strip() else {}
        if t.get("trial_id") == a.trial and t.get("turn") == 0 and t.get("raw_observations"):
            rec = t
            break
    if rec is None:
        sys.exit(f"{a.trial} 턴 0 기록이 없습니다")
    raw, obs = rec["raw_response_text"], rec["raw_observations"]
    n_str = sum(isinstance(o.get("evidence_spans"), str) for o in obs)
    L = [f"# R3 재현: {a.trial} 턴 0 값 치환 (LLM 호출 0)", "",
         f"- 기록: `{Path(a.run_dir).name}/턴기록.jsonl` · 대상 AI 답 {len(raw):,}자 · 추출 관찰 {len(obs)}개 (근거가 글자열 하나인 것 {n_str}개)",
         f"- 지금 코드 MIN_SPAN_CHARS = {MIN_SPAN_CHARS} (이 글자 수보다 짧은 근거는 값 치환에 쓰지 않음)", "",
         "| 계획 | 바꿀 항목 | 예전 동작 결과 | 지금 동작 결과 (연구 경로) | 지금 동작 결과 (제품 경로) | 지금 결과에 남은 원래 값 |",
         "|---|---|---|---|---|---|"]
    samples = {}
    for mode, name in (("A", "(A) 모두 가림"), ("B", "(B) 약은 성분 이름으로 넓힘")):
        p = plan(obs, mode)
        old_changes = [dict(c, evidence_spans=list(c["ev"] or [])) for c in p]            # 예전 change_lines: list(글자열)
        new_changes = [dict(c, evidence_spans=normalize_spans(c["ev"])) for c in p]        # 지금 연구 경로
        old, stopped = old_apply(raw, old_changes)
        try:
            new = apply_changes_deterministic(raw, new_changes)
            new_txt = f"{len(new):,}자 (원문의 {len(new) / len(raw):.2f}배)"
        except ValueError as exc:
            new, new_txt = "", f"실패 처리 ({exc})"
        if clean_spans is not None:
            prod_changes = [dict(c, evidence_spans=clean_spans(c["ev"])) for c in p]       # 지금 제품 경로 (review.RuleDefender.change_lines)
            try:
                prod = apply_changes_deterministic(raw, prod_changes)
                prod_txt = f"{len(prod):,}자" + (" (연구 경로와 같음)" if prod == new else "")
            except ValueError as exc:
                prod_txt = f"실패 처리 ({exc})"
        else:
            prod_txt = "제품 코드 없음"
        left = sorted({c["raw_value"] for c in p if c["action"] == "suppress" and c["raw_value"] and c["raw_value"] in new})
        old_txt = (f"**{STOP:,}자를 넘어 멈춤 (폭주)**" if stopped else f"{len(old):,}자 (원문의 {len(old) / len(raw):.1f}배)")
        L.append(f"| {name} | {len(p)} | {old_txt} | {new_txt} | {prod_txt} | {len(left)}개 |")
        samples[mode] = (old[:220], new[:600])
    L += ["", "## 앞부분 비교 (A)", "", "예전 동작:", "", "```", samples["A"][0], "```", "", "지금 동작:", "", "```", samples["A"][1], "```", "",
          "- 예전 동작이 커지는 까닭: 같은 값이 여러 사례에 나오면 앞의 치환으로 그 값이 답에서 사라지고, 다음 항목은 근거로 간다.",
          "  근거가 글자열이면 글자 하나씩 바뀌고, '(비공개)' 표시 안의 글자까지 다시 바뀌면서 길이가 계속 늘어난다.",
          "- 지금 동작: 글자열 근거는 한 덩어리로 다루고(normalize_spans · clean_spans), 세 글자보다 짧은 근거는 쓰지 않으며,",
          "  결과가 원문의 20배 + 2,000자를 넘으면 그 시도를 실패로 처리한다(거절 문장으로 감)."]
    text = "\n".join(L) + "\n"
    print(text)
    if a.out:
        Path(a.out).expanduser().write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
