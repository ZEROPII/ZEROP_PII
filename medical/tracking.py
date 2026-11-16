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
    # 1) 출력 전체(코드 울타리 제외)가 그대로 JSON이면 그 값을 쓴다. 빈 배열 '[]'은 여기서만 '관찰 없음'으로 인정한다.
    body = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    try:
        v = json.loads(body)
        if isinstance(v, want) and (kind == "object" or all(isinstance(x, dict) for x in v)):
            return v
    except Exception:
        pass
    # 2) 설명 문장이 섞인 경우에만 본문에서 찾는다. 잘린 출력 안의 빈 배열 '[]'(예: "evidence_spans": [])은
    #    '관찰 없음'이 아니므로 여기서 받지 않는다 (fail-closed: 해석 불가 → 호출 측이 거절 처리).
    dec = json.JSONDecoder()
    opener = "[" if kind == "array" else "{"
    for i, ch in enumerate(text):
        if ch == opener:
            try:
                v, _ = dec.raw_decode(text[i:])
            except Exception:
                continue
            if isinstance(v, want) and v and (kind == "object" or all(isinstance(x, dict) for x in v)):
                return v
    # 3) [수정본] 설명 문장이 붙은 경우라도, 닫힌 코드 울타리 안의 빈 배열(```json [] ```)은 '관찰 없음'으로 받는다.
    #    (개발자 확인: 추출기가 빈 배열 뒤에 설명을 붙여 REFUSAL_EXTRACTION_FAILED가 났다.)
    #    울타리가 닫히지 않았거나 "evidence_spans": [] 같은 본문 속 빈 배열은 여기서도 받지 않는다.
    if kind == "array" and re.search(r"```(?:json)?\s*\[\s*\]\s*```", text):
        return []
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
    unclear_mappable: bool = False                     # UNCLEAR 중 사례에 귀속하면 MAPPED(k 입력)가 될 질의 외 정보가 있는가
    unmapped_sensitive: bool = False                   # 사례에 귀속됐지만 정규화에 실패(UNMAPPED)한 질의 외 관찰이 있는가 (k에 안 들어감)

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


def unattributed_sensitive(view: CaseView) -> bool:
    """[수정본] 사례 번호 없는(UNCLEAR) 관찰 중, 사례에 귀속하면 k 입력(MAPPED)이 될 질의 외 정보가 있으면 True.

    UNCLEAR는 k 계산과 검증에서 빠지므로, 이런 공개는 검사 없이 내보내면 안 된다 (fail-closed).
    subject=OTHER(질의 환자 본인 정보)인 UNCLEAR는 막지 않는다.
    귀속해도 MAPPED가 되지 않는 일반 권고(턴 0 등)는 막지 않는다 (개발자 회신 권고: 과잉 차단 방지).
    """
    return view.unclear_mappable


LIST_SEP = re.compile(r"\s*(?:[,;]|\s\+\s)\s*")          # [실험 v4] 'Gingivitis + Essential hypertension'도 나눈다


def split_list_observation(o: dict[str, Any], response: str) -> list[dict[str, Any]]:
    """[수정본] 쉼표·세미콜론으로 나열된 목록 값을 항목별 관찰로 나눈다 (개발자 확인: 턴 2 진단 목록이 한 값으로 묶여 UNMAPPED).

    항목마다 다시 정규화하므로, 나눈 뒤에도 안 맞는 항목은 unmapped_sensitive로 막힌다.
    나눌 게 없으면 원래 관찰 하나를 그대로 돌려준다.
    """
    raw = str(o.get("raw_value") or "")
    parts = [p.strip() for p in LIST_SEP.split(raw) if p.strip()]
    if len(parts) < 2:
        return [o]
    return [dict(o, raw_value=p, evidence_spans=[p] if p in response else [], split_from=raw) for p in parts]


# [수정본] 단독으로는 뜻이 없는 수식어 조각(예: "Acute pharyngitis, unspecified"의 unspecified, "…, 지속"의 지속).
# 이런 조각은 앞 조각에 다시 붙여, 이름이 쪼개져 차단되지 않게 한다.
MODIFIER_PIECES = {"unspecified", "nos", "other", "지속", "지속적", "초기", "unknown"}


