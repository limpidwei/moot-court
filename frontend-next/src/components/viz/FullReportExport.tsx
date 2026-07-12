"use client";

// 完整报告导出 — 调用后端生成高质量 PDF
// 后端使用 reportlab + matplotlib 生成，支持中文字体和矢量图表

import { useState, useRef, useEffect } from "react";
import { getAuthHeaders } from "@/lib/auth";
import { API_BASE } from "@/lib/api";

interface Props {
  caseId: string;
  caseTitle?: string;
  currentPhase: number;
  phases?: any[];
  className?: string;
}

export default function FullReportExport({
  caseId,
  caseTitle = "模拟庭审",
  currentPhase,
  className = "",
}: Props) {
  const [exporting, setExporting] = useState(false);
  const [progress, setProgress] = useState("");
  // P4 修复：组件卸载后 setTimeout 仍会 setState（React warning + 内存泄漏）。
  // 用 ref 跟踪挂载状态，fetch 加 AbortController，卸载时 abort。
  const mountedRef = useRef(true);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
      abortRef.current?.abort();
    };
  }, []);

  const handleExport = async () => {
    if (exporting) return;

    setExporting(true);
    setProgress("正在生成 PDF 报告...");

    // 创建新的 AbortController（每次导出独立）
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const response = await fetch(`${API_BASE}/trial/export-pdf/${caseId}`, {
        headers: getAuthHeaders(),
        signal: controller.signal,
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`HTTP ${response.status}: ${errorText}`);
      }

      const blob = await response.blob();

      if (!mountedRef.current) return;

      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      const safeTitle = caseTitle.replace(/[<>:"/\\|?*]/g, "_").slice(0, 30);
      link.download = `模拟法庭报告_${safeTitle}_${caseId}.pdf`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);

      setProgress("导出成功！");
      setTimeout(() => {
        if (mountedRef.current) { setProgress(""); setExporting(false); }
      }, 1500);
    } catch (error) {
      if (!mountedRef.current) return;
      console.error("PDF export failed:", error);
      setProgress(`导出失败: ${error instanceof Error ? error.message : "未知错误"}`);
      setTimeout(() => {
        if (mountedRef.current) { setProgress(""); setExporting(false); }
      }, 3000);
    }
  };

  return (
    <>
      <button
        onClick={handleExport}
        disabled={exporting || currentPhase < 1}
        className={`px-4 py-2 rounded-lg text-sm font-semibold transition ${
          exporting
            ? "bg-gray-300 text-gray-500 cursor-not-allowed"
            : "bg-purple-600 text-white hover:bg-purple-700"
        } ${className}`}
      >
        {exporting ? "生成中..." : "📥 导出完整报告"}
      </button>

      {/* 进度提示 */}
      {progress && (
        <div className="fixed top-4 right-4 bg-white rounded-lg shadow-lg p-4 z-50 max-w-sm">
          <div className="flex items-center gap-3">
            {exporting && (
              <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-purple-600"></div>
            )}
            <p className={`text-sm ${
              progress.includes("成功") ? "text-green-600" :
              progress.includes("失败") ? "text-red-600" :
              "text-gray-700"
            }`}>
              {progress}
            </p>
          </div>
        </div>
      )}
    </>
  );
}
