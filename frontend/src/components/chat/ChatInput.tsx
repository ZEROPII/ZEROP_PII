import { ArrowUp, Loader2, Square } from 'lucide-react';
import { useEffect, useRef, type KeyboardEvent } from 'react';

interface Props {
  value: string;
  onChange(value: string): void;
  onSubmit(): void;
  disabled: boolean;
  sending: boolean;
  placeholder: string;
  /** 답을 기다리는 동안 보내기 단추 자리에 '멈추기'를 둔다 (실제 LLM 대화) */
  onStop?: () => void;
  stopping?: boolean;
}

const MAX_HEIGHT = 140;

export function ChatInput({ value, onChange, onSubmit, disabled, sending, placeholder, onStop, stopping = false }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const canSend = !disabled && !sending && value.trim().length > 0;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`;
  }, [value]);

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    // 한글 조합 중 Enter는 글자 확정용이므로 보내지 않는다.
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (canSend) onSubmit();
    }
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (canSend) onSubmit();
      }}
      className="flex items-end gap-2 rounded-[14px] border border-line-input bg-surface p-1.5 pl-3.5 focus-within:border-focus focus-within:shadow-[0_0_0_2px_var(--zp-iris-tint)]"
    >
      <label htmlFor="chat-input" className="sr-only">
        질문 입력 (Enter로 보내기, Shift+Enter로 줄바꿈)
      </label>
      <textarea
        id="chat-input"
        ref={ref}
        rows={1}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        disabled={disabled}
        className="max-h-[140px] min-h-[38px] flex-1 resize-none bg-transparent py-2 text-sm leading-[22px] text-ink outline-none placeholder:text-ink-3 focus-visible:outline-none disabled:cursor-not-allowed"
      />
      {sending && onStop ? (
        <button
          type="button"
          onClick={onStop}
          disabled={stopping}
          aria-label={stopping ? '멈추는 중' : '답 기다리기 멈추기'}
          title={stopping ? '멈추는 중' : '멈추기: 답을 받지 않고 질문을 입력칸으로 돌려놓습니다'}
          className="btn-primary h-9 w-9 shrink-0 px-0"
        >
          {stopping ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Square className="h-3.5 w-3.5 fill-current" aria-hidden />}
        </button>
      ) : (
        <button type="submit" disabled={!canSend} aria-label="질문 보내기" className="btn-primary h-9 w-9 shrink-0 px-0">
          {sending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <ArrowUp className="h-4 w-4" aria-hidden />}
        </button>
      )}
    </form>
  );
}
