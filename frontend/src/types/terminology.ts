// 의료 용어 RAG 타입 (백엔드 medical/terminology_api.py · 이유진 medical/terminology.py의 JSON 키 그대로)

export type TermAttribute = 'DX' | 'MED' | 'PROC';

/** security: 모든 필드 / clinician: 기준 집단 환자 수(k_patients · total_patients)를 뺀 보기 */
export type TermView = 'security' | 'clinician';

export interface TermSummary {
  node_id: string;
  attribute: TermAttribute;
  attribute_label: string;
  canonical_label: string;
  /** LLM이 만든 일반인용 설명. 아직 없으면 null */
  plain_explanation: string | null;
  has_explanation: boolean;
  standard_code: string | null;
  /** 코드 체계 (RxNorm · SNOMED CT · ICD-10 · ATC · ICD-10-PCS) */
  source: string;
  level_label: string;
  parent_id: string | null;
  is_sensitive: boolean;
  review_status: string;
  reviewer?: string | null;
  reviewed_at?: string | null;
  llm_model: string | null;
  /** security 보기에만 */
  k_patients?: number | null;
  total_patients?: number | null;
  /** detect 결과에만: 이번 글에서 나온 횟수 */
  mentions?: number;
}

export interface TermChainStep {
  node_id: string;
  label: string;
  plain_explanation: string | null;
  level_label: string;
}

export interface TermCard extends TermSummary {
  generalization_chain: TermChainStep[];
  aliases: string[];
}

export interface TermMention {
  start: number;
  end: number;
  node_id: string;
}

export interface TermDetectResult {
  /** 보낸 글 순서대로, 글마다 찾은 용어 위치 */
  mentions: TermMention[][];
  terms: Record<string, TermSummary>;
}

export interface TermStatus {
  available: boolean;
  /** 용어 DB 파일이 없어 노드 표로 설명 없는 DB를 임시로 만든 경우 */
  generated: boolean;
  total?: number;
  by_attribute?: Partial<Record<TermAttribute, number>>;
  explained?: number;
  reviewed?: number;
  sensitive?: number;
  llm_models?: string[];
  build_command: string;
  db?: string;
  /** Mock 모드 */
  mock?: boolean;
}

export interface TermPage {
  total: number;
  limit: number;
  offset: number;
  items: TermSummary[];
}

export const TERM_ATTR_LABEL: Record<TermAttribute, string> = { DX: '진단', MED: '약', PROC: '시술' };
