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
#     기간 뒤에 '이상 · 넘게'(하한) · '이내 · 미만 · 이하'(상한) · '정도 · 가량'(어림)이 붙으면 그 말까지 한 번에 바꾼다
#     ('약 2년 이상' → '1년 이상', '3일 이내' → '3일 이내'). 범위 뒤에 '이상'이 남아 '약 1~3년 이상'처럼 읽히지 않게 한다 (ADR-0035).
#   duration_mentions: 내보낸 글의 기간 범위를 사례마다 찾는다 (사례 노트 '기간' 항목).
#
#   내보낼 글 다듬기 (post_release, ADR-0032 · 연구자 4인 검토 P0-3 · P1-4). 후보 수 계산에 없는 값이 글에 그대로 나가지 않게 한다.
#     - 횟수 ('3회 처방' → '2~3회 처방')와 간격 ('6개월 간격' → '3~6개월 간격')은 정해 둔 범위로. '하루 2회' 같은 복용 횟수는 그대로.
#     - 부재 · 배타 진술 ('acetaminophen만 처방받았고 다른 약물은 없습니다', 'X 외에는 처방이 없었습니다')은 사례 문장에서 뺀다.
#       '그 사례에 다른 기록이 없다'는 것도 환자를 좁히는 정보인데 후보 수에 없다 (fail-closed: 세지 못하는 값은 내보내지 않는다).
#     - 짐작 문장 ('…피임 목적으로 보입니다', '…일 가능성이 있습니다')은 사례 문장에서 뺀다. 기록에 없는 원인 · 목적을 사실처럼
#       남기지 않는다 (지시문 v6의 짐작 금지를 출력에서도 확인).
#     - 사례 문장에 나온 영문 낱말이 그 답의 사례 문서 · 그 상위 범주 이름 어디에도 없으면 '설명 안 되는 용어'로 기록한다 (글은 그대로).
#     - 기록 말투를 진료 화면 말로 (natural_wording, ADR-0035): 사례 문서의 '종료 기록 없음'(처방 종료일이 없음)을 대상 AI가
#       '종료 기록이 없습니다'로 옮기면 무엇이 없는지 알기 어렵다. '종료일 없이 계속 처방되었습니다'로 바꾼다 (처방을 복용으로 바꾸지 않음).
#   사례 문장(사례 표기가 있거나 앞 문장의 사례를 잇는 문장)만 다룬다. 일반 설명 문장은 그대로 둔다.

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
        if att == "MED":
            for brand in re.findall(r"\[([^\]]+)\]", span or ""):
                add(att, brand)                          # 상표 이름: '… Intrauterine System [Mirena]' → 'Mirena' (ADR-0032)
        if data is not None and node in getattr(data, "N", {}):
            for a in data.anc(node)[1:]:
                if att == "MED" and a.startswith("MED_IN_"):
                    add(att, data.label(a))              # 성분 이름: 'acetaminophen 325 MG Oral Tablet' → 'acetaminophen'
                if att == "MED" and a.startswith("MED_DF_"):
                    add(att, data.label(a))              # 성분 · 제형: 'levonorgestrel Intrauterine System' (용량을 뺀 이름, ADR-0032)
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


# 날짜 표현 → 정규화기가 읽는 꼴 (2017-11-20 · 2017-11 · 2017). 정규화기는 '2017년 11월 20일' · '2017.11.20'을 읽지 못한다
_DATE_FORMS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?<!\d)(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일"), "day"),
    (re.compile(r"(?<![\d.])(\d{4})\s*[./]\s*(\d{1,2})\s*[./]\s*(\d{1,2})(?!\d)"), "day"),
    (re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)"), "day"),
    (re.compile(r"(?<!\d)(\d{4})\s*년\s*(\d{1,2})\s*월"), "month"),
    (re.compile(r"(?<![\d.])(\d{4})[./](\d{1,2})(?![\d./])"), "month"),
    (re.compile(r"(?<!\d)(\d{4})-(\d{2})(?![\d-])"), "month"),
    (re.compile(r"(?<!\d)(\d{4})\s*년(?!\s*\d)"), "year"),
]


