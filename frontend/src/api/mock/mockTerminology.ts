// Mock 모드 의료 용어 (화면 확인용 예시). 실제 용어 DB(scripts/build_terminology_db.py)의 내용이 아니다.
// 설명 문장은 화면 확인을 위해 손으로 쓴 예시이며 검토를 거치지 않았다.

import type { TermAttribute, TermCard } from '../../types/terminology';

interface MockTerm {
  id: string;
  attr: TermAttribute;
  label: string;
  code: string | null;
  source: string;
  level: string;
  explain: string;
  aliases: string[];
  chain: [string, string][];
  k: number;
}

const ATTR: Record<TermAttribute, string> = { DX: '진단', MED: '약', PROC: '시술·처치' };

const TERMS: MockTerm[] = [
  { id: 'DX_SCT_22298006', attr: 'DX', label: 'Myocardial infarction', code: '22298006', source: 'SNOMED CT', level: 'SNOMED CT 개념',
    explain: '심장 근육에 피를 보내는 혈관이 막혀 심장 근육 일부가 손상된 상태입니다.', aliases: ['심근경색'],
    chain: [['DX_ICD_CODE_I21', 'Acute myocardial infarction'], ['DX_ICD_SECTION_I20-I25', 'Ischemic heart diseases (I20-I25)']], k: 41 },
  { id: 'DX_SCT_53741008', attr: 'DX', label: 'Coronary arteriosclerosis', code: '53741008', source: 'SNOMED CT', level: 'SNOMED CT 개념',
    explain: '심장에 피를 보내는 혈관 벽이 두꺼워지고 딱딱해져 혈관이 좁아진 상태입니다.', aliases: ['관상동맥 경화'],
    chain: [['DX_ICD_CODE_I25', 'Chronic ischemic heart disease'], ['DX_ICD_SECTION_I20-I25', 'Ischemic heart diseases (I20-I25)']], k: 37 },
  { id: 'DX_SCT_414545008', attr: 'DX', label: 'Ischemic heart disease', code: '414545008', source: 'SNOMED CT', level: 'SNOMED CT 개념',
    explain: '심장 근육으로 가는 피가 부족해서 생기는 심장 질환을 묶어 부르는 이름입니다.', aliases: ['허혈성 심장질환'],
    chain: [['DX_ICD_SECTION_I20-I25', 'Ischemic heart diseases (I20-I25)']], k: 52 },
  { id: 'DX_SCT_55822004', attr: 'DX', label: 'Hyperlipidemia', code: '55822004', source: 'SNOMED CT', level: 'SNOMED CT 개념',
    explain: '혈액 속 콜레스테롤이나 중성지방 같은 지방 성분이 많은 상태입니다.', aliases: ['고지혈증'],
    chain: [['DX_ICD_CODE_E78', 'Disorders of lipoprotein metabolism and other lipidemias']], k: 88 },
  { id: 'DX_SCT_40055000', attr: 'DX', label: 'Chronic sinusitis', code: '40055000', source: 'SNOMED CT', level: 'SNOMED CT 개념',
    explain: '코 주변의 빈 공간(부비동)에 염증이 오래 이어지는 상태입니다.', aliases: ['만성 부비동염'],
    chain: [['DX_ICD_CODE_J32', 'Chronic sinusitis']], k: 64 },
  { id: 'DX_SCT_59621000', attr: 'DX', label: 'Essential hypertension', code: '59621000', source: 'SNOMED CT', level: 'SNOMED CT 개념',
    explain: '뚜렷한 다른 원인 없이 혈압이 정상보다 계속 높은 상태입니다.', aliases: ['Hypertension', '고혈압'],
    chain: [['DX_ICD_CODE_I10', 'Essential (primary) hypertension']], k: 120 },
  { id: 'DX_SCT_44054006', attr: 'DX', label: 'Type 2 diabetes', code: '44054006', source: 'SNOMED CT', level: 'SNOMED CT 개념',
    explain: '몸이 인슐린을 잘 쓰지 못해 혈당이 높게 유지되는 상태입니다.', aliases: ['제2형 당뇨병'],
    chain: [['DX_ICD_CODE_E11', 'Type 2 diabetes mellitus']], k: 73 },
  { id: 'MED_IN_1191', attr: 'MED', label: 'aspirin', code: '1191', source: 'RxNorm', level: '성분',
    explain: '혈소판이 뭉치는 것을 줄여 혈관이 막히지 않게 하는 데 쓰는 약입니다. 통증과 열을 내리는 데도 씁니다.', aliases: ['아스피린'],
    chain: [['MED_ATC_B01AC', 'B01AC Platelet aggregation inhibitors excl. heparin'], ['MED_ATC_B01', 'B01 ANTITHROMBOTIC AGENTS']], k: 210 },
  { id: 'MED_IN_32968', attr: 'MED', label: 'clopidogrel', code: '32968', source: 'RxNorm', level: '성분',
    explain: '혈소판이 서로 뭉치지 않게 해서 혈관 속에 피떡(혈전)이 생기는 것을 막는 약입니다.', aliases: ['클로피도그렐'],
    chain: [['MED_ATC_B01AC', 'B01AC Platelet aggregation inhibitors excl. heparin'], ['MED_ATC_B01', 'B01 ANTITHROMBOTIC AGENTS']], k: 46 },
  { id: 'MED_IN_1116632', attr: 'MED', label: 'ticagrelor', code: '1116632', source: 'RxNorm', level: '성분',
    explain: '클로피도그렐처럼 혈소판이 뭉치는 것을 막아 혈전을 줄이는 약입니다.', aliases: ['티카그렐러'],
    chain: [['MED_ATC_B01AC', 'B01AC Platelet aggregation inhibitors excl. heparin']], k: 9 },
  { id: 'MED_ATC_C10AA', attr: 'MED', label: 'C10AA HMG CoA reductase inhibitors', code: 'C10AA', source: 'ATC', level: 'ATC 약효 분류',
    explain: '몸에서 콜레스테롤을 만드는 과정을 줄여 혈중 콜레스테롤을 낮추는 약 종류(스타틴)입니다.', aliases: ['스타틴', 'statin'],
    chain: [['MED_ATC_C10A', 'C10A LIPID MODIFYING AGENTS, PLAIN'], ['MED_ATC_C10', 'C10 LIPID MODIFYING AGENTS']], k: 150 },
  { id: 'MED_ATC_C07', attr: 'MED', label: 'C07 BETA BLOCKING AGENTS', code: 'C07', source: 'ATC', level: 'ATC 약효 분류',
    explain: '심장 박동을 느리게 하고 혈압을 낮추는 약 종류입니다.', aliases: ['베타차단제'],
    chain: [['MED_ATC_C', 'C CARDIOVASCULAR SYSTEM']], k: 97 },
  { id: 'MED_ATC_C09A', attr: 'MED', label: 'C09A ACE INHIBITORS, PLAIN', code: 'C09A', source: 'ATC', level: 'ATC 약효 분류',
    explain: '혈관을 좁히는 물질이 만들어지지 않게 해서 혈압을 낮추는 약 종류입니다.', aliases: ['ACE 억제제'],
    chain: [['MED_ATC_C09', 'C09 AGENTS ACTING ON THE RENIN-ANGIOTENSIN SYSTEM']], k: 81 },
  { id: 'PROC_SCT_415070008', attr: 'PROC', label: 'Percutaneous coronary intervention', code: '415070008', source: 'SNOMED CT', level: 'SNOMED CT 시술',
    explain: '손목이나 다리의 혈관으로 가는 관을 넣어 좁아진 심장 혈관을 넓히는 시술입니다.', aliases: ['PCI', '관상동맥 중재술'],
    chain: [['PROC_GROUP_0_2', '0-2 심장·대혈관 / Heart and Great Vessels']], k: 33 },
  { id: 'PROC_MOCK_THROMBOLYSIS', attr: 'PROC', label: 'Thrombolytic therapy', code: null, source: '기타', level: '시술',
    explain: '혈관을 막은 피떡(혈전)을 약으로 녹이는 치료입니다.', aliases: ['혈전용해'],
    chain: [], k: 12 },
];

const TOTAL = 576;

export function mockTermCards(): TermCard[] {
  return TERMS.map((t, i) => ({
    node_id: t.id,
    attribute: t.attr,
    attribute_label: ATTR[t.attr],
    canonical_label: t.label,
    plain_explanation: t.explain,
    has_explanation: true,
    standard_code: t.code,
    source: t.source,
    level_label: t.level,
    parent_id: t.chain[0]?.[0] ?? null,
    is_sensitive: false,
    review_status: i === 0 ? '검토완료' : '검토대기',
    reviewer: i === 0 ? '예시' : null,
    reviewed_at: null,
    llm_model: null,
    k_patients: t.k,
    total_patients: TOTAL,
    aliases: t.aliases,
    generalization_chain: [
      { node_id: t.id, label: t.label, plain_explanation: t.explain, level_label: t.level },
      ...t.chain.map(([id, label]) => ({ node_id: id, label, plain_explanation: null, level_label: '상위 분류' })),
    ],
  }));
}

/** 찾는 표현: [소문자 표현, node_id] */
export function mockSurfaces(): [string, string][] {
  return TERMS.flatMap((t) => [t.label, ...t.aliases].map((s) => [s.toLowerCase(), t.id] as [string, string]));
}
