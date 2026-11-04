// /auth/me 응답으로 서버 종류를 가른다: 404 데모 서버 · 401 로그인 필요 · 200 로그인함 · 연결 실패
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('./index', () => ({ apiMode: 'http' }));

import { fetchMe, login } from './authApi';

function respond(status: number, body: unknown = {}) {
  return vi.fn(async (_url: string, _init?: RequestInit) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
}

afterEach(() => vi.unstubAllGlobals());

describe('fetchMe', () => {
  it('404면 로그인 없는 데모 서버', async () => {
    vi.stubGlobal('fetch', respond(404, { detail: '로그인 없는 데모 서버입니다.' }));
    expect(await fetchMe()).toEqual({ kind: 'demo' });
  });
  it('401이면 로그인 화면', async () => {
    vi.stubGlobal('fetch', respond(401));
    expect(await fetchMe()).toEqual({ kind: 'anon' });
  });
  it('200이면 사용자와 역할', async () => {
    const user = { userId: 1, username: 'doctor1', displayName: '김서연', role: 'clinician', roleLabel: '의료진', department: '내과' };
    const f = respond(200, { user });
    vi.stubGlobal('fetch', f);
    expect(await fetchMe()).toEqual({ kind: 'user', user });
    expect(f.mock.calls[0][1]).toMatchObject({ credentials: 'include' });       // 쿠키 세션 (토큰을 화면 코드가 들고 있지 않음)
  });
  it('서버에 닿지 않으면 offline', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))));
    expect(await fetchMe()).toEqual({ kind: 'offline' });
  });
});

describe('login', () => {
  it('틀린 비밀번호와 잠금은 서버 문구 그대로', async () => {
    vi.stubGlobal('fetch', respond(401));
    expect(await login('doctor1', 'x')).toEqual({ ok: false, message: '아이디 또는 비밀번호가 맞지 않습니다.' });
    vi.stubGlobal('fetch', respond(429, { detail: '로그인을 잠시 막았습니다. 10분 뒤 다시 시도하세요.' }));
    expect(await login('doctor1', 'x')).toEqual({ ok: false, message: '로그인을 잠시 막았습니다. 10분 뒤 다시 시도하세요.' });
  });
});
