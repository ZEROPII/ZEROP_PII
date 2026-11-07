/** 초 단위 epoch → "방금", "3분 전", "2시간 전" */
export function relativeTime(epochSec: number, now = Date.now() / 1000): string {
  const d = Math.max(0, now - epochSec);
  if (d < 45) return '방금';
  if (d < 3600) return `${Math.round(d / 60)}분 전`;
  if (d < 86400) return `${Math.round(d / 3600)}시간 전`;
  return `${Math.round(d / 86400)}일 전`;
}

export function clockTime(epochSec: number): string {
  return new Date(epochSec * 1000).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
}

/** '사례1' → '사례 1' */
export function caseLabel(ref: string | null | undefined): string {
  return ref ? ref.replace(/^사례(\d+)$/, '사례 $1') : '';
}
