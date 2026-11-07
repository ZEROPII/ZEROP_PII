# 단서 추출을 사례마다 나눠 동시에 부르기 (ADR-0035): 나누는 조건 · 합친 결과 · 실패하면 한 번에 · 동시 호출 · 자리 하나
import json
import threading
import time

from medical.prompts import PROMPTS
from webdemo.backend.live import LiveLLM
from webdemo.backend.split_extract import SplitExtractLLM, plan, split_extract

ANSWER = ("현재 환자(31세 여성, Acute pharyngitis)와 비슷한 사례를 정리했습니다.\n\n"
          "사례1은 Anemia 진단을 받았고 vitamin B12를 처방받았습니다.\n\n"
          "사례2는 사례1과 같은 약을 처방받았습니다.\n\n"
          "사례3은 penicillin V potassium 500 MG Oral Tablet을 처방받았습니다.")
ALL = [dict(attribute="AGE", raw_value="31세", case_ref="UNCLEAR", subject="OTHER"),
       dict(attribute="DX", raw_value="Anemia", case_ref="사례1", subject="TARGET_PATIENT"),
       dict(attribute="MED", raw_value="vitamin B12", case_ref="사례1", subject="TARGET_PATIENT"),
       dict(attribute="MED", raw_value="vitamin B12", case_ref="사례 2", subject="TARGET_PATIENT"),
       dict(attribute="MED", raw_value="penicillin V potassium 500 MG Oral Tablet", case_ref="사례3", subject="TARGET_PATIENT")]


def prompt(response: str) -> str:
    return PROMPTS["extractor"].format(cases="[]", query="비슷한 사례의 처방을 알려 주세요", response=response)


def test_plan_needs_two_cases_and_finds_text_without_case_numbers():
    assert plan(prompt("사례1은 Anemia입니다."), "사례1은 Anemia입니다.") is None
    assert plan(prompt(ANSWER), ANSWER) == (["1", "2", "3"], True)
    only = "사례1은 Anemia입니다.\n\n사례2는 Gingivitis입니다."
    assert plan(prompt(only), only) == (["1", "2"], False)
    assert plan(prompt(only), "다른 답") is None                         # 지시문 끝이 답과 다르면 나누지 않는다
    one_para = "사례1은 Anemia, 사례2는 Gingivitis입니다."
    assert plan(prompt(one_para), one_para) == (["1", "2"], True)      # 한 문단에 여럿이면 번호 없는 값도 따로 본다


def test_split_merges_each_case_in_order_and_keeps_values_without_case_numbers():
    seen: list[str] = []
    lock = threading.Lock()

    def call(p: str) -> str:                                          # 추출기 흉내: 범위와 상관없이 모두 낸다 (거르는 것은 split_extract)
        with lock:
            seen.append(p)
        return "```json\n" + json.dumps(ALL, ensure_ascii=False) + "\n```"

    out = json.loads(split_extract(call, prompt(ANSWER), ANSWER, 4))
    assert [(o["case_ref"], o["raw_value"]) for o in out] == [("UNCLEAR", "31세"), ("사례1", "Anemia"), ("사례1", "vitamin B12"),
                                                             ("사례 2", "vitamin B12"), ("사례3", "penicillin V potassium 500 MG Oral Tablet")]
    assert len(seen) == 4                                             # 사례 셋 + 번호 없는 글 하나
    base = prompt(ANSWER)
    assert all(p.startswith(base) and p.count("[이번 답변]") == base.count("[이번 답변]") for p in seen)   # 답 전체를 그대로 (앞 사례를 가리키는 말도 풀게)


def test_split_falls_back_when_a_part_is_not_json_and_skips_single_case():
    calls = []

    def call(p: str) -> str:
        calls.append(p)
        return "추출하지 못했습니다" if "사례2" in p.rsplit("[이번에 뽑을", 1)[-1] else "[]"

    assert split_extract(call, prompt(ANSWER), ANSWER, 4) is None     # 하나라도 JSON이 아니면 한 번에 다시 부르게 None
    assert split_extract(lambda p: "[]", prompt("사례1은 Anemia입니다."), "사례1은 Anemia입니다.", 4) is None
    assert split_extract(lambda p: "[]", prompt(ANSWER), ANSWER, 1) is None


def test_parts_run_at_the_same_time_and_share_one_slot():
    active, peak = [0], [0]
    lock = threading.Lock()

    class Inner:
        usage: list = []

        def complete(self, role, system, messages, **kw):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.2)
            with lock:
                active[0] -= 1
            return "[]"

    live = LiveLLM(Inner(), None, concurrency=1, extract_parallel=4)
    t0 = time.time()
    out = live.complete("extractor", prompt(ANSWER), [], response=ANSWER, docs=None)
    took = time.time() - t0
    assert json.loads(out) == [] and peak[0] == 4 and took < 0.6       # 넷이 한꺼번에 (하나씩이면 0.8초)
    assert live._slots.busy == 0                                       # 자리는 하나만 잡았다가 돌려준다
    # .env에 요청 간 최소 간격이 있으면 나누지 않는다
    spaced = type("I", (Inner,), {"client": type("C", (), {"_settings": type("S", (), {"llm_min_interval_sec": 1.0})()})()})()
    assert LiveLLM(spaced, None, concurrency=1, extract_parallel=4).extract_parallel == 1
    # 측정 스크립트용 감싸개도 같은 방식
    peak[0] = 0
    assert SplitExtractLLM(Inner(), 4).complete("extractor", prompt(ANSWER), [], response=ANSWER) == "[]" and peak[0] == 4
