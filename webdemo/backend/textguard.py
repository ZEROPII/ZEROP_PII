# 실제 LLM 경로의 글 다루기 보강 (ADR-0029). 연구 모듈(medical/)은 바꾸지 않고, 제품 쪽에서 LLM 출력과 내보낼 글을 다듬는다.
#
#   추출기 출력 바로잡기 (fix_extraction): 실제 LLM 추출기가 낸 JSON 배열을 공개 판정에 넘기기 전에 다듬는다 (live.LiveLLM이 부른다).
#     1) 근거 문장(evidence_spans)이 목록이 아니라 글자열 하나로 오면 목록으로 감싼다. 그대로 두면 공개 계획(change_lines)이
#        글자 하나하나로 쪼개, 값 치환 단계가 답의 모든 'i' · 'l'을 약 이름으로 바꾼다 (2026-11-05 측정: 1,132자 → 2,481만 자,
#        HTTP 400 prompt is too long). Haiku 4.5 추출기는 관측 869건 중 519건을 글자열로 냈다.
#        글자열 근거가 답에 그대로 없으면(조각을 이어 붙인 경우 등) 답에 있는 조각 · 원래 값으로 바꾼다. 하나도 없으면 그대로 두어
#        정규화가 PENDING으로 둔다 (목록으로 온 근거와 같은 대우).
#     2) 사례 문서 대조 보탬: 답에서 '사례N'이 나온 문장(같은 단락의 이어지는 문장, '사례 모두' 같은 전체 문장 포함)에
#        그 사례 문서의 진단 · 시술 · 약(성분 이름 포함) · 관리 계획 · 성별 · 거주 지역 표현이 그대로 있는데 추출기가 그 사례에
#        같은 값을 내지 않았으면 관측을 더한다 (source='DOC_MATCH'). 문서에 있는 참값만 더하므로 공개 판정이 느슨해지지 않는다.
#        사례 3의 약('사례3은 acetaminophen만…')을 추출기가 빠뜨려 판정 · 사례 노트에서 빠진 일 (의료진 체험 2026-11-05)을 막는다.
#        나이 · 날짜는 규칙 추출(medical/rule_extract.py)이 맡으므로 여기서는 더하지 않는다.
#   기간 범위 (coarsen_durations): 내보낼 글의 상대 기간(며칠 · 몇 주 · 몇 달)을 범위로 바꾼다 ('약 12일' → '약 1~2주').
#     후보 수 계산에는 기간 노드가 없으므로, 묻는 범위(사례 하나 · 전체)와 상관없이 늘 같은 범위로만 보인다.
#     절대 날짜(시기)는 지금처럼 후보 수로 판정하고, 기간은 날짜와 따로 범위로 보인다.
#   duration_mentions: 내보낸 글의 기간 범위를 사례마다 찾는다 (사례 노트 '기간' 항목).

from __future__ import annotations

import functools
import json
import math
import re
from typing import Any

from medical.tracking import parse_json

# ── 문장과 사례 귀속 ───────────────────────────────────────────

_CASE = re.compile(r"사례\s*0*(\d{1,2})(?![\d\-./])")
_UNITS_AFTER = r"(?!\s*(?:회|번|세|살|년|월|일|주|개월|명|건|%|MG|mg|ML|ml|정|캡슐|\.\d|\d))"
_LIST_TAIL = re.compile(r"\s*(?:,|、|와|과|및|·|그리고)\s*(?:사례\s*)?0*(\d{1,2})(?![\d\-./])" + _UNITS_AFTER)
_ALL = re.compile(r"(?:모든|전체|각)\s*사례|사례\s*(?:전체|모두|전부)|\d+\s*(?:개|건)\s*(?:의\s*)?사례\s*(?:모두|전부)|사례들")
_NOT_CASE = re.compile(r"현재\s*환자|이\s*환자|제\s*환자|질의\s*환자|환자분|진료\s*중인\s*환자")
_END = re.compile(r"(?:(?<!\d)\.(?!\d)|[!?。])+[\"'”’)\]]*\s*|\n+")
_PARA = re.compile(r"\n\s*\n")


def sentences(text: str) -> list[tuple[int, int, int]]:
    """(시작, 끝, 단락 번호). 소수점 · 용량의 점에서는 끊지 않는다."""
    paras, out = [], []
    start = 0
    for m in _PARA.finditer(text):
        paras.append((start, m.start()))
        start = m.end()
    paras.append((start, len(text)))
    for pi, (a, b) in enumerate(paras):
        pos = a
        for m in _END.finditer(text, a, b):
            if text[pos:m.end()].strip():
                out.append((pos, m.end(), pi))
            pos = m.end()
        if text[pos:b].strip():
            out.append((pos, b, pi))
    return out


