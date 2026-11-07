# 가상 EMR: Synthea 합성 환자 · 진료 사건 · 온톨로지 노드를 DB에 두고, FHIR R4 모양으로 읽게 한다.
#
#   load_csv()   data/medical의 노드표 · 사건연결표 → emr_node · emr_event, 환자 표(emr_patient)는 사건에서 만든다.
#                코호트(QUERY_POOL 외래 환자 · STORE 과거 기록)는 medical.data.split_cohort와 같은 규칙으로 나눈다.
#   export_csv() DB → 위험 계산 엔진(kcalc · 정규화 · MedicalData)이 읽는 CSV 스냅숏. 서버를 켤 때 DB가 바뀌었으면 다시 쓴다.
#                연구 하네스(medical/, 고정본 bundle)는 파일 경로로 읽으므로 고치지 않고 DB를 원본으로 쓸 수 있다.
#   FHIR         Patient · Condition · MedicationRequest · Procedure · CarePlan (읽기 전용, 이름 등 직접 식별자는 원래 없음)
#
# 외래 환자 목록(EMR 화면에서 진료 지원 AI를 여는 환자)은 QUERY_POOL, 유사 사례 검색 대상(과거 기록)은 STORE다.

from __future__ import annotations

import collections
import csv
import datetime as dt
import hashlib
import re
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from medical.config import MedicalConfig, MedicalPaths
from medical.data import QUERY_POOL, split_cohort
from webdemo.backend.store import Store

NODE_COLS = ["node_id", "attribute", "canonical_label", "parent_id", "depth", "review_status", "standard_code", "time_role",
             "calendar_basis", "level", "k_patients"]
EVENT_COLS = ["event_id", "patient_id", "event_type", "encounter_id", "code", "code_node", "start", "stop", "time_basis",
              "period_start_node", "period_end_node", "age_years_at_start", "age_node", "sex_node", "region_node", "code_nodes",
              "map_trace", "record_date", "context"]

FHIR_TYPE = dict(CONDITION="Condition", MEDICATION="MedicationRequest", PROCEDURE="Procedure", PROCEDURE_HISTORY="Procedure",
                 CAREPLAN="CarePlan")
CODE_SYSTEM = dict(CONDITION="http://snomed.info/sct", PROCEDURE="http://snomed.info/sct", PROCEDURE_HISTORY="http://snomed.info/sct",
                   CAREPLAN="http://snomed.info/sct", MEDICATION="http://www.nlm.nih.gov/research/umls/rxnorm")
SEX_FHIR = dict(SEX_MALE="male", SEX_FEMALE="female")


