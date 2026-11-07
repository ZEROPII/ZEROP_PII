# 의료진 화면(frontend/ 진료 지원 AI) 계약을 엔진 위에서 구현한다.
#
# 경로와 응답 모양은 frontend/src/api/httpApi.ts · api_server/와 같다 (접두사 /api).
#   ClinicConversation : 의료진 대화 하나 = 엔진 Session 하나 (세 조건 C0 · C1 · C1S를 같은 질문으로 나란히 진행).
#                        의료진 화면은 C1(누적 State Defender)만 본다. C0 · C1S와 원 응답은 관제 화면에서만 보인다.
#   ArchivedConversation : DB에 남은 지난 대화 (서버를 다시 켠 뒤). 읽기만 한다.
#   ClinicDesk         : 의료진 한 명의 진료 지원 AI. 지금 대화 하나와 그 전 대화들. 질문과 새 대화 시작을 한 번에 하나씩 받는다.
#   DeskRegistry       : 계정마다 ClinicDesk 하나 (데모 모드에서는 화면 하나가 쓰는 'demo' 하나).
#
# 대상 AI
#   oracle : 결정적 응답기. 질문 문장에서 묻는 단서를 찾아 Seed를 고른다 (intent.py). LLM 호출 0.
#   live   : 서버를 켤 때 정한 LLM (.env의 실제 모델 또는 배선 확인용 가짜). 의료진이 쓴 문장을 그대로 보낸다 (Session.ask_text).
#            턴 0 사례 검색 답과 '보내기 전 확인'은 언제나 결정적 응답기로 만든다 (호출 비용 0).
#
# 이 모듈의 응답에는 후보 수(k) · 기준값이 그대로 들어 있다. 의료진 화면 API는 redact.py를 거쳐 숫자를 지우고,
# 보안 담당자 '의료진 대화' API(/api/watch/{대화})는 그대로 보낸다.

from __future__ import annotations

import collections
import copy
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

from api_server.engine import segments_of
from medical.defense import ALLOW, GENERALIZE, SUPPRESS, SUPPRESSED_MARK as SUPPRESSED
from medical.retrieval import PANEL_LABEL, code_sets
from webdemo.backend import intent as I
from webdemo.backend.engine import ATTR_KO, QTYPE_KO, Engine, Session, parse_answer
from webdemo.backend.review import CASE_DROPPED, REFUSAL_TIMEOUT, ROUNDED, ref_no, same_text
from webdemo.backend.textguard import attribute_sentences, duration_mentions

ATTR_LABEL = dict(AGE="나이", SEX="성별", REGION="거주 지역", DX="진단", PROC="시술", PERIOD="시기", MED="처방 약", PLAN="관리 계획",
                  DURATION="기간")
DURATION_NOTE = "기간은 범위로만 보여 줍니다"
NOT_IN_FIRST = "첫 답에 나오지 않음"           # 사례 검색 첫 답이 이 사례를 말하지 않았다 (가린 것이 아니다)
RELEASE_PARTIAL_KO = "일부 공개 승인"           # 요청한 값 가운데 일부만 공개한 승인 메시지의 종류 이름 (의료진 화면 '일부 승인')
WAS_HIDDEN_KO = dict(suppress="가렸던 값", generalize="범위로 보였던 값", dropped="답에서 뺐던 값")
_CASE_LABEL = re.compile(r"사례\s*0*(\d+)(?!\d)")
_SENTENCE_END = re.compile(r"[.!?。](?=\s|$)|\n")
_PARA_BREAK = re.compile(r"\n[ \t]*\n")


def place_suppressed(text: str, segments: list[dict[str, Any]], tf: list[dict[str, Any]], own_ref: str, n_cases: int) -> list[dict[str, Any]]:
    """
    글에 남은 '(비공개)' 자리를 그 문장의 사례에 맞는 가림 조치에 다시 잇는다.
    segments_of는 '(비공개)'를 사례와 상관없이 가림 조치 순서대로 앞에서부터 잇는다. 값만 바꾼 답에서 사례 2의 약 자리가
    사례 1의 시기로 이름 붙고, 정작 사례 1에는 표시가 빠졌다 (2026-11-06 화면 확인). 사례 안에서는 조치 순서(답에 나온 순서)대로 잇는다.
    """
    by_id = {t["id"]: t for t in tf}
    slots: list[tuple[int, str]] = []
    sents = attribute_sentences(text, n_cases)
    pos = 0
    for i, seg in enumerate(segments):
        t = by_id.get(seg.get("transformationId") or "")
        if seg["kind"] == "disclosure" and seg["text"] == SUPPRESSED and t is not None and t["action"] == SUPPRESS:
            slots.append((i, _case_at(text, pos, sents) or own_ref))
        pos += len(seg["text"])
    if not slots:
        return segments
    order = [t["id"] for t in tf if t["action"] == SUPPRESS]
    used: set[str] = set()
    assign: dict[int, str] = {}
    for want_case in (True, False):                     # 먼저 같은 사례의 조치, 남으면 아무 가림 조치
        for i, ref in slots:
            if i in assign:
                continue
            tid = next((x for x in order if x not in used and (not want_case or by_id[x].get("caseRef") == ref)), None)
            if tid is not None:
                assign[i] = tid
                used.add(tid)
    return [dict(seg, transformationId=assign[i]) if i in assign else seg for i, seg in enumerate(segments)]


def _case_at(text: str, pos: int, sents: list[tuple[int, int, list[int], bool]]) -> str | None:
    """pos가 든 문장의 사례: 사례가 하나면 그것, 여럿이면 그 문장에서 pos 바로 앞에 나온 '사례N'."""
    for a, b, nums, _ in sents:
        if a <= pos < b:
            if len(nums) == 1:
                return f"사례{nums[0]}"
            before = [m for m in _CASE_LABEL.finditer(text, a, pos)]
            return f"사례{int(before[-1].group(1))}" if before else None
    return None


def mark_hidden(text: str, segments: list[dict[str, Any]], tf: list[dict[str, Any]], own_ref: str) -> list[dict[str, Any]]:
    """
    실제 LLM 답은 재작성기가 가린 값을 문장에서 지워, 글에 '(비공개)' 자리가 남지 않는다 (사례 노트에만 보였다).
    글에서 찾지 못한 '가림' 조치마다 그 사례 단락 끝(다음 사례가 시작하는 문장 앞, 없으면 그 사례가 나온 문단 끝)에 잠금 표시 조각을 넣는다.
    자리는 그 사례 마지막 줄의 글 끝이다: 뒤따르는 빈 줄 · 줄바꿈 앞으로 당겨 그 줄 안에 붙인다 (빈 줄에 혼자 떨어지면
    앞 줄의 꼬리표처럼 보였다, 의료진 체험 2026-11-05).
    조각에는 무엇을 가렸는지(단서 이름, 다른 사례면 사례 이름도)를 붙인다. 값은 넣지 않는다. 같은 답에 그 사례의 같은 단서가
    다른 값으로 보이면 partial(화면 '처방 약 일부 비공개')을 붙인다.
    사례째로 뺀 값은 뺀 사례 안내가 따로 있어 넣지 않는다. 내보낸 글 · 판정 · 후보 수는 그대로다 (화면 조각만 더한다).
    """
    matched = {s.get("transformationId") for s in segments if s.get("kind") == "disclosure"}
    want: dict[tuple[str, str], dict[str, Any]] = {}
    for x in tf:
        if x["action"] == SUPPRESS and x["id"] not in matched and not x.get("dropped") and x.get("caseRef"):
            want.setdefault((x["caseRef"], x["attribute"]), x)
    if not want:
        return segments
    labels = [(m.start(), f"사례{int(m.group(1))}") for m in _CASE_LABEL.finditer(text)]
    end_of_text = len(text.rstrip())
    shown = {(x["caseRef"], x["attribute"]) for x in tf if x["action"] != SUPPRESS and x.get("caseRef")}

    def block_end(ref: str) -> int:
        mine = [pos for pos, r in labels if r == ref]
        if not mine:
            return end_of_text
        nxt = next((pos for pos, r in labels if pos > mine[-1] and r != ref), None)
        if nxt is None:
            para = _PARA_BREAK.search(text, mine[-1])
            at = para.start() if para else end_of_text
        else:
            ends = [m.start() if m.group() == "\n" else m.end() for m in _SENTENCE_END.finditer(text, mine[-1], nxt)]
            at = ends[-1] if ends else nxt
        while at > mine[-1] and text[at - 1].isspace():
            at -= 1
        return at

    order = {a: i for i, a in enumerate(("DX", "PROC", "MED", "PLAN", "PERIOD", "AGE", "SEX", "REGION"))}
    inserts = sorted((block_end(ref), ref_no(ref), order.get(attr, 99), x) for (ref, attr), x in want.items())

    def marker(x: dict[str, Any]) -> dict[str, Any]:
        name = ATTR_LABEL.get(x["attribute"], x["attribute"])
        label = name if x["caseRef"] == own_ref else f"{x['caseRef'].replace('사례', '사례 ')} {name}"
        return dict(kind="disclosure", text=SUPPRESSED, transformationId=x["id"], placeholder=True, label=label,
                    partial=(x["caseRef"], x["attribute"]) in shown)

    out: list[dict[str, Any]] = []
    pos, k = 0, 0
    for seg in segments:
        start, end = pos, pos + len(seg["text"])
        if seg["kind"] == "text":
            cur = start
            while k < len(inserts) and inserts[k][0] <= end:
                at = max(inserts[k][0], cur)
                if at > cur:
                    out.append(dict(kind="text", text=seg["text"][cur - start: at - start]))
                    cur = at
                out.append(marker(inserts[k][3]))
                k += 1
            if cur < end:
                out.append(dict(kind="text", text=seg["text"][cur - start:]))
        else:
            out.append(seg)
        pos = end
    out += [marker(x[3]) for x in inserts[k:]]
    return out
