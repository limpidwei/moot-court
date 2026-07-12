"use client";

// Agentic 执行面板：杀手场景入口 + Proposal 审批门

import { useState, useEffect, useCallback } from "react";
import {
  analyzeEvidenceChain,
  analyzePleaBargain,
  analyzeExecutionRisk,
  analyzeJudgeQuestions,
  approveProposal,
  rejectProposal,
  listProposals,
  type Proposal,
} from "@/lib/api";

interface AgenticPanelProps {
  caseId: string;
}

const SCENARIOS = [
  { key: "evidence-chain", label: "🔍 证据链缺口诊断", run: analyzeEvidenceChain },
  { key: "plea-bargain", label: "💰 调解报价建议", run: analyzePleaBargain },
  { key: "execution-risk", label: "⚠️ 执行风险评估", run: analyzeExecutionRisk },
  { key: "judge-questions", label: "🧑‍⚖️ 法官追问预测", run: analyzeJudgeQuestions },
];

export default function AgenticPanel({ caseId }: AgenticPanelProps) {
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [loading, setLoading] = useState<Record<string, boolean>>({});
  const [error, setError] = useState("");

  const loadProposals = useCallback(async () => {
    try {
      const res = await listProposals(caseId);
      setProposals(res.items);
    } catch {
      // 忽略首次加载失败
    }
  }, [caseId]);

  useEffect(() => {
    loadProposals();
  }, [loadProposals]);

  const handleRun = async (scenario: typeof SCENARIOS[number]) => {
    setLoading((prev: Record<string, boolean>) => ({ ...prev, [scenario.key]: true }));
    setError("");
    try {
      await scenario.run(caseId);
      await loadProposals();
    } catch (e: any) {
      setError(e.message || `${scenario.label} 失败`);
    } finally {
      setLoading((prev: Record<string, boolean>) => ({ ...prev, [scenario.key]: false }));
    }
  };

  const handleApprove = async (proposalId: string) => {
    setLoading((prev: Record<string, boolean>) => ({ ...prev, [proposalId]: true }));
    try {
      await approveProposal(caseId, proposalId);
      await loadProposals();
    } catch (e: any) {
      setError(e.message || "审批失败");
    } finally {
      setLoading((prev: Record<string, boolean>) => ({ ...prev, [proposalId]: false }));
    }
  };

  const handleReject = async (proposalId: string) => {
    setLoading((prev: Record<string, boolean>) => ({ ...prev, [proposalId]: true }));
    try {
      await rejectProposal(caseId, proposalId);
      await loadProposals();
    } catch (e: any) {
      setError(e.message || "驳回失败");
    } finally {
      setLoading((prev: Record<string, boolean>) => ({ ...prev, [proposalId]: false }));
    }
  };

  const pending = proposals.filter((p) => p.status === "pending");
  const executed = proposals.filter((p) => ["executed", "failed"].includes(p.status));

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
      <h2 className="font-semibold text-gray-800 mb-4">🤖 AI 分析助手（需审批）</h2>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        {SCENARIOS.map((s) => (
          <button
            key={s.key}
            onClick={() => handleRun(s)}
            disabled={loading[s.key]}
            className="bg-indigo-50 hover:bg-indigo-100 text-indigo-700 border border-indigo-200 rounded-lg px-3 py-3 text-sm font-medium transition disabled:opacity-50 text-left"
          >
            {loading[s.key] ? "分析中..." : s.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="bg-red-50 text-red-700 rounded-lg p-3 mb-4 text-sm">{error}</div>
      )}

      {/* 待审批提案 */}
      {pending.length > 0 && (
        <div className="mb-6">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">📝 待审批分析</h3>
          <div className="space-y-3">
            {pending.map((p) => (
              <div key={p.id} className="border border-yellow-200 bg-yellow-50 rounded-lg p-4">
                <p className="text-sm font-medium text-gray-800">{p.task}</p>
                <p className="text-xs text-gray-600 mt-1">{p.rationale}</p>
                <div className="flex gap-2 mt-3">
                  <button
                    onClick={() => handleApprove(p.id)}
                    disabled={loading[p.id]}
                    className="bg-green-600 text-white text-xs px-3 py-1.5 rounded hover:bg-green-700 disabled:opacity-50"
                  >
                    {loading[p.id] ? "执行中..." : "✅ 审批执行"}
                  </button>
                  <button
                    onClick={() => handleReject(p.id)}
                    disabled={loading[p.id]}
                    className="bg-gray-200 text-gray-700 text-xs px-3 py-1.5 rounded hover:bg-gray-300 disabled:opacity-50"
                  >
                    ❌ 驳回
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 已执行结果 */}
      {executed.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-700 mb-3">📊 分析结果</h3>
          <div className="space-y-3">
            {executed.map((p) => (
              <div key={p.id} className="border border-gray-200 rounded-lg p-4">
                <div className="flex items-center justify-between mb-2">
                  <p className="text-sm font-medium text-gray-800">{p.task}</p>
                  <span
                    className={`text-xs px-2 py-0.5 rounded-full ${
                      p.status === "executed"
                        ? "bg-green-100 text-green-700"
                        : "bg-red-100 text-red-700"
                    }`}
                  >
                    {p.status === "executed" ? "已完成" : "失败"}
                  </span>
                </div>
                {p.status === "executed" && p.result && (
                  <pre className="text-xs bg-gray-50 rounded p-3 overflow-auto max-h-60">
                    {JSON.stringify(p.result, null, 2)}
                  </pre>
                )}
                {p.status === "failed" && typeof p.result?.error === "string" && (
                  <p className="text-xs text-red-600">{p.result.error}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
