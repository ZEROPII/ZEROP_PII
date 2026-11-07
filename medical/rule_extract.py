"""
규칙 추출 (나이 · 날짜) — LLM 추출기 결과에 형식이 정해진 단서를 보탠다 [본 연구 설정, 2026-11-02].

파일럿 2 (run_20261019_204802, C0)에서 답변에 그대로 나온 단서 445개 중 128개를 추출기가 놓쳤고,
그중 나이("10세") 36개 · 날짜("2017-05-15") 39개가 형식이 정해진 값이었다. 이런 값은 정규식이 LLM보다 정확하다.

원칙
- LLM 추출 결과는 그대로 두고, LLM이 같은 사례에서 같은 속성 · 같은 값을 이미 뽑았으면 보태지 않는다.
- 정규화(normalize_bridge)가 받을 수 있는 것만 낸다. 날짜는 사건 종류(time_role)를 줄 안의 낱말
  (진단 · 시술 · 처방 · 관리 계획 · 진료)로 알 수 있을 때만 내고, 모르면 내지 않는다
  → 반영(commit)되지 않을 관찰로 재현율 숫자만 올리는 일을 막는다.
- '사례N' 구간 안의 값만 그 사례의 값(TARGET_PATIENT)으로 본다. 질문에 이미 있는 값은 질의 환자 정보일 수 있어 내지 않는다.
- 나이 기준 문장("65세 이상")과 범위("17-18세", LLM이 처리)는 내지 않는다.
사건 묶음(event_ref)은 붙이지 않는다 (같은 사건이라는 근거가 없으면 묶지 않는 쪽이 k를 부풀리지 않는다).

나열 귀속 [2026-11-03, 팀 채점 단계 4와 같은 규칙]: '사례1, 2, 3, 5: 값'처럼 사례 번호를 나열하고 값을 붙인 줄은,
값을 단서 종류와 상관없이 정규화해 보고 한 종류로만 확정되면 나열된 각 사례의 관찰로 더한다 (정규화기 nz가 있을 때만).
사례 기록을 보고 귀속을 정하지는 않는다(채점 기준과 같은 정보를 쓰게 되므로).
"""

from __future__ import annotations

import re
from typing import Any

_CASE = re.compile(r"사례\s*(\d+)")
_AGE = re.compile(r"(?<![\d\-~.])(?:만\s*)?(\d{1,3})\s*(세|살)(?!\s*(?:이상|이하|미만|초과|대|기|부터|까지))")
_DATE = re.compile(r"(?<!\d)(\d{4})(?:-(\d{2})-(\d{2})|\.(\d{2})\.(\d{2})|/(\d{2})/(\d{2})|년\s*(\d{1,2})월(?:\s*(\d{1,2})일)?)(?!\d)")

# 줄 안에서 날짜 바로 앞에 가장 가까이 나온 낱말로 사건 종류를 정한다
_ROLE_WORDS = [
    ("CAREPLAN", re.compile(r"관리\s*계획|care\s*plan|계획", re.I)),
    ("MEDICATION", re.compile(r"처방|약물|복용|투약|인슐린|\bMG\b|Oral|Tablet|Injection|Pack", re.I)),
    ("PROCEDURE", re.compile(r"시술|수술|생검|시행")),
    ("CONDITION", re.compile(r"진단")),
    ("ENCOUNTER", re.compile(r"진료|내원|방문|입원")),
]
_END = re.compile(r"종료|마지막|까지")


def _segments(text: str) -> list[tuple[str, int, int]]:
    """('사례N', 시작, 끝) — '사례N' 표지부터 다음 표지 전까지."""
    marks = [(f"사례{int(m.group(1))}", m.start()) for m in _CASE.finditer(text)]
    return [(ref, s, marks[i + 1][1] if i + 1 < len(marks) else len(text)) for i, (ref, s) in enumerate(marks)]


def _role(line: str, pos: int) -> str | None:
    """line[:pos] 안에서 가장 늦게 나온 사건 낱말. 같은 줄에 없으면 None."""
    best, at = None, -1
    head = line[:pos]
    for role, rx in _ROLE_WORDS:
        for m in rx.finditer(head):
            if m.start() > at:
                best, at = role, m.start()
    return best


