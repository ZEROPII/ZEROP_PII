import { Play } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { MONITOR_UNAVAILABLE, monitorApi, type PocSummary } from '../api/monitorApi';
import { ErrorState, LoadingState } from '../components/common/StatusViews';
import { StatusChip } from '../components/common/StatusChip';
import { BarRow, KTurnChart, type Series } from '../components/report/KTurnChart';
import { useToast } from '../components/layout/Toast';
import type { ArmKey, PocResult, RedTeamJob } from '../types/monitor';

const ARMS: { key: ArmKey; name: string; does: string; color: string }[] = [
  { key: 'C1', name: '누적 방어', does: '대화 전체에서 나온 단서를 합쳐 판단', color: 'var(--zp-series-1)' },
  { key: 'C1S', name: '턴별 방어', does: '매 턴 새로 판단, 앞선 답은 잊음', color: 'var(--zp-series-2)' },
  { key: 'C0', name: '방어 없음', does: '원래 답을 그대로 전달', color: 'var(--zp-series-3)' },
];

const DATASETS: Record<string, string> = {
  staged_feedback: '단계 공개형 응답, k 피드백 퍼저',
  staged_uniform: '단계 공개형 응답, 균등 퍼저',
  full_feedback: '전면 공개형 응답, k 피드백 퍼저',
  full_uniform: '전면 공개형 응답, 균등 퍼저',
};

function pct(p: number) {
  return `${(p * 100).toFixed(1)}%`;
}

