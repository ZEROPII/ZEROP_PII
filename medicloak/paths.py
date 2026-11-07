# MediCloak이 쓰는 폴더 (ADR-0039)
#
#   저장소에서 켤 때(python -m medicloak …): runs/medicloak/ (runs/는 커밋하지 않는다)
#   묶은 앱(PyInstaller)으로 켤 때: 사용자 앱 데이터 폴더. 앱 안(읽기 전용)에는 쓰지 않는다
#       macOS    ~/Library/Application Support/MediCloak
#       Windows  %APPDATA%\MediCloak
#       Linux    $XDG_DATA_HOME/medicloak (없으면 ~/.local/share/medicloak)
#   MEDICLOAK_HOME 환경변수가 있으면 어느 쪽이든 그 폴더를 쓴다.
#
# 무거운 모듈을 부르지 않는다 (앱이 켜지자마자 읽는다).

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_NAME = "MediCloak"


def is_frozen() -> bool:
    """PyInstaller로 묶은 앱에서 돌고 있는지."""
    return bool(getattr(sys, "frozen", False))


def user_data_dir(platform: str | None = None, env: dict[str, str] | None = None, home: Path | None = None) -> Path:
    """운영체제의 사용자 앱 데이터 폴더 (만들지는 않는다)."""
    platform = platform or sys.platform
    env = os.environ if env is None else env
    home = home or Path.home()
    if platform == "darwin":
        return home / "Library" / "Application Support" / APP_NAME
    if platform.startswith("win"):
        base = env.get("APPDATA") or env.get("LOCALAPPDATA")
        return Path(base) / APP_NAME if base else home / "AppData" / "Roaming" / APP_NAME
    base = env.get("XDG_DATA_HOME")
    return (Path(base) if base else home / ".local" / "share") / APP_NAME.lower()


def app_home(env: dict[str, str] | None = None) -> Path:
    """DB · .env · 기록을 두는 폴더."""
    env = os.environ if env is None else env
    if env.get("MEDICLOAK_HOME"):
        return Path(env["MEDICLOAK_HOME"]).expanduser()
    if is_frozen():
        return user_data_dir(env=env)
    return ROOT / "runs" / "medicloak"


def default_env_file(home: Path | None = None) -> Path | None:
    """읽을 .env. 저장소에서는 None(저장소 루트의 .env, core/config.py 기본), 묶은 앱에서는 앱 데이터 폴더의 .env."""
    return (home or app_home()) / ".env" if is_frozen() else None
