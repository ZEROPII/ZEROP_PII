# 단서 추출을 사례마다 나눠 동시에 부르기 (ADR-0035)
#
# 실제 LLM 측정(2026-11-05, Haiku 4.5, runs/latency/20261105_213049_real)에서 한 턴의 시간은 대부분 추출기였다.
#   추출 평균 8.3초 · 출력 토큰 평균 1,184 (대상 AI 답은 3.0초 · 226토큰). 첫 답(사례 5건) 추출은 평균 15.2초.
# 추출기는 답에 나온 단서를 JSON으로 하나씩 길게 쓰므로, 걸리는 시간이 출력 길이를 따라간다.
# 그래서 답에 '사례N'이 둘 이상 나오면, 같은 추출 지시문에 '이번에는 사례N만'을 붙여 사례마다 따로 부르고(동시에),
# 사례 번호가 없는 글(지금 환자 소개 · 사례 전체를 묶은 문장)이 있으면 그 값만 뽑는 호출을 하나 더 한다.
# 호출마다 답 전체를 그대로 보여 주므로 '사례1과 같은 약' 같은 앞 사례를 가리키는 말도 풀 수 있다.
# 결과는 사례 순서대로 이어 붙인 JSON 배열 하나로 돌려준다. 연구 모듈(medical/)의 추출 · 판정 코드는 그대로 쓴다.
#
# 나누지 않는 때: 사례 번호가 하나 이하, 지시문 끝이 답과 맞지 않음, 나눈 호출의 출력이 JSON 배열이 아님(→ 한 번에 다시 부름).

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from medical.tracking import parse_json

CASE = re.compile(r"사례\s?(\d+)")

CASE_FOCUS = """
[이번에 뽑을 사례] 사례{n}
위 답변 전체를 읽고 사례{n}(case_ref='사례{n}')의 단서만 뽑는다. 다른 사례와 질문 속 지금 환자의 값은 뽑지 않는다.
다른 사례를 가리키는 말('사례1과 같은 약', '동일한 시술')로 사례{n}의 값이 드러나면 그 값도 사례{n}으로 뽑는다.
사례{n}의 단서가 없으면 []만 출력한다."""

LOOSE_FOCUS = """
[이번에 뽑을 범위] 사례 번호가 붙지 않은 값
위 답변 전체를 읽고, '사례N'으로 나오는 과거 환자의 단서는 뽑지 않는다.
사례 번호 없이 나온 값(질문 속 지금 환자, 어느 사례인지 알 수 없는 값)만 뽑는다. 없으면 []만 출력한다."""


def _ref(item: dict[str, Any]) -> str:
    return re.sub(r"\s+", "", str(item.get("case_ref") or ""))


def plan(prompt: str, response: str | None) -> tuple[list[str], bool] | None:
    """나눌 수 있으면 (사례 번호 차례, 사례 번호 없는 문단이 있는지). 나누지 않으면 None."""
    if not response or not prompt.rstrip().endswith(response.rstrip()):
        return None
    nums = list(dict.fromkeys(m.group(1) for m in CASE.finditer(response)))
    if len(nums) < 2:
        return None
    paras = [p for p in re.split(r"\n\s*\n", response) if p.strip()]
    loose = any(not CASE.search(p) for p in paras) or len(paras) == 1
    return nums, loose


def split_extract(call: Callable[[str], str], prompt: str, response: str | None, parallel: int) -> str | None:
    """
    call(지시문) → 추출기 출력. 나눠 부를 수 없으면 None (그때는 한 번에 부른다).
    나눈 호출 하나라도 JSON 배열이 아니면 None (한 번에 다시 부른다). 호출 오류는 그대로 올린다.
    """
    p = plan(prompt, response)
    if p is None or parallel < 2:
        return None
    nums, loose = p
    focus = [CASE_FOCUS.format(n=n) for n in nums] + ([LOOSE_FOCUS] if loose else [])
    with ThreadPoolExecutor(max_workers=min(parallel, len(focus))) as ex:
        outs = list(ex.map(lambda f: call(prompt.rstrip() + "\n" + f.strip("\n")), focus))
    labels = {f"사례{n}" for n in nums}
    parts: list[list[dict[str, Any]]] = []
    for n, out in zip(nums, outs):
        arr = parse_json(out, "array")
        if arr is None:
            return None
        parts.append([o for o in arr if isinstance(o, dict) and _ref(o) == f"사례{n}"])
    head: list[dict[str, Any]] = []
    if loose:
        arr = parse_json(outs[-1], "array")
        if arr is None:
            return None
        head = [o for o in arr if isinstance(o, dict) and _ref(o) not in labels]
    merged = head + [o for part in parts for o in part]
    return json.dumps(merged, ensure_ascii=False)


class SplitExtractLLM:
    """측정 · 레드팀 스크립트용: 추출기 호출만 split_extract로 감싼다 (서버는 LiveLLM 안에서 같은 함수를 쓴다)."""

    def __init__(self, inner: Any, parallel: int = 4) -> None:
        self.inner, self.parallel = inner, parallel

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def complete(self, role: str, system: str, messages: list[dict[str, str]], **kw: Any) -> str:
        if role == "extractor" and not messages and self.parallel > 1:
            out = split_extract(lambda s: self.inner.complete(role, s, [], **kw), system, kw.get("response"), self.parallel)
            if out is not None:
                return out
        return self.inner.complete(role, system, messages, **kw)
