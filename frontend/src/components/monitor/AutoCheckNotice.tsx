// 관제 화면 위 한 줄: 자동 레드팀 점검이 도는 중이거나, 마지막 점검이 직전 점검보다 나빠졌을 때만 보인다 (ADR-0028).

import { AlertTriangle, Loader2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { monitorApi } from '../../api/monitorApi';
import type { AutoStatus } from '../../types/monitor';

export function AutoCheckNotice() {
  const [st, setSt] = useState<AutoStatus | null>(null);

  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const ctl = new AbortController();
    const load = () =>
      monitorApi.autoStatus(ctl.signal).then(
        (x) => {
          if (!alive) return;
          setSt(x);
          timer = window.setTimeout(load, x.running ? 4000 : 15000);
        },
        () => {
          if (alive) timer = window.setTimeout(load, 30000);
        },
      );
    void load();
    return () => {
      alive = false;
      ctl.abort();
      if (timer) window.clearTimeout(timer);
    };
  }, []);

  if (!st) return null;
  const auto = st.running && st.running.trigger !== 'manual' ? st.running : null;
  if (auto)
    return (
      <p role="status" className="mx-4 mb-3 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-control border border-line bg-surface px-3 py-2 text-[13px] text-ink-2 md:mx-6">
        <Loader2 className="h-4 w-4 shrink-0 animate-spin text-iris-text" aria-hidden />
        <span className="min-w-0 flex-1">
          {auto.trigger === 'daily' ? '정기 레드팀 점검' : '설정이 바뀌어 레드팀 점검'}을 자동으로 돌리는 중입니다{' '}
          <span className="num text-ink">
            (대화 {auto.done}/{auto.total}건)
          </span>
          . 의료진 질문이 먼저 처리됩니다.
        </span>
        <Link to="/report" className="font-semibold text-iris-text hover:underline">
          리포트에서 보기
        </Link>
      </p>
    );
  if (!st.alert) return null;
  const warn = st.alert.level === 'warn';
  return (
    <p
      role="alert"
      className={`mx-4 mb-3 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-control border px-3 py-2 text-[13px] md:mx-6 ${
        warn ? 'border-danger bg-danger-tint text-danger-text' : 'border-caution bg-caution-tint text-caution-text'
      }`}
    >
      <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden />
      <span className="min-w-0 flex-1">
        <b className="font-semibold">레드팀 점검 {st.alert.levelLabel}</b> ({st.alert.jobId}): {st.alert.text}
      </span>
      <Link to="/report" className="font-semibold underline-offset-2 hover:underline">
        리포트에서 비교 보기
      </Link>
    </p>
  );
}
