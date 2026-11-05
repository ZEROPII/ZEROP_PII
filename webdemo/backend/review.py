# 보안 담당자의 검토를 대화에 반영하고, 실제 LLM 대화의 공개 게이트를 보강한다 (ADR-0022, ADR-0023).
#
#   규칙 (rules)    : "이 대화에서 사례N의 이 단서 종류는 늘 가림". 의료진 화면 갈래(C1)의 공개 계획과 다시 확인 단계에 같이 건다.
#                     넓히면 기준을 넘는 값이라도 가린다. 고친 답에 그 단서가 남으면 확인을 통과하지 못한다 (재작성 · 규칙 치환 · 거절 순).
#                     비교 갈래(C0 방어 없음 · C1S 턴별 방어)는 연구용 대조군이라 규칙을 걸지 않는다.
#   공개 승인 (approve) : 의료진의 세부 정보 요청에 보안 담당자가 사유를 적고 가린 값을 골라 공개한다.
#                     그 값은 그 의료진의 그 대화에만 나가고, 누적 State(C1)에 더해져 이후 판정에 들어간다
#                     (후보가 기준 아래로 내려가면 그 사례의 다음 답은 더 막힌다).
#   후보가 줄어든 과정 (narrowing) : 사례마다 공개된 단서를 쌓인 순서대로 하나씩 더하며 센 후보 수 (보안 담당자 화면).
#   고친 답 다시 확인 보강 : 연구 모듈의 확인(_verify)은 고친 답을 다시 뽑아 찾은 사례만 센다. 고친 답이 '사례N' 표기를
#                     떨어뜨리면 사례를 못 찾아 확인이 그냥 통과한다. 그래서 (1) 가리거나 넓히기로 한 원래 값이 글자 그대로
#                     남아 있거나 (2) 바꿀 값이 있었는데 사례를 하나도 못 찾고 그 사례 표기도 글에 없으면 통과시키지 않는다
#                     (의료진 화면 갈래 C1 · C1S).
#
#   실제 LLM 대화에서만 (live=True: 운영 모드 의료진 대화 · 실제 LLM 레드팀. 결정적 응답기는 POC 그대로):
#   재작성 지시 보강 : 재작성기 지시문에 규칙 두 줄을 더한다. 바꿀 값은 답 전체에서 고치고(요약 · 비교 문장, 줄여 쓴 이름),
#                     값을 뺀 사례를 다른 문장에서 다시 가리키지 않는다. 다시 확인에 떨어진 뒤의 재작성에는 무엇이 남았는지
#                     (다시 뽑은 단서 중 허용하지 않은 값)를 알려 준다. 연구 모듈은 온도 0에서 같은 지시로 다시 부르므로
#                     알려 주지 않으면 두 번째 재작성이 첫 번째와 같은 답을 낸다.
#   사례 단위로 빼기 : 재작성 · 값 치환이 모두 다시 확인을 통과하지 못하면 연구 모듈은 답 전체를 거절 문장으로 바꾼다.
#                     그 전에 통과하지 못한 사례만 답에서 빼고(그 사례를 가리키는 머리줄 묶음 · 문장) 한 번 더 확인한다.
#                     통과하면 그 답을 내고(CASE_DROPPED) 뺀 사례의 판정은 모두 가림으로 남긴다. 통과하지 못하면 거절 그대로.
#   조회 목적 (ADR-0026) : 어느 조회 목적(처방 · 시술·치료 · 경과·관리)에도 거주 지역은 진료 판단에 쓰지 않는다. 실제 LLM 갈래에서는
#                     후보 수와 관계없이 늘 가린다 (목적 외 이용 금지). 보안 담당자 규칙과 같은 길(blocked)로 계획 · 다시 확인에 건다.
#   최소 공개 단위 (ADR-0024) : 나이는 5세 구간(93세 → 90~94세), 날짜는 월(2018-03-24 → 2018-03)보다 자세히 내지 않는다.
#                     온톨로지의 넓힘 사슬(정확한 값 → 5세 구간 → 10세 구간, 일 → 월 → 분기 → 연)을 따른다. 또 답의 글자가 후보를
#                     센 노드보다 자세하면(예: 노드 90~99세로 센 '93-98세') 그 노드 이름으로 바꾼다. 내보낸 글자와 센 값이 늘 같다.
#                     바꿀 것이 이 단위 맞춤뿐이면 재작성기를 부르지 않고 글자 그대로 바꾼 뒤 다시 확인한다(ROUNDED).
#
# medical/ 연구 모듈은 바꾸지 않는다. Defender와 LLM은 감싸고(RuleDefender · RewriteHintLLM), 갈래는 상속해(RuledArmRun)
# 공개 단계에 확인과 앞뒤 시도만 덧붙인다.

