// 의료진 화면의 개인정보 보호 담당자 메시지 (세부 정보 요청 · 확인 요청 · 답장).
// 대화 하나(질의 환자 하나)에 묶인다. 새 대화를 시작하면 서버 목록이 비고, 읽음 표시도 처음부터 센다.
// 백엔드가 메시지를 지원하지 않으면(api_server) supported=false가 되고 화면은 요청 기능을 숨긴다.

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import type { ClinicMessage, PostClinicMessageRequest } from '../types/domain';
import { useWorkspace } from './WorkspaceContext';

const POLL_MS = 4000;

interface ClinicMessagesValue {
  /** null: 아직 모름 · false: 이 백엔드는 메시지를 지원하지 않음 */
  supported: boolean | null;
  messages: ClinicMessage[];
  /** 아직 열어 보지 않은 보호 담당자 메시지 수 */
  unread: number;
  /** 마지막 메시지가 보호 담당자의 확인 요청이면 그 메시지 (의료진이 답할 차례) */
  awaitingReply: ClinicMessage | null;
  markRead(): void;
  send(request: PostClinicMessageRequest): Promise<boolean>;
  sending: boolean;
  error: string | null;
  /** 머리줄 알림 · 확인 요청 띠에서 '메시지 열기'를 누른 횟수. 진료 화면이 바뀌는 것을 보고 메시지 탭을 연다. */
  openRequest: number;
  requestOpen(): void;
}

const Ctx = createContext<ClinicMessagesValue | null>(null);

export function ClinicMessagesProvider({ children }: { children: ReactNode }) {
  const { api, state } = useWorkspace();
  const contextId = state.patient.data?.contextId ?? null;
  const [supported, setSupported] = useState<boolean | null>(api.listClinicMessages ? null : false);
  const [messages, setMessages] = useState<ClinicMessage[]>([]);
  const [seen, setSeen] = useState(0);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openRequest, setOpenRequest] = useState(0);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  // 새 대화(다른 질의 환자)로 바뀌면 읽음 표시를 처음부터 센다.
  useEffect(() => {
    setSeen(0);
    setMessages([]);
  }, [contextId]);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      if (!api.listClinicMessages) return;
      try {
        const list = await api.listClinicMessages(signal);
        if (!alive.current) return;
        if (list === null) {
          setSupported(false);
          return;
        }
        setSupported(true);
        setMessages((old) => (old.length === list.length && old.every((m, i) => m.messageId === list[i].messageId) ? old : list));
      } catch {
        /* 다음 주기에 다시 받는다 */
      }
    },
    [api],
  );

  useEffect(() => {
    if (supported === false || !contextId) return;
    const ctl = new AbortController();
    void load(ctl.signal);
    const t = window.setInterval(() => void load(), POLL_MS);
    return () => {
      ctl.abort();
      window.clearInterval(t);
    };
  }, [load, supported, contextId]);

  const send = useCallback(
    async (request: PostClinicMessageRequest) => {
      if (!api.postClinicMessage) return false;
      setSending(true);
      setError(null);
      try {
        const list = await api.postClinicMessage(request);
        if (!alive.current) return true;
        setMessages(list);
        setSeen(list.length);
        return true;
      } catch (e) {
        if (alive.current) setError(e instanceof Error ? e.message : '메시지를 보내지 못했습니다.');
        return false;
      } finally {
        if (alive.current) setSending(false);
      }
    },
    [api],
  );

  const value = useMemo<ClinicMessagesValue>(() => {
    const last = messages[messages.length - 1];
    return {
      supported,
      messages,
      unread: messages.slice(seen).filter((m) => m.sender === 'security').length,
      awaitingReply: last && last.sender === 'security' && last.kind === 'check_request' ? last : null,
      markRead: () => setSeen(messages.length),
      send,
      sending,
      error,
      openRequest,
      requestOpen: () => setOpenRequest((n) => n + 1),
    };
  }, [supported, messages, seen, send, sending, error, openRequest]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useClinicMessages(): ClinicMessagesValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useClinicMessages는 ClinicMessagesProvider 안에서만 쓸 수 있습니다.');
  return v;
}
