import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';

interface ToastItem {
  id: number;
  text: string;
}

const ToastContext = createContext<(text: string) => void>(() => undefined);

let seq = 0;

/** 짧은 알림. 동작 이름과 같은 말로 결과를 알린다 (예: 검토 완료 → "검토 완료로 표시했습니다"). */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const push = useCallback((text: string) => {
    const id = ++seq;
    setItems((xs) => [...xs, { id, text }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), 3200);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed bottom-5 left-1/2 z-[60] flex -translate-x-1/2 flex-col items-center gap-2">
        {items.map((t) => (
          <div key={t.id} className="rounded-[14px] bg-toast px-4 py-2.5 text-[13px] text-toast-text shadow-overlay">
            {t.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
