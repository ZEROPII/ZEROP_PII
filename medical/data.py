# 의료 원자료 적재와 코호트 분리 (하네스 명세 §1·§2)
#
# 사건연결표 한 행 = 사건 하나 (CONDITION·PROCEDURE·PROCEDURE_HISTORY·MEDICATION·CAREPLAN).
# 노드 v0.10(v0.9 + PERIOD 분기 단계)은 단일 부모 계층이다 (parent_id 하나). DX·PROC 공식 다중 부모 그래프(2026-10-07 스냅샷)는
# 실행 플래그가 모두 꺼진 상태라 1차에서는 쓰지 않는다 (docs/medical.md '온톨로지 판').

from __future__ import annotations

import collections
import csv
import random
import re
from functools import lru_cache
from pathlib import Path

from medical.config import MedicalPaths

QUERY_POOL = "QUERY_POOL"
STORE = "STORE"

_SEMTAG = re.compile(r" \((disorder|procedure|regime/therapy|record artifact|finding|situation)\)$")


def read_csv(path: Path | str) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class MedicalData:
    """노드표와 사건연결표. 실행 중 바뀌지 않는다 (run 전체에서 하나를 공유)."""

    def __init__(self, paths: MedicalPaths | None = None) -> None:
        self.paths = paths or MedicalPaths()
        self.N: dict[str, dict[str, str]] = {n["node_id"]: n for n in read_csv(self.paths.nodes)}
        self.E: list[dict[str, str]] = read_csv(self.paths.events)
        self.by_pat: dict[str, list[dict[str, str]]] = collections.defaultdict(list)
        for e in self.E:
            self.by_pat[e["patient_id"]].append(e)
        self.children: dict[str, int] = collections.Counter(n["parent_id"] for n in self.N.values() if n["parent_id"])
        self._anc: dict[str, list[str]] = {}

    def anc(self, node_id: str) -> list[str]:
        """자기 자신부터 루트까지 (구체적 → 넓은 순서)."""
        if node_id not in self._anc:
            out, x = [], node_id
            while x:
                out.append(x)
                x = self.N[x]["parent_id"] if x in self.N else ""
            self._anc[node_id] = out
        return self._anc[node_id]

    def is_root(self, node_id: str) -> bool:
        return node_id in self.N and not self.N[node_id]["parent_id"]

    def depth(self, node_id: str) -> int:
        return len(self.anc(node_id)) - 1

    def label(self, node_id: str) -> str:
        """문서·질문·재작성에 쓰는 이름. SNOMED 원개념 라벨의 의미 태그만 뗀다 (별칭표와 같음)."""
        t = self.N[node_id]["canonical_label"]
        return _SEMTAG.sub("", t) if "_SCT_" in node_id else t

    def patients(self) -> list[str]:
        return sorted(self.by_pat)


def split_cohort(data: MedicalData, ratio: float, seed: int) -> dict[str, str]:
    """명세 §2. patient_id 정렬 → Random(seed).shuffle → 앞 round(n×ratio)명 = QUERY_POOL, 나머지 = STORE."""
    pids = data.patients()
    rng = random.Random(seed)
    rng.shuffle(pids)
    nq = round(len(pids) * ratio)
    return {p: (QUERY_POOL if i < nq else STORE) for i, p in enumerate(pids)}


def write_split(split: dict[str, str], seed: int, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["patient_id", "split", "seed"])
        for p, s in sorted(split.items()):
            w.writerow([p, s, seed])


@lru_cache(maxsize=4)
def load_data(paths: MedicalPaths | None = None) -> MedicalData:
    return MedicalData(paths)
