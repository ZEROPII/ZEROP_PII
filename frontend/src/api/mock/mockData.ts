// Mock 고정 데이터 (UI 동작 확인용 가상 데이터)
//
// - 실제 환자 정보가 아니다. 사례 A~E와 k 값은 화면 검증용 예시이며 연구 실험 측정값이 아니다.
// - 기준값(generalize 5 · suppress 3)만 medical/config.py · risk_defender 기본값과 맞췄다.
// - QI_PROJECTIONS는 "이 항목을 지금 공개하면 k가 얼마가 되는가"를 백엔드 대신 미리 정해 둔 표다.
//   실제 환경에서는 백엔드(kcalc + Defender)가 계산한다.

import type { CaseId, CaseSummary, PatientContext, ProtectionPolicy, SuggestedQuestion, WorkspaceEnvironment } from '../../types/domain';

export const MOCK_ENVIRONMENT: WorkspaceEnvironment = {
  roleLabel: '의료진',
  locationLabel: '순환기내과 외래 진료실',
};

export const MOCK_POLICY: ProtectionPolicy = {
  modeLabel: '보호 모드',
  arm: 'C1',
  stateModeLabel: '누적 State 판정',
  minK: 5,
  suppressK: 3,
  populationSize: 576,
  source: 'mock',
};

export const MOCK_PATIENT: PatientContext = {
  contextId: 'ctx-demo-001',
  ageSexLabel: '61세 / 남성',
  primaryDiagnosis: 'Myocardial infarction',
  comorbidities: ['Chronic sinusitis', 'Hyperlipidemia'],
  plannedProcedure: 'PCI',
  queryPurpose: '시술 후 처방 확인',
  source: 'mock',
};

export const MOCK_CASES: CaseSummary[] = [
  { caseId: 'case-a', label: '사례 A', diagnosis: 'Myocardial infarction', description: 'PCI · 시술 후 처방 35건', similarityRank: 1 },
  { caseId: 'case-b', label: '사례 B', diagnosis: 'Coronary arteriosclerosis', description: 'PCI · 시술 후 처방 21건', similarityRank: 2 },
  { caseId: 'case-c', label: '사례 C', diagnosis: 'Myocardial infarction', description: '혈전용해 · 처방 18건', similarityRank: 3 },
  { caseId: 'case-d', label: '사례 D', diagnosis: 'Ischemic heart disease', description: '약물 치료 · 처방 9건', similarityRank: 4 },
  { caseId: 'case-e', label: '사례 E', diagnosis: 'Hyperlipidemia', description: '스타틴 단독 · 처방 40건', similarityRank: 5 },
];

/** 사례별 시술명 (답변 문장용) */
export const CASE_PROCEDURE: Record<CaseId, string> = {
  'case-a': 'Percutaneous coronary intervention',
  'case-b': 'Percutaneous coronary intervention',
  'case-c': 'Thrombolytic therapy',
  'case-d': '약물 치료',
  'case-e': '지질 강하 치료',
};

/** 검색 결과 노출(턴 0) 직후의 k. 사례 A는 시드 대화(질문 3회)를 거쳐 7이 된다. */
export const INITIAL_K: Record<CaseId, number> = {
  'case-a': 48,
  'case-b': 31,
  'case-c': 18,
  'case-d': 5,
  'case-e': 42,
};

// ── 질문 의도 (Mock 전용 키워드 규칙) ─────────────────────────────────────────

export type QiAttribute = 'AGE' | 'DATE' | 'LOC' | 'STATE' | 'SEX' | 'COMORBID';
export type ClinicalTopic = 'RX' | 'COMPARE';

export const QI_LABEL: Record<QiAttribute, string> = {
  AGE: '나이',
  DATE: '시술 시점',
  LOC: '거주 도시',
  STATE: '거주 주',
  SEX: '성별',
  COMORBID: '동반질환',
};

export const QI_PATTERNS: [QiAttribute, RegExp][] = [
  ['AGE', /몇\s*살|나이|연령|몇\s*세/],
  ['DATE', /언제|시점|날짜|몇\s*년|연도|몇\s*월/],
  ['LOC', /도시|거주지|사는\s*곳|어디\s*(에\s*)?살|동네|시군구|주소/],
  ['STATE', /어느\s*주|거주(하는|한)?\s*주|사는\s*주/],
  ['SEX', /성별|남자|여자|남성|여성/],
  ['COMORBID', /동반|기저\s*질환|합병증|다른\s*질환/],
];

export const TOPIC_PATTERNS: [ClinicalTopic, RegExp][] = [
  ['COMPARE', /비교/],
  ['RX', /처방|약|복용|투약/],
];

