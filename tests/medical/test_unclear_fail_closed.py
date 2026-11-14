"""사례 번호가 없는 민감 공개(UNCLEAR)는 검증·k 집계에서 빠지므로 릴리스를 막아야 한다.

현재 구현(tracking.py: case_refs/disclosures에서 UNCLEAR 제외)에서는 이 테스트가 실패해야 한다 (red).
구현: tracking.unattributed_sensitive(view) -> bool 을 추가하고, 세션 release 경로에서 True면 거절.
"""
import pytest

from medical.tracking import view_of


def test_unattributed_diagnosis_is_flagged(nz):
    from medical.tracking import unattributed_sensitive
    resp = "이 환자는 Diabetes mellitus type 2 진단을 받았습니다."
    obs = [dict(attribute="DX", raw_value="Diabetes mellitus type 2", evidence_spans=["Diabetes mellitus type 2"],
                case_ref="UNCLEAR", subject="TARGET_PATIENT")]
    v = view_of(obs, resp, "질문", nz)
    assert "UNCLEAR" not in v.disclosures          # 기존 계약: k 계산에서는 빠짐
    assert unattributed_sensitive(v) is True        # 새 계약: 검증 없이 내보내면 안 됨


def test_unattributed_general_advice_is_not_blocked(nz):
    """턴 0 일반 권고(subject=UNCLEAR, 귀속해도 MAPPED 안 됨)는 막지 않는다 (과잉 차단 방지)."""
    from medical.tracking import unattributed_sensitive
    resp = "일반적으로 정기적인 운동과 충분한 수면을 권장합니다."
    obs = [dict(attribute="PLAN", raw_value="정기적인 운동과 충분한 수면", evidence_spans=["정기적인 운동과 충분한 수면"],
                case_ref="UNCLEAR", subject="UNCLEAR")]
    v = view_of(obs, resp, "질문", nz)
    assert unattributed_sensitive(v) is False


def test_unattributed_other_subject_is_not_blocked(nz):
    """질의 환자 본인 정보(subject=OTHER)인 UNCLEAR는 막지 않는다."""
    from medical.tracking import unattributed_sensitive
    resp = "이 환자는 Diabetes mellitus type 2 진단을 받았습니다."
    obs = [dict(attribute="DX", raw_value="Diabetes mellitus type 2", evidence_spans=["Diabetes mellitus type 2"],
                case_ref="UNCLEAR", subject="OTHER")]
    v = view_of(obs, resp, "질문", nz)
    assert unattributed_sensitive(v) is False
