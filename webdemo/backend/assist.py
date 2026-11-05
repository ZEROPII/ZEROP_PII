# 보안 담당자 검토 보조 에이전트: 의료진의 세부 정보 요청이 오면 검토 초안을 만든다 (ADR-0027)
#
# 의료진이 '세부 정보 요청'을 보내면 뒤에서 한 번 돈다 (관제 상세의 '다시 만들기'로도 돈다).
#   1. 요청 읽기        : 어느 사례에 대한 요청인지, 조회 목적, 의료진이 쓴 사유
#   2. 가린 값 모으기   : 그 사례에서 넓히거나 가린 값. 값 자체는 읽지 않는다 (단서 종류 · 처리 · 어느 답인지만)
#   3. 하나씩 열어 보기 : 지금 누적 상태에 그 값 하나를 더했을 때 후보 수 (Session.what_if, State는 바꾸지 않는다)
#   4. 조회 목적과 대조 : 처방 · 시술·치료 · 경과·관리 판단에 그 단서가 쓰이는지 (PURPOSE_NEED, 병원이 고쳐 쓰는 표)
#   5. 함께 열어 보기   : 공개해도 되는 값을 한꺼번에 더해도 기준 이상인지. 후보가 많이 남는 값부터 하나씩 더하고, 기준 아래로 내려가는 값은 뺀다
#   6. 초안 쓰기        : 담당자용 요약 · 의료진 답장 · 공개 사유. 실제 LLM이 있으면 LLM이 쓰고, 없거나 실패하면 정해진 문장으로 쓴다
#
# 추천(공개 가능 · 사유 확인 뒤 결정 · 지금 범위 유지 · 공개하지 않음)은 규칙으로 정한다. LLM은 글만 쓰고 추천을 바꾸지 않는다.
# 하지 않는 일
#   - 공개 · 답장 · 규칙을 스스로 보내지 않는다. 보안 담당자가 초안을 고쳐 직접 보낸다 (자동 승인 없음).
#   - LLM에 가린 값의 원문 · 환자 번호 · 과거 기록을 보내지 않는다. 단서 종류 · 처리 · 후보 수 · 조회 목적 · 요청 문장만 보낸다.
#   - 의료진 답장 초안에 숫자를 넣지 않는다 (의료진 화면은 후보 수를 보이지 않는다). LLM 답장에 숫자가 섞이면 정해진 문장을 쓴다.
# 초안은 메모리에만 두고, 만들 때마다 감사 기록(assist_draft)에 사례 · 추천 수 · 쓴 방식만 남긴다 (값 없음).

from __future__ import annotations

import json
import re
import threading
import time
import traceback
from typing import Any, Callable

from webdemo.backend.live import background_calls

ACTOR = "검토 보조 AI"

# 조회 목적마다 단서가 진료 판단에 쓰이는 정도 (need: 직접 씀 · coarse: 범위로도 충분 · low: 관련 적음).
# 거주 지역은 조회 목적 규칙(review.PURPOSE_UNNEEDED)으로 이미 늘 가리므로 공개 승인 대상에 오지 않는다.
PURPOSE_NEED: dict[str, dict[str, str]] = {
    "PRESCRIPTION": dict(MED="need", DX="need", PERIOD="coarse", AGE="coarse", SEX="low", PROC="low", PLAN="low"),
    "TREATMENT_PROCEDURE": dict(PROC="need", DX="need", MED="need", PLAN="need", PERIOD="coarse", AGE="coarse", SEX="low"),
    "COURSE_CARE": dict(PLAN="need", DX="need", MED="need", PERIOD="coarse", AGE="coarse", PROC="low", SEX="low"),
}
PURPOSE_KO = dict(PRESCRIPTION="처방", TREATMENT_PROCEDURE="시술·치료", COURSE_CARE="경과·관리")
NEED_KO = dict(need="판단에 직접 쓰임", coarse="범위로도 판단 가능", low="이번 목적과 관련 적음")
REC_KO = dict(release="공개 가능", consider="사유 확인 뒤 결정", keep="지금 범위 유지", decline="공개하지 않음")
VERDICT_KO = dict(release="공개 권장", partial="일부 공개 권장", consider="사유 확인 뒤 결정", keep="지금 처리 유지 권장", none="공개할 값 없음")
ACTION_KO = dict(generalize="범위로 바꿈", suppress="가림", dropped="사례째로 뺌")
# 담당자 화면의 단서 이름 · 의료진 답장에 쓰는 이름
ATTR_KO = dict(AGE="나이", SEX="성별", REGION="거주 지역", PERIOD="시점", DX="진단", PROC="시술", MED="약", PLAN="관리 계획")
REPLY_KO = dict(AGE="나이", SEX="성별", REGION="거주 지역", PERIOD="날짜", DX="진단명", PROC="시술명", MED="약 이름", PLAN="관리 계획")
# 바로 열지 않을 때 담당자가 고를 수 있는 대안 (담당자용 짧은 말 · 의료진 답장 문장)
ALT_KO = dict(PERIOD="정확한 날짜 대신 진단 뒤 몇 달째인지로 안내", AGE="지금 연령대로 판단하도록 안내", MED="약 이름 대신 약 계열로 안내",
              DX="진단명 대신 진단군으로 안내", PROC="시술명 대신 시술 종류로 안내", PLAN="관리 계획의 종류만 안내",
              SEX="성별 대신 필요한 조건만 확인")
