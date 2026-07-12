// 模拟法庭 v2.0 — 类型定义

export interface CaseInput {
  case_title: string;
  facts: string;
  evidence: string;
  claims: string;
}

export interface ParsedCase {
  case_title: string;
  plaintiff: string;
  defendant: string;
  facts: string;
  evidence_list: { name: string; type: string; description: string }[];
  claims: string[];
}

export interface StrategyRoute {
  route_id: string;
  title: string;
  is_recommended: boolean;
  core_theory: string;
  legal_basis: string;
  evidence_strategy: string;
  risk_warning: string;
}

export interface TrialPhase {
  phase: number;
  label: string;
  content: string | object;
  needs_confirm?: boolean;
  strategy_routes?: StrategyRoute[];
  selected_route?: string;
}

export interface TrialState {
  case_id: string;
  current_phase: number;
  user_role: "plaintiff" | "defendant" | "neutral";
  mode?: "neutral" | "asymmetric";
  user_side?: "plaintiff" | "defendant" | "";
  phase1_confirmed: boolean;
  phase2_confirmed: boolean;
  phase3_confirmed: boolean;
  phase4_confirmed: boolean;
  phase5_confirmed?: boolean;
  phase6_confirmed?: boolean;
  phase7_confirmed?: boolean;
  phase8_confirmed?: boolean;
  phase_labels: Record<number, string>;
  win_rate: number;
}

export interface CrossExamMessage {
  round: number;
  speaker: "plaintiff" | "defendant" | "judge";
  type: "question" | "answer" | "guidance";
  content: string;
}

export interface JudgeQAResponse {
  question: string;
  answer: string;
}

export const PHASE_COUNT = 8;

// ============================================================
// 可视化相关类型（详细定义在 components/viz/shared/types.ts）
// ============================================================

export interface VizData {
  type: string;
  data: Record<string, unknown>;
}

// ============================================================
// 证据管理相关类型
// ============================================================

export interface EvidenceItem {
  id: string;
  source_file: string;
  source_type: string;
  content: string;
  summary: string;
  date: string | null;
  parties: string[];
  evidence_type: string;
  relevance: string[];
  confidence: number;
  status: string;
  file_size: number;
  mime_type: string;
  storage_path: string;
  party: string;
  error_message: string;
  created_at: string;
}

export interface TimelineEvent {
  id: string;
  date: string;
  label: string;
  event_type: string;
  evidence_ids: string[];
  phase: number;
  party: string;
}

export interface ClaimDetail {
  evidence_id: string;
  party: string;
  original_text: string;
  extracted_claim: string;
}

export interface ConflictReport {
  id: string;
  case_id: string;
  conflict_type: string;
  severity: "high" | "medium" | "low";
  description: string;
  involved_evidence_ids: string[];
  involved_parties: string[];
  claims: ClaimDetail[];
  ai_note: string;
  resolved: boolean;
  lawyer_note: string;
  created_at: string;
}

export interface EvidenceRegistry {
  case_id: string;
  items: EvidenceItem[];
  timeline: TimelineEvent[];
  party_relations: unknown[];
  conflicts: ConflictReport[];
}