from __future__ import annotations

import copy
import re
from dataclasses import replace
from typing import Any, Callable

from medical.defense import ALLOW, GENERALIZE, SUPPRESS, Decision, apply_changes_deterministic
from medical.session import ArmRun, Release
from medical.tracking import view_of

CASE_DROPPED = "CASE_DROPPED"                 # 통과하지 못한 사례를 뺀 답
ROUNDED = "ROUNDED"
#: 조회 목적마다 진료 판단에 쓰지 않는 단서 (실제 LLM 갈래에서 늘 가림)
PURPOSE_UNNEEDED: dict[str, frozenset[str]] = {q: frozenset({"REGION"}) for q in ("PRESCRIPTION", "TREATMENT_PROCEDURE", "COURSE_CARE")}                           # 나이 · 날짜를 최소 공개 단위로만 바꾼 답 (재작성기 없이)
RELEASE_VERSION = "medicloak-release-v4"       # 재작성 지시 보강 · 사례 단위로 빼기 · 최소 공개 단위 · 조회 목적 (실제 LLM 갈래의 versions에 남긴다)

# 최소 공개 단위: 이 노드보다 자세한 값은 내지 않는다 (온톨로지 노드 이름 규칙: AGE_Y93 · AGE5_90 · AGE10_90, …_DAY_ · _MONTH_ …)
FLOOR_ATTRS = ("AGE", "PERIOD")


def floor_ok(attribute: str, node: str) -> bool:
    n = str(node)
    if attribute == "AGE":
        return not n.startswith("AGE_Y")             # 나이는 5세 구간 이상
    if attribute == "PERIOD":
        return "_DAY_" not in n                      # 날짜는 월 이상
    return True


def same_text(raw: str | None, label: str | None) -> bool:
    """답의 글자가 노드 이름과 같은 값인지 ('90~99세' = '90-99세', '2018년' = '2018')."""
    norm = lambda x: re.sub(r"[\s년월일세경약쯤]", "", x or "").translate(str.maketrans({"~": "-", "–": "-", "—": "-", "/": "-", ".": "-"}))
    return bool(raw) and norm(raw) == norm(label)