def dates_in(text: str) -> list[str]:
    """글 속 날짜를 앞에서부터 정규화기 꼴로 (겹치는 것은 더 자세한 꼴 하나만). 달 1~12 · 날 1~31이 아니면 버린다."""
    taken: list[tuple[int, int]] = []
    found: list[tuple[int, str]] = []
    for rx, level in _DATE_FORMS:
        for m in rx.finditer(text or ""):
            if any(a < m.end() and m.start() < b for a, b in taken):
                continue
            y = m.group(1)
            if level == "year":
                val = y
            else:
                mo = int(m.group(2))
                if not 1 <= mo <= 12:
                    continue
                if level == "month":
                    val = f"{y}-{mo:02d}"
                else:
                    d = int(m.group(3))
                    if not 1 <= d <= 31:
                        continue
                    val = f"{y}-{mo:02d}-{d:02d}"
            taken.append(m.span())
            found.append((m.start(), val))
    return [v for _, v in sorted(found)]


def fix_period_value(ob: dict[str, Any]) -> dict[str, Any]:
    """
    날짜 단서의 값을 정규화기가 읽는 꼴로 바로잡는다. 그대로 두면 정규화가 실패해(UNMAPPED) State에 들어가지 않고, 공개 판정이
    그 날짜를 위험으로 보지 않아 원 답 그대로 나간다 (실제 LLM 결과 ⑥ 기록, RAG 재측정 R5 원본 대조에서 찾음, ADR-0033).
      - 값 자리에 설명('Gingivitis 진단 시작')을 쓰고 날짜는 근거 문장('2017-11-20에 시작되었고')에만 둔 경우 (T0003 턴 4: 시스템 k 8, 원본 대조 k 1)
      - '2014년 4월 1일' · '2014.04.01' 꼴 (T0004 턴 6: 재작성기가 날짜를 이 꼴로 바꿔 다시 확인을 지나침)
    값 · 근거 문장에 날짜가 하나만 있을 때만 바꾼다 (둘 이상이면 어느 것인지 모른다).
    """
    if ob.get("attribute") != "PERIOD":
        return ob
    raw = str(ob.get("raw_value") or "").strip()
    own = list(dict.fromkeys(dates_in(raw)))
    if len(own) > 1:
        return ob
    if len(own) == 1:
        return ob if own[0] == raw else dict(ob, raw_value=own[0], raw_value_was=ob.get("raw_value"))
    found: list[str] = []
    for sp in clean_spans(ob.get("evidence_spans")):
        found += dates_in(sp)
    found = list(dict.fromkeys(found))
    if len(found) != 1:
        return ob
    return dict(ob, raw_value=found[0], raw_value_was=ob.get("raw_value"))


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
        fixed.append(fix_period_value(o))
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

#: 기간 바로 뒤의 하한 · 상한 · 어림 말. '2년이 넘는'처럼 조사를 끼운 하한도 본다.
_BOUND = re.compile(r"(?P<low>\s*(?:이상|초과)|(?:이|가|을|를)?\s*넘(?:게|도록|는|은|어))|(?P<high>\s*(?:이내|미만|이하|안에))"
                    r"|(?P<about>\s*(?:정도|가량|쯤|남짓|내외|전후)|여(?=\s|$|[,.)]))")
#: 하한은 그 기간보다 짧은 가장 가까운 값으로, 상한은 긴 가장 가까운 값으로 (참인 채로 더 넓게). 10년보다 긴 상한은 바꾸지 않는다.
LOW_STEPS: list[tuple[float, str]] = [(1, "하루"), (3, "3일"), (7, "1주"), (14, "2주"), (30, "1개월"), (91, "3개월"), (182, "6개월"),
                                      (365, "1년"), (1095, "3년")]
HIGH_STEPS: list[tuple[float, str]] = [(3, "3일"), (7, "1주"), (14, "2주"), (31, "1개월"), (92, "3개월"), (183, "6개월"), (365, "1년"),
                                       (1095, "3년"), (1825, "5년"), (3650, "10년")]


