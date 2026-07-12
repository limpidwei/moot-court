"use client";

import { useState } from "react";
import type { ConflictReport, EvidenceItem } from "@/lib/types";

interface ConflictPanelProps {
  conflicts: ConflictReport[];
  evidenceItems: EvidenceItem[];
}

const CONFLICT_TYPE_LABEL: Record<string, string> = {
  temporal: "⏰ 时间冲突",
  factual: "❗ 事实冲突",
  quantitative: "📊 数量冲突",
  party: "👥 当事人冲突",
  stance: "⚔️ 立场冲突",
};

const SEVERITY_STYLE: Record<string, string> = {
  high: "border-red-300 bg-red-50",
  medium: "border-orange-300 bg-orange-50",
  low: "border-yellow-300 bg-yellow-50",
};

export default function ConflictPanel({ conflicts, evidenceItems }: ConflictPanelProps) {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  if (conflicts.length === 0) {
    return (
      <div className="text-center py-8 text-gray-400">
        <div className="text-3xl mb-2">✅</div>
        <p className="text-sm">暂未发现证据冲突</p>
        <p className="text-xs mt-1">点击"AI 分析"按钮检测矛盾</p>
      </div>
    );
  }

  const toggleExpand = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const getEvidenceName = (evidenceId: string) => {
    const item = evidenceItems.find((it) => it.id === evidenceId);
    return item ? item.source_file : evidenceId;
  };

  const getPartyLabel = (party: string) => {
    const map: Record<string, string> = {
      plaintiff: "原告",
      defendant: "被告",
      third_party: "第三方",
      unknown: "未知",
    };
    return map[party] || party;
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-gray-800">
          ⚠️ 证据冲突 ({conflicts.length})
        </h3>
        <span className="text-xs text-gray-500">
          系统不做真假判断，仅呈现矛盾供参考
        </span>
      </div>

      {conflicts.map((conflict) => {
        const isExpanded = expandedIds.has(conflict.id);
        const style = SEVERITY_STYLE[conflict.severity] || SEVERITY_STYLE.medium;

        return (
          <div
            key={conflict.id}
            className={`border rounded-xl p-4 ${style} transition-shadow hover:shadow-sm`}
          >
            <div className="flex items-start gap-3">
              <div className="text-xl shrink-0">
                {conflict.severity === "high" ? "🔴" : conflict.severity === "medium" ? "🟠" : "🟡"}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs font-medium px-2 py-0.5 rounded bg-white/80">
                    {CONFLICT_TYPE_LABEL[conflict.conflict_type] || conflict.conflict_type}
                  </span>
                  <span className="text-xs text-gray-500">
                    涉及 {conflict.involved_evidence_ids.length} 条证据
                  </span>
                </div>
                <p className="font-medium text-gray-800 mt-1">{conflict.description}</p>

                {isExpanded && (
                  <div className="mt-3 space-y-3 text-sm">
                    {/* 各方主张 */}
                    <div className="bg-white/70 rounded-lg p-3 space-y-2">
                      <p className="font-medium text-gray-700">各方主张:</p>
                      {conflict.claims.map((claim, idx) => (
                        <div key={idx} className="pl-3 border-l-2 border-gray-300">
                          <div className="flex items-center gap-2 text-xs text-gray-500">
                            <span className="font-medium">{getEvidenceName(claim.evidence_id)}</span>
                            <span>({getPartyLabel(claim.party)})</span>
                          </div>
                          <p className="text-gray-700 mt-0.5">{claim.extracted_claim}</p>
                          {claim.original_text && (
                            <p className="text-xs text-gray-400 mt-0.5 line-clamp-2">
                              原文: {claim.original_text}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>

                    {/* AI 备注 */}
                    {conflict.ai_note && (
                      <div className="bg-blue-50/50 rounded-lg p-3">
                        <p className="text-xs font-medium text-blue-700 mb-1">🤖 AI 分析备注</p>
                        <p className="text-gray-600 text-xs">{conflict.ai_note}</p>
                      </div>
                    )}
                  </div>
                )}

                <button
                  onClick={() => toggleExpand(conflict.id)}
                  className="text-xs text-blue-600 hover:underline mt-2"
                >
                  {isExpanded ? "收起" : "查看详情"}
                </button>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
