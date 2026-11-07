"""
정규화 확장 v0.11.3 [본 연구 설정, 2026-11-03] — 전달 묶음 normalize_bridge(v0.11.1)는 그대로 두고 상속으로 더한다.

r3_rule · holdout_1 실행 기록의 정규화 실패를 보고 넣은 규칙이다. 원칙은 묶음과 같다:
기록보다 구체적으로 세지 않는다(모르면 넓은 노드로, 그래도 모르면 반영하지 않음).

1. 날짜 기간 (v0.11.2, 팀 보류검증 패키지의 normalize_bridge_v0.11.2.patch와 같은 규칙)
   '2018-03-09~24', '2016-02-01~현재', '2012-10-02 시작' → 시작 역할이면 '~' 왼쪽, 종료 역할이면 오른쪽(빠진 연·월은 왼쪽에서 채움).
   근거: TimeML/TIMEX3는 기간을 시작점 · 끝점이 있는 구간으로 다룬다.
2. '/'로 이은 이름 (v0.11.2) 'Gingivitis/Gingival disease' → 진단 · 시술 · 관리 계획은 나눠서 각각 찾는다 (NCBI disease corpus의 composite mention).
3. 나이 범위 '93-96세'처럼 5 · 10세 구간이 아닌 범위 → 감싸는 가장 좁은 5 · 10세 구간 (팀 채점 단계 3과 같은 규칙).
4. 성별 한 글자 '남' · '여' · '남자' · '여자'.
5. 이름 일부로 찾기: 'ibuprofen', 'metformin hydrochloride 500 MG', 'Removal of supragingival plaque'처럼
   별칭표에 그대로 없는 이름은, 그 낱말을 모두 담은 별칭들의 **가장 가까운 공통 상위 노드**로 반영한다.
   예: 'ibuprofen' → 모든 ibuprofen 제품의 공통 상위(ATC M01AE01 ibuprofen). 공통 상위가 뿌리(ANY)면 반영하지 않는다.
   이름 일부만 말했으니 그 이름이 가리킬 수 있는 것보다 좁게 세지 않는다.
"""
from __future__ import annotations

import re

from medical.bundle.normalize_bridge import Normalizer

VERSION = "medical/normalize_ext v0.11.3"
_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
_SEX = {"남": "남성", "남자": "남성", "여": "여성", "여자": "여성"}
PARTIAL_ATTRS = ("DX", "PROC", "MED", "PLAN")


class NormalizerV2(Normalizer):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._tok_index = None

    # 1. 날짜 기간 -----------------------------------------------------------------------
    def _period(self, raw, role):
        s = re.sub(r"\s*(시작|부터|이후|경부터)$", "", str(raw).strip())
        if "~" in s and role:
            left, right = [x.strip() for x in s.split("~", 1)]
            if role.endswith("_END") and right and not re.search(r"현재|지속", right):
                m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", left)
                if m and re.fullmatch(r"\d{1,2}", right):
                    s = f"{m.group(1)}-{m.group(2)}-{int(right):02d}"
                elif m and re.fullmatch(r"\d{1,2}-\d{1,2}", right):
                    s = f"{m.group(1)}-" + "-".join(f"{int(x):02d}" for x in right.split("-"))
                else:
                    s = right
            else:
                s = left
        return super()._period(s, role)

    # 2 · 4. 표현 다듬기 ---------------------------------------------------------------------
    def _variants(self, att, raw):
        yield from super()._variants(att, raw)
        s = str(raw).strip()
        if "/" in s and att in ("DX", "PROC", "PLAN"):
            for part in s.split("/"):
                if part.strip():
                    yield part.strip(), "SLASH_SPLIT"
        if att == "SEX" and s in _SEX:
            yield _SEX[s], "SEX_SHORT"

    # 3. 나이 범위 ---------------------------------------------------------------------------
    def _age(self, raw):
        nid = super()._age(raw)
        if nid:
            return nid
        m = re.fullmatch(r"(\d{1,3})[~\-](\d{1,3})(세|살)?", str(raw).replace(" ", ""))
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a <= b and a // 5 == b // 5:
                return f"AGE5_{a // 5 * 5}"
            if a <= b and a // 10 == b // 10:
                return f"AGE10_{a // 10 * 10}"
        return None

    # 5. 이름 일부 → 공통 상위 노드 -------------------------------------------------------------
    def _lookup(self, att, raw):
        hits, how = super()._lookup(att, raw)
        if hits or att not in PARTIAL_ATTRS:
            return hits, how
        lca = self._partial(att, str(raw))
        return ({lca}, "TOKEN_SUBSET_LCA") if lca else (set(), "")

    def _index(self):
        if self._tok_index is None:
            self._tok_index = {}
            for (att, sf), nids in self.alias.items():
                if att in PARTIAL_ATTRS:
                    self._tok_index.setdefault(att, []).append((frozenset(_TOKEN.findall(sf)), nids))
        return self._tok_index

    def _partial(self, att, raw):
        q = set(_TOKEN.findall(raw.lower()))
        if not any(len(t) >= 4 and not t[0].isdigit() for t in q):      # 'of', 'mg', '500'만으로는 찾지 않음
            return None
        nodes = set()
        for toks, nids in self._index().get(att, []):
            if q <= toks:
                nodes |= nids
        nodes = {n for n in nodes if n in self.node}
        if not nodes:
            return None
        common = None
        for n in nodes:
            common = self._anc(n) if common is None else common & self._anc(n)
        if not common:
            return None
        lca = max(common, key=lambda n: len(self._anc(n)))              # 가장 깊은(가까운) 공통 상위
        if lca.startswith("ANY") or lca.endswith("_ANY") or not self.node[lca].get("parent_id"):
            return None
        return lca


def make_normalizer(paths, version: str = "v2", min_confidence=None) -> Normalizer:
    cls = NormalizerV2 if version == "v2" else Normalizer
    return cls(paths.nodes, paths.alias, min_confidence=min_confidence)
