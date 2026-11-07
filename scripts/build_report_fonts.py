# 보고서 PDF용 글꼴 만들기 (ADR-0042): Wanted Sans(OFL-1.1) 정적 TTF를 보고서에 쓰는 글자만 남겨 줄인다.
#
#   python scripts/build_report_fonts.py        frontend/node_modules/wanted-sans에서 읽어 webdemo/backend/fonts/에 쓴다
#
# 남기는 글자: 기본 라틴 · 라틴-1 보충 · 일반 구두점 · 화살표 · 한글 호환 자모 · KS X 1001 완성형 한글 2,350자 · 전각 기호.
# 진단 · 약 이름은 영문(온톨로지 표준 이름)이고, 한글은 화면 문구와 범위 표기('5~9세', '2014년')뿐이라 완성형으로 충분하다.
# 만든 의료진 이름에 완성형 밖 글자(예: '똠')가 있으면 그 글자만 PDF에서 빈칸으로 나온다.
# 글꼴 파일을 바꾸면 이 스크립트를 다시 돌린다 (npm install이 먼저 필요).

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from fontTools import subset

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "node_modules" / "wanted-sans" / "fonts"
OUT = ROOT / "webdemo" / "backend" / "fonts"
WEIGHTS = ("Regular", "Bold")


def ks_x_1001_hangul() -> list[int]:
    """EUC-KR 두 바이트 B0A1~C8FE에 있는 완성형 한글 2,350자."""
    out = []
    for hi in range(0xB0, 0xC9):
        for lo in range(0xA1, 0xFF):
            try:
                out.append(ord(bytes([hi, lo]).decode("euc-kr")))
            except UnicodeDecodeError:
                pass
    return out


def unicodes() -> list[int]:
    ranges = [(0x20, 0x7E), (0xA0, 0xFF), (0x2010, 0x2027), (0x2030, 0x205E), (0x2190, 0x21FF), (0x2460, 0x24FF),
              (0x25A0, 0x25FF), (0x3000, 0x303F), (0x3131, 0x318E), (0xFF01, 0xFF5E)]
    cps = {c for a, b in ranges for c in range(a, b + 1)}
    return sorted(cps | set(ks_x_1001_hangul()))


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"{SRC}가 없습니다. frontend에서 npm install을 먼저 하세요.")
    OUT.mkdir(parents=True, exist_ok=True)
    opts = subset.Options()
    opts.layout_features = ["*"]
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    for w in WEIGHTS:
        font = subset.load_font(str(SRC / "ttf" / f"WantedSans-{w}.ttf"), opts)
        s = subset.Subsetter(opts)
        s.populate(unicodes=unicodes())
        s.subset(font)
        dst = OUT / f"WantedSans-Report-{w}.ttf"
        subset.save_font(font, str(dst), opts)
        print(f"{dst.relative_to(ROOT)} {dst.stat().st_size // 1024}KB")
    shutil.copy(SRC / "OFL.txt", OUT / "OFL.txt")


if __name__ == "__main__":
    sys.exit(main())
