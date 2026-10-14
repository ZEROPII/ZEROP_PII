# 기준 집단 변형
#
# 이름 규칙
#   synthpai-300   → SynthPAI 원본 300명만 (설계서의 P_ref. 실제 속성 간 관계를 그대로 가진다)
#   indep-N        → 원본 300명 + 합성 인원 N-300명 (현재 30만 파일에서 무작위 추출. 속성을 서로 독립으로 만든 집단)
#   joint-N        → indep-N과 같은 사람들이되, 합성 인원의 출생 국가를 원본의 "출생 국가 = 거주 국가" 비율에 맞춰
#                    거주 국가로 바꾼 집단. 30만 집단에서 끊어진 거주–출생 관계를 되살린 비교용 변형이다
#
# 모든 변형은 하나의 공통 온톨로지와 해석 규칙을 쓴다. 변형마다 온톨로지를 따로 만들면 같은 표현이
# 다른 node로 풀려 조건끼리 비교할 수 없기 때문이다.
#
# 이 파일은 팀원의 생성 스크립트와 데이터 파일을 고치지 않는다. 변형은 메모리에서만 만든다.
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from adapters.risk_adapter import PopulationMode, ReferencePopulation, load_reference_population
from ontology.builder import PROFILE_FIELD_BY_QI, build_ontology
from ontology.index import PopulationIndex
from ontology.isco import load_occupation_table
from ontology.mapper import ProfileMapper
from ontology.model import Ontology
from ontology.parsing import Parser

LOC_FIELD, POB_FIELD = PROFILE_FIELD_BY_QI["LOC"], PROFILE_FIELD_BY_QI["POB"]


@dataclass(frozen=True)
class PopulationSpec:
    name: str
    kind: str     # synthpai / indep / joint
    size: int

    @classmethod
    def parse(cls, name: str) -> "PopulationSpec":
        kind, _, size = name.partition("-")
        if kind not in ("synthpai", "indep", "joint") or not size.isdigit():
            raise ValueError(f"기준 집단 이름을 해석할 수 없습니다: {name} (예: synthpai-300, indep-30000, joint-300000)")
        if kind == "synthpai" and int(size) != 300:
            raise ValueError("synthpai는 300명만 있습니다.")
        if int(size) < 300:
            raise ValueError("원본 300명보다 작게 만들 수 없습니다 (대상이 빠지면 안 되므로).")
        return cls(name, kind, int(size))


