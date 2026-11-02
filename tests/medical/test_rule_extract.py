"""규칙 추출(medical/rule_extract.py): 나이 · 날짜를 사례 구간에서 뽑고, 사건 종류를 줄 안 낱말로 정한다."""
from __future__ import annotations

from types import SimpleNamespace

from medical.rule_extract import rule_observations
from medical.session import extract
from medical.tracking import view_of

ANSWER = (
    "사례1은 비슷합니다.\n"
    "진단: Gingivitis (1985-05-25, 65세) → 종료: 1985-06-08\n"
    "- 약물: acetaminophen 325 MG Oral Tablet (2017-05-14~2017-05-24)\n"
    "| **Acute pharyngitis** | 2023-04-16 | 16세 |\n"
    "일반적으로 65세 이상 환자에게 권고됩니다.\n"
    "사례2\n"
    "- 현재 나이: 약 17-18세\n"
    "관리 계획: Respiratory therapy (2017-05-15 시작)\n"
)


def _by(obs):
    return {(o["case_ref"], o["attribute"], o["raw_value"], o.get("time_role")) for o in obs}


def test_ages_and_dates_with_roles():
    got = _by(rule_observations(ANSWER, "54세 남성 환자와 비슷한 사례", []))
    assert ("사례1", "AGE", "65세", None) in got
    assert ("사례1", "AGE", "16세", None) in got
    assert ("사례1", "PERIOD", "1985-05-25", "CONDITION_START") in got
    assert ("사례1", "PERIOD", "1985-06-08", "CONDITION_END") in got
    assert ("사례1", "PERIOD", "2017-05-14", "MEDICATION_START") in got
    assert ("사례1", "PERIOD", "2017-05-24", "MEDICATION_END") in got
    assert ("사례2", "PERIOD", "2017-05-15", "CAREPLAN_START") in got


def test_skips_what_it_cannot_place():
    obs = rule_observations(ANSWER, "", [])
    vals = {(o["case_ref"], o["raw_value"]) for o in obs}
    assert ("사례1", "2023-04-16") not in vals          # 표 줄에 사건 낱말이 없음 → 사건 종류를 모름
    assert not any(o["raw_value"] == "18세" for o in obs)   # 범위 '17-18세'는 LLM 추출에 맡김
    assert sum(1 for o in obs if o["raw_value"] == "65세") == 1   # '65세 이상'(기준 문장)은 따로 내지 않음
    assert all(o["subject"] == "TARGET_PATIENT" and o["source"] == "RULE" for o in obs)


def test_does_not_repeat_llm_or_query_values():
    llm = [dict(attribute="AGE", raw_value="65세", evidence_spans="65세", case_ref="사례1", subject="TARGET_PATIENT")]
    obs = rule_observations(ANSWER, "16세 환자", llm)
    assert not any(o["raw_value"] in ("65세", "16세") for o in obs)


def test_rule_observations_commit_through_normalizer(nz):
    obs = [o for o in rule_observations(ANSWER, "", []) if o["case_ref"] == "사례1"]
    v = view_of(obs, ANSWER, "", nz)
    committed = {o["raw_value"]: o["node_id"] for o in v.normalized["사례1"] if o["commit"]}
    assert committed["65세"] == "AGE_Y65"
    assert committed["1985-05-25"].startswith("PERIOD_CONDITION_START")


def test_extract_adds_rules_only_when_enabled():
    llm = SimpleNamespace(complete=lambda *a, **k: "[]")
    for flag, expect in ((False, 0), (True, 1)):
        ctx = SimpleNamespace(cfg=SimpleNamespace(max_extract_retries=0, rule_extract=flag), llm=llm)
        obs, ok, n = extract(ctx, "질문", "사례1\n당시 나이: 10세", "[]", [])
        assert ok and n == 1 and len(obs) == expect