ALT_REPLY = dict(PERIOD="정확한 날짜 대신 진단 뒤 몇 달째였는지로는 알려 드릴 수 있습니다.",
                 AGE="연령대로 판단하기 어려운 사정이 있으면 함께 적어 주세요.",
                 MED="약 이름 대신 약 계열로는 알려 드릴 수 있습니다.",
                 DX="진단명 대신 진단군으로는 알려 드릴 수 있습니다.",
                 PROC="시술명 대신 시술 종류로는 알려 드릴 수 있습니다.",
                 PLAN="관리 계획의 종류로는 알려 드릴 수 있습니다.",
                 SEX="진료에 필요한 조건(예: 임신 가능성)을 적어 주시면 그 여부만 확인해 드리겠습니다.")
REASON_FIT = ("구체적", "불분명", "목적과 다름")
_DIGIT = re.compile(r"[0-9０-９]")
_CASE = re.compile(r"사례\s*\d+")


# ── 한국어 조사 ──
def _final(word: str) -> int | None:
    """마지막 한글 글자의 받침 번호 (0이면 받침 없음). 한글로 끝나지 않으면 None."""
    w = word.strip()
    if not w or not "가" <= w[-1] <= "힣":
        return None
    return (ord(w[-1]) - 0xAC00) % 28


def josa(word: str, with_final: str, without: str) -> str:
    f = _final(word)
    if f is None:
        return f"{word}{with_final}({without})"
    if with_final == "으로" and f == 8:          # ㄹ 받침 + 으로 → 로
        return word + without
    return word + (with_final if f else without)


def join_ko(words: list[str]) -> str:
    """'나이', '날짜', '약 이름' → '나이, 날짜와 약 이름'"""
    words = list(dict.fromkeys(words))
    if len(words) <= 1:
        return "".join(words)
    head = ", ".join(words[:-2] + [josa(words[-2], "과", "와")])
    return f"{head} {words[-1]}"


def case_ko(ref: str | None) -> str:
    m = re.fullmatch(r"사례(\d+)", ref or "")
    return f"사례 {m.group(1)}" if m else "찾은 사례"


def where_ko(turn: int) -> str:
    return "사례 검색 답" if turn == 0 else f"질문 {turn}의 답"


# ── 판정 ──
def recommend(action: str, need: str, k_one: int | None, k_req: int) -> tuple[str, str]:
    """가린 값 하나의 추천과 이유 (규칙). k_one: 그 값 하나만 지금 공개했을 때 후보 수."""
    if k_one is not None and k_one >= k_req:
        return "release", "공개해도 후보가 기준 이상으로 남습니다"
    if need == "low":
        return "decline", "이번 조회 목적과 관련이 적고, 공개하면 후보가 기준 아래로 줄어듭니다"
    if action == "generalize" and need == "coarse":
        return "keep", "지금 보이는 범위로도 판단할 수 있습니다"
    if k_one is not None and k_one <= 1:
        return "decline", "공개하면 과거 환자 한 명으로 좁혀집니다"
    return "consider", "진료에 쓰이는 값이지만 공개하면 후보가 기준 아래로 줄어듭니다"


