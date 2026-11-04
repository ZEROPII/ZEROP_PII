# 가상 EMR API: FHIR R4 읽기 전용 (/fhir) · EMR 외래 진료 목록 (/api/emr/worklist)
#
# 의료진 계정만 쓴다 (auth.ROUTE_ROLES). 공개하는 환자는 외래(QUERY_POOL) 코호트뿐이다.
# 유사 사례 검색 대상인 과거 기록(STORE) 환자는 FHIR로 열 수 없다: 그 기록은 진료 지원 AI 답을 거쳐서만,
# MediCloak 방어(누적 State Defender)를 지난 값으로만 보여야 하기 때문이다. 과거 기록 환자 id로 부르면 404다.
#
# 외래 목록 한 줄 = 환자 한 명. 진료 목적(처방 · 시술·치료 · 경과·관리)마다 연구 계획(engine.plan)의 trial이 있고,
# 의료진이 목적을 골라 '진료 지원 AI 열기'를 누르면 그 trial로 새 대화를 시작한다 (/api/emr/launch, app.py).

from __future__ import annotations

import collections
import random
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from medical.data import QUERY_POOL
from medical.retrieval import PANEL_LABEL, query_binding
from webdemo.backend.emr import CAPABILITY, FHIR_TYPE, Emr, FhirNotFound
from webdemo.backend.engine import QTYPE_KO, Engine

FHIR_JSON = "application/fhir+json"
RESOURCE_TYPES = sorted(set(FHIR_TYPE.values()))
FEATURED = ("T0014", "T0010", "T0024", "T0036", "T0005", "T0016", "T0037", "T0001")


class OutpatientEmr(Emr):
    """의료진에게 여는 EMR: 외래 코호트만."""

    def patient_row(self, fhir_id: str):
        r = super().patient_row(fhir_id)
        if r["cohort"] != QUERY_POOL:
            raise FhirNotFound(fhir_id)
        return r


def _fhir(body: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status, media_type=FHIR_JSON)


def _outcome(status: int, text: str) -> JSONResponse:
    return _fhir(dict(resourceType="OperationOutcome", issue=[dict(severity="error", code="not-found" if status == 404 else "invalid",
                                                                   diagnostics=text)]), status)


def fhir_router(emr_of) -> APIRouter:
    """emr_of(): 요청 때 OutpatientEmr를 돌려주는 함수 (앱 lifespan에서 만든다)."""
    r = APIRouter(prefix="/fhir")

    @r.get("/metadata")
    def metadata() -> JSONResponse:
        return _fhir(CAPABILITY)

    @r.get("/Patient")
    def patients(_count: int = Query(50, ge=1, le=200), _offset: int = Query(0, ge=0)) -> JSONResponse:
        return _fhir(emr_of().patients("outpatient", _count, _offset))

    @r.get("/Patient/{pid}")
    def patient(pid: str) -> JSONResponse:
        try:
            return _fhir(emr_of().patient(pid))
        except FhirNotFound:
            return _outcome(404, f"외래 환자 목록에 없는 환자입니다: Patient/{pid}")

    @r.get("/{rtype}")
    def search(rtype: str, patient: str | None = None) -> JSONResponse:
        if rtype not in RESOURCE_TYPES:
            return _outcome(404, f"지원하지 않는 자원입니다: {rtype} (지원: Patient, {', '.join(RESOURCE_TYPES)})")
        if not patient:
            return _outcome(400, "patient 검색 조건이 필요합니다 (예: ?patient=<환자 id>).")
        try:
            return _fhir(emr_of().resources(rtype, patient.removeprefix("Patient/")))
        except FhirNotFound:
            return _outcome(404, f"외래 환자 목록에 없는 환자입니다: Patient/{patient}")

    return r


def worklist(eng: Engine, emr: OutpatientEmr) -> list[dict[str, Any]]:
    """외래 진료 목록: 연구 계획에 trial이 있는 외래 환자. 목적마다 진료일(index date) · 주진단 · 고려 중인 처치."""
    by_pid: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for tid, pid, qt, _ in eng.plan:
        b = query_binding(eng.data, pid, qt, random.Random(f"{eng.cfg.seed}-{tid}"))     # make_prefix와 같은 난수 → 같은 패널
        if b is None:
            continue
        panel = {lab: b["panel"][k] for k, lab in PANEL_LABEL}
        by_pid[pid].append(dict(trialId=tid, purpose=qt, purposeLabel=QTYPE_KO[qt], visitDate=b["index_date"], ageSex=panel.get("연령 / 성별"),
                                mainDx=panel.get("주진단"), item=panel.get("고려 중인 처치")))
    out = []
    for pid, purposes in by_pid.items():
        try:
            s = emr.summary(pid)
        except FhirNotFound:
            continue
        purposes.sort(key=lambda p: p["trialId"])
        out.append(dict(s, purposes=purposes, featured=any(p["trialId"] in FEATURED for p in purposes),
                        lastVisit=max(p["visitDate"] for p in purposes)))
    out.sort(key=lambda x: (not x["featured"], min(p["trialId"] for p in x["purposes"])))
    return out


def find_trial(eng: Engine, fhir_id: str, purpose: str) -> str:
    for tid, pid, qt, _ in eng.plan:
        if pid == fhir_id and qt == purpose:
            return tid
    raise HTTPException(404, "이 환자는 고른 진료 목적으로 진료 지원 AI를 열 수 없습니다.")
