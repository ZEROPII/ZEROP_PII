"""[수정본] 방어가 넓히기로 고른 범주어는 미매핑 차단에서 빼고, 그 계획된 공개로 k를 센다."""
from medical.session import _add_planned
from medical.tracking import CaseView, is_planned_label, unmapped_attributed, view_of


class _UnmappedNz:
    """모든 값을 UNMAPPED로 돌려주는 가짜 정규화기 (범주어가 정규화되지 않는 경우를 재현)."""

    def normalize(self, obs, response, query):
        return dict(obs, mapping_status="UNMAPPED", commit=False)


def _view(disclosures, sources, unmapped=False):
    return CaseView(normalized={}, disclosures=disclosures, sources=sources, partial={}, order=list(disclosures),
                    unmapped_sensitive=unmapped)


def test_planned_label_matches_exact_and_marker_prefixed_forms():
    allowed = frozenset({("사례1", "대사질환 약물")})
    assert is_planned_label("대사질환 약물", "사례1", allowed)
    assert is_planned_label("(비공개) 등 대사질환 약물", "사례1", allowed)


def test_planned_label_rejects_other_case_extra_text_or_empty_allowed():
    allowed = frozenset({("사례1", "대사질환 약물")})
    assert not is_planned_label("대사질환 약물", "사례2", allowed)
    assert not is_planned_label("대사질환 약물 외 다수", "사례1", allowed)
    assert not is_planned_label("대사질환 약물", "사례1", frozenset())


def test_view_of_does_not_block_planned_label():
    nz = _UnmappedNz()
    obs = [dict(attribute="DX", raw_value="대사질환 약물", case_ref="사례1", subject="TARGET_PATIENT",
                evidence_spans=["대사질환 약물"])]
    resp = "사례1 환자는 대사질환 약물을 복용했습니다."
    assert unmapped_attributed(view_of(obs, resp, "질문", nz)) is True
    assert unmapped_attributed(view_of(obs, resp, "질문", nz, frozenset({("사례1", "대사질환 약물")}))) is False


def test_add_planned_adds_disclosure_once_when_label_is_in_text():
    dis = dict(attribute="DX", node_id="N_meta", event_group="사례1:g1")
    src = dict(attribute="DX", raw_value="당뇨", case_ref="사례1")
    v = _view({"사례1": []}, {"사례1": []})
    v = _add_planned(v, "사례1 환자는 대사질환 약물을 복용했습니다.", [("사례1", "대사질환 약물", dis, src)])
    assert v.disclosures["사례1"] == [dis]
    assert v.sources["사례1"][0]["raw_value"] == "대사질환 약물"
    v = _add_planned(v, "대사질환 약물", [("사례1", "대사질환 약물", dis, src)])
    assert len(v.disclosures["사례1"]) == 1


def test_add_planned_skips_when_label_absent_or_case_gone():
    dis = dict(attribute="DX", node_id="N_meta", event_group="사례1:g1")
    src = dict(attribute="DX", raw_value="당뇨", case_ref="사례1")
    v = _view({"사례1": []}, {"사례1": []})
    v = _add_planned(v, "라벨이 없는 답변", [("사례1", "대사질환 약물", dis, src)])
    assert v.disclosures["사례1"] == []
    v = _add_planned(v, "대사질환 약물", [("사례2", "대사질환 약물", dis, src)])
    assert "사례2" not in v.disclosures