def _bounded(days: float, b: re.Match[str], label: str, ranged: bool) -> str | None:
    """'약 2년 이상' 같은 기간 + 뒤말을 바꿀 글. 바꾸지 않으면 None."""
    if b.group("low") is not None:
        word = next((w for t, w in reversed(LOW_STEPS) if t <= days), LOW_STEPS[0][1])
        tail = b.group("low").strip()
        if "넘" in tail:
            verb = tail.lstrip("이가을를").strip()
            return f"{word}{'이' if _final_sound(word) else '가'} {verb}" if tail[0] in "이가을를" else f"{word} {verb}"
        return f"{word} 이상" if tail == "이상" else f"{word} 넘게"
    if b.group("high") is not None:
        word = next((w for t, w in HIGH_STEPS if t >= days - 0.5), None)
        return None if word is None else f"{word} {b.group('high').strip()}"
    return f"약 {label}" if ranged else label


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
        b = _BOUND.match(text, end)
        if b:
            got = _bounded(days, b, label, ranged)
            if got is None:
                continue                                 # '10년 미만'처럼 넓힐 값이 없는 상한은 그대로
            new, end = (f"총 {got}" if m.group(1) == "총" else got), b.end()
            old = text[m.start():end]
            if old.replace(" ", "") != new.replace(" ", ""):
                out.append(text[pos:m.start()])
                out.append(new)
                pos = end
                changes.append((old, new))
            continue                                     # 같으면 그대로 ('3일 이내', '1년 이상')
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


_BOUND_WORDS = sorted({w for _, w in LOW_STEPS + HIGH_STEPS}, key=len, reverse=True)
_BUCKET_RX = re.compile(r"(?<![\d~∼\-.])(?:" + "|".join(
    [r"(?:" + "|".join(map(re.escape, _BOUND_WORDS)) + r")(?:이|가)?\s?(?:이상|넘게|넘는|넘은|이내|미만|이하)"]
    + [(r"(?:약\s*)?" + re.escape(lab)) if ranged else re.escape(lab) for _, lab, ranged in sorted(BUCKETS, key=lambda x: -len(x[1]))]) + r")")


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


# ── 내보낼 글 다듬기 (ADR-0032) ────────────────────────────────

def count_bucket(n: int) -> str:
    """횟수 범위: 1회는 그대로, 2~3회, 4~9회, 10회 이상."""
    if n <= 1:
        return f"{n}회"
    if n <= 3:
        return "2~3회"
    if n <= 9:
        return "4~9회"
    return "10회 이상"


_CNT = re.compile(r"(?<![\d.~∼\-])(총\s*)?(\d{1,3})\s*(회|번|차례)(?![\d가-힣]*\s*(?:간격|마다|째))")
_FREQ_BEFORE = re.compile(r"(?:하루|매일|매주|매달|매월|\d+\s*일|\d+\s*주|\d+\s*달|\d+\s*개월|\d+\s*시간|주|달|월|일)\s*(?:에\s*)?$")
_INTERVAL = re.compile(r"(?<![\d.~∼\-])(?:(약|대략)\s*)?(\d{1,3})\s*(일|주|개월|달|년)\s*(간격|마다|주기|에\s*한\s*번)")


def coarsen_counts(text: str, n_cases: int) -> tuple[str, list[dict[str, Any]]]:
    """사례 문장의 횟수를 범위로 ('3회 처방' → '2~3회 처방'). 복용 횟수('하루 2회', '1일 3회', '주 2회')는 그대로."""
    edits: list[dict[str, Any]] = []
    out, pos = [], 0
    spans = [(a, b) for a, b, nums, _ in attribute_sentences(text, n_cases) if nums]
    for a, b in spans:
        for m in _CNT.finditer(text, a, b):
            n = int(m.group(2))
            if n <= 1 or _FREQ_BEFORE.search(text[max(a, m.start() - 8):m.start()]):
                continue
            new = f"{m.group(1) or ''}{count_bucket(n)}"
            old = text[m.start():m.end()]
            out.append(text[pos:m.start()])
            out.append(new)
            pos = m.end()
            edits.append(dict(kind="count", before=old, after=new))
    if not edits:
        return text, []
    out.append(text[pos:])
    return "".join(out), edits