def case_numbers(sentence: str) -> list[int]:
    """문장에 나온 사례 번호 ('사례4와 사례5', '사례 1, 2, 4' 나열 포함)."""
    nums: list[int] = []
    for m in _CASE.finditer(sentence):
        nums.append(int(m.group(1)))
        pos = m.end()
        while (t := _LIST_TAIL.match(sentence, pos)):
            nums.append(int(t.group(1)))
            pos = t.end()
    return list(dict.fromkeys(nums))


def attribute_sentences(text: str, n_cases: int) -> list[tuple[int, int, list[int], bool]]:
    """
    문장마다 (시작, 끝, 사례 번호들, 이 문장에 사례 표기가 직접 있는지).
    표기가 없는 문장은 같은 단락에서 바로 앞에 나온 사례 하나를 잇는다 (현재 환자를 말하는 문장은 잇지 않는다).
    '사례 모두 · 모든 사례 · 사례들' 문장은 모든 사례.
    """
    out = []
    last: tuple[int, list[int]] | None = None            # (단락, 사례들)
    for a, b, pi in sentences(text):
        s = text[a:b]
        nums = [n for n in case_numbers(s) if 1 <= n <= n_cases]
        if nums:
            out.append((a, b, nums, True))
            last = (pi, nums)
        elif _ALL.search(s):
            out.append((a, b, list(range(1, n_cases + 1)), False))
        elif last is not None and last[0] == pi and len(last[1]) == 1 and not _NOT_CASE.search(s):
            out.append((a, b, last[1], False))
        else:
            out.append((a, b, [], False))
    return out


# ── 추출기 출력 바로잡기 ───────────────────────────────────────

def clean_spans(spans: Any) -> list[str]:
    """근거 문장을 글자열 목록으로 (글자열 하나면 목록 하나로). 두 글자보다 짧은 조각은 버린다."""
    parts = [spans] if isinstance(spans, str) else list(spans or []) if isinstance(spans, (list, tuple)) else []
    return [s for s in (str(x).strip() for x in parts if isinstance(x, (str, int, float))) if len(s) >= 2]


def fix_spans(ob: dict[str, Any], response: str | None) -> list[str]:
    parts = clean_spans(ob.get("evidence_spans"))
    if response is None:
        return parts
    ok = [p for p in parts if p in response]
    if len(ok) < len(parts):
        for p in parts:
            if p in response:
                continue
            ok += [q for q in (x.strip() for x in re.split(r"[,，;]\s*", p)) if len(q) >= 2 and q in response and q not in ok]
    if not ok:
        raw = str(ob.get("raw_value") or "").strip()
        if raw and raw in response:
            ok = [raw]
    return ok or parts


_TERM_ATTRS = ("DX", "PROC", "MED", "PLAN", "SEX", "REGION")
_SEX_WORDS = {"SEX_MALE": ("남성", "남자"), "SEX_FEMALE": ("여성", "여자")}


_TERMS: dict[tuple[str, str, int], list[tuple[str, str]]] = {}


def doc_terms(doc: dict[str, Any], data: Any = None) -> list[tuple[str, str]]:
    """사례 문서에서 답에 그대로 나올 수 있는 표현 (단서 종류, 표현). 긴 것부터. 문서마다 한 번 만들어 둔다."""
    key = (str(doc.get("doc_id")), str(doc.get("text_sha256") or len(doc.get("text") or "")), id(data))
    cached = _TERMS.get(key)
    if cached is not None:
        return cached
    out: list[tuple[str, str]] = []

    def add(att: str, term: str | None) -> None:
        t = (term or "").strip().rstrip(".")
        if not t or (att not in ("SEX",) and len(t) < 4) or (att, t.lower()) in {(a, x.lower()) for a, x in out}:
            return
        out.append((att, t))

    for r in doc.get("fact_rows") or []:
        att, span, node = r.get("attribute"), r.get("span_text"), r.get("node_id")
        if att not in _TERM_ATTRS:
            continue
        if att == "SEX":
            for w in _SEX_WORDS.get(node or "", ()):
                add(att, w)
            continue
        add(att, span)
        if att == "REGION" and span and "," in span:
            add(att, span.split(",")[0])                 # 'Attleboro, Massachusetts' → 'Attleboro' (주 이름만은 더하지 않는다)
        if data is not None and node in getattr(data, "N", {}):
            for a in data.anc(node)[1:]:
                if att == "MED" and a.startswith("MED_IN_"):
                    add(att, data.label(a))              # 성분 이름: 'acetaminophen 325 MG Oral Tablet' → 'acetaminophen'
                if att == "DX" and a.startswith("DX_ICD_CODE_") and len(data.N[a].get("standard_code") or "") == 3:
                    add(att, data.label(a))              # ICD 세 자리 범주 이름
    out.sort(key=lambda x: -len(x[1]))
    if len(_TERMS) > 5000:
        _TERMS.clear()
    _TERMS[key] = out
    return out


