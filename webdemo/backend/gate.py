# 입력 단계 게이팅: 대상 AI에 공개할 수 있는 값만 넣는다 (ADR-0032, 연구자 4인 검토 P0-2)
#
# 지금까지 대상 AI 지시문에는 검색된 과거 환자 문서 원문(정확한 날짜 · 나이 · 거주지 · 드문 진단까지)이 그대로 들어갔고,
# MediCloak은 대상 AI가 쓴 답을 공개 직전에 고쳤다. 그러면 보호 수준이 추출기 재현율에 묶이고(놓친 값은 그대로 나감),
# 외부 LLM에 원본 기록이 넘어간다.
#
# 게이팅은 대상 AI를 부르기 전에, 사례 문서의 사실 줄마다 지금 그 사례의 누적 State(원장 포함)를 기준으로 판정한다.
#   - 그 값 하나를 그대로 더해도 후보가 generalize 기준(5명)보다 많으면 그대로, 아니면 출력 단계 Defender와 같은 순서로
#     원래 값이 suppress 기준(3명) 이하면 가림, 아니면 후보가 기준을 넘는 가장 가까운 상위 범주로 넓힘.
#   - 조회 목적에 필요 없는 단서(거주 지역)와 보안 담당자 규칙은 가림. 나이 · 날짜는 최소 공개 단위(5세 · 월)로 (review.floor_ok).
#   - 민감 값(sensitivity.py 등급 2)은 후보가 strict_k명 이상일 때만, 아니면 민감하지 않은 상위 범주나 가림.
#   - 횟수 줄('총 7회')은 후보 수 계산에 없는 값이라 범위로만('총 4~9회').
# 값 하나씩 판정하므로, 여러 값을 함께 말해 후보가 줄어드는 위험은 지금처럼 출력 단계(공개 판정 · 다시 확인)가 막는다.
# 출력 단계가 그 값을 혼자 말한 답에도 같은 판정을 내리므로, 게이팅이 가리는 값은 출력 단계도 가렸을 값이다.
#
# 후보 수는 kcalc와 같게 센다: 그 사례 State의 후보 집합(kc.candidates) ∩ 그 값을 가진 환자. 새 값은 자기만의 사건 묶음이라
# 이 교집합이 kcalc k와 같다 (교집합이 0이면 해석이 바뀔 수 있어 kcalc로 다시 센다). 값마다 가진 환자 집합은 한 번만 만든다.

from __future__ import annotations

import collections
import re
import threading
from typing import Any, Callable

from datetime import date as _date

from medical.defense import ALLOW, GENERALIZE, SUPPRESS, SUPPRESSED_MARK
from webdemo.backend.review import FLOOR_ATTRS, floor_ok
from webdemo.backend.textguard import bucket, count_bucket

PATIENT_LEVEL = ("SEX", "REGION")
ITEM_ATTRS = ("DX", "PROC", "MED", "PLAN")
_LINE = re.compile(r"^\[(\d+)\]\s*(.*)$")
_COUNT = re.compile(r"총\s*(\d+)\s*회")
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
_START = re.compile(r"위 (?:진단 시작일|시술 첫 시행일|약 첫 처방 시작일|계획 시작일)")
_END = re.compile(r"위 (?:진단 종료일|시술 마지막 시행일|약 마지막 처방 종료일|계획 종료일)")
GATE_NOTE = ("※ 아래 사례 기록의 '(비공개)'와 범위 · 상위 범주로 적힌 값은 환자 보호를 위해 미리 가리거나 넓힌 값입니다. "
             "원래 값을 짐작해 채우지 말고 적힌 그대로 쓰세요.")


def span_phrase(start: str, end: str) -> str | None:
    """두 날짜 사이를 기간 범위로 ('약 1~2주'). 날짜를 읽지 못하거나 거꾸로면 None."""
    try:
        days = (_date.fromisoformat(end) - _date.fromisoformat(start)).days
    except ValueError:
        return None
    if days < 0:
        return None
    label, ranged = bucket(max(days, 0.5))
    return f"약 {label}" if ranged else label


