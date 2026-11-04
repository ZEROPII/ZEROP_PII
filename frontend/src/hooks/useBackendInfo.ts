import { useEffect, useState } from 'react';
import { apiMode } from '../api';

export interface BackendInfo {
  kind: 'mock' | 'webdemo' | 'medicloak' | 'research' | 'unknown' | 'offline';
  label: string;
  detail: string;
  monitor: boolean;
  /** medicloak: 의료진 대화의 대상 AI가 실제(또는 dry-run) LLM인지 */
  llmLive?: boolean;
}

interface Health {
  backend?: string;
  llm?: string | { mode?: string; label?: string; live?: boolean };
  arm?: string;
}

const MOCK: BackendInfo = { kind: 'mock', label: '예시 데이터', detail: '브라우저 안 Mock Service. 숫자는 화면 확인용 예시입니다.', monitor: false };

/** 연결된 백엔드 종류. 관제 API는 데모 서버(webdemo)와 운영 서버(medicloak)에 있다. */
export function useBackendInfo(): BackendInfo | null {
  const [info, setInfo] = useState<BackendInfo | null>(apiMode === 'mock' ? MOCK : null);
  useEffect(() => {
    if (apiMode === 'mock') return;
    const base = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/+$/, '');
    const ctl = new AbortController();
    fetch(`${base}/health`, { signal: ctl.signal, credentials: 'include' })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((h: Health) => {
        const llm = typeof h.llm === 'object' ? h.llm : undefined;
        if (h.backend === 'medicloak')
          setInfo({
            kind: 'medicloak',
            label: llm?.label ?? '운영 서버',
            detail: `MediCloak 운영 서버 · 의료진 대화의 대상 AI: ${llm?.label ?? '알 수 없음'} · 보내기 전 확인과 레드팀은 결정적 응답기`,
            monitor: true,
            llmLive: !!llm?.live,
          });
        else if (h.backend === 'webdemo')
          setInfo({ kind: 'webdemo', label: '데모 서버', detail: '결정적 응답기로 의료 파이프라인을 그대로 돌립니다 (LLM 호출 없음).', monitor: true });
        else setInfo({ kind: 'research', label: '연구 서버', detail: `api_server ${h.arm ?? ''} ${typeof h.llm === 'string' ? h.llm : ''}`.trim(), monitor: false });
      })
      .catch((e) => {
        if (e instanceof DOMException && e.name === 'AbortError') return;
        setInfo({ kind: 'offline', label: '서버 연결 안 됨', detail: '백엔드가 켜져 있는지 확인하세요.', monitor: false });
      });
    return () => ctl.abort();
  }, []);
  return info;
}
