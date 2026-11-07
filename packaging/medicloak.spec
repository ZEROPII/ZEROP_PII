# -*- mode: python -*-
# PyInstaller 묶음 설정 (ADR-0039). 직접 부르지 말고 python scripts/build_desktop.py 로 만든다.
#
#   macOS    dist/desktop/MediCloak.app
#   Windows  dist/desktop/MediCloak/MediCloak.exe
#   Linux    dist/desktop/MediCloak/MediCloak   (창 없이 점검용: MediCloak app --no-window --llm oracle)
#
# 앱 안에는 코드 · 화면(frontend/dist) · 가상 EMR 원본 표 · Seed 표 · 보고서 PDF 글꼴만 넣는다.
# DB · .env · 기록은 켤 때 사용자 앱 데이터 폴더에 만든다 (medicloak/paths.py). .env · runs/ · 키는 넣지 않는다.

import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent          # noqa: F821 (PyInstaller가 넣어 준다)
sys.path.insert(0, str(ROOT))
from medical.config import MedicalPaths          # noqa: E402  (원본 표 판이 바뀌어도 여기는 그대로)

ICONS = ROOT / "packaging" / "icons"
if not (ROOT / "frontend" / "dist" / "index.html").exists():
    raise SystemExit("frontend/dist가 없습니다. python scripts/build_desktop.py 로 만드세요 (화면을 먼저 빌드합니다).")


def rel(p: Path) -> str:
    return str(p.resolve().relative_to(ROOT).parent)


tables = [Path(getattr(MedicalPaths(), f)) for f in MedicalPaths.__dataclass_fields__]
datas = [(str(ROOT / "frontend" / "dist"), "frontend/dist"),
         (str(ROOT / "medicloak" / "desktop_start.html"), "medicloak"),
         (str(ROOT / "scripts" / "build_terminology_db.py"), "scripts")]          # 용어 DB가 없을 때 medical/term_service.py가 읽는다
datas += [(str(p), rel(p)) for p in tables]
datas += [(str(ROOT / "webdemo" / "backend" / "fonts"), "webdemo/backend/fonts")]   # 유사 사례 보고서 PDF 글꼴 (ADR-0042, OFL)
datas += collect_data_files("fpdf")
for extra in (ROOT / "data" / "medical" / "terminology.db", ROOT / "webdemo" / "data" / "poc_summary.json"):
    if extra.exists():                                                            # 있으면 넣는다 (설명이 채워진 용어 DB 등)
        datas.append((str(extra), rel(extra)))

hidden = (collect_submodules("webdemo.backend") + collect_submodules("core")
          + collect_submodules("medical", filter=lambda n: not n.startswith(("medical.scoring", "medical.__main__")))
          + collect_submodules("uvicorn") + ["medicloak.cli", "medicloak.desktop", "medicloak.paths"]
          + collect_submodules("fpdf") + collect_submodules("fontTools.ttLib.tables"))       # PDF: 글꼴 표는 이름으로 불러온다

# 서버와 창에 쓰지 않는 큰 꾸러미 (분석 · 시험 · 다른 GUI 백엔드 · 엑셀 그림 · pywebview의 https 인증서 만들기)
excludes = ["matplotlib", "tkinter", "pytest", "IPython", "notebook", "PIL", "lxml", "cryptography", "PySide2", "PySide6", "PyQt5", "PyQt6", "qtpy", "gi", "cefpython3"]

a = Analysis([str(ROOT / "packaging" / "medicloak_app.py")], pathex=[str(ROOT)], datas=datas, hiddenimports=hidden,
             excludes=excludes, noarchive=False)                                 # noqa: F821
pyz = PYZ(a.pure)                                                                 # noqa: F821
icon = str(ICONS / ("MediCloak.icns" if sys.platform == "darwin" else "MediCloak.ico"))
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MediCloak", console=sys.platform.startswith("linux"),
          icon=icon, upx=False)                                                   # noqa: F821
coll = COLLECT(exe, a.binaries, a.datas, name="MediCloak", upx=False)             # noqa: F821

if sys.platform == "darwin":
    release = re.search(r'RELEASE_VERSION = "medicloak-release-v(\d+)"', (ROOT / "webdemo" / "backend" / "review.py").read_text(encoding="utf-8"))
    version = f"{release.group(1) if release else 0}.0"
    app = BUNDLE(coll, name="MediCloak.app", icon=str(ICONS / "MediCloak.icns"), bundle_identifier="io.github.zeropii.medicloak",  # noqa: F821
                 info_plist={
                     "CFBundleName": "MediCloak", "CFBundleDisplayName": "MediCloak", "CFBundleDevelopmentRegion": "ko",
                     "CFBundleShortVersionString": version, "CFBundleVersion": version,
                     "LSApplicationCategoryType": "public.app-category.medical", "NSHighResolutionCapable": True,
                     # 창(WKWebView)이 이 컴퓨터의 서버(http://127.0.0.1)와 병원 서버를 열 수 있게
                     "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True, "NSAllowsArbitraryLoadsInWebContent": True},
                 })