class InputGate:
    """
    kc     : GroupRepairKC (k · candidates) — 안의 KCalc로 값마다 가진 환자 집합을 만든다.
    data   : MedicalData (anc · label · is_root · N)
    g, s   : Defender 기준 (넓힘 · 가림)
    floors : 나이 · 날짜 최소 공개 단위 (실제 LLM 갈래)
    strict : 노드가 민감 등급 2 이상인지 (sensitivity.Sensitivity.strict), strict_k: 민감 값의 후보 수 하한
    """

    def __init__(self, kc: Any, data: Any, g: int, s: int, *, floors: bool = True, strict: Callable[[str], bool] | None = None,
                 strict_k: int = 10) -> None:
        self.kc, self.data, self.g, self.s = kc, data, g, s
        self.base = getattr(kc, "base", kc)
        self.floors, self.strict, self.strict_k = floors, strict, strict_k
        self._has: dict[tuple[str, str], frozenset[str]] = {}
        self.all = frozenset(self.base.by_pat)
        self._by_node: dict[str, frozenset[str]] | None = None
        self._index_lock = threading.Lock()

    # ── 후보 수 ──
    def event_index(self) -> dict[str, frozenset[str]]:
        """
        노드 → 그 노드(또는 그 아래 노드)의 사건이 있는 과거 환자. 사건마다 조상 노드를 한 번씩만 훑어 한 번 만든다.
        전에는 값마다 사건 전체(약 5만 건)를 다시 훑어, 처음 여는 환자의 사례 문서 게이팅에 3초 가까이 걸렸다.
        """
        if self._by_node is None:
            with self._index_lock:
                if self._by_node is None:
                    b = self.base
                    idx: dict[str, set[str]] = {}
                    for p, events in b.by_pat.items():
                        for i in events:
                            for a in b.ev_anc[i]:
                                idx.setdefault(a, set()).add(p)
                    self._by_node = {n: frozenset(ps) for n, ps in idx.items()}
        return self._by_node

    def has(self, attribute: str, node: str) -> frozenset[str]:
        key = (attribute, node)
        hit = self._has.get(key)
        if hit is None:
            b = self.base
            if attribute in PATIENT_LEVEL:
                hit = frozenset(p for p, a in b.pat.items() if node in a.get(attribute, ()))
            else:
                hit = self.event_index().get(node, frozenset())
            self._has[key] = hit
        return hit

    def _k(self, attribute: str, node: str, cands: frozenset[str], basis: list[dict[str, Any]]) -> int:
        v = len(cands & self.has(attribute, node))
        if v == 0 and basis:
            v = self.kc.k(list(basis) + [dict(attribute=attribute, node_id=node, event_group=f"GATE:{node}")])["k"]
        return v

    def candidates(self, basis: list[dict[str, Any]]) -> tuple[frozenset[str], int]:
        if not basis:
            return self.all, len(self.all)
        k = self.kc.k(basis)["k"]
        return (frozenset(self.kc.candidates(basis)) if k else frozenset()), k

    # ── 값 하나 ──
    def decide(self, basis: list[dict[str, Any]], attribute: str, node: str, *, cands: frozenset[str] | None = None,
               k_basis: int | None = None, blocked: set[str] | frozenset[str] = frozenset()) -> tuple[str, str | None, str | None]:
        """(조치, 바꿀 노드, 까닭). 까닭은 purpose · count · floor · strict · None(그대로)."""
        if attribute in blocked:
            return SUPPRESS, None, "purpose"
        if node not in self.data.N:
            return SUPPRESS, None, "count"
        if cands is None:
            cands, k_basis = self.candidates(basis)
        if k_basis == 0:
            return SUPPRESS, None, "count"                # State끼리 맞지 않는 사례: 출력 단계도 새 값을 모두 가린다
        # 이미 공개된 값도 따로 보지 않는다: 출력 단계도 후보가 적으면 다시 말한 값을 가린다 (두 단계 판정을 같게)
        k = (lambda n: self._k(attribute, n, cands, basis))
        why: str | None = None
        to: str | None = node
        k0 = k(node)
        if k0 <= self.g:
            if k0 <= self.s:
                return SUPPRESS, None, "count"
            chain = self.data.anc(node)
            to = next((c for c in chain if k(c) > self.g), None) or next((c for c in chain if k(c) > self.s), None)
            if to is None or self.data.is_root(to):
                return SUPPRESS, None, "count"
            why = "count" if to != node else None
        if self.floors and attribute in FLOOR_ATTRS and to is not None and not floor_ok(attribute, to):
            chain = self.data.anc(to)
            target = next((n for n in chain if floor_ok(attribute, n)), None)
            if target is None or self.data.is_root(target):
                return SUPPRESS, None, "floor"
            to, why = target, why or "floor"
        if self.strict is not None and to is not None and (self.strict(node) or self.strict(to)):
            if k(to) < self.strict_k:
                chain = self.data.anc(to)
                safe = next((c for c in chain if not self.strict(c) and not self.data.is_root(c) and k(c) >= self.strict_k), None)
                if safe is None:
                    return SUPPRESS, None, "strict"
                to, why = safe, "strict"
        if to == node:
            return ALLOW, node, why
        return GENERALIZE, to, why

    # ── 문서 하나 ──
    def render(self, doc: dict[str, Any], basis: list[dict[str, Any]], blocked: set[str] | frozenset[str] = frozenset()) -> tuple[str, dict[str, Any]]:
        """사례 문서 본문을 게이팅한 글과 집계 (그대로 · 넓힘 · 가림 수, 단서 종류별 가림 · 넓힘)."""
        rows: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
        for r in doc.get("fact_rows") or []:
            if r.get("attribute") and r.get("node_id"):
                rows[int(r["sentence_no"])].append(r)
        cands, kb = self.candidates(basis)
        stats: dict[str, Any] = dict(allow=0, generalize=0, suppress=0, counts=0, spans=0, changed=collections.Counter())
        out = []
        start: tuple[str, bool] | None = None              # 지금 항목의 시작일 (원래 날짜, 가리거나 넓혔는지)
        for ln in (doc.get("text") or "").split("\n"):
            m = _LINE.match(ln)
            if not m:
                out.append(ln)
                continue
            no, body = int(m.group(1)), m.group(2)
            facts = rows.get(no)
            if not facts:                                   # 표시용 줄: 횟수만 범위로
                new = _COUNT.sub(lambda c: "총 " + count_bucket(int(c.group(1))), body)
                stats["counts"] += new != body
                out.append(f"[{no}] {new}")
                continue
            changed_date = False
            for r in facts:
                act, to, why = self.decide(basis, r["attribute"], r["node_id"], cands=cands, k_basis=kb, blocked=blocked)
                stats[act] += 1
                if r["attribute"] in ITEM_ATTRS:
                    start = None                            # 새 항목 (진단 · 시술 · 약 · 계획)
                if act == ALLOW:
                    continue
                changed_date = changed_date or r["attribute"] == "PERIOD"
                stats["changed"][f"{r['attribute']}:{act}"] += 1
                rep = SUPPRESSED_MARK if act == SUPPRESS else self.data.label(to)
                span = str(r.get("span_text") or "")
                body = body.replace(span, rep, 1) if span and span in body else body
            # 날짜를 가리거나 넓혀도 기간은 범위로 남긴다: 진료에 쓰는 경과 · 치료 기간 (검토 P2-2, textguard 기간 범위와 같은 구간)
            date = next((str(r.get("span_text") or "") for r in facts if r["attribute"] == "PERIOD"), "")
            if _START.match(body) and _ISO.fullmatch(date):
                start = (date, changed_date)
            elif _END.match(body) and _ISO.fullmatch(date) and start is not None and (changed_date or start[1]):
                phrase = span_phrase(start[0], date)
                if phrase:
                    body = f"{body.rstrip('.')} (시작부터 {phrase})."
                    stats["spans"] += 1
                start = None
            out.append(f"[{no}] {body}")
        stats["changed"] = dict(stats["changed"])
        return "\n".join(out), stats

    def cases_block(self, docs: list[dict[str, Any]], basis_of: Callable[[int, dict[str, Any]], list[dict[str, Any]]],
                    blocked_of: Callable[[int], set[str] | frozenset[str]]) -> tuple[str, list[dict[str, Any]]]:
        """대상 AI 지시문의 [검색된 사례] 자리 글과 사례마다 집계 (사례 번호는 1부터)."""
        parts, report = [GATE_NOTE], []
        for i, d in enumerate(docs, 1):
            text, st = self.render(d, basis_of(i, d), blocked_of(i))
            parts.append(f"[사례{i}]\n{text}")
            report.append(dict(ref=f"사례{i}", **st))
        return "\n\n".join(parts), report
