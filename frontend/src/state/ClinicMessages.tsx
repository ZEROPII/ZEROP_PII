// 의료진 화면의 개인정보 보호 담당자 메시지 (세부 정보 요청 · 확인 요청 · 답장).
// 대화 하나(질의 환자 하나)에 묶인다. 새 대화를 시작하면 서버 목록이 비고, 읽음 표시도 처음부터 센다.
// 백엔드가 메시지를 지원하지 않으면(api_server) supported=false가 되고 화면은 요청 기능을 숨긴다.
// 읽음 표시는 대화마다 세션 저장소에 둔다 (새로 고침해도 읽은 답장이 다시 '새로 옴'이 되지 않게). 못 쓰면 메모리에만.

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
  /** 머리줄 알림에서 '메시지 열기'를 눌렀다. 진료 화면이 이것을 보고 메시지 탭을 연 뒤 consumeOpen으로 지운다. */
  openPending: boolean;
  requestOpen(): void;
  consumeOpen(): void;
}

const Ctx = createContext<ClinicMessagesValue | null>(null);

const seenKey = (contextId: string) => `zp-msg-seen:${contextId}`;

function loadSeen(contextId: string | null): number {
  if (!contextId) return 0;
  try {
    return Number(sessionStorage.getItem(seenKey(contextId))) || 0;
  } catch {
    return 0;
  }
}

function saveSeen(contextId: string | null, n: number): void {
  if (!contextId) return;
  try {
    sessionStorage.setItem(seenKey(contextId), String(n));
  } catch {
    /* 저장 못 해도 이번 화면에서는 동작 */
  }
}

/** enabled가 false면(보안 담당자 화면) 메시지를 받아 오지 않는다. 읽음 표시와 목록은 그대로 둔다. */
export function ClinicMessagesProvider({ children, enabled = true }: { children: ReactNode; enabled?: boolean }) {
  const { api, state } = useWorkspace();
  const contextId = state.patient.data?.contextId ?? null;
  const [supported, setSupported] = useState<boolean | null>(api.listClinicMessages ? null : false);
  const [messages, setMessages] = useState<ClinicMessage[]>([]);
  const [seen, setSeen] = useState(() => loadSeen(contextId));
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openPending, setOpenPending] = useState(false);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  // 새 대화(다른 질의 환자)로 바뀌면 그 대화의 읽음 표시를 불러온다 (처음이면 0).
  useEffect(() => {
    setSeen(loadSeen(contextId));
    setMessages([]);
  }, [contextId]);

  const markSeen = useCallback(
    (n: number) => {
      setSeen(n);
      saveSeen(contextId, n);
    },
    [contextId],
  );

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
    if (!enabled || supported === false || !contextId) return;
    const ctl = new AbortController();
    void load(ctl.signal);
    const t = window.setInterval(() => void load(), POLL_MS);
    return () => {
      ctl.abort();
      window.clearInterval(t);
    };
  }, [load, supported, contextId, enabled]);

  const send = useCallback(
    async (request: PostClinicMessageRequest) => {
      if (!api.postClinicMessage) return false;
      setSending(true);
      setError(null);
      try {
        const list = await api.postClinicMessage(request);
        if (!alive.current) return true;
        setMessages(list);
        markSeen(list.length);
        return true;
      } catch (e) {
        if (alive.current) setError(e instanceof Error ? e.message : '메시지를 보내지 못했습니다.');
        return false;
      } finally {
        if (alive.current) setSending(false);
      }
    },
    [api, markSeen],
  );

  const consumeOpen = useCallback(() => setOpenPending(false), []);

  const value = useMemo<ClinicMessagesValue>(() => {
    const last = messages[messages.length - 1];
    return {
      supported,
      messages,
      // 저장된 읽음 수가 목록보다 크면 서버 대화가 새로 시작된 것이다 (서버를 다시 켬) → 처음부터 센다
      unread: messages.slice(seen > messages.length ? 0 : seen).filter((m) => m.sender === 'security').length,
      awaitingReply: last && last.sender === 'security' && last.kind === 'check_request' ? last : null,
      markRead: () => {
        if (messages.length !== seen) markSeen(messages.length);
      },
      send,
      sending,
      error,
      openPending,
      requestOpen: () => setOpenPending(true),
      consumeOpen,
    };
  }, [supported, messages, seen, markSeen, send, sending, error, openPending, consumeOpen]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useClinicMessages(): ClinicMessagesValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useClinicMessages는 ClinicMessagesProvider 안에서만 쓸 수 있습니다.');
  return v;
}
