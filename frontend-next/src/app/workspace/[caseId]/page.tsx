"use client";

// 案件决策工作台（Palantir 式 Ontology Dashboard）
// 展示案件本体概览、争议焦点、证据链健康度、待办行动与未决决策。

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  getOntologyDashboard,
  extractOntology,
  type OntologyDashboardSummary,
} from "@/lib/api";
import AgenticPanel from "@/components/agentic/AgenticPanel";

function roleLabel(role: string) {
  return role === "plaintiff" ? "原告" : role === "defendant" ? "被告" : role;
}

function priorityClass(priority: string) {
  if (priority === "high") return "bg-red-100 text-red-700";
  if (priority === "medium") return "bg-yellow-100 text-yellow-700";
  return "bg-green-100 text-green-700";
}

export default function WorkspacePage() {
  const params = useParams<{ caseId: string }>();
  const router = useRouter();
  const caseId = params.caseId;

  const [data, setData] = useState<OntologyDashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [extracting, setExtracting] = useState(false);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getOntologyDashboard(caseId);
      setData(res);
    } catch (e: any) {
      // 若 Ontology 尚未提取，提供友好的重新提取入口
      if (e.message?.includes("404") || e.message?.includes("Ontology 不存在")) {
        setError("案件本体尚未提取，请点击「重新提取本体」开始分析。");
      } else {
        setError(e.message || "加载工作台失败");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleExtract = async () => {
    setExtracting(true);
    try {
      await extractOntology(caseId);
      await load();
    } catch (e: any) {
      setError(e.message || "提取失败");
    } finally {
      setExtracting(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId]);

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <p className="text-gray-500">加载案件工作台...</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 px-4 py-6">
      <div className="max-w-5xl mx-auto">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-8">
          <div>
            <button
              onClick={() => router.push("/")}
              className="text-blue-600 text-sm hover:underline mb-2"
            >
              ← 返回首页
            </button>
            <h1 className="text-2xl font-bold text-gray-900">
              {data?.case.title || "案件工作台"}
            </h1>
            <p className="text-sm text-gray-500 mt-1">
              {data?.parties.map((p) => `${roleLabel(p.role)}：${p.name}`).join(" · ")}
            </p>
          </div>
          <div className="flex gap-3">
            <button
              onClick={handleExtract}
              disabled={extracting}
              className="bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-semibold hover:bg-indigo-700 disabled:opacity-50"
            >
              {extracting ? "提取中..." : "🔄 重新提取本体"}
            </button>
            <button
              onClick={() => router.push(`/trial/${caseId}`)}
              className="bg-gray-900 text-white px-4 py-2 rounded-lg text-sm font-semibold hover:bg-gray-800"
            >
              ⚖️ 庭审推演
            </button>
          </div>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl p-4 mb-6">
            {error}
          </div>
        )}

        {data && (
          <>
            {/* 统计卡片区 */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
              <StatCard
                label="争议焦点"
                value={`${data.stats.open_issues_count}/${data.stats.issues_count}`}
                sub="待解决 / 总数"
                color="blue"
              />
              <StatCard
                label="证据链健康度"
                value={`${Math.round(data.stats.fact_health * 100)}%`}
                sub="关键事实有证据支持"
                color="green"
              />
              <StatCard
                label="待办行动"
                value={String(data.stats.open_actions_count)}
                sub="待执行"
                color="orange"
              />
              <StatCard
                label="未决决策"
                value={String(data.stats.pending_decisions_count)}
                sub="需律师确认"
                color="purple"
              />
            </div>

            <div className="grid md:grid-cols-2 gap-6">
              {/* Top Issues */}
              <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
                <h2 className="font-semibold text-gray-800 mb-4">🔥 核心争议焦点</h2>
                {data.top_issues.length === 0 ? (
                  <p className="text-sm text-gray-500">暂无争议焦点，请先完成庭审推演。</p>
                ) : (
                  <ul className="space-y-3">
                    {data.top_issues.map((issue) => (
                      <li key={issue.id} className="border-l-4 border-indigo-400 pl-3">
                        <p className="text-sm font-medium text-gray-800">{issue.title}</p>
                        <div className="flex gap-2 mt-1">
                          <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">
                            优先级 {issue.priority}
                          </span>
                          <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">
                            {issue.status === "open" ? "开放" : issue.status}
                          </span>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              {/* Top Actions */}
              <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
                <h2 className="font-semibold text-gray-800 mb-4">✅ 优先待办行动</h2>
                {data.top_actions.length === 0 ? (
                  <p className="text-sm text-gray-500">暂无待办行动。</p>
                ) : (
                  <ul className="space-y-3">
                    {data.top_actions.map((action) => (
                      <li key={action.id} className="flex items-start gap-3">
                        <span
                          className={`text-xs px-2 py-0.5 rounded-full whitespace-nowrap mt-0.5 ${priorityClass(
                            action.priority
                          )}`}
                        >
                          {action.priority === "high" ? "高" : action.priority === "medium" ? "中" : "低"}
                        </span>
                        <span className="text-sm text-gray-700">{action.title}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>

            {/* Pending Decisions */}
            {data.pending_decisions.length > 0 && (
              <div className="mt-6 bg-white rounded-xl shadow-sm border border-gray-200 p-5">
                <h2 className="font-semibold text-gray-800 mb-4">🤔 待确认决策</h2>
                <ul className="space-y-3">
                  {data.pending_decisions.map((decision) => (
                    <li
                      key={decision.id}
                      className="flex items-center justify-between border border-gray-100 rounded-lg p-3"
                    >
                      <span className="text-sm text-gray-800">{decision.title}</span>
                      <button
                        onClick={() => router.push(`/trial/${caseId}`)}
                        className="text-xs bg-indigo-50 text-indigo-700 px-3 py-1.5 rounded hover:bg-indigo-100"
                      >
                        去确认
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Agentic 杀手场景 */}
            <div className="mt-6">
              <AgenticPanel caseId={caseId} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
  color,
}: {
  label: string;
  value: string;
  sub: string;
  color: "blue" | "green" | "orange" | "purple";
}) {
  const colorMap = {
    blue: "bg-blue-50 border-blue-100",
    green: "bg-green-50 border-green-100",
    orange: "bg-orange-50 border-orange-100",
    purple: "bg-purple-50 border-purple-100",
  };
  return (
    <div className={`rounded-xl border p-4 ${colorMap[color]}`}>
      <p className="text-sm text-gray-600 mb-1">{label}</p>
      <p className="text-2xl font-bold text-gray-900">{value}</p>
      <p className="text-xs text-gray-500 mt-1">{sub}</p>
    </div>
  );
}