def analyse(s: Any, request: dict[str, Any]) -> dict[str, Any]:
    """엔진 잠금 안에서 부른다. 값 원문 없이 단서 종류 · 처리 · 후보 수로 판정한다."""
    case = request.get("case")
    qtype = s.qtype
    purpose = PURPOSE_KO.get(qtype, qtype)
    need_of = PURPOSE_NEED.get(qtype, {})
    k_req = s.cfg.k_req
    hidden = [x for x in s.hidden() if not x["released"] and (case is None or x["case"] == case)]
    purpose_cut = sum(1 for rec in s.logs["C1"] if rec.get("turn") is not None
                      for p in rec.get("release_plans") or [] if case is None or p["ref"] == case
                      for d in p["decisions"] if d.get("purpose") and d["action"] != "allow")
    refs = list(dict.fromkeys(x["case"] for x in hidden)) or ([case] if case else [])
    k_now = {ref: s.current_k("C1", ref) for ref in refs}
    items = []
    for x in hidden:
        k_one = s.what_if([x["id"]]).get(x["case"])
        need = need_of.get(x["attribute"], "low")
        action = "dropped" if x.get("dropped") else x["action"]
        rec, why = recommend(x["action"], need, k_one, k_req)
        items.append(dict(id=x["id"], turn=x["turn"], where=where_ko(x["turn"]), case=x["case"], attribute=x["attribute"],
                          attributeLabel=ATTR_KO.get(x["attribute"], x["attribute"]), action=action, actionLabel=ACTION_KO.get(action, action),
                          need=need, needLabel=NEED_KO[need], kNow=k_now.get(x["case"]), kIfRelease=k_one, rec=rec, why=why,
                          alternative=ALT_KO.get(x["attribute"]) if rec in ("consider", "decline") else None))
    # 함께 열어 보기: 후보가 많이 남는 값부터 하나씩 더해 본다. 기준 아래로 내려가게 하는 값은 '사유 확인'으로 돌린다
    chosen: list[str] = []
    combined: dict[str, int] = {}
    for it in sorted((i for i in items if i["rec"] == "release"), key=lambda i: (-(i["kIfRelease"] or 0), i["id"])):
        ks = s.what_if(chosen + [it["id"]])
        if min(ks.values()) >= k_req:
            chosen.append(it["id"])
            combined = ks
        else:
            it.update(rec="consider", why="다른 값과 함께 열면 후보가 기준 아래로 줄어듭니다", alternative=ALT_KO.get(it["attribute"]))
    for it in items:
        it["recLabel"] = REC_KO[it["rec"]]
    recs = [i["rec"] for i in items]
    verdict = ("none" if not items else "release" if all(r == "release" for r in recs) else "partial" if "release" in recs
               else "consider" if "consider" in recs else "keep")
    ks_one = [i["kIfRelease"] for i in items if i["kIfRelease"] is not None]
    counts = {r: recs.count(r) for r in REC_KO}
    needs = [i["need"] for i in items]
    steps = [
        dict(label="요청 읽기", detail=f"{case_ko(case)} · {purpose} 참고 · 요청 문장 {len((request.get('text') or '').strip())}자"),
        dict(label="가린 값 모으기", detail=f"공개 승인 대상 {len(items)}개" + (f" (조회 목적 규칙으로 뺀 값 {purpose_cut}개는 제외)" if purpose_cut else "")),
        dict(label="하나씩 열어 보기", detail=(f"지금 후보 {min(k_now.values()) if k_now else '–'}명, 하나만 공개하면 "
                                         + (f"{min(ks_one)}명" if min(ks_one) == max(ks_one) else f"{min(ks_one)}~{max(ks_one)}명")
                                         if ks_one else "열어 볼 값 없음")),
        dict(label="조회 목적과 대조", detail=f"직접 쓰임 {needs.count('need')}개 · 범위로 충분 {needs.count('coarse')}개 · 관련 적음 {needs.count('low')}개"),
        dict(label="함께 열어 보기", detail=(f"공개 가능 {len(chosen)}개를 함께 열면 후보 {min(combined.values())}명 (기준 {k_req}명)"
                                         if chosen else "함께 열 값 없음")),
    ]
    return dict(case=case, caseLabel=case_ko(case), purpose=qtype, purposeLabel=purpose, requestId=request["id"], requestText=request.get("text") or "",
                kReq=k_req, kNow=min(k_now.values()) if k_now else None, items=items, release=chosen,
                combinedK=min(combined.values()) if combined else None, counts=counts, verdict=verdict, verdictLabel=VERDICT_KO[verdict], steps=steps)