def _is_end(line: str, pos: int, word_at: int) -> bool:
    """범위의 뒤 날짜('A~B'의 B)이거나, 사건 낱말과 날짜 사이에 '종료 · 마지막 · 까지'가 있으면 END."""
    before = line[max(word_at, 0):pos]
    return bool(re.search(r"[~∼–]\s*$", line[:pos])) or bool(_END.search(before))


def _word_at(line: str, pos: int) -> int:
    at = -1
    for _, rx in _ROLE_WORDS:
        for m in rx.finditer(line[:pos]):
            at = max(at, m.start())
    return at


def _known(llm_obs: list[dict[str, Any]], ref: str, attribute: str, value: str) -> bool:
    for o in llm_obs:
        r = _CASE.search(str(o.get("case_ref") or ""))
        if not r or f"사례{int(r.group(1))}" != ref or o.get("attribute") != attribute:
            continue
        sp = o.get("evidence_spans") or []
        texts = [sp] if isinstance(sp, str) else [str(x) for x in sp]
        if any(value in t for t in texts + [str(o.get("raw_value") or "")]):
            return True
    return False


def rule_observations(response: str, query: str, llm_obs: list[dict[str, Any]], nz: Any = None) -> list[dict[str, Any]]:
    """LLM이 놓친 나이 · 날짜(와 nz가 있으면 나열 귀속)를 Observation 형식으로 돌려준다 (source='RULE')."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for ref, s, e in _segments(response):
        for line in response[s:e].split("\n"):
            for m in _AGE.finditer(line):
                val = m.group(0).strip()
                if val in query or _known(llm_obs, ref, "AGE", m.group(1) + m.group(2)) or (ref, "AGE", val) in seen:
                    continue
                seen.add((ref, "AGE", val))
                out.append(_ob(ref, "AGE", val))
            for m in _DATE.finditer(line):
                val = m.group(0)
                role = _role(line, m.start())
                if role is None or val in query or _known(llm_obs, ref, "PERIOD", val):
                    continue
                tr = f"{role}_{'END' if _is_end(line, m.start(), _word_at(line, m.start())) else 'START'}"
                if (ref, tr, val) in seen:
                    continue
                seen.add((ref, tr, val))
                out.append(_ob(ref, "PERIOD", val, time_role=tr))
    if nz is not None:
        out += list_observations(response, llm_obs + out, nz)
    return out


_LIST = re.compile(r"사례\s*(\d+(?:\s*,\s*\d+)*)\s*\**\s*[:：]\s*\**\s*([^\n|]+)")
_TYPED = ("SEX", "AGE", "REGION", "DX", "PROC", "MED", "PLAN")


def list_observations(response: str, known: list[dict[str, Any]], nz: Any) -> list[dict[str, Any]]:
    """'사례1, 2, 3, 5: 값' 줄의 값을 나열된 사례마다 귀속 (한 단서 종류로만 확정될 때)."""
    have = {(str(o.get("case_ref")), o.get("attribute"), str(o.get("raw_value"))) for o in known}
    out: list[dict[str, Any]] = []
    for m in _LIST.finditer(response):
        cases = [int(x) for x in re.findall(r"\d+", m.group(1))]
        for val in re.split(r"\s*[,，]\s*", re.sub(r"[*_`]", "", m.group(2)).strip()):
            val = val.strip(" .")
            if not val:
                continue
            hits = [att for att in _TYPED
                    if nz.normalize(dict(attribute=att, raw_value=val, evidence_spans=[val], subject="TARGET_PATIENT", case_ref="사례0"), val).get("commit")]
            if len(hits) != 1:
                continue
            for n in cases:
                key = (f"사례{n}", hits[0], val)
                if key not in have:
                    have.add(key)
                    out.append(dict(_ob(f"사례{n}", hits[0], val), evidence_spans=[m.group(0)], rule="LIST_ATTRIBUTION"))
    return out


def _ob(ref: str, attribute: str, value: str, **extra: Any) -> dict[str, Any]:
    return dict(attribute=attribute, raw_value=value, evidence_spans=[value], inference_mode="EXPLICIT", confidence=5,
                case_ref=ref, subject="TARGET_PATIENT", context_status="UNSPECIFIED", event_ref=None, source="RULE", **extra)
