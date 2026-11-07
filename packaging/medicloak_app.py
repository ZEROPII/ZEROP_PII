# 묶은 앱(PyInstaller)의 시작점 (ADR-0039)
#
#   명령 없이 켜면(Finder · 시작 메뉴에서 두 번 누름) 데스크톱 앱: python -m medicloak app 과 같다.
#   명령을 주면 python -m medicloak 과 같다. 예: MediCloak.app/Contents/MacOS/MediCloak users list

import multiprocessing
import sys

COMMANDS = {"init", "serve", "app", "check-llm", "users", "assign"}


def argv(args: list[str]) -> list[str]:
    args = [a for a in args if not a.startswith("-psn_")]          # 예전 macOS가 Finder에서 붙이던 인자
    head, rest = (args[:2], args[2:]) if args[:1] == ["--db"] else ([], args)
    if not (rest[:1] and rest[0] in COMMANDS) and not {"-h", "--help"} & set(rest):
        rest = ["app", *rest]
    return head + rest


def run() -> None:
    from medicloak.cli import main
    main(argv(sys.argv[1:]))


if __name__ == "__main__":
    multiprocessing.freeze_support()
    run()
