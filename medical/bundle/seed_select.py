"""Seed Registry v0.7의 required_state_condition 평가와 자리표시자 채우기 (설계 8.40–8.41·8.55·8.57, 근거는 Registry의 조건문법 시트).
state: KCalc.reduce()가 돌려주는 {(단서,) | (단서, 사건묶음[, 순번]): 노드ID}. 공개·commit된 값만 들어 있어야 한다."""
import csv, openpyxl
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
        if cl == f'{q} not active': ok = not keys
        elif cl == f'{q} active': ok = bool(keys)
        elif cl == 'active_node_has_descendant = true': keys = [k for k in keys if children.get(state[k], 0) > 0]; ok = bool(keys)
        elif cl == 'active_node_is_root = false': keys = [k for k in keys if node[state[k]]['parent_id']]; ok = bool(keys)       # ANY에서 O2 시작 금지
        elif cl == 'refine_same_event_ref = true': keys = [k for k in keys if len(k) > 1 and k[1] is not None]; ok = bool(keys)  # 같은 사건 값만 세분화
        elif cl == 'prior_context_available = true': ok = prior_context_available
        else: raise ValueError(f'모르는 조건 절: {cl}')
        if not ok: return None
    return keys[0] if seed['attack_objective'] == 'SPECIFICITY_REFINEMENT' else True
def fill(seed, key, state, node, subject='이 환자', event_text=None):
    t = seed['template_text'].replace('[SUBJECT]', subject)
    if '[PREVIOUSLY_DISCLOSED_QI]' in t:                      # 공개·commit된 값만 바인딩 (정답·raw 후보 금지)
        label = node[state[key]]['canonical_label']
        if seed['target_qi'] in ('AGE', 'PERIOD') and event_text and key[1] in event_text:
            label = f"{label}({event_text[key[1]]} 당시)"     # 나이·시기만 어느 사건의 것인지 함께. DX·PROC·MED·PLAN은 값 이름이 곧 사건(Registry 조건문법)
        t = t.replace('[PREVIOUSLY_DISCLOSED_QI]', f"'{label}'")
    return t
