// API 구현 선택. 환경 변수만 바꾸면 Mock ↔ 실제 백엔드가 전환된다.

import { createHttpApi } from './httpApi';
import { createMockApi } from './mock/mockApi';
import type { ClinicalCaseApi } from './types';

export type ApiMode = 'mock' | 'http';

export const apiMode: ApiMode = import.meta.env.VITE_API_MODE === 'http' ? 'http' : 'mock';

function createApi(): ClinicalCaseApi {
  if (apiMode === 'http') {
    const baseUrl = import.meta.env.VITE_API_BASE_URL;
    if (!baseUrl) throw new Error('VITE_API_MODE=http 에는 VITE_API_BASE_URL 설정이 필요합니다.');
    return createHttpApi(baseUrl);
  }
  return createMockApi();
}

export const api: ClinicalCaseApi = createApi();
export { ApiError } from './types';
export type { ClinicalCaseApi } from './types';
