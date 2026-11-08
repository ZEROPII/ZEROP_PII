import { Check, ChevronRight, Loader2, Square } from 'lucide-react';
import type { LaunchProgress } from '../../types/domain';

type Step = NonNullable<LaunchProgress['step']>;
const ORDER: Step[] = ['target', 'extractor', 'rewriter', 'recheck'];

/** 배너에 보일 문장: 지금 무엇을 하는지 (걸린 시간은 보이지 않는다) */
const MESSAGE: Record<'answer' | 'launch', Record<Step, string>> = {
  answer: {
    target: '진료 지원 AI가 답을 쓰고 있습니다',
    extractor: '답에 환자를 알아볼 수 있는 값이 있는지 확인하고 있습니다',
    rewriter: '알아볼 수 있는 값을 고쳐 쓰고 있습니다',
    recheck: '고친 답을 한 번 더 확인하고 있습니다',
  },
  launch: {
    target: '비슷한 과거 사례를 찾아 첫 답을 쓰고 있습니다',
    extractor: '첫 답에 환자를 알아볼 수 있는 값이 있는지 확인하고 있습니다',
    rewriter: '알아볼 수 있는 값을 고쳐 쓰고 있습니다',
    recheck: '고친 첫 답을 한 번 더 확인하고 있습니다',
  },
};
const LABELS: Record<'answer' | 'launch', string[]> = {
  answer: ['답 쓰기', '보호 확인', '고쳐 쓰기', '다시 확인'],
  launch: ['사례 찾기', '보호 확인', '고쳐 쓰기', '다시 확인'],
};

/**
 * 진료 지원 AI가 답을 만드는 단계 (ADR-0040): 위에는 지금 하는 일을 적은 배너, 아래에는 단계 막대 넷.
 *   답 쓰기(사례 찾기) → 보호 확인 → 고쳐 쓰기 → 다시 확인. 뒤의 둘은 보호 기준을 넘는 값이 있을 때만 거쳐 점선으로 둔다.
 * 끝난 단계는 채운 막대와 확인 표시, 지금 단계는 빛이 지나가는 막대와 진한 이름표. 서버 진행(step)이 없으면 첫 단계로 둔다.
 * onStop을 주면 오른쪽 아래에 '멈추기'가 보인다 (실제 LLM일 때만).
 */
export function StageTrack({
  step,
  mode = 'answer',
  stopping = false,
  onStop,
  done = false,
}: {
  step?: LaunchProgress['step'];
  mode?: 'answer' | 'launch';
  stopping?: boolean;
  onStop?: () => void;
  /** 모두 마친 상태 (잠깐 보이고 다음 화면으로 넘어갈 때) */
  done?: boolean;
}) {
  const at = done ? ORDER.length : step ? ORDER.indexOf(step) : 0;
  const labels = LABELS[mode];
  const message = done ? '보호 기준에 맞춰 마쳤습니다' : stopping ? '멈추는 중입니다. 보낸 호출 하나는 끝까지 받고 멈춥니다' : MESSAGE[mode][ORDER[Math.max(0, at)]];
  return (
    <div className="progress-panel" data-state={done ? 'done' : stopping ? 'stopping' : 'running'}>
      <div className="progress-banner">
        {done ? (
          <Check className="h-4 w-4 shrink-0" strokeWidth={3} aria-hidden />
        ) : (
          <span className="chev-run" aria-hidden>
            <ChevronRight strokeWidth={2.8} />
            <ChevronRight strokeWidth={2.8} />
            <ChevronRight strokeWidth={2.8} />
          </span>
        )}
        <span className="relative min-w-0 flex-1">{message}{done ? '' : '…'}</span>
      </div>
      <ol aria-hidden className="mt-3 grid grid-cols-4 gap-2">
        {labels.map((label, i) => (
          <li key={label} data-state={i < at ? 'done' : i === at ? 'now' : 'next'} data-optional={i >= 2 ? '' : undefined} className="min-w-0">
            <span className="pseg">
              {i < at && (
                <span className="pseg-check">
                  <Check strokeWidth={3.4} />
                </span>
              )}
            </span>
            <span className="plabel">{label}</span>
          </li>
        ))}
      </ol>
      <div className="mt-2.5 flex items-end justify-between gap-3">
        <p className="text-[11.5px] leading-5 text-ink-3">고쳐 쓰기 · 다시 확인은 환자를 알아볼 수 있는 값이 있을 때만 거칩니다.</p>
        {onStop && !done && (
          <button type="button" className="btn-ghost btn-sm h-7 shrink-0 gap-1.5 border border-line bg-surface text-ink-2" onClick={onStop} disabled={stopping}>
            {stopping ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> : <Square className="h-3 w-3 fill-current" aria-hidden />}
            {stopping ? '멈추는 중' : '멈추기'}
          </button>
        )}
      </div>
      <span className="sr-only">{done ? '모두 마쳤습니다' : stopping ? '멈추는 중입니다' : `${at + 1}단계 ${labels[at]}: ${message}`}</span>
    </div>
  );
}

/** 여는 중 단추 안의 흐르는 꺾쇠 (돌아가는 표시 대신) */
export function RunningChevrons() {
  return (
    <span className="chev-run" aria-hidden>
      <ChevronRight strokeWidth={2.6} />
      <ChevronRight strokeWidth={2.6} />
      <ChevronRight strokeWidth={2.6} />
    </span>
  );
}
