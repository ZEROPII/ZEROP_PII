// 진료 지원 AI 열기가 실패했을 때 외래 목록에 남기는 안내 (ADR-0031).
// 알림(토스트)은 몇 초 뒤 사라져, 오래 기다린 끝에 끊기면 무슨 일인지 모른 채 단추만 원래대로 돌아왔다.

export interface OpenFailure {
  /** 무엇이 실패했는지 (서버가 알려 준 까닭, 없으면 상태로 짐작한 것) */
  detail: string;
  /** 다음에 할 일 */
  hint: string | null;
  /** 다시 시도해 볼 만한지 */
  retry: boolean;
}

/** 서버가 응답하지 않고 앞단(프록시 · 터널)이 끊은 상태 코드 */
const GATEWAY = new Set([502, 503, 504, 520, 521, 522, 523, 524]);

/**
 * status: HTTP 상태(연결 못 함은 0) · message: 받은 오류 문구 · seconds: 누르고 끊길 때까지 걸린 초.
 * 서버가 까닭을 적어 보냈으면 그대로 쓰고, 앞단이 끊었으면(본문 없는 502 등) 그렇게 알린다.
 */
export function openFailure(status: number, message: string, seconds: number | null): OpenFailure {
  const took = seconds != null && seconds >= 1 ? `, ${Math.round(seconds)}초 지나서` : '';
  if (!status) return { detail: '서버에 연결할 수 없습니다.', hint: '서버가 켜져 있는지, 인터넷 연결을 확인한 뒤 다시 시도하세요.', retry: true };
  const generic = message.startsWith('진료 지원 AI를 열지 못했습니다 (HTTP');
  if (GATEWAY.has(status) && generic)
    return {
      detail: `응답을 기다리다 연결이 끊겼습니다 (HTTP ${status}${took}).`,
      hint: '가릴 값이 많은 환자는 고친 답을 여러 번 다시 확인하느라 오래 걸릴 수 있습니다. 서버가 그 사이 답을 마쳤으면 다시 시도할 때 바로 열립니다.',
      retry: true,
    };
  if (status === 502) return { detail: message, hint: '대상 AI가 잠시 응답하지 않았을 수 있습니다. 잠시 뒤 다시 시도하세요.', retry: true };
  if (status === 401) return { detail: '로그인이 끝났습니다. 다시 로그인한 뒤 여세요.', hint: null, retry: false };
  if (status === 404) return { detail: message, hint: '다른 진료 목적을 고르거나 다른 환자를 여세요.', retry: false };
  return { detail: message, hint: null, retry: true };
}
