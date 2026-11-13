"""추출 출력 해석: 잘린 출력 안의 빈 배열을 '관찰 없음'으로 받아들이면 안 된다 (fail-open 재현 입력)."""
from medical.tracking import parse_json


def test_truncated_output_with_inner_empty_array_is_not_accepted():
    truncated = '[{"attribute": "DX", "raw_value": "당뇨", "evidence_spans": []'
    assert parse_json(truncated, "array") is None


def test_truncated_output_without_inner_array_is_not_accepted():
    assert parse_json('[{"attribute": "DX"', "array") is None


def test_clean_empty_array_means_no_observations():
    assert parse_json("[]", "array") == []


def test_fenced_empty_array_means_no_observations():
    assert parse_json("```json\n[]\n```", "array") == []


def test_fenced_valid_list_is_accepted():
    assert parse_json('```json\n[{"attribute": "DX"}]\n```', "array") == [{"attribute": "DX"}]


def test_prose_wrapped_empty_array_is_rejected_fail_closed():
    assert parse_json("관찰 없음. []", "array") is None


def test_object_parse_unchanged():
    assert parse_json('{"a": 1}', "object") == {"a": 1}
