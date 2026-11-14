"""[수정본] 결정적 재작성 폭주 방지: 근거 문장이 글자 단위로 쪼개지거나 치환이 무한히 커지면 안 된다."""
import pytest

from medical.defense import MIN_SPAN_CHARS, SUPPRESSED_MARK, apply_changes_deterministic, normalize_spans


def test_string_span_is_not_split_into_characters():
    assert normalize_spans("Acute pharyngitis") == ["Acute pharyngitis"]
    assert normalize_spans(["a b", "c"]) == ["a b", "c"]
    assert normalize_spans(None) == []


def test_single_character_spans_are_not_replaced():
    resp = "진단은 acute 입니다."
    ch = [dict(raw_value="", action="suppress", to_label=None, evidence_spans=["a", "c", "t"])]
    assert apply_changes_deterministic(resp, ch) == resp


def test_multi_char_span_is_replaced_once():
    resp = "진단: Acute pharyngitis 입니다."
    ch = [dict(raw_value="", action="suppress", to_label=None, evidence_spans=["Acute pharyngitis"])]
    out = apply_changes_deterministic(resp, ch)
    assert "Acute pharyngitis" not in out and SUPPRESSED_MARK in out


def test_growth_guard_raises_instead_of_exploding():
    # 치환 표시 안에 들어 있는 글자를 근거로 반복 치환하면 길이가 계속 커진다 (실제 폭주 패턴)
    resp = "공개 " * 300
    ch = [dict(raw_value="", action="suppress", to_label=None, evidence_spans=["공개"] * 200)]
    try:
        out = apply_changes_deterministic(resp, ch)
    except ValueError:
        return
    assert len(out) < 20 * len(resp) + 2000


def test_min_span_constant_is_two():
    assert MIN_SPAN_CHARS == 2
