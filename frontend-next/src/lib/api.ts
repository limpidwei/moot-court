// 模拟法庭 v2.0 — API 客户端

const API_BASE = "http://127.0.0.1:8000";

// 长请求（庭审阶段调用）的超时时间：5 分钟
const LONG_TIMEOUT = 5 * 60 * 1000;

async function fetchWithTimeout(url: string, options: RequestInit = {}, timeout = LONG_TIMEOUT) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const res = await fetch(url, { ...options, signal: controller.signal });
    return res;
  } finally {
    clearTimeout(timer);
  }
}

export async function createCase(data: {
  case_title: string;
  facts: string;
  evidence: string;
  claims: string;
}) {
  const res = await fetch(`${API_BASE}/case/create`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return res.json();
}

export async function parseText(text: string) {
  const formData = new FormData();
  formData.append("text", text);
  const res = await fetch(`${API_BASE}/case/parse-text`, {
    method: "POST",
    body: formData,
  });
  return res.json();
}

export async function parseFile(file: File) {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_BASE}/case/parse-file`, {
    method: "POST",
    body: formData,
  });
  return res.json();
}

export async function startTrial(caseId: string, userRole: string) {
  const res = await fetchWithTimeout(`${API_BASE}/trial/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ case_id: caseId, user_role: userRole }),
  });
  return res.json();
}

export async function continueTrial(
  caseId: string,
  confirmedPhase: number,
  editedContent?: string
) {
  const res = await fetchWithTimeout(`${API_BASE}/trial/continue`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      case_id: caseId,
      confirmed_phase: confirmedPhase,
      edited_content: editedContent || "",
    }),
  });
  return res.json();
}

export async function getTrialState(caseId: string) {
  const res = await fetch(`${API_BASE}/trial/state/${caseId}`);
  return res.json();
}

export async function getPhaseContent(caseId: string, phase: number) {
  const res = await fetch(`${API_BASE}/trial/content/${caseId}/${phase}`);
  return res.json();
}

export async function exportReport(caseId: string) {
  const res = await fetch(`${API_BASE}/trial/export/${caseId}`);
  return res.json();
}

export async function askJudge(caseId: string, question: string) {
  const res = await fetch(`${API_BASE}/trial/judge-qa`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ case_id: caseId, question }),
  });
  return res.json();
}
