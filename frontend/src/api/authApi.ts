// 로그인 API (python -m medicloak). 데모 서버(python -m webdemo)에는 없어서 /auth/me가 404다.

import type { AuthUser } from '../types/domain';
import { apiMode } from './index';
import { API_BASE } from './session';

export type MeResult = { kind: 'user'; user: AuthUser } | { kind: 'anon' } | { kind: 'demo' } | { kind: 'offline' };

/** 404 → 로그인 없는 데모 서버, 401 → 로그인 필요, 200 → 로그인한 사용자. */
export async function fetchMe(signal?: AbortSignal): Promise<MeResult> {
  if (apiMode !== 'http') return { kind: 'demo' };
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/auth/me`, { credentials: 'include', headers: { Accept: 'application/json' }, signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    return { kind: 'offline' };
  }
  if (res.status === 404) return { kind: 'demo' };
  if (res.status === 401) return { kind: 'anon' };
  if (!res.ok) return { kind: 'offline' };
  const body = (await res.json()) as { user: AuthUser };
  return { kind: 'user', user: body.user };
}

export type LoginResult = { ok: true; user: AuthUser } | { ok: false; message: string };

export async function login(username: string, password: string): Promise<LoginResult> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      credentials: 'include',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
  } catch {
    return { ok: false, message: '서버에 연결할 수 없습니다. 서버가 켜져 있는지 확인하세요.' };
  }
  if (res.ok) return { ok: true, user: ((await res.json()) as { user: AuthUser }).user };
  if (res.status === 401) return { ok: false, message: '아이디 또는 비밀번호가 맞지 않습니다.' };
  if (res.status === 429) {
    let detail = '로그인을 여러 번 실패해 잠시 막았습니다. 몇 분 뒤 다시 시도하세요.';
    try {
      const b = (await res.json()) as { detail?: unknown };
      if (typeof b.detail === 'string') detail = b.detail;
    } catch {
      /* 본문 없음 */
    }
    return { ok: false, message: detail };
  }
  return { ok: false, message: `로그인하지 못했습니다 (HTTP ${res.status}).` };
}

export async function logout(): Promise<void> {
  try {
    await fetch(`${API_BASE}/auth/logout`, { method: 'POST', credentials: 'include', headers: { Accept: 'application/json' } });
  } catch {
    /* 서버가 꺼져 있어도 화면은 로그인으로 돌아간다 */
  }
}
