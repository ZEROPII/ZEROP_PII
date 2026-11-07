// 가상 EMR API (python -m medicloak): 내 담당 환자 목록 · 차트 요약 · 협진 의뢰 · 담당 외 환자 열기 · 진료 지원 AI 열기 · FHIR R4 읽기.
// 의료진 계정만 쓴다. 담당 환자와 협진 의뢰 · 예외 열람으로 연 환자만 열리고(아니면 403), 유사 사례(과거 기록) 환자는 404다
// (ADR-0034 · ADR-0036).

import type { Clinician, EmrChart, EmrConsult, EmrGrant, EmrMe, LaunchProgress, VisitChoice, WorklistPatient } from '../types/domain';
import { ApiError } from './types';
import { API_BASE, FHIR_BASE, notifyUnauthorized } from './session';

const EMR_OFF = 'EMR 연동은 MediCloak 운영 서버(python -m medicloak)에서만 쓸 수 있습니다.';

/** 서버가 돌려준 안내 문장 (detail). 이 API의 안내에는 환자 기록이 들어 있지 않다 */
async function detailOf(res: Response): Promise<string | null> {
  try {
    const b = (await res.json()) as { detail?: unknown };
    return typeof b?.detail === 'string' ? b.detail : null;
  } catch {
    return null;
  }
}

async function get<T>(url: string, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, { credentials: 'include', headers: { Accept: 'application/json' }, signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError('서버에 연결할 수 없습니다.');
  }
  if (res.status === 401) notifyUnauthorized();
  if (!res.ok) {
    const detail = url.includes('/emr/') ? await detailOf(res) : null;
    if (res.status === 404 && url.includes('/emr/') && (!detail || detail.includes('운영 모드'))) throw new ApiError(EMR_OFF, 404);
    throw new ApiError(detail ?? `요청이 실패했습니다 (HTTP ${res.status}).`, res.status, res.headers.get('X-MediCloak-State') ?? undefined);
  }
  return (await res.json()) as T;
}

