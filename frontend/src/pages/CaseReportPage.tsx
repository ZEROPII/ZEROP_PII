import { Download, FileText, Lock, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { apiMode } from '../api';
import { reportApi } from '../api/reportApi';
import { ApiError, isNoConversation } from '../api/types';
import { Explained } from '../components/clinic/ClinicValue';
import { RunningChevrons } from '../components/common/StageTrack';
import { ErrorState, LoadingState } from '../components/common/StatusViews';
import { useToast } from '../components/layout/Toast';
import { KIND_CHIP } from '../lib/kindStyle';
import { josa } from '../lib/korean';
import { useWorkspace } from '../state/WorkspaceContext';
import type { CaseReport, ReportCase, ReportValue } from '../types/domain';

const KEEP = '과거 사례 기록은 바뀌지 않습니다. 꼭 필요하면 대화에서 그 사례에 물은 뒤 세부 정보 요청을 보내세요.';
const ABOUT = [
  '값은 이 대화의 답과 같은 기준으로 MediCloak이 판정합니다. 환자를 알아볼 수 있는 값은 비공개로, 너무 자세한 값은 범위로 적습니다.',
  '보고서에 담은 값도 이 대화에서 공개한 것으로 셉니다. 보고서를 만든 뒤의 답에서는 같은 사례의 값이 더 가려질 수 있습니다.',
  '경과는 기록에 남은 날짜로 센 범위입니다. 치료 효과를 입증하지 않습니다.',
];

function when(sec: number): string {
  const d = new Date(sec * 1000);
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** 값 하나: 그대로는 글, 범위는 글 + '범위' 표시, 비공개는 잠금 표시. 표시를 누르면 까닭이 뜬다 */
function Value({ v, name, why }: { v: ReportValue | null | undefined; name: string; why: Record<string, string> }) {
  if (!v) return <span className="text-ink-3">–</span>;
  const reason = v.why ? why[v.why] : null;
  if (v.action === 'suppress')
    return (
      <Explained
        className="lock-token"
        title={`${name} 비공개`}
        lines={[`MediCloak이 보고서에서 이 ${josa(name, '을', '를')} 가렸습니다.`, ...(reason ? [reason] : []), KEEP]}
        trigger={
          <>
            <Lock className="h-3 w-3 shrink-0" strokeWidth={2.4} aria-hidden />
            <span className="lock-bar" aria-hidden />
            비공개
            <span className="sr-only"> (눌러서 까닭 보기)</span>
          </>
        }
      />
    );
  if (v.action === 'generalize')
    return (
      <span>
        {v.text}
        <Explained
          className="range-tag"
          title={`${name} · 범위로 적음`}
          lines={[`MediCloak이 정확한 ${name} 대신 넓은 범위로 적었습니다.`, ...(reason ? [reason] : []), KEEP]}
          trigger={
            <>
              범위<span className="sr-only"> (눌러서 까닭 보기)</span>
            </>
          }
        />
      </span>
    );
  return <span>{v.text}</span>;
}

/** 표 한 줄: 구분(기록 종류 색) · 이름 · 기록상 경과. 좁은 화면에서는 경과가 이름 아래로 간다 */
function Row({ chip, label, children, course }: { chip: string; label: string; children: ReactNode; course: ReactNode }) {
  return (
    <li className="grid grid-cols-[64px_minmax(0,1fr)] gap-x-3 gap-y-0.5 px-5 py-2.5 sm:grid-cols-[72px_minmax(0,1.1fr)_minmax(0,1fr)]">
      <span>
        <span className={`kind-chip ${chip}`}>{label}</span>
      </span>
      <span className="min-w-0 break-words text-[13px] text-ink">{children}</span>
      <span className="col-start-2 min-w-0 text-[12.5px] leading-5 text-ink-2 sm:col-start-auto">{course}</span>
    </li>
  );
}

function CaseCard({ c, why }: { c: ReportCase; why: Record<string, string> }) {
  const m = c.main;
  const hasCourse = !!m && (!!m.start || m.course.length > 0);
  return (
    <article className="panel overflow-hidden" aria-labelledby={`${c.caseId}-title`}>
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-line px-5 py-3">
        <h2 id={`${c.caseId}-title`} className="text-[15px] font-bold text-ink">
          {c.label}
        </h2>
        <span className="text-[12.5px] text-ink-2">
          성별 <Value v={c.profile.sex} name="성별" why={why} /> · 주진단 당시 나이 <Value v={c.profile.age} name="나이" why={why} />
        </span>
        {(c.hidden > 0 || c.ranged > 0) && (
          <span className="ml-auto text-[11.5px] text-ink-3">{[c.hidden ? `비공개 ${c.hidden}` : '', c.ranged ? `범위 ${c.ranged}` : ''].filter(Boolean).join(' · ')}</span>
        )}
      </header>
      {!m && c.treatments.length === 0 ? (
        <p className="px-5 py-3 text-[13px] text-ink-3">판정할 기록이 없습니다.</p>
      ) : (
        <>
          <div aria-hidden className="hidden grid-cols-[72px_minmax(0,1.1fr)_minmax(0,1fr)] gap-x-3 border-b border-line px-5 py-1.5 text-[11px] font-semibold text-ink-3 sm:grid">
            <span>구분</span>
            <span>이름</span>
            <span>기록상 경과</span>
          </div>
          <ul className="divide-y divide-line">
            {m && (
              <Row
                chip={KIND_CHIP.problems}
                label="주진단"
                course={
                  hasCourse && m ? (
                    <>
                      {m.start && (
                        <>
                          시작 <Value v={m.start} name="진단 시작 시기" why={why} />
                          {m.course.length > 0 && ' · '}
                        </>
                      )}
                      {m.course.join(' · ')}
                    </>
                  ) : (
                    '–'
                  )
                }
              >
                <span className="font-semibold">
                  <Value v={m.value} name="주진단" why={why} />
                </span>
              </Row>
            )}
            {c.treatments.map((t, i) => (
              <Row key={`${t.kind}:${i}`} chip={KIND_CHIP[t.kind]} label={t.kindLabel} course={t.course.length ? t.course.join(' · ') : '–'}>
                <Value v={t.name} name={t.kindLabel === '처방' ? '처방 약' : t.kindLabel} why={why} />
              </Row>
            ))}
            {m && c.treatments.length === 0 && m.value.text && <li className="px-5 py-2.5 text-[12.5px] text-ink-3">주진단 무렵 시작한 처방 · 시술 · 관리 계획 기록이 없습니다.</li>}
          </ul>
        </>
      )}
      <footer className="space-y-2 border-t border-line bg-surface-2 px-5 py-3">
        {c.others.length > 0 && (
          <p className="text-[12.5px] leading-6 text-ink-2">
            <span className="mr-1.5 font-semibold text-ink">동반 진단</span>
            {c.others.map((v, i) => (
              <span key={i}>
                {i > 0 && <span className="text-ink-3">, </span>}
                <Value v={v} name="동반 진단" why={why} />
              </span>
            ))}
          </p>
        )}
        <p className="text-[13px] font-medium leading-6 text-ink">{c.summary}</p>
      </footer>
    </article>
  );
}

function Count({ n, label, tone }: { n: number; label: string; tone: string }) {
  return (
    <span className={`inline-flex items-baseline gap-1.5 rounded-[8px] px-2.5 py-1 text-[12px] font-semibold ${tone}`}>
      {label}
      <span className="num text-[14px] font-bold">{n}</span>
    </span>
  );
}

/**
 * 유사 사례 보고서 (ADR-0042): 지금 대화의 과거 사례마다 주진단 · 그 무렵 시작한 처방 · 시술 · 관리 계획 · 기록상 경과.
 * 값은 답과 같은 판정을 거쳐 비공개 · 범위가 그대로 보이고, PDF로도 같은 모습으로 받는다. 만드는 것은 공개라 버튼으로만 만든다.
 */
export function CaseReportPage() {
  const toast = useToast();
  const { state, actions } = useWorkspace();
  const [report, setReport] = useState<CaseReport | null>(null);
  const [status, setStatus] = useState<'loading' | 'none' | 'ready' | 'error'>('loading');
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [making, setMaking] = useState(false);
  const http = apiMode === 'http';
  const contextId = state.patient.data?.contextId;

  const load = useCallback((signal?: AbortSignal) => {
    setStatus('loading');
    reportApi.get(signal).then(
      (r) => {
        setReport(r);
        setStatus('ready');
      },
      (e) => {
        if (e instanceof DOMException) return;
        if (e instanceof ApiError && e.status === 404) {
          setReport(null);
          setStatus('none');
          return;
        }
        setError(e instanceof Error ? e : new Error(String(e)));
        setStatus('error');
      },
    );
  }, []);

  useEffect(() => {
    if (!http) return;
    const ctl = new AbortController();
    load(ctl.signal);
    return () => ctl.abort();
  }, [http, load, contextId]);

  async function make() {
    setMaking(true);
    try {
      const r = await reportApi.create();
      setReport(r);
      setStatus('ready');
      toast(report ? '보고서를 다시 만들었습니다. 지금까지의 답까지 합쳐 판정했습니다.' : '보고서를 만들었습니다. 담은 값은 이 대화에서 공개한 것으로 셉니다.');
      void actions.refreshLive();
    } catch (e) {
      if (isNoConversation(e)) {
        setError(e as ApiError);
        setStatus('error');
      } else toast(e instanceof Error ? e.message : '보고서를 만들지 못했습니다.');
    } finally {
      setMaking(false);
    }
  }

  const noConversation = status === 'error' && isNoConversation(error);
  const p = report?.patient;
  return (
    <div className="scroll-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-[920px] space-y-3 p-4 md:p-6">
        <section className="panel overflow-hidden">
          <header className="flex flex-col gap-3 border-b border-line px-5 py-4 sm:flex-row sm:items-center">
            <div className="min-w-0 flex-1">
              <h1 className="flex items-center gap-2 text-[17px] font-bold text-ink">
                <FileText className="h-[18px] w-[18px] text-iris-text" aria-hidden />
                유사 사례 보고서
              </h1>
              {report && p && (
                <p className="mt-1 text-[12.5px] leading-5 text-ink-2">
                  {[report.regno ? `등록번호 ${report.regno}` : null, p.ageSex, `주진단 ${p.primaryDiagnosis}`, report.purpose, p.visitDate ? `${p.visitDate} 진료 기준` : null]
                    .filter(Boolean)
                    .join(' · ')}
                  <br />
                  <span className="text-ink-3">
                    {when(report.createdAt)}
                    {report.createdBy ? ` · ${report.createdBy} 선생님이 만듦` : ''}
                  </span>
                </p>
              )}
            </div>
            {status === 'ready' && report && (
              <div className="flex shrink-0 gap-2">
                <button type="button" className="btn-ghost btn-sm h-9 gap-1.5 border border-line bg-surface text-ink-2" onClick={() => void make()} disabled={making}>
                  {making ? <RunningChevrons /> : <RefreshCw className="h-3.5 w-3.5" aria-hidden />}
                  {making ? '만드는 중' : '다시 만들기'}
                </button>
                <a className="btn-primary btn-sm h-9 gap-1.5" href={reportApi.pdfUrl} download={report.pdfName ?? 'MediCloak-유사사례보고서.pdf'}>
                  <Download className="h-3.5 w-3.5" aria-hidden />
                  PDF로 받기
                </a>
              </div>
            )}
          </header>
          {!http ? (
            <p className="px-5 py-5 text-[13px] leading-6 text-ink-2">보고서는 MediCloak 서버(python -m medicloak)에 연결했을 때 만들 수 있습니다.</p>
          ) : status === 'loading' ? (
            <LoadingState compact label="보고서를 불러오는 중" />
          ) : noConversation ? (
            <div className="px-5 py-5 text-[13px] leading-6 text-ink-2">
              <p>열린 진료 지원 AI 대화가 없습니다. 내 담당 환자에서 환자를 열어 유사 사례를 찾은 뒤 보고서를 만드세요.</p>
              <Link to="/emr" className="btn-primary btn-sm mt-3 inline-flex h-9">
                내 담당 환자로
              </Link>
            </div>
          ) : status === 'error' ? (
            <ErrorState message={error?.message ?? '보고서를 불러오지 못했습니다.'} onRetry={() => load()} />
          ) : status === 'none' ? (
            <div className="px-5 py-5">
              <p className="text-[13.5px] leading-6 text-ink">
                지금 대화에서 찾은 비슷한 사례마다 주진단, 그 무렵 시작한 처방 · 시술 · 관리 계획, 기록상 경과를 한 문서로 모읍니다. 만든 보고서는 PDF로 받을 수 있습니다.
              </p>
              <ul className="mt-3 space-y-1.5 text-[12.5px] leading-5 text-ink-2">
                {ABOUT.map((t) => (
                  <li key={t} className="flex gap-2">
                    <span aria-hidden className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-ink-3" />
                    {t}
                  </li>
                ))}
              </ul>
              <button type="button" className="btn-primary mt-4 h-10 gap-2 px-4" onClick={() => void make()} disabled={making}>
                {making ? <RunningChevrons /> : <FileText className="h-4 w-4" aria-hidden />}
                {making ? '보고서를 만드는 중' : '보고서 만들기'}
              </button>
            </div>
          ) : (
            report && (
              <div className="px-5 py-3.5">
                <div className="flex flex-wrap gap-2" aria-label="보고서 값 판정">
                  <Count n={report.counts.allow} label="그대로" tone="bg-safe-tint text-safe-text" />
                  <Count n={report.counts.generalize} label="범위로 적음" tone="bg-iris-tint text-iris-text" />
                  <Count n={report.counts.suppress} label="비공개" tone="bg-emr-lock-tint text-emr-lock" />
                </div>
                <ul className="mt-3 space-y-1 text-[12.5px] leading-5 text-ink-2">
                  {report.notes.map((t) => (
                    <li key={t} className="flex gap-2">
                      <span aria-hidden className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-ink-3" />
                      {t}
                    </li>
                  ))}
                </ul>
              </div>
            )
          )}
        </section>
        {status === 'ready' && report && report.cases.map((c) => <CaseCard key={c.caseId} c={c} why={report.whyLabels} />)}
      </div>
    </div>
  );
}
