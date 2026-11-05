// 세부 정보 요청의 처리 상태: 요청 뒤에 보호 담당자가 보낸 메시지로 정한다.
//   released 승인됨 (공개 승인 메시지) · answered 답장 옴 (승인 없이 답장) · pending 대기 중

import type { CaseId, ClinicMessage } from '../types/domain';

export type RequestState = 'pending' | 'answered' | 'released';

export interface RequestStatus {
  state: RequestState;
  /** 요청을 보낸 때 */
  sentAt: string;
  /** 처리된 때 (대기 중이면 null) */
  doneAt: string | null;
}

export const REQUEST_STATE_KO: Record<RequestState, string> = { pending: '대기 중', answered: '답장 옴', released: '승인됨' };

/** 요청 메시지 하나의 상태: 그 뒤 같은 사례(또는 사례 없는) 보호 담당자 메시지 중 공개 승인이 있으면 승인, 답장이 있으면 답장 옴. */
export function statusOf(messages: ClinicMessage[], request: ClinicMessage): RequestStatus {
  const at = messages.indexOf(request);
  const after = messages.slice(at + 1).filter((m) => m.sender === 'security' && (m.caseId === request.caseId || m.caseId == null));
  const rel = after.find((m) => m.kind === 'release');
  if (rel) return { state: 'released', sentAt: request.createdAt, doneAt: rel.createdAt };
  const rep = after.find((m) => m.kind === 'reply');
  if (rep) return { state: 'answered', sentAt: request.createdAt, doneAt: rep.createdAt };
  return { state: 'pending', sentAt: request.createdAt, doneAt: null };
}

/** 이 사례에 since 뒤로(until 전까지) 보낸 마지막 요청의 상태 (없으면 null) */
export function latestRequest(messages: ClinicMessage[], caseId: CaseId | null, since = '', until?: string): RequestStatus | null {
  const reqs = messages.filter(
    (m) => m.sender === 'clinician' && m.kind === 'access_request' && m.caseId === caseId && m.createdAt >= since && (!until || m.createdAt < until),
  );
  const last = reqs[reqs.length - 1];
  return last ? statusOf(messages, last) : null;
}
