"use client";

import { useState } from "react";
import type { EvidenceItem } from "@/lib/types";

interface EvidenceListProps {
  items: EvidenceItem[];
  onDelete: (evidenceId: string) => Promise<void>;
  onImportToTrial: () => Promise<void>;
  importing: boolean;
}

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  pending: { label: "待分析", color: "bg-yellow-100 text-yellow-700" },
  extracting: { label: "提取中", color: "bg-blue-100 text-blue-700" },
  analyzing: { label: "分析中", color: "bg-purple-100 text-purple-700" },
  completed: { label: "已完成", color: "bg-green-100 text-green-700" },
  failed: { label: "失败", color: "bg-red-100 text-red-700" },
};

const SOURCE_ICON: Record<string, string> = {
  text: "📄",
  docx: "📝",
  pdf: "📑",
  image: "🖼️",
  audio: "🎵",
  contract: "📋",
};

export default function EvidenceList({ items, onDelete, onImportToTrial, importing }: EvidenceListProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const handleDelete = async (id: string) => {
    if (!confirm("确定删除此证据？此操作不可撤销。")) return;
    setDeletingId(id);
    await onDelete(id);
    setDeletingId(null);
  };

  if (items.length === 0) {
    return (
      <div className="text-center py-12 text-gray-400">
        <div className="text-4xl mb-2">📭</div>
        <p>暂无证据，请先上传</p>
      </div>
    );
  }

  const completedCount = items.filter((it) => it.status === "completed").length;

  return (
    <div className="space-y-4">
      {/* 统计栏 */}
      <div className="flex items-center justify-between">
        <div className="text-sm text-gray-600">
          共 {items.length} 条证据
          {completedCount > 0 && (
            <span className="ml-2 text-green-600">({completedCount} 条已分析)</span>
          )}
        </div>
        {completedCount > 0 && (
          <button
            onClick={onImportToTrial}
            disabled={importing}
            className="bg-green-600 text-white px-4 py-2 rounded-lg text-sm font-semibold
                       disabled:opacity-50 hover:bg-green-700 transition"
          >
            {importing ? "导入中..." : "📥 导入庭审系统"}
          </button>
        )}
      </div>

      {/* 证据卡片列表 */}
      {items.map((item) => {
        const status = STATUS_MAP[item.status] || STATUS_MAP.pending;
        const isExpanded = expandedId === item.id;

        return (
          <div
            key={item.id}
            className={`bg-white border rounded-xl p-4 transition-shadow ${
              isExpanded ? "shadow-md" : "shadow-sm hover:shadow-md"
            }`}
          >
            <div className="flex items-start gap-3">
              <div className="text-2xl shrink-0">
                {SOURCE_ICON[item.source_type] || "📄"}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <h4 className="font-semibold text-gray-800 truncate">
                    {item.source_file}
                  </h4>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${status.color}`}>
                    {status.label}
                  </span>
                  {item.party !== "unknown" && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">
                      {item.party === "plaintiff" ? "原告" : item.party === "defendant" ? "被告" : "第三方"}
                    </span>
                  )}
                  {item.evidence_type && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-600">
                      {item.evidence_type}
                    </span>
                  )}
                </div>

                {/* 摘要行 */}
                {item.summary && (
                  <p className="text-sm text-gray-600 mt-1 line-clamp-2">{item.summary}</p>
                )}

                {/* 元数据 */}
                <div className="flex items-center gap-3 mt-2 text-xs text-gray-400">
                  {item.date && <span>📅 {item.date}</span>}
                  {item.parties.length > 0 && <span>👤 {item.parties.join(", ")}</span>}
                  {item.file_size > 0 && (
                    <span>{(item.file_size / 1024).toFixed(1)} KB</span>
                  )}
                  {item.confidence < 1.0 && (
                    <span>置信度: {(item.confidence * 100).toFixed(0)}%</span>
                  )}
                </div>

                {/* 展开内容 */}
                {isExpanded && (
                  <div className="mt-3 pt-3 border-t text-sm space-y-2">
                    {item.content && (
                      <div>
                        <p className="font-medium text-gray-700 mb-1">提取内容:</p>
                        <div className="bg-gray-50 p-3 rounded-lg max-h-48 overflow-y-auto whitespace-pre-wrap text-gray-600">
                          {item.content}
                        </div>
                      </div>
                    )}
                    {item.relevance.length > 0 && (
                      <div>
                        <p className="font-medium text-gray-700 mb-1">关联争议焦点:</p>
                        <div className="flex flex-wrap gap-2">
                          {item.relevance.map((r, i) => (
                            <span key={i} className="bg-blue-50 text-blue-600 px-2 py-1 rounded text-xs">
                              {r}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                    {item.error_message && (
                      <p className="text-red-600">错误: {item.error_message}</p>
                    )}
                  </div>
                )}

                {/* 操作按钮 */}
                <div className="flex items-center gap-3 mt-3">
                  <button
                    onClick={() => setExpandedId(isExpanded ? null : item.id)}
                    className="text-xs text-blue-600 hover:underline"
                  >
                    {isExpanded ? "收起" : "查看详情"}
                  </button>
                  <button
                    onClick={() => handleDelete(item.id)}
                    disabled={deletingId === item.id}
                    className="text-xs text-red-500 hover:underline disabled:opacity-50"
                  >
                    {deletingId === item.id ? "删除中..." : "删除"}
                  </button>
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
