# 가상 EMR API: FHIR R4 읽기 전용 (/fhir) · EMR 외래 진료 목록 (/api/emr/worklist)
#
# 의료진 계정만 쓴다 (auth.ROUTE_ROLES). 공개하는 환자는 외래(QUERY_POOL) 코호트뿐이고, 운영 모드에서는 그중에서도
# 자기 담당 환자와 예외 열람 중인 환자만 열린다 (access.py, ADR-0034). 담당이 아닌 외래 환자는 403(forbidden)이다.
# 유사 사례 검색 대상인 과거 기록(STORE) 환자는 FHIR로 열 수 없다: 그 기록은 진료 지원 AI 답을 거쳐서만,
# MediCloak 방어(누적 State Defender)를 지난 값으로만 보여야 하기 때문이다. 과거 기록 환자 id로 부르면 404다.
#
# 외래 목록 한 줄 = 환자 한 명. 진료 목적(처방 · 시술·치료 · 경과·관리)마다 연구 계획(engine.plan)의 trial이 있고,
# 의료진이 목적을 골라 '진료 지원 AI 열기'를 누르면 그 trial로 새 대화를 시작한다 (/api/emr/launch, app.py).

from __future__ import annotations

import collections
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from medical.data import QUERY_POOL
from medical.retrieval import PANEL_LABEL
from webdemo.backend.access import NotAssigned
from webdemo.backend.emr import CAPABILITY, FHIR_TYPE, Emr, FhirNotFound, bundle
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

    def patients_in(self, allowed: set[str], count: int = 50, offset: int = 0) -> dict[str, Any]:
        """allowed(담당 · 예외 열람) 안의 외래 환자만."""
        ids = sorted(allowed)
        rows = [r for r in (self.store.one("SELECT * FROM emr_patient WHERE fhir_id = ? AND cohort = ?", (f, QUERY_POOL)) for f in ids) if r is not None]
        rows.sort(key=lambda r: r["patient_id"])
        return bundle([self._patient(r) for r in rows[offset:offset + count]], len(rows))


def _fhir(body: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status, media_type=FHIR_JSON)


def _outcome(status: int, text: str) -> JSONResponse:
    code = {404: "not-found", 403: "forbidden"}.get(status, "invalid")
    return _fhir(dict(resourceType="OperationOutcome", issue=[dict(severity="error", code=code, diagnostics=text)]), status)


def fhir_router(emr_of, guard: Any = None) -> APIRouter:
    """
    emr_of(): 요청 때 OutpatientEmr를 돌려주는 함수 (앱 lifespan에서 만든다).
    guard: 운영 모드의 담당 검사. guard.scope(request) → 열 수 있는 환자 id 집합(None이면 제한 없음),
           guard.check(request, fhir_id, what) → (담당 · 예외 열람, 열람). 열 수 없으면 NotAssigned (감사 기록은 guard가 남긴다).
    """
    r = APIRouter(prefix="/fhir")

    @r.get("/metadata")
    def metadata() -> JSONResponse:
        return _fhir(CAPABILITY)

    @r.get("/Patient")
    def patients(request: Request, _count: int = Query(50, ge=1, le=200), _offset: int = Query(0, ge=0)) -> JSONResponse:
        allowed = guard.scope(request) if guard is not None else None
        if allowed is None:
            return _fhir(emr_of().patients("outpatient", _count, _offset))
        return _fhir(emr_of().patients_in(allowed, _count, _offset))

    @r.get("/Patient/{pid}")
    def patient(pid: str, request: Request) -> JSONResponse:
        try:
            emr_of().patient_row(pid)
            via = guard.check(request, pid, "fhir") if guard is not None else None
            res = emr_of().patient(pid)
        except FhirNotFound:
            return _outcome(404, f"외래 환자 목록에 없는 환자입니다: Patient/{pid}")
        except NotAssigned as exc:
            return _outcome(403, str(exc))
        if via and via[0] in ("break_glass", "consult"):
            # 예외 열람 · 협진 의뢰 열람은 차트 요약까지만: 생년 · 거주 지역은 담당 환자에게만 보인다
            res.pop("birthDate", None)
            res.pop("address", None)
        return _fhir(res)

    @r.get("/{rtype}")
    def search(rtype: str, request: Request, patient: str | None = None) -> JSONResponse:
        if rtype not in RESOURCE_TYPES:
            return _outcome(404, f"지원하지 않는 자원입니다: {rtype} (지원: Patient, {', '.join(RESOURCE_TYPES)})")
        if not patient:
            return _outcome(400, "patient 검색 조건이 필요합니다 (예: ?patient=<환자 id>).")
        pid = patient.removeprefix("Patient/")
        try:
            emr_of().patient_row(pid)                       # 외래 환자가 아니면 404 (담당 검사보다 먼저)
            if guard is not None:
                guard.check(request, pid, "fhir")
            out = emr_of().resources(rtype, pid)
        except FhirNotFound:
            return _outcome(404, f"외래 환자 목록에 없는 환자입니다: Patient/{patient}")
        except NotAssigned as exc:
            return _outcome(403, str(exc))
        return _fhir(out)

    return r