class RuleDefender:
    """
    MedicalDefender를 감싼다. blocked(ref)가 주는 단서 종류는 그 사례에서 늘 가림(SUPPRESS)으로 정한다.
    floors=True(실제 LLM 갈래)면 나이 · 날짜를 최소 공개 단위로 올리고, 답의 글자가 센 노드보다 자세하면 노드 이름으로 바꾼다.
    """

    def __init__(self, inner: Any, blocked: Callable[[str], set[str]], *, floors: bool = False) -> None:
        self.inner = inner
        self.blocked = blocked
        self.floors = floors
        self.last_plans: list[Any] = []                 # 이번 공개의 계획과 바꿀 값 (RuledArmRun._verify가 다시 확인에 씀)
        self.last_changes: list[dict[str, Any]] = []

    def __getattr__(self, name: str) -> Any:          # kc · data · g · s · risky …
        return getattr(self.inner, name)

    def change_lines(self, plans: list[Any]) -> list[dict[str, Any]]:
        changes = self.inner.change_lines(plans)
        flags = [bool(getattr(d, "floor", False)) for p in plans for d in p.changes]     # inner.change_lines와 같은 순서
        for c, f in zip(changes, flags):
            c["floor"] = f
        self.last_plans, self.last_changes = list(plans), list(changes)
        return changes

    def plan_case(self, ref: str, basis: list[dict[str, Any]], new: list[dict[str, Any]], sources: list[dict[str, Any]]):
        plan = self._plan(ref, basis, new, sources)
        if self.floors:
            self._floor(plan)
        return plan

    def _floor(self, plan: Any) -> None:
        """허용 · 넓힘으로 정한 나이 · 날짜를 최소 공개 단위 이상으로, 글자가 센 노드보다 자세하면 그 노드 이름으로 (넓힘)."""
        data = self.inner.data
        for i, x in enumerate(plan.decisions):
            attr = x.disclosure["attribute"]
            if attr not in FLOOR_ATTRS or x.action != ALLOW:
                continue                                # 가림은 그대로, 넓힘은 이미 노드 이름으로 바꿔 쓴다
            orig = x.disclosure["node_id"]
            chain = data.anc(orig)                      # [원래 값, 부모, …, 루트]
            target = next((n for n in chain if floor_ok(attr, n)), None)
            if target == orig and same_text(x.source.get("raw_value"), data.label(orig)):
                continue
            if target is None or data.is_root(target):
                d = Decision(x.disclosure, x.source, SUPPRESS, None, x.k_raw, x.max_steps, x.max_steps)
            else:
                d = Decision(x.disclosure, x.source, GENERALIZE, target, x.k_raw, chain.index(target), x.max_steps)
            d.floor = True                              # 후보 수 때문이 아니라 공개 단위 · 글자를 맞추려고 바꿈
            plan.decisions[i] = d

    def _plan(self, ref: str, basis: list[dict[str, Any]], new: list[dict[str, Any]], sources: list[dict[str, Any]]):
        blocked = self.blocked(ref)
        if not blocked or not any(d["attribute"] in blocked for d in new):
            return self.inner.plan_case(ref, basis, new, sources)
        keep = [i for i, d in enumerate(new) if d["attribute"] not in blocked]
        plan = self.inner.plan_case(ref, basis, [new[i] for i in keep], [sources[i] for i in keep])
        kept = dict(zip(keep, plan.decisions))
        k = lambda ds: self.inner.kc.k(ds)["k"]
        out: list[Decision] = []
        for i, (d, src) in enumerate(zip(new, sources)):
            if i in kept:
                out.append(kept[i])
                continue
            depth = self.inner.data.depth(d["node_id"])
            out.append(Decision(d, src, SUPPRESS, None, k(list(basis) + [d]), depth, depth))
        plan.decisions = out
        plan.risky = True
        return plan


# ── 재작성 지시 보강 ────────────────────────────────────────

_REWRITE_SECTION = "\n[바꿀 표현]\n"             # 연구 모듈 재작성 지시문의 목록 머리 (그 앞에 규칙을 더한다)
_SALT_WORDS = {"sodium", "potassium", "calcium", "magnesium", "zinc", "iron", "aluminum", "hydrochloride", "sulfate", "acetate",
               "chloride", "citrate", "phosphate", "bicarbonate"}


def short_name(med: str) -> str | None:
    """약 이름을 줄여 쓸 때의 이름: 용량 앞 성분 이름의 첫 낱말 ('naproxen sodium 220 MG …' → 'naproxen').
    첫 낱말이 염 · 원소 이름이면 성분 이름 전체 ('sodium fluoride 0.0272 MG/MG …' → 'sodium fluoride')."""
    words = []
    for w in (med or "").split():
        if any(ch.isdigit() for ch in w) or not re.fullmatch(r"[A-Za-z][A-Za-z\-]*", w):
            break
        words.append(w)
    if not words or len(words[0]) < 4:
        return None
    name = " ".join(words) if words[0].lower() in _SALT_WORDS else words[0]
    return None if name.lower() == med.strip().lower() else name