# ── 정해진 문장 (LLM이 없거나 실패했을 때) ──
def template_text(a: dict[str, Any]) -> dict[str, str]:
    items, purpose, case = a["items"], a["purposeLabel"], a["caseLabel"]

    def names(rec: str, low: bool | None = None) -> list[str]:
        return [REPLY_KO.get(i["attribute"], i["attributeLabel"]) for i in items
                if i["rec"] == rec and (low is None or (i["need"] == "low") == low)]

    c = a["counts"]
    summary = (f"{case} 요청에서 공개 승인 대상 값은 {len(items)}개입니다. 공개 가능 {c['release']}개, 사유 확인 {c['consider']}개, "
               f"범위 유지 {c['keep']}개, 공개하지 않음 {c['decline']}개로 봅니다.")
    if a["combinedK"] is not None:
        summary += f" 공개 가능한 값을 함께 열어도 후보는 {a['combinedK']}명으로 기준 {a['kReq']}명 이상입니다."
    low = [i["kIfRelease"] for i in items if i["rec"] in ("consider", "decline") and i["kIfRelease"] is not None]
    if low:
        summary += f" 나머지 값은 하나만 열어도 후보가 {min(low)}명까지 줄어듭니다."
    if not items:
        summary = f"{case}에는 공개 승인으로 열 수 있는 가린 값이 없습니다. 조회 목적에 필요 없어 가린 값은 공개 대상이 아닙니다."
    parts: list[str] = [f"요청하신 {case}의 가린 값을 검토했습니다."]
    if names("release"):
        parts.append(f"{josa(join_ko(names('release')), '은', '는')} 공개 승인으로 따로 보내 드리겠습니다.")
    if names("keep"):
        parts.append(f"{josa(join_ko(names('keep')), '은', '는')} 지금 보이는 범위로도 {purpose} 판단에 충분하다고 보아 그대로 두겠습니다.")
    if names("consider"):
        parts.append(f"{josa(join_ko(names('consider')), '은', '는')} 그대로 보이면 과거 환자를 알아볼 수 있어 바로 열지 않았습니다. "
                     "진료에 꼭 필요한 이유를 알려 주시면 다시 검토하겠습니다.")
    if names("decline", low=True):
        parts.append(f"{josa(join_ko(names('decline', low=True)), '은', '는')} 이번 {purpose} 참고 목적과 관련이 적어 공개하지 않습니다.")
    if names("decline", low=False):
        parts.append(f"{josa(join_ko(names('decline', low=False)), '은', '는')} 공개하면 그 과거 환자를 알아볼 수 있어 공개하지 않습니다.")
    alt = next((ALT_REPLY[i["attribute"]] for i in items if i["rec"] in ("consider", "decline") and i["attribute"] in ALT_REPLY), None)
    if alt:
        parts.append(alt)
    if not items:
        parts = [f"요청하신 {case}의 가린 값은 이번 {purpose} 참고 목적에 필요하지 않아 공개 대상이 아닙니다. 진료에 필요한 내용을 다시 알려 주세요."]
    released = [ATTR_KO.get(i["attribute"], i["attribute"]) for i in items if i["rec"] == "release"]
    reason = (f"{purpose} 참고에 필요한 {join_ko(released)} 공개. 공개 뒤에도 후보가 기준 이상으로 남음 (검토 보조 확인)"
              if released else "")
    return dict(summary=summary, reply=" ".join(parts), reason=reason)


