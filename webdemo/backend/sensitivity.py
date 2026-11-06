# 민감도 등급 (ADR-0032, 연구자 4인 검토 P2-3)
#
# 후보 수(k)는 '누구인지'만 본다. 그런데 정신 건강 · 물질 사용 · 생식(피임 · 임신) · HIV 같은 값은 한 번 알려지면 피해가 크고,
# 진단을 가려도 약 이름이 진단을 그대로 알려 준다 (통합 체험: 'levonorgestrel 자궁 내 장치 [Mirena]' → 피임, 'buprenorphine/naloxone'
# → 아편유사제 사용 장애). 그래서 값마다 등급을 매기고, 등급이 높은 값은 더 엄격하게 다룬다.
#
#   등급 3  미성년 시기에 물질 사용 장애 진단을 받은 과거 환자: 유사 사례 검색에서 기본으로 뺀다 (후보 수 계산의 기준 집단에는 남는다).
#   등급 2  정신 건강 · 물질 사용 · 생식 · HIV/성매개 감염 진단과, 그 진단을 거꾸로 알려 주는 약: 내보낸 뒤 후보가 strict_k(기본 10명)
#           미만이면 그대로 내지 않는다. 민감하지 않은 상위 범주로 넓혀 strict_k를 넘으면 그 범주로, 아니면 가린다.
#   등급 1  암: 표시만 한다 (임상 판단에 꼭 필요한 정보라 더 막지 않는다).
# 판정은 온톨로지의 상위 노드(ICD-10 범주 · 블록 · 장, ATC 분류)와 성분 이름으로 한다. 표는 진료과 · 보호 담당자와 함께 다듬는다.

from __future__ import annotations

import re
from typing import Any

#: 범주 → (등급, 화면 이름)
CATEGORY: dict[str, tuple[int, str]] = {
    "SUD": (2, "물질 사용"),
    "MENTAL": (2, "정신 건강"),
    "REPRO": (2, "생식 · 피임 · 임신"),
    "HIV": (2, "HIV · 성매개 감염"),
    "CANCER": (1, "암"),
}
STRICT_GRADE = 2
DEFAULT_STRICT_K = 10
MINOR_AGE = 19                                          # 이 나이 미만에 받은 진단을 '미성년 시기'로 본다

# 진단: 조상 노드 이름 (ICD-10-CM 블록 · 장 · 세 자리 범주)
_DX_ANC: dict[str, tuple[str, ...]] = {
    "SUD": ("DX_ICD_SECTION_F10-F19",),
    "MENTAL": ("DX_ICD_CHAPTER_5",),
    "REPRO": ("DX_ICD_CHAPTER_15",) + tuple(f"DX_ICD_CODE_Z3{i}" for i in range(10)),
    "HIV": ("DX_ICD_SECTION_B20", "DX_ICD_CODE_B20", "DX_ICD_CODE_Z21", "DX_ICD_SECTION_A50-A64"),
    "CANCER": ("DX_ICD_CHAPTER_2",),
}
# 약: ATC 분류와 성분 · 상표 이름 (진단을 거꾸로 알려 주는 약)
_MED_ATC: dict[str, tuple[str, ...]] = {
    "REPRO": ("MED_ATC_G03A", "MED_ATC_G02B"),
    "SUD": ("MED_ATC_N07B",),
    "MENTAL": ("MED_ATC_N05A", "MED_ATC_N06A"),
    "HIV": ("MED_ATC_J05AR", "MED_ATC_J05AE", "MED_ATC_J05AF", "MED_ATC_J05AG", "MED_ATC_J05AJ"),
}
_MED_WORDS: dict[str, tuple[str, ...]] = {
    "REPRO": ("levonorgestrel", "etonogestrel", "norethindrone", "ethinyl estradiol", "drospirenone", "norgestimate", "desogestrel",
              "medroxyprogesterone", "ulipristal", "mirena", "kyleena", "liletta", "skyla", "nexplanon", "depo-provera"),
    "SUD": ("buprenorphine", "methadone", "naltrexone", "disulfiram", "acamprosate", "naloxone"),
    "MENTAL": ("sertraline", "fluoxetine", "escitalopram", "citalopram", "paroxetine", "venlafaxine", "duloxetine", "bupropion",
               "quetiapine", "aripiprazole", "risperidone", "olanzapine", "lithium", "haloperidol", "clozapine", "trazodone"),
    "HIV": ("tenofovir", "emtricitabine", "efavirenz", "dolutegravir", "raltegravir", "abacavir", "zidovudine", "darunavir",
            "bictegravir"),
}
# 시술 · 관리 계획: 이름의 낱말
_OTHER_WORDS: dict[str, tuple[str, ...]] = {
    "REPRO": ("contracept", "abortion", "termination of pregnancy", "intrauterine", "prenatal", "pregnancy"),
    "SUD": ("substance", "detoxification", "opioid", "alcohol use", "drug use"),
    "MENTAL": ("psychotherapy", "psychiatric", "mental health", "suicide", "depression", "anxiety"),
    "HIV": ("hiv", "human immunodeficiency virus"),
}


