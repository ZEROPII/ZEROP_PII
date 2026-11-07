import { useCallback, useEffect, useState } from 'react';

export type ThemeChoice = 'system' | 'light' | 'dark';

function read(): ThemeChoice {
  try {
    const t = localStorage.getItem('zp-theme');
    return t === 'light' || t === 'dark' ? t : 'system';
  } catch {
    return 'system';
  }
}

/** 테마: OS 설정을 따르거나 라이트/다크로 고정. 브라우저 저장소를 못 쓰면 이번 화면에서만 바뀐다. */
export function useTheme() {
  const [theme, setTheme] = useState<ThemeChoice>(read);
  useEffect(() => {
    const el = document.documentElement;
    if (theme === 'system') el.removeAttribute('data-theme');
    else el.setAttribute('data-theme', theme);
    try {
      if (theme === 'system') localStorage.removeItem('zp-theme');
      else localStorage.setItem('zp-theme', theme);
    } catch {
      /* 저장 못 해도 화면은 바뀐다 */
    }
  }, [theme]);
  const cycle = useCallback(() => setTheme((t) => (t === 'system' ? 'dark' : t === 'dark' ? 'light' : 'system')), []);
  return { theme, setTheme, cycle };
}
