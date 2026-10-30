import { useEffect, useState } from 'react';
import { apiMode } from '../api';

export interface BackendInfo {
  kind: 'mock' | 'webdemo' | 'research' | 'unknown' | 'offline';
  label: string;
  detail: string;
  monitor: boolean;
}

const MOCK: BackendInfo = { kind: 'mock', label: '예시 데이터', detail: '브라우저 안 Mock Service. 숫자는 화면 확인용 예시입니다.', monitor: false };

/** 연결된 백엔드 종류. 데모 서버(webdemo)에만 관제 API가 있다. */
export function useBackendInfo(): BackendInfo | null {
  const [info, setInfo] = useState<BackendInfo | null>(apiMode === 'mock' ? MOCK : null);
  useEffect(() => {
    if (apiMode === 'mock') return;
    const base = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/+$/, '');
    const ctl = new AbortController();
    fetch(`${base}/health`, { signal: ctl.signal, credentials: 'include' })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((h: { backend?: string; llm?: string; arm?: string }) => {
        if (h.backend === 'webdemo')
          setInfo({ kind: 'webdemo', label: '데모 서버', detail: '결정적 응답기로 의료 파이프라인을 그대로 돌립니다 (LLM 호출 없음).', monitor: true });
        else setInfo({ kind: 'research', label: '연구 서버', detail: `api_server ${h.arm ?? ''} ${h.llm ?? ''}`.trim(), monitor: false });
      })
      .catch((e) => {
        if (e instanceof DOMException && e.name === 'AbortError') return;
        setInfo({ kind: 'offline', label: '서버 연결 안 됨', detail: '백엔드가 켜져 있는지 확인하세요.', monitor: false });
      });
    return () => ctl.abort();
  }, []);
  return info;
}