/** 본문이 있는 POST. 실패하면 서버 안내 문장(detail)으로 ApiError (머리글 X-MediCloak-State를 flag로) */
async function post<T>(url: string, body: unknown, fallback: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, {
      method: 'POST',
      credentials: 'include',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify(body ?? {}),
    });
  } catch {
    throw new ApiError('서버에 연결할 수 없습니다.');
  }
  if (res.status === 401) notifyUnauthorized();
  if (!res.ok) throw new ApiError((await detailOf(res)) ?? `${fallback} (HTTP ${res.status}).`, res.status, res.headers.get('X-MediCloak-State') ?? undefined);
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
  /** 내 담당 환자 (+ 예외 열람 중인 환자) */
  worklist: (signal?: AbortSignal) => get<WorklistPatient[]>(`${API_BASE}/emr/worklist`, signal),
  /** 담당 환자 수 · 예외 열람 설정 */
  me: (signal?: AbortSignal) => get<EmrMe>(`${API_BASE}/emr/me`, signal),
  /** 차트 요약 (열면 접근 기록에 남는다) */
  chart: (fhirId: string, signal?: AbortSignal) => get<EmrChart>(`${API_BASE}/emr/chart?fhirId=${encodeURIComponent(fhirId)}`, signal),
  /** 담당 외 환자 열기: 등록번호('26-4821') · 사유 분류 · 직접 쓴 설명 */
  breakGlass: async (patient: string, reason: string, note: string): Promise<{ fhirId: string; identifier: string; regno?: string | null; created: boolean; grant: EmrGrant }> => {
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/emr/break-glass`, {
        method: 'POST',
        credentials: 'include',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ patient, reason, note }),
      });
    } catch {
      throw new ApiError('서버에 연결할 수 없습니다.');
    }
    if (res.status === 401) notifyUnauthorized();
    if (!res.ok) throw new ApiError((await detailOf(res)) ?? `담당 외 환자를 열지 못했습니다 (HTTP ${res.status}).`, res.status);
    return (await res.json()) as { fhirId: string; identifier: string; regno?: string | null; created: boolean; grant: EmrGrant };
  },
  /** 협진 의뢰를 받을 수 있는 의료진 (나를 뺀) */
  directory: (signal?: AbortSignal) => get<Clinician[]>(`${API_BASE}/emr/directory`, signal),
  /** 받은 협진 의뢰(열 수 있는 것 먼저) · 보낸 협진 의뢰 */
  consults: (signal?: AbortSignal) => get<{ received: EmrConsult[]; sent: EmrConsult[] }>(`${API_BASE}/emr/consults`, signal),
  /** 담당 환자에 대해 협진 의뢰를 보낸다 (같은 의료진에게 열린 의뢰가 있으면 그것, created=false) */
  sendConsult: (fhirId: string, to: string, note: string) =>
    post<EmrConsult & { created: boolean }>(`${API_BASE}/emr/consults`, { fhirId, to, note }, '협진 의뢰를 보내지 못했습니다'),
  /** 받은 협진 의뢰로 환자를 연다 (번호 없이) */
  openConsult: (id: number) =>
    post<{ consult: EmrConsult; fhirId: string; grant: EmrGrant; created: boolean }>(`${API_BASE}/emr/consults/${id}/open`, {}, '협진 의뢰를 열지 못했습니다'),
  declineConsult: (id: number, note?: string) => post<EmrConsult>(`${API_BASE}/emr/consults/${id}/decline`, { note: note ?? null }, '협진 의뢰를 거절하지 못했습니다'),
  cancelConsult: (id: number, note?: string) => post<EmrConsult>(`${API_BASE}/emr/consults/${id}/cancel`, { note: note ?? null }, '협진 의뢰를 취소하지 못했습니다'),
  /** 진료 지원 AI 열기를 멈춘다 (idle: 여는 중이 아님 · stopping: 멈추는 중) */
  stopLaunch: () => post<{ status: 'idle' | 'stopping' }>(`${API_BASE}/emr/launch/stop`, {}, '멈추지 못했습니다'),
  /** 답을 기다리는 질문을 멈춘다 */
  stopQuestion: () => post<{ status: 'idle' | 'stopping' }>(`${API_BASE}/clinic/stop`, {}, '멈추지 못했습니다'),
  /** 오늘 볼 진단으로 고를 수 있는 것 (진료 목적마다, 최근 것부터) */
  visits: (fhirId: string, signal?: AbortSignal) =>
    get<{ purposes: Record<string, VisitChoice[]> }>(`${API_BASE}/emr/visits?fhirId=${encodeURIComponent(fhirId)}`, signal),
  launchProgress: (signal?: AbortSignal) => get<LaunchProgress>(`${API_BASE}/emr/launch/progress`, signal),
  /** 질문에 답하는 중의 단계 (실제 LLM 대화) */
  questionProgress: (signal?: AbortSignal) => get<LaunchProgress>(`${API_BASE}/clinic/progress`, signal),
  /** visitEvent: 의사가 고른 오늘 진단 (없으면 기본 기준 진료) */
  launch: async (fhirId: string, purpose: string, visitEvent?: string | null): Promise<{ trialId: string; seconds?: number; calls?: number }> => {
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/emr/launch`, {
        method: 'POST',
        credentials: 'include',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ fhirId, purpose, visitEvent: visitEvent ?? null }),
      });
    } catch {
      throw new ApiError('서버에 연결할 수 없습니다.');
    }
    if (res.status === 401) notifyUnauthorized();
    if (!res.ok) {
      const detail = await detailOf(res);
      throw new ApiError(
        res.status === 404 ? '이 환자는 고른 진료 목적으로 진료 지원 AI를 열 수 없습니다.' : (detail ?? `진료 지원 AI를 열지 못했습니다 (HTTP ${res.status}).`),
        res.status,
        res.headers.get('X-MediCloak-State') ?? undefined,
      );
    }
    return (await res.json()) as { trialId: string; seconds?: number; calls?: number };
  },
  /**
   * 고른 환자 · 진료 목적의 첫 답을 서버가 뒤에서 미리 만들어 두게 한다 (열기를 짧게). 실패해도 화면에는 알리지 않는다.
   * status: started · queued(앞의 미리 준비가 끝나면 이어서) · current(지금 연 대화) · off(서버 설정)
   */
  prefetch: async (fhirId: string, purpose: string, visitEvent?: string | null): Promise<string> => {
    try {
      const res = await fetch(`${API_BASE}/emr/prefetch`, {
        method: 'POST',
        credentials: 'include',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ fhirId, purpose, visitEvent: visitEvent ?? null }),
      });
      if (!res.ok) return 'error';
      return ((await res.json()) as { status?: string }).status ?? 'error';
    } catch {
      return 'error';
    }
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