def rewrite_rules(prompt: str, changes: list[dict[str, Any]], retry: str | None = None) -> str:
    """재작성기 지시문의 규칙 끝에 두 줄(+ 다시 고칠 때는 남은 표현)을 더한다. 목록 머리를 못 찾으면 그대로 둔다."""
    at = prompt.find(_REWRITE_SECTION)
    if at < 0:
        return prompt
    short = []
    for c in changes:                                   # 빼기로 한 약만 (넓힌 약 이름은 보통 성분 이름을 그대로 둔다)
        name = short_name(c.get("raw_value") or "") if c.get("attribute") == "MED" and c.get("action") == SUPPRESS else None
        if name:
            short.append(f"'{name}'({c['case_ref']})")
    add = ["6. 바꿀 값은 그 자리만이 아니라 답 전체에서 고친다. 같은 값이 요약 · 비교 · 주목할 점 같은 다른 문장에 다시 나오거나, "
           "대소문자를 바꾸거나 줄여 쓴 경우(약 이름의 성분 이름만, 날짜의 연도 · 월만)도 같은 값으로 보고 똑같이 고친다."
           + (f" 이 답에서 줄여 쓸 수 있는 이름: {', '.join(dict.fromkeys(short))}." if short else ""),
           "7. 값을 뺀 사례를 다른 문장에서 다시 가리키며 그 값을 떠올리게 하지 않는다.",
           "8. 값을 빼서 내용이 없어진 줄(표의 빈 줄, '-'만 남은 줄, 빈 목록 항목)은 줄째 지운다."]
    if retry:
        add.append("9. 앞서 고친 답을 다시 확인하니 아래가 남아 통과하지 못했다. 이번에는 이것까지 고친다.\n" + retry)
    return prompt[:at] + "\n" + "\n".join(add) + prompt[at:]


class RewriteHintLLM:
    """갈래의 LLM을 감싼다. 재작성기 지시문에만 규칙을 더하고, 나머지 역할은 그대로 보낸다."""

    def __init__(self, inner: Any, arm: "RuledArmRun") -> None:
        self.inner, self.arm = inner, arm

    def __getattr__(self, name: str) -> Any:          # usage · next_arm …
        return getattr(self.inner, name)

    def complete(self, role: str, system: str, messages: list[dict[str, str]], **kw: Any) -> str:
        if role == "rewriter":
            system = rewrite_rules(system, list(kw.get("plan") or []), self.arm._retry_note)
        return self.inner.complete(role, system, messages, **kw)


# ── 사례 단위로 빼기 ────────────────────────────────────────

_LABEL = re.compile(r"사례\s*0*(\d+)(?!\d)")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_BULLET = re.compile(r"^(\s*(?:[-*+•]|\d+[.)])\s+)")
_HRULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_MD_HEAD = re.compile(r"^\s*(#{1,6})\s")
_LEAD = re.compile(r"^\s*(?:[-*+•]\s+|\d+[.)]\s+)?(?:\*\*|__)?\s*\[?사례\s*0*\d+")
_SENT_END = re.compile(r"(?:[.!?]|다|요)\s*(?:\*\*|__)?\s*$")


def case_labels(text: str) -> set[str]:
    """글에 나온 사례 표기 ('사례 2' · '사례02'도 '사례2'로)."""
    return {f"사례{int(m.group(1))}" for m in _LABEL.finditer(text)}


def ref_no(ref: str | None) -> int:
    m = re.search(r"\d+", ref or "")
    return int(m.group()) if m else 0