@functools.lru_cache(maxsize=20000)
def _term_rx(term: str) -> re.Pattern[str]:
    body = re.escape(term)
    if term[:1].isascii() and term[:1].isalnum():
        body = r"(?<![A-Za-z0-9])" + body
    if term[-1:].isascii() and term[-1:].isalnum():
        body += r"(?![A-Za-z0-9])"
    return re.compile(body, re.I)


def _known(found: list[dict[str, Any]], ref: str, att: str, value: str) -> bool:
    v = value.lower()
    for o in found:
        m = _CASE.search(str(o.get("case_ref") or ""))
        if not m or f"사례{int(m.group(1))}" != ref or o.get("attribute") != att:
            continue
        raw = str(o.get("raw_value") or "").lower()
        if raw and (v in raw or raw in v):
            return True
    return False


def grounded_observations(response: str, docs: list[dict[str, Any]], found: list[dict[str, Any]], data: Any = None) -> list[dict[str, Any]]:
    """사례 문서 대조 보탬 (위 설명 2). found는 추출기가 낸 관측 (이미 있는 값은 더하지 않는다)."""
    out: list[dict[str, Any]] = []
    have = list(found)
    for a, b, nums, explicit in attribute_sentences(response, len(docs)):
        if not nums:
            continue
        sent = response[a:b]
        for n in nums:
            ref = f"사례{n}"
            taken: list[tuple[int, int]] = []
            for att, term in doc_terms(docs[n - 1], data):
                if att == "SEX" and not (explicit and len(nums) == 1):
                    continue                             # 성별은 그 사례만 가리키는 문장에서만
                m = _term_rx(term).search(sent)
                if m is None or any(x < m.end() and m.start() < y for x, y in taken):
                    continue
                taken.append((m.start(), m.end()))
                value = m.group(0)
                if _known(have, ref, att, value):
                    continue
                ob = dict(attribute=att, raw_value=value, evidence_spans=[value], inference_mode="EXPLICIT", confidence=5,
                          case_ref=ref, subject="TARGET_PATIENT", context_status="UNSPECIFIED", source="DOC_MATCH")
                if att == "MED":
                    ob["med_assertion"] = "PRESCRIBED"
                out.append(ob)
                have.append(ob)
    return out


def fix_extraction(output: str, response: str | None, docs: list[dict[str, Any]] | None, data: Any = None) -> str:
    """추출기 출력(JSON 배열 글)을 바로잡아 다시 글로. 배열을 찾지 못하면 그대로 돌려준다 (연구 모듈이 다시 추출한다)."""
    obs = parse_json(output, "array")
    if obs is None:
        return output
    fixed = []
    for item in obs:
        o = dict(item)
        if "evidence_spans" in o or isinstance(o.get("raw_value"), str):
            o["evidence_spans"] = fix_spans(o, response)
        fixed.append(o)
    if response and docs:
        fixed += grounded_observations(response, docs, fixed, data)
    return json.dumps(fixed, ensure_ascii=False)


# ── 기간 범위 ─────────────────────────────────────────────────

#: (이 일수까지, 보이는 범위, 범위인지). 범위면 '약'을 붙일 수 있다.
BUCKETS: list[tuple[float, str, bool]] = [
    (3, "3일 이내", False), (7, "1주 이내", False), (14, "1~2주", True), (31, "2~4주", True), (92, "1~3개월", True),
    (183, "3~6개월", True), (330, "6개월~1년", True), (548, "약 1년", False), (1095, "1~3년", True), (math.inf, "3년 넘게", False),
]
_DAYS = {"일": 1.0, "주": 7.0, "주일": 7.0, "개월": 30.4, "달": 30.4, "년": 365.0}
_WORDS = {"하루": 1, "이틀": 2, "사흘": 3, "나흘": 4, "일주일": 7, "보름": 15, "한 달": 30, "한달": 30, "두 달": 61, "두달": 61,
          "석 달": 91, "석달": 91, "반년": 182}
