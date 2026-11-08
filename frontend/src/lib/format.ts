export function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false });
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
}

/**
 * 기록의 날짜 값('1998' · '1998-12' · '1998-12-03' · '1998-Q4')을 진료 화면 말로 ('1998년' · '1998년 12월' · '1998년 4분기').
 * 값 전체가 이 꼴일 때만 바꾸고, 다른 글은 그대로 둔다 (ADR-0043, 화면에만 쓴다: 판정 · 기록 값은 그대로).
 */
export function periodKo(text: string): string {
  const t = text.trim();
  let m = /^(\d{4})$/.exec(t);
  if (m) return `${m[1]}년`;
  m = /^(\d{4})-(\d{2})$/.exec(t);
  if (m) return `${m[1]}년 ${Number(m[2])}월`;
  m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(t);
  if (m) return `${m[1]}년 ${Number(m[2])}월 ${Number(m[3])}일`;
  m = /^(\d{4})-Q([1-4])$/.exec(t);
  if (m) return `${m[1]}년 ${m[2]}분기`;
  return text;
}
