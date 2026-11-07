import type { ReactNode } from 'react';
import { TONE_CHIP, type Tone } from '../../lib/riskStyles';

/** 상태 모양: 안전 원, 주의 마름모, 위험 삼각형, 브랜드 고리. 색만으로 구분하지 않기 위해 모양을 함께 쓴다. */
export function StatusIcon({ tone, className = 'h-3 w-3' }: { tone: Tone; className?: string }) {
  if (tone === 'danger')
    return (
      <svg viewBox="0 0 12 12" className={className} aria-hidden>
        <path d="M6 1 11 10H1Z" fill="currentColor" />
      </svg>
    );
  if (tone === 'caution')
    return (
      <svg viewBox="0 0 12 12" className={className} aria-hidden>
        <rect x="2" y="2" width="8" height="8" rx="1.4" transform="rotate(45 6 6)" fill="currentColor" />
      </svg>
    );
  if (tone === 'safe')
    return (
      <svg viewBox="0 0 12 12" className={className} aria-hidden>
        <circle cx="6" cy="6" r="4.6" fill="currentColor" />
      </svg>
    );
  return (
    <svg viewBox="0 0 12 12" className={className} aria-hidden>
      <circle cx="6" cy="6" r="4.2" fill="none" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
}

export function StatusChip({ tone, children, title, className = '' }: { tone: Tone; children: ReactNode; title?: string; className?: string }) {
  return (
    <span className={`chip ${TONE_CHIP[tone]} ${className}`} title={title}>
      {tone !== 'plain' && <StatusIcon tone={tone} />}
      {children}
    </span>
  );
}
