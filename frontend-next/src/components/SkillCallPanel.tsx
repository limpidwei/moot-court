"use client";

import { useState } from "react";

interface SkillCall {
  id: string;
  agent: string;
  skill: string;
  description: string;
  inputPreview: string;
  outputPreview?: string;
  durationMs?: number;
  status: "running" | "done" | "error";
}

interface SkillCallPanelProps {
  calls: SkillCall[];
}

const AGENT_ICONS: Record<string, string> = {
  plaintiff: "⚔️",
  defendant: "🛡️",
  judge: "⚖️",
};

const AGENT_LABELS: Record<string, string> = {
  plaintiff: "原告律师",
  defendant: "被告律师",
  judge: "法官",
};

const SKILL_ICONS: Record<string, string> = {
  legal_research: "📚",
  drafting: "📝",
  evidence_analysis: "🔍",
  cross_exam: "❓",
  moderation: "📋",
  adjudication: "🏛️",
};

function SkillCallCard({ call }: { call: SkillCall }) {
  const [expanded, setExpanded] = useState(call.status === "running");

  const isRunning = call.status === "running";
  const agentIcon = AGENT_ICONS[call.agent] || "🤖";
  const agentLabel = AGENT_LABELS[call.agent] || call.agent;
  const skillIcon = SKILL_ICONS[call.skill] || "🔧";

  return (
    <div
      className={`border rounded-lg text-sm transition-all ${
        isRunning
          ? "border-blue-300 bg-blue-50/60"
          : "border-gray-200 bg-gray-50/60"
      }`}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left"
      >
        {isRunning ? (
          <span className="inline-block w-3.5 h-3.5 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
        ) : (
          <span className="text-green-500 text-xs">✓</span>
        )}
        <span>{agentIcon}</span>
        <span className="font-medium text-gray-700 truncate">
          {agentLabel}
        </span>
        <span className="text-gray-400">·</span>
        <span className="text-gray-600 truncate">
          {skillIcon} {call.description}
        </span>
        {call.durationMs !== undefined && (
          <span className="ml-auto text-xs text-gray-400 whitespace-nowrap">
            {call.durationMs}ms
          </span>
        )}
        <span className="text-gray-400 ml-1">{expanded ? "▼" : "▶"}</span>
      </button>

      {expanded && (
        <div className="px-3 pb-3 space-y-2 border-t border-gray-100 pt-2">
          {call.inputPreview && (
            <div>
              <div className="text-xs text-gray-400 mb-0.5">输入</div>
              <div className="text-xs text-gray-600 bg-white rounded px-2 py-1.5 border border-gray-100">
                {call.inputPreview}
              </div>
            </div>
          )}
          {call.outputPreview && (
            <div>
              <div className="text-xs text-gray-400 mb-0.5">输出</div>
              <div className="text-xs text-gray-600 bg-white rounded px-2 py-1.5 border border-gray-100 max-h-24 overflow-y-auto">
                {call.outputPreview}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function SkillCallPanel({ calls }: SkillCallPanelProps) {
  if (calls.length === 0) return null;

  const runningCount = calls.filter((c) => c.status === "running").length;
  const doneCount = calls.filter((c) => c.status === "done").length;

  return (
    <div className="mb-4">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-sm font-semibold text-gray-700">🔧 Agent 技能调用</span>
        {runningCount > 0 && (
          <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">
            进行中 {runningCount}
          </span>
        )}
        {doneCount > 0 && (
          <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">
            已完成 {doneCount}
          </span>
        )}
      </div>
      <div className="space-y-1.5 max-h-64 overflow-y-auto">
        {calls.map((call) => (
          <SkillCallCard key={call.id} call={call} />
        ))}
      </div>
    </div>
  );
}