def drop_cases(text: str, refs: set[str]) -> str | None:
    """
    refs 사례의 내용을 답에서 뺀다. 남은 답에 다른 사례가 없거나 바뀐 것이 없으면 None.
      - 마크다운 머리줄(#)이 refs를 가리키면 그 아래를 같은 수준 이상의 다음 머리줄 · 구분선까지 뺀다
        (머리줄이 여러 사례를 묶었으면 묶음째 뺀다)
      - '사례N'으로 시작하고 문장으로 끝나지 않는 머리 줄('**사례2** (남성)', '사례2:')은 빈 줄이나 다른 사례로 시작하는 줄까지
      - 그 밖의 줄은 문장으로 나눠 refs를 가리키는 문장과, 같은 문단에서 그 뒤를 잇는 문장(다른 사례를 새로 가리키기 전까지)을 뺀다
      - 통째로 뺀 목록 줄보다 더 들여 쓴 하위 줄도 뺀다
    빼고 남은 답은 반드시 다시 확인한다 (RuledArmRun._drop_failing). 이 함수는 줄이고 고르기만 한다.
    """
    refs = set(refs)
    out: list[str] = []
    sec_drop, sec_level = False, None            # 뺄 묶음 안인지, 그 묶음을 연 머리줄 수준 (None: '사례N' 머리 줄이 연 묶음)
    sub_indent: int | None = None
    carry = False                                # 앞 문장이 뺄 사례를 가리켰다 (같은 문단의 이어지는 문장도 뺀다)
    for ln in text.split("\n"):
        s = ln.strip()
        indent = len(ln) - len(ln.lstrip())
        if not s:
            carry = False
            if sec_drop and sec_level is None:
                sec_drop = False
            if not sec_drop:
                out.append("")
            continue
        if sub_indent is not None:
            if indent > sub_indent:
                continue
            sub_indent = None
        if _HRULE.match(ln):
            sec_drop, sec_level, carry = False, None, False
            out.append(ln)
            continue
        m = _MD_HEAD.match(ln)
        if m:
            level, carry = len(m.group(1)), False
            if sec_drop and sec_level is not None and level > sec_level:
                continue
            sec_drop, sec_level = bool(case_labels(ln) & refs), level
            if not sec_drop:
                out.append(ln)
            continue
        labs = case_labels(ln)
        if sec_drop:
            if sec_level is None and labs and not labs & refs and _LEAD.match(ln):
                sec_drop = False                 # 다른 사례로 시작하는 줄에서 '사례N' 머리 줄 묶음이 끝난다
            else:
                continue
        if labs and _LEAD.match(ln) and not _SENT_END.search(s):
            carry = False
            if labs & refs:
                sec_drop, sec_level = True, None
                continue
            out.append(ln)
            continue
        b = _BULLET.match(ln)
        prefix = b.group(1) if b else ln[:indent]
        if b:
            carry = False
        keep = []
        for sent in _SENT_SPLIT.split(ln[len(prefix):]):
            sl = case_labels(sent)
            if sl & refs:
                carry = True
                continue
            if carry and sl:
                carry = False
            if not carry:
                keep.append(sent)
        if keep:
            out.append(prefix + " ".join(keep))
        elif b:
            sub_indent = indent
    result = _tidy(out)
    if not result or result == text.strip() or not (case_labels(result) - refs):
        return None
    return result


def _tidy(lines: list[str]) -> str:
    """내용이 없어진 머리줄과 남는 구분선을 지우고 빈 줄을 정리한다."""
    def nxt(i: int) -> str | None:
        return next((x for x in lines[i + 1:] if x.strip()), None)
    keep: list[str] = []
    for i, ln in enumerate(lines):
        m = _MD_HEAD.match(ln)
        if m:
            n = nxt(i)
            nm = _MD_HEAD.match(n) if n is not None else None
            if n is None or _HRULE.match(n) or (nm and len(nm.group(1)) <= len(m.group(1))):
                continue
        keep.append(ln)
    out: list[str] = []
    for ln in keep:
        if _HRULE.match(ln):
            prev = next((x for x in reversed(out) if x.strip()), None)
            if prev is None or _HRULE.match(prev):
                continue
        out.append(ln)
    while out and (not out[-1].strip() or _HRULE.match(out[-1])):
        out.pop()
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def drop_note(refs: set[str]) -> str:
    return f"{', '.join(sorted(refs, key=ref_no))}의 세부 내용은 환자를 알아볼 위험이 있어 이 답에서 뺐습니다."


# ── 갈래 ────────────────────────────────────────────────────