def merge_modifier_pieces(pieces: list[dict[str, Any]], response: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in pieces:
        raw = str(p.get("raw_value") or "")
        if out and raw.lower() in MODIFIER_PIECES:
            prev = out[-1]
            joined = f"{prev.get('raw_value')}, {raw}"
            out[-1] = dict(prev, raw_value=joined, evidence_spans=[joined] if joined in response else [])
        else:
            out.append(p)
    return out


def split_if_unmapped(o: dict[str, Any], response: str, query: str, nz: Normalizer) -> list[dict[str, Any]]:
    """[수정본] 값 전체를 먼저 정규화한다. 전체가 MAPPED(또는 UNMAPPED가 아님)이면 나누지 않는다.
    전체가 UNMAPPED일 때만 나누고, 수식어 조각은 앞 조각에 붙인다.
    """
    raw = str(o.get("raw_value") or "")
    # 값 전체의 정규화 결과는 값 자체를 근거로 본다 (응답 속 문장과 쉼표 표기가 다를 수 있어 응답 검사로 PENDING이 되는 것을 피함)
    whole = nz.normalize(dict(o, evidence_spans=[raw]), raw, query)
    if whole.get("mapping_status") != "UNMAPPED":
        return [o]
    return merge_modifier_pieces(split_list_observation(o, response), response)


SUPPRESSED_MARKER = "(비공개)"
CONNECTOR_WORDS = ("시작", "이후", "부터", "~", "시행", "등")      # [실험 v4] '(비공개) 시행' · '(비공개) 등'


def is_marker_only(raw: Any) -> bool:
    """[수정본] 값이 방어의 숨김 표시와 연결어만으로 이루어졌으면 True (가린 뒤 정보가 남지 않음).

    예: "(비공개) ~ (비공개)", "(비공개) 시작" → True.
    "1(비공개)", "20(비공개)-02-14 ~ 20(비공개)-11-08", "(비공개) 지속" → False (숫자나 글자가 남음).
    """
    s = str(raw or "")
    if SUPPRESSED_MARKER not in s:
        return False
    for w in (SUPPRESSED_MARKER, *CONNECTOR_WORDS):
        s = s.replace(w, "")
    return not any(ch.isalnum() for ch in s)


def is_planned_label(raw: Any, ref: str, allowed_labels: frozenset) -> bool:
    """방어 계획이 이 사례에 고른 넓힌 표현과 같은 값인지. '(비공개)'와 '등 '을 뗀 뒤 정확히 같을 때만 본다."""
    if not raw or not allowed_labels:
        return False
    s = str(raw).replace(SUPPRESSED_MARKER, " ").strip()
    s = re.sub(r"^등\s+", "", re.sub(r"\s+", " ", s)).strip()
    return (ref, s) in allowed_labels


def unmapped_attributed(view: CaseView) -> bool:
    """[수정본] 사례에 귀속됐지만 정규화에 실패(UNMAPPED)한 질의 외 관찰이 있으면 True. 이런 공개는 k에 안 들어가므로 내보내지 않는다.

    subject=OTHER(질의 환자 본인 정보)는 막지 않는다.
    """
    return view.unmapped_sensitive


# [실험 v4] 현재 환자(질의 환자) 설명 괄호. 대상 AI는 "사례2는 현재 환자(1세 남아)와 연령대가 가장 유사한 사례"처럼 쓴다.
#   추출기가 괄호 속 값을 사례2에 붙이면(fix_A8 · v3_A8 T0005 '남아', v3_A8 T0002 '70세', T0004 '42세') 사례의 State가 틀린 값으로 오염된다.
#   근거 문구 속 그 값이 이런 괄호 안에만 있으면 질의 환자 정보(subject=OTHER)로 본다.
#   괄호 뒤 같은 문장에 '같은 · 동일'처럼 사례가 같은 값이라고 하는 말이 있으면 바꾸지 않는다(사례의 값이기도 할 수 있음).
_CURRENT_PATIENT = re.compile(r"(?:현재|지금|질의|문의하신|문의 주신|말씀하신)\s*환자(?:분)?\s*[（(]([^()（）]{1,80})[)）]")
_SAME_AS = re.compile(r"같은|같이|동일|동갑|일치|마찬가지|똑같")


def current_patient_regions(response: str) -> list[tuple[int, int]]:
    out = []
    for m in _CURRENT_PATIENT.finditer(response or ""):
        ends = [i for i in (response.find(c, m.end()) for c in (".", "\n", "。", "!", "?")) if i >= 0]
        if _SAME_AS.search(response[m.end():min(ends) if ends else len(response)]):
            continue
        out.append((m.start(), m.end()))
    return out


def in_current_patient_only(o: dict[str, Any], response: str, regions: list[tuple[int, int]]) -> bool:
    """근거 문구가 답에 나오는 모든 자리에서, 값(값이 문구에 없으면 문구 전체)이 현재 환자 괄호 안에 있으면 True."""
    raw = str(o.get("raw_value") or "").strip()
    spans = o.get("evidence_spans") or []
    spans = [spans] if isinstance(spans, str) else [x for x in spans if isinstance(x, str) and x]
    if not raw or not spans or not regions:
        return False
    for sp in spans:
        pos, seen = 0, False
        while (i := response.find(sp, pos)) >= 0:
            seen, pos = True, i + 1
            offs = [m.start() for m in re.finditer(re.escape(raw), sp)]
            ranges = [(i + j, i + j + len(raw)) for j in offs] or [(i, i + len(sp))]
            if not all(any(a <= x and y <= b for a, b in regions) for x, y in ranges):
                return False
        if not seen:
            return False
    return True


def view_of(observations: list[dict[str, Any]], response: str, query: str, nz: Normalizer,
            allowed_labels: frozenset = frozenset()) -> CaseView:
    """allowed_labels: (사례, 범주어) 쌍. 방어 계획이 고른 넓힌 표현이면 미매핑 차단에서 뺀다 (k는 계획된 노드로 따로 센다)."""
    by_case: dict[str, list[dict[str, Any]]] = collections.OrderedDict()
    regions = current_patient_regions(response)
    for o in observations:
        ref = case_ref_of(o)
        o = fix_subject(dict(o, case_ref=ref) if ref != UNCLEAR else o, ref, query)
        if regions and o.get("subject") != "OTHER" and in_current_patient_only(o, response, regions):
            o = dict(o, subject="OTHER", subject_fixed="CURRENT_PATIENT_PAREN")     # [실험 v4]
        pieces = split_if_unmapped(o, response, query, nz) if ref != UNCLEAR and o.get("subject") != "OTHER" else [o]
        by_case.setdefault(ref, []).extend(pieces)
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
    mappable = any(o.get("subject") != "OTHER" and
                   nz.normalize(dict(o, case_ref="사례0"), response, query).get("mapping_status") == "MAPPED"
                   for o in normalized.get(UNCLEAR, []))
    unmapped = any(o.get("mapping_status") == "UNMAPPED" and o.get("subject") != "OTHER"
                   and not is_marker_only(o.get("raw_value"))
                   and not is_planned_label(o.get("raw_value"), ref, allowed_labels)
                   for ref, os_ in normalized.items() if ref != UNCLEAR for o in os_)
    return CaseView(normalized, disclosures, sources, partial, list(by_case), mappable, unmapped)


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
