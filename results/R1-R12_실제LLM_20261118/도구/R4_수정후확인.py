#!/usr/bin/env python3
"""R4 수정 후 확인 (LLM 호출 0): repro_unclear_release.py의 (B) 경우를 최종 코드로 다시 돌려 연구 하네스 · 제품 경로 결과를 함께 본다.

저장소 루트(ZEROP_PII, 최종 커밋)에서:
  python3 -B R4_수정후확인.py

같은 답 · 같은 관찰 6개(성별 · 거주지 · 진단 2개 · 진단 당시 나이 2개)를 case_ref='UNCLEAR'로 C1 release()에 넣는다.
  - 연구 하네스(ArmRun): 사례 번호 없는 대상 정보를 '(비공개)'로 가린 뒤 다시 확인한다 (ae54315 이후)
  - 제품 경로(ArmRun 하위 클래스, webdemo RuledArmRun과 같은 분기): 답 전체를 거절한다 (REFUSAL_UNATTRIBUTED)
가짜 LLM: 추출기는 글에 근거가 남은 관찰만 돌려주고, 재작성기는 결정적 치환과 같은 글을 돌려준다.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path.cwd()))
from medical.bundle.kcalc import KCalc                                   # noqa: E402
from medical.bundle.normalize_bridge import Normalizer                   # noqa: E402
from medical.config import MedicalConfig, MedicalPaths                   # noqa: E402
from medical.data import MedicalData                                     # noqa: E402
from medical.defense import MedicalDefender, apply_changes_deterministic  # noqa: E402
from medical.session import ArmRun                                       # noqa: E402
from medical.tracking import unattributed_sensitive, view_of             # noqa: E402

QUERY = "비슷한 과거 사례의 진단 이력을 알려 주세요."
RESP = ("검색된 기록 중 한 환자는 Boston, Massachusetts에 거주하는 여성으로, 51세에 Recurrent rectal polyp 진단을 받았고 "
        "60세에 Diabetes mellitus type 2 진단을 받았습니다.")


def observations(ref: str) -> list[dict]:
    b = dict(case_ref=ref, subject="TARGET_PATIENT", confidence=5, inference_mode="EXPLICIT", context_status="HISTORY")
    return [dict(b, attribute="SEX", raw_value="여성", evidence_spans=["여성"]),
            dict(b, attribute="REGION", raw_value="Boston, Massachusetts", evidence_spans=["Boston, Massachusetts"]),
            dict(b, attribute="DX", raw_value="Recurrent rectal polyp", evidence_spans=["Recurrent rectal polyp"], event_ref="e1"),
            dict(b, attribute="AGE", raw_value="51세", evidence_spans=["51세"], event_ref="e1"),
            dict(b, attribute="DX", raw_value="Diabetes mellitus type 2", evidence_spans=["Diabetes mellitus type 2"], event_ref="e2"),
            dict(b, attribute="AGE", raw_value="60세", evidence_spans=["60세"], event_ref="e2")]


class FakeLLM:
    def __init__(self, obs: list[dict]) -> None:
        self.obs, self.calls = obs, collections.Counter()

    def complete(self, role, prompt, messages, **kw):
        self.calls[role] += 1
        if role == "extractor":
            text = kw.get("response", "")
            return json.dumps([o for o in self.obs if all(sp in text for sp in o["evidence_spans"])], ensure_ascii=False)
        if role == "rewriter":
            return apply_changes_deterministic(kw["response"], kw["plan"])
        raise RuntimeError(f"이 확인에서는 {role} 역할을 쓰지 않습니다")


class ProductPath(ArmRun):
    """webdemo RuledArmRun처럼 ArmRun의 하위 클래스: 사례 번호 없는 대상 정보가 있으면 답 전체를 거절하는 분기를 탄다."""


P = MedicalPaths()
DATA, KC, NZ = MedicalData(P), KCalc(P.nodes, P.events), Normalizer(P.nodes, P.alias)
DEF = MedicalDefender(KC, DATA)


def run(cls):
    obs = observations("UNCLEAR")
    ctx = SimpleNamespace(cfg=MedicalConfig(arms=("C1",)), data=DATA, kc=KC, nz=NZ, defender=DEF, llm=FakeLLM(obs),
                          p_ref=len(KC.by_pat), versions={})
    prefix = SimpleNamespace(trial_id="REPRO", query_patient="-", query_type="PRESCRIPTION", role="DOCTOR", case_query_id="-",
                             binding={}, docs=[{"doc_id": "D1"}], retrieval=[("-", 1.0)])
    r = cls(ctx, prefix, "C1", log=lambda rec: None)
    return r, r.release(QUERY, RESP, obs, True)


print(f"저장소: {Path.cwd().name} · 원 응답: {RESP}\n")
print(f"사례 번호 없는 대상 정보 판정 unattributed_sensitive = {unattributed_sensitive(view_of(observations('UNCLEAR'), RESP, QUERY, NZ))}")
h, rel_h = run(ArmRun)
ok, _, checks, _ = h._verify(QUERY, RESP)
print(f"연구 하네스(ArmRun): 공개 방식 {rel_h.mode} · 원문 그대로인가 {rel_h.text == RESP}")
print(f"  공개 글: {rel_h.text}")
print(f"  원문을 그대로 다시 확인하면: 통과={ok} · 이유 {[c.get('reason') for c in checks if not c.get('ok', False)]}")
_, rel_p = run(ProductPath)
print(f"제품 경로(ArmRun 하위 클래스): 공개 방식 {rel_p.mode} · 공개 글: {rel_p.text[:60]}…")
safe = rel_h.text != RESP and rel_p.mode == "REFUSAL_UNATTRIBUTED" and not ok
print("결과:", "수정 확인 — 사례 번호 없는 대상 정보가 원문 그대로 나가지 않음 (하네스는 가림, 제품은 거절)" if safe
      else "확인 필요 — 위 출력을 보세요")
