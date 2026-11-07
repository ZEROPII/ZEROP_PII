// 찾은 사례 한눈에: 사례 목록에 이미 보이는 값(진단 · 대표 항목)만으로 공통점과 다른 점을 센다. 새 값을 드러내지 않는다.

import type { CaseSummary, PatientContext } from '../types/domain';

export interface ValueCount {
  value: string;
  n: number;
}

/** 진단 · 대표 항목을 모르는 사례 (가렸거나, 첫 답에 나오지 않아 아직 모름): 공통 · 다른 항목 세기에서 뺀다 */
export const UNKNOWN = /비공개|관련 항목 없음|나오지 않음|미확인|채워집니다/;

function counts(values: string[]): ValueCount[] {
  const m = new Map<string, number>();
  for (const v of values) if (v && !UNKNOWN.test(v)) m.set(v, (m.get(v) ?? 0) + 1);
  return [...m.entries()].map(([value, n]) => ({ value, n })).sort((a, b) => b.n - a.n || a.value.localeCompare(b.value));
}

export interface CaseOverview {
  total: number;
  diagnoses: ValueCount[];
  items: ValueCount[];
  /** 두 사례 이상에 나온 가장 흔한 대표 항목 (없으면 null) */
  commonItem: string | null;
  commonDx: string | null;
}

export function overviewOf(cases: CaseSummary[]): CaseOverview {
  const diagnoses = counts(cases.map((c) => c.diagnosis));
  const items = counts(cases.map((c) => c.description));
  return {
    total: cases.length,
    diagnoses,
    items,
    commonDx: diagnoses[0] && diagnoses[0].n >= 2 ? diagnoses[0].value : null,
    commonItem: items[0] && items[0].n >= 2 ? items[0].value : null,
  };
}

/** 이 사례가 지금 환자와 겹치는 점 (환자 띠와 사례 목록에 이미 보이는 값끼리만 비교) */
export function matchReasons(c: CaseSummary, patient: Pick<PatientContext, 'primaryDiagnosis' | 'plannedProcedure'> | null | undefined): string[] {
  if (!patient) return [];
  const out: string[] = [];
  if (c.diagnosis && c.diagnosis === patient.primaryDiagnosis) out.push('주진단 같음');
  const item = (patient.plannedProcedure ?? '').trim().toLowerCase();
  if (item && c.description.toLowerCase().includes(item)) out.push('고려 중 처치와 같음');
  return out;
}

/** '처방 약 acetaminophen 325 MG Oral Tablet' → ['처방 약', 'acetaminophen 325 MG Oral Tablet'] */
export function splitItem(description: string): [string, string] {
  const m = /^(처방 약|시술|관리 계획)\s+(.+)$/.exec(description);
  return m ? [m[1], m[2]] : ['', description];
}