def _read(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _digest(*paths: Path) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(Path(p).read_bytes())
    return h.hexdigest()[:16]


def is_loaded(store: Store) -> bool:
    return store.get_meta("emr_version") is not None


def load_csv(store: Store, paths: MedicalPaths | None = None, cfg: MedicalConfig | None = None, log=print) -> dict[str, int]:
    """CSV 원자료를 DB로 옮긴다 (이미 있으면 지우고 다시). 반환: 표별 행 수."""
    paths = paths or MedicalPaths()
    cfg = cfg or MedicalConfig()
    t0 = time.time()
    nodes = _read(paths.nodes)
    events = _read(paths.events)
    with store.lock:
        for t in ("emr_node", "emr_event", "emr_patient"):
            store.conn.execute(f"DELETE FROM {t}")
    store.many(f"INSERT INTO emr_node ({', '.join(NODE_COLS)}, seq) VALUES ({', '.join('?' for _ in NODE_COLS)}, ?)",
               ([n.get(c, "") for c in NODE_COLS] + [i] for i, n in enumerate(nodes)))
    store.many(f"INSERT INTO emr_event ({', '.join(EVENT_COLS)}, seq) VALUES ({', '.join('?' for _ in EVENT_COLS)}, ?)",
               ([e.get(c, "") for c in EVENT_COLS] + [i] for i, e in enumerate(events)))
    by_pat: dict[str, list[dict[str, str]]] = collections.defaultdict(list)
    for e in events:
        by_pat[e["patient_id"]].append(e)
    split = split_cohort(SimpleNamespace(patients=lambda: sorted(by_pat)), cfg.query_pool_ratio, cfg.seed)
    rows = []
    for pid, es in by_pat.items():
        sex = collections.Counter(e["sex_node"] for e in es if e["sex_node"]).most_common(1)
        region = collections.Counter(e["region_node"] for e in es if e["region_node"]).most_common(1)
        births = collections.Counter(int(e["start"][:4]) - int(e["age_years_at_start"]) for e in es
                                     if e["start"][:4].isdigit() and e["age_years_at_start"].isdigit())
        rows.append((pid, pid, sex[0][0] if sex else None, region[0][0] if region else None,
                     births.most_common(1)[0][0] if births else None, split[pid], len(es)))
    store.many("INSERT INTO emr_patient (patient_id, fhir_id, sex_node, region_node, birth_year, cohort, n_events) VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    version = _digest(paths.nodes, paths.events)
    store.set_meta("emr_version", version)
    store.set_meta("emr_loaded_at", str(time.time()))
    store.set_meta("emr_source", f"{Path(paths.nodes).name}, {Path(paths.events).name}")
    counts = dict(emr_node=len(nodes), emr_event=len(events), emr_patient=len(rows))
    log(f"[medicloak] EMR 적재 {time.time() - t0:.1f}초: 노드 {len(nodes):,} · 사건 {len(events):,} · 환자 {len(rows):,}명")
    return counts


def export_csv(store: Store, out_dir: Path, log=print) -> MedicalPaths:
    """DB → kcalc · MedicalData가 읽는 CSV. DB 버전이 같으면 다시 쓰지 않는다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    version = store.get_meta("emr_version")
    if version is None:
        raise RuntimeError("EMR 데이터가 비어 있습니다. 먼저 python -m medicloak init 을 실행하세요.")
    nodes, events, marker = out_dir / "노드_db.csv", out_dir / "사건연결표_db.csv", out_dir / "VERSION"
    if not (marker.exists() and marker.read_text().strip() == version and nodes.exists() and events.exists()):
        t0 = time.time()
        for path, table, cols in ((nodes, "emr_node", NODE_COLS), (events, "emr_event", EVENT_COLS)):
            tmp = path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(cols)
                for r in store.q(f"SELECT {', '.join(cols)} FROM {table} ORDER BY seq"):
                    w.writerow([r[c] if r[c] is not None else "" for c in cols])
            tmp.replace(path)
        marker.write_text(version)
        log(f"[medicloak] 위험 계산용 스냅숏을 DB에서 내보냄 {time.time() - t0:.1f}초 ({out_dir})")
    base = MedicalPaths()
    return MedicalPaths(nodes=nodes, events=events, alias=base.alias, o1=base.o1, o2=base.o2, case_queries=base.case_queries)


# ── FHIR R4 (읽기 전용) ─────────────────────────────────────────

class FhirNotFound(KeyError):
    pass


#: 끝나지 않은 진단이 있어도 마지막 내원이 이보다 오래되면 '장기 미내원'으로 둔다 (진료 중 목록에 섞지 않는다)
DORMANT_YEARS = 3
STATUS_KO = {"ACTIVE": "진료 중", "RESOLVED": "완치", "DORMANT": "장기 미내원"}
#: 종료일이 없는 처방도 마지막 처방이 마지막 내원보다 이 날수 넘게 앞서면 '진행 중'으로 세지 않는다 (차트에 '종료일 없음'으로 따로)
MED_STALE_DAYS = 365
#: 급성 질환(감염 · 손상 · 급성 발작 등)은 종료일이 없어도 마지막 기록이 마지막 내원보다 이 날수 넘게 앞서면 '진행 중'으로 세지 않는다.
#: 만성 질환(당뇨 · 고혈압 · 만성 신장병 …)은 진단 기록이 한 번뿐이어도 종료일이 없으면 진행 중이다 (Synthea 기록 방식).
ACUTE_STALE_DAYS = 365
ACUTE = re.compile(r"\b(acute|sepsis|septic|urinary tract infection|pneumonia|otitis|pharyngitis|tonsillitis|bronchitis|influenza|covid|viral|"
                   r"streptococcal|cystitis|gastroenteritis|fracture|injury|sprain|strain|laceration|contusion|concussion|dislocation|burn|bite|"
                   r"poisoning|overdose|convulsions)\b", re.I)
KIND = dict(CONDITION="problems", MEDICATION="medications", PROCEDURE="procedures", PROCEDURE_HISTORY="procedures", CAREPLAN="carePlans")
KIND_ORDER = dict(problems=0, procedures=1, medications=2, carePlans=3)
#: 차트 '내원 이력'에 보내는 내원 수 · 하루 항목 수 (그보다 오래된 내원은 visitDates로 날짜만)
VISITS_MAX = 400
VISIT_ITEMS_MAX = 12


def days_before(day: str, n: int) -> str:
    """'YYYY-MM-DD'에서 n일 앞 (글자로 비교하려고 같은 꼴로)."""
    return (dt.date.fromisoformat(day[:10]) - dt.timedelta(days=n)).isoformat()


def care_status(open_items: int, last: str | None, latest: str | None) -> str:
    """
    외래 목록의 진료 상태 (last: 마지막 내원일, latest: 가상 EMR 전체의 마지막 기록일).
      RESOLVED 완치       진행 중인 진단 · 처방 · 관리 계획이 없다 (종료일이 있거나, 종료일 없는 오래된 처방 · 급성 질환뿐)
      DORMANT  장기 미내원 진행 중인 것이 있지만 마지막 내원이 EMR 마지막 기록일보다 DORMANT_YEARS년 넘게 앞선다
      ACTIVE   진료 중     진행 중인 것이 있고 최근 DORMANT_YEARS년 안에 내원했다
    날짜는 'YYYY-MM-DD' 글자로 비교한다 (기준일의 연도만 뺀다).
    """
    if not open_items:
        return "RESOLVED"
    if last and latest and last < f"{int(latest[:4]) - DORMANT_YEARS:04d}{latest[4:10]}":
        return "DORMANT"
    return "ACTIVE"


def _stale(kind: str, g: dict[str, Any], last_visit: str | None) -> bool:
    """종료일이 없어도 진행 중으로 세지 않는 것: 오래된 처방, 오래된 급성 질환."""
    if not last_visit or not g["last"]:
        return False
    if kind == "medications":
        return g["last"] < days_before(last_visit, MED_STALE_DAYS)
    if kind == "problems":
        return bool(ACUTE.search(g["label"])) and "chronic" not in g["label"].lower() and g["last"] < days_before(last_visit, ACUTE_STALE_DAYS)
    return False


class Emr:
    """DB 위의 가상 EMR. 라벨은 온톨로지 노드 이름을 쓴다."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self._labels: dict[str, str] = {}
        self._latest: str | None = None

    def latest_record(self) -> str:
        """가상 EMR 전체의 마지막 기록일 (합성 데이터를 만든 날). 진료 상태의 '최근'을 오늘이 아니라 이 날 기준으로 센다."""
        if self._latest is None:
            r = self.store.one("SELECT MAX(SUBSTR(start, 1, 10)) AS d FROM emr_event WHERE start <> ''")
            self._latest = (r["d"] if r else None) or ""
        return self._latest

    def label(self, node_id: str | None) -> str:
        if not node_id:
            return ""
        if node_id not in self._labels:
            r = self.store.one("SELECT canonical_label FROM emr_node WHERE node_id = ?", (node_id,))
            lab = r["canonical_label"] if r else node_id
            for tag in (" (disorder)", " (procedure)", " (regime/therapy)", " (record artifact)", " (finding)", " (situation)"):
                lab = lab.removesuffix(tag)
            self._labels[node_id] = lab
        return self._labels[node_id]

    def patient_row(self, fhir_id: str):
        r = self.store.one("SELECT * FROM emr_patient WHERE fhir_id = ?", (fhir_id,))
        if r is None:
            raise FhirNotFound(fhir_id)
        return r

    def patient(self, fhir_id: str) -> dict[str, Any]:
        return self._patient(self.patient_row(fhir_id))

    def _patient(self, r) -> dict[str, Any]:
        region = self.label(r["region_node"])
        city, _, state = region.partition(", ")
        res = dict(resourceType="Patient", id=r["fhir_id"],
                   identifier=[dict(system="urn:medicloak:synthea-patient", value=r["patient_id"][:8])],
                   gender=SEX_FHIR.get(r["sex_node"], "unknown"),
                   meta=dict(tag=[dict(system="urn:medicloak:cohort", code="outpatient" if r["cohort"] == QUERY_POOL else "record-store")]))
        if r["birth_year"]:
            res["birthDate"] = str(r["birth_year"])               # 연도만 (합성 원자료의 정확한 생일은 쓰지 않는다)
        if region:
            res["address"] = [dict(city=city or None, state=state or city, country="US")]
        return res

    def patients(self, cohort: str | None = "outpatient", count: int = 50, offset: int = 0) -> dict[str, Any]:
        where, args = "", []
        if cohort == "outpatient":
            where, args = " WHERE cohort = ?", [QUERY_POOL]
        elif cohort == "record-store":
            where, args = " WHERE cohort != ?", [QUERY_POOL]
        total = self.store.one(f"SELECT COUNT(*) AS n FROM emr_patient{where}", args)["n"]
        rows = self.store.q(f"SELECT * FROM emr_patient{where} ORDER BY patient_id LIMIT ? OFFSET ?", [*args, count, offset])
        return bundle([self._patient(r) for r in rows], total)

    def resources(self, rtype: str, fhir_id: str) -> dict[str, Any]:
        r = self.patient_row(fhir_id)
        kinds = [k for k, v in FHIR_TYPE.items() if v == rtype]
        if not kinds:
            raise FhirNotFound(rtype)
        rows = self.store.q(f"SELECT * FROM emr_event WHERE patient_id = ? AND event_type IN ({', '.join('?' for _ in kinds)}) ORDER BY start, seq",
                            [r["patient_id"], *kinds])
        return bundle([self._event(e, fhir_id) for e in rows], len(rows))

    def _event(self, e, fhir_id: str) -> dict[str, Any]:
        rtype = FHIR_TYPE[e["event_type"]]
        code = dict(coding=[dict(system=CODE_SYSTEM[e["event_type"]], code=e["code"], display=self.label(e["code_node"]))],
                    text=self.label(e["code_node"]))
        res: dict[str, Any] = dict(resourceType=rtype, id=e["event_id"], subject=dict(reference=f"Patient/{fhir_id}"))
        if e["encounter_id"]:
            res["encounter"] = dict(reference=f"Encounter/{e['encounter_id']}")
        start, stop = e["start"] or None, e["stop"] or None
        if rtype == "Condition":
            res.update(code=code, onsetDateTime=start, clinicalStatus=dict(text="resolved" if stop else "active"))
            if stop:
                res["abatementDateTime"] = stop
        elif rtype == "MedicationRequest":
            res.update(status="completed" if stop else "active", intent="order", medicationCodeableConcept=code, authoredOn=start)
        elif rtype == "Procedure":
            res.update(status="completed", code=code, performedPeriod=dict(start=start, end=stop))
        else:
            res.update(status="completed" if stop else "active", intent="plan", category=[code], period=dict(start=start, end=stop))
        return res

    def record(self, pid: str) -> dict[str, Any]:
        """
        한 환자의 기록을 차트 모양으로 묶는다: 종류마다 같은 이름을 한 줄로(횟수 · 처음 · 마지막 · 종료일), 진료(encounter)마다 내원.
        진행 중(active): 종료일 없는 기록이 있고 _stale이 아님. 종료일은 없지만 오래되어 진행 중으로 세지 않으면 noEnd.
        """
        rows = self.store.q("SELECT event_type, encounter_id, code_node, SUBSTR(start, 1, 10) AS d, SUBSTR(stop, 1, 10) AS e FROM emr_event "
                            "WHERE patient_id = ? ORDER BY start, seq", (pid,))
        groups: dict[str, dict[str, dict[str, Any]]] = collections.defaultdict(dict)
        visits: dict[str, dict[str, Any]] = {}
        seen: set[tuple[str, str]] = set()               # 이 환자 기록에 처음 나온 (종류, 이름): 그 내원에 '처음' 표시
        for e in rows:
            k = KIND.get(e["event_type"])
            if k is None:
                continue
            lab = self.label(e["code_node"]) or e["code_node"]
            g = groups[k].setdefault(lab, dict(label=lab, times=0, first=e["d"] or None, last=e["d"] or None, active=False, ended=None,
                                               noEnd=False, open=False))
            g["times"] += 1
            g["last"] = max(filter(None, (g["last"], e["d"])), default=None)
            if e["event_type"] in ("CONDITION", "MEDICATION", "CAREPLAN"):
                if e["e"]:
                    g["ended"] = max(filter(None, (g["ended"], e["e"])), default=None)
                else:
                    g["open"] = True
            enc = e["encounter_id"] or (f"day:{e['d']}" if e["d"] else None)
            if enc and e["d"]:
                v = visits.setdefault(enc, dict(date=e["d"], items=[]))
                v["date"] = min(v["date"], e["d"])
                first = (k, lab) not in seen
                seen.add((k, lab))
                old = next((x for x in v["items"] if x["kind"] == k and x["label"] == lab), None)
                if old is None:
                    v["items"].append(dict(kind=k, label=lab, first=first))
                elif first:
                    old["first"] = True
        days = sorted({v["date"] for v in visits.values()})
        last_visit = days[-1] if days else None
        # 같은 날 진료(encounter)가 여럿이면 한 번의 내원으로 합친다 (내원 수 = 내원한 날 수)
        by_day: dict[str, dict[str, Any]] = {}
        for v in sorted(visits.values(), key=lambda v: v["date"]):
            d = by_day.setdefault(v["date"], dict(date=v["date"], items=[]))
            for it in v["items"]:
                old = next((x for x in d["items"] if x["kind"] == it["kind"] and x["label"] == it["label"]), None)
                if old is None:
                    d["items"].append(dict(it))
                elif it["first"]:
                    old["first"] = True
        for k, gs in groups.items():
            for g in gs.values():
                is_open = g.pop("open")
                g["active"] = is_open and not _stale(k, g, last_visit)
                g["noEnd"] = is_open and not g["active"]
                if is_open:
                    g["ended"] = None                     # 종료일 없는 기록이 있으면 끝난 날을 보이지 않는다
        return dict(groups=groups, visits=visits, by_day=by_day, days=days, lastVisit=last_visit)

    def summary(self, fhir_id: str, rec: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        EMR 외래 목록 한 줄: 성별 · 대표 진단 · 진료 상태 · 마지막 내원일 (화면에서 진료할 환자를 고를 때).
        생년 · 거주 지역은 목록에 넣지 않는다 (환자를 고르는 데 필요 없다. FHIR Patient 자원에는 그대로 있다).
        진료 상태는 care_status: 진료 중 · 완치 · 장기 미내원. openItems는 차트의 '진행 중'(진단 · 처방 · 관리 계획) 수와 같다.
        lastRecord는 마지막 내원일이다 (진료 encounter의 첫날): 차트 내원 이력의 마지막 날과 같은 날을 보인다.
        ageYear: 나이(연령대)를 센 해 = 마지막 내원 해 (장기 미내원이면 화면이 '1998년 기준'처럼 같이 보인다).
        """
        r = self.patient_row(fhir_id)
        pid = r["patient_id"]
        rec = rec or self.record(pid)
        dx = self.store.q("SELECT code_node, COUNT(*) AS n FROM emr_event WHERE patient_id = ? AND event_type = 'CONDITION' "
                          "GROUP BY code_node ORDER BY n DESC, code_node LIMIT 3", (pid,))
        open_n = sum(g["active"] for k in ("problems", "medications", "carePlans") for g in rec["groups"].get(k, {}).values())
        last = rec["lastVisit"]
        status = care_status(open_n, last, self.latest_record())
        return dict(fhirId=r["fhir_id"], identifier=pid[:8], sex=SEX_FHIR.get(r["sex_node"], "unknown"),
                    conditions=[self.label(d["code_node"]) for d in dx], events=r["n_events"],
                    status=status, statusLabel=STATUS_KO[status], openItems=open_n, lastRecord=last,
                    ageYear=int(last[:4]) if last else None)

    def age_band(self, fhir_id: str) -> str | None:
        """
        마지막 내원 때 나이의 연령대 ('40대', '10세 미만'). 진료 지원 AI 목적이 없는 외래 환자의 목록 줄에 쓴다.
        진료 지원 AI의 환자 요약도 가장 최근 진료일 기준 나이라 같은 연령대가 된다. 장기 미내원이면 화면이 그 해를 같이 보인다 (ageYear).
        """
        r = self.patient_row(fhir_id)
        e = self.store.one("SELECT age_years_at_start AS a FROM emr_event WHERE patient_id = ? AND age_years_at_start <> '' "
                           "ORDER BY start DESC, seq DESC LIMIT 1", (r["patient_id"],))
        if e is None or not str(e["a"]).isdigit():
            return None
        age = int(e["a"])
        return "10세 미만" if age < 10 else f"{age // 10 * 10}대"

    def chart(self, fhir_id: str, *, limit: int = 10) -> dict[str, Any]:
        """
        차트 요약 (의료진 환자 화면 · 보안 담당자의 사유를 적은 열람). 같은 이름은 한 줄로 묶어 횟수 · 처음 · 마지막 날을 보인다.
          problems    진단 이력: 진행 중인 진단 먼저, 그다음 최근 것부터
          medications 처방: 진행 중인 처방 먼저 (종료일이 없어도 마지막 처방이 마지막 내원보다 1년 넘게 앞서면 '종료일 없음')
          procedures  시술 (과거 시술 기록 포함) · carePlans 관리 계획
          visits      내원: 날마다(같은 날 진료는 합침) 그날 기록된 진단 · 처방 · 시술 · 관리 계획, 최근 것부터 VISITS_MAX번까지.
                      항목마다 first(이 환자 기록에 처음 나온 이름: 새 진단 · 첫 시술 · 첫 처방). 하루 항목은 VISIT_ITEMS_MAX개까지, 넘으면 more
          yearly      해마다 내원한 날 수 (마지막 내원 해까지 최근 10년. 지금 화면은 visitDates로 센다, 예전 앞단 · 다른 도구용으로 둔다)
          visitDates  내원한 날 전체, 오래된 것부터 (내원 이력: 해마다 내원 수 · 달력 띠 · 지난 1년) · refDate 가상 EMR 기준일 (합성 데이터의 마지막 기록일)
        생년 · 거주 지역은 넣지 않는다 (목록 줄과 같다). 날짜는 EMR 기록 그대로 (자기 환자 차트).
        """
        pid = self.patient_row(fhir_id)["patient_id"]
        rec = self.record(pid)
        s = self.summary(fhir_id, rec)
        groups = rec["groups"]

        def ordered(k: str) -> dict[str, Any]:
            # 진행 중인 것 먼저, 그 안에서는 마지막 기록이 최근인 것부터 (정렬을 두 번: 뒤의 정렬이 앞의 순서를 지킨다)
            xs = sorted(groups.get(k, {}).values(), key=lambda g: g["last"] or "", reverse=True)
            xs = sorted(xs, key=lambda g: not g["active"])
            return dict(items=xs[:limit], total=len(xs), active=sum(g["active"] for g in xs), noEnd=sum(g["noEnd"] for g in xs))

        days = rec["days"]
        by_year = collections.Counter(d[:4] for d in days)
        last_y = int(days[-1][:4]) if days else 0
        # yearly는 마지막 내원 해까지 최근 10년만 (처음 기록이 더 늦으면 그 해부터)
        yearly = [dict(year=y, visits=by_year.get(str(y), 0)) for y in range(max(int(days[0][:4]), last_y - 9), last_y + 1)] if days else []
        recent = []
        for v in sorted(rec["by_day"].values(), key=lambda v: v["date"], reverse=True)[:VISITS_MAX]:
            items = sorted(v["items"], key=lambda x: (not x["first"], KIND_ORDER.get(x["kind"], 9)))     # 처음 나온 것 · 진단 먼저
            recent.append(dict(date=v["date"], items=items[:VISIT_ITEMS_MAX], more=max(0, len(items) - VISIT_ITEMS_MAX)))
        return dict(patient=dict(s, ageBand=self.age_band(fhir_id)), problems=ordered("problems"), medications=ordered("medications"),
                    procedures=ordered("procedures"), carePlans=ordered("carePlans"), visits=recent, yearly=yearly,
                    visitDays=len(days), firstRecord=days[0] if days else None, visitDates=days, refDate=self.latest_record() or None)


def bundle(resources: list[dict[str, Any]], total: int) -> dict[str, Any]:
    return dict(resourceType="Bundle", type="searchset", total=total, entry=[dict(resource=x, search=dict(mode="match")) for x in resources])


CAPABILITY = dict(
    resourceType="CapabilityStatement", status="active", kind="instance", fhirVersion="4.0.1", format=["json"],
    software=dict(name="MediCloak EMR 연동 (FHIR R4)"),
    rest=[dict(mode="server", resource=[dict(type=t, interaction=[dict(code="read" if t == "Patient" else "search-type")],
                                             searchParam=[dict(name="patient", type="reference")] if t != "Patient" else [])
                                        for t in ("Patient", "Condition", "MedicationRequest", "Procedure", "CarePlan")])],
)