def worklist(eng: Engine, emr: OutpatientEmr) -> list[dict[str, Any]]:
    """
    외래 진료 목록 (모든 외래 환자, 의료진마다 담당 · 예외 열람으로 거르는 것은 app.py). 진료 지원 AI 목적(연구 계획의 trial)마다
    진료일(index date) · 주진단 · 고려 중인 처치 · 그날 이어지던 동반질환. trial이 없는 외래 환자도 목적 없이 넣는다 (차트는 볼 수 있다).
    유사 사례 검색 대상(과거 기록 환자 461명)과는 다른 환자들이다 (cohort QUERY_POOL만, OutpatientEmr).
    """
    by_pid: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for tid, pid, qt, _ in eng.plan:
        b = eng.binding(tid)          # 대화가 쓸 진료 기준과 같다 (운영 모드: 가장 최근 진료, visit.py)
        if b is None:
            continue
        panel = {lab: b["panel"][k] for k, lab in PANEL_LABEL}
        by_pid[pid].append(dict(trialId=tid, purpose=qt, purposeLabel=QTYPE_KO[qt], visitDate=b["index_date"], band=b["QUERY_AGE_BAND"],
                                mainDx=panel.get("주진단"), item=panel.get("고려 중인 처치"),
                                comorbidity=None if panel.get("동반질환") in (None, "없음") else panel.get("동반질환")))
    out = []
    for pid, purposes in by_pid.items():
        try:
            s = emr.summary(pid)
        except FhirNotFound:
            continue
        purposes.sort(key=lambda p: p["trialId"])
        # 나이는 진료 중 환자 띠와 같은 연령대('40대', '10세 미만')로만. 정확한 나이 · 생년은 목록 응답에 넣지 않는다
        band = max(purposes, key=lambda p: p["visitDate"])["band"]
        for p in purposes:
            del p["band"]
        out.append(dict(s, purposes=purposes, featured=any(p["trialId"] in FEATURED for p in purposes), ageBand=band))
    for r in emr.store.q("SELECT fhir_id FROM emr_patient WHERE cohort = ? ORDER BY fhir_id", (QUERY_POOL,)):
        if r["fhir_id"] not in by_pid:
            out.append(dict(emr.summary(r["fhir_id"]), purposes=[], featured=False, ageBand=emr.age_band(r["fhir_id"])))
    order = {"ACTIVE": 0, "RESOLVED": 1, "DORMANT": 2}
    out.sort(key=lambda x: (order.get(x["status"], 3), not x["featured"], min((p["trialId"] for p in x["purposes"]), default="T~"), x["fhirId"]))
    return out


def find_trial(eng: Engine, fhir_id: str, purpose: str) -> str:
    for tid, pid, qt, _ in eng.plan:
        if pid == fhir_id and qt == purpose:
            return tid
    raise HTTPException(404, "이 환자는 고른 진료 목적으로 진료 지원 AI를 열 수 없습니다.")
