"""실행 폴더의 llm_usage.jsonl로 LLM 호출 지연시간을 역할별로 요약한다 (LLM 0, 저장소 없이 실행 가능).

llm_usage.jsonl 한 줄 = LLM 호출 1번 (role, model, latency_ms, input_tokens, output_tokens, attempts, truncated).
호출 기록에 trial · 턴 번호가 없어서 '턴 하나의 총 지연'은 바로 나오지 않는다.
대신 턴 하나에서 보통 일어나는 호출(대상 AI 1번 + 추출기 1번, 고쳐 쓰면 재작성기 + 재추출)을 역할별 평균으로 더해 어림한다.

사용:
  python medical/scoring/llm_latency.py <실행 폴더>
"""
import collections, csv, json, statistics, sys, unicodedata
from pathlib import Path


def _p(run, name):
    for n in (unicodedata.normalize('NFC', name), unicodedata.normalize('NFD', name)):
        if (run / n).exists():
            return run / n
    return run / name


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def main():
    run = Path(sys.argv[1])
    rows = [json.loads(l) for l in open(_p(run, 'llm_usage.jsonl'), encoding='utf-8') if l.strip()]
    by = collections.defaultdict(list)
    for r in rows:
        by[r.get('role') or '?'].append(r)
    out = []
    for role, rs in sorted(by.items(), key=lambda kv: -len(kv[1])) + [('전체', rows)]:
        lat = [r['latency_ms'] for r in rs if r.get('latency_ms') is not None]
        out.append(dict(role=role, calls=len(rs), mean_ms=round(statistics.mean(lat)) if lat else None,
                        p50_ms=round(pct(lat, .5)) if lat else None, p95_ms=round(pct(lat, .95)) if lat else None,
                        max_ms=max(lat) if lat else None,
                        mean_in_tokens=round(statistics.mean(r.get('input_tokens') or 0 for r in rs)),
                        mean_out_tokens=round(statistics.mean(r.get('output_tokens') or 0 for r in rs)),
                        retried=sum(1 for r in rs if (r.get('attempts') or 1) > 1),
                        truncated=sum(1 for r in rs if r.get('truncated')),
                        models=' '.join(sorted({str(r.get('model')) for r in rs}))))
    print('| 역할 | 호출 | 평균 ms | 중앙값 ms | 상위 5% ms | 최대 ms | 입력 토큰 평균 | 출력 토큰 평균 | 재시도 | 잘림 |')
    print('|---|---|---|---|---|---|---|---|---|---|')
    for o in out:
        print(f"| {o['role']} | {o['calls']} | {o['mean_ms']} | {o['p50_ms']} | {o['p95_ms']} | {o['max_ms']} | "
              f"{o['mean_in_tokens']} | {o['mean_out_tokens']} | {o['retried']} | {o['truncated']} |")
    mean = {o['role']: o['mean_ms'] for o in out}
    print('\n역할 이름:', ', '.join(r for r in by))
    path = run / 'llm_latency.csv'
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
    print('저장:', path)
    return mean


if __name__ == '__main__':
    main()
