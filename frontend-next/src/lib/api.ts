// 模拟法庭 v2.0 — API 客户端

import { getAuthHeaders, logout } from "./auth";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

// 长请求（庭审阶段调用）的超时时间：30 分钟
// Phase 5-8 含多轮 Agent 交互，总耗时可能较长
const LONG_TIMEOUT = 30 * 60 * 1000;

// 处理 401 响应
function handleUnauthorized(res: Response) {
  if (res.status === 401) {
    logout();
  }
  return res;
}

// H8 修复：统一错误处理 —— 校验 res.ok，解析后端 detail，调用方一律 throw 而非把错误响应当成功。
// 取代各处 `return res.json()` 的静默失败（如 createCase 失败 → undefined case_id → 跳 /trial/undefined）。
async function assertOk(res: Response, fallbackMsg: string): Promise<void> {
  if (res.ok) return;
  let detail = fallbackMsg;
  try {
    const data = await res.json();
    detail = data.detail || data.message || fallbackMsg;
  } catch {
    // 响应非 JSON，沿用 fallbackMsg
  }
  throw new Error(`${detail} (${res.status})`);
}

async function fetchWithTimeout(url: string, options: RequestInit = {}, timeout = LONG_TIMEOUT) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const res = await fetch(url, {
      ...options,
      headers: {
        ...getAuthHeaders(),
        ...options.headers,
      },
      signal: controller.signal,
    });
    return handleUnauthorized(res);
  } finally {
    clearTimeout(timer);
  }
}

export interface LLMConfig {
  provider: string;
  base_url: string;
  api_key: string;
  model: string;
  temperature: number;
}

export const PROVIDER_PRESETS: Record<string, { base_url: string; models: string[] }> = {
  deepseek: {
    base_url: "https://api.deepseek.com",
    models: ["deepseek-v4-flash", "deepseek-v4-pro"],
  },
  kimi: {
    base_url: "https://api.moonshot.cn/v1",
    models: ["kimi-k2.6", "kimi-k2.5", "moonshot-v1-128k"],
  },
  glm: {
    base_url: "https://open.bigmodel.cn/api/paas/v4",
    models: ["glm-5.1", "glm-5-turbo", "glm-4.7"],
  },
  minimax: {
    base_url: "https://api.minimax.io/v1",
    models: ["MiniMax-M2.7", "MiniMax-M2.5"],
  },
  mimo: {
    base_url: "https://api.xiaomimimo.com/v1",
    models: ["mimo-v2-flash", "mimo-v2-pro"],
  },
};

export interface CaseSummary {
  case_id: string;
  case_title: string;
  current_phase: number;
  created_at: string;
  mode?: string;
  user_side?: string;
}

export interface CaseListResponse {
  items: CaseSummary[];
  total: number;
  page: number;
  page_size: number;
}

export async function getCases(params?: {
  q?: string;
  mode?: string;
  phase?: number;
  sort?: string;
  page?: number;
  page_size?: number;
}): Promise<CaseListResponse> {
  const query = new URLSearchParams();
  if (params?.q) query.set("q", params.q);
  if (params?.mode) query.set("mode", params.mode);
  if (params?.phase !== undefined && params.phase >= 0)
    query.set("phase", String(params.phase));
  if (params?.sort) query.set("sort", params.sort);
  if (params?.page) query.set("page", String(params.page));
  if (params?.page_size) query.set("page_size", String(params.page_size));

  const res = await fetch(`${API_BASE}/cases?${query.toString()}`, {
    headers: getAuthHeaders(),
  });
  handleUnauthorized(res);
  if (!res.ok) {
    throw new Error("获取案件列表失败");
  }
  return res.json();
}

export async function deleteCase(caseId: string) {
  const res = await fetch(`${API_BASE}/cases/${caseId}`, {
    method: "DELETE",
    headers: getAuthHeaders(),
  });
  handleUnauthorized(res);
  await assertOk(res, "删除案件失败");
  return res.json();
}

