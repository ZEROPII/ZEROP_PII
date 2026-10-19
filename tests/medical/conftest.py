from __future__ import annotations

import pytest

from medical.bundle.kcalc import KCalc
from medical.bundle.normalize_bridge import Normalizer
from medical.config import MedicalPaths
from medical.data import MedicalData

EXAMPLE_PID = "e67f5054-bf0e-0bea-2c00-23094ec924d7"   # 묶음 예시 문서의 환자 (보스턴, 여성, 진단 16개)


@pytest.fixture(scope="session")
def paths() -> MedicalPaths:
    return MedicalPaths()


@pytest.fixture(scope="session")
def data(paths: MedicalPaths) -> MedicalData:
    return MedicalData(paths)


@pytest.fixture(scope="session")
def kc(paths: MedicalPaths) -> KCalc:
    return KCalc(paths.nodes, paths.events)


@pytest.fixture(scope="session")
def nz(paths: MedicalPaths) -> Normalizer:
    return Normalizer(paths.nodes, paths.alias)
