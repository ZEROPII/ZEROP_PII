import { ArrowUp, Loader2 } from 'lucide-react';
import { useEffect, useRef, type KeyboardEvent } from 'react';

interface Props {
  value: string;
  onChange(value: string): void;
  onSubmit(): void;
  disabled: boolean;
  sending: boolean;
  placeholder: string;
}

const MAX_HEIGHT = 140;

export function ChatInput({ value, onChange, onSubmit, disabled, sending, placeholder }: Props) {
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
      <button type="submit" disabled={!canSend} aria-label="질문 보내기" className="btn-primary h-9 w-9 shrink-0 px-0">
        {sending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <ArrowUp className="h-4 w-4" aria-hidden />}
      </button>
    </form>
  );
}