export async function renameCase(caseId: string, caseTitle: string) {
  const res = await fetch(`${API_BASE}/cases/${caseId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify({ case_title: caseTitle }),
  });
  handleUnauthorized(res);
  await assertOk(res, "重命名案件失败");
  return res.json();
}

export async function createCase(data: {
  case_title: string;
  facts: string;
  evidence: string;
  claims: string;
  mode?: string;           // "neutral" | "asymmetric"
  user_side?: string;      // "plaintiff" | "defendant" | ""
  user_strategy_hint?: string;
  source_materials?: string;
  adversarial_intensity?: number; // 1-5
  llm_config?: LLMConfig;
}): Promise<{ case_id: string; [key: string]: unknown }> {
  const res = await fetch(`${API_BASE}/case/create`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify(data),
  });
  handleUnauthorized(res);
  await assertOk(res, "创建案件失败");
  return res.json();
}

export async function parseText(text: string) {
  const formData = new FormData();
  formData.append("text", text);
  const res = await fetch(`${API_BASE}/case/parse-text`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: formData,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `解析请求失败 (${res.status})`);
  }
  return data;
}

export async function parseFile(file: File) {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_BASE}/case/parse-file`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: formData,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `文件解析请求失败 (${res.status})`);
  }
  return data;
}

export async function getTrialState(caseId: string) {
  const res = await fetch(`${API_BASE}/trial/state/${caseId}`, {
    headers: getAuthHeaders(),
  });
  handleUnauthorized(res);
  await assertOk(res, "获取庭审状态失败");
  return res.json();
}

export async function askJudge(caseId: string, question: string) {
  const res = await fetch(`${API_BASE}/trial/judge-qa`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify({ case_id: caseId, question }),
  });
  handleUnauthorized(res);
  await assertOk(res, "法官问答失败");
  return res.json();
}

export async function getPhaseInsights(caseId: string, phase: number) {
  const res = await fetch(`${API_BASE}/trial/insights/${caseId}/${phase}`, {
    headers: getAuthHeaders(),
  });
  handleUnauthorized(res);
  await assertOk(res, "获取洞察失败");
  return res.json();
}

export async function getTrialHistory(caseId: string) {
  const res = await fetch(`${API_BASE}/trial/history/${caseId}`, {
    headers: getAuthHeaders(),
  });
  handleUnauthorized(res);
  await assertOk(res, "获取历史快照失败");
  return res.json();
}

export async function resetTrial(caseId: string, toPhase: number) {
  const res = await fetch(`${API_BASE}/trial/reset/${caseId}/${toPhase}`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  handleUnauthorized(res);
  await assertOk(res, "回退庭审失败");
  return res.json();
}

export async function selectStrategy(caseId: string, phase: number, routeId: string) {
  const res = await fetch(`${API_BASE}/trial/select-strategy/${caseId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify({ phase, route_id: routeId }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "选择策略失败" }));
    throw new Error(err.detail || "选择策略失败");
  }
  return res.json();
}

// ============================================================
// 证据管理 API
// ============================================================

export async function uploadEvidence(
  caseId: string,
  files: File[],
  party: string = "unknown",
  evidenceType: string = ""
) {
  const formData = new FormData();
  formData.append("case_id", caseId);
  formData.append("party", party);
  if (evidenceType) formData.append("evidence_type", evidenceType);
  files.forEach((file) => formData.append("files", file));

  const res = await fetch(`${API_BASE}/evidence/upload`, {
    method: "POST",
    headers: getAuthHeaders(), // FormData 不能设 Content-Type
    body: formData,
  });
  handleUnauthorized(res);
  await assertOk(res, "证据上传失败");
  return res.json();
}

export async function getEvidence(caseId: string) {
  const res = await fetch(`${API_BASE}/evidence/${caseId}`, {
    headers: getAuthHeaders(),
  });
  handleUnauthorized(res);
  await assertOk(res, "获取证据列表失败");
  return res.json();
}

export async function analyzeEvidence(caseId: string) {
  const res = await fetchWithTimeout(`${API_BASE}/evidence/${caseId}/analyze`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  await assertOk(res, "证据分析失败");
  return res.json();
}

export async function importEvidenceToTrial(caseId: string) {
  const res = await fetch(`${API_BASE}/evidence/${caseId}/import-to-trial`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  handleUnauthorized(res);
  await assertOk(res, "证据导入庭审失败");
  return res.json();
}

export async function deleteEvidence(caseId: string, evidenceId: string) {
  const res = await fetch(`${API_BASE}/evidence/${caseId}/${evidenceId}`, {
    method: "DELETE",
    headers: getAuthHeaders(),
  });
  handleUnauthorized(res);
  await assertOk(res, "删除证据失败");
  return res.json();
}

export interface TrialStreamEvent {
  type?: string;
  phase?: number;
  speaker?: string;
  content?: string;
  msg_type?: string;
  round?: number;
  item?: number;
  message?: string;
  [key: string]: unknown;
}

// SSE 流式庭审（混合粒度）
// H9 修复：新增可选 signal 参数，调用方可在卸载/中断时 abort fetch，
// 终止后端流式（停止烧 token）并阻止 abort 后的 setState。
export async function connectTrialStream(
  data: {
    case_id: string;
    action: string;
    user_role?: string;
    confirmed_phase?: number;
    edited_content?: string;
    llm_config?: LLMConfig;
  },
  onEvent: (event: TrialStreamEvent) => void,
  signal?: AbortSignal
) {
  const res = await fetch(`${API_BASE}/trial/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify(data),
    signal,
  });
  // 401 统一处理（SSE 也要走）
  handleUnauthorized(res);
  if (!res.body) throw new Error("No response body");
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        const trimmed = line.trimStart();
        if (trimmed.startsWith("data:")) {
          const payload = trimmed.slice(5).trimStart();
          try {
            const event = JSON.parse(payload);
            onEvent(event);
          } catch {
            // ignore parse error
          }
        }
      }
    }
  } finally {
    // 修复：flush decoder 残留字节（覆盖正常结束 + abort 两种场景）
    // abort 时 reader.read() 抛 AbortError 直接跳到 finally，原来的 flush 逻辑被跳过。
    // 此处先 cancel 中断读取中的流，再 releaseLock 释放 reader，避免泄漏。
    try {
      const leftover = decoder.decode();
      if (leftover) buffer += leftover;
      if (buffer.trim()) {
        const trimmed = buffer.trimStart();
        if (trimmed.startsWith("data:")) {
          try {
            onEvent(JSON.parse(trimmed.slice(5).trimStart()));
          } catch {}
        }
      }
    } catch {
      // flush 失败不影响 reader 释放
    }
    try {
      await reader.cancel();
    } catch {
      // stream already cancelled
    }
    try {
      reader.releaseLock();
    } catch {
      // already released
    }
  }
}