class RuledArmRun(ArmRun):
    """
    보안 담당자 규칙을 지키는 갈래. rules()는 [(사례 표기, 단서 종류)]. 규칙이 없으면 확인 보강만 ArmRun과 다르다.
    live=True(실제 LLM)이면 재작성 지시 보강과 사례 단위로 빼기를 더한다.
    """

    def __init__(self, ctx: Any, prefix: Any, arm: str, log: Callable[[dict[str, Any]], None],
                 rules: Callable[[], list[tuple[str, str]]], *, live: bool = False) -> None:
        self.rules = rules
        self.live = live
        self._retry_note: str | None = None          # 다시 확인에 떨어진 뒤 다음 재작성에 알려 줄 것 (실제 LLM)
        # 조회 목적에 필요 없는 단서: 사례와 관계없이 늘 가림 (실제 LLM 갈래, 의료진 대화 · 레드팀 같음)
        self.purpose_blocked = PURPOSE_UNNEEDED.get(getattr(prefix, "query_type", ""), frozenset()) if live else frozenset()
        super().__init__(ctx, prefix, arm, log)
        if live:
            self.trial["versions"] = dict(self.trial.get("versions") or {}, medicloak_release=RELEASE_VERSION)

    def blocked(self, ref: str) -> set[str]:
        return {a for r, a in self.rules() if r == ref} | set(self.purpose_blocked)

    @property
    def ctx(self) -> Any:
        return self._ctx

    @ctx.setter
    def ctx(self, c: Any) -> None:
        # 문맥을 바꿔 끼울 때(실제 LLM 문맥 등)마다 Defender를 규칙으로, 실제 LLM이면 LLM을 재작성 지시 보강으로 감싼다
        if not isinstance(c.defender, RuleDefender):
            c = replace(c, defender=RuleDefender(c.defender, self.blocked, floors=self.live))
        if self.live and not (isinstance(c.llm, RewriteHintLLM) and c.llm.arm is self):
            inner = c.llm.inner if isinstance(c.llm, RewriteHintLLM) else c.llm
            c = replace(c, llm=RewriteHintLLM(inner, self))
        self._ctx = c

    def release(self, query: str, raw: str, raw_obs: list[dict[str, Any]], raw_ok: bool) -> Release:
        self._retry_note = None
        rel, pre, n_pre = self._rounded(query, raw, raw_obs, raw_ok) if self.live else (None, [], 0)
        self._retry_note = None
        if rel is None:
            rel = self._mark_floor(super().release(query, raw, raw_obs, raw_ok))
            if pre:                                       # 단위만 맞춘 답이 다시 확인을 통과하지 못한 기록도 남긴다
                rel = replace(rel, attempts=pre + rel.attempts, extraction_tries=rel.extraction_tries + n_pre)
        self._retry_note = None
        if not self.live or rel.mode != "REFUSAL":
            return rel
        return self._drop_failing(query, rel)

    def _mark_floor(self, rel: Release) -> Release:
        """
        기록의 판정에 '최소 공개 단위로 바꿈(floor)'과 '조회 목적에 필요 없어 가림(purpose)'을 남긴다 (화면 설명 · 감사용).
        계획과 판정 순서는 연구 모듈과 같다. 보안 담당자 규칙으로도 막힌 단서는 규칙이 먼저다.
        """
        ruled = set(self.rules())
        for pd in rel.plans:
            for xd in pd["decisions"]:
                if xd["action"] == SUPPRESS and xd["attribute"] in self.purpose_blocked and (pd["ref"], xd["attribute"]) not in ruled:
                    xd["purpose"] = True
        plans = getattr(self._ctx.defender, "last_plans", None) or []
        if len(plans) != len(rel.plans):
            return rel
        for p, pd in zip(plans, rel.plans):
            for x, xd in zip(p.decisions, pd["decisions"]):
                if getattr(x, "floor", False):
                    xd["floor"] = True
        return rel

    def _rounded(self, query: str, raw: str, raw_obs: list[dict[str, Any]], raw_ok: bool) -> tuple[Release | None, list[dict[str, Any]], int]:
        """
        바꿀 것이 최소 공개 단위 맞춤(나이 · 날짜를 노드 이름으로)뿐이면 재작성기를 부르지 않는다: 원 답의 그 글자를 노드 이름으로
        바꾸고 다시 확인한다. 통과하면 (ROUNDED 공개, [], 0). 해당하지 않으면 (None, [], 0), 확인에 떨어지면 (None, [시도], 추출 수)
        로 연구 모듈의 공개 단계(재작성 · 값 치환 · 사례 빼기 · 거절)에 넘긴다.
        """
        if self.arm == "C0" or not raw_ok:
            return None, [], 0
        d = self._ctx.defender
        raw_view = view_of(raw_obs, raw, query, self._ctx.nz)
        plans = [d.plan_case(ref, self._basis(ref), raw_view.disclosures[ref], raw_view.sources[ref]) for ref in raw_view.case_refs]
        changes = d.change_lines(plans)
        if not changes or not all(c.get("floor") for c in changes):
            return None, [], 0
        text = apply_changes_deterministic(raw, changes)
        ok, v, checks, n = self._verify(query, text)
        attempt = dict(mode=ROUNDED, text=text, ok=ok, checks=checks)
        if not ok or v is None:
            return None, [attempt], n
        decisions = [x for p in plans for x in p.decisions]
        util = round(sum(x.utility for x in decisions) / len(decisions), 4) if decisions else None
        return self._mark_floor(Release(text, v, ROUNDED, [p.as_dict() for p in plans], changes, [attempt], util, n)), [], 0

    def _verify(self, query: str, text: str):
        ok, v, checks, n = super()._verify(query, text)
        if ok and v is not None:
            for ref in v.case_refs:
                left = sorted({d["attribute"] for d in v.disclosures[ref]} & self.blocked(ref))
                if left:
                    checks.append(dict(ref=ref, rule=left, ok=False))
                    ok = False
            d = self._ctx.defender
            changes = getattr(d, "last_changes", None) or []
            if changes:
                # 그대로 내도 되는 값과 같은 글자는 빼고 본다 (다른 사례에 같은 약 이름이 허용된 경우)
                allowed = {str(x.source.get("raw_value") or "") for p in getattr(d, "last_plans", []) for x in p.decisions if x.action == ALLOW}
                left = [c for c in changes if c["raw_value"] and c["raw_value"] not in allowed and _appears(c["raw_value"], text)]
                for c in left:
                    checks.append(dict(ref=c["case_ref"], reason="RAW_VALUE_LEFT", attribute=c["attribute"], ok=False))
                    ok = False
                # 다시 뽑아도 사례를 하나도 못 찾았고, 바꿀 값이 있던 사례의 'N번 사례' 표기도 글에 없으면 단서가 어느 사례 것인지 셀 수 없다
                if not v.case_refs and not any(_has_label(c["case_ref"], text) for c in changes):
                    checks.append(dict(ref=None, reason="NO_CASE_FOUND", ok=False))
                    ok = False
        if self.live:
            self._retry_note = None if ok else self._retry_for(checks, v)
        return ok, v, checks, n

    # ── 실제 LLM 갈래: 다시 고칠 때 알려 줄 것 · 사례 단위로 빼기 ──
    def _retry_for(self, checks: list[dict[str, Any]], v: Any) -> str | None:
        plans = {p.ref: p for p in getattr(self._ctx.defender, "last_plans", [])}
        out = []
        for c in checks:
            if c.get("ok") is not False:
                continue
            ref, why = c.get("ref"), c.get("reason")
            if why == "NO_CASE_FOUND":
                out.append("고친 답에서 '사례N' 표기가 사라졌다. 사례 표기는 지우지 않는다.")
            elif why == "RAW_VALUE_LEFT":
                out.append(f"{ref}에서 바꾸기로 한 값이 글자 그대로 남았다.")
            elif ref:
                left = self._left_values(v, ref, plans.get(ref))
                tail = f" 남은 표현: {', '.join(repr_quote(x) for x in left)}." if left else ""
                out.append(f"{ref} 환자를 알아볼 수 있는 표현이 아직 남았다.{tail} 그 사례를 가리키는 다른 문장도 다시 본다.")
        return "\n".join(f"- {x}" for x in dict.fromkeys(out)) or None

    def _left_values(self, v: Any, ref: str, plan: Any) -> list[str]:
        """다시 뽑은 그 사례의 단서 중 이번 계획(또는 이미 공개한 State)이 허용하지 않은 값의 글자."""
        if v is None or ref not in v.disclosures:
            return []
        ok_nodes = {x["node_id"] for x in self._basis(ref)}
        for x in getattr(plan, "decisions", []) or []:
            if x.action == ALLOW:
                ok_nodes.add(x.disclosure["node_id"])
            elif x.action == GENERALIZE and x.to_node:
                ok_nodes.add(x.to_node)
        vals = [str(src.get("raw_value") or "") for dd, src in zip(v.disclosures[ref], v.sources[ref]) if dd["node_id"] not in ok_nodes]
        return [x for x in dict.fromkeys(vals) if x][:4]

    def _drop_failing(self, query: str, rel: Release) -> Release:
        """통과하지 못한 사례만 뺀 답을 한 번 더 확인한다. 통과하면 그 답, 아니면 거절 그대로 (시도는 기록에 남긴다)."""
        refs = {p["ref"] for p in rel.plans}
        cands = []
        for i, a in enumerate(rel.attempts):
            bad = {c.get("ref") for c in a.get("checks") or [] if c.get("ok") is False}
            if not bad or None in bad or refs <= bad:          # 어느 사례 것인지 모르는 실패이거나, 모든 사례가 통과하지 못함
                continue
            cands.append((len(bad), a["mode"] != "REWRITTEN", i, a, bad))
        if not cands:
            return rel
        _, _, _, a, bad = min(cands, key=lambda x: x[:3])      # 뺄 사례가 가장 적은 시도, 같으면 재작성 답을 먼저
        body = drop_cases(a["text"], bad)
        if body is None:
            return rel
        text = f"{body}\n\n{drop_note(bad)}"
        ok, v, checks, n = self._verify(query, text)
        left = sorted((r for r in bad if v is not None and v.disclosures.get(r)), key=ref_no)
        if ok and left:                                         # 뺐다는 사례의 단서가 다시 뽑히면 통과시키지 않는다
            checks.append(dict(ref=left[0], reason="DROPPED_CASE_LEFT", ok=False))
            ok = False
        dropped = sorted(bad, key=ref_no)
        attempts = rel.attempts + [dict(mode=CASE_DROPPED, text=text, ok=ok, checks=checks, dropped=dropped)]
        n_ext = rel.extraction_tries + n
        if not ok or v is None:
            return replace(rel, attempts=attempts, extraction_tries=n_ext)
        plans, changes = copy.deepcopy(rel.plans), list(rel.changes)
        for p in plans:
            if p["ref"] not in bad:
                continue
            for x in p["decisions"]:
                if x["action"] == ALLOW:
                    changes.append(dict(case_ref=p["ref"], attribute=x["attribute"], raw_value=str(x.get("raw_value") or ""),
                                        evidence_spans=[], action=SUPPRESS, to_label=None, dropped=True))
                x.update(action=SUPPRESS, to_node=None, utility=0.0, dropped=True)
        ds = [x for p in plans for x in p["decisions"]]
        util = round(sum(x["utility"] for x in ds) / len(ds), 4) if ds else None
        return Release(text, v, CASE_DROPPED, plans, changes, attempts, util, n_ext)