class PopulationBank:
    """
    원본 30만 집단을 한 번 읽고, 요청한 변형의 색인을 만들어 둔다.

    ontology / parser → 모든 변형이 함께 쓰는 온톨로지와 해석 규칙
    master            → 원본 ReferencePopulation (대상의 정답을 찾을 때 쓴다)
    same_country_rate → 원본 300명 중 출생 국가와 거주 국가가 같은 사람의 비율 (joint 변형에 쓴다)
    """

    def __init__(self, seed: int = 7, population: ReferencePopulation | None = None) -> None:
        self.seed = seed
        self.master = population or load_reference_population(PopulationMode.EXPANDED)
        records = self.master.records
        self._profiles: list[dict[str, Any]] = [dict(r.raw_profile) for r in records]
        self._ids: list[str] = [r.person_id for r in records]
        base_ids = {r.person_id for r in load_reference_population(PopulationMode.BASE).records} \
            if population is None else {r.person_id for r in records[:300]}
        self.original_positions = [i for i, pid in enumerate(self._ids) if pid in base_ids]
        self.synthetic_positions = [i for i, pid in enumerate(self._ids) if pid not in base_ids]

        table = load_occupation_table()
        probe = build_ontology(self._profiles, occupation_table=table)
        probe_parser = Parser(probe, table)
        self.same_country_rate = self._same_country_rate(probe, probe_parser)
        self._joint_profiles = self._make_joint(probe, probe_parser)
        # 공통 온톨로지: 원본 집단 + joint 변형에서 새로 생긴 표기까지 모두 포함
        self.ontology: Ontology = build_ontology(self._profiles + [self._joint_profiles[i] for i in sorted(self._joint_profiles)],
                                                 occupation_table=table)
        self.parser = Parser(self.ontology, table)
        self._indexes: dict[str, PopulationIndex] = {}
        self._members: dict[str, list[int]] = {}

    # ── 변형 ─────────────────────────────────────────────

    def index(self, name: str) -> PopulationIndex:
        if name not in self._indexes:
            spec = PopulationSpec.parse(name)
            positions = self.members(name)
            profiles = [self._profile(spec.kind, i) for i in positions]
            self._indexes[name] = PopulationIndex(self.ontology, self.parser, profiles)
        return self._indexes[name]

    def members(self, name: str) -> list[int]:
        """변형에 들어간 사람의 원본 순번 (원본 300명은 항상 포함)"""
        if name not in self._members:
            spec = PopulationSpec.parse(name)
            if spec.kind == "synthpai":
                positions = list(self.original_positions)
            else:
                need = spec.size - len(self.original_positions)
                if need > len(self.synthetic_positions):
                    raise ValueError(f"{name}: 합성 인원이 {len(self.synthetic_positions):,}명뿐입니다.")
                rng = random.Random(f"{self.seed}:members:{spec.size}")   # indep-N과 joint-N은 같은 사람들이다
                sample = (self.synthetic_positions if need == len(self.synthetic_positions)
                          else rng.sample(self.synthetic_positions, need))
                positions = self.original_positions + sorted(sample)
            self._members[name] = positions
        return self._members[name]

    def profiles(self, name: str) -> list[Mapping[str, Any]]:
        spec = PopulationSpec.parse(name)
        return [self._profile(spec.kind, i) for i in self.members(name)]

    def fingerprint(self, name: str) -> str:
        """변형 내용의 짧은 지문 (재현 확인용)"""
        digest = hashlib.sha256()
        for profile in self.profiles(name):
            digest.update(repr(sorted(profile.items())).encode("utf-8"))
        return digest.hexdigest()[:16]

    def _profile(self, kind: str, position: int) -> Mapping[str, Any]:
        if kind == "joint" and position in self._joint_profiles:
            return self._joint_profiles[position]
        return self._profiles[position]

    # ── 거주–출생 관계 ───────────────────────────────────

    def country_of(self, ontology: Ontology, node_id: str | None) -> str | None:
        """LOC/POB node의 국가 node 코드 (예: LOC:C:CH → CH)"""
        if node_id is None:
            return None
        for candidate in (node_id, *ontology.ancestors(node_id)):
            if ontology.node(candidate).level == "country":
                return candidate.rsplit(":", 1)[-1]
        return None

    def _same_country_rate(self, ontology: Ontology, parser: Parser) -> float:
        return self._rate(ontology, ProfileMapper(ontology, parser), [self._profiles[i] for i in self.original_positions])[0]

    def _rate(self, ontology: Ontology, mapper: ProfileMapper, profiles) -> tuple[float, int]:
        same = total = 0
        cache: dict[tuple[str, str], str | None] = {}
        for profile in profiles:
            countries = []
            for qi, field in (("LOC", LOC_FIELD), ("POB", POB_FIELD)):
                value = profile.get(field)
                key = (qi, str(value))
                if key not in cache:
                    cache[key] = self.country_of(ontology, mapper.node_for(qi, value)) if value else None
                countries.append(cache[key])
            if all(countries):
                total += 1
                same += countries[0] == countries[1]
        return (same / total if total else 0.0), total

    def _make_joint(self, ontology: Ontology, parser: Parser) -> dict[int, dict[str, Any]]:
        """합성 인원 중 same_country_rate 비율만큼 출생지를 거주 국가 이름으로 바꾼다 (난수 고정)."""
        rng = random.Random(f"{self.seed}:joint")
        changed: dict[int, dict[str, Any]] = {}
        for i in self.synthetic_positions:
            if rng.random() >= self.same_country_rate:
                continue
            location = str(self._profiles[i].get(LOC_FIELD) or "")
            country = location.rsplit(",", 1)[-1].strip()
            if country:
                changed[i] = {**self._profiles[i], POB_FIELD: country}
        return changed

    def association_table(self, names: Sequence[str]) -> list[dict[str, Any]]:
        """
        변형별 "출생 국가 = 거주 국가" 비율 (원본 300명과 비교해 집단이 현실적인 관계를 갖는지 본다)
        """
        mapper = ProfileMapper(self.ontology, self.parser)
        rows = []
        for name in names:
            rate, total = self._rate(self.ontology, mapper, self.profiles(name))
            rows.append({"population": name, "size": len(self.members(name)), "same_country_rate": rate, "pairs": total})
        return rows


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
