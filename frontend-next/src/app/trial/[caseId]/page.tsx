"use client";

// 庭审控制台 — 核心页面
// 8 阶段分步执行，支持确认/编辑/代理模式

import { useState, useEffect, useCallback, useRef } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";
import { startTrial, continueTrial, getTrialState, exportReport } from "@/lib/api";
import type { TrialState, TrialPhase, CrossExamMessage } from "@/lib/types";
import ProgressBar from "@/components/ProgressBar";
import PhaseContent from "@/components/PhaseContent";
import ChatBubble from "@/components/ChatBubble";
import JudgeQA from "@/components/JudgeQA";

export default function TrialPage() {
  const params = useParams<{ caseId: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const caseId = params.caseId;
  const userRole = searchParams.get("role") || "neutral";

  const [state, setState] = useState<TrialState | null>(null);
  const [phases, setPhases] = useState<TrialPhase[]>([]);
  const [loading, setLoading] = useState(true);
  const [continuing, setContinuing] = useState(false);
  const [error, setError] = useState("");
  const [exportMd, setExportMd] = useState("");
  const [showExport, setShowExport] = useState(false);

  const loadedRef = useRef(false);

  // 解析交叉询问 JSON
  const parseCrossExam = (phase6Content: string): CrossExamMessage[] => {
    try {
      const data = JSON.parse(phase6Content);
      return data.cross_exam ? JSON.parse(data.cross_exam) : [];
    } catch {
      try {
        return JSON.parse(phase6Content);
      } catch {
        return [];
      }
    }
  };

  // 解析 Phase 6 子内容
  const parsePhase6 = (content: string) => {
    try {
      const data = JSON.parse(content);
      return {
        crossExam: data.cross_exam || "",
        evidenceExam: data.evidence_exam || "",
      };
    } catch {
      return { crossExam: "", evidenceExam: content };
    }
  };

  // 启动庭审
  const handleStart = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await startTrial(caseId, userRole);
      setPhases(res.phases || []);
      setState({
        case_id: caseId,
        current_phase: res.current_phase || 0,
        user_role: userRole as "plaintiff" | "defendant" | "neutral",
        phase1_confirmed: false,
        phase2_confirmed: false,
        phase3_confirmed: false,
        phase4_confirmed: false,
        phase_labels: {},
        win_rate: 0,
      });
    } catch {
      setError("启动庭审失败，请检查后端是否运行");
    }
    setLoading(false);
  }, [caseId, userRole]);

  // 确认并继续
  const handleConfirm = async (phase: number, editedContent?: string) => {
    setContinuing(true);
    setError("");
    try {
      const res = await continueTrial(caseId, phase, editedContent);
      const newPhases = [...phases];
      // 追加新阶段
      for (const p of res.phases || []) {
        const existing = newPhases.findIndex((ep) => ep.phase === p.phase);
        if (existing >= 0) {
          newPhases[existing] = p;
        } else {
          newPhases.push(p);
        }
      }
      setPhases(newPhases);
      setState((prev) =>
        prev
          ? {
              ...prev,
              current_phase: res.current_phase,
              [`phase${phase}_confirmed` as keyof TrialState]: true as never,
            }
          : prev
      );
    } catch {
      setError("继续庭审失败");
    }
    setContinuing(false);
  };

  // 初始加载
  useEffect(() => {
    if (loadedRef.current) return;
    loadedRef.current = true;
    handleStart();
  }, [handleStart]);

  // 导出
  const handleExport = async () => {
    try {
      const res = await exportReport(caseId);
      setExportMd(res.content);
      setShowExport(true);
    } catch {
      alert("导出失败");
    }
  };

  const handleCopyExport = () => {
    navigator.clipboard.writeText(exportMd);
    alert("已复制到剪贴板");
  };

  // Phase 6 的特殊处理
  const phase6Data = (() => {
    const p6 = phases.find((p) => p.phase === 6);
    if (!p6) return null;
    return parsePhase6(typeof p6.content === "string" ? p6.content : "");
  })();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <div className="text-4xl mb-4">⚖️</div>
          <p className="text-gray-600">正在启动庭审...</p>
          <p className="text-sm text-gray-400 mt-2">
            Phase 1 原告律师分析中，请稍候（约 30-60 秒）
          </p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-600 text-lg mb-4">{error}</p>
          <button
            onClick={handleStart}
            className="bg-blue-600 text-white px-6 py-2 rounded-lg"
          >
            重试
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto p-6">
      {/* 顶部 */}
      <div className="flex items-center justify-between mb-6">
        <button
          onClick={() => router.push("/")}
          className="text-blue-600 text-sm hover:underline"
        >
          ← 返回首页
        </button>
        <div className="flex gap-2">
          {state?.current_phase === 8 && (
            <>
              <button
                onClick={handleExport}
                className="bg-purple-600 text-white px-4 py-2 rounded-lg text-sm"
              >
                📥 导出报告
              </button>
              <button
                onClick={() => router.push("/case/new")}
                className="bg-green-600 text-white px-4 py-2 rounded-lg text-sm"
              >
                🔄 新建庭审
              </button>
            </>
          )}
        </div>
      </div>

      <h1 className="text-2xl font-bold text-gray-800 mb-2">⚖️ 庭审控制台</h1>
      <p className="text-sm text-gray-500 mb-6">
        案件编号：{caseId} · 代理模式：
        {userRole === "plaintiff"
          ? "代理原告"
          : userRole === "defendant"
          ? "代理被告"
          : "中立观察"}
      </p>

      {/* 进度条 */}
      <ProgressBar
        currentPhase={state?.current_phase || 0}
        phaseLabels={state?.phase_labels || {}}
      />

      {/* 阶段列表 */}
      <div className="mt-6 space-y-2">
        {phases.map((p) => {
          // Phase 6 特殊处理
          if (p.phase === 6 && phase6Data) {
            const crossMessages = parseCrossExam(phase6Data.crossExam);
            return (
              <div key={6}>
                <PhaseContent
                  phase={6}
                  label={p.label}
                  content={
                    crossMessages.length > 0
                      ? "交叉询问（见下方对话展示）"
                      : "加载中..."
                  }
                  isCurrent={state?.current_phase === 6}
                  confirmed={
                    (state?.current_phase || 0) > 6
                  }
                />
                {crossMessages.length > 0 && (
                  <div className="border rounded-lg p-4 mb-3 bg-gray-50">
                    <h3 className="font-semibold text-gray-700 mb-3">
                      💬 交叉询问对话
                    </h3>
                    <ChatBubble messages={crossMessages} />
                  </div>
                )}
                {phase6Data.evidenceExam && (
                  <PhaseContent
                    phase={6}
                    label="举证质证"
                    content={phase6Data.evidenceExam}
                    isCurrent={state?.current_phase === 6}
                    confirmed={(state?.current_phase || 0) > 6}
                  />
                )}
              </div>
            );
          }

          // 其他阶段
          const isCurrent = p.phase === state?.current_phase;
          const phaseConfirmed =
            p.phase === 1
              ? state?.phase1_confirmed
              : p.phase === 2
              ? state?.phase2_confirmed
              : p.phase === 3
              ? state?.phase3_confirmed
              : p.phase === 4
              ? state?.phase4_confirmed
              : false;

          return (
            <PhaseContent
              key={p.phase}
              phase={p.phase}
              label={p.label}
              content={p.content}
              defaultExpanded={p.phase === state?.current_phase}
              isCurrent={isCurrent}
              needsConfirm={p.needs_confirm && !phaseConfirmed}
              confirmed={phaseConfirmed}
              onConfirm={() => handleConfirm(p.phase)}
              onEdit={(edited) => handleConfirm(p.phase, edited)}
            />
          );
        })}

        {/* 持续加载 */}
        {continuing && (
          <div className="text-center py-8 text-gray-500">
            <div className="animate-pulse text-lg">庭审进行中...</div>
            <div className="text-sm mt-1">AI 正在生成下一阶段内容</div>
          </div>
        )}
      </div>

      {/* 导出弹窗 */}
      {showExport && exportMd && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl p-6 max-w-2xl w-full max-h-[80vh] overflow-auto">
            <h2 className="text-xl font-bold mb-4">📥 庭审报告</h2>
            <pre className="text-xs bg-gray-50 p-4 rounded-lg whitespace-pre-wrap max-h-96 overflow-auto">
              {exportMd}
            </pre>
            <div className="flex gap-3 mt-4">
              <button
                onClick={handleCopyExport}
                className="bg-blue-600 text-white px-5 py-2 rounded-lg text-sm"
              >
                📋 复制全文
              </button>
              <button
                onClick={() => setShowExport(false)}
                className="bg-gray-200 px-5 py-2 rounded-lg text-sm"
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 庭后法官问答 */}
      {state?.current_phase === 8 && <JudgeQA caseId={caseId} />}
    </div>
  );
}
