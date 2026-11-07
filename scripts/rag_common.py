"""RAG 기준 재측정(요청서 2026-11-05 R2~R6) 스크립트가 같이 쓰는 것.

- 실행 폴더 읽기: run_meta.json · trial요약.json(또는 trials.jsonl) · 턴기록.jsonl · RAG문서.jsonl · 코호트분리.csv
- 후보 수: 실행과 같은 KCalc + GroupRepairKC (기준 집단 = STORE 환자)
- 값 하나를 가진 환자 집합(비트 집합): 사건 연결 없이 '그 값을 가진 환자'만 센다 (기준 희귀도 · 층화에 쓴다)
- 위반 = 1 <= k < k_req (k = 0은 대조 불일치, 위반이 아님). 0건이면 단측 95% 상한 1 - 0.05^(1/n)
연구 모듈(medical/)은 읽기만 한다.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ARM_ORDER = ("C0", "C1S", "C1", "C1G")
PATIENT_LEVEL = ("SEX", "REGION")


def ub95(n: int) -> float | None:
    return 1 - 0.05 ** (1 / n) if n else None


def rate(a: int, n: int) -> dict[str, Any]:
    d: dict[str, Any] = dict(n=n, violated=a, rate=round(a / n, 4) if n else None)
    if n and a == 0:
        d["upper95_one_sided"] = round(ub95(n), 4)
    return d


def fmt(d: dict[str, Any] | None) -> str:
    if not d or not d.get("n"):
        return "-"
    s = f"{d['violated']}/{d['n']} ({100 * d['rate']:.1f}%)"
    return s + (f" [0건, 단측 95% 상한 {100 * d['upper95_one_sided']:.1f}%]" if "upper95_one_sided" in d else "")


def sha256(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def arm_sorted(arms: Any) -> list[str]:
    return sorted(set(arms), key=lambda x: ARM_ORDER.index(x) if x in ARM_ORDER else 9)


def violated(k: Any, k_req: int) -> bool:
    return isinstance(k, int) and 1 <= k < k_req


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        if not rows and not fields:
            f.write("")
            return
        w = csv.DictWriter(f, fieldnames=fields or list(rows[0]), extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# ── 실행 폴더 ─────────────────────────────────────────────────────

class Run:
    """실행 폴더 하나. 대화 열쇠 = (trial_id, arm, repeat). repeat이 없는 예전 기록은 0."""

    def __init__(self, path: str | Path) -> None:
        self.path = p = Path(path)
        self.meta = json.loads((p / "run_meta.json").read_text(encoding="utf-8")) if (p / "run_meta.json").exists() else {}
        self.cfg = self.meta.get("config", {})
        if not self.cfg and (p / "trial요약.json").exists():
            self.cfg = json.loads((p / "trial요약.json").read_text(encoding="utf-8")).get("config", {})
        self.k_req = int(self.cfg.get("k_req", 5))
        self.trials = self._trials()
        self.doc2pid: dict[str, str] = {}
        with open(p / "RAG문서.jsonl", encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                self.doc2pid[d["doc_id"]] = d["patient_id"]
        self.store = {r["patient_id"] for r in read_csv(p / "코호트분리.csv") if r["split"] == "STORE"}

    def _trials(self) -> list[dict[str, Any]]:
        p = self.path
        if (p / "trials.jsonl").exists():                 # rag_remeasure.py: 끝난 대화마다 한 줄 (중간에 멈춰도 남는다)
            rows = [json.loads(x) for x in (p / "trials.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
            if rows:
                return rows
        if (p / "trial요약.json").exists():
            return json.loads((p / "trial요약.json").read_text(encoding="utf-8"))["trials"]
        return []

    @staticmethod
    def key(rec: dict[str, Any]) -> tuple[str, str, int]:
        return (rec["trial_id"], rec["arm"], int(rec.get("repeat") or 0))

    def refs(self, t: dict[str, Any]) -> dict[str, str]:
        """사례N → 저장소 환자 ID (검색 순위 N)."""
        return {f"사례{i + 1}": self.doc2pid[d] for i, d in enumerate(t.get("retrieved_doc_ids") or []) if d in self.doc2pid}

    def records(self) -> Iterator[dict[str, Any]]:
        with open(self.path / "턴기록.jsonl", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if r.get("invalid_mutation") or r.get("turn") is None:
                    continue
                yield r

    def kc(self) -> Any:
        from medical.bundle.kcalc import KCalc
        from medical.config import MedicalPaths
        from medical.grouping import GroupRepairKC
        paths = MedicalPaths()
        return GroupRepairKC(KCalc(paths.nodes, paths.events, exclude_provisional_atc=self.cfg.get("exclude_provisional_atc", False),
                                   patients=self.store))


def committed_of(case_rec: dict[str, Any], ref: str) -> list[dict[str, Any]]:
    """턴기록 cases[ref].normalized 가운데 State에 들어간(commit) 단서. 사건 묶음은 '사례N:사건'."""
    out = []
    for o in case_rec.get("normalized") or []:
        if o.get("commit") and o.get("node_id"):
            ev = o.get("event_ref")
            out.append(dict(attribute=o["attribute"], node_id=o["node_id"], event_group=f"{ref}:{ev}" if ev else None))
    return out


def stable_event(label: str | None) -> bool:
    """결정적 응답기는 사건 표지를 원본 사건으로 붙인다('e_…'): 대화가 달라도 같은 사건. 실제 LLM 추출은 'e1' 같은 대화 안 번호."""
    return bool(label) and str(label).startswith("e_")


def global_group(d: dict[str, Any], pid: str, conv: str) -> dict[str, Any]:
    """대화 간 합산용 사건 묶음: 원본 사건 표지면 환자 단위로 합치고, 대화 안 번호면 대화마다 따로 둔다."""
    eg = d.get("event_group")
    if not eg:
        return dict(d)
    label = eg.split(":", 1)[1] if ":" in eg else eg
    return dict(d, event_group=f"{pid}:{label}" if stable_event(label) else f"{pid}:{conv}:{label}")


# ── 값을 가진 환자 집합 (비트) ──────────────────────────────────────

class HasIndex:
    """(단서 종류, 노드) → 그 값을 가진 STORE 환자 비트 집합. webdemo/backend/gate.py의 has와 같은 정의."""

    def __init__(self, kc: Any) -> None:
        self.base = getattr(kc, "base", kc)
        self.pids = sorted(self.base.by_pat)
        self.bit = {p: 1 << i for i, p in enumerate(self.pids)}
        self._has: dict[tuple[str, str], int] = {}

    def has(self, attribute: str, node: str) -> int:
        key = (attribute, node)
        hit = self._has.get(key)
        if hit is None:
            b, v = self.base, 0
            if attribute in PATIENT_LEVEL:
                for p, a in b.pat.items():
                    if node in a.get(attribute, ()):
                        v |= self.bit[p]
            else:
                for p, idx in b.by_pat.items():
                    if any(node in b.ev_anc[i] for i in idx):
                        v |= self.bit[p]
            self._has[key] = hit = v
        return hit

    def count(self, mask: int) -> int:
        return mask.bit_count()


def baseline_rarity(hx: HasIndex, clues: list[tuple[str, str]], pid: str, k_req: int = 5, exact_upto: int = 3) -> dict[str, Any]:
    """
    기준 희귀도: 이 환자의 원본 단서(문서 사실 줄의 값) 가운데 몇 개를 공개하면 후보가 k_req 아래로 내려가는가의 최솟값.
    사건 연결 없이 '그 값을 가진 환자'의 교집합으로 센다 (같은 사건으로 묶으면 더 빨리 내려갈 수 있다 → 이 값은 상한).
    exact_upto개까지는 모든 조합을 보고, 그 위는 욕심쟁이(후보를 가장 많이 줄이는 값부터)로 센다.
    """
    me = hx.bit[pid]
    masks = []
    seen = set()
    for a, n in clues:
        if (a, n) in seen:
            continue
        seen.add((a, n))
        m = hx.has(a, n)
        if m & me:                                      # 자기 값이 아닌 노드(사실표 오류)는 뺀다
            masks.append(((a, n), m))
    masks.sort(key=lambda x: x[1].bit_count())
    n_all = len(hx.pids)
    out: dict[str, Any] = dict(n_clues=len(masks), min_clues=None, method=None, example=None,
                               k_single_min=min((m.bit_count() for _, m in masks), default=n_all))
    for size in range(1, exact_upto + 1):
        best = _exact(masks, size, k_req)
        if best is not None:
            out.update(min_clues=size, method="exact", example=[f"{a}:{n}" for a, n in best])
            return out
    cur, chosen = (1 << n_all) - 1, []
    left = list(masks)
    while left and cur.bit_count() >= k_req:
        (c, m) = min(left, key=lambda x: (cur & x[1]).bit_count())
        if (cur & m).bit_count() == cur.bit_count():
            break
        cur &= m
        chosen.append(c)
        left = [x for x in left if x[0] != c]
    if cur.bit_count() < k_req:
        out.update(min_clues=len(chosen), method="greedy_upper", example=[f"{a}:{n}" for a, n in chosen])
    else:
        out.update(min_clues=None, method="not_reached", example=None)
    return out


def _exact(masks: list[tuple[tuple[str, str], int]], size: int, k_req: int) -> list[tuple[str, str]] | None:
    import itertools
    if size == 1:
        for c, m in masks:
            if m.bit_count() < k_req:
                return [c]
        return None
    pool = masks[:80]                                   # 희귀한 값 80개 안에서 찾는다 (흔한 값은 조합에 거의 쓸모가 없다)
    for combo in itertools.combinations(pool, size):
        m = combo[0][1]
        for _, x in combo[1:]:
            m &= x
            if m.bit_count() < k_req:
                break
        if m.bit_count() < k_req:
            return [c for c, _ in combo]
    return None


def sensitive_groups(data: Any, nodes: list[str]) -> list[str]:
    """요청서의 민감 진단 층: 생식 · 물질사용 · 암 · 정신 (webdemo/backend/sensitivity.py 범주 이름으로)."""
    from webdemo.backend.sensitivity import categories
    names = dict(REPRO="생식", SUD="물질사용", CANCER="암", MENTAL="정신", HIV="HIV")
    got: set[str] = set()
    for n in nodes:
        for c in categories(data, n):
            got.add(names.get(c, c))
    return sorted(got)
