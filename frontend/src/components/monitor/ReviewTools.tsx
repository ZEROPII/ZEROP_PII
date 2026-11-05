// 관제 상세의 후보 수 계기와 검토 반영 도구 (규칙 · 공개 승인).
//   규칙   : 이 대화에서 고른 사례 · 단서 종류는 다음 질문부터 늘 가린다 (의료진 화면 갈래에만, 감사 기록).
//   승인   : 의료진의 세부 정보 요청에 사유를 적고 가린 값을 골라 그 의료진의 그 대화에만 공개한다.
//            공개한 값은 누적 State에 더해져 이후 판정에 들어간다 (후보가 기준 아래로 내려갈 수 있다).

import { Eye, Loader2, Plus, ShieldCheck, Trash2, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { monitorApi } from '../../api/monitorApi';
import { josa } from '../../lib/korean';
import { caseLabel, clockTime } from '../../lib/time';
import type { HiddenItem, MonitorDetail, Narrowing } from '../../types/monitor';
import { useToast } from '../layout/Toast';
import { ArmCompare, NarrowingLadder } from '../viz/Instruments';

// 관제 화면의 단서 이름 (SessionDetail · 서버 engine.ATTR_KO와 같은 말)
const ATTRS: [string, string][] = [
  ['PERIOD', '시점 (날짜)'],
  ['AGE', '나이'],
  ['SEX', '성별'],
  ['REGION', '거주지'],
  ['DX', '진단'],
  ['PROC', '시술'],
  ['MED', '약'],
  ['PLAN', '관리 계획'],
];
const ATTR_LABEL: Record<string, string> = Object.fromEntries(ATTRS.map(([k, v]) => [k, v.replace(/ \(.+\)$/, '')]));
const labelOf = (a: string, fallback: string) => ATTR_LABEL[a] ?? fallback;

function caseIdOf(ref: string | null | undefined): string | null {
  const m = /^사례(\d+)$/.exec(ref ?? '');
  return m ? `case-${m[1]}` : null;
}

function lastK(series: [number, number][] | undefined): number | null {
  return series && series.length ? series[series.length - 1][1] : null;
}

function where(turn: number): string {
  return turn === 0 ? '사례 검색 답' : `질문 ${turn}의 답`;
}

/** 대화 끝 후보 수(세 갈래)와 초점 사례에서 후보가 줄어든 과정 */
export function CountsSection({ d, onReveal }: { d: MonitorDetail; onReveal(): void }) {
  const r = d.row;
  const focus = r.focus_case;
  const cid = caseIdOf(focus);
  const [nar, setNar] = useState<Narrowing | null>(null);
  const [narError, setNarError] = useState<string | null>(null);
  const key = `${d.id}|${focus}|${d.turn}|${(d.approvals ?? []).length}|${(d.rules ?? []).length}`;

  useEffect(() => {
    setNar(null);
    setNarError(null);
    if (!cid || d.source !== 'clinic') return;
    const ctl = new AbortController();
    monitorApi.narrowing(d.id, cid, ctl.signal).then(setNar, (e) => {
      if (!(e instanceof DOMException)) setNarError(e instanceof Error ? e.message : '불러오지 못했습니다.');
    });
    return () => ctl.abort();
  }, [key, cid, d.id, d.source]);

  const g = d.k_req;
  const s = nar?.suppressK ?? 3;
  const max = d.p_ref;
  const rows = [
    { key: 'C1', label: '의료진 화면', note: '누적 방어', k: focus ? lastK(d.arms.C1?.k_series[focus]) : null },
    { key: 'C1S', label: '턴별 방어였다면', note: '비교', k: focus ? lastK(d.arms.C1S?.k_series[focus]) : null },
    { key: 'C0', label: '방어 없었다면', note: '비교', k: focus ? lastK(d.arms.C0?.k_series[focus]) : null },
  ];
  const patient = d.retrieval.find((x) => x.ref === focus)?.patient;

  return (
    <section aria-label="후보 수" className="border-b border-line px-5 py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="text-[13px] font-bold text-ink-2">
          {josa(caseLabel(focus), '과', '와')} 조건이 같은 과거 환자 <span className="num text-ink">{r.k_now != null ? `${r.k_now.toLocaleString()}명` : '–'}</span>
        </h3>
        <span className="flex items-center gap-2 text-xs text-ink-3">
          환자 번호
          {d.revealed ? (
            <span className="font-mono text-ink">{patient ?? '–'}</span>
          ) : (
            <>
              <span className="redact" style={{ width: 72 }} aria-label="가려진 환자 번호" />
              <button type="button" onClick={onReveal} className="btn-ghost btn-sm h-6 px-1.5">
                <Eye className="h-3.5 w-3.5" aria-hidden />
                사유 적고 보기
              </button>
            </>
          )}
        </span>
      </div>
      <p className="mt-1 max-w-[62ch] text-xs leading-5 text-ink-3">
        {josa(caseLabel(focus), '은', '는')} 과거 기록 환자 한 명입니다. 지금까지 답에 나온 이 사람의 단서를 모두 가진 사람이 {max.toLocaleString()}명 중 몇 명인지
        셉니다. {g}명 아래로 줄면 누구인지 좁혀지고, 1명이면 특정됩니다.
      </p>
      <div className="mt-2.5">
        <ArmCompare rows={rows} max={max} g={g} s={s} />
      </div>
      {d.source === 'clinic' && (
        <div className="mt-4">
          <h4 className="mb-1 text-xs font-semibold text-ink-2">{caseLabel(focus)} 후보가 줄어든 과정</h4>
          {nar ? <NarrowingLadder data={nar} labelOf={labelOf} /> : <p className="text-xs text-ink-3">{narError ?? '불러오는 중'}</p>}
        </div>
      )}
    </section>
  );
}

/** 이 대화에 건 규칙 목록과 추가 양식 */
export function RulesSection({ d, open, onOpen, onDetail }: { d: MonitorDetail; open: boolean; onOpen(v: boolean): void; onDetail(d: MonitorDetail): void }) {
  const toast = useToast();
  const rules = d.rules ?? [];
  const refs = d.retrieval.map((x) => x.ref);
  const [caseRef, setCaseRef] = useState(d.row.focus_case ?? refs[0] ?? '사례1');
  const [attr, setAttr] = useState('PERIOD');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const archived = !!d.archived || !!d.row.archived;

  useEffect(() => {
    setCaseRef(d.row.focus_case ?? refs[0] ?? '사례1');
  }, [d.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function add() {
    setBusy(true);
    try {
      onDetail(await monitorApi.addRule(d.id, caseRef, attr, note.trim()));
      toast(`규칙을 걸었습니다. 다음 질문부터 ${caseLabel(caseRef)}의 ${ATTR_LABEL[attr]}은(는) 가립니다.`);
      setNote('');
      onOpen(false);
    } catch (e) {
      toast(e instanceof Error ? e.message : '규칙을 걸지 못했습니다.');
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setBusy(true);
    try {
      onDetail(await monitorApi.removeRule(d.id, id));
      toast('규칙을 풀었습니다.');
    } catch (e) {
      toast(e instanceof Error ? e.message : '규칙을 풀지 못했습니다.');
    } finally {
      setBusy(false);
    }
  }

  if (!rules.length && !open) return null;
  return (
    <section aria-label="이 대화의 규칙" className="border-b border-line px-5 py-4">
      <h3 className="mb-2 text-[13px] font-bold text-ink-2">이 대화의 규칙</h3>
      {rules.length > 0 && (
        <ul className="mb-2 space-y-1.5">
          {rules.map((r) => (
            <li key={r.id} className="flex items-start gap-2 rounded-cell bg-surface-2 px-2.5 py-2 text-xs">
              <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-iris-text" aria-hidden />
              <span className="min-w-0 flex-1 text-ink">
                {caseLabel(r.case)}의 <b>{r.attribute_label}</b>은(는) 질문 {r.from_turn}부터 늘 가림
                <span className="block text-ink-3">
                  {r.by.split(' (')[0]} · {clockTime(r.at)}
                  {r.note ? ` · ${r.note}` : ''}
                </span>
              </span>
              {!archived && (
                <button type="button" className="btn-ghost btn-sm h-6 px-1.5" disabled={busy} onClick={() => void remove(r.id)} aria-label={`${caseLabel(r.case)} ${r.attribute_label} 규칙 풀기`}>
                  <Trash2 className="h-3.5 w-3.5" aria-hidden />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {open && !archived && (
        <form
          className="grid gap-2 rounded-control border border-line px-3 py-3"
          onSubmit={(e) => {
            e.preventDefault();
            void add();
          }}
        >
          <p className="text-xs leading-5 text-ink-2">고른 사례의 이 단서는 다음 질문부터 넓히지 않고 가립니다. 이미 나간 답은 바뀌지 않습니다.</p>
          <div className="flex flex-wrap gap-2">
            <label className="text-xs text-ink-3">
              사례
              <select value={caseRef} onChange={(e) => setCaseRef(e.target.value)} className="ml-1.5 h-8 rounded-cell border border-line-input bg-surface px-2 text-[13px] text-ink">
                {refs.map((ref) => (
                  <option key={ref} value={ref}>
                    {caseLabel(ref)}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-ink-3">
              단서
              <select value={attr} onChange={(e) => setAttr(e.target.value)} className="ml-1.5 h-8 rounded-cell border border-line-input bg-surface px-2 text-[13px] text-ink">
                {ATTRS.map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            maxLength={300}
            placeholder="메모 (선택): 왜 이 규칙을 거는지"
            className="h-9 rounded-cell border border-line-input bg-surface px-2.5 text-[13px] text-ink outline-none placeholder:text-ink-3 focus:border-focus"
          />
          <div className="flex justify-end gap-1.5">
            <button type="button" className="btn-ghost btn-sm" onClick={() => onOpen(false)}>
              취소
            </button>
            <button type="submit" className="btn-primary btn-sm" disabled={busy}>
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Plus className="h-3.5 w-3.5" aria-hidden />}
              규칙 걸기
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

/** 세부 정보 요청 승인: 가린 값을 골라 사유와 함께 공개한다 */
export function ApprovePanel({
  d,
  caseRef,
  onCancel,
  onDetail,
  initialPick,
  initialReason,
}: {
  d: MonitorDetail;
  caseRef: string | null;
  onCancel(): void;
  onDetail(d: MonitorDetail): void;
  /** 검토 보조 추천대로 미리 고를 값 · 사유 초안 */
  initialPick?: string[];
  initialReason?: string;
}) {
  const toast = useToast();
  const [items, setItems] = useState<HiddenItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set(initialPick ?? []));
  const [reason, setReason] = useState(initialReason ?? '');
  const seeded = !!initialPick?.length;
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const ctl = new AbortController();
    monitorApi.hidden(d.id, ctl.signal).then(
      (xs) => setItems(xs.filter((x) => !x.released && (!caseRef || x.case === caseRef))),
      (e) => {
        if (!(e instanceof DOMException)) setError(e instanceof Error ? e.message : '불러오지 못했습니다.');
      },
    );
    return () => ctl.abort();
  }, [d.id, caseRef]);

  const lowest = items?.filter((x) => picked.has(x.id) && x.kIfRaw != null).reduce<number | null>((m, x) => (m == null ? x.kIfRaw : Math.min(m, x.kIfRaw!)), null);

  async function submit() {
    setBusy(true);
    try {
      const res = await monitorApi.approve(d.id, [...picked], reason.trim());
      onDetail(res.detail);
      const ks = Object.entries(res.approval.k_after)
        .map(([ref, k]) => `${caseLabel(ref)} 후보 ${k}명`)
        .join(', ');
      toast(`값 ${res.approval.items.length}개를 공개했습니다 (${ks}). 의료진 화면의 보호 담당자 창에 도착합니다.`);
      onCancel();
    } catch (e) {
      toast(e instanceof Error ? e.message : '공개하지 못했습니다.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3 rounded-control border border-line bg-surface px-3 py-3 text-[13px]">
      <div className="flex items-center gap-2">
        <h4 className="flex-1 font-bold text-ink">가린 값 공개 승인{caseRef ? ` · ${caseLabel(caseRef)}` : ''}</h4>
        <button type="button" className="btn-ghost btn-sm h-6 px-1.5" onClick={onCancel} aria-label="닫기">
          <X className="h-3.5 w-3.5" aria-hidden />
        </button>
      </div>
      <p className="mt-1 text-xs leading-5 text-ink-2">
        고른 값은 이 의료진의 이 대화에만 나가고, 누적 판정에 더해져 이후 답에 반영됩니다. 사유와 공개한 항목은 감사 기록에 남습니다.
        {seeded && ' 검토 보조가 공개 가능으로 본 값과 사유 초안을 담아 두었습니다. 확인하고 고쳐서 공개하세요.'}
      </p>
      {error ? (
        <p className="mt-2 text-xs text-danger-text">{error}</p>
      ) : !items ? (
        <p className="mt-2 text-xs text-ink-3">가린 값을 불러오는 중</p>
      ) : items.length === 0 ? (
        <p className="mt-2 text-xs text-ink-3">공개할 수 있는 가린 값이 없습니다.</p>
      ) : (
        <ul className="mt-2 divide-y divide-line/70 rounded-cell border border-line">
          {items.map((x) => (
            <li key={x.id}>
              <label className="flex cursor-pointer items-center gap-2.5 px-2.5 py-2 text-xs hover:bg-surface-2">
                <input
                  type="checkbox"
                  checked={picked.has(x.id)}
                  onChange={(e) =>
                    setPicked((s) => {
                      const n = new Set(s);
                      if (e.target.checked) n.add(x.id);
                      else n.delete(x.id);
                      return n;
                    })
                  }
                />
                <span className="min-w-0 flex-1 text-ink">
                  {caseLabel(x.case)} <b>{ATTR_LABEL[x.attribute] ?? x.attribute}</b>
                  <span className="text-ink-3"> · {where(x.turn)}에서 {x.dropped ? '사례째로 뺌' : x.action === 'generalize' ? '넓힘' : '가림'}</span>
                </span>
                {x.kIfRaw != null && (
                  <span className="num shrink-0 text-ink-2">
                    그대로면 <b className={x.kIfRaw < d.k_req ? 'text-danger-text' : 'text-ink'}>{x.kIfRaw}명</b>
                  </span>
                )}
              </label>
            </li>
          ))}
        </ul>
      )}
      {lowest != null && lowest < d.k_req && (
        <p className="mt-2 rounded-cell bg-danger-tint px-2.5 py-1.5 text-xs text-danger-text">
          고른 값을 공개하면 후보가 {lowest}명까지 줄 수 있습니다 (기준 {d.k_req}명). 그 뒤 이 사례의 새 단서는 가려서 답합니다.
        </p>
      )}
      <label htmlFor="approve-reason" className="mt-2.5 block text-xs font-semibold text-ink-2">
        공개 사유 (5자 이상, 감사 기록에 남음)
      </label>
      <textarea
        id="approve-reason"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        rows={2}
        maxLength={300}
        placeholder="예: 처방 시작 시기가 현재 환자 약물 조정 판단에 필요함"
        className="mt-1 w-full resize-none rounded-control border border-line-input bg-surface px-3 py-2 text-[13px] leading-5 text-ink outline-none placeholder:text-ink-3 focus:border-focus"
      />
      <div className="mt-1.5 flex justify-end gap-1.5">
        <button type="button" className="btn-ghost btn-sm" onClick={onCancel}>
          취소
        </button>
        <button type="button" className="btn-primary btn-sm" disabled={busy || picked.size === 0 || reason.trim().length < 5} onClick={() => void submit()}>
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <ShieldCheck className="h-3.5 w-3.5" aria-hidden />}
          고른 값 {picked.size}개 공개
        </button>
      </div>
    </div>
  );
}

/** 승인 공개 기록 (값은 열람 뒤에만) */
export function ApprovalsList({ d }: { d: MonitorDetail }) {
  const aps = d.approvals ?? [];
  if (!aps.length) return null;
  return (
    <section aria-label="승인 공개 기록" className="border-b border-line px-5 py-4">
      <h3 className="mb-2 text-[13px] font-bold text-ink-2">승인 공개 기록</h3>
      <ul className="space-y-1.5">
        {aps.map((ap) => (
          <li key={ap.id} className="rounded-cell bg-surface-2 px-2.5 py-2 text-xs">
            <p className="text-ink">
              {ap.items.map((x, i) => (
                <span key={i} className="mr-2 inline-block">
                  {caseLabel(x.case)} <b>{x.attribute_label}</b>
                  {x.value ? <span className="text-ink-2">: {x.value}</span> : <span className="redact ml-1 inline-block align-middle" style={{ width: 48 }} aria-label="열람 전" />}
                </span>
              ))}
            </p>
            <p className="mt-0.5 text-ink-3">
              {ap.by.split(' (')[0]} · {clockTime(ap.at)} · 사유: {ap.reason} · 공개 뒤{' '}
              {Object.entries(ap.k_after)
                .map(([ref, k]) => `${caseLabel(ref)} 후보 ${k}명`)
                .join(', ')}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