TITLE_ATTRS = ("DX", "MED", "PROC", "PLAN")          # 사례 목록 제목에 쓰는 단서 (진단 + 관련 항목)
STATE_MODE_LABEL = dict(C0="방어 없음", C1="누적 판정 (대화 전체 기억)", C1S="턴별 판정 (매 턴 새로)")
DEMO_LOCATION = "MediCloak 데모 (Synthea 합성 환자)"
MAX_QUESTION = 1000                     # 의료진 질문 한 건의 최대 글자 수 (실제 LLM 호출 비용 · 지연 상한)
PREFLIGHT_LIMIT = 20                    # 보내기 전 확인: 대화마다 PREFLIGHT_WINDOW초 안에 판정을 알려 주는 횟수 (ADR-0032)
PREFLIGHT_WINDOW = 600.0
_REF = re.compile(r"사례(\d+)")



# ── 진료 목적별 예시 질문 (실제 LLM 대화) ─────────────────────────
# 연구용 질문 목록(나이 · 성별 · 거주 지역을 그대로 묻는 재식별 시험 문장)은 레드팀 · 데모 응답기에만 쓰고, 의료진 화면에는
# 조회 목적에 맞는 진료 질문을 보인다. '{ref}'는 고른 사례 표기(사례1)로 바꾼다.
CLINICAL_QUESTIONS: dict[str, list[tuple[str, str]]] = {
    "PRESCRIPTION": [
        ("처방 약", "{ref} 환자에게 처방된 약과 복용 기간을 알려 주세요."),
        ("함께 쓴 약", "{ref} 환자에게 같은 시기에 함께 처방된 약이 있었나요?"),
        ("처방 변경", "{ref} 환자가 처방을 바꾸거나 중단한 기록이 있나요?"),
        ("처방 이유", "{ref} 환자에게 그 약이 어떤 진단으로 처방되었나요?"),
    ],
    "TREATMENT_PROCEDURE": [
        ("시술 · 치료", "{ref} 환자는 어떤 시술이나 치료를 받았나요?"),
        ("시술 전후 약", "{ref} 환자가 시술 전후로 쓴 약이 있나요?"),
        ("시술 뒤 관리", "{ref} 환자의 시술 뒤 관리 계획은 무엇이었나요?"),
        ("관련 진단", "{ref} 환자가 그 시술을 받게 된 진단은 무엇인가요?"),
    ],
    "COURSE_CARE": [
        ("관리 계획", "{ref} 환자는 어떤 관리 계획을 받았나요?"),
        ("경과", "{ref} 환자의 진단이 이후 어떻게 바뀌었나요?"),
        ("다시 진료", "{ref} 환자가 같은 문제로 다시 진료받은 기록이 있나요?"),
        ("관리 중 약", "{ref} 환자가 관리 기간에 쓴 약을 알려 주세요."),
    ],
}
ALL_CASE_QUESTIONS: dict[str, list[tuple[str, str]]] = {
    "PRESCRIPTION": [("공통 처방", "찾은 사례들에서 공통으로 쓴 약과 사례마다 다른 약을 정리해 주세요.")],
    "TREATMENT_PROCEDURE": [("공통 시술", "찾은 사례들에서 공통으로 받은 시술과 사례마다 다른 점을 정리해 주세요.")],
    "COURSE_CARE": [("관리 비교", "찾은 사례들의 관리 계획을 비교해 공통점과 차이를 정리해 주세요.")],
}


def clinical_questions(qtype: str, ref: str) -> list[dict[str, Any]]:
    """조회 목적(qtype)에 맞는 진료 질문: 고른 사례 질문 넷 + 모든 사례 질문 하나."""
    one = [dict(label=label, question=text.format(ref=ref), scope="case") for label, text in CLINICAL_QUESTIONS.get(qtype, CLINICAL_QUESTIONS["PRESCRIPTION"])]
    every = [dict(label=label, question=text, scope="all") for label, text in ALL_CASE_QUESTIONS.get(qtype, ALL_CASE_QUESTIONS["PRESCRIPTION"])]
    return one + every

class NotFound(KeyError):
    pass


class Conflict(ValueError):
    pass


def _iso(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts or time.time(), timezone.utc).isoformat()


class Slot:
    def __init__(self, n: int) -> None:
        self.number = n
        self.case_id = f"case-{n}"
        self.ref = f"사례{n}"
        self.label = f"사례 {n}"
        self.messages: list[dict[str, Any]] = []
        self.questions = 0
        self.history: list[dict[str, Any]] = []
        self.decisions: list[dict[str, Any]] = []
        self.last_action = ALLOW


CHECK_MODE_KO = dict(REWRITTEN="재작성기가 고친 답", REWRITTEN_FALLBACK="값만 글자 그대로 바꾼 답", CASE_DROPPED="통과하지 못한 사례를 뺀 답",
                     ROUNDED="나이 · 날짜를 공개 단위로만 바꾼 답")


def _checks(rec: dict[str, Any]) -> list[dict[str, Any]]:
    """고친 답을 다시 뽑아 확인한 기록 (보안 담당자 화면). 시도마다: 어떤 방식 · 통과 여부 · 사례별 후보 수와 필요한 수 · 규칙 위반 ·
    원래 값이 글자 그대로 남음(RAW_VALUE_LEFT) · 사례 표기를 찾지 못함(NO_CASE_FOUND)."""
    out = []
    for i, a in enumerate(rec.get("release_attempts") or [], 1):
        cases = [dict(case=c.get("ref"), kAfter=c.get("k_after"), need=c.get("need"), rule=c.get("rule"), reason=c.get("reason"), ok=c.get("ok"),
                      attributeLabel=ATTR_LABEL.get(c["attribute"], c["attribute"]) if c.get("attribute") else None)
                 for c in a.get("checks") or []]
        out.append(dict(attempt=i, mode=a["mode"], modeLabel=CHECK_MODE_KO.get(a["mode"], a["mode"]), ok=bool(a["ok"]), cases=cases,
                        dropped=a.get("dropped")))
    return out


def _messages_view(raw: list[dict[str, Any]], case_of_ref: Callable[[str], str | None], label_of: Callable[[str], str]) -> list[dict[str, Any]]:
    out = []
    for m in raw:
        cid = case_of_ref(m["case"]) if m.get("case") else None
        out.append(dict(messageId=m["id"], createdAt=_iso(m["at"]), sender=m["sender"], kind=m["kind"], kindLabel=m["kind_label"],
                        caseId=cid, caseLabel=label_of(cid) if cid else None, text=m["text"],
                        partial=m["kind"] == "release" and m.get("kind_label") == RELEASE_PARTIAL_KO))
    return out


