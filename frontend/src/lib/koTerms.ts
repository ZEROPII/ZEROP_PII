// 외래 목록 찾기용 한국어 진단 이름. 진단 이름(SNOMED · ICD 이름)이 영어라 '기관지염'으로 찾을 수 있게 영어 낱말에 한국어 이름을 잇는다.
// 화면에 보이는 값은 바꾸지 않고 찾기에만 쓴다.

const KO: [RegExp, string][] = [
  [/bronchitis/i, '기관지염'],
  [/pharyngitis/i, '인두염 목감기'],
  [/streptococcal/i, '연쇄상구균'],
  [/gingiv/i, '치은염 잇몸'],
  [/periodontal/i, '치주염 치주질환 잇몸'],
  [/sinusitis/i, '부비동염 축농증'],
  [/dental caries|caries/i, '충치 치아우식'],
  [/pulp|periapical/i, '치수 치근단'],
  [/tooth|dental|alveolar/i, '치아'],
  [/hypertension/i, '고혈압'],
  [/prediabetes/i, '당뇨 전단계'],
  [/diabetes/i, '당뇨'],
  [/blood glucose/i, '혈당'],
  [/otitis media/i, '중이염'],
  [/cystitis/i, '방광염'],
  [/urinary tract/i, '요로감염'],
  [/intracranial|concussion/i, '뇌진탕 머리 손상'],
  [/abortion/i, '유산'],
  [/rhinitis/i, '비염 알레르기'],
  [/sepsis/i, '패혈증'],
  [/anemi/i, '빈혈'],
  [/fracture/i, '골절'],
  [/sprain|dislocation/i, '염좌 삠 탈구'],
  [/epilep|seizure|convulsion/i, '뇌전증 경련 발작'],
  [/asthma/i, '천식'],
  [/hypoxemia/i, '저산소혈증'],
  [/migraine/i, '편두통'],
  [/eclampsia/i, '자간증 임신'],
  [/laceration/i, '열상 찢어짐'],
  [/heart failure/i, '심부전'],
  [/scoliosis/i, '척추측만증'],
  [/sleep apnea/i, '수면무호흡'],
  [/sleep/i, '수면'],
  [/alzheimer/i, '알츠하이머 치매'],
  [/lung cancer|neoplasm|cancer/i, '암 종양'],
  [/colon/i, '대장'],
  [/breast/i, '유방'],
  [/kidney/i, '신장 콩팥'],
  [/covid/i, '코로나'],
  [/opioid|overdose/i, '약물 과다'],
  [/appendicitis/i, '충수염 맹장염'],
  [/pulmonary embolism/i, '폐색전증'],
  [/neuropathy/i, '신경병증'],
  [/whiplash/i, '목 손상'],
  [/congenital/i, '선천'],
];

/** 영어 진단 이름에 맞는 한국어 이름들 (없으면 빈 글) */
export function koreanNames(label: string): string {
  return KO.filter(([re]) => re.test(label))
    .map(([, ko]) => ko)
    .join(' ');
}