/** 이 문구가 들어간 질문은 Mock 서버 오류를 낸다 (오류 상태 UI 확인용). */
export const MOCK_ERROR_TRIGGER = '#오류';

// ── 공개 시 k 예측표 ──────────────────────────────────────────────────────────

export interface Generalization {
  value: string;
  /** 예: "5세 구간" */
  level: string;
  k: number;
}

export interface QiProjection {
  /** 원래 값으로 공개할 때의 k */
  rawK: number;
  /** 원래 값 공개가 허용될 때만 쓰는 표시 값 */
  rawValue: string;
  /** 예: "1세 단위" */
  rawLevel: string;
  generalizations: Generalization[];
}

type ProjectionTable = Partial<Record<QiAttribute, QiProjection>>;

export const QI_PROJECTIONS: Record<CaseId, ProjectionTable> = {
  'case-a': {
    SEX: { rawK: 26, rawValue: '남성', rawLevel: '성별', generalizations: [] },
    STATE: { rawK: 18, rawValue: 'Massachusetts', rawLevel: '주 단위', generalizations: [] },
    AGE: { rawK: 4, rawValue: '—', rawLevel: '1세 단위', generalizations: [{ value: '50~54세', level: '5세 구간', k: 7 }] },
    DATE: { rawK: 2, rawValue: '—', rawLevel: '일 단위', generalizations: [{ value: '—', level: '연도', k: 3 }] },
    LOC: { rawK: 3, rawValue: '—', rawLevel: '도시 단위', generalizations: [] },
    COMORBID: { rawK: 4, rawValue: '—', rawLevel: '개별 진단명', generalizations: [{ value: '호흡기·대사 질환 동반', level: '질환군', k: 6 }] },
  },
  'case-b': {
    SEX: { rawK: 16, rawValue: '여성', rawLevel: '성별', generalizations: [] },
    STATE: { rawK: 22, rawValue: 'Massachusetts', rawLevel: '주 단위', generalizations: [] },
    AGE: { rawK: 4, rawValue: '—', rawLevel: '1세 단위', generalizations: [{ value: '60~64세', level: '5세 구간', k: 12 }] },
    DATE: { rawK: 5, rawValue: '—', rawLevel: '일 단위', generalizations: [{ value: '2019년', level: '연도', k: 9 }] },
    LOC: { rawK: 4, rawValue: '—', rawLevel: '도시 단위', generalizations: [{ value: 'Massachusetts 주', level: '주 단위', k: 20 }] },
    COMORBID: { rawK: 11, rawValue: 'Hypertension', rawLevel: '개별 진단명', generalizations: [] },
  },
  'case-c': {
    SEX: { rawK: 9, rawValue: '남성', rawLevel: '성별', generalizations: [] },
    STATE: { rawK: 12, rawValue: 'Massachusetts', rawLevel: '주 단위', generalizations: [] },
    AGE: { rawK: 3, rawValue: '—', rawLevel: '1세 단위', generalizations: [{ value: '70~74세', level: '5세 구간', k: 4 }] },
    DATE: { rawK: 4, rawValue: '—', rawLevel: '일 단위', generalizations: [{ value: '2018년', level: '연도', k: 10 }] },
    LOC: { rawK: 2, rawValue: '—', rawLevel: '도시 단위', generalizations: [] },
    COMORBID: { rawK: 5, rawValue: '—', rawLevel: '개별 진단명', generalizations: [{ value: '대사 질환 동반', level: '질환군', k: 8 }] },
  },
  'case-d': {
    SEX: { rawK: 3, rawValue: '—', rawLevel: '성별', generalizations: [] },
    STATE: { rawK: 3, rawValue: '—', rawLevel: '주 단위', generalizations: [] },
    AGE: { rawK: 1, rawValue: '—', rawLevel: '1세 단위', generalizations: [{ value: '—', level: '10세 구간', k: 2 }] },
    DATE: { rawK: 2, rawValue: '—', rawLevel: '일 단위', generalizations: [] },
    LOC: { rawK: 1, rawValue: '—', rawLevel: '도시 단위', generalizations: [] },
    COMORBID: { rawK: 2, rawValue: '—', rawLevel: '개별 진단명', generalizations: [] },
  },
  'case-e': {
    SEX: { rawK: 30, rawValue: '남성', rawLevel: '성별', generalizations: [] },
    STATE: { rawK: 33, rawValue: 'Massachusetts', rawLevel: '주 단위', generalizations: [] },
    AGE: { rawK: 14, rawValue: '48세', rawLevel: '1세 단위', generalizations: [] },
    DATE: { rawK: 5, rawValue: '—', rawLevel: '일 단위', generalizations: [{ value: '2020년', level: '연도', k: 21 }] },
    LOC: { rawK: 5, rawValue: '—', rawLevel: '도시 단위', generalizations: [{ value: 'Massachusetts 주', level: '주 단위', k: 25 }] },
    COMORBID: { rawK: 19, rawValue: 'Type 2 diabetes', rawLevel: '개별 진단명', generalizations: [] },
  },
};

