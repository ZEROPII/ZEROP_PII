// 백엔드 주소와 로그인 세션 끝남 알림을 API 모듈끼리 나눠 쓴다.
//
// 로그인은 HttpOnly 쿠키(mc_session)라 화면 코드는 토큰을 보지 않는다. 어떤 요청이든 401이 오면
// (세션이 끝났거나 서버를 다시 켜 쿠키가 무효) 알림을 보내고, AuthProvider가 로그인 화면으로 돌린다.

export const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/+$/, '');

/** FHIR 경로는 /api 옆(/fhir)에 있다. API_BASE가 절대 주소면 같은 호스트의 /fhir. */
export const FHIR_BASE = API_BASE.replace(/\/api$/, '') + '/fhir';

export const UNAUTHORIZED_EVENT = 'medicloak:unauthorized';

export function notifyUnauthorized(): void {
  try {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  } catch {
    /* 테스트 환경 등 window가 없으면 무시 */
  }
}
