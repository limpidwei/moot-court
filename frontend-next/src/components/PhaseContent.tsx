"use client";

// 可折叠的阶段内容展示组件

import { useState } from "react";

export default function PhaseContent({
  phase,
  label,
  content,
  defaultExpanded = false,
  isCurrent = false,
  onConfirm,
  needsConfirm = false,
  confirmed = false,
  onEdit,
}: {
  phase: number;
  label: string;
  content: string | object;
  defaultExpanded?: boolean;
  isCurrent?: boolean;
  onConfirm?: () => void;
  needsConfirm?: boolean;
  confirmed?: boolean;
  onEdit?: (content: string) => void;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState("");

  const contentStr =
    typeof content === "string" ? content : JSON.stringify(content, null, 2);

  return (
    <div
      className={`border rounded-lg mb-3 overflow-hidden ${
        isCurrent ? "border-blue-400 ring-1 ring-blue-200" : "border-gray-200"
      }`}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 text-left"
      >
        <div className="flex items-center gap-2">
          <span
            className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold
              ${confirmed ? "bg-green-500 text-white" : "bg-blue-500 text-white"}
            `}
          >
            {confirmed ? "✓" : phase}
          </span>
          <span className="font-semibold text-gray-800">{label}</span>
          {isCurrent && (
            <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">
              进行中
            </span>
          )}
          {confirmed && (
            <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">
              已确认
            </span>
          )}
        </div>
        <span className="text-gray-400">{expanded ? "▲" : "▼"}</span>
      </button>

      {expanded && (
        <div className="p-4 bg-white">
          {editing ? (
            <div>
              <textarea
                className="w-full h-64 p-3 border rounded font-mono text-sm"
                value={editText}
                onChange={(e) => setEditText(e.target.value)}
              />
              <div className="flex gap-2 mt-2">
                <button
                  onClick={() => {
                    onEdit?.(editText);
                    setEditing(false);
                  }}
                  className="bg-blue-600 text-white px-4 py-2 rounded text-sm"
                >
                  保存修改
                </button>
                <button
                  onClick={() => setEditing(false)}
                  className="bg-gray-200 px-4 py-2 rounded text-sm"
                >
                  取消
                </button>
              </div>
            </div>
          ) : (
            <div>
              <div className="prose prose-sm max-w-none whitespace-pre-wrap text-gray-700">
                {contentStr}
              </div>
              <div className="flex gap-2 mt-4">
                {needsConfirm && !confirmed && onConfirm && (
                  <button
                    onClick={onConfirm}
                    className="bg-green-600 text-white px-6 py-2 rounded-lg text-sm font-semibold"
                  >
                    确认并继续
                  </button>
                )}
                {onEdit && (
                  <button
                    onClick={() => {
                      setEditText(contentStr);
                      setEditing(true);
                    }}
                    className="bg-gray-100 text-gray-600 px-4 py-2 rounded-lg text-sm"
                  >
                    编辑
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