# ── LLM 초안 ──
def prompt_of(a: dict[str, Any]) -> str:
    lines = [f"- {i['attributeLabel']} · {i['where']}에서 {i['actionLabel']} · 하나만 공개하면 후보 {i['kIfRelease'] if i['kIfRelease'] is not None else '–'}명"
             f" · 조회 목적: {i['needLabel']} → {i['recLabel']} ({i['why']})" + (f" · 대안: {i['alternative']}" if i["alternative"] else "")
             for i in a["items"]] or ["- 공개 승인으로 열 수 있는 가린 값 없음"]
    together = (f"공개 가능 값을 함께 열면 후보 {a['combinedK']}명 (기준 {a['kReq']}명)" if a["combinedK"] is not None else "함께 열 값 없음")
    return "\n".join([
        "[검토 보조]",
        "너는 병원 개인정보 보호 담당자를 돕는 검토 보조다. 의료진이 진료 지원 AI 답에서 가려진 값을 보여 달라고 요청했다.",
        "아래 [판정]은 규칙으로 이미 정했다. 판정을 바꾸지 말고, 담당자가 읽을 요약과 의료진에게 보낼 답장 초안을 써라.",
        "지킬 것",
        "- 가린 값의 원래 내용을 추측하거나 지어내지 않는다.",
        "- summary: 담당자용. 두세 문장. 후보 수를 써도 된다. 의료진 요청 사유가 조회 목적에 맞는지도 한 문장으로 평가한다.",
        "- reply: 의료진에게 보낼 답장. 정중한 존댓말 두세 문장. 숫자는 하나도 쓰지 않는다 (후보 수 · 기준 · 날짜 · 나이 모두).",
        "  공개 가능한 항목은 '공개 승인으로 따로 보낸다'고, 나머지는 이유와 대안을 짧게 쓴다.",
        "- reason_fit: 요청 사유 평가. '구체적' · '불분명' · '목적과 다름' 중 하나. reason_note: 그 이유 한 구절.",
        "- 출력은 JSON 객체 하나만: {\"summary\": \"…\", \"reply\": \"…\", \"reason_fit\": \"…\", \"reason_note\": \"…\"}",
        "",
        f"[조회 목적] {a['purposeLabel']} 참고",
        f"[요청 사례] {a['caseLabel']}",
        f"[의료진 요청 문장] {a['requestText'].strip()[:500]}",
        "[판정]",
        *lines,
        f"[함께 공개] {together}",
    ])


