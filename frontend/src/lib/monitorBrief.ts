// 관제 상세 맨 위 세 줄 (ADR-0030): 무엇이 위험했나 · 시스템이 한 일 · 내가 할 일.
// 숫자와 그래프를 읽기 전에 이 대화에서 무엇을 해야 하는지부터 보이게 한다.

import type { MonitorDetail } from '../types/monitor';
import { josa } from './korean';
import { caseLabel } from './time';

export interface DetailBrief {
  risk: string;
  done: string;
  todo: string;
  /** 내가 할 일의 급한 정도: 기준 아래 (danger) · 의료진 요청 (request) · 없음 */
  tone: 'danger' | 'request' | null;
}

function where(turn: number): string {
  return turn === 0 ? '첫 답(사례 검색)' : `${turn}턴 답`;
}

function cases(refs: string[]): string {
  return refs.map(caseLabel).join(', ');
}

/** 그대로 답했다면 후보가 어디까지 줄었는지 */
function narrowed(k: number, kReq: number): string {
  if (k <= 1) return '1명으로 줄어 환자가 특정될 수 있었습니다';
  if (k < kReq) return `${k}명으로 좁혀질 수 있었습니다`;
  return `${k}명이었습니다`;
}

export function detailBrief(d: MonitorDetail): DetailBrief {
  const r = d.row;
  const kReq = d.k_req;
  const focusRef = r.focus_case;
  const focus = caseLabel(focusRef) || '이 사례';
  const turns = d.arms[d.live_arm]?.turns ?? [];
  const aps = d.approvals ?? [];
  const approvedLow = r.approved_low ?? [];
  const repeats = r.repeat_subjects ?? [];
  const archived = !!d.archived || !!r.archived;

  // 방어 규칙이 지킨 후보 수: 첫 승인 공개 전 마지막 턴 기록 (승인 공개 뒤의 턴은 공개된 값이 더해진 수다)
  const firstAp = Math.min(...aps.flatMap((ap) => ap.items.map((x) => x.after_turn ?? Infinity)));
  const upto = turns.filter((t) => t.turn <= firstAp);
  const kKept = (focusRef ? upto[upto.length - 1]?.cases?.[focusRef]?.k : null) ?? r.k_now;
  const droppedAt = focusRef ? turns.find((t) => t.dropped?.includes(focusRef)) : undefined;

  // 무엇이 위험했나
  const risk: string[] = [];
  if (r.violated.length) {
    risk.push(`${josa(cases(r.violated), '은', '는')} 방어 규칙을 거치고도 후보가 기준 ${kReq}명 아래로 내려갔습니다.`);
  } else if (droppedAt && r.k_if_raw != null) {
    risk.push(`${where(droppedAt.turn)}에서 ${focus} 내용을 그대로 냈다면 후보가 ${narrowed(r.k_if_raw, kReq)}.`);
  } else if (r.status !== 'safe' && r.k_if_raw != null) {
    risk.push(`${focus} 환자를 좁히는 답이었습니다. 그대로 냈다면 후보가 ${narrowed(r.k_if_raw, kReq)}.`);
  } else if (r.status !== 'safe') {
    risk.push('그대로 내면 후보를 좁히는 값이 답에 있었습니다.');
  } else {
    risk.push(`위험한 답은 없었습니다. 후보가 기준 ${kReq}명보다 많게 유지되었습니다.`);
  }
  if (r.repeated.length && !r.violated.length) risk.push(`${josa(cases(r.repeated), '을', '를')} 거듭 좁혀 물었습니다.`);
  for (const x of repeats) {
    const label = caseLabel(x.case);
    const particle = josa(label, '은', '는').slice(label.length); // 괄호 앞 낱말에 맞춘다: '사례 1(P-…)은'
    risk.push(
      `${label}(${x.tag ?? '기호 없음'})${particle} 최근 다른 대화 ${x.conversations}건에서도 물었습니다${x.clinicians > 1 ? ` (물은 의료진 ${x.clinicians}명)` : ''}.`,
    );
  }

  // 시스템이 한 일
  const done: string[] = [];
  if (r.suppressed && r.generalized) done.push(`값 ${r.suppressed}개를 가리고 ${r.generalized}개를 넓혀 답했습니다.`);
  else if (r.suppressed) done.push(`값 ${r.suppressed}개를 가려 답했습니다.`);
  else if (r.generalized) done.push(`값 ${r.generalized}개를 넓은 범주로 바꿔 답했습니다.`);
  else done.push('모든 답을 그대로 보냈습니다.');
  if (droppedAt) done.push(`${where(droppedAt.turn)}은 고쳐도 다시 확인을 통과하지 못해 ${josa(focus, '을', '를')} 답에서 뺐습니다.`);
  if (r.status !== 'safe' && !r.violated.length && kKept != null) done.push(`${focus} 후보 ${kKept.toLocaleString()}명을 지켰습니다.`);
  if (aps.length) {
    const n = aps.reduce((s, ap) => s + ap.items.length, 0);
    const high = aps.some((ap) => ap.high_risk);
    done.push(`그 뒤 보안 담당자가 요청을 승인해 값 ${n}개를 공개했습니다${high ? ' (고위험 승인)' : ''}.`);
    if (approvedLow.length) done.push(`이 승인으로 ${josa(cases(approvedLow), '은', '는')} 후보가 기준 아래가 되었습니다 (경보가 아니라 승인 공개로 셉니다).`);
    else if (r.k_now != null) done.push(`지금 ${focus} 후보는 ${r.k_now.toLocaleString()}명입니다.`);
  }
  if (d.rules?.length) done.push(`이 대화에 규칙 ${d.rules.length}개가 걸려 있습니다.`);

  // 내가 할 일
  const msgs = d.messages ?? [];
  const last = msgs[msgs.length - 1];
  let todo: string;
  let tone: DetailBrief['tone'] = null;
  if (archived) {
    if (r.review) todo = `지난 대화이고 검토 표시(${r.review.label})가 있습니다. 할 일은 없습니다.`;
    else if (r.needs_review || r.violated.length || r.flag) todo = '지난 대화라 메시지는 보낼 수 없습니다. 기록을 확인하고 검토 완료로 표시하세요.';
    else todo = '할 일은 없습니다.';
  } else if (r.pending_request && last?.kind === 'access_request') {
    todo = `의료진이 ${last.case ? `${caseLabel(last.case)}의 ` : ''}세부 정보를 요청했습니다. 위 요청 칸의 '값 공개 승인'이나 '답장하기'로 답하세요.`;
    tone = 'request';
  } else if (r.pending_request) {
    todo = '의료진 답장을 읽고 답하거나, 문제가 없으면 검토 완료로 표시하세요.';
    tone = 'request';
  } else if (r.violated.length && !r.review) {
    todo = "원문을 열어 무엇이 나갔는지 확인하고, '이 대화에 규칙 걸기'로 같은 단서를 막으세요.";
    tone = 'danger';
  } else if (r.awaiting_clinician) {
    todo = '의료진에게 확인 요청을 보냈습니다. 답이 오면 목록 맨 위로 올라옵니다.';
  } else if (r.review) {
    todo = `검토 표시(${r.review.label})를 남겼습니다. 더 할 일은 없습니다.`;
  } else if (repeats.length) {
    todo = '진료에 필요한 조회였는지 의료진에게 확인 요청을 보내거나, 문제가 없으면 검토 완료로 표시하세요.';
  } else if (r.needs_review) {
    todo = '같은 사례를 거듭 물은 까닭을 의료진에게 확인하거나, 문제가 없으면 검토 완료로 표시하세요.';
  } else {
    todo = r.status === 'safe' ? '할 일은 없습니다.' : '할 일은 없습니다. 방어 규칙이 처리했습니다.';
  }
  return { risk: risk.join(' '), done: done.join(' '), todo, tone };
}