def _rx(words: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(r"(?<![a-z])(?:" + "|".join(re.escape(w) for w in words) + r")", re.I)


_MED_RX = {c: _rx(w) for c, w in _MED_WORDS.items()}
_OTHER_RX = {c: _rx(w) for c, w in _OTHER_WORDS.items()}


def _categories(data: Any, node: str) -> frozenset[str]:
    if node not in data.N:
        return frozenset()
    att = data.N[node]["attribute"]
    anc = set(data.anc(node))
    out: set[str] = set()
    if att == "DX":
        for c, keys in _DX_ANC.items():
            if anc & set(keys):
                out.add(c)
        if "SUD" in out:
            out.discard("MENTAL")                      # 물질 사용은 정신 건강 장(F)에도 들지만 따로 센다
    elif att == "MED":
        labels = " ".join(data.label(a) for a in anc)
        for c, keys in _MED_ATC.items():
            if anc & set(keys) or _MED_RX[c].search(labels):
                out.add(c)
    elif att in ("PROC", "PLAN"):
        label = data.label(node)
        for c, rx in _OTHER_RX.items():
            if rx.search(label):
                out.add(c)
    return frozenset(out)


def categories(data: Any, node: str | None) -> frozenset[str]:
    """노드가 드는 민감 범주. 모르는 노드 · 없으면 빈 집합. 데이터 객체마다 한 번씩 세어 둔다."""
    if not node:
        return frozenset()
    cache = data.__dict__.setdefault("_sensitivity_cache", {})
    hit = cache.get(node)
    if hit is None:
        hit = cache[node] = _categories(data, node)
    return hit


def grade(data: Any, node: str | None) -> int:
    return max((CATEGORY[c][0] for c in categories(data, node)), default=0)


def labels(data: Any, node: str | None) -> list[str]:
    return [CATEGORY[c][1] for c in sorted(categories(data, node), key=lambda c: (-CATEGORY[c][0], c))]


class Sensitivity:
    """한 서버의 민감도 정책. strict(node)는 등급 2 이상인지. excluded는 유사 사례 검색에서 뺄 과거 환자."""

    def __init__(self, data: Any, *, strict_k: int = DEFAULT_STRICT_K, exclude_minor_sud: bool = True,
                 store_patients: set[str] | None = None) -> None:
        self.data = data
        self.strict_k = int(strict_k)
        self.excluded: frozenset[str] = frozenset(minor_sud_patients(data, store_patients)) if exclude_minor_sud else frozenset()

    def strict(self, node: str | None) -> bool:
        return grade(self.data, node) >= STRICT_GRADE

    def describe(self) -> dict[str, Any]:
        return dict(on=True, strictK=self.strict_k, excludedPatients=len(self.excluded),
                    categories=[dict(name=v[1], grade=v[0]) for v in sorted(CATEGORY.values(), key=lambda v: -v[0])])


def minor_sud_patients(data: Any, patients: set[str] | None = None) -> set[str]:
    """미성년 시기(MINOR_AGE 미만)에 물질 사용 장애 진단을 받은 환자."""
    out = set()
    for pid, evs in data.by_pat.items():
        if patients is not None and pid not in patients:
            continue
        for e in evs:
            if e["event_type"] != "CONDITION" or "SUD" not in categories(data, e["code_node"]):
                continue
            try:
                age = int(float(e.get("age_years_at_start") or 99))
            except ValueError:
                continue
            if age < MINOR_AGE:
                out.add(pid)
                break
    return out
