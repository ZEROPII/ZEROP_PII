// 의료 용어 RAG API. 실제 백엔드(api_server · webdemo 모두 /api/terminology)와 Mock(예시 용어 15개)이 같은 모양을 돌려준다.
// LLM은 부르지 않는다. 검색 · 카드 · 답변 속 용어 찾기는 모두 용어 DB 조회다.

import { detectLocal } from '../lib/termText';
import type { TermAttribute, TermCard, TermDetectResult, TermPage, TermStatus, TermSummary, TermView } from '../types/terminology';
import { apiMode } from './index';
import { mockSurfaces, mockTermCards } from './mock/mockTerminology';
import { ApiError } from './types';

export interface TermApi {
  status(signal?: AbortSignal): Promise<TermStatus>;
  search(q: string, opts: { attribute?: TermAttribute | null; limit?: number; view: TermView }, signal?: AbortSignal): Promise<TermSummary[]>;
  card(nodeId: string, view: TermView, signal?: AbortSignal): Promise<TermCard>;
  list(opts: { attribute?: TermAttribute | null; reviewStatus?: string | null; sensitive?: boolean | null; limit?: number; offset?: number; view: TermView }, signal?: AbortSignal): Promise<TermPage>;
  detect(texts: string[], view: TermView, signal?: AbortSignal): Promise<TermDetectResult>;
}

const UNAVAILABLE = '용어 DB를 열 수 없습니다. 서버 폴더에서 python scripts/build_terminology_db.py 를 실행하세요.';

function base(): string {
  return (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/+$/, '');
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${base()}/terminology${path}`, {
      ...init,
      credentials: 'include',
      headers: { Accept: 'application/json', ...(init.body ? { 'Content-Type': 'application/json' } : {}) },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError('서버에 연결할 수 없습니다.');
  }
  if (res.status === 503) throw new ApiError(UNAVAILABLE, 503);
  if (res.status === 404) throw new ApiError('용어 DB에 없는 항목이거나, 용어 기능이 없는 서버입니다.', 404);
  if (!res.ok) throw new ApiError(`용어 조회가 실패했습니다 (HTTP ${res.status}).`, res.status);
  return (await res.json()) as T;
}

function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== '') p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : '';
}

const httpTermApi: TermApi = {
  status: (signal) => request('/status', { signal }),
  search: (q, { attribute, limit = 20, view }, signal) => request(`/search${qs({ q, attribute, limit, view })}`, { signal }),
  card: (nodeId, view, signal) => request(`/${encodeURIComponent(nodeId)}${qs({ view })}`, { signal }),
  list: ({ attribute, reviewStatus, sensitive, limit = 50, offset = 0, view }, signal) =>
    request(qs({ attribute, review_status: reviewStatus, is_sensitive: sensitive, limit, offset, view }), { signal }),
  detect: (texts, view, signal) => request('/detect', { method: 'POST', body: JSON.stringify({ texts, view }), signal }),
};

// ── Mock ─────────────────────────────────────────────────────────────
function forView<T extends TermSummary>(t: T, view: TermView): T {
  if (view === 'security') return t;
  const { k_patients: _k, total_patients: _t, ...rest } = t;
  return rest as T;
}

const mockTermApi: TermApi = {
  async status() {
    const cards = mockTermCards();
    return { available: true, generated: false, mock: true, total: cards.length, explained: cards.length, reviewed: 1, sensitive: 0,
      by_attribute: { DX: cards.filter((c) => c.attribute === 'DX').length, MED: cards.filter((c) => c.attribute === 'MED').length, PROC: cards.filter((c) => c.attribute === 'PROC').length },
      llm_models: [], build_command: 'python scripts/build_terminology_db.py', db: '예시 데이터' };
  },
  async search(q, { attribute, limit = 20, view }) {
    const t = q.trim().toLowerCase();
    return mockTermCards()
      .filter((c) => (!attribute || c.attribute === attribute) &&
        [c.canonical_label, c.plain_explanation ?? '', c.standard_code ?? '', ...c.aliases].some((s) => s.toLowerCase().includes(t)))
      .slice(0, limit)
      .map((c) => forView(c, view));
  },
  async card(nodeId, view) {
    const c = mockTermCards().find((x) => x.node_id === nodeId);
    if (!c) throw new ApiError('예시 용어에 없는 항목입니다.', 404);
    return forView(c, view);
  },
  async list({ attribute, reviewStatus, sensitive, limit = 50, offset = 0, view }) {
    const all = mockTermCards().filter((c) => (!attribute || c.attribute === attribute) && (!reviewStatus || c.review_status === reviewStatus) &&
      (sensitive == null || c.is_sensitive === sensitive));
    return { total: all.length, limit, offset, items: all.slice(offset, offset + limit).map((c) => forView(c, view)) };
  },
  async detect(texts, view) {
    const surfaces = mockSurfaces();
    const cards = new Map(mockTermCards().map((c) => [c.node_id, c]));
    const mentions = texts.map((t) => detectLocal(t, surfaces));
    const terms: Record<string, TermSummary> = {};
    for (const m of mentions.flat()) {
      const c = cards.get(m.node_id)!;
      terms[m.node_id] = { ...forView(c, view), mentions: (terms[m.node_id]?.mentions ?? 0) + 1 };
    }
    return { mentions, terms };
  },
};

export const terminologyApi: TermApi = apiMode === 'http' ? httpTermApi : mockTermApi;
export { mockTermApi };