def coarsen_intervals(text: str) -> tuple[str, list[dict[str, Any]]]:
    """간격을 기간 범위로 ('6개월 간격' → '3~6개월 간격', '2주마다' → '1~2주마다')."""
    edits: list[dict[str, Any]] = []

    def rep(m: re.Match[str]) -> str:
        days = int(m.group(2)) * _DAYS[m.group(3)]
        if days <= 0:
            return m.group(0)
        label, ranged = bucket(days)
        tail = m.group(4)
        new = (f"약 {label}" if ranged and m.group(1) else label) + ("" if tail == "마다" else " ") + tail
        if new.replace(" ", "") == m.group(0).replace(" ", ""):
            return m.group(0)
        edits.append(dict(kind="interval", before=m.group(0), after=new))
        return new

    return _INTERVAL.sub(rep, text), edits


# 부재 · 배타 진술
_KINDS = r"(?:약물|약|처방|진단|질환|병력|시술|치료|관리\s*계획|기록|동반\s*질환)"
_NONE_TAIL = (r"(?:은|는|이|가|도)?\s*(?:따로\s*|별도로\s*)?(?:없(?:었)?습니다|없었고|없고|없으며|없었으며|없음|없어요|없다"
              r"|(?:기록|확인|처방)되(?:어\s*있)?지\s*않(?:았)?(?:습니다|고|으며))")
_EXCEPT = re.compile(r"(?P<x>[^\s,.]+?)\s*(?:외에는|외에|이외에는|이외에|말고는|말고)\s*(?:다른\s*)?(?P<k>" + _KINDS + r")" + _NONE_TAIL)
_OTHER_NONE = re.compile(r"(?:,\s*|\s+)?(?:그리고\s*)?(?:그\s*(?:외|밖)(?:에|의|에는)?|이\s*외(?:에|의|에는)?|그\s*이외(?:에|의)?|다른)\s*(?:의\s*)?"
                         + _KINDS + _NONE_TAIL)
# 다른 말 없이 '없다'만 말하는 문장('사례1 기록에는 처방 약이 없습니다'): 게이팅으로 '(비공개)'를 본 대상 AI가 없다고 잘못 읽은 것일 수 있고,
# 맞더라도 후보 수 계산에 없는 부정 정보라 문장째 뺀다 (절만 떼면 남은 말이 어색해진다)
_PLAIN_NONE = re.compile(r"(?:처방\s*)?" + _KINDS + _NONE_TAIL)
_ONLY = re.compile(r"(?<=[A-Za-z0-9가-힣\])])만(?P<p>\s*(?:을|를|이|가))?(?=\s*(?:처방|투여|사용|복용|진단|시행|받|썼|쓰|기록|있))")
_COUNTED = re.compile(r"(?:\d|한|두|세|네)\s*(?:번|회|차례|일|주|개월|달|년|알|정)$")
_DIGIT_FINAL = dict(zip("0123456789", (True, True, False, True, False, False, True, True, True, False)))


def _final_sound(word: str) -> bool:
    """조사를 고를 끝소리에 받침이 있는지. 한글 · 숫자는 그대로, 로마자 약 이름은 어림한다 (-ine · -one · Tablet → 받침, MG · Spray · -er → 없음)."""
    w = re.sub(r"[\s\])}'\"]+$", "", word)
    if not w:
        return True
    c = w[-1]
    if "가" <= c <= "힣":
        return (ord(c) - 0xAC00) % 28 != 0
    if c.isdigit():
        return _DIGIT_FINAL[c]
    t = w.lower()
    if not t[-1].isalpha():
        return True
    return t.endswith(("ng", "n", "m", "l", "k", "p", "let", "ne", "me", "le"))


