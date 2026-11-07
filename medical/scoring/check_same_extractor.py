"""두 실행이 같은 추출기 · 프롬프트 · 모델로 돌았는지 확인한다 (보류 검증의 '추출기 고정' 확인용, LLM 0).
run_meta.json에 실행 당시 medical/*.py 해시와 프롬프트 해시가, llm_usage.jsonl에 실제 모델 이름이 남아 있다.
사용: python medical/scoring/check_same_extractor.py runs/medical/holdout_1 runs/medical/holdout_2
'다름'이 medical/ 코드뿐이고 프롬프트 버전 · 모델이 '같음'이면, 추출기 LLM과 프롬프트는 그대로이고 그 뒤 처리만 바뀐 것이다.
"""
import json, sys, unicodedata
from pathlib import Path


def _p(run, name):
    for n in (unicodedata.normalize('NFC', name), unicodedata.normalize('NFD', name)):
        if (run / n).exists():
            return run / n
    return run / name


def load(run):
    run = Path(run)
    m = json.load(open(_p(run, 'run_meta.json'), encoding='utf-8'))
    models = {}
    for line in open(_p(run, 'llm_usage.jsonl'), encoding='utf-8'):
        if line.strip():
            u = json.loads(line)
            models.setdefault(u.get('role'), set()).add(u.get('model'))
    cfg = m.get('config', {})
    return dict(code=m.get('code', {}), prompts=m.get('prompts', {}), prompt_version=m.get('versions', {}).get('prompts'),
                models={k: sorted(v) for k, v in models.items()},
                settings={k: cfg.get(k) for k in ('rule_extract', 'mode', 'budget_B', 'documents', 'arms', 'k_req', 'temperature', 'seed')})


a, b = load(sys.argv[1]), load(sys.argv[2])
bad = 0
for key in ('code', 'prompts'):
    for name in sorted(set(a[key]) | set(b[key])):
        if a[key].get(name) != b[key].get(name):
            bad += 1
            print(f'다름  {key}: {name}')
print('프롬프트 버전', '같음' if a['prompt_version'] == b['prompt_version'] else f"다름 ({a['prompt_version']} / {b['prompt_version']})")
for role in sorted(set(a['models']) | set(b['models'])):
    same = a['models'].get(role) == b['models'].get(role)
    bad += 0 if same else 1
    print(f"모델 {role:9s} {'같음' if same else '다름'}  {a['models'].get(role)} / {b['models'].get(role)}")
for k in a['settings']:
    if a['settings'][k] != b['settings'][k]:
        print(f"설정 차이 {k}: {a['settings'][k]} / {b['settings'][k]}")
print('\n결론:', '추출기 · 프롬프트 · 모델이 같습니다' if bad == 0 else f'다른 곳이 {bad}개 있습니다 (위 목록)')
