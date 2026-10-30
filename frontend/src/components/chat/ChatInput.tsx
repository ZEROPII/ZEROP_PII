import { Loader2, SendHorizontal } from 'lucide-react';
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
    // 한글 조합 중 Enter는 글자 확정용이므로 전송하지 않는다.
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
      className="flex items-end gap-2 rounded-xl border border-slate-300 bg-white p-1.5 pl-3 shadow-sm focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-100"
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
        className="max-h-[140px] min-h-[36px] flex-1 resize-none bg-transparent py-2 text-[13px] leading-5 text-slate-800 outline-none placeholder:text-slate-400 disabled:cursor-not-allowed"
      />
      <button
        type="submit"
        disabled={!canSend}
        aria-label="질문 보내기"
        className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-blue-600 text-white transition-colors hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500 disabled:bg-slate-300"
      >
        {sending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <SendHorizontal className="h-4 w-4" aria-hidden />}
      </button>
    </form>
  );
}
