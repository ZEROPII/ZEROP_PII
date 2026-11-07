import { ChevronRight } from 'lucide-react';
import type { LaunchProgress } from '../../types/domain';

type Step = NonNullable<LaunchProgress['step']>;
const AT: Record<Step, number> = { target: 0, extractor: 1, rewriter: 2, recheck: 2 };

/**
 * 진료 지원 AI가 답을 만드는 단계를 막대 셋으로 보인다 (걸린 시간은 보이지 않는다).
 *   ① first(답 쓰기 · 사례 찾기) → ② 보호 기준 확인 → ③ 필요하면 고쳐 쓰기 (고칠 값이 있을 때만 거친다)
 * 서버 진행(step)이 없으면(결정적 응답기 · 아직 받기 전) 첫 단계로 둔다.
 */
export function StageTrack({ step, first, stopping = false }: { step?: LaunchProgress['step']; first: string; stopping?: boolean }) {
  const at = step ? AT[step] : 0;
  const steps = [first, '보호 기준 확인', '필요하면 고쳐 쓰기'];
  return (
    <div className={`stage-track ${stopping ? 'is-stopping' : ''}`}>
      <ol aria-hidden className="grid grid-cols-3 gap-1.5">
        {steps.map((label, i) => (
          <li key={label} data-state={i < at ? 'done' : i === at ? 'now' : 'next'} className="min-w-0">
            <span className="stage-bar" />
            <span className="stage-label">{label}</span>
          </li>
        ))}
      </ol>
      <span className="sr-only">{stopping ? '멈추는 중입니다' : `${at + 1}단계 ${steps[at]} 중입니다`}</span>
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
