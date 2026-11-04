// 로그인 상태 (python -m medicloak). 데모 서버 · Mock에서는 'demo'로, 로그인 없이 화면 전환 단추로 역할을 바꾼다.
//
//   loading : /api/auth/me 확인 중
//   demo    : 로그인 없는 서버 (webdemo) 또는 Mock
//   offline : 서버에 닿지 않음 (화면은 데모처럼 띄우고 각 화면이 연결 오류를 보여 준다)
//   anon    : 로그인 필요 → 로그인 화면
//   user    : 로그인함. 역할(user.role)이 화면을 정한다 (다른 역할 화면 주소로 오면 자기 처음 화면으로)

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import * as authApi from '../api/authApi';
import { UNAUTHORIZED_EVENT } from '../api/session';
import type { AuthUser } from '../types/domain';

export type AuthStatus = 'loading' | 'demo' | 'offline' | 'anon' | 'user';

interface AuthValue {
  status: AuthStatus;
  user: AuthUser | null;
  /** 로그인 화면에 띄울 안내 (세션이 끝나 돌아온 경우 등) */
  notice: string | null;
  /** 실패하면 오류 문구, 성공하면 null */
  login(username: string, password: string): Promise<string | null>;
  logout(): Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [user, setUser] = useState<AuthUser | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const statusRef = useRef(status);
  statusRef.current = status;

  // 서버에 닿지 않으면(켜는 중 · 프록시 502 등) 3초마다 다시 물어 데모 · 로그인 화면 중 맞는 쪽으로 간다
  useEffect(() => {
    const ctl = new AbortController();
    let timer: number | undefined;
    const check = () =>
      authApi.fetchMe(ctl.signal).then(
        (r) => {
          if (r.kind === 'user') {
            setUser(r.user);
            setStatus('user');
            return;
          }
          setStatus(r.kind);
          if (r.kind === 'offline') timer = window.setTimeout(() => void check(), 3000);
        },
        () => undefined,
      );
    void check();
    return () => {
      ctl.abort();
      if (timer) window.clearTimeout(timer);
    };
  }, []);

  // 어느 요청이든 401이면 세션이 끝났거나 로그인이 필요한 서버다: 로그인 화면으로
  useEffect(() => {
    function onUnauthorized() {
      const s = statusRef.current;
      if (s === 'anon' || s === 'loading') return;
      if (s === 'user') setNotice('로그인 시간이 지났거나 서버를 다시 켰습니다. 다시 로그인하세요.');
      setUser(null);
      setStatus('anon');
    }
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const r = await authApi.login(username, password);
    if (!r.ok) return r.message;
    setUser(r.user);
    setNotice(null);
    setStatus('user');
    return null;
  }, []);

  const logout = useCallback(async () => {
    await authApi.logout();
    setUser(null);
    setNotice('로그아웃했습니다.');
    setStatus('anon');
  }, []);

  const value = useMemo(() => ({ status, user, notice, login, logout }), [status, user, notice, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const v = useContext(AuthContext);
  if (!v) throw new Error('useAuth는 AuthProvider 안에서만 쓸 수 있습니다.');
  return v;
}