def _only_rep(m: re.Match[str]) -> str:
    """'X만 처방받았' → 'X을 처방받았', 'X만 있습니다' → 'X이 있습니다', '한 번만 받았' → '한 번 받았'. 조사는 X의 끝소리로 고른다."""
    prev = m.string[:m.start()]
    if _COUNTED.search(prev):
        return (m.group("p") or "").strip()
    nxt = m.string[m.end():].lstrip()
    head = (re.match(r"\S+", nxt) or re.match(r"", nxt)).group(0)
    if m.group("p"):
        subject = m.group("p").strip() in ("이", "가")
    else:
        subject = head.startswith(("있", "기록")) or "되" in head
    has = _final_sound(prev)
    return ("이" if has else "가") if subject else ("을" if has else "를")
_ONLY_END = re.compile(r"뿐(?=입니다|이었습니다|이고|이며|이다|이었고)")
_ENDINGS = [(re.compile(r"(았|었|였|했)고\s*([.!?]?)\s*$"), r"\1습니다\2"), (re.compile(r"(았|었|였|했)으?며\s*([.!?]?)\s*$"), r"\1습니다\2"),
            (re.compile(r"있으며\s*([.!?]?)\s*$"), r"있습니다\1"), (re.compile(r"있고\s*([.!?]?)\s*$"), r"있습니다\1"),
            (re.compile(r"이며\s*([.!?]?)\s*$"), r"입니다\1"), (re.compile(r"하며\s*([.!?]?)\s*$"), r"합니다\1"),
            (re.compile(r"하고\s*([.!?]?)\s*$"), r"합니다\1")]
_FINAL = re.compile(r"(?:다|요|음|함|됨)\s*[.!?]?\s*$")


def _close(sentence: str) -> str | None:
    """잘린 문장을 끝맺는다 ('처방받았고' → '처방받았습니다.'). 끝맺을 수 없으면 None (문장째 뺀다)."""
    s = sentence.rstrip()
    if not s:
        return None
    body = s.rstrip(" ,.;")
    for rx, sub in _ENDINGS:
        if rx.search(body):
            return rx.sub(sub, body).rstrip(".") + "."
    if _FINAL.search(s):
        return s if s.endswith((".", "!", "?")) else s + "."
    return None


def _rewrite_sentences(text: str, n_cases: int, fix: Any) -> tuple[str, list[dict[str, Any]]]:
    """사례 문장마다 fix(문장) → (새 문장 또는 None=빼기, [편집])를 적용한다."""
    edits: list[dict[str, Any]] = []
    out, pos = [], 0
    for a, b, nums, _ in attribute_sentences(text, n_cases):
        if not nums:
            continue
        sent = text[a:b]
        lead = sent[:len(sent) - len(sent.lstrip())]
        trail = sent[len(sent.rstrip()):]
        new, ed = fix(sent.strip())
        if not ed:
            continue
        for e in ed:
            e.setdefault("cases", [f"사례{n}" for n in nums])
        edits += ed
        out.append(text[pos:a])
        out.append("" if new is None else lead + new + trail)
        pos = b
    if not edits:
        return text, []
    out.append(text[pos:])
    joined = "".join(out)
    return re.sub(r"[ \t]{2,}", " ", re.sub(r"\n{3,}", "\n\n", joined)).strip(), edits