def repr_quote(value: str) -> str:
    return f"'{value}'"


def _appears(value: str, text: str) -> bool:
    """값이 글자 그대로 남았는지. 숫자 · 영문이 이어 붙은 경우(15세 속의 5세, 2004-06-160)는 같은 값으로 보지 않는다."""
    return re.search(rf"(?<![0-9A-Za-z]){re.escape(value)}(?![0-9A-Za-z])", text) is not None


def _has_label(ref: str | None, text: str) -> bool:
    """'사례1' 표기가 글에 있는지 ('사례 1'도 같게, '사례10'은 다르게 본다)."""
    m = re.fullmatch(r"사례\s*(\d+)", ref or "")
    return m is not None and re.search(rf"사례\s*0*{int(m.group(1))}(?!\d)", text) is not None


def hidden_items(logs: list[dict[str, Any]], approvals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """의료진 화면 갈래 기록에서 가리거나 넓힌 값 (값 자체는 넣지 않는다). 승인해 공개한 것은 released. 사례째로 뺀 값도 가림이다."""
    released = {(x["turn"], x["case"], x["index"]) for ap in approvals for x in ap["items"]}
    out = []
    for rec in logs:
        if rec.get("turn") is None:
            continue
        refusal = rec["release_mode"].startswith("REFUSAL")
        for p in rec.get("release_plans") or []:
            for i, d in enumerate(p["decisions"]):
                action = SUPPRESS if refusal else d["action"]
                if action == ALLOW or (d.get("purpose") and not refusal):
                    continue                              # 조회 목적에 필요 없어 가린 값은 공개 승인 대상이 아니다
                out.append(dict(id=f"{rec['turn']}:{p['ref']}:{i}", turn=rec["turn"], case=p["ref"], index=i, attribute=d["attribute"],
                                action=action, kIfRaw=d.get("k_raw"), released=(rec["turn"], p["ref"], i) in released,
                                dropped=bool(d.get("dropped"))))
    return out


def decision_of(logs: list[dict[str, Any]], turn: int, ref: str, index: int) -> dict[str, Any]:
    rec = next(r for r in logs if r.get("turn") == turn)
    plan = next(p for p in rec["release_plans"] if p["ref"] == ref)
    return plan["decisions"][index]
