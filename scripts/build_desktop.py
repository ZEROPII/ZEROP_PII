# MediCloak 데스크톱 앱 묶기 (ADR-0039)
#
#   python scripts/build_desktop.py            화면 빌드(npm run build:demo) → PyInstaller → dist/desktop/
#   python scripts/build_desktop.py --zip      다른 컴퓨터에 보낼 압축 파일도 만든다 (macOS: MediCloak-macOS.zip)
#   python scripts/build_desktop.py --skip-frontend   frontend/dist를 이미 만들었으면
#
# 준비: pip install -r medicloak/requirements-desktop.txt (pywebview · PyInstaller), Node.js(npm).
# 그 운영체제용 앱만 만든다 (macOS 앱은 macOS에서, Windows 앱은 Windows에서).

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONT = ROOT / "frontend"
OUT = ROOT / "dist" / "desktop"
WORK = ROOT / "build" / "desktop"
SPEC = ROOT / "packaging" / "medicloak.spec"


def npm(*args: str) -> None:
    exe = shutil.which("npm") or shutil.which("npm.cmd")
    if not exe:
        raise SystemExit("npm이 없습니다. Node.js를 설치하거나, frontend/dist를 만든 뒤 --skip-frontend로 다시 부르세요.")
    subprocess.run([exe, *args], cwd=FRONT, check=True)


def built_app() -> Path:
    if sys.platform == "darwin":
        return OUT / "MediCloak.app"
    return OUT / "MediCloak" / ("MediCloak.exe" if sys.platform.startswith("win") else "MediCloak")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="MediCloak 데스크톱 앱 묶기 (PyInstaller)")
    ap.add_argument("--skip-frontend", action="store_true", help="화면 빌드를 건너뛴다 (frontend/dist가 이미 있을 때)")
    ap.add_argument("--zip", action="store_true", help="다른 컴퓨터에 보낼 압축 파일도 만든다")
    a = ap.parse_args(argv)
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        raise SystemExit("PyInstaller가 없습니다: pip install -r medicloak/requirements-desktop.txt")
    try:
        import webview  # noqa: F401
    except ImportError:
        print("[build] pywebview가 없어 창 없이 브라우저로 여는 앱이 됩니다 (pip install -r medicloak/requirements-desktop.txt)")

    if not a.skip_frontend:
        if not (FRONT / "node_modules").exists():
            print("[build] npm ci (처음 한 번)")
            npm("ci")
        print("[build] 화면 빌드: npm run build:demo")
        npm("run", "build:demo")
    if not (FRONT / "dist" / "index.html").exists():
        raise SystemExit("frontend/dist/index.html이 없습니다. --skip-frontend 없이 다시 부르세요.")

    print("[build] PyInstaller로 묶습니다 (몇 분 걸립니다)")
    subprocess.run([sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm", "--clean",
                    "--distpath", str(OUT), "--workpath", str(WORK)], cwd=ROOT, check=True)
    app = built_app()
    if not app.exists():
        raise SystemExit(f"묶은 앱을 찾지 못했습니다: {app}")
    print(f"[build] 만들었습니다: {app}")

    if a.zip:
        if sys.platform == "darwin":                    # 실행 권한 · 서명을 지키려면 ditto로 묶는다
            z = OUT / "MediCloak-macOS.zip"
            subprocess.run(["ditto", "-c", "-k", "--keepParent", str(app), str(z)], check=True)
        else:
            z = Path(shutil.make_archive(str(OUT / f"MediCloak-{'Windows' if sys.platform.startswith('win') else 'Linux'}"), "zip", OUT, "MediCloak"))
        print(f"[build] 압축 파일: {z}")


if __name__ == "__main__":
    main()
