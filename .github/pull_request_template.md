## 무엇을 바꿨나

<!-- 한두 줄 -->

## Jira

ZP-

## 바뀌는 결정

- [ ] 결정이 바뀌지 않는다 (버그 수정 · 리팩터링 · 문서)
- [ ] 결정이 새로 생기거나 바뀐다 → ADR 번호: ADR-

새 결정이면 `python scripts/adr.py new "제목" --slug 이름 --deciders 이름 --area 영역 --jira ZP-00` 으로 초안을 만들고 이 PR에 함께 올립니다.
기존 결정을 뒤집으면 새 ADR을 쓴 뒤 `python scripts/adr.py supersede 옛번호 --by 새번호`.

## 확인

- [ ] `python -m pytest -q` 통과
- [ ] `.env` · `runs/` · 기준 집단 데이터가 커밋에 없다
