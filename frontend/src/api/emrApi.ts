// 가상 EMR API (python -m medicloak): 외래 진료 목록 · 진료 지원 AI 열기 · FHIR R4 읽기.
// 의료진 계정만 쓴다. FHIR로는 외래 환자만 열리고, 유사 사례(과거 기록) 환자는 404다.

import type { LaunchProgress, WorklistPatient } from '../types/domain';
import { ApiError } from './types';
import { API_BASE, FHIR_BASE, notifyUnauthorized } from './session';

async function get<T>(url: string, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, { credentials: 'include', headers: { Accept: 'application/json' }, signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError('서버에 연결할 수 없습니다.');
  }
  if (res.status === 401) notifyUnauthorized();
  if (res.status === 404 && url.includes('/emr/')) throw new ApiError('EMR 연동은 MediCloak 운영 서버(python -m medicloak)에서만 쓸 수 있습니다.', 404);
  if (!res.ok) throw new ApiError(`요청이 실패했습니다 (HTTP ${res.status}).`, res.status);
  return (await res.json()) as T;
}

export interface FhirCoding {
  system?: string;
  code?: string;
  display?: string;
}

export interface FhirResource {
  resourceType: string;
  id: string;
  code?: { coding?: FhirCoding[]; text?: string };
  medicationCodeableConcept?: { coding?: FhirCoding[]; text?: string };
  category?: { coding?: FhirCoding[]; text?: string }[];
  onsetDateTime?: string | null;
  abatementDateTime?: string | null;
  authoredOn?: string | null;
  performedPeriod?: { start?: string | null; end?: string | null };
  period?: { start?: string | null; end?: string | null };
  status?: string;
  clinicalStatus?: { text?: string };
}

export interface FhirBundle {
  resourceType: 'Bundle';
  total: number;
  entry?: { resource: FhirResource }[];
}

export const emrApi = {
  worklist: (signal?: AbortSignal) => get<WorklistPatient[]>(`${API_BASE}/emr/worklist`, signal),
  launchProgress: (signal?: AbortSignal) => get<LaunchProgress>(`${API_BASE}/emr/launch/progress`, signal),
  /** 질문에 답하는 중의 단계 (실제 LLM 대화) */
  questionProgress: (signal?: AbortSignal) => get<LaunchProgress>(`${API_BASE}/clinic/progress`, signal),
  launch: async (fhirId: string, purpose: string): Promise<{ trialId: string; seconds?: number; calls?: number }> => {
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/emr/launch`, {
        method: 'POST',
        credentials: 'include',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ fhirId, purpose }),
      });
    } catch {
      throw new ApiError('서버에 연결할 수 없습니다.');
    }
    if (res.status === 401) notifyUnauthorized();
    if (!res.ok) {
      const detail = await res
        .json()
        .then((b: { detail?: unknown }) => (typeof b?.detail === 'string' ? b.detail : null))
        .catch(() => null);
      throw new ApiError(
        res.status === 404 ? '이 환자는 고른 진료 목적으로 진료 지원 AI를 열 수 없습니다.' : (detail ?? `진료 지원 AI를 열지 못했습니다 (HTTP ${res.status}).`),
        res.status,
      );
    }
    return (await res.json()) as { trialId: string; seconds?: number; calls?: number };
  },
  /** /fhir/{Condition|MedicationRequest|Procedure|CarePlan}?patient= */
  search: (resource: string, patientId: string, signal?: AbortSignal) =>
    get<FhirBundle>(`${FHIR_BASE}/${resource}?patient=${encodeURIComponent(patientId)}`, signal),
};

/** FHIR 자원 하나의 이름과 날짜 */
export function fhirLabel(r: FhirResource): string {
  const c: { coding?: FhirCoding[]; text?: string } | undefined = r.code ?? r.medicationCodeableConcept ?? r.category?.[0];
  return c?.text || c?.coding?.[0]?.display || r.resourceType;
}

export function fhirDate(r: FhirResource): string | null {
  return r.onsetDateTime ?? r.authoredOn ?? r.performedPeriod?.start ?? r.period?.start ?? null;
}