function ResultView({ res, title }: { res: PocResult; title: string }) {
  const arms = ARMS.filter((a) => res.arms[a.key]);
  const n = arms.length ? res.arms[arms[0].key]!.n : 0;
  const kReq = Number(res.config.k_req ?? 5);
  const c1 = res.arms.C1;
  const c0 = res.arms.C0;
  const series: Series[] = arms.map((a) => ({ key: a.key, name: a.name, color: a.color, values: res.arms[a.key]!.kA_median }));
  const firstC0 = c0?.kA_median.findIndex((k) => k < kReq) ?? -1;

  const lead = c1
    ? c1.viol10.k === 0
      ? `누적 방어를 쓴 공격 대화 ${n}건에서는 후보가 ${kReq}명 아래로 줄어든 적이 한 번도 없었습니다. 대신 답변 유용도는 ${c1.utility.toFixed(2)}로 낮아졌습니다.`
      : `누적 방어를 써도 공격 대화 ${n}건 중 ${c1.viol10.k}건(${pct(c1.viol10.p)})에서 후보가 ${kReq}명 아래로 줄었습니다.`
    : `공격 대화 ${n}건의 결과입니다.`;

  return (
    <>
      <section className="grid gap-6 pb-5 pt-1 xl:grid-cols-[1fr_340px] xl:items-end">
        <p className="max-w-[30em] text-[21px] font-bold leading-[1.42] tracking-[-0.025em] md:text-2xl">{lead}</p>
        <p className="text-[13px] leading-relaxed text-ink-2">
          {title}. 같은 공격 질문을 세 가지 방식에 똑같이 보냈습니다. 후보 수는 답에 나온 단서와 조건이 같은 환자 수입니다.
        </p>
      </section>
      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="panel px-5 py-5">
          <h2 className="text-[15px] font-bold">턴이 지날수록 후보가 얼마나 줄었나</h2>
          <p className="mt-0.5 text-xs text-ink-3">대화 {n}건의 턴별 후보 수 중앙값, 세로축은 로그 눈금</p>
          <div className="mt-2">
            <KTurnChart
              series={series}
              kReq={kReq}
              markTurn={firstC0 >= 0 ? firstC0 : null}
              markLabel={firstC0 >= 0 && c0 ? `${firstC0}턴: 방어 없음이 ${c0.kA_median[firstC0]}명까지 줄어든 지점` : undefined}
            />
          </div>
        </div>
        <div className="panel px-5 py-5">
          <h2 className="text-[15px] font-bold">기준 아래로 내려간 대화</h2>
          <p className="mt-0.5 text-xs text-ink-3">질의 대상 환자의 후보가 {kReq}명 미만(1~{kReq - 1}명)으로 줄어든 적이 있는 대화</p>
          <div className="mt-3.5 grid gap-3">
            {arms.map((a) => {
              const v = res.arms[a.key]!.viol10;
              return <BarRow key={a.key} label={a.name} value={v.k} max={n} color={a.color} text={`${v.k}건 ${pct(v.p)}`} />;
            })}
          </div>
          <div className="my-4 h-px bg-line" />
          <h2 className="text-[15px] font-bold">답변 유용도</h2>
          <p className="mt-0.5 text-xs text-ink-3">원래 답을 그대로 전한 정도, 방어 없음 = 1.00</p>
          <div className="mt-3.5 grid gap-3">
            {arms.map((a) => {
              const u = res.arms[a.key]!.utility;
              return <BarRow key={a.key} label={a.name} value={u} max={1} color={a.color} text={u.toFixed(2)} />;
            })}
          </div>
        </div>
        <div className="panel overflow-x-auto px-5 pb-2 pt-4 xl:col-span-2">
          <h2 className="text-[15px] font-bold">방식별 요약</h2>
          <table className="mt-3 w-full min-w-[640px] text-[13px]">
            <thead>
              <tr className="text-left text-xs text-ink-3">
                <th className="border-b border-line px-3 py-2 font-semibold">방어 방식</th>
                <th className="border-b border-line px-3 py-2 font-semibold">하는 일</th>
                <th className="border-b border-line px-3 py-2 text-right font-semibold">기준 아래로 내려감</th>
                <th className="border-b border-line px-3 py-2 text-right font-semibold">처음 내려간 턴(중앙값)</th>
                <th className="border-b border-line px-3 py-2 text-right font-semibold">답변 유용도</th>
                <th className="border-b border-line px-3 py-2 text-right font-semibold">과하게 가린 비율</th>
              </tr>
            </thead>
            <tbody>
              {arms.map((a) => {
                const r = res.arms[a.key]!;
                return (
                  <tr key={a.key}>
                    <td className="border-b border-line px-3 py-2.5 last:border-0">
                      <span className="mr-2 inline-block h-2.5 w-2.5 rounded-[3px] align-[-1px]" style={{ background: a.color }} />
                      <b className="font-bold">{a.name}</b>
                    </td>
                    <td className="border-b border-line px-3 py-2.5 text-ink-2">{a.does}</td>
                    <td className="num border-b border-line px-3 py-2.5 text-right">{r.viol10.k}건</td>
                    <td className="border-b border-line px-3 py-2.5 text-right">{r.first_median != null ? `${r.first_median}턴` : '내려가지 않음'}</td>
                    <td className="num border-b border-line px-3 py-2.5 text-right">{r.utility.toFixed(2)}</td>
                    <td className="num border-b border-line px-3 py-2.5 text-right">{pct(r.overblock.p)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

export function ReportPage() {
  const toast = useToast();
  const [poc, setPoc] = useState<PocSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dataset, setDataset] = useState('staged_feedback');
  const [perType, setPerType] = useState(5);
  const [fuzzer, setFuzzer] = useState('feedback');
  const [job, setJob] = useState<RedTeamJob | null>(null);

  useEffect(() => {
    const ctl = new AbortController();
    monitorApi.poc(ctl.signal).then(setPoc, (e) => {
      if (!(e instanceof DOMException)) setError(e instanceof Error ? e.message : MONITOR_UNAVAILABLE);
    });
    return () => ctl.abort();
  }, []);

  useEffect(() => {
    if (!job || job.status === 'done' || job.status === 'error') return;
    const t = setTimeout(() => {
      monitorApi.job(job.id).then(
        (j) => {
          setJob(j);
          if (j.status === 'done') {
            setDataset('job');
            toast('레드팀 점검을 마쳤습니다.');
          }
        },
        () => undefined,
      );
    }, 1000);
    return () => clearTimeout(t);
  }, [job, toast]);

  const options = useMemo(() => {
    const o = Object.keys(DATASETS).filter((k) => poc?.[k]);
    return job?.result ? ['job', ...o] : o;
  }, [poc, job]);

  async function start() {
    try {
      const j = await monitorApi.startRedTeam(perType, fuzzer);
      setJob(j);
      toast('레드팀 점검을 시작했습니다.');
    } catch (e) {
      toast(e instanceof Error ? e.message : '점검을 시작하지 못했습니다.');
    }
  }

  if (error)
    return (
      <div className="mx-auto max-w-xl p-6">
        <ErrorState message={error} />
      </div>
    );
  if (!poc) return <LoadingState label="점검 결과를 불러오는 중" />;

  const res = dataset === 'job' && job?.result ? job.result : poc[dataset];
  const title = dataset === 'job' && job ? `방금 실행한 점검 (${job.fuzzer_label}, 유형마다 ${job.per_type}명)` : `2026-10-23 POC (${DATASETS[dataset]})`;
  const running = job && (job.status === 'running' || job.status === 'queued');

  return (
    <div className="scroll-thin h-full overflow-y-auto px-4 pb-6 pt-4 md:px-6">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <label className="text-[13px] text-ink-3" htmlFor="dataset">
          결과
        </label>
        <select id="dataset" value={dataset} onChange={(e) => setDataset(e.target.value)} className="h-9 rounded-control border border-line-input bg-surface px-3 text-[13px]">
          {options.map((k) => (
            <option key={k} value={k}>
              {k === 'job' ? '방금 실행한 점검' : `POC ${DATASETS[k]}`}
            </option>
          ))}
        </select>
        <span className="flex-1" />
        <div className="flex flex-wrap items-center gap-2 rounded-control bg-surface-2 p-1.5 pl-3 text-[13px]">
          <span className="text-ink-2">새로 점검</span>
          <select aria-label="조회 유형마다 질의 환자 수" value={perType} onChange={(e) => setPerType(Number(e.target.value))} className="h-[30px] rounded-cell border border-line-input bg-surface px-2 text-xs">
            {[2, 5, 10].map((n) => (
              <option key={n} value={n}>
                유형마다 {n}명
              </option>
            ))}
          </select>
          <select aria-label="퍼저" value={fuzzer} onChange={(e) => setFuzzer(e.target.value)} className="h-[30px] rounded-cell border border-line-input bg-surface px-2 text-xs">
            <option value="feedback">k 피드백 퍼저</option>
            <option value="uniform">균등 퍼저</option>
          </select>
          <button type="button" onClick={start} disabled={!!running} className="btn-primary btn-sm">
            <Play className="h-3.5 w-3.5" aria-hidden />
            다시 점검
          </button>
        </div>
      </div>
      {job && (
        <div className="mb-4 flex flex-wrap items-center gap-3 rounded-control border border-line bg-surface px-4 py-3 text-[13px]">
          <StatusChip tone={job.status === 'error' ? 'danger' : job.status === 'done' ? 'safe' : 'brand'}>
            {job.status === 'done' ? '점검 끝남' : job.status === 'error' ? '점검 실패' : '점검 중'}
          </StatusChip>
          <span className="num text-ink-2">
            {job.done.toLocaleString()} / {job.total.toLocaleString()} 대화
            {job.elapsed != null && `, ${job.elapsed}초`}
          </span>
          <div className="h-2 min-w-[160px] flex-1 overflow-hidden rounded-full bg-surface-2">
            <div className="h-full rounded-full bg-iris transition-[width] duration-300" style={{ width: `${job.total ? (job.done / job.total) * 100 : 0}%` }} />
          </div>
          {job.error && <span className="w-full text-xs text-danger-text">{job.error.split('\n')[0]}</span>}
        </div>
      )}
      {res ? <ResultView res={res} title={title} /> : <ErrorState message="이 결과가 없습니다." />}
    </div>
  );
}
