// Mock Service: 백엔드가 없을 때 ClinicalCaseApi를 브라우저 안에서 흉내 낸다.
//
// 이 파일은 "백엔드 역할"을 대신한다. 질문 의도 파악(키워드), k 예측(고정 표), Defender 판정을 여기서 하고,
// UI에는 실제 백엔드와 같은 모양의 결과(보호 조치 메타데이터·확정된 누적 상태)만 넘긴다.
// 판정 순서는 medical/defense.py 정책을 단순화해 따랐다:
//   원래 값 k > minK → 그대로 / 원래 값 k ≤ suppressK → 억제 / 그 사이 → k > minK가 되는 첫 일반화,
//   없으면 k > suppressK가 되는 첫 값, 그것도 없으면 억제.
// 최종 k는 이번에 공개한 값들의 예측 k와 이전 k 중 최솟값으로 근사한다 (실제 kcalc는 결합 계산).

import { josa, josaRo } from '../../lib/korean';
import type {
  CaseId,
  CaseRiskState,
  ChatMessage,
  ConversationSession,
  DisclosureHistoryEntry,
  MessageSegment,
  PolicyDecisionRationale,
  PolicyDecisionState,
  PreflightRiskAssessment,
  PrivacyAction,
  PrivacyTransformation,
  ProtectionResult,
  SendQuestionRequest,
  SendQuestionResponse,
} from '../../types/domain';
import { ApiError, type ClinicalCaseApi } from '../types';
import {
  CASE_PROCEDURE,
  CLINICAL_ANSWERS,
  type ClinicalTopic,
  INITIAL_K,
  MOCK_CASES,
  MOCK_ENVIRONMENT,
  MOCK_ERROR_TRIGGER,
  MOCK_PATIENT,
  MOCK_POLICY,
  QI_LABEL,
  QI_PATTERNS,
  QI_PROJECTIONS,
  type QiAttribute,
  type QiProjection,
  SEED_QUESTIONS,
  SUGGESTED_QUESTIONS,
  TOPIC_PATTERNS,
} from './mockData';

interface DisclosedQi {
  action: PrivacyAction;
  value: string | null;
  level: string;
}

interface CaseStore {
  session: ConversationSession;
  history: DisclosureHistoryEntry[];
  disclosed: Partial<Record<QiAttribute, DisclosedQi>>;
  risk: CaseRiskState;
  lastDecision: PrivacyAction;
}

interface DefenseOutcome {
  attribute: QiAttribute;
  action: PrivacyAction;
  value: string | null;
  level: string;
  fromLevel: string;
  k: number | null;
  repeated: boolean;
}

export interface MockApiOptions {
  /** 응답 지연(ms). 테스트에서는 0. */
  latency?: [number, number];
  now?: () => Date;
}

