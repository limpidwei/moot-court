"use client";

// 证据管理页面
// 支持：多模态证据上传、AI 分析、冲突检测、导入庭审系统

import { useState, useEffect, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  getEvidence,
  uploadEvidence,
  analyzeEvidence,
  importEvidenceToTrial,
  deleteEvidence,
} from "@/lib/api";
import type { EvidenceRegistry } from "@/lib/types";
import EvidenceUploader from "@/components/evidence/EvidenceUploader";
import EvidenceList from "@/components/evidence/EvidenceList";
import ConflictPanel from "@/components/evidence/ConflictPanel";

export default function EvidencePage() {
  const params = useParams();
  const router = useRouter();
  const caseId = params.caseId as string;

  const [registry, setRegistry] = useState<EvidenceRegistry | null>(null);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<"list" | "conflicts" | "timeline">("list");

  const loadEvidence = useCallback(async () => {
    if (!caseId) return;
    setLoading(true);
    setError("");
    try {
      const data = await getEvidence(caseId);
      setRegistry(data);
    } catch (e) {
      setError("加载证据失败，请检查后端的启动状态");
    }
    setLoading(false);
  }, [caseId]);

  useEffect(() => {
    loadEvidence();
  }, [loadEvidence]);

  const handleUpload = async (files: File[], party: string, evidenceType: string) => {
    setUploading(true);
    setError("");
    try {
      await uploadEvidence(caseId, files, party, evidenceType);
      await loadEvidence();
    } catch (e) {
      setError("上传失败: " + (e as Error).message);
    }
    setUploading(false);
  };

  const handleAnalyze = async () => {
    if (!registry || registry.items.length === 0) {
      alert("请先上传证据");
      return;
    }
    setAnalyzing(true);
    setError("");
    try {
      const result = await analyzeEvidence(caseId);
      alert(
        `分析完成！\n已分析: ${result.analyzed_count} 条\n发现冲突: ${result.conflict_count} 个\n时间线事件: ${result.timeline_count} 个`
      );
      await loadEvidence();
    } catch (e) {
      setError("AI 分析失败: " + (e as Error).message);
    }
    setAnalyzing(false);
  };

  const handleDelete = async (evidenceId: string) => {
    try {
      await deleteEvidence(caseId, evidenceId);
      await loadEvidence();
    } catch (e) {
      setError("删除失败: " + (e as Error).message);
    }
  };

  const handleImportToTrial = async () => {
    setImporting(true);
    try {
      const result = await importEvidenceToTrial(caseId);
      alert(`导入成功！共导入 ${result.imported_count} 条证据到庭审系统。`);
    } catch (e) {
      setError("导入失败: " + (e as Error).message);
    }
    setImporting(false);
  };

  return (
    <div className="max-w-5xl mx-auto p-4 lg:p-6">
      {/* 头部导航 */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div className="flex items-center gap-4">
          <button
            onClick={() => router.push("/")}
            className="text-blue-600 text-sm hover:underline"
          >
            ← 返回首页
          </button>
          <button
            onClick={() => router.push(`/trial/${caseId}`)}
            className="text-blue-600 text-sm hover:underline"
          >
            🏛️ 进入庭审 →
          </button>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleAnalyze}
            disabled={analyzing}
            className="bg-purple-600 text-white px-4 py-2 rounded-lg text-sm font-semibold
                       disabled:opacity-50 hover:bg-purple-700 transition"
          >
            {analyzing ? "🧠 分析中..." : "🧠 AI 分析"}
          </button>
        </div>
      </div>

      <h1 className="text-2xl font-bold text-gray-800 mb-2">📂 证据管理</h1>
      <p className="text-gray-500 mb-6">
        上传、管理和分析案件证据，自动检测矛盾点
      </p>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg mb-4 text-sm">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 左侧：上传 + 统计 */}
        <div className="lg:col-span-1 space-y-6">
          <EvidenceUploader
            caseId={caseId}
            onUpload={handleUpload}
            uploading={uploading}
          />

          {/* 快速统计 */}
          {registry && (
            <div className="bg-white border rounded-xl p-4 shadow-sm">
              <h4 className="font-semibold text-gray-700 mb-3">📊 统计</h4>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-500">总证据数</span>
                  <span className="font-medium">{registry.items.length}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">已分析</span>
                  <span className="font-medium text-green-600">
                    {registry.items.filter((it) => it.status === "completed").length}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">冲突数</span>
                  <span className={`font-medium ${registry.conflicts.length > 0 ? "text-red-600" : "text-green-600"}`}>
                    {registry.conflicts.length}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">时间线事件</span>
                  <span className="font-medium">{registry.timeline.length}</span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* 右侧：标签页内容 */}
        <div className="lg:col-span-2">
          {/* 标签页 */}
          <div className="flex flex-wrap border-b mb-4">
            {[
              { key: "list" as const, label: "📄 证据列表" },
              { key: "conflicts" as const, label: `⚠️ 冲突检测${registry?.conflicts.length ? ` (${registry.conflicts.length})` : ""}` },
              { key: "timeline" as const, label: `📅 时间线${registry?.timeline.length ? ` (${registry.timeline.length})` : ""}` },
            ].map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`px-4 py-2 text-sm font-medium border-b-2 transition
                  ${
                    activeTab === tab.key
                      ? "border-blue-500 text-blue-600"
                      : "border-transparent text-gray-500 hover:text-gray-700"
                  }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {loading && (
            <div className="text-center py-12 text-gray-400">
              <div className="text-3xl mb-2 animate-spin">⏳</div>
              <p>加载中...</p>
            </div>
          )}

          {!loading && registry && activeTab === "list" && (
            <EvidenceList
              items={registry.items}
              onDelete={handleDelete}
              onImportToTrial={handleImportToTrial}
              importing={importing}
            />
          )}

          {!loading && registry && activeTab === "conflicts" && (
            <ConflictPanel
              conflicts={registry.conflicts}
              evidenceItems={registry.items}
            />
          )}

          {!loading && registry && activeTab === "timeline" && (
            <TimelineView timeline={registry.timeline} items={registry.items} />
          )}
        </div>
      </div>
    </div>
  );
}

// ============================================================
// 时间线子组件
// ============================================================

function TimelineView({
  timeline,
  items,
}: {
  timeline: EvidenceRegistry["timeline"];
  items: EvidenceRegistry["items"];
}) {
  if (timeline.length === 0) {
    return (
      <div className="text-center py-12 text-gray-400">
        <div className="text-3xl mb-2">📅</div>
        <p>暂无时间线数据</p>
        <p className="text-xs mt-1">上传证据并点击"AI 分析"自动生成</p>
      </div>
    );
  }

  const getEvidenceName = (evidenceId: string) => {
    const item = items.find((it) => it.id === evidenceId);
    return item ? item.source_file : evidenceId;
  };

  const eventTypeIcon: Record<string, string> = {
    contract: "📝",
    breach: "💥",
    action: "⚡",
    deadline: "⏰",
    fact: "📌",
    evidence: "📄",
  };

  return (
    <div className="relative pl-6">
      <div className="absolute left-2 top-0 bottom-0 w-0.5 bg-gray-200"></div>
      {timeline.map((event, idx) => (
        <div key={idx} className="relative mb-6">
          <div className="absolute -left-4 top-1 w-2.5 h-2.5 rounded-full bg-blue-500 ring-4 ring-white"></div>
          <div className="bg-white border rounded-lg p-4 shadow-sm">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-lg">{eventTypeIcon[event.event_type] || "📌"}</span>
              <span className="font-semibold text-gray-800">{event.label}</span>
            </div>
            <div className="flex items-center gap-3 text-xs text-gray-500">
              <span>📅 {event.date}</span>
              {event.party && <span>👤 {event.party}</span>}
            </div>
            {event.evidence_ids.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {event.evidence_ids.map((eid) => (
                  <span
                    key={eid}
                    className="text-xs bg-blue-50 text-blue-600 px-2 py-0.5 rounded"
                  >
                    {getEvidenceName(eid)}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
