import { ExternalLink, Play, Square } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { MONITOR_UNAVAILABLE, monitorApi, type PocSummary } from '../api/monitorApi';
import { ErrorState, LoadingState } from '../components/common/StatusViews';
import { useBackendInfo } from '../hooks/useBackendInfo';
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
      ? `누적 방어를 쓴 공격 대화 ${n}건에서는 후보가 ${kReq}명 아래로 줄어든 적이 한 번도 없었습니다.${c1.utility != null ? ` 대신 답변 유용도는 ${c1.utility.toFixed(2)}로 낮아졌습니다.` : ''}`
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
              return <BarRow key={a.key} label={a.name} value={u ?? 0} max={1} color={a.color} text={u != null ? u.toFixed(2) : '–'} />;
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
                    <td className="num border-b border-line px-3 py-2.5 text-right">{r.utility != null ? r.utility.toFixed(2) : '–'}</td>
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

const SCALES: { value: number | null; trials: number; label: string }[] = [
  { value: 1, trials: 3, label: '유형마다 1명 (질의 환자 3명)' },
  { value: 2, trials: 6, label: '유형마다 2명 (6명)' },
  { value: 5, trials: 15, label: '유형마다 5명 (15명)' },
  { value: 10, trials: 30, label: '유형마다 10명 (30명)' },
  { value: null, trials: 296, label: '전체 (296명)' },
];
/** 어림값: 질의 환자 한 명 × 갈래 3개 × 최대 10턴 × 턴마다 6번(공격 질문 · 확인 · 대상 AI · 추출 · 재작성 · 다시 확인). 형식 오류 다시 시도는 따로 */
const MAX_CALLS_PER_TRIAL = 3 * 10 * 6;

const STATUS_KO: Record<RedTeamJob['status'], string> = {
  queued: '준비 중',
  running: '점검 중',
  done: '점검 끝남',
  error: '점검 실패',
  cancelled: '멈춤',
  interrupted: '끊김',
};

