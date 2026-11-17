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


def test_min_span_constant_is_three():
    assert MIN_SPAN_CHARS == 3


def test_two_character_spans_are_not_replaced():
    """[R3] 두 글자 근거는 값 치환에 쓰지 않는다. 원래 값이 답에 없을 때 두 글자 조각으로 바꾸면 답의 다른 곳까지 바뀐다."""
    resp = "환자는 서울 거주입니다. 서울 소재 병원 기록입니다."
    ch = [dict(raw_value="Seoul", action="suppress", to_label=None, evidence_spans=["서울"])]
    assert apply_changes_deterministic(resp, ch) == resp


def test_two_character_raw_value_is_still_replaced():
    """[R3] 원래 값이 답에 그대로 있으면 길이와 상관없이 원래 값으로 가린다 (두 글자 값도 가려진다)."""
    resp = "성별은 남성입니다."
    ch = [dict(raw_value="남성", action="suppress", to_label=None, evidence_spans=["남성"])]
    out = apply_changes_deterministic(resp, ch)
    assert "남성" not in out and SUPPRESSED_MARK in out


def test_string_span_replaced_as_one_piece():
    """[R3] 11-05 T0002: 추출기가 근거를 글자열 하나로 주어도 글자 단위로 쪼개지지 않고 한 덩어리로 바뀐다."""
    resp = "사례1은 naproxen 220 MG 정제를 처방받았습니다. 사례2는 lisinopril을 복용합니다."
    ch = [dict(raw_value="naproxen sodium 220 MG Oral Tablet", action="suppress", to_label=None,
               evidence_spans="naproxen 220 MG 정제")]
    out = apply_changes_deterministic(resp, ch)
    assert "naproxen" not in out and "lisinopril" in out and len(out) < len(resp) + 20
