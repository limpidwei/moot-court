"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getUsageSummary, getUsageRecords, type UsageSummary, type UsageRecord } from "@/lib/api";

function formatNumber(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
  return String(n);
}

function ProgressBar({ used, limit }: { used: number; limit: number }) {
  const pct = limit > 0 ? Math.min(100, (used / limit) * 100) : 0;
  const color = pct >= 90 ? "bg-red-500" : pct >= 70 ? "bg-yellow-500" : "bg-blue-500";
  return (
    <div className="w-full bg-gray-200 rounded-full h-2.5 mt-2">
      <div className={`${color} h-2.5 rounded-full transition-all`} style={{ width: `${pct}%` }} />
    </div>
  );
}

export default function UsagePage() {
  const router = useRouter();
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [records, setRecords] = useState<UsageRecord[]>([]);
  const [totalRecords, setTotalRecords] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const PAGE_SIZE = 20;

  const load = () => {
    setLoading(true);
    setError("");
    Promise.all([
      getUsageSummary(),
      getUsageRecords({ page, page_size: PAGE_SIZE }),
    ])
      .then(([s, r]) => {
        setSummary(s);
        setRecords(r.items);
        setTotalRecords(r.total);
      })
      .catch((e) => {
        setSummary(null);
        setRecords([]);
        setError(e.message || "加载失败，请检查网络连接或重新登录");
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  const totalPages = Math.ceil(totalRecords / PAGE_SIZE);

  return (
    <div className="min-h-screen bg-gray-50 px-4 py-8">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-3">
            <button
              onClick={() => router.push("/")}
              className="text-gray-500 hover:text-gray-700 text-sm"
            >
              ← 返回
            </button>
            <h1 className="text-2xl font-bold text-gray-800">📊 LLM 用量统计</h1>
          </div>
          <button
            onClick={load}
            className="text-sm text-blue-600 hover:text-blue-700 px-3 py-1.5 border border-blue-200 rounded-lg hover:bg-blue-50 transition"
          >
            🔄 刷新
          </button>
        </div>

        {loading && !summary && !error && (
          <div className="text-center text-gray-400 py-12">加载中...</div>
        )}

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-xl p-4 mb-6 text-red-700 text-sm">
            ⚠️ {error}
          </div>
        )}

        {summary && (
          <>
            {/* Summary Cards */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
              <div className="bg-white border border-gray-200 rounded-xl p-5">
                <div className="text-sm text-gray-500 mb-1">今日用量</div>
                <div className="text-2xl font-bold text-gray-800">
                  {formatNumber(summary.daily.used)}
                  <span className="text-sm font-normal text-gray-400 ml-1">/ {formatNumber(summary.daily.limit)} tokens</span>
                </div>
                <ProgressBar used={summary.daily.used} limit={summary.daily.limit} />
                <div className="text-xs text-gray-400 mt-1">剩余 {formatNumber(summary.daily.remaining)} tokens</div>
              </div>

              <div className="bg-white border border-gray-200 rounded-xl p-5">
                <div className="text-sm text-gray-500 mb-1">本月用量</div>
                <div className="text-2xl font-bold text-gray-800">
                  {formatNumber(summary.monthly.used)}
                  <span className="text-sm font-normal text-gray-400 ml-1">/ {formatNumber(summary.monthly.limit)} tokens</span>
                </div>
                <ProgressBar used={summary.monthly.used} limit={summary.monthly.limit} />
                <div className="text-xs text-gray-400 mt-1">剩余 {formatNumber(summary.monthly.remaining)} tokens</div>
              </div>

              <div className="bg-white border border-gray-200 rounded-xl p-5">
                <div className="text-sm text-gray-500 mb-1">累计总量</div>
                <div className="text-2xl font-bold text-gray-800">{formatNumber(summary.total.tokens)}</div>
                <div className="text-xs text-gray-400 mt-1">tokens · {summary.total.calls} 次调用</div>
              </div>
            </div>

            {/* Records Table */}
            <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
              <div className="px-5 py-4 border-b border-gray-100">
                <h2 className="font-semibold text-gray-700">调用明细</h2>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 text-gray-500">
                    <tr>
                      <th className="px-4 py-3 text-left font-medium">时间</th>
                      <th className="px-4 py-3 text-left font-medium">模型</th>
                      <th className="px-4 py-3 text-left font-medium">端点</th>
                      <th className="px-4 py-3 text-right font-medium">Prompt</th>
                      <th className="px-4 py-3 text-right font-medium">Completion</th>
                      <th className="px-4 py-3 text-right font-medium">总计</th>
                      <th className="px-4 py-3 text-right font-medium">延迟</th>
                      <th className="px-4 py-3 text-center font-medium">状态</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {records.length === 0 && (
                      <tr>
                        <td colSpan={8} className="px-4 py-8 text-center text-gray-400">
                          暂无调用记录
                        </td>
                      </tr>
                    )}
                    {records.map((r) => (
                      <tr key={r.id} className="hover:bg-gray-50">
                        <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                          {new Date(r.created_at).toLocaleString("zh-CN")}
                        </td>
                        <td className="px-4 py-3 text-gray-800">{r.model}</td>
                        <td className="px-4 py-3 text-gray-600">{r.endpoint}</td>
                        <td className="px-4 py-3 text-right text-gray-600">{formatNumber(r.prompt_tokens)}</td>
                        <td className="px-4 py-3 text-right text-gray-600">{formatNumber(r.completion_tokens)}</td>
                        <td className="px-4 py-3 text-right font-medium text-gray-800">{formatNumber(r.total_tokens)}</td>
                        <td className="px-4 py-3 text-right text-gray-600">{r.latency_ms}ms</td>
                        <td className="px-4 py-3 text-center">
                          {r.success ? (
                            <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">成功</span>
                          ) : (
                            <span className="text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded-full">失败</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {totalPages > 1 && (
                <div className="flex items-center justify-center gap-2 py-4 border-t border-gray-100">
                  <button
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page === 1}
                    className="px-3 py-1 rounded border text-sm disabled:opacity-50"
                  >
                    上一页
                  </button>
                  <span className="text-sm text-gray-600">
                    第 {page} / {totalPages} 页
                  </span>
                  <button
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    disabled={page === totalPages}
                    className="px-3 py-1 rounded border text-sm disabled:opacity-50"
                  >
                    下一页
                  </button>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
