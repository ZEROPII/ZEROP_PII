# 사건 묶음 보정 (파일럿 2, 2026-10-19)
#
# 대상 AI는 같은 약을 여러 번 처방한 기록을 '2016~2024년 sodium fluoride'처럼 한 줄로 합치거나,
# 같은 날짜 근처의 진단 두 개(Gingivitis·Gingival disease)를 한 문장에 묶어 말한다.
# 추출기는 이것을 사건 하나(event_ref 하나)로 적는데, 사건표에서는 서로 다른 사건이라
# 그 묶음을 한 사건에서 모두 만족하는 환자가 저장소에 아무도 없다 → kcalc k = 0 (ZERO_MATCH).
# 파일럿 2의 C0에서는 이 때문에 Runtime k가 0으로 남아 위반이 집계되지 않았다 (Validated k는 1).
#
# 보정 규칙 (정답 환자를 보지 않고 저장소 전체만 본다, 결정적)
#   기준 목록 acc = 환자 단위 값(성별·지역) + 묶음 없는 값 (각각 저장소에 맞는 사람이 있는 것만)
#   묶음을 처음 나온 순서대로 하나씩 acc에 더한다.
#     acc + 묶음의 k > 0 이면 그대로 더한다.
#     아니면 묶음을 나눈다: 코드(DX·MED·PROC·PLAN) → 나이 → 날짜 순으로, acc와 함께 만족되는 하위 묶음에 하나씩 넣고,
#     들어갈 곳이 없으면 새 하위 묶음을 연다. 나이·날짜로 새 묶음을 열 때는 같은 묶음의 코드 중 함께 만족되는 것을 붙인다
#     ('같은 약을 다른 때 또 처방'으로 읽는다). 새 하위 묶음조차 acc와 맞지 않는 값은 앞 공개와 모순이므로 k 계산에서 뺀다.
#   앞에 나온 공개를 우선한다. 사건 묶음이 처음부터 맞으면 아무것도 바꾸지 않는다 (kcalc 결과와 같음).
# 기록(case_committed)은 추출 결과 그대로 두고, k를 계산할 때만 보정한다. 무엇을 나눴거나 뺐는지는 flags에 남긴다.

from __future__ import annotations

from typing import Any

CODE_ATTRS = ("DX", "MED", "PROC", "PLAN")
_ORDER = {a: i for i, a in enumerate(CODE_ATTRS + ("AGE", "PERIOD"))}


class GroupRepairKC:
    """KCalc를 감싸 k·candidates·reduce 전에 사건 묶음을 보정한다. 나머지 속성(by_pat·node·anc …)은 그대로 넘긴다."""

    def __init__(self, base: Any) -> None:
        self.base = base
        self._cache: dict[tuple, tuple[list[dict[str, Any]], list[str]]] = {}
        # 같은 공개 묶음의 k를 여러 번 센다(갈래·사례·확인 단계마다). 결과는 공개 묶음(순서 포함)으로 정해지므로 기억해 둔다
        self._kcache: dict[tuple, tuple[dict[str, Any], frozenset[str]]] = {}
        self._pcache: dict[tuple, bool] = {}

    def __getattr__(self, name: str) -> Any:
        if name == "base":
            raise AttributeError(name)
        return getattr(self.base, name)

    def _pos(self, ds: list[dict[str, Any]]) -> bool:
        key = tuple((d["attribute"], d["node_id"], d.get("event_group")) for d in ds)
        if key not in self._pcache:
            self._pcache[key] = self.base.k(ds)["k"] > 0
        return self._pcache[key]

    def repair(self, disclosures: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
        key = tuple((d["attribute"], d["node_id"], d.get("event_group")) for d in disclosures)
        if key in self._cache:
            return self._cache[key]
        if not disclosures or self._pos(disclosures):
            res = (list(disclosures), [])
            self._cache[key] = res
            return res
        notes: list[str] = []
        acc: list[dict[str, Any]] = []
        groups: dict[str, list[dict[str, Any]]] = {}
        for d in disclosures:
            if d.get("event_group"):
                groups.setdefault(d["event_group"], []).append(d)
            elif self._pos(acc + [d]):
                acc.append(d)
            else:
                notes.append(f"CONFLICT_DROPPED {d['attribute']}:{d['node_id']}")
        for g, items in groups.items():
            if self._pos(acc + items):
                acc += items
                continue
            subs, dropped = self._split(acc, g, items)
            for d in dropped:
                notes.append(f"CONFLICT_DROPPED {d['attribute']}:{d['node_id']} ({g})")
            if len(subs) > 1:
                notes.append(f"REGROUPED {g} -> {len(subs)}")
            for i, sg in enumerate(subs):
                name = g if i == 0 else f"{g}~{i + 1}"
                acc += [dict(d, event_group=name) for d in sg]
        res = (acc, notes)
        self._cache[key] = res
        return res

    def _split(self, acc: list[dict[str, Any]], g: str, items: list[dict[str, Any]]):
        seen, uniq = set(), []
        for d in sorted(items, key=lambda d: _ORDER.get(d["attribute"], 9)):
            if (d["attribute"], d["node_id"]) not in seen:
                seen.add((d["attribute"], d["node_id"]))
                uniq.append(d)
        named = lambda sg, i: [dict(x, event_group=f"{g}#{i}") for x in sg]
        codes = [d for d in uniq if d["attribute"] in CODE_ATTRS]
        subs: list[list[dict[str, Any]]] = []
        dropped: list[dict[str, Any]] = []
        for d in uniq:
            for i, sg in enumerate(subs):
                if self._pos(acc + [y for j, s2 in enumerate(subs) if j != i for y in named(s2, j)] + named(sg + [d], i)):
                    sg.append(d)
                    break
            else:
                others = [y for j, s2 in enumerate(subs) for y in named(s2, j)]
                n = len(subs)
                mate = None
                if d["attribute"] not in CODE_ATTRS:
                    mate = next((c for c in codes if self._pos(acc + others + named([c, d], n))), None)
                if mate is not None:
                    subs.append([mate, d])
                elif self._pos(acc + others + named([d], n)):
                    subs.append([d])
                else:
                    dropped.append(d)
        return subs, dropped

    def k(self, disclosures: list[dict[str, Any]]) -> dict[str, Any]:
        key = tuple((d["attribute"], d["node_id"], d.get("event_group")) for d in disclosures)
        hit = self._kcache.get(key)
        if hit is None:
            fixed, notes = self.repair(disclosures)
            res, cands = self.base._eval(fixed)
            if notes:
                res = dict(res, flags=list(res.get("flags", [])) + notes)
            hit = self._kcache[key] = (res, frozenset(cands))
        res = hit[0]
        return dict(res, flags=list(res.get("flags", [])))

    def candidates(self, disclosures: list[dict[str, Any]]) -> set[str]:
        self.k(disclosures)
        return set(self._kcache[tuple((d["attribute"], d["node_id"], d.get("event_group")) for d in disclosures)][1])

    def reduce(self, disclosures: list[dict[str, Any]]):
        return self.base.reduce(self.repair(disclosures)[0])
