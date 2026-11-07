# 추출 결과 해석과 사례 추적 (하네스 명세 §7, 추출·정규화 명세 v0.3 §4)
#
# 한 답변에 과거 환자 사례가 여러 명(사례1~사례5) 나온다. Observation을 case_ref별로 나눠
#   사례마다 정규화(normalize_bridge) → 공개 목록(to_disclosures) → 그 사례의 누적 목록 → kcalc k
# event_ref는 사례 안에서만 의미가 있으므로 '{case_ref}:{event_ref}'로 이름을 바꿔 사례끼리 섞이지 않게 한다.
# 추출기는 과거 답변을 다시 읽지 않는 대신, 하네스가 넘겨주는 '지금까지의 사례 목록'(사례 표기·사건 표지·사건 표현)을
# 보고 같은 사례·같은 사건이면 같은 이름을 재사용한다. 이 목록은 앞선 commit에서 만든 것이며 정답이 아니다.

from __future__ import annotations

import collections
import json
import re
from dataclasses import dataclass, field
from typing import Any

from medical.bundle.normalize_bridge import Normalizer, to_disclosures

EV_WORD = {"DX": "진단", "PROC": "시술", "MED": "처방", "PLAN": "관리 계획"}
UNCLEAR = "UNCLEAR"


def parse_json(text: str, kind: str) -> Any:
    """LLM 출력에서 JSON 배열(kind='array', 원소는 모두 객체) 또는 객체('object')를 찾는다. 없으면 None."""
    want = list if kind == "array" else dict
    try:
        v = json.loads(text)
        if isinstance(v, want) and (kind == "object" or all(isinstance(x, dict) for x in v)):
            return v
    except Exception:
        pass
    dec = json.JSONDecoder()
    opener = "[" if kind == "array" else "{"
    for i, ch in enumerate(text):
        if ch == opener:
            try:
                v, _ = dec.raw_decode(text[i:])
            except Exception:
                continue
            if isinstance(v, want) and (kind == "object" or not v or all(isinstance(x, dict) for x in v)):
                return v
    return None


@dataclass
class Case:
    """사례 하나(과거 환자 한 명)의 Runtime 상태. committed는 공개된 답변에서 나온 값만 쌓이고 지워지지 않는다."""
    ref: str
    committed: list[dict[str, Any]] = field(default_factory=list)
    events: dict[str, str] = field(default_factory=dict)       # 사건 묶음 표지 → 공개된 사건 표현 ('Diabetes mellitus type 2 진단')
    k_hist: list[int] = field(default_factory=list)

    def describe(self) -> dict[str, Any]:
        return {"case_ref": self.ref, "events": dict(self.events)}


@dataclass
class CaseView:
    """한 답변을 사례별로 정규화한 결과 (아직 State에 넣기 전)."""
    normalized: dict[str, list[dict[str, Any]]]        # case_ref → 정규화된 Observation (UNCLEAR 포함)
    disclosures: dict[str, list[dict[str, Any]]]       # case_ref → kcalc 입력 (event_group 이름 바꿈, UNCLEAR 제외)
    sources: dict[str, list[dict[str, Any]]]           # case_ref → disclosures와 같은 순서의 원 Observation
    partial: dict[str, bool]
    order: list[str]                                   # 답변에서 처음 언급된 순서

    @property
    def case_refs(self) -> list[str]:
        return [r for r in self.order if r != UNCLEAR]


def known_cases_json(cases: dict[str, Case], order: list[str]) -> str:
    return json.dumps([cases[c].describe() for c in order], ensure_ascii=False)


def case_ref_of(o: dict[str, Any]) -> str:
    """'사례 4'·'[사례4]'·'사례4번' → '사례4'. 사례 번호가 없으면 원래 표기 (없으면 UNCLEAR)."""
    raw = str(o.get("case_ref") or "").strip()
    m = re.search(r"사례\s*(\d+)", raw)
    return f"사례{int(m.group(1))}" if m else (raw or UNCLEAR)


def fix_subject(o: dict[str, Any], ref: str, query: str) -> dict[str, Any]:
    """
    case_ref가 '사례N'인데 subject=OTHER로 적힌 관찰 (파일럿 2 턴 0): OTHER는 질문 속 지금 환자에게만 쓰는 값이므로 서로 맞지 않는다.
    값이 질문에 없고 답변에서 나온 것이면 그 사례의 값(TARGET_PATIENT)으로 고친다. 질문에 있는 값이면 그대로 둔다(질의 환자 정보일 수 있음).
    """
    if o.get("subject") == "OTHER" and re.fullmatch(r"사례\d+", ref):
        val = str(o.get("raw_value") or "").strip()
        if val and val not in query:
            return dict(o, subject="TARGET_PATIENT", subject_fixed="OTHER->TARGET_PATIENT")
    return o


def view_of(observations: list[dict[str, Any]], response: str, query: str, nz: Normalizer) -> CaseView:
    by_case: dict[str, list[dict[str, Any]]] = collections.OrderedDict()
    for o in observations:
        ref = case_ref_of(o)
        o = fix_subject(dict(o, case_ref=ref) if ref != UNCLEAR else o, ref, query)
        by_case.setdefault(ref, []).append(o)
    normalized, disclosures, sources, partial = {}, {}, {}, {}
    for ref, os_ in by_case.items():
        norm = [nz.normalize(o, response, query) for o in os_]
        normalized[ref] = norm
        if ref == UNCLEAR:
            continue
        ds, part = to_disclosures(norm)
        committed_obs = [o for o in norm if o["commit"]]
        for d in ds:
            if d["event_group"]:
                d["event_group"] = f"{ref}:{d['event_group']}"
        disclosures[ref], sources[ref], partial[ref] = ds, committed_obs, part
    return CaseView(normalized, disclosures, sources, partial, list(by_case))


def commit_view(view: CaseView, cases: dict[str, Case], order: list[str]) -> None:
    """공개된 답변의 CaseView를 사례 상태에 반영한다 (사례가 처음이면 만든다)."""
    for ref in view.case_refs:
        if ref not in cases:
            cases[ref] = Case(ref)
            order.append(ref)
        c = cases[ref]
        for d, src in zip(view.disclosures[ref], view.sources[ref]):
            g = d["event_group"]
            if g and d["attribute"] in EV_WORD:
                local = g.split(":", 1)[1]
                if local not in c.events:
                    c.events[local] = f"{src['raw_value']} {EV_WORD[d['attribute']]}"
        c.committed += view.disclosures[ref]
