#!/usr/bin/env python3
"""결과 폴더 · zip에 API 키가 남았는지 확인한다 (키 값은 화면 · 파일 어디에도 출력하지 않는다).

저장소 루트(ZEROP_PII)에서:
  python3 -B 키점검.py <결과 폴더 또는 zip> [...]

- 저장소 설정(.env와 환경 변수)에서 키를 메모리로만 읽어, 모든 파일(zip 안 파일 포함)에 그 글자열이 있는지 본다.
- 키 모양 글자열(sk-ant-…)과 .env 파일이 들어 있는지도 본다.
- 출력은 파일 이름과 개수뿐이다.
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

KEY_LIKE = re.compile(rb"sk-ant-[A-Za-z0-9_\-]{16,}")


def load_key() -> bytes | None:
    sys.path.insert(0, str(Path.cwd()))
    try:
        from core.config import get_settings
        k = get_settings().llm_api_key
        return k.encode() if k and len(k) >= 16 else None
    except Exception:
        return None


def items(p: Path):
    if p.is_dir():
        for f in sorted(p.rglob("*")):
            if f.is_file():
                yield from items(f)
    elif p.suffix.lower() == ".zip":
        with zipfile.ZipFile(p) as z:
            for n in z.namelist():
                if not n.endswith("/"):
                    yield f"{p.name}:{n}", z.read(n)
    else:
        yield str(p), p.read_bytes()


def main() -> int:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    key = load_key()
    n = 0
    hit_key, hit_like, env_files = [], [], []
    for arg in sys.argv[1:]:
        for name, data in items(Path(arg).expanduser()):
            n += 1
            if Path(name.split(":")[-1]).name in (".env",) or name.endswith("/.env"):
                env_files.append(name)
            if key and key in data:
                hit_key.append(name)
            if KEY_LIKE.search(data):
                hit_like.append(name)
    print(f"검사한 파일 {n}개 · 설정의 키 {'읽음' if key else '못 읽음(모양 검사만 함)'}")
    print(f"  키 글자열이 든 파일: {len(hit_key)}개 {hit_key[:10]}")
    print(f"  키 모양(sk-ant-…) 글자열이 든 파일: {len(hit_like)}개 {hit_like[:10]}")
    print(f"  .env 파일: {len(env_files)}개 {env_files[:10]}")
    ok = not (hit_key or hit_like or env_files)
    print("결과: 키 없음" if ok else "결과: 확인 필요 — 위 파일은 보내지 마세요")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