export function createMockApi(options: MockApiOptions = {}): ClinicalCaseApi {
  const [minLatency, maxLatency] = options.latency ?? [450, 900];
  const now = options.now ?? (() => new Date());
  const policy = MOCK_POLICY;
  let idSeq = 0;
  const nextId = (prefix: string) => `${prefix}-${++idSeq}`;

  const stores = new Map<CaseId, CaseStore>();

  function caseLabel(caseId: CaseId): string {
    return MOCK_CASES.find((c) => c.caseId === caseId)?.label ?? caseId;
  }

  function deriveRisk(caseId: CaseId, k: number, decision: PrivacyAction, version: number): CaseRiskState {
    let riskLevel: CaseRiskState['riskLevel'];
    let statusLabel: string;
    let policyDecision: PolicyDecisionState = decision;
    if (k <= policy.suppressK) {
      riskLevel = 'danger';
      statusLabel = '위험 · 공개 차단';
      policyDecision = 'restrict';
    } else if (k <= policy.minK) {
      riskLevel = 'blocked';
      statusLabel = '추가 공개 제한';
      policyDecision = 'restrict';
    } else if (k <= 15) {
      riskLevel = 'caution';
      statusLabel = '주의';
    } else {
      riskLevel = 'safe';
      statusLabel = '여유';
    }
    return {
      caseId,
      k,
      riskLevel,
      statusLabel,
      disclosureAllowed: k > policy.minK,
      policyDecision,
      version,
      updatedAt: now().toISOString(),
    };
  }

  function ensureStore(caseId: CaseId): CaseStore {
    const existing = stores.get(caseId);
    if (existing) return existing;
    if (!(caseId in INITIAL_K)) throw new ApiError('존재하지 않는 사례입니다.', 404);

    const summary = MOCK_CASES.find((c) => c.caseId === caseId)!;
    const store: CaseStore = {
      session: { sessionId: `session-${caseId}`, caseId, messages: [], questionCount: 0 },
      history: [
        {
          entryId: nextId('dh'),
          turn: 0,
          attribute: 'DX',
          attributeLabel: caseId === 'case-a' ? '진단 · 시술명' : '진단명',
          action: 'allow',
          description: `검색 결과 노출 · ${caseId === 'case-a' ? `${summary.diagnosis}, PCI` : summary.diagnosis}`,
        },
      ],
      disclosed: {},
      risk: deriveRisk(caseId, INITIAL_K[caseId], 'allow', 1),
      lastDecision: 'allow',
    };
    stores.set(caseId, store);
    for (const question of SEED_QUESTIONS[caseId] ?? []) answer(store, question, nextId('seed'));
    return store;
  }

  function detect(question: string) {
    // 질문에 나온 순서대로 답한다.
    const qis = QI_PATTERNS.map(([a, re]) => [a, question.search(re)] as const)
      .filter(([, at]) => at >= 0)
      .sort((x, y) => x[1] - y[1])
      .map(([a]) => a);
    const topics = TOPIC_PATTERNS.filter(([, re]) => re.test(question)).map(([t]) => t);
    return { qis, topics };
  }

  /** 원래 값 k > minK → 그대로 / ≤ suppressK → 억제 / 사이 → k > minK인 첫 일반화, 없으면 원래 값(k > suppressK). */
  function plan(projection: QiProjection): Pick<DefenseOutcome, 'action' | 'value' | 'level' | 'k'> {
    if (projection.rawK > policy.minK) return { action: 'allow', value: projection.rawValue, level: projection.rawLevel, k: projection.rawK };
    if (projection.rawK <= policy.suppressK) return { action: 'suppress', value: null, level: '', k: null };
    const safe = projection.generalizations.find((g) => g.k > policy.minK);
    if (safe) return { action: 'generalize', value: safe.value, level: safe.level, k: safe.k };
    return { action: 'allow', value: projection.rawValue, level: projection.rawLevel, k: projection.rawK };
  }

  function defend(store: CaseStore, attribute: QiAttribute): DefenseOutcome {
    const previous = store.disclosed[attribute];
    if (previous) return { attribute, ...previous, fromLevel: previous.level, k: null, repeated: true };
    const projection = QI_PROJECTIONS[store.session.caseId]?.[attribute];
    if (!projection) return { attribute, action: 'suppress', value: null, level: '', fromLevel: '', k: null, repeated: false };
    return { attribute, fromLevel: projection.rawLevel, repeated: false, ...plan(projection) };
  }

  function sentenceFor(caseId: CaseId, outcome: DefenseOutcome, tid: string): MessageSegment[] {
    const L = caseLabel(caseId);
    const value: MessageSegment = { kind: 'disclosure', text: outcome.value ?? '비공개', transformationId: tid };
    const hidden = outcome.action === 'suppress';
    switch (outcome.attribute) {
      case 'AGE':
        return hidden
          ? [{ kind: 'text', text: `${L}의 시술 당시 나이는 ` }, value, { kind: 'text', text: '입니다. ' }]
          : [{ kind: 'text', text: `${josa(L, '은', '는')} ` }, value, { kind: 'text', text: `에 ${josa(CASE_PROCEDURE[caseId], '을', '를')} 받았습니다. ` }];
      case 'DATE':
        return [{ kind: 'text', text: '시술 시점은 ' }, value, { kind: 'text', text: '입니다. ' }];
      case 'LOC':
        return hidden
          ? [{ kind: 'text', text: '거주 도시는 ' }, value, { kind: 'text', text: '입니다. ' }]
          : [{ kind: 'text', text: '거주 지역은 ' }, value, { kind: 'text', text: '까지 공개할 수 있습니다. ' }];
      case 'STATE':
        return [{ kind: 'text', text: '거주 주는 ' }, value, { kind: 'text', text: '입니다. ' }];
      case 'SEX':
        return [{ kind: 'text', text: '성별은 ' }, value, { kind: 'text', text: '입니다. ' }];
      case 'COMORBID':
        return [{ kind: 'text', text: '동반질환은 ' }, value, { kind: 'text', text: '입니다. ' }];
    }
  }

  function levelDescription(outcome: DefenseOutcome): string {
    if (outcome.action === 'generalize') return `${outcome.fromLevel} → ${outcome.level}`;
    if (outcome.action === 'suppress') return '공개하지 않음';
    return outcome.value ?? '';
  }

  function explain(caseId: CaseId, outcomes: DefenseOutcome[], kBefore: number, kAfter: number): string {
    const L = caseLabel(caseId);
    const fresh = outcomes.filter((o) => !o.repeated);
    const gens = fresh.filter((o) => o.action === 'generalize');
    const sups = fresh.filter((o) => o.action === 'suppress');
    const kPhrase =
      kAfter > policy.minK
        ? kAfter === kBefore
          ? `${L}의 후보 수가 ${kAfter}명으로 유지되었습니다.`
          : `${L}의 후보 수가 ${kBefore}명에서 ${kAfter}명이 되었지만 기준(${policy.minK}명)보다 많습니다.`
        : `${L}의 후보 수가 ${kAfter}명으로 기준(${policy.minK}명) 이하여서 추가 공개가 제한됩니다.`;

    if (fresh.length === 0) {
      return outcomes.length
        ? `이미 공개된 범위 안에서만 답했습니다. ${kPhrase}`
        : `이 답변은 새로운 준식별자를 공개하지 않았습니다. ${kPhrase}`;
    }
    const parts: string[] = [];
    if (gens.length) {
      parts.push(gens.map((g) => `${josa(QI_LABEL[g.attribute], '을', '를')} ${g.fromLevel}에서 ${josaRo(g.level)}`).join(', ') + ' 일반화');
    }
    if (sups.length) parts.push(`${josa(sups.map((s) => QI_LABEL[s.attribute]).join('·'), '을', '를')} 비공개`);
    if (!parts.length) return `새로 공개한 항목이 모두 기준을 넘어 그대로 공개했습니다. ${kPhrase}`;
    return `${parts.join('하고 ')}했습니다. 이에 따라 ${kPhrase}`;
  }

  function answer(store: CaseStore, question: string, clientMessageId: string): SendQuestionResponse {
    const { caseId } = store.session;
    const turn = store.session.questionCount + 1;
    const createdAt = now().toISOString();
    const { qis, topics } = detect(question);

    const outcomes = qis.map((a) => defend(store, a));
    const transformations: PrivacyTransformation[] = [];
    const segments: MessageSegment[] = [];
    for (const outcome of outcomes) {
      const tid = nextId('tf');
      transformations.push({
        id: tid,
        attribute: outcome.attribute,
        attributeLabel: QI_LABEL[outcome.attribute],
        action: outcome.action,
        disclosedValue: outcome.value,
        levelDescription: levelDescription(outcome),
      });
      segments.push(...sentenceFor(caseId, outcome, tid));
    }
    for (const topic of topics as ClinicalTopic[]) segments.push({ kind: 'text', text: `${CLINICAL_ANSWERS[caseId][topic]} ` });
    if (!segments.length) {
      const summary = MOCK_CASES.find((c) => c.caseId === caseId)!;
      segments.push({
        kind: 'text',
        text: `${josa(caseLabel(caseId), '은', '는')} ${summary.diagnosis} 사례입니다 (${summary.description}). 처방·경과처럼 진료에 필요한 내용을 구체적으로 물어보세요.`,
      });
    }

    const kBefore = store.risk.k;
    const disclosedKs = outcomes.filter((o) => !o.repeated && o.k !== null).map((o) => o.k!);
    const kAfter = Math.min(kBefore, ...disclosedKs);
    const fresh = outcomes.filter((o) => !o.repeated);
    const decision: PrivacyAction = fresh.some((o) => o.action === 'generalize')
      ? 'generalize'
      : fresh.length && fresh.every((o) => o.action === 'suppress')
        ? 'suppress'
        : fresh.some((o) => o.action === 'suppress')
          ? 'generalize'
          : 'allow';

    const protection: ProtectionResult = {
      decision,
      transformations,
      explanation: explain(caseId, outcomes, kBefore, kAfter),
      kBefore,
      kAfter,
    };

    const newDisclosures: DisclosureHistoryEntry[] = fresh.map((o) => ({
      entryId: nextId('dh'),
      turn,
      attribute: o.attribute,
      attributeLabel: QI_LABEL[o.attribute],
      action: o.action,
      description: o.action === 'allow' ? `${o.value} (그대로 공개)` : levelDescription(o),
    }));
    for (const o of fresh) store.disclosed[o.attribute] = { action: o.action, value: o.value, level: o.level };

    const userMessage: ChatMessage = {
      messageId: clientMessageId,
      caseId,
      role: 'user',
      turn,
      createdAt,
      segments: [{ kind: 'text', text: question }],
      status: 'sent',
    };
    const assistantMessage: ChatMessage = {
      messageId: nextId('msg'),
      caseId,
      role: 'assistant',
      turn,
      createdAt: now().toISOString(),
      segments,
      protection,
      status: 'sent',
    };

    store.session.messages.push(userMessage, assistantMessage);
    store.session.questionCount = turn;
    store.history.push(...newDisclosures);
    store.lastDecision = decision;
    store.risk = deriveRisk(caseId, kAfter, decision, store.risk.version + 1);

    return { userMessage, assistantMessage, riskState: store.risk, newDisclosures };
  }

  function preflight(store: CaseStore, question: string): PreflightRiskAssessment {
    const { caseId } = store.session;
    const L = caseLabel(caseId);
    const risky = detect(question)
      .qis.filter((a) => !store.disclosed[a])
      .map((a) => ({ attribute: a, projection: QI_PROJECTIONS[caseId]?.[a] }))
      .filter((r) => r.projection && r.projection.rawK <= policy.minK);

    const base = {
      caseId,
      question,
      currentK: store.risk.k,
      source: 'mock' as const,
      suggestions: SUGGESTED_QUESTIONS[caseId] ?? [],
    };
    if (!risky.length) {
      return { ...base, requiresWarning: false, projectedK: null, message: null, affectedAttributes: [], suggestions: [] };
    }
    const projectedK = Math.min(store.risk.k, ...risky.map((r) => r.projection!.rawK));
    const labels = risky.map((r) => `‘${QI_LABEL[r.attribute]}’`).join(', ');
    const actions = risky.map((r) => plan(r.projection!).action);
    const outcomeText = actions.includes('suppress') ? '제외될' : actions.includes('generalize') ? '일반화될' : '그대로 공개되어 후보 수를 줄일';
    return {
      ...base,
      requiresWarning: true,
      projectedK,
      message: `이 질문은 ${L}의 후보를 ${store.risk.k}명에서 ${projectedK}명으로 줄일 수 있습니다. ${labels} 항목은 답변에서 ${outcomeText} 수 있습니다.`,
      affectedAttributes: risky.map((r) => QI_LABEL[r.attribute]),
    };
  }

  function rationale(store: CaseStore): PolicyDecisionRationale {
    const entries = Object.entries(store.disclosed) as [QiAttribute, DisclosedQi][];
    return {
      caseId: store.session.caseId,
      currentK: store.risk.k,
      minK: policy.minK,
      suppressK: policy.suppressK,
      arm: policy.arm,
      disclosedQis: [
        { attributeLabel: '진단명', levelDescription: '검색 결과 노출' },
        ...entries
          .filter(([, d]) => d.action === 'allow')
          .map(([a, d]) => ({ attributeLabel: QI_LABEL[a], levelDescription: d.level })),
      ],
      generalized: entries
        .filter(([, d]) => d.action === 'generalize')
        .map(([a, d]) => ({ attributeLabel: QI_LABEL[a], levelDescription: `${QI_PROJECTIONS[store.session.caseId]?.[a]?.rawLevel} → ${d.level}` })),
      suppressed: entries.filter(([, d]) => d.action === 'suppress').map(([a]) => ({ attributeLabel: QI_LABEL[a] })),
      finalDecision: store.risk.policyDecision,
      finalDecisionLabel: store.risk.statusLabel,
      notes: [
        `원래 값으로 공개했을 때 k가 ${policy.minK} 이하이면 일반화를 시도하고, ${policy.suppressK} 이하이면 일반화 없이 비공개합니다.`,
        `${policy.arm}: 사례별로 앞선 공개를 누적한 State를 기준으로 판정합니다. 다른 사례의 공개는 이 사례의 k에 영향을 주지 않습니다.`,
      ],
      stateVersion: store.risk.version,
      source: 'mock',
    };
  }

  async function delay<T>(fn: () => T, signal?: AbortSignal): Promise<T> {
    const ms = maxLatency > 0 ? minLatency + Math.random() * (maxLatency - minLatency) : 0;
    await new Promise<void>((resolve, reject) => {
      if (signal?.aborted) return reject(new DOMException('Aborted', 'AbortError'));
      const timer = setTimeout(resolve, ms);
      signal?.addEventListener('abort', () => {
        clearTimeout(timer);
        reject(new DOMException('Aborted', 'AbortError'));
      });
    });
    // 호출자가 Mock 내부 상태를 직접 바꾸지 못하도록 복사본을 넘긴다.
    return structuredClone(fn());
  }

  return {
    getWorkspaceEnvironment: (signal) => delay(() => MOCK_ENVIRONMENT, signal),
    getProtectionPolicy: (signal) => delay(() => MOCK_POLICY, signal),
    getPatientContext: (signal) => delay(() => MOCK_PATIENT, signal),
    listSimilarCases: (patientContextId, signal) =>
      delay(() => {
        if (patientContextId !== MOCK_PATIENT.contextId) throw new ApiError('환자 맥락을 찾을 수 없습니다.', 404);
        return MOCK_CASES;
      }, signal),
    getConversation: (caseId, signal) => delay(() => ensureStore(caseId).session, signal),
    sendQuestion: (req: SendQuestionRequest, signal) =>
      delay(() => {
        if (req.question.includes(MOCK_ERROR_TRIGGER)) throw new ApiError('Mock 서버 오류: 응답을 생성하지 못했습니다.', 500);
        const store = ensureStore(req.caseId);
        if (store.session.sessionId !== req.sessionId) throw new ApiError('세션이 일치하지 않습니다.', 409);
        return answer(store, req.question.trim(), req.clientMessageId);
      }, signal),
    assessPreflight: (caseId, _sessionId, question, signal) => delay(() => preflight(ensureStore(caseId), question), signal),
    listRiskStates: (signal) => delay(() => MOCK_CASES.map((c) => ensureStore(c.caseId).risk), signal),
    getDisclosureHistory: (caseId, signal) => delay(() => ({ caseId, entries: ensureStore(caseId).history }), signal),
    getPolicyDecision: (caseId, signal) => delay(() => rationale(ensureStore(caseId)), signal),
  };
}