def _fix_absence(s: str) -> tuple[str | None, list[dict[str, Any]]]:
    ed: list[dict[str, Any]] = []
    new = s

    def except_rep(m: re.Match[str]) -> str:
        ed.append(dict(kind="absence", before=m.group(0)))
        tail = m.group(0)
        verb = "있습니다" if re.search(r"(?:습니다|음|어요|다)$", tail) else "있고" if tail.endswith("고") else "있으며" if tail.endswith("며") else "있습니다"
        kind = re.sub(r"\s+", " ", m.group("k"))           # f-string 안에 역슬래시를 두지 않는다 (Python 3.11)
        return f"{m.group('x')} {kind} 기록이 {verb}"

    new = _EXCEPT.sub(except_rep, new)
    m = _OTHER_NONE.search(new)
    while m is not None:
        ed.append(dict(kind="absence", before=m.group(0).strip(" ,")))
        new = new[:m.start()] + new[m.end():]
        m = _OTHER_NONE.search(new)
    plain = _PLAIN_NONE.search(new)
    if plain is not None:
        ed.append(dict(kind="absence", before=plain.group(0)))
        return None, ed
    for rx, rep in ((_ONLY, _only_rep), (_ONLY_END, "")):
        if rx.search(new):
            ed.append(dict(kind="exclusive", before=rx.search(new).group(0)))
            new = rx.sub(rep, new)
    if not ed:
        return s, []
    closed = _close(new)
    if closed is None or len(re.sub(r"사례\s*\d+(?:[은는이가의,]|\s)*", "", closed).strip(" .")) < 4:
        return None, ed
    return closed, ed


_SPEC = re.compile(r"(?:것으로|것처럼|로|으로)\s*(?:보입니다|보이며|보이고|보여집니다|보였습니다|추정됩니다|생각됩니다|판단됩니다)"
                   r"|추정(?:됩니다|합니다|되며|되고)|짐작(?:됩니다|합니다)|아마(?:도)?\s|가능성이\s*(?:있|높|큽)|인\s*듯(?:합니다|하며|하고)"
                   r"|(?:것|거)\s*같습니다|시사(?:합니다|하며)|의심(?:됩니다|되며)|(?:일|였을|이었을)\s*수\s*있습니다"
                   r"|목적(?:으로|인\s*것으로)\s*(?:보|추정|생각)|때문(?:으로|인\s*것으로)\s*(?:보|추정|생각)")
_SPEC_CUT = re.compile(r",?\s*(?:이는|이것은|이런\s*처방은|이\s*처방은|따라서|그래서|아마)\s")


def _fix_speculation(s: str) -> tuple[str | None, list[dict[str, Any]]]:
    m = _SPEC.search(s)
    if m is None:
        return s, []
    cut = None
    for c in _SPEC_CUT.finditer(s):
        if c.start() < m.start():
            cut = c
    if cut is not None and cut.start() > 0:
        head = _close(s[:cut.start()])
        if head is not None and _SPEC.search(head) is None:
            return head, [dict(kind="speculation", before=s[cut.start():].strip(" ,"))]
    return None, [dict(kind="speculation", before=s)]


_WORD = re.compile(r"[A-Za-z][A-Za-z\-]{3,}")
_COMMON_WORDS = {w.lower() for w in (
    "Oral Tablet Capsule Solution Injection Injectable Chewable Sublingual System Intrauterine Topical Cream Suspension Extended Release "
    "Delayed Disintegrating Transdermal Patch Inhalation Inhaler Nasal Spray Powder Gel Ointment Lotion Drops Ophthalmic Otic Vaginal Rectal "
    "Prefilled Syringe Auto-Injector Pack Kit Metered Dose Unit Hour Daily Dental Instrument Procedure Therapy Plan Care Record "
    "ICD SNOMED ATC RxNorm LLM AI MediCloak Massachusetts with from using and the for "
    "Diseases Disorders Disease Disorder Syndrome Chronic Acute History Finding Status Other Unspecified Certain Conditions").split()}


