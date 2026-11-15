"""[수정본] 설명이 붙은 닫힌 울타리 빈 배열은 '관찰 없음'이고, 잘린 출력의 빈 배열은 여전히 거절(None)이다."""
from medical.tracking import parse_json


def test_fenced_empty_array_with_explanation_is_no_observation():
    text = "```json\n[]\n```\n\n**설명:** 이번 답변에서 추출할 단서가 없습니다."
    assert parse_json(text, "array") == []


def test_empty_array_inside_body_is_still_rejected():
    text = '설명입니다. {"evidence_spans": []} 그리고 끝.'
    assert parse_json(text, "array") is None


def test_truncated_output_is_still_rejected():
    text = '```json\n[{"attribute": "DX", "raw_value": "Anemia", "evidence_spans": []'
    assert parse_json(text, "array") is None


def test_plain_empty_array_still_accepted():
    assert parse_json("[]", "array") == []
