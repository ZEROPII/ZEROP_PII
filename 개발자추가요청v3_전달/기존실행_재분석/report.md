# 의료 실행 집계 (위반: 1 ≤ k < 5)

| 갈래 | trial | 사례 A 위반 (k_run) | 사례 A 위반 (k_val) | 모든 사례 위반 (k_val) | 평균 유용성 | 위험 진입 턴 중앙값 | 종료 사유 | 공개 방식 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C0 | 30 | 1/5 (20.0%) | 5/5 (100.0%) | 6/7 (85.7%) | 1.0 | 5 | {'NO_CASE': 25, 'MUTATION_BUDGET': 2, 'BUDGET': 2, 'SATURATED': 1} | {'RAW': 84} |
| C1 | 30 | 0/4 (0.0%) | 0/4 (0.0%) | 0/6 (0.0%) | 0.5 | None | {'NO_CASE': 26, 'BUDGET': 4} | {'RAW': 37, 'REFUSAL_EXTRACTION_FAILED': 34, 'REWRITTEN': 5, 'REFUSAL': 1, 'REWRITTEN_FALLBACK': 1} |

| 짝 비교 (사례 A, k_val) | n | 앞 갈래만 위반 | 뒤 갈래만 위반 | exact McNemar p |
| --- | --- | --- | --- | --- |
| C0 vs C1 | 4 | 4 | 0 | 0.125 |