// ============================================================
// 用量统计 API
// ============================================================

export interface UsageSummary {
  daily: { used: number; limit: number; remaining: number };
  monthly: { used: number; limit: number; remaining: number };
  total: { tokens: number; calls: number };
}

export async function getUsageSummary(): Promise<UsageSummary> {
  const res = await fetch(`${API_BASE}/usage/summary`, {
    headers: getAuthHeaders(),
  });
  handleUnauthorized(res);
  if (!res.ok) throw new Error("获取用量统计失败");
  return res.json();
}

export interface UsageRecord {
  id: number;
  case_id: string | null;
  model: string;
  endpoint: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  latency_ms: number;
  success: boolean;
  created_at: string;
}

export interface UsageRecordsResponse {
  items: UsageRecord[];
  total: number;
  page: number;
  page_size: number;
}

export async function getUsageRecords(params?: {
  page?: number;
  page_size?: number;
}): Promise<UsageRecordsResponse> {
  const query = new URLSearchParams();
  if (params?.page) query.set("page", String(params.page));
  if (params?.page_size) query.set("page_size", String(params.page_size));
  const res = await fetch(`${API_BASE}/usage?${query.toString()}`, {
    headers: getAuthHeaders(),
  });
  handleUnauthorized(res);
  if (!res.ok) throw new Error("获取用量明细失败");
  return res.json();
}

// ============================================================
// 案件分享 API
// ============================================================

