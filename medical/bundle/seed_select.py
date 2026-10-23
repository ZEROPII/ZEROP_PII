"""Seed Registry v0.13의 required_state_condition 평가와 자리표시자 채우기 (설계 8.40–8.41·8.55·8.57, 근거는 Registry의 조건문법 시트).
state: KCalc.reduce()가 돌려주는 {(단서,) | (단서, 사건묶음[, 순번]): 노드ID}. 공개·commit된 값만 들어 있어야 한다."""
import csv, re, openpyxl
def load_registry(path):
    ws = openpyxl.load_workbook(path, data_only=True).worksheets[0]
    rows = list(ws.iter_rows(values_only=True)); return [dict(zip(rows[0], r)) for r in rows[1:] if r[0]]
def child_count(nodes_csv):
    c = {}
    for n in csv.DictReader(open(nodes_csv, encoding='utf-8-sig')): c[n['parent_id']] = c.get(n['parent_id'], 0) + 1
    return c
def target(seed, state, node, children, prior_context_available):
    """적용되면 O1은 True, O2는 좁힐 대상 State 키. 적용 안 되면 None. 모르는 절은 오류(조용히 통과시키지 않음)."""
    q = seed['target_qi']; keys = [k for k in state if k[0] == q]
    for cl in [x.strip() for x in seed['required_state_condition'].split(' AND ')]:
        q2 = seed.get('target_qi_2') or ''
        if q2 and cl == f'{q2} not active': ok = not [k for k in state if k[0] == q2]   # v0.13 단서 두 개 행
        elif cl == f'{q} not active': ok = not keys
        elif cl == f'{q} active': ok = bool(keys)
        elif cl == 'active_node_has_descendant = true': keys = [k for k in keys if children.get(state[k], 0) > 0]; ok = bool(keys)
        elif cl == 'active_node_is_root = false': keys = [k for k in keys if node[state[k]]['parent_id']]; ok = bool(keys)       # ANY에서 O2 시작 금지
        elif cl == 'refine_same_event_ref = true': keys = [k for k in keys if len(k) > 1 and k[1] is not None]; ok = bool(keys)  # 같은 사건 값만 세분화
        elif cl == 'prior_context_available = true': ok = prior_context_available
        else: raise ValueError(f'모르는 조건 절: {cl}')
        if not ok: return None
    return keys[0] if seed['attack_objective'] == 'SPECIFICITY_REFINEMENT' else True
# ---- 조사 맞추기 (v0.11) -----------------------------------------------------------------------
# 문장 원본은 자리표시자 뒤 조사를 한 형태로만 적는다("[PREVIOUSLY_DISCLOSED_QI]를"). 채울 때 값의 끝소리에 맞춘다.
# 괄호 덧붙임("40~49세(… 당시)")은 빼고 그 앞 말에 맞춘다(국립국어원 괄호 뒤 조사 원칙).
# 한글: 받침으로 정확히 판정 · 숫자: 한국어 읽기(0 영, 1 일, 3 삼, 6 육, 7 칠, 8 팔, 10 십, 100 백, 1000 천)
# 영문: 끝 글자로 어림(l·m·n·ng·k·p·t·b·d·g·c 소리로 끝나면 받침 있음으로) — 영어 발음과 다를 수 있는 근사.
_PAIR = {'을': ('을', '를'), '를': ('을', '를'), '이': ('이', '가'), '가': ('이', '가'), '은': ('은', '는'), '는': ('은', '는'),
         '과': ('과', '와'), '와': ('과', '와'), '으로': ('으로', '로'), '로': ('으로', '로')}
def _final(label):
    """끝소리: None = 받침 없음, 'ㄹ' = ㄹ 받침, 'O' = 그 밖의 받침."""
    x = re.sub(r"\([^()]*\)\s*$", "", label).strip() or label
    x = re.sub(r"\s*\[[^\]]*\]\s*$", "", x).strip() or x
    c = x[-1]
    if '가' <= c <= '힣':
        j = (ord(c) - 0xAC00) % 28
        return None if j == 0 else ('ㄹ' if j == 8 else 'O')
    if c.isdigit():
        digits = re.search(r"(\d+)$", x).group(1)
        z = len(digits) - len(digits.rstrip('0'))
        if digits.strip('0') == '': return 'O'                      # 0 = 영
        if z: return {1: 'O', 2: 'O', 3: 'O'}.get(z, 'O')           # 십·백·천·만 모두 받침
        return {'1': 'ㄹ', '7': 'ㄹ', '8': 'ㄹ', '3': 'O', '6': 'O', '0': 'O'}.get(digits[-1])
    w = x.lower()
    if w.endswith(('ng', 'l')): return 'ㄹ' if w.endswith('l') else 'O'
    if w[-1] in 'mnkptbdgc': return 'O'
    return None
def josa(label, written):
    a, b = _PAIR[written]
    f = _final(label)
    if a == '으로': return '로' if f in (None, 'ㄹ') else '으로'
    return b if f is None else a

def fill(seed, key, state, node, subject='이 환자', event_text=None):
    t = seed['template_text'].replace('[SUBJECT]', subject)
    if '[PREVIOUSLY_DISCLOSED_QI]' in t:                      # 공개·commit된 값만 바인딩 (정답·raw 후보 금지)
        label = node[state[key]]['canonical_label']
        if seed['target_qi'] in ('AGE', 'PERIOD') and event_text and key[1] in event_text:
            label = f"{label}({event_text[key[1]]} 당시)"     # 나이·시기만 어느 사건의 것인지 함께. DX·PROC·MED·PLAN은 값 이름이 곧 사건(Registry 조건문법)
        t = re.sub(r"\[PREVIOUSLY_DISCLOSED_QI\](으로|로|을|를|이|가|은|는|과|와)?",
                   lambda m: f"'{label}'" + (josa(label, m.group(1)) if m.group(1) else ''), t)
    # v0.9 LINKED_EVENT(같은 진료의 다른 사건을 거쳐 묻는 O2): '그 진료'가 어느 사건인지 공개된 사건 표현으로 밝힌다
    if seed.get('expected_relation') == 'LINKED_EVENT' and '그 진료' in t and key and len(key) > 1 and event_text and key[1] in event_text:
        t = t.replace('그 진료', f"그 진료({event_text[key[1]]})", 1)
    return t