function dur(sec: number | null | undefined): string {
  if (sec == null) return '–';
  const s = Math.round(sec);
  if (s < 60) return `${s}초`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}분 ${s % 60}초`;
  return `${Math.floor(m / 60)}시간 ${m % 60}분`;
}

/** 실제 LLM 실행의 대상 AI 답 형식: 다른 설정끼리는 결과를 바로 비교하지 않는다 */
function styleText(j: RedTeamJob): string {
  return j.answer_style === 'on' ? '짧은 답 지시' : '답 형식 지시 없음';
}

const TRIGGER_KO: Record<string, string> = { change: '자동 · 설정 바뀜', daily: '자동 · 정기' };
const TRIGGER_CARD: Record<string, string> = { change: '설정이 바뀌어 자동으로 시작한 점검', daily: '정해진 시각에 자동으로 시작한 점검' };
const LEVEL_TONE = { warn: 'danger', caution: 'caution', ok: 'safe', none: 'plain' } as const;

function jobTitle(j: RedTeamJob): string {
  const auto = j.trigger && TRIGGER_KO[j.trigger] ? `${TRIGGER_KO[j.trigger]} · ` : '';
  const who = `${auto}${j.live ? `${j.model ?? '실제 LLM'} · ${styleText(j)}` : `결정적 응답기 (${j.profile_label})`}`;
  const n = j.trials ?? Math.round(j.total / 3);
  const when = j.started_at ? new Date(j.started_at * 1000).toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '';
  const kept = j.kept ?? j.done;
  const part = j.status === 'done' ? '' : ` · ${STATUS_KO[j.status]}, 대화 ${kept}/${j.total}까지 집계`;
  return `${j.id} ${who}, ${j.fuzzer_label}, 질의 환자 ${n}명 ${when}${part}`;
}

/** 끝난 실제 LLM 점검: 같은 규모로 바로 앞에 끝난 점검과 누적 방어 지표 비교 (autocheck.py) */
function CompareCard({ job }: { job: RedTeamJob }) {
  const c = job.compare!;
  return (
    <section aria-label="직전 점검과 비교" className="panel mb-4 px-5 py-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-[15px] font-bold">{c.baseline ? `직전 점검 ${c.baseline.id}과 비교` : '직전 점검과 비교'}</h2>
        <StatusChip tone={LEVEL_TONE[c.level]}>{c.levelLabel}</StatusChip>
        {job.trigger && TRIGGER_CARD[job.trigger] && <span className="text-xs text-ink-3">{TRIGGER_CARD[job.trigger]}</span>}
      </div>
      <p className="mt-1.5 max-w-[62ch] text-[13px] leading-6 text-ink">{c.text}</p>
      {c.rows.length > 0 && (
        <table className="mt-2 w-full max-w-[640px] border-collapse text-[13px]">
          <thead>
            <tr className="text-left text-xs text-ink-3">
              <th scope="col" className="border-b border-line py-1.5 pr-3 font-semibold">
                누적 방어 지표
              </th>
              <th scope="col" className="border-b border-line px-3 py-1.5 text-right font-semibold">
                직전 점검
              </th>
              <th scope="col" className="border-b border-line py-1.5 pl-3 text-right font-semibold">
                이번 점검
              </th>
            </tr>
          </thead>
          <tbody>
            {c.rows.map((r) => (
              <tr key={r.key}>
                <th scope="row" className="border-b border-line py-1.5 pr-3 text-left font-normal text-ink-2">
                  {r.label}
                </th>
                <td className="num border-b border-line px-3 py-1.5 text-right text-ink-2">{r.before}</td>
                <td className={`num border-b border-line py-1.5 pl-3 text-right ${r.worse ? 'font-semibold text-danger-text' : 'text-ink'}`}>{r.after}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {c.changes.length > 0 && <p className="mt-2 text-xs text-ink-2">바뀐 설정: {c.changes.join(' · ')}</p>}
      <p className="mt-1.5 text-xs text-ink-3">{c.note}</p>
    </section>
  );
}

export function ReportPage() {
  const toast = useToast();
  // 평가 지표 대시보드(eval_demo/)는 연구 재현용 정적 페이지다. 운영 서버 화면에서는 링크를 두지 않는다
  const backend = useBackendInfo();
  const researchLinks = !!backend && backend.kind !== 'medicloak';
  const [poc, setPoc] = useState<PocSummary | null>(null);
  const [jobs, setJobs] = useState<RedTeamJob[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState<boolean | null>(null);
  const [dataset, setDataset] = useState<string | null>(null);
  const [perType, setPerType] = useState<number | null>(1);
  const [fuzzer, setFuzzer] = useState('feedback');
  const [confirming, setConfirming] = useState(false);
  const [job, setJob] = useState<RedTeamJob | null>(null);
  const [results, setResults] = useState<Record<string, RedTeamJob>>({});

  useEffect(() => {
    const ctl = new AbortController();
    monitorApi.poc(ctl.signal).then(setPoc, (e) => {
      if (!(e instanceof DOMException)) setPoc({} as PocSummary);
    });
    monitorApi.jobs(ctl.signal).then(
      (js) => {
        setJobs(js);
        const running = js.find((j) => j.status === 'running' || j.status === 'queued');
        if (running) setJob(running);
      },
      (e) => {
        if (!(e instanceof DOMException)) setError(e instanceof Error ? e.message : MONITOR_UNAVAILABLE);
      },
    );
    monitorApi.policy(ctl.signal).then((p) => setLive(p.llmLive), () => setLive(false));
    return () => ctl.abort();
  }, []);

  // 돌고 있는 점검: 2초마다 진행을 받는다
  useEffect(() => {
    if (!job || (job.status !== 'running' && job.status !== 'queued')) return;
    const t = setTimeout(() => {
      monitorApi.job(job.id).then(
        (j) => {
          setJob(j);
          if (j.status !== 'running' && j.status !== 'queued') {
            setJobs((js) => [j, ...(js ?? []).filter((x) => x.id !== j.id)]);
            if (j.result) {
              setResults((r) => ({ ...r, [j.id]: j }));
              setDataset(`job:${j.id}`);
            }
            toast(j.status === 'done' ? '레드팀 점검을 마쳤습니다.' : j.status === 'cancelled' ? '점검을 멈췄습니다. 끝낸 대화까지 집계했습니다.' : '점검이 끝나지 못했습니다.');
          }
        },
        () => undefined,
      );
    }, 2000);
    return () => clearTimeout(t);
  }, [job, toast]);

  const finished = useMemo(() => (jobs ?? []).filter((j) => j.status !== 'running' && j.status !== 'queued' && (j.kept ?? j.done) > 0), [jobs]);
  const pocKeys = useMemo(() => Object.keys(DATASETS).filter((k) => poc?.[k]), [poc]);

  // 처음 고를 결과: 가장 최근의 실제 LLM 점검, 없으면 POC
  useEffect(() => {
    if (dataset || jobs == null || poc == null) return;
    const latest = finished.find((j) => j.live) ?? finished[0];
    setDataset(latest ? `job:${latest.id}` : (pocKeys.includes('staged_feedback') ? 'staged_feedback' : pocKeys[0] ?? null));
  }, [dataset, jobs, poc, finished, pocKeys]);

  // 고른 점검의 결과 받기 (목록에는 결과가 빠져 온다)
  const pickedJob = dataset?.startsWith('job:') ? dataset.slice(4) : null;
  useEffect(() => {
    if (!pickedJob || results[pickedJob]) return;
    const ctl = new AbortController();
    monitorApi.job(pickedJob, ctl.signal).then((j) => setResults((r) => ({ ...r, [j.id]: j })), () => undefined);
    return () => ctl.abort();
  }, [pickedJob, results]);

  const running = !!job && (job.status === 'running' || job.status === 'queued');
  const scale = SCALES.find((s) => s.value === perType) ?? SCALES[0];

  async function start() {
    setConfirming(false);
    try {
      const j = await monitorApi.startRedTeam(perType, fuzzer, live ? 'live' : 'oracle');
      setJob(j);
      setJobs((js) => [j, ...(js ?? [])]);
      toast(j.live ? '실제 LLM으로 레드팀 점검을 시작했습니다.' : '레드팀 점검을 시작했습니다.');
    } catch (e) {
      toast(e instanceof Error ? e.message : '점검을 시작하지 못했습니다.');
    }
  }

  async function cancel() {
    if (!job) return;
    try {
      setJob(await monitorApi.cancelRedTeam(job.id));
      toast('멈추는 중입니다. 돌던 질의 환자는 빼고, 세 갈래를 다 끝낸 질의 환자까지 집계합니다.');
    } catch (e) {
      toast(e instanceof Error ? e.message : '멈추지 못했습니다.');
    }
  }

  if (error)
    return (
      <div className="mx-auto max-w-xl p-6">
        <ErrorState message={error} />
      </div>
    );
  if (!poc || jobs == null) return <LoadingState label="점검 결과를 불러오는 중" />;

  const shownJob = pickedJob ? results[pickedJob] : null;
  const res = pickedJob ? shownJob?.result ?? null : dataset ? poc[dataset] : null;
  const title = pickedJob
    ? shownJob
      ? jobTitle(shownJob)
      : '점검 결과를 불러오는 중'
    : `기준 평가 · 결정적 응답기 2026-10-23 (${dataset ? DATASETS[dataset] : ''})`;

  return (
    <div className="scroll-thin h-full overflow-y-auto px-4 pb-6 pt-4 md:px-6">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <label className="text-[13px] text-ink-3" htmlFor="dataset">
          결과
        </label>
        <select
          id="dataset"
          value={dataset ?? ''}
          onChange={(e) => setDataset(e.target.value)}
          className="h-9 max-w-full rounded-control border border-line-input bg-surface px-3 text-[13px]"
        >
          {finished.length > 0 && (
            <optgroup label="레드팀 점검">
              {finished.map((j) => (
                <option key={j.id} value={`job:${j.id}`}>
                  {jobTitle(j)}
                </option>
              ))}
            </optgroup>
          )}
          {pocKeys.length > 0 && (
            <optgroup label="참고: 기준 평가 (결정적 응답기 · 2026-10-23)">
              {pocKeys.map((k) => (
                <option key={k} value={k}>
                  기준 평가 {DATASETS[k]}
                </option>
              ))}
            </optgroup>
          )}
        </select>
        {researchLinks && (
          <a href="/eval/" target="_blank" rel="noreferrer" className="btn-ghost btn-sm" title="평가 지표 대시보드 (eval_demo/)">
            <ExternalLink className="h-3.5 w-3.5" aria-hidden />
            평가 지표 22개
          </a>
        )}
        <span className="flex-1" />
        <div className="flex flex-wrap items-center gap-2 rounded-control bg-surface-2 p-1.5 pl-3 text-[13px]">
          <span className="text-ink-2">{live ? '실제 LLM으로 새 점검' : '새 점검 (결정적 응답기)'}</span>
          <select
            aria-label="질의 환자 수"
            value={perType ?? 'all'}
            onChange={(e) => setPerType(e.target.value === 'all' ? null : Number(e.target.value))}
            className="h-[30px] rounded-cell border border-line-input bg-surface px-2 text-xs"
          >
            {SCALES.map((s) => (
              <option key={s.label} value={s.value ?? 'all'}>
                {s.label}
              </option>
            ))}
          </select>
          <select aria-label="퍼저" value={fuzzer} onChange={(e) => setFuzzer(e.target.value)} className="h-[30px] rounded-cell border border-line-input bg-surface px-2 text-xs">
            <option value="feedback">k 피드백 퍼저</option>
            <option value="uniform">균등 퍼저</option>
          </select>
          <button type="button" onClick={() => (live ? setConfirming(true) : void start())} disabled={running || live == null} className="btn-primary btn-sm">
            <Play className="h-3.5 w-3.5" aria-hidden />
            점검 시작
          </button>
        </div>
      </div>
      {confirming && (
        <div role="alertdialog" aria-label="실제 LLM 점검 확인" className="mb-4 rounded-control border border-caution bg-caution-tint px-4 py-3 text-[13px] text-ink">
          <p>
            실제 LLM으로 질의 환자 <b className="num">{scale.trials}명</b> × 갈래 3개(누적 방어 · 턴별 방어 · 방어 없음)를 최대 10턴씩 돌립니다. LLM 호출은 턴마다 6번으로 잡으면{' '}
            <b className="num">약 {(scale.trials * MAX_CALLS_PER_TRIAL).toLocaleString()}번</b>입니다. 위험에 닿은 대화는 일찍 끝나 줄고, 형식 오류로 다시 부르면 늘어납니다.
          </p>
          <p className="mt-1 text-xs text-ink-2">의료진 질문이 들어오면 그 호출을 먼저 보냅니다. 중간에 멈춰도 끝낸 질의 환자까지는 집계해 리포트에 남깁니다.</p>
          <div className="mt-2 flex gap-1.5">
            <button type="button" className="btn-primary btn-sm" onClick={() => void start()}>
              시작
            </button>
            <button type="button" className="btn-ghost btn-sm" onClick={() => setConfirming(false)}>
              취소
            </button>
          </div>
        </div>
      )}
      {job && (running || job.id === pickedJob || !finished.some((j) => j.id === job.id)) && (
        <div className="mb-4 rounded-control border border-line bg-surface px-4 py-3 text-[13px]">
          <div className="flex flex-wrap items-center gap-3">
            <StatusChip tone={job.status === 'error' || job.status === 'interrupted' ? 'danger' : job.status === 'done' ? 'safe' : job.status === 'cancelled' ? 'plain' : 'brand'}>
              {STATUS_KO[job.status]}
            </StatusChip>
            <span className="font-mono text-xs text-ink-3">{job.id}</span>
            <span className="text-ink-2">{job.live ? `${job.model ?? '실제 LLM'} · ${styleText(job)}` : '결정적 응답기'}</span>
            <span className="flex-1" />
            {running && job.status === 'running' && (
              <button type="button" className="btn-ghost btn-sm" onClick={() => void cancel()}>
                <Square className="h-3.5 w-3.5" aria-hidden />
                멈추기
              </button>
            )}
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-2" role="progressbar" aria-valuemin={0} aria-valuemax={job.total} aria-valuenow={job.done}>
            <div className="h-full rounded-full bg-iris transition-[width] duration-300" style={{ width: `${job.total ? (job.done / job.total) * 100 : 0}%` }} />
          </div>
          <dl className="num mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-xs sm:grid-cols-4">
            <div>
              <dt className="text-ink-3">끝낸 대화</dt>
              <dd className="font-semibold text-ink">
                {job.done.toLocaleString()} / {job.total.toLocaleString()}
              </dd>
            </div>
            <div>
              <dt className="text-ink-3">LLM 호출</dt>
              <dd className="font-semibold text-ink">{job.live ? `${(job.usage?.calls ?? 0).toLocaleString()}번` : '없음'}</dd>
            </div>
            <div>
              <dt className="text-ink-3">토큰 (입력 / 출력)</dt>
              <dd className="font-semibold text-ink">
                {job.live ? `${(job.usage?.input_tokens ?? 0).toLocaleString()} / ${(job.usage?.output_tokens ?? 0).toLocaleString()}` : '–'}
              </dd>
            </div>
            <div>
              <dt className="text-ink-3">걸린 시간{running && job.eta != null ? ' · 남은 시간' : ''}</dt>
              <dd className="font-semibold text-ink">
                {dur(job.elapsed)}
                {running && job.eta != null && <span className="font-normal text-ink-2"> · 약 {dur(job.eta)}</span>}
              </dd>
            </div>
          </dl>
          {!!job.llm_error_trials && (
            <p className="mt-1.5 text-xs text-caution-text">LLM 호출이 실패한 질의 환자 {job.llm_error_trials}명은 집계에서 뺐습니다 (세 갈래 짝을 맞추려고).</p>
          )}
          {job.last && <p className="mt-1.5 truncate text-xs text-ink-3">마지막: {job.last}</p>}
          {job.error && <p className="mt-1.5 text-xs text-danger-text">{job.error.split('\n')[0]}</p>}
        </div>
      )}
      {shownJob?.compare && <CompareCard job={shownJob} />}
      {res ? (
        <ResultView res={res} title={title} />
      ) : pickedJob && !shownJob ? (
        <LoadingState label="점검 결과를 불러오는 중" />
      ) : (
        <ErrorState message={pickedJob ? '이 점검에는 집계할 대화가 없습니다.' : '아직 점검 결과가 없습니다. 위에서 점검을 시작하세요.'} />
      )}
    </div>
  );
}