export async function createShare(caseId: string) {
  const res = await fetch(`${API_BASE}/cases/${caseId}/share`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  handleUnauthorized(res);
  if (!res.ok) throw new Error("创建分享链接失败");
  return res.json() as Promise<{ share_id: string; token: string; url: string }>;
}


// ============================================================
// 通知 API
// ============================================================

export interface NotificationItem {
  id: number;
  type: string;
  title: string;
  message: string;
  data: Record<string, unknown>;
  read: boolean;
  created_at: string;
}

export async function getNotifications(): Promise<{ items: NotificationItem[]; unread_count: number }> {
  const res = await fetch(`${API_BASE}/notifications`, {
    headers: getAuthHeaders(),
  });
  handleUnauthorized(res);
  if (!res.ok) throw new Error("获取通知失败");
  return res.json();
}

export async function markNotificationRead(id: number) {
  const res = await fetch(`${API_BASE}/notifications/${id}/read`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  handleUnauthorized(res);
  await assertOk(res, "标记通知已读失败");
  return res.json();
}

export async function markAllNotificationsRead() {
  const res = await fetch(`${API_BASE}/notifications/read-all`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  handleUnauthorized(res);
  await assertOk(res, "全部已读失败");
  return res.json();
}

// ============================================================
// Ontology API（Palantir 式案件本体与决策工作台）
// ============================================================

export interface OntologyDashboardSummary {
  case: {
    id: string;
    title: string;
    case_type: string;
    mode: string;
    status: string;
  };
  parties: { role: string; name: string }[];
  stats: {
    claims_count: number;
    facts_count: number;
    evidence_count: number;
    issues_count: number;
    open_issues_count: number;
    disputed_facts_count: number;
    weak_evidence_count: number;
    open_actions_count: number;
    pending_decisions_count: number;
    fact_health: number;
  };
  top_issues: { id: string; title: string; priority: number; status: string }[];
  top_actions: { id: string; title: string; priority: string }[];
  pending_decisions: { id: string; title: string; decision_type: string }[];
}

export async function getOntologyDashboard(caseId: string): Promise<OntologyDashboardSummary> {
  const res = await fetch(`${API_BASE}/ontology/${caseId}/dashboard`, {
    headers: getAuthHeaders(),
  });
  handleUnauthorized(res);
  await assertOk(res, "获取案件工作台失败");
  return res.json();
}

export async function extractOntology(caseId: string): Promise<unknown> {
  const res = await fetch(`${API_BASE}/ontology/${caseId}/extract`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  handleUnauthorized(res);
  await assertOk(res, "提取案件本体失败");
  return res.json();
}

export async function getOntology(caseId: string): Promise<unknown> {
  const res = await fetch(`${API_BASE}/ontology/${caseId}`, {
    headers: getAuthHeaders(),
  });
  handleUnauthorized(res);
  await assertOk(res, "获取案件本体失败");
  return res.json();
}

export async function updateOntologyDecision(
  caseId: string,
  decisionId: string,
  selectedOptionId: string,
  rationale = ""
) {
  const res = await fetch(`${API_BASE}/ontology/${caseId}/decisions/${decisionId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify({ selected_option_id: selectedOptionId, rationale }),
  });
  handleUnauthorized(res);
  await assertOk(res, "提交决策失败");
  return res.json();
}

export async function updateOntologyActionItem(caseId: string, actionId: string, status: string) {
  const res = await fetch(`${API_BASE}/ontology/${caseId}/action-items/${actionId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify({ status }),
  });
  handleUnauthorized(res);
  await assertOk(res, "更新行动项失败");
  return res.json();
}

// ============================================================
// Agentic API（Codex 式执行 + 审批门）
// ============================================================

export interface Proposal {
  id: string;
  case_id: string;
  task: string;
  action_type: string;
  skill_name: string;
  params: Record<string, unknown>;
  rationale: string;
  status: "pending" | "approved" | "rejected" | "executed" | "failed";
  result: Record<string, unknown>;
  created_by: string;
  created_at: string;
}

export async function runAgent(caseId: string, task: string): Promise<{ proposals: Proposal[] }> {
  const res = await fetch(`${API_BASE}/agent/${caseId}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify({ task }),
  });
  handleUnauthorized(res);
  await assertOk(res, "Agent 任务提交失败");
  return res.json();
}

export async function approveProposal(caseId: string, proposalId: string, rationale = "") {
  const res = await fetch(`${API_BASE}/agent/${caseId}/proposals/${proposalId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify({ rationale }),
  });
  handleUnauthorized(res);
  await assertOk(res, "审批提案失败");
  return res.json();
}

export async function rejectProposal(caseId: string, proposalId: string, rationale = "") {
  const res = await fetch(`${API_BASE}/agent/${caseId}/proposals/${proposalId}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify({ rationale }),
  });
  handleUnauthorized(res);
  await assertOk(res, "驳回提案失败");
  return res.json();
}

export async function listProposals(caseId: string): Promise<{ items: Proposal[] }> {
  const res = await fetch(`${API_BASE}/agent/${caseId}/proposals`, {
    headers: getAuthHeaders(),
  });
  handleUnauthorized(res);
  await assertOk(res, "获取提案列表失败");
  return res.json();
}

// 杀手场景快捷 API
export async function analyzeEvidenceChain(caseId: string) {
  return runAgent(caseId, "证据链缺口诊断");
}
export async function analyzePleaBargain(caseId: string) {
  return runAgent(caseId, "调解报价策略");
}
export async function analyzeExecutionRisk(caseId: string) {
  return runAgent(caseId, "执行风险评估");
}
export async function analyzeJudgeQuestions(caseId: string) {
  return runAgent(caseId, "预测法官可能追问的问题");
}