// ── 비(非)QI 임상 답변 ────────────────────────────────────────────────────────

export const CLINICAL_ANSWERS: Record<CaseId, Record<ClinicalTopic, string>> = {
  'case-a': {
    RX: '시술 후 이중 항혈소판요법(아스피린 + 클로피도그렐)을 12개월 유지했고, 고강도 스타틴과 베타차단제를 함께 처방받았습니다.',
    COMPARE: '사례 A·B는 시술 후 이중 항혈소판요법을 12개월 유지했고, 사례 C는 혈전용해 후 아스피린 단독 요법으로 전환했습니다. 세 사례 모두 고강도 스타틴을 병용했습니다.',
  },
  'case-b': {
    RX: '시술 후 아스피린 + 티카그렐러를 12개월 유지한 뒤 아스피린 단독으로 전환했고, 스타틴을 지속 처방받았습니다.',
    COMPARE: '사례 B는 사례 A와 같은 이중 항혈소판요법 기간을 따랐고, P2Y12 억제제만 티카그렐러로 달랐습니다.',
  },
  'case-c': {
    RX: '혈전용해 치료 후 아스피린 단독 요법과 ACE 억제제, 중등도 스타틴을 처방받았습니다.',
    COMPARE: '사례 C는 PCI 대신 혈전용해 치료를 받아 항혈소판제 구성이 사례 A·B보다 단순합니다.',
  },
  'case-d': {
    RX: '시술 없이 아스피린, 질산염 제제, 스타틴으로 약물 치료를 유지했습니다.',
    COMPARE: '사례 D는 시술을 받지 않아 시술 후 처방 비교 대상에서 제외됩니다. 약물 치료 구성만 비교할 수 있습니다.',
  },
  'case-e': {
    RX: '스타틴 단독 요법을 유지했고 6개월 간격으로 지질 검사 후 용량을 조정했습니다.',
    COMPARE: '사례 E는 관상동맥 시술 이력이 없어 지질 강하 처방만 비교할 수 있습니다.',
  },
};

export const SUGGESTED_QUESTIONS: Record<CaseId, SuggestedQuestion[]> = {
  'case-a': [
    { label: '시술 후 처방 기간을 묻기', question: '사례 A의 시술 후 항혈소판제 처방 기간은 어떻게 되나요?' },
    { label: '사례 B·C와 처방 비교', question: '사례 A와 사례 B·C의 시술 후 처방을 비교해 주세요.' },
  ],
  'case-b': [
    { label: '시술 후 처방 구성을 묻기', question: '사례 B의 시술 후 처방 구성은 어떻게 되나요?' },
    { label: '사례 A와 처방 비교', question: '사례 B와 사례 A의 처방을 비교해 주세요.' },
  ],
  'case-c': [
    { label: '혈전용해 후 처방을 묻기', question: '사례 C의 혈전용해 후 처방은 어떻게 되나요?' },
    { label: '사례 A·B와 처방 비교', question: '사례 C와 사례 A·B의 처방을 비교해 주세요.' },
  ],
  'case-d': [
    { label: '약물 치료 구성을 묻기', question: '사례 D의 약물 치료 구성은 어떻게 되나요?' },
    { label: '다른 사례와 처방 비교', question: '사례 D와 다른 사례의 처방을 비교해 주세요.' },
  ],
  'case-e': [
    { label: '지질 강하 처방을 묻기', question: '사례 E의 지질 강하 처방은 어떻게 조정되었나요?' },
    { label: '사례 A와 처방 비교', question: '사례 E와 사례 A의 처방을 비교해 주세요.' },
  ],
};

/** 사례 A 시드 대화 (질문 3회). 엔진을 그대로 거쳐 k 48 → 18 → 7 → 7이 된다. */
export const SEED_QUESTIONS: Record<CaseId, string[]> = {
  'case-a': [
    '사례 A 환자의 성별과 거주하는 주는 어떻게 되나요?',
    '사례 A 환자는 그 시술을 몇 살 때, 언제 받았나요?',
    '사례 A의 시술 후 처방은 어떻게 되었나요?',
  ],
};
