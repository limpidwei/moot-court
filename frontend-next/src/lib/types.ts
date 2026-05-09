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

export interface TrialPhase {
  phase: number;
  label: string;
  content: string | object;
  needs_confirm?: boolean;
}

export interface TrialState {
  case_id: string;
  current_phase: number;
  user_role: "plaintiff" | "defendant" | "neutral";
  phase1_confirmed: boolean;
  phase2_confirmed: boolean;
  phase3_confirmed: boolean;
  phase4_confirmed: boolean;
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
