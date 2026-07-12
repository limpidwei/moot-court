"use client";

// 可折叠的阶段内容展示组件（支持 Markdown 渲染）

import { useState, useEffect, ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface FinalStatements {
  plaintiff_final?: string;
  defendant_final?: string;
}

export default function PhaseContent({
  phase,
  label,
  content,
  children,
  defaultExpanded = false,
  isCurrent = false,
  confirmed = false,
  onEdit,
  highlighted = false,
}: {
  phase: number;
  label: string;
  content?: string | object;
  children?: ReactNode;
  defaultExpanded?: boolean;
  isCurrent?: boolean;
  confirmed?: boolean;
  onEdit?: (content: string) => void;
  highlighted?: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded || highlighted);
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState("");

  useEffect(() => {
    if (highlighted) {
      setExpanded(true);
    }
  }, [highlighted]);

  const contentStr =
    typeof content === "string" ? content : JSON.stringify(content, null, 2);

  return (
    <div
      ref={(el) => {
        if (highlighted && el) {
          el.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      }}
      className={`border rounded-lg mb-3 overflow-hidden transition ${
        highlighted
          ? "border-yellow-400 ring-2 ring-yellow-200 shadow-lg"
          : isCurrent
          ? "border-blue-400 ring-1 ring-blue-200"
          : "border-gray-200"
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
              <div className="prose prose-sm max-w-none text-gray-700">
                {children ? (
                  children
                ) : phase === 7 && content && typeof content === "object" ? (
                  (content as FinalStatements).plaintiff_final || (content as FinalStatements).defendant_final ? (
                    <div className="space-y-4">
                      {(content as FinalStatements).plaintiff_final && (
                        <div>
                          <h4 className="text-sm font-semibold text-gray-700 mb-1">原告最后陈述</h4>
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {(content as FinalStatements).plaintiff_final}
                          </ReactMarkdown>
                        </div>
                      )}
                      {(content as FinalStatements).defendant_final && (
                        <div>
                          <h4 className="text-sm font-semibold text-gray-700 mb-1">被告最后陈述</h4>
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {(content as FinalStatements).defendant_final}
                          </ReactMarkdown>
                        </div>
                      )}
                    </div>
                  ) : (
                    <span className="text-gray-400 italic">暂无内容</span>
                  )
                ) : typeof content === "string" && content ? (
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {content}
                  </ReactMarkdown>
                ) : typeof content === "string" ? (
                  <span className="text-gray-400 italic">暂无内容</span>
                ) : (
                  <div className="text-sm text-gray-500 italic">
                    该阶段包含结构化数据，已在上方面板展示
                  </div>
                )}
              </div>
              <div className="flex gap-2 mt-4">
                {onEdit && (
                  <button
                    onClick={() => {
                      setEditText(contentStr);
                      setEditing(true);
                    }}
                    className="bg-gray-100 text-gray-600 px-4 py-2 rounded-lg text-sm hover:bg-gray-200 transition"
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