class ClinicConversation:
    """의료진 대화 하나. 화면의 사례 탭은 대상 AI의 '사례N' 표기와 1:1이다."""

    archived = False

    def __init__(self, eng: Engine, session: Session, arm: str = "C1", *, compare: bool = True,
                 location_label: str = DEMO_LOCATION) -> None:
        self.eng, self.session, self.arm, self.compare = eng, session, arm, compare
        self.location_label = location_label
        self.id = session.id
        self._seq = 0
        self.workspace_id = f"ws-{session.id}"
        self.version = 1
        self.updated_at = _iso()
        self.saved_turns: set[tuple[str, int]] = set()          # DB에 이미 넣은 턴 기록 (persist.py)
        self._preflights: collections.deque = collections.deque()    # 보내기 전 확인 시각 (사용 한도, ADR-0032)
        self.preflight_limited = 0                              # 한도를 넘겨 판정 없이 돌려준 수
        self.save_lock = threading.Lock()                       # 저장 한 번(스냅숏 만들기 + DB 쓰기)을 대화마다 줄 세운다
        self.slots = {f"case-{i}": Slot(i) for i in range(1, len(session.prefix.docs) + 1)}
        rec0 = self._records()[0]
        self.titles: dict[str, dict[str, str]] = collections.defaultdict(dict)
        for ln in parse_answer(rec0["response_text"]):
            if "case" in ln:
                self.titles[ln["case"]][ln["attribute"]] = ln["value"]
        self._absorb(rec0, None)
        if not self.titles:
            # 실제 LLM의 첫 답은 '사례1 · [기록5] 진단: …' 줄 형식이 아니다. 사례 목록 제목은 턴 0 공개 판정에서 만든다 (가린 값은 '(비공개)').
            for sl in self.slots.values():
                for e in sl.history:
                    if e["attribute"] in TITLE_ATTRS and e["attribute"] not in self.titles[sl.ref]:
                        self.titles[sl.ref][e["attribute"]] = e["value"] or SUPPRESSED

    @property
    def live(self) -> bool:
        return self.session.llm_mode == "live"

    def _id(self, p: str) -> str:
        self._seq += 1
        return f"{p}-{self._seq}"

    def _records(self) -> list[dict[str, Any]]:
        return [r for r in self.session.logs[self.arm] if r.get("turn") is not None]

    def slot(self, case_id: str) -> Slot:
        if case_id not in self.slots:
            raise NotFound(case_id)
        return self.slots[case_id]

    def session_id(self, case_id: str) -> str:
        return f"{self.workspace_id}:{case_id}"

    def _check(self, case_id: str, session_id: str) -> Slot:
        s = self.slot(case_id)
        if session_id != self.session_id(case_id):
            raise Conflict("대화가 바뀌었습니다. 화면을 새로 불러오세요.")
        return s

    def case_of_ref(self, ref: str) -> str | None:
        m = _REF.fullmatch(ref or "")
        cid = f"case-{int(m.group(1))}" if m else None
        return cid if cid in self.slots else None

    def ref_of(self, case_id: str) -> str:
        return self.slot(case_id).ref

    # ── k와 위험 표시 ──
    def k(self, case_id: str) -> int:
        """이 사례의 후보 수. 공개 원장을 켠 서버는 다른 대화에서 같은 과거 환자에 대해 나간 값까지 합쳐 센다 (ADR-0032)."""
        ref = self.slots[case_id].ref
        if self.arm == "C1" and getattr(self.session, "ledger", None) is not None:
            return self.session.k_global(ref)
        c = self.session.runs[self.arm].cases.get(ref)
        ctx = self.session.ctx
        return ctx.kc.k(c.committed)["k"] if c and c.committed else ctx.p_ref

    def risk_state(self, case_id: str) -> dict[str, Any]:
        s, d = self.slot(case_id), self.session.ctx.defender
        k = self.k(case_id)
        if k == 0:
            level, label = "blocked", "후보 일치 없음"
        elif k <= d.s:
            level, label = "danger", "위험"
        elif k <= d.g:
            level, label = "caution", "추가 공개 제한"
        else:
            level, label = "safe", "여유"
        restricted = self.arm == "C1" and d.risky(k)
        return dict(caseId=case_id, k=k, riskLevel=level, statusLabel=label, disclosureAllowed=not restricted,
                    policyDecision="restrict" if restricted else s.last_action, version=self.version, updatedAt=self.updated_at)

    def risk_states(self) -> list[dict[str, Any]]:
        with self.eng.lock:
            return [self.risk_state(cid) for cid in self.slots]

    # ── 화면 계약 ──
    def environment(self) -> dict[str, Any]:
        return dict(roleLabel="의료진", locationLabel=self.location_label)

    def policy(self) -> dict[str, Any]:
        d = self.session.ctx.defender
        mode = self.eng.live_label if self.live else "결정적 응답기 (LLM 없음)"
        return dict(modeLabel=mode, arm=self.arm, stateModeLabel=STATE_MODE_LABEL[self.arm], minK=d.g, suppressK=d.s,
                    populationSize=self.session.ctx.p_ref, source="backend", live=self.live)

    def patient_context(self) -> dict[str, Any]:
        b, data, p = self.session.prefix.binding, self.session.ctx.data, self.session.prefix
        main = b["main_dx_node"]
        if "active" in b:                       # 운영 모드 가장 최근 진료 기준(visit.py): 그날 이어지던 다른 진단
            others = list(b["active"])
        else:
            others = sorted({data.label(e["code_node"]) for e in data.by_pat[p.query_patient]
                             if e["event_type"] == "CONDITION" and (e["start"] or "")[:10] <= b["index_date"] and main not in data.anc(e["code_node"])})
        # AI에 실제로 보내는 환자 요약(대상 AI 지시문의 패널)과 유사 사례 검색에 쓰는 기록 범위. 화면의 'AI에 보내는 요약'을 펼치면 보인다
        sets = code_sets(data.by_pat[p.query_patient], b["index_date"])
        return dict(contextId=f"{self.workspace_id}:patient", ageSexLabel=f"{b['QUERY_AGE_BAND']} / {b['QUERY_SEX']}",
                    primaryDiagnosis=b["QUERY_MAIN_DX"], comorbidities=others, plannedProcedure=b["QUERY_RELATED_ITEM"],
                    queryPurpose=QTYPE_KO.get(p.query_type, p.query_type) + " 참고", source="backend", trialId=self.session.trial_id,
                    visitDate=b["index_date"], visitEvent=b.get("index_event"), visitChosen=b.get("visit") == "chosen",
                    aiSummary=[dict(label=lab, value=b["panel"][k]) for k, lab in PANEL_LABEL],
                    searchBasis=dict(until=b["index_date"], diagnoses=len(sets["DX"]), medications=len(sets["MED"]), procedures=len(sets["PROC"])))

    def similar_cases(self, context_id: str) -> list[dict[str, Any]]:
        if context_id != f"{self.workspace_id}:patient":
            raise NotFound(context_id)
        out = []
        approved: dict[str, list[str]] = collections.defaultdict(list)       # 보안 담당자가 승인해 공개한 단서 (사례 카드에 표시)
        for ap in getattr(self.session, "approvals", None) or []:
            for x in ap["items"]:
                approved[x["case"]].append(ATTR_LABEL.get(x["attribute"], x["attribute"]))
        for s, (_, score) in zip(self.slots.values(), self.session.prefix.retrieval):
            t = self.titles.get(s.ref, {})
            item = next(((ATTR_LABEL[a], t[a]) for a in ("MED", "PROC", "PLAN") if a in t), None)
            # 첫 답이 이 사례를 말하지 않았으면 가린 것이 아니므로 '비공개'라고 쓰지 않는다 (뒤 질문에서 나온 값으로 채운다)
            blank = not t
            out.append(dict(caseId=s.case_id, label=s.label, diagnosis=t.get("DX", NOT_IN_FIRST if blank else "진단 미확인"),
                            description=(f"{item[0]} {item[1]}" if item else "물으면 답에 나온 값이 여기에 채워집니다" if blank else "관련 항목 미확인"),
                            similarityRank=s.number, similarity=round(score, 3), mentioned=not blank,
                            approved=list(dict.fromkeys(approved.get(s.ref, [])))))
        return out

    def conversation(self, case_id: str) -> dict[str, Any]:
        s = self.slot(case_id)
        return dict(sessionId=self.session_id(case_id), caseId=case_id, messages=s.messages, questionCount=s.questions)

    def disclosures(self, case_id: str) -> dict[str, Any]:
        return dict(caseId=case_id, entries=self.slot(case_id).history)

    # ── 보안 담당자와 주고받은 메시지 (이 대화) ──
    def messages(self) -> list[dict[str, Any]]:
        with self.eng.lock:
            return _messages_view(self.session.messages, self.case_of_ref, lambda cid: self.slots[cid].label)

    def policy_decision(self, case_id: str) -> dict[str, Any]:
        s, d, data = self.slot(case_id), self.session.ctx.defender, self.session.ctx.data
        risk = self.risk_state(case_id)
        c = self.session.runs[self.arm].cases.get(s.ref)
        gen = [x for x in s.decisions if x["action"] == GENERALIZE]
        sup = [x for x in s.decisions if x["action"] == SUPPRESS]
        notes = [f"새로 나온 단서를 모두 더해도 후보가 {d.g}명보다 많으면 그대로 답합니다. 아니면 단서마다 원래 값으로 후보가 {d.s}명 이하이면 가리고, "
                 f"그 외에는 후보가 {d.g}명을 넘는 가장 가까운 상위 범주로 넓혀 답합니다.",
                 "후보 수는 사건 단위로 셉니다 (같은 진료 사건의 진단·나이·날짜를 한 사람이 함께 만족해야 후보).",
                 "사례마다 따로 셉니다. 한 사례에 나온 단서는 다른 사례의 후보 수에 더하지 않습니다."]
        if self.live:
            notes.append("대상 AI는 실제 LLM입니다. 공개된 답을 다시 추출해 확인한 값만 누적 State에 넣습니다.")
        if self.arm == "C1" and getattr(self.session, "ledger", None) is not None:
            notes.append("같은 과거 환자에 대해 다른 진료 대화(다른 의료진 포함)에서 이미 공개된 값까지 합쳐 셉니다.")
        if getattr(self.session, "gated", False):
            notes.append("대상 AI에는 이 기준으로 공개할 수 있는 값만 넣습니다. 그 밖의 값은 넓히거나 '(비공개)'로 바꿔 넣습니다.")
        return dict(caseId=case_id, currentK=risk["k"], minK=d.g, suppressK=d.s, arm=self.arm,
                    disclosedQis=[dict(attributeLabel=ATTR_LABEL.get(x["attribute"], x["attribute"]), levelDescription=data.label(x["node_id"]))
                                  for x in (c.committed if c else []) if x.get("node_id") in data.N],
                    generalized=[dict(attributeLabel=ATTR_LABEL.get(x["attribute"], x["attribute"]),
                                      levelDescription=f"'{data.label(x['to_node'])}'로 넓힘 (턴 {x['turn']})") for x in gen],
                    suppressed=[dict(attributeLabel=f"{ATTR_LABEL.get(x['attribute'], x['attribute'])} (턴 {x['turn']})") for x in sup],
                    finalDecision=risk["policyDecision"], finalDecisionLabel=risk["statusLabel"], notes=notes, stateVersion=risk["version"],
                    source="backend")

    # ── 보내기 전 확인 (결정적 응답기로 추정, State는 바꾸지 않음) ──
    def _seed_for(self, it: I.Intent):
        return I.candidates(self.session.ctx.seeds, it)[:14]

    def preflight(self, case_id: str, session_id: str, question: str, *, limit: bool = True) -> dict[str, Any]:
        """
        보내기 전 확인. limit=True(의료진 화면)이면 대화마다 PREFLIGHT_WINDOW초 안에 PREFLIGHT_LIMIT번까지만 판정을 미리 알려 준다.
        넘으면 판정 없이 limited=True만 돌려준다: 질문을 바꿔 가며 미리 세기로 드문 값을 찾는 것(후보 수 조회 도구)을 막는다 (ADR-0032).
        보안 담당자의 '질문 미리 세기'(limit=False)는 서버가 계정마다 따로 센다 (app.py).
        """
        with self.eng.lock:
            s = self._check(case_id, session_id)
            k_now = self.k(case_id)
            it = I.parse(question)
            focus = it.case or s.ref
            base = dict(caseId=case_id, question=question, requiresWarning=False, currentK=k_now, projectedK=None, message=None,
                        affectedAttributes=[], suggestions=[], source="backend", supported=True, plannedAction=None,
                        targetCaseId=None, targetCaseLabel=None, estimate="oracle" if self.live else None)
            if not it.understood:
                return dict(base, understood=False)
            if limit:
                now, dq = time.time(), self._preflights
                while dq and now - dq[0] > PREFLIGHT_WINDOW:
                    dq.popleft()
                if len(dq) >= PREFLIGHT_LIMIT:
                    self.preflight_limited += 1
                    return dict(base, understood=True, limited=True, currentK=None,
                                message="보내기 전 확인을 짧은 시간에 많이 써서 잠시 멈춥니다. 질문을 보내면 답을 받을 때 확인합니다.")
                dq.append(now)
            for seed in self._seed_for(it):
                pv = self.session.preview(seed["seed_id"], self.arm, focus, question)
                if not pv.get("applicable"):
                    continue
                mine = next((c for c in pv["cases"] if c["ref"] == focus), None) or (pv["cases"][0] if pv["cases"] else None)
                if mine is None:
                    return dict(base, understood=True)
                acts = mine.get("defender") or {}
                warn = bool(acts.get(SUPPRESS) or acts.get(GENERALIZE))
                label = mine["ref"].replace("사례", "사례 ")
                attrs = ", ".join(mine["attributes"]) or ATTR_KO.get(seed["target_qi"], seed["target_qi"])
                if acts.get(SUPPRESS):
                    msg = f"그대로 답하면 {label} 후보가 {mine['k_now']}명에서 {mine['k_if_raw']}명으로 줄어듭니다. 보내면 {attrs} 값은 가리고 답합니다."
                elif acts.get(GENERALIZE):
                    msg = f"그대로 답하면 {label} 후보가 {mine['k_now']}명에서 {mine['k_if_raw']}명으로 줄어듭니다. 보내면 {attrs} 값을 넓은 범주로 바꿔 답합니다."
                else:
                    msg = None
                # plannedAction: 보내면 어떻게 답할지 (의료진 화면은 후보 수 대신 이것만 보고 안내 문구를 만든다)
                planned = SUPPRESS if acts.get(SUPPRESS) else GENERALIZE if acts.get(GENERALIZE) else None
                # basis: 왜 그렇게 답하는지. count(후보 수, 실제 LLM은 미리 센 추정) · rule(보안 담당자 규칙) · purpose(조회 목적) — 뒤의 둘은 확정
                basis = "count" if planned else None
                ruled = {(r["case"], r["attribute"]) for r in getattr(self.session, "rules", [])} if self.arm == "C1" else set()
                if (mine["ref"], seed["target_qi"]) in ruled:
                    # 보안 담당자 규칙: 이 단서는 후보 수와 상관없이 가린다
                    planned, warn, basis = SUPPRESS, True, "rule"
                    msg = f"이 대화에서 {label}의 {ATTR_KO.get(seed['target_qi'], seed['target_qi'])}은(는) 보안 담당자 규칙으로 가리고 답합니다."
                # targetCase*: 질문이 가리킨 사례 (고른 탭이 사례 1이어도 '사례5 환자의 나이'면 사례 5)
                purpose = getattr(self.session.runs.get(self.arm), "purpose_blocked", frozenset())
                if seed["target_qi"] in purpose:
                    # 조회 목적에 필요 없는 단서: 후보 수와 관계없이 가린다
                    planned, warn, basis = SUPPRESS, True, "purpose"
                    msg = f"{ATTR_KO.get(seed['target_qi'], seed['target_qi'])}은(는) 이번 조회 목적에 필요하지 않아 답에서 뺍니다."
                alt = ([dict(label=x["label"], question=x["question"]) for x in clinical_questions(self.session.qtype, focus)][:2] if self.live else
                       [dict(label=f"{x['label']} 묻기", question=x["question"])
                        for x in self._ranked(focus, skip=(seed["target_qi"], "PERIOD", "AGE", "SEX", "REGION"))][:2])
                return dict(base, requiresWarning=warn, understood=True, currentK=mine["k_now"], projectedK=mine["k_if_raw"], message=msg,
                            affectedAttributes=mine["attributes"], plannedAction=planned, basis=basis,
                            targetCaseId=self.case_of_ref(mine["ref"]), targetCaseLabel=label,
                            suggestions=alt if warn else [])
            return dict(base, understood=True)

    def _ranked(self, ref: str, skip: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        """지금 이 사례에 물을 수 있는 질문을 단서 종류마다 하나씩 (한 사례 질문, 처음 묻기, 기본 문장 순)."""
        qs = self.session.questions(self.arm, ref)
        out, seen = [], set(skip)
        for q in sorted(qs, key=lambda q: (q["scope"] != "한 사례", q["objective"] != "처음 묻기", q["variant"] != "기본")):
            if q["target_qi"] in seen:
                continue
            seen.add(q["target_qi"])
            out.append(dict(label=q["target_label"], question=q["text"], target=q["target_qi"]))
        return out

    def suggestions(self, case_id: str) -> list[dict[str, Any]]:
        """
        예시 질문. 실제 LLM 대화는 조회 목적에 맞는 진료 질문(사례 하나 · 모든 사례)을, 데모(결정적 응답기)는 응답기가 알아듣는
        연구 질문 목록에서 단서 종류마다 하나씩 준다.
        """
        with self.eng.lock:
            s = self.slot(case_id)
            if self.live:
                return clinical_questions(self.session.qtype, s.ref)
            return [dict(label=x["label"], question=x["question"], scope="case") for x in self._ranked(s.ref)][:6]

    # ── 질문 ──
    def ask(self, case_id: str, session_id: str, question: str, client_message_id: str, scope: str = "case") -> dict[str, Any]:
        question = question.strip()
        if not question:
            raise ValueError("질문이 비어 있습니다.")
        if scope not in ("case", "all"):
            raise ValueError("질문 범위는 case(고른 사례) 또는 all(모든 사례)입니다.")
        if scope == "all" and not self.live:
            raise ValueError("모든 사례에 묻기는 실제 LLM 대화에서만 됩니다.")
        if len(question) > MAX_QUESTION:
            raise ValueError(f"질문은 {MAX_QUESTION}자 이하로 써 주세요.")
        with self.eng.lock:
            s = self._check(case_id, session_id)
            it = I.parse(question)
            k_before = {cid: self.k(cid) for cid in self.slots}
            rec = None
            if self.live:
                # 의료진 문장을 그대로 LLM에 보낸다. LLM 오류(LLMError)는 State를 바꾸기 전에 나므로 그대로 올린다.
                rec = self.session.ask_text(s.ref, question, self.arm, compare=self.compare, scope=scope)
            elif it.understood:
                focus = it.case or s.ref
                for seed in self._seed_for(it):
                    if self.session.ask(seed, focus, question, self.arm) is not None:
                        rec = self._records()[-1]
                        break
            self.version += 1
            self.updated_at = _iso()
            return self._reply(s, question, client_message_id, rec, k_before, it, scope)

    # ── 응답 만들기 ──
    @staticmethod
    def _released(rec: dict[str, Any]) -> dict[str, list[tuple[str, str, str]]]:
        """내보낸 답을 다시 뽑아 State에 들어간 단서 (사례마다 [(단서 종류, 노드, 답의 글자)]). 의료진이 실제로 본 값이다."""
        out: dict[str, list[tuple[str, str, str]]] = {}
        for ref, c in (rec.get("cases") or {}).items():
            if not isinstance(c, dict) or ref == "UNCLEAR":
                continue
            out[ref] = [(o["attribute"], o["node_id"], str(o.get("raw_value") or "")) for o in c.get("normalized") or []
                        if o.get("commit") and o.get("node_id")]
        return out

    def _absorb(self, rec: dict[str, Any], turn_for_entries: int | None) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        """
        한 턴 기록 → 화면 조치 목록(Defender 판정)과 사례별 공개 이력(사례 노트).
        공개 이력은 내보낸 답에 실제로 나온 값만 담는다: 허용 · 넓힘으로 정했어도 고친 답에서 빠졌으면 넣지 않고,
        값은 계획의 원래 글자가 아니라 답에 나온 글자(넓혔으면 넓힌 이름)로 적는다. 가린 값은 '비공개'로 남긴다.
        """
        data = self.session.ctx.data
        refusal = rec["release_mode"].startswith("REFUSAL")
        cand = rec.get("cases_candidate_k") or {}
        ruled = {(r["case"], r["attribute"]) for r in getattr(self.session, "rules", []) if r["from_turn"] <= rec["turn"]} if self.arm == "C1" else set()
        purpose = getattr(self.session.runs.get(self.arm), "purpose_blocked", frozenset())
        released = self._released(rec)
        used: set[tuple[str, str, str]] = set()
        turn = rec["turn"] if turn_for_entries is None else turn_for_entries
        tf, entries = [], {cid: [] for cid in self.slots}

        def shown(ref: str, attribute: str, node: str | None) -> tuple[str, str, str] | None:
            label = data.label(node) if node in data.N else None
            for o in released.get(ref, []):
                key = (ref, o[0], o[1])
                if key not in used and o[0] == attribute and (o[1] == node or (label and same_text(o[2], label))):
                    used.add(key)
                    return o
            return None

        for p in rec.get("release_plans") or []:
            cid = self.case_of_ref(p["ref"])
            for x in p["decisions"]:
                action = SUPPRESS if refusal else x["action"]
                to_label = data.label(x["to_node"]) if x.get("to_node") in data.N else None
                k_raw = x.get("k_raw") if x.get("k_raw") is not None else cand.get(p["ref"])
                floor = bool(x.get("floor")) and not refusal
                if action == GENERALIZE:
                    value, desc = to_label, (f"정해진 공개 단위로 바꿔 공개: {to_label}" if floor else
                                             f"민감한 값이라 넓은 범주로 바꿔 공개: {to_label}" if x.get("strict") and not refusal else
                                             f"넓은 범주로 바꿔 공개: {to_label}")
                elif action == SUPPRESS:
                    value = None
                    if refusal:
                        desc = "거절 문장으로 대체"
                    elif x.get("dropped"):
                        desc = "이 사례 내용을 답에서 뺌"
                    elif (p["ref"], x["attribute"]) in ruled:
                        desc = "보안 담당자 규칙으로 가림"
                    elif x["attribute"] in purpose:
                        desc = "조회 목적에 필요 없는 값이라 가림"
                    elif x.get("strict"):
                        desc = "민감한 값이라 더 엄격한 기준으로 가림"
                    else:
                        desc = f"가림 (그대로면 후보 {k_raw}명)" if k_raw is not None else "가림"
                else:
                    value, desc = str(x.get("raw_value") or to_label or ""), "그대로 공개"
                label = ATTR_LABEL.get(x["attribute"], x["attribute"])
                tf.append(dict(id=self._id("tf"), attribute=x["attribute"], attributeLabel=(f"{p['ref'].replace('사례', '사례 ')} {label}"),
                               action=action, disclosedValue=value, levelDescription=desc, caseRef=p["ref"], kIfRaw=k_raw,
                               rule=(p["ref"], x["attribute"]) in ruled and action == SUPPRESS and not refusal,
                               dropped=bool(x.get("dropped")) and not refusal, floor=floor,
                               purpose=x["attribute"] in purpose and action == SUPPRESS and not refusal and (p["ref"], x["attribute"]) not in ruled))
                if not cid:
                    continue
                self.slots[cid].decisions.append(dict(x, action=action, turn=turn))
                if action == SUPPRESS:
                    entries[cid].append(dict(entryId=self._id("dh"), turn=turn, attribute=x["attribute"], attributeLabel=label, action=action,
                                             description=desc, value=None))
                    continue
                o = shown(p["ref"], x["attribute"], x.get("to_node") or x.get("node_id"))
                if o is None:                      # 고친 답에서 빠져 의료진에게 나가지 않은 값
                    continue
                text = o[2] or value or ""
                entries[cid].append(dict(entryId=self._id("dh"), turn=turn, attribute=x["attribute"], attributeLabel=label, action=action,
                                         description=text if action == ALLOW else desc, value=text))
        # 계획에 없던 값이 내보낸 답에 나왔으면(재작성기가 남긴 반복 등) 의료진이 본 것이므로 노트에 넣는다
        for ref, obs in released.items():
            cid = self.case_of_ref(ref)
            if not cid:
                continue
            for attribute, node, text in obs:
                if (ref, attribute, node) in used or not text:
                    continue
                used.add((ref, attribute, node))
                entries[cid].append(dict(entryId=self._id("dh"), turn=turn, attribute=attribute, attributeLabel=ATTR_LABEL.get(attribute, attribute),
                                         action=ALLOW, description=text, value=text))
        # 기간: 후보 수 계산에 없는 값이라 판정 기록에 없다. 내보낸 글에 범위로 나온 것을 사례마다 노트에 남긴다 (textguard)
        if self.live and self.arm != "C0" and not refusal:
            for ref, phrase in duration_mentions(rec.get("response_text") or "", len(self.slots)):
                cid = self.case_of_ref(ref)
                tf.append(dict(id=self._id("tf"), attribute="DURATION", attributeLabel=f"{ref.replace('사례', '사례 ')} 기간", action=GENERALIZE,
                               disclosedValue=phrase, levelDescription=DURATION_NOTE, caseRef=ref, kIfRaw=None, rule=False, dropped=False,
                               floor=False, purpose=False, duration=True))
                if cid:
                    entries[cid].append(dict(entryId=self._id("dh"), turn=turn, attribute="DURATION", attributeLabel="기간", action=GENERALIZE,
                                             description=f"{phrase} ({DURATION_NOTE})", value=phrase))
        for cid, es in entries.items():
            sl = self.slots[cid]
            sl.history += es
            if es:
                acts = {e["action"] for e in es if e["attribute"] != "DURATION"}
                sl.last_action = SUPPRESS if SUPPRESS in acts else GENERALIZE if GENERALIZE in acts else ALLOW
        return tf, entries

    def _fill_titles(self, entries: dict[str, list[dict[str, Any]]]) -> None:
        """사례 목록 제목: 첫 답에 없던 진단 · 대표 항목이 뒤 답에 나오면 채운다 (사례 노트 · 공통 요약과 같은 값)."""
        for cid, es in entries.items():
            ref = self.slots[cid].ref
            for e in es:
                have = self.titles.get(ref, {})
                if e["attribute"] in TITLE_ATTRS and e["action"] != SUPPRESS and e.get("value") and e["attribute"] not in have:
                    self.titles[ref][e["attribute"]] = e["value"]

    def _reply(self, s: Slot, question: str, cmid: str, rec: dict[str, Any] | None, k_before: dict[str, int], it: I.Intent,
               scope: str = "case") -> dict[str, Any]:
        turn_no = s.questions + 1
        created = _iso()
        if rec is None:
            text = I.HELP_TEXT if not it.understood else "이 질문으로 더 알려 드릴 기록이 없습니다. 다른 항목을 물어보세요."
            tf, entries, mode = [], {cid: [] for cid in self.slots}, "NO_ANSWER"
            explanation = "답할 수 있는 항목을 찾지 못해 사례 기록을 공개하지 않았습니다."
            segments = [dict(kind="text", text=text)]
        else:
            tf, entries = self._absorb(rec, None)
            self._fill_titles(entries)
            mode, text = rec["release_mode"], rec["response_text"]
            explanation = self._explain(s, rec, tf, k_before)
            segments = ([dict(kind="text", text=text)] if mode.startswith("REFUSAL")
                        else mark_hidden(text, place_suppressed(text, segments_of(text, tf), tf, s.ref, len(self.slots)), tf, s.ref))
        acts = {t["action"] for t in tf if not t.get("duration")}
        decision = SUPPRESS if SUPPRESS in acts else GENERALIZE if GENERALIZE in acts else ALLOW
        k_after = self.k(s.case_id)
        protection = dict(decision=decision, transformations=tf, kBefore=k_before[s.case_id], kAfter=k_after, explanation=explanation,
                          releaseMode=mode, extractionOk=bool(rec["extraction_ok"]) if rec else True,
                          checks=_checks(rec) if rec else [])
        # engineTurn: 대화 전체의 턴 번호. 공개 이력(entries.turn)과 관제 화면이 이 번호를 쓰므로 의료진 화면이 질문과 이력을 잇는 데 쓴다.
        et = rec["turn"] if rec else None
        user = dict(messageId=cmid, caseId=s.case_id, role="user", turn=turn_no, createdAt=created, segments=[dict(kind="text", text=question)],
                    status="sent", engineTurn=et, scope=scope)
        asst = dict(messageId=self._id("msg"), caseId=s.case_id, role="assistant", turn=turn_no, createdAt=_iso(), segments=segments,
                    protection=protection, status="sent", engineTurn=et)
        s.messages += [user, asst]
        s.questions = turn_no
        related = [self.risk_state(cid) for cid in self.slots if cid != s.case_id and (entries[cid] or self.k(cid) != k_before[cid])]
        return dict(userMessage=user, assistantMessage=asst, riskState=self.risk_state(s.case_id), newDisclosures=entries[s.case_id],
                    relatedRiskStates=related)

    def _explain(self, s: Slot, rec: dict[str, Any], tf: list[dict[str, Any]], k_before: dict[str, int]) -> str:
        """화면이 후보 수(전→후)를 따로 보여 주므로 여기서는 무엇을 왜 했는지만 쓴다."""
        mode, g = rec["release_mode"], self.session.ctx.defender.g
        if mode == "REFUSAL_EXTRACTION_FAILED":
            return "답에서 단서를 확인하지 못해 위험을 판단할 수 없었습니다. 그래서 답 대신 거절 문장을 보냈습니다."
        if mode == REFUSAL_TIMEOUT:
            return ("정해진 시간 안에 고친 답을 안전하게 확인하지 못해 답 대신 거절 문장을 보냈습니다. "
                    "질문을 사례 하나씩 나누어 다시 물어보세요.")
        if mode.startswith("REFUSAL"):
            return "고친 답이 다시 확인을 통과하지 못해 거절 문장을 보냈습니다."
        extra = self._extra_notes(rec, s.ref)
        return (self._explain_main(rec, tf, mode, g) + extra).strip()

    def _extra_notes(self, rec: dict[str, Any], ref: str) -> str:
        """ADR-0032 설명 덧붙임: 내보낼 글에서 뺀 짐작 · 부재 진술, 다른 대화의 공개를 합쳐 판정한 것 (숫자 없음)."""
        kinds = {e.get("kind") for e in rec.get("post_edits") or []}
        out = []
        if "speculation" in kinds:
            out.append("기록에 없는 짐작 문장은 답에서 뺐습니다.")
        if kinds & {"absence", "exclusive"}:
            out.append("'…만 처방', '다른 기록 없음'처럼 환자를 좁힐 수 있는 표현은 답에서 뺐습니다.")
        if kinds & {"count", "interval"}:
            out.append("횟수 · 간격은 정해 둔 범위로만 보입니다.")
        if self.arm == "C1" and (rec.get("cases_global") or {}).get(ref) is not None:
            out.append("이 사례는 다른 진료 대화에서 이미 공개된 정보까지 합쳐 판단했습니다.")
        return (" " + " ".join(out)) if out else ""

    def _explain_main(self, rec: dict[str, Any], tf: list[dict[str, Any]], mode: str, g: int) -> str:
        if mode == CASE_DROPPED:
            dropped = sorted({t["caseRef"] for t in tf if t.get("dropped")}, key=ref_no)
            names = ", ".join(r.replace("사례", "사례 ") for r in dropped)
            rest = [t for t in tf if t["action"] != ALLOW and not t.get("dropped") and not t.get("duration")]
            tail = f" 다른 사례도 일부 값을 보호했습니다 ({len(rest)}건)." if rest else " 다른 사례는 그대로 답했습니다."
            return f"고친 답에서도 {names}의 내용으로 환자를 알아볼 수 있어, 그 사례 내용만 빼고 답했습니다.{tail}"
        if self.arm == "C0":
            return "방어 없이 원래 답을 그대로 보냈습니다."
        tail = f" {DURATION_NOTE}." if any(t.get("duration") for t in tf) else ""
        tf = [t for t in tf if not t.get("duration")]
        changed = [t for t in tf if t["action"] != ALLOW]
        if not tf:
            return ("이 답에는 새로 더해진 단서가 없습니다." + tail).strip()
        if not changed:
            return f"새로 나온 단서를 모두 더해도 후보가 {g}명보다 많아 그대로 답했습니다.{tail}"
        units = " 나이는 5세 구간, 날짜는 월 단위보다 자세히 보이지 않습니다."
        if mode == ROUNDED or all(t.get("floor") for t in changed):
            return "새로 나온 단서로 환자를 좁힐 위험은 없었고, 나이 · 날짜만 정해진 공개 단위로 바꿔 답했습니다." + units + tail
        cand = rec.get("cases_candidate_k") or {}
        worst = min((cand[t["caseRef"]] for t in changed if cand.get(t["caseRef"]) is not None), default=None)
        n_sup = sum(t["action"] == SUPPRESS for t in changed)
        n_gen = len(changed) - n_sup
        what = ", ".join(x for x in (f"가림 {n_sup}건" if n_sup else "", f"넓힘 {n_gen}건" if n_gen else "") if x)
        head = f"그대로 답하면 후보가 {worst}명까지 줄어들어 " if worst is not None else ""
        how = " 대상 AI의 답을 재작성기가 고친 뒤 다시 확인했습니다." if self.live and rec["release_mode"] == "REWRITTEN" else ""
        unit = units if any(t.get("floor") for t in changed) else ""
        return f"{head}일부 값을 보호해 답했습니다 ({what}).{how}{unit}{tail}"

    # ── 보안 담당자 검토 반영 (review.py) ──
    def apply_approval(self, ap: dict[str, Any], kept: list[dict[str, Any]] | None = None) -> str:
        """
        승인해 공개한 값을 사례 노트(공개 이력)와 사례 목록 카드에 더하고, 의료진에게 보낼 메시지 문장을 돌려준다.
        kept: 같은 요청에서 이번에 공개하지 않은 값과 그 까닭 · 대안 (assist.kept_items). 있으면 항목마다 결과를 나눠 적는다 (ADR-0031).
        """
        lines = []
        for x in ap["items"]:
            cid = self.case_of_ref(x["case"])
            label = ATTR_LABEL.get(x["attribute"], x["attribute"])
            where = "사례 검색 답" if x["turn"] == 0 else f"질문 {self._question_no(cid, x['turn'])}의 답"
            if cid:
                sl = self.slots[cid]
                sl.history.append(dict(entryId=self._id("dh"), turn=x["turn"], attribute=x["attribute"], attributeLabel=label, action=ALLOW,
                                       description=f"{x['value']} (보안 담당자 승인)", value=x["value"], approved=True))
                if x["attribute"] in TITLE_ATTRS:            # 사례 카드의 진단 · 대표 항목도 가림 · 범위 대신 승인한 값으로
                    self.titles[x["case"]][x["attribute"]] = x["value"]
            was = WAS_HIDDEN_KO.get(x.get("action") or "", "가렸던 값")
            lines.append(f"{x['case'].replace('사례', '사례 ')} {label}: {x['value']} ({where}에서 {was})")
        self.version += 1
        self.updated_at = _iso()
        if not kept:
            return "세부 정보 요청을 승인해 아래 값을 이 대화에서 공개합니다.\n" + "\n".join(lines)
        rest = [f"{k['case'].replace('사례', '사례 ')} {ATTR_LABEL.get(k['attribute'], k['attribute'])}: {k['reason']}"
                + (f" {k['alternative']}" if k.get("alternative") else "") for k in kept]
        return ("세부 정보 요청 가운데 일부를 승인했습니다.\n\n공개한 값\n" + "\n".join(f"· {ln}" for ln in lines)
                + "\n\n이번에 공개하지 않은 값\n" + "\n".join(f"· {ln}" for ln in rest))

    def _question_no(self, cid: str | None, engine_turn: int) -> int | str:
        if cid:
            for m in self.slots[cid].messages:
                if m["role"] == "user" and m.get("engineTurn") == engine_turn:
                    return m["turn"]
        return engine_turn

    def narrowing(self, case_id: str) -> dict[str, Any]:
        sl = self.slot(case_id)
        n = self.session.narrowing(self.arm, sl.ref)
        for x in n["steps"] + n["hidden"] + n["rules"]:
            x["attributeLabel"] = ATTR_LABEL.get(x["attribute"], x["attributeLabel"])
        return dict(n, caseId=case_id, label=sl.label)

    # ── DB 스냅숏 (서버를 다시 켠 뒤 읽기 전용으로 보여 줄 화면 계약 전체) ──
    def snapshot(self) -> dict[str, Any]:
        with self.eng.lock:
            per = {cid: dict(conversation=copy.deepcopy(self.conversation(cid)), disclosures=copy.deepcopy(self.disclosures(cid)),
                             decision=self.policy_decision(cid), risk=self.risk_state(cid), narrowing=self.narrowing(cid)) for cid in self.slots}
            return dict(workspace_id=self.workspace_id, version=self.version, updated_at=self.updated_at, labels={cid: s.label for cid, s in self.slots.items()},
                        environment=self.environment(), policy=self.policy(), patient=self.patient_context(),
                        cases=self.similar_cases(f"{self.workspace_id}:patient"), per_case=per)


class ArchivedConversation:
    """DB에 남은 지난 대화 (서버를 다시 켜기 전 대화). 화면 계약을 스냅숏에서 읽기만 한다."""

    archived = True
    live = False

    def __init__(self, row: dict[str, Any], messages: list[dict[str, Any]] | None = None) -> None:
        snap = row.get("clinic")
        if not snap:
            raise NotFound(row.get("conv_id"))
        self.row = row
        self.id = row["conv_id"]
        self.snap = snap
        self.workspace_id = snap["workspace_id"]
        self.raw_messages = messages or []

    def _case(self, case_id: str) -> dict[str, Any]:
        if case_id not in self.snap["per_case"]:
            raise NotFound(case_id)
        return self.snap["per_case"][case_id]

    def case_of_ref(self, ref: str) -> str | None:
        m = _REF.fullmatch(ref or "")
        cid = f"case-{int(m.group(1))}" if m else None
        return cid if cid in self.snap["per_case"] else None

    def ref_of(self, case_id: str) -> str:
        self._case(case_id)
        return case_id.replace("case-", "사례")

    def session_id(self, case_id: str) -> str:
        return f"{self.workspace_id}:{case_id}"

    def environment(self) -> dict[str, Any]:
        return dict(self.snap["environment"], locationLabel=self.snap["environment"]["locationLabel"] + " · 지난 대화 (읽기 전용)")

    def policy(self) -> dict[str, Any]:
        return self.snap["policy"]

    def patient_context(self) -> dict[str, Any]:
        return self.snap["patient"]

    def similar_cases(self, context_id: str) -> list[dict[str, Any]]:
        if context_id != f"{self.workspace_id}:patient":
            raise NotFound(context_id)
        return self.snap["cases"]

    def conversation(self, case_id: str) -> dict[str, Any]:
        return self._case(case_id)["conversation"]

    def disclosures(self, case_id: str) -> dict[str, Any]:
        return self._case(case_id)["disclosures"]

    def policy_decision(self, case_id: str) -> dict[str, Any]:
        return self._case(case_id)["decision"]

    def risk_state(self, case_id: str) -> dict[str, Any]:
        return self._case(case_id)["risk"]

    def risk_states(self) -> list[dict[str, Any]]:
        return [v["risk"] for v in self.snap["per_case"].values()]

    def narrowing(self, case_id: str) -> dict[str, Any]:
        n = self._case(case_id).get("narrowing")
        if n is None:                                    # 이 기능 전에 저장한 대화
            raise NotFound(f"{case_id}: 후보가 줄어든 과정이 저장되지 않은 지난 대화입니다.")
        return n

    def messages(self) -> list[dict[str, Any]]:
        labels = self.snap.get("labels") or {}
        return _messages_view(self.raw_messages, self.case_of_ref, lambda cid: labels.get(cid, cid))

    def preflight(self, case_id: str, session_id: str, question: str, **kw: Any) -> dict[str, Any]:
        self._case(case_id)
        return dict(caseId=case_id, question=question, requiresWarning=False, currentK=None, projectedK=None,
                    message="보관된 지난 대화라 보내기 전 확인을 할 수 없습니다.", affectedAttributes=[], suggestions=[], source="backend",
                    supported=False, plannedAction=None, targetCaseId=None, targetCaseLabel=None)

    def suggestions(self, case_id: str) -> list[dict[str, Any]]:
        self._case(case_id)
        return []

    def ask(self, *a: Any, **kw: Any) -> dict[str, Any]:
        raise Conflict("지난 대화는 읽기만 할 수 있습니다. 새 대화를 시작하세요.")


class ClinicDesk:
    """
    의료진 한 명(데모 모드에서는 화면 하나)의 진료 지원 AI.
    start로 다른 환자(trial)를 고르면 새 대화를 만든다. 지난 대화는 관제 화면에 남는다.
    on_change(대화, 이유)는 대화가 바뀔 때마다 부른다 (DB 저장, persist.py). 실패해도 의료진 요청은 그대로 끝낸다.
    """

    def __init__(self, eng: Engine, trial_id: str = "T0014", arm: str = "C1", budget: int = 60, *, llm_mode: str = "oracle",
                 owner: dict[str, Any] | None = None, compare: bool = True, location_label: str = DEMO_LOCATION,
                 on_change: Callable[[ClinicConversation, str], None] | None = None, keep: int | None = None,
                 on_evict: Callable[[ClinicConversation], None] | None = None, lazy: bool = False) -> None:
        self.eng, self.arm, self.budget, self.llm_mode = eng, arm, budget, llm_mode
        self.owner, self.compare, self.location_label = owner, compare, location_label
        self.on_change, self.keep, self.on_evict = on_change, keep, on_evict
        self.default_trial = trial_id
        self.lock = threading.RLock()            # 이 의료진의 질문 · 새 대화 시작을 한 번에 하나씩 (LLM을 기다리는 동안에도)
        self.history: dict[str, ClinicConversation] = {}
        self._current: ClinicConversation | None = None
        if not lazy:                             # lazy: 운영 모드. EMR에서 환자를 열 때 첫 대화를 만든다 (안 열고 화면을 보면 기본 환자)
            self.start(trial_id)

    @property
    def current(self) -> ClinicConversation:
        if self._current is None:
            with self.lock:
                if self._current is None:
                    self.start(self.default_trial)
        return self._current  # type: ignore[return-value]

    def peek(self) -> ClinicConversation | None:
        """지금 대화 (없으면 만들지 않고 None)."""
        return self._current

    # 지금 대화로 넘기는 읽기 (앞선 코드 · 테스트와 같은 이름)
    @property
    def session(self) -> Session:
        return self.current.session

    @property
    def slots(self) -> dict[str, Slot]:
        return self.current.slots

    @property
    def workspace_id(self) -> str:
        return self.current.workspace_id

    def start(self, trial_id: str, *, launch: dict[str, Any] | None = None, on_call: Callable[[str, int], None] | None = None,
              visit_event: str | None = None, stop: Any = None) -> ClinicConversation:
        with self.lock:
            cur = self._current
            first = next((r for r in cur.session.logs[self.arm] if r.get("turn") == 0), None) if cur is not None else None
            refused0 = bool(first and first["release_mode"].startswith("REFUSAL"))          # 첫 답이 거절이면 새로 시도한다
            same_visit = cur is not None and getattr(cur.session, "visit_event", None) == visit_event
            if (cur is not None and cur.session.trial_id == trial_id and same_visit and cur.session.turn == 0 and not cur.session.messages
                    and not refused0):
                # 같은 환자이고 아직 아무것도 묻지 않은 대화는 그대로 쓴다 (화면을 열 때 만든 기본 대화를 EMR에서 다시 열 때 등)
                if launch is not None:
                    cur.session.launch = launch
                    self._changed(cur, "launch")
                return cur
            with self.eng.lock:
                s = self.eng.new_session(trial_id, source="clinic", budget=self.budget, llm_mode=self.llm_mode, on_call=on_call,
                                         visit_event=visit_event, owner=self.owner, stop=stop)
                s.owner = self.owner
                s.launch = launch
                conv = ClinicConversation(self.eng, s, self.arm, compare=self.compare, location_label=self.location_label)
                self.history[s.id] = conv
                self._current = conv
            self._changed(conv, "start")
            self._evict()
            return conv

    def ask(self, case_id: str, session_id: str, question: str, client_message_id: str, scope: str = "case") -> dict[str, Any]:
        with self.lock:
            conv = self.current
            out = conv.ask(case_id, session_id, question, client_message_id, scope)
            self._changed(conv, "ask")
            return out

    def _changed(self, conv: ClinicConversation, why: str) -> None:
        if self.on_change is None:
            return
        try:
            self.on_change(conv, why)
        except Exception as exc:          # 저장 실패가 의료진 답을 막지 않게 한다 (관제 /api/health에 개수가 남는다)
            print(f"[medicloak] 대화 {conv.id} 저장 실패: {type(exc).__name__}: {exc}")

    def _evict(self) -> None:
        """
        메모리에 둘 지난 대화 수 상한 (DB가 있을 때만). 내린 대화는 DB 스냅숏으로 관제 화면에 남는다.
        저장에 성공한 대화만 내린다 (실패하면 메모리에 그대로 두고 다음에 다시). 뒤에서 비교 갈래를 계산 중인 대화는 두고 간다.
        """
        if not self.keep or self.on_evict is None:
            return
        for sid in list(self.history):
            if len(self.history) <= self.keep:
                break
            conv = self.history[sid]
            if (self._current is not None and sid == self._current.id) or conv.session.compare_pending:
                continue
            try:
                self.on_evict(conv)
            except Exception as exc:
                print(f"[medicloak] 대화 {sid}를 메모리에서 내리지 못했습니다 (저장 실패, 다음에 다시): {type(exc).__name__}: {exc}")
                break
            self.history.pop(sid, None)


class DeskRegistry:
    """계정마다 ClinicDesk 하나. 데모 모드(로그인 없음)는 'demo' 하나만 쓴다."""

    def __init__(self, eng: Engine, *, trial: str = "T0014", llm_mode: str = "oracle", compare: bool = True,
                 location_label: str = DEMO_LOCATION, on_change: Callable[[ClinicConversation, str], None] | None = None,
                 keep: int | None = None, on_evict: Callable[[ClinicConversation], None] | None = None,
                 archive: Callable[[str], ArchivedConversation | None] | None = None, lazy: bool = False) -> None:
        self.eng, self.trial, self.llm_mode, self.compare, self.location_label = eng, trial, llm_mode, compare, location_label
        self.on_change, self.keep, self.on_evict, self.archive, self.lazy = on_change, keep, on_evict, archive, lazy
        self.desks: dict[Any, ClinicDesk] = {}
        self.lock = threading.Lock()

    def desk_for(self, user: dict[str, Any] | None) -> ClinicDesk:
        key = user["user_id"] if user else "demo"
        with self.lock:
            d = self.desks.get(key)
            if d is None:
                owner = dict(user_id=user["user_id"], username=user["username"], label=user["display_name"],
                             department=user.get("department")) if user else None
                d = ClinicDesk(self.eng, self.trial, llm_mode=self.llm_mode, owner=owner, compare=self.compare,
                               location_label=self.location_label, on_change=self.on_change, keep=self.keep, on_evict=self.on_evict,
                               lazy=self.lazy and user is not None)
                self.desks[key] = d
            return d

    def live(self, sid: str) -> ClinicConversation | None:
        with self.lock:
            desks = list(self.desks.values())
        for d in desks:
            conv = d.history.get(sid)
            if conv is not None:
                return conv
        return None

    def current_ids(self) -> set[str]:
        with self.lock:
            return {c.id for c in (d.peek() for d in self.desks.values()) if c is not None}

    def lookup(self, sid: str) -> ClinicConversation | ArchivedConversation:
        conv = self.live(sid)
        if conv is not None:
            return conv
        if self.archive is not None:
            a = self.archive(sid)
            if a is not None:
                return a
        raise NotFound(sid)

    def all_live(self) -> list[ClinicConversation]:
        with self.lock:
            desks = list(self.desks.values())
        return [c for d in desks for c in d.history.values()]