def parse_draft(text: str) -> dict[str, str]:
    """LLM 답에서 JSON을 꺼내 검사한다. 틀리면 ValueError (정해진 문장으로 돌아간다)."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if m is None:
        raise ValueError("JSON이 없습니다")
    d = json.loads(m.group(0))
    summary, reply = str(d.get("summary") or "").strip(), str(d.get("reply") or "").strip()
    if not 10 <= len(summary) <= 700:
        raise ValueError("요약 길이")
    if not 10 <= len(reply) <= 500:
        raise ValueError("답장 길이")
    if _DIGIT.search(_CASE.sub("", reply)) or "후보" in reply:          # 사례 표시('사례 1')의 번호는 숫자로 치지 않는다
        raise ValueError("답장에 숫자")
    fit = str(d.get("reason_fit") or "").strip()
    return dict(summary=summary, reply=reply, reasonFit=fit if fit in REASON_FIT else "불분명",
                reasonNote=str(d.get("reason_note") or "").strip()[:120])


class _ReviewerLLM:
    """ClientRoleLLM의 HTTP 클라이언트로 '검토 보조' 역할 호출을 한다 (모델은 재작성기와 같다: --rewriter-model). 사용량은 reviewer로 센다."""

    MAX_TOKENS = 1500

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    @property
    def usage(self) -> list[dict[str, Any]]:
        return self.inner.usage

    def complete(self, role: str, system: str, messages: list[dict[str, str]], **kw: Any) -> str:
        c = self.inner
        model = (c.models.get("reviewer") or c.models.get("rewriter")) or None
        resp = c.client.chat([{"role": "user", "content": system}], max_tokens=self.MAX_TOKENS, temperature=0.0, model=model)
        c.usage.append(dict(role="reviewer", model=resp.model, input_tokens=resp.input_tokens, output_tokens=resp.output_tokens,
                            latency_ms=round(resp.latency_ms, 1), attempts=resp.attempts, truncated=resp.truncated, max_tokens=self.MAX_TOKENS))
        return resp.text


def writer_llm(eng: Any) -> Any | None:
    """실제 LLM이 있으면 같은 자리(동시 호출 수 · 의료진 질문 우선)를 나눠 쓰는 검토 보조 LLM. 결정적 응답기 · 점검용 가짜는 None."""
    live = getattr(eng, "live_llm", None)
    inner = getattr(live, "inner", None)
    if inner is None or not hasattr(inner, "client") or not hasattr(inner, "models"):
        return None
    return live.sibling(_ReviewerLLM(inner))


class ReviewAssistant:
    """세부 정보 요청마다 검토 초안을 만든다. 초안은 Session.assist에 둔다 (메모리)."""

    def __init__(self, eng: Any, log: Callable[..., Any], *, llm: Any = None) -> None:
        self.eng = eng
        self.log = log                                # Monitor.log
        self.llm = llm if llm is not None else writer_llm(eng)
        self.lock = threading.Lock()
        self.threads: list[threading.Thread] = []

    def state(self, s: Any) -> dict[str, Any]:
        with self.lock:
            st = getattr(s, "assist", None)
            return dict(st) if st else dict(status="none")

    def latest_request(self, s: Any) -> dict[str, Any] | None:
        return next((m for m in reversed(s.messages) if m["sender"] == "clinician" and m["kind"] == "access_request"), None)

    def schedule(self, s: Any, request: dict[str, Any] | None = None) -> dict[str, Any]:
        """뒤에서 초안을 만든다. 요청이 없으면 이 대화의 마지막 세부 정보 요청."""
        request = request or self.latest_request(s)
        if request is None:
            raise LookupError("이 대화에는 세부 정보 요청이 없습니다.")
        with self.lock:
            s.assist = dict(status="running", requestId=request["id"], startedAt=time.time())
        t = threading.Thread(target=self._run, args=(s, request), daemon=True, name=f"assist-{s.id}")
        self.threads = [x for x in self.threads if x.is_alive()] + [t]
        t.start()
        return self.state(s)

    def wait(self, timeout: float = 30.0) -> None:
        """테스트 · 점검용: 돌고 있는 초안 작성이 끝날 때까지."""
        end = time.time() + timeout
        for t in list(self.threads):
            t.join(max(0.0, end - time.time()))

    def _run(self, s: Any, request: dict[str, Any]) -> None:
        background_calls()                            # 의료진 질문 호출이 기다리면 먼저 보낸다
        try:
            with self.eng.lock:
                a = analyse(s, request)
            text = template_text(a)
            writer, note = "template", "정해진 문장 (실제 LLM 없음)"
            if self.llm is not None:
                try:
                    llm_text = parse_draft(self.llm.complete("reviewer", prompt_of(a), []))
                    text = dict(text, summary=llm_text["summary"], reply=llm_text["reply"])
                    a.update(reasonFit=llm_text["reasonFit"], reasonNote=llm_text["reasonNote"])
                    writer, note = "llm", "실제 LLM이 요약과 답장을 썼습니다 (가린 값 원문은 보내지 않음)"
                except Exception as exc:                # 형식이 틀리거나 숫자가 섞이거나 호출이 실패하면 정해진 문장
                    note = f"정해진 문장 (LLM 초안을 쓰지 않음: {type(exc).__name__})"
            a["steps"].append(dict(label="초안 쓰기", detail=note))
            draft = dict(a, **text, writer=writer, writerLabel="AI 초안" if writer == "llm" else "정해진 문장", createdAt=time.time())
            with self.lock:
                if (getattr(s, "assist", None) or {}).get("requestId") == request["id"]:
                    s.assist = dict(status="ready", requestId=request["id"], startedAt=s.assist.get("startedAt"), finishedAt=time.time(), draft=draft)
            self.log("assist_draft", s, actor=ACTOR, case=a["case"], request=request["id"], verdict=a["verdict"], writer=writer,
                     counts=a["counts"])
        except Exception as exc:
            traceback.print_exc()
            with self.lock:
                if (getattr(s, "assist", None) or {}).get("requestId") == request["id"]:
                    s.assist = dict(status="error", requestId=request["id"], error=f"검토 초안을 만들지 못했습니다 ({type(exc).__name__}).",
                                    finishedAt=time.time())
