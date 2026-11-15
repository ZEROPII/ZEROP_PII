"""[수정본] 사례에 귀속됐지만 정규화에 실패(UNMAPPED)한 공개는 내보내지 않는다. 목록 값은 항목별로 나눠 다시 본다."""
from medical.tracking import split_list_observation, unmapped_attributed, view_of


def test_list_value_is_split_into_items():
    o = dict(attribute="DX", raw_value="Diabetes mellitus type 2, Anemia", case_ref="사례1", subject="TARGET_PATIENT",
             evidence_spans=["Diabetes mellitus type 2, Anemia"])
    pieces = split_list_observation(o, "Diabetes mellitus type 2 and Anemia")
    assert [p["raw_value"] for p in pieces] == ["Diabetes mellitus type 2", "Anemia"]
    assert all(p["split_from"] == "Diabetes mellitus type 2, Anemia" for p in pieces)


def test_single_value_is_not_split():
    o = dict(attribute="DX", raw_value="Anemia", case_ref="사례1", subject="TARGET_PATIENT", evidence_spans=["Anemia"])
    assert split_list_observation(o, "Anemia") == [o]


def test_unmapped_attributed_item_is_blocked(nz):
    resp = "사례1의 환자는 Diabetes mellitus type 2와 zzzz-unknown-condition 진단을 받았습니다."
    obs = [dict(attribute="DX", raw_value="Diabetes mellitus type 2, zzzz-unknown-condition", case_ref="사례1",
                subject="TARGET_PATIENT", evidence_spans=["Diabetes mellitus type 2, zzzz-unknown-condition"])]
    v = view_of(obs, resp, "질문", nz)
    assert unmapped_attributed(v) is True


def test_unmapped_other_subject_is_not_blocked(nz):
    """값이 질문에 있는 질의 환자 정보(subject=OTHER)는 막지 않는다. (질문에 없으면 fix_subject가 TARGET_PATIENT로 고친다)"""
    query = "지금 환자는 zzzz-unknown-condition 이 있습니다."
    resp = "사례1의 환자는 zzzz-unknown-condition 진단을 받았습니다."
    obs = [dict(attribute="DX", raw_value="zzzz-unknown-condition", case_ref="사례1", subject="OTHER",
                evidence_spans=["zzzz-unknown-condition"])]
    v = view_of(obs, resp, query, nz)
    assert unmapped_attributed(v) is False


class _FakeNz:
    """전체 값의 정규화 결과만 정해 주는 가짜 정규화기 (실제 온톨로지에 의존하지 않는 단위 테스트용)."""

    def __init__(self, whole_status):
        self.whole_status = whole_status

    def normalize(self, obs, response, query):
        return {"mapping_status": self.whole_status}


def test_modifier_piece_is_merged_back_into_previous_item():
    from medical.tracking import merge_modifier_pieces
    pieces = [dict(raw_value="Acute pharyngitis", evidence_spans=[]), dict(raw_value="unspecified", evidence_spans=[])]
    out = merge_modifier_pieces(pieces, "Acute pharyngitis, unspecified")
    assert [p["raw_value"] for p in out] == ["Acute pharyngitis, unspecified"]
    assert out[0]["evidence_spans"] == ["Acute pharyngitis, unspecified"]


def test_mapped_whole_value_is_not_split():
    from medical.tracking import split_if_unmapped
    o = dict(attribute="DX", raw_value="Anemia, unspecified", case_ref="사례1", subject="TARGET_PATIENT",
             evidence_spans=["Anemia, unspecified"])
    assert split_if_unmapped(o, "Anemia, unspecified", "질문", _FakeNz("MAPPED")) == [o]


def test_unmapped_whole_value_is_split_and_modifier_merged():
    from medical.tracking import split_if_unmapped
    resp = "Acute pharyngitis, unspecified"
    o = dict(attribute="DX", raw_value="Acute pharyngitis, unspecified", case_ref="사례1",
             subject="TARGET_PATIENT", evidence_spans=[resp])
    out = split_if_unmapped(o, resp, "질문", _FakeNz("UNMAPPED"))
    assert [p["raw_value"] for p in out] == ["Acute pharyngitis, unspecified"]
