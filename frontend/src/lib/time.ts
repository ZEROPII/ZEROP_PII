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

/** 초 단위 epoch → '11-07 14:32' (같은 해) 또는 '2025-11-07 14:32' */
export function dateTime(epochSec: number, now = Date.now() / 1000): string {
  const d = new Date(epochSec * 1000);
  const p = (n: number) => String(n).padStart(2, '0');
  const md = `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  return d.getFullYear() === new Date(now * 1000).getFullYear() ? md : `${d.getFullYear()}-${md}`;
}

/** 끝나는 시각까지 남은 시간 (분은 올림, 넘쳐 보이지 않게 시간은 그대로): '12시간 남음' · '11시간 30분 남음' · '25분 남음' · '끝남' */
export function timeLeft(untilSec: number, now = Date.now() / 1000): string {
  const s = untilSec - now;
  if (s <= 0) return '끝남';
  const total = Math.ceil(s / 60);
  const h = Math.floor(total / 60);
  const m = total % 60;
  if (!h) return `${m}분 남음`;
  return m ? `${h}시간 ${m}분 남음` : `${h}시간 남음`;
}