def unexplained_terms(text: str, docs: list[dict[str, Any]], n_cases: int, data: Any = None) -> list[dict[str, Any]]:
    """사례 문장의 영문 낱말 가운데 그 답의 사례 문서 · 상위 범주 이름에 없는 것 (기록만, 글은 바꾸지 않는다)."""
    vocab = set(_COMMON_WORDS)
    for d in docs:
        vocab |= {w.lower() for w in _WORD.findall(d.get("text") or "")}
        if data is not None:
            for r in d.get("fact_rows") or []:
                node = r.get("node_id")
                if node in getattr(data, "N", {}):
                    for a in data.anc(node):
                        vocab |= {w.lower() for w in _WORD.findall(data.label(a))}
    out = []
    for a, b, nums, _ in attribute_sentences(text, n_cases):
        if not nums:
            continue
        for w in _WORD.findall(text[a:b]):
            if w.lower() not in vocab:
                out.append(dict(kind="unexplained", term=w, cases=[f"사례{n}" for n in nums]))
    seen, uniq = set(), []
    for x in out:
        if (x["term"].lower(), tuple(x["cases"])) not in seen:
            seen.add((x["term"].lower(), tuple(x["cases"])))
            uniq.append(x)
    return uniq[:20]


# ── 기록 말투를 진료 화면 말로 (ADR-0035) ─────────────────────────

_NO_END = re.compile(r"(?:처방\s*)?종료\s*(?:일\s*)?(?:기록|날짜)\s*(?:이|은|도|가)?\s*"
                     r"(?P<end>없(?:습니다|어요|는\s*상태입니다|으며|고|음)|없이)")
_PLAN_CTX = re.compile(r"관리\s*계획|계획은|계획도|계획이")
_MED_CTX = re.compile(r"처방|약|MG|Tablet|Capsule|Injection|Spray|Gel|Solution|Patch|Inhaler", re.I)
_DONE_CTX = re.compile(r"(?:처방|진행)(?:되었|받았|됐)(?:으며|고)\s*$")
_NO_END_TAIL = {"없습니다": "습니다", "없어요": "습니다", "없는상태입니다": "습니다", "없으며": "으며", "없고": "고"}


def natural_wording(text: str) -> tuple[str, list[dict[str, Any]]]:
    """
    '종료 기록이 없습니다' → '종료일 없이 계속 처방되었습니다' (과거 사례의 기록이라 지난 일로 쓴다. 처방을 복용으로 바꾸지 않는다).
    앞에 '처방되었으며'가 있으면 '종료일 없이 이어졌습니다', 관리 계획 문장이면 '계속 진행되었습니다'. 바꾼 것을 편집 목록으로.
    """
    edits: list[dict[str, Any]] = []

    def rep(m: re.Match[str]) -> str:
        start = max(text.rfind("\n", 0, m.start()), text.rfind(". ", 0, m.start()))
        ctx = text[start + 1:m.start()]
        plan = bool(_PLAN_CTX.search(ctx)) and not _MED_CTX.search(ctx)
        end = re.sub(r"\s+", "", m.group("end"))
        if end == "없이":
            new = "종료일 없이"
        elif end == "없음":
            new = f"종료일 없음(계속 {'진행' if plan else '처방'})"
        elif _DONE_CTX.search(ctx):
            new = "종료일 없이 이어졌" + _NO_END_TAIL.get(end, "습니다")
        else:
            new = f"종료일 없이 계속 {'진행되었' if plan else '처방되었'}" + _NO_END_TAIL.get(end, "습니다")
        edits.append(dict(kind="wording", before=m.group(0), after=new))
        return new

    return _NO_END.sub(rep, text), edits


def post_release(text: str, n_cases: int, docs: list[dict[str, Any]] | None = None, data: Any = None) -> tuple[str, list[dict[str, Any]]]:
    """내보낼 글 다듬기 전체 (위 설명). (다듬은 글, 편집 목록). 기간 범위는 coarsen_durations와 같다."""
    edits: list[dict[str, Any]] = []
    text, dur = coarsen_durations(text)
    edits += [dict(kind="duration", before=o, after=n) for o, n in dur]
    text, ed = coarsen_intervals(text)
    edits += ed
    text, ed = coarsen_counts(text, n_cases)
    edits += ed
    text, ed = natural_wording(text)
    edits += ed
    text, ed = _rewrite_sentences(text, n_cases, _fix_absence)
    edits += ed
    text, ed = _rewrite_sentences(text, n_cases, _fix_speculation)
    edits += ed
    if docs:
        edits += unexplained_terms(text, docs, n_cases, data)
    return text, edits