_AFTER = r"(?!\s*(?:\d|회|번|차|째|마다|간격|분|시간|세|살|에\s*(?:한|두|세|네|\d)))"
_DUR = re.compile(
    r"(?<![\d.\-/:~∼])(?:(약|대략|거의|총)\s*)?"
    r"(?:(\d{1,2})\s*년\s*(\d{1,2})\s*개월|(\d{1,3})(?:\s*[~∼\-–]\s*(\d{1,3}))?\s*(주일|개월|일|주|달|년)"
    r"|(하루|이틀|사흘|나흘|일주일|보름|한\s?달|두\s?달|석\s?달|반년))" + _AFTER)


_TAIL = re.compile(r"\s*(동안|간|전)(?=[의에은는을이가도]?(?:\s|$|[,.)])|부터|까지)")


def bucket(days: float) -> tuple[str, bool]:
    for top, label, ranged in BUCKETS:
        if days <= top:
            return label, ranged
    return BUCKETS[-1][1], BUCKETS[-1][2]


def _days_of(m: re.Match[str]) -> float | None:
    if m.group(2):
        return int(m.group(2)) * 365.0 + int(m.group(3)) * 30.4
    if m.group(7):
        w = m.group(7)
        return float(_WORDS.get(w) or _WORDS.get(w.replace(" ", "")) or 0) or None
    lo = int(m.group(4))
    hi = int(m.group(5)) if m.group(5) else lo
    if lo <= 0 or hi < lo:
        return None
    return (lo + hi) / 2 * _DAYS[m.group(6)]


def coarsen_durations(text: str) -> tuple[str, list[tuple[str, str]]]:
    """상대 기간을 범위로 바꾼 글과 [(원래 표현, 바꾼 표현)]. 날짜('3월 15일') · 횟수('1일 2회') · 연도('2019년')는 건드리지 않는다."""
    out, changes, pos = [], [], 0
    for m in _DUR.finditer(text):
        if m.group(6) == "일" and text[:m.start()].rstrip().endswith("월"):
            continue                                     # '3월 15일'은 날짜
        days = _days_of(m)
        if not days:
            continue
        label, ranged = bucket(days)
        new = f"약 {label}" if ranged and m.group(1) in ("약", "대략", "거의") else label
        end = m.end()
        tail = _TAIL.match(text, end)
        if tail and not ranged and label != "약 1년":
            # '이틀 동안' → '3일 이내', '3일 전' → '최근 3일 이내', '5년 전' → '3년도 더 전' (어색한 '3일 이내 동안'을 피한다)
            if tail.group(1) in ("동안", "간"):
                end = tail.end()
            elif label.endswith("이내"):
                new, end = f"최근 {label}", tail.end()
            else:
                new, end = "3년도 더 전", tail.end()
        old = text[m.start():end]
        if old.replace(" ", "") == new.replace(" ", ""):
            continue
        out.append(text[pos:m.start()])
        out.append(new)
        pos = end
        changes.append((old, new))
    if not changes:
        return text, []
    out.append(text[pos:])
    return "".join(out), changes


_BUCKET_RX = re.compile(r"(?<![\d~∼\-.])(?:" + "|".join(
    (r"(?:약\s*)?" + re.escape(lab)) if ranged else re.escape(lab) for _, lab, ranged in sorted(BUCKETS, key=lambda x: -len(x[1]))) + r")")


def duration_mentions(text: str, n_cases: int) -> list[tuple[str, str]]:
    """내보낸 글의 기간 범위 표현을 사례마다 [(사례N, 표현)]. 사례 표기가 없는 문장은 뺀다."""
    out: list[tuple[str, str]] = []
    for a, b, nums, _ in attribute_sentences(text, n_cases):
        if len(nums) == 0:
            continue
        sent = text[a:b]
        for m in _BUCKET_RX.finditer(sent):
            phrase = m.group(0).strip()
            if len(nums) == 1:
                out.append((f"사례{nums[0]}", phrase))
            else:                                        # '사례1은 약 1~2주, 사례2는 약 2~4주' → 그 앞에 가장 가까이 나온 사례
                before = [x for x in _CASE.finditer(sent[:m.start()]) if 1 <= int(x.group(1)) <= n_cases]
                if before:
                    out.append((f"사례{int(before[-1].group(1))}", phrase))
    return list(dict.fromkeys(out))
