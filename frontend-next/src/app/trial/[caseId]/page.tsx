"use client";

// 庭审控制台 — 核心页面
// 8 阶段分步执行，支持确认/编辑/代理模式

import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";
import {
  connectTrialStream,
  getTrialHistory,
  resetTrial,
  getTrialState,
  selectStrategy,
} from "@/lib/api";
import type { TrialState, TrialPhase, CrossExamMessage } from "@/lib/types";
import ProgressBar from "@/components/ProgressBar";
import PhaseContent from "@/components/PhaseContent";
import ChatBubble from "@/components/ChatBubble";
import JudgeQA from "@/components/JudgeQA";
import FullReportExport from "@/components/viz/FullReportExport";
import SkillCallPanel from "@/components/SkillCallPanel";

// 解析交叉询问 JSON（支持 string 或 object）
function parseCrossExam(phase6Content: string | object): CrossExamMessage[] {
  try {
    const data = typeof phase6Content === "string" ? JSON.parse(phase6Content) : phase6Content;
    if (data.cross_exam) {
      const cross = typeof data.cross_exam === "string" ? JSON.parse(data.cross_exam) : data.cross_exam;
      return Array.isArray(cross) ? cross : [];
    }
    return Array.isArray(data) ? data : [];
  } catch {
    try {
      return typeof phase6Content === "string" ? JSON.parse(phase6Content) : [];
    } catch {
      return [];
    }
  }
}

// 解析 Phase 6 子内容（支持 string 或 object）
function parsePhase6(content: string | object) {
  try {
    const data = typeof content === "string" ? JSON.parse(content) : content;
    return {
      crossExam: typeof data.cross_exam === "string" ? data.cross_exam : JSON.stringify(data.cross_exam || ""),
      evidenceExam: typeof data.evidence_exam === "string" ? data.evidence_exam : JSON.stringify(data.evidence_exam || ""),
    };
  } catch {
    return { crossExam: typeof content === "string" ? content : "", evidenceExam: "" };
  }
}

// 解析举证质证 JSON
function parseEvidenceExam(phase6Content: string | object) {
  try {
    const data = typeof phase6Content === "string" ? JSON.parse(phase6Content) : phase6Content;
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

export default function TrialPage() {
  const params = useParams<{ caseId: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const caseId = params.caseId;
  const [userRole, setUserRole] = useState<"plaintiff" | "defendant" | "neutral">(
    (searchParams.get("role") as "plaintiff" | "defendant" | "neutral") || "neutral"
  );
  const [mode, setMode] = useState<"neutral" | "asymmetric">("neutral");

  const [state, setState] = useState<TrialState | null>(null);
  const [phases, setPhases] = useState<TrialPhase[]>([]);
  const [started, setStarted] = useState(false);
  const [continuing, setContinuing] = useState(false);
  const [error, setError] = useState("");
  const [currentPhaseLabel, setCurrentPhaseLabel] = useState("Phase 1");
  const [history, setHistory] = useState<
    { phase: number; label: string; timestamp: string; preview: string }[]
  >([]);
  const [showHistory, setShowHistory] = useState(false);
  const [streamingPhase, setStreamingPhase] = useState(0);
  const [streamingContent, setStreamingContent] = useState("");

  const [streamPhase6Msgs, setStreamPhase6Msgs] = useState<
    { round?: number; item?: number; speaker: string; msg_type: string; content: string }[]
  >([]);
  const [streamEvidenceMsgs, setStreamEvidenceMsgs] = useState<
    { round?: number; item?: number; speaker: string; msg_type: string; content: string }[]
  >([]);
  const [skillCalls, setSkillCalls] = useState<
    {
      id: string;
      agent: string;
      skill: string;
      description: string;
      inputPreview: string;
      outputPreview?: string;
      durationMs?: number;
      status: "running" | "done" | "error";
    }[]
  >([]);

  const [awaitingStrategySelection, setAwaitingStrategySelection] = useState<{
    phase: number;
    routes: any[];
  } | null>(null);

  // H9 修复：持有当前 SSE 流的 AbortController，便于卸载/重开时 abort，
  // 终止后端流式（停止烧 token）并阻止 abort 后的 setState 覆盖。
  const streamAbortRef = useRef<AbortController | null>(null);
  const abortStream = useCallback(() => {
    streamAbortRef.current?.abort();
    streamAbortRef.current = null;
  }, []);
  const startStream = useCallback(() => {
    // 启动新流前先终止旧流，避免并发多路 SSE 相互覆盖
    abortStream();
    const controller = new AbortController();
    streamAbortRef.current = controller;
    return controller.signal;
  }, [abortStream]);

  // 组件卸载时终止进行中的流
  useEffect(() => {
    return () => {
      streamAbortRef.current?.abort();
      streamAbortRef.current = null;
    };
  }, []);

  // 加载案件权威状态（获取 mode / user_role）
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await getTrialState(caseId);
        if (cancelled) return;
        if (data.mode === "asymmetric" && data.user_role) {
          setUserRole(data.user_role as "plaintiff" | "defendant" | "neutral");
        }
        if (data.mode) {
          setMode(data.mode as "neutral" | "asymmetric");
        }
        // 自动恢复已有庭审进度
        if (data.phases && data.phases.length > 0) {
          setPhases(data.phases);
        }
        if (data.current_phase > 0) {
          setStarted(true);
        }
        setState((prev) =>
          prev
            ? { ...prev, ...data }
            : {
                case_id: caseId,
                current_phase: data.current_phase || 0,
                user_role: data.user_role || "neutral",
                mode: data.mode,
                user_side: data.user_side,
                phase1_confirmed: data.phase1_confirmed || false,
                phase2_confirmed: data.phase2_confirmed || false,
                phase3_confirmed: data.phase3_confirmed || false,
                phase4_confirmed: data.phase4_confirmed || false,
                phase_labels: data.phase_labels || {},
                win_rate: data.win_rate || 0,
              }
        );
        // 恢复等待策略选择状态（优先使用后端直接返回的 strategy_routes）
        if (data.phase1_strategy_pending && data.phase1_strategy_routes?.length > 0) {
          setAwaitingStrategySelection({ phase: 1, routes: data.phase1_strategy_routes });
        } else if (data.phase3_strategy_pending && data.phase3_strategy_routes?.length > 0) {
          setAwaitingStrategySelection({ phase: 3, routes: data.phase3_strategy_routes });
        } else {
          setAwaitingStrategySelection(null);
        }
      } catch {
        // 静默失败，不影响已有流程
      }
    }
    load();
    return () => { cancelled = true; };
  }, [caseId]);

  // 启动庭审（SSE 流式）
  const handleStart = useCallback(async () => {
    setError("");
    setStarted(true);
    setStreamPhase6Msgs([]);
    setStreamEvidenceMsgs([]);
    setSkillCalls([]);
    setStreamingPhase(1);
    setStreamingContent("");
    setCurrentPhaseLabel("Phase 1：原告律师请求权基础分析");
    // Phase 1 文本框优先出现，避免全屏空白等待
    setPhases((prevPhases) => {
      const arr = [...prevPhases];
      const idx = arr.findIndex((p) => p.phase === 1);
      if (idx < 0) {
        arr.push({
          phase: 1,
          label: "Phase 1：原告律师请求权基础分析",
          content: "",
          needs_confirm: true,
        });
      }
      return arr;
    });

    try {
      await connectTrialStream(
        { case_id: caseId, action: "start", user_role: userRole },
        (event) => {
          if (event.type === "phase_start" || event.type === "agent_start" || event.type === "phase_progress") {
            if (event.phase) {
              setStreamingPhase(event.phase);
              if (event.type === "phase_start") {
                setPhases((prevPhases) => {
                  const arr = [...prevPhases];
                  const idx = arr.findIndex((p) => p.phase === event.phase);
                  if (idx < 0) {
                    arr.push({
                      phase: event.phase || 0,
                      label: (event.label as string) || `Phase ${event.phase || 0}`,
                      content: "",
                      needs_confirm: true,
                    });
                  }
                  return arr;
                });
              }
            }
            if (event.type !== "phase_progress") {
              setStreamingContent("");
            }
            if (event.label) {
              setCurrentPhaseLabel(`Phase ${event.phase}：${event.label}`);
            }
          } else if (event.type === "token") {
            // H11 修复：content 缺失时拼入字面 "undefined"，改为 ?? ""。
            const tokenChunk = event.content ?? "";
            setStreamingContent((prev) => {
              const next = prev + tokenChunk;
              // 同步更新 phases 预览（仅非 Phase 6）
              const sp = event.phase || streamingPhase;
              if (sp && sp !== 6) {
                setPhases((prevPhases) => {
                  const arr = [...prevPhases];
                  const idx = arr.findIndex((p) => p.phase === sp);
                  if (idx >= 0) {
                    arr[idx] = { ...arr[idx], content: next };
                  } else {
                    arr.push({
                      phase: sp,
                      label: `Phase ${sp}`,
                      content: next,
                      needs_confirm: true,
                    });
                  }
                  return arr;
                });
              }
              return next;
            });
          } else if (event.type === "agent_step") {
            if (event.round) {
              setStreamPhase6Msgs((prev) => [
                ...prev,
                {
                  round: event.round,
                  item: event.item,
                  speaker: event.speaker!,
                  msg_type: event.msg_type!,
                  content: event.content!,
                },
              ]);
            } else if (event.item) {
              setStreamEvidenceMsgs((prev) => [
                ...prev,
                {
                  round: event.round,
                  item: event.item,
                  speaker: event.speaker!,
                  msg_type: event.msg_type!,
                  content: event.content!,
                },
              ]);
            }
          } else if (event.type === "skill_start") {
            setSkillCalls((prev) => [
              ...prev,
              {
                id: `${event.agent}-${event.skill}-${Date.now()}`,
                agent: event.agent as string,
                skill: event.skill as string,
                description: event.description as string,
                inputPreview: event.input_preview as string,
                status: "running",
              },
            ]);
          } else if (event.type === "skill_end") {
            setSkillCalls((prev) => {
              const arr = [...prev];
              const idx = arr.findIndex(
                (s) => s.agent === event.agent && s.skill === event.skill && s.status === "running"
              );
              if (idx >= 0) {
                arr[idx] = {
                  ...arr[idx],
                  outputPreview: event.output_preview as string,
                  durationMs: event.duration_ms as number,
                  status: "done",
                };
              }
              return arr;
            });
          } else if (event.type === "awaiting_strategy_selection") {
            setAwaitingStrategySelection({
              phase: event.phase as number,
              routes: event.routes as any[],
            });
          } else if (event.type === "insights_ready") {
          } else if (event.type === "done") {
            setPhases((event.phases as TrialPhase[]) || []);
            setState((prev) => ({
              case_id: caseId,
              current_phase: (event.current_phase as number) || 0,
              user_role: userRole as "plaintiff" | "defendant" | "neutral",
              mode: prev?.mode,
              user_side: prev?.user_side,
              phase1_confirmed: false,
              phase2_confirmed: false,
              phase3_confirmed: false,
              phase4_confirmed: false,
              phase_labels: prev?.phase_labels || {},
              win_rate: prev?.win_rate || 0,
            }));
            setSkillCalls([]);
            // 恢复等待策略选择状态（从 done 事件）
            const awaiting = (event as any).awaiting_strategy_selection;
            if (awaiting) {
              setAwaitingStrategySelection(awaiting);
            } else {
              setAwaitingStrategySelection(null);
            }
          } else if (event.type === "error") {
            setError(event.message || "庭审流式输出出错");
          }
        },
        startStream()
      );
    } catch (err) {
      // H9：abort（卸载/重开）触发的 AbortError 不当作错误展示
      const isAbort = err instanceof DOMException && err.name === "AbortError";
      if (!isAbort) {
        setError(err instanceof Error ? err.message : "启动庭审失败，请检查后端是否运行或刷新页面重试");
      }
    } finally {
      abortStream();
    }
  }, [caseId, userRole, streamingPhase, startStream, abortStream]);

  // 确认并继续（SSE 流式）
  const handleConfirm = async (phase: number, editedContent?: string) => {
    setContinuing(true);
    setError("");
    setStreamingPhase(0);
    setStreamingContent("");
    setStreamEvidenceMsgs([]);
    setSkillCalls([]);
    const nextPhaseNum = phase + 1;
    const labels: Record<number, string> = {
      2: "Phase 2：原告律师起诉状与证据目录",
      3: "Phase 3：被告律师答辩策略分析",
      4: "Phase 4：被告律师答辩状与证据目录",
      5: "Phase 5：法官归纳争议焦点",
      6: "Phase 6：交叉询问与举证质证",
      7: "Phase 7：双方最后陈述",
      8: "Phase 8：法官判决与胜率评估",
    };
    setCurrentPhaseLabel(labels[nextPhaseNum] || `Phase ${nextPhaseNum}`);

    try {
      await connectTrialStream(
        {
          case_id: caseId,
          action: "continue",
          confirmed_phase: phase,
          edited_content: editedContent || "",
        },
        (event) => {
          if (event.type === "phase_start" || event.type === "agent_start" || event.type === "phase_progress") {
            if (event.phase) {
              setStreamingPhase(event.phase);
              if (event.type === "phase_start") {
                setPhases((prevPhases) => {
                  const arr = [...prevPhases];
                  const idx = arr.findIndex((p) => p.phase === event.phase);
                  if (idx < 0) {
                    arr.push({
                      phase: event.phase || 0,
                      label: (event.label as string) || `Phase ${event.phase || 0}`,
                      content: "",
                      needs_confirm: true,
                    });
                  }
                  return arr;
                });
              }
            }
            if (event.type !== "phase_progress") {
              setStreamingContent("");
            }
            if (event.label) {
              setCurrentPhaseLabel(`Phase ${event.phase}：${event.label}`);
            }
          } else if (event.type === "token") {
            // H11 修复：content 缺失时拼入字面 "undefined"，改为 ?? ""。
            const tokenChunk = event.content ?? "";
            setStreamingContent((prev) => {
              const next = prev + tokenChunk;
              const sp = event.phase || streamingPhase;
              if (sp && sp !== 6) {
                setPhases((prevPhases) => {
                  const arr = [...prevPhases];
                  const idx = arr.findIndex((p) => p.phase === sp);
                  if (idx >= 0) {
                    arr[idx] = { ...arr[idx], content: next };
                  } else {
                    arr.push({
                      phase: sp,
                      label: `Phase ${sp}`,
                      content: next,
                      needs_confirm: true,
                    });
                  }
                  return arr;
                });
              }
              return next;
            });
          } else if (event.type === "agent_step") {
            if (event.round) {
              setStreamPhase6Msgs((prev) => [
                ...prev,
                {
                  round: event.round,
                  item: event.item,
                  speaker: event.speaker!,
                  msg_type: event.msg_type!,
                  content: event.content!,
                },
              ]);
            } else if (event.item) {
              setStreamEvidenceMsgs((prev) => [
                ...prev,
                {
                  round: event.round,
                  item: event.item,
                  speaker: event.speaker!,
                  msg_type: event.msg_type!,
                  content: event.content!,
                },
              ]);
            }
          } else if (event.type === "skill_start") {
            setSkillCalls((prev) => [
              ...prev,
              {
                id: `${event.agent}-${event.skill}-${Date.now()}`,
                agent: event.agent as string,
                skill: event.skill as string,
                description: event.description as string,
                inputPreview: event.input_preview as string,
                status: "running",
              },
            ]);
          } else if (event.type === "skill_end") {
            setSkillCalls((prev) => {
              const arr = [...prev];
              const idx = arr.findIndex(
                (s) => s.agent === event.agent && s.skill === event.skill && s.status === "running"
              );
              if (idx >= 0) {
                arr[idx] = {
                  ...arr[idx],
                  outputPreview: event.output_preview as string,
                  durationMs: event.duration_ms as number,
                  status: "done",
                };
              }
              return arr;
            });
          } else if (event.type === "insights_ready") {
          } else if (event.type === "done") {
            setPhases((event.phases as TrialPhase[]) || []);
            setState((prev) =>
              prev
                ? {
                    ...prev,
                    current_phase: event.current_phase as number,
                    [`phase${phase}_confirmed` as keyof TrialState]: true as never,
                  }
                : prev
            );
            setStreamingPhase(0);
            setStreamingContent("");
            setSkillCalls([]);
            const awaiting = (event as any).awaiting_strategy_selection;
            if (awaiting) {
              setAwaitingStrategySelection(awaiting);
            } else {
              setAwaitingStrategySelection(null);
            }
          } else if (event.type === "error") {
            setError(event.message || "继续庭审失败");
          }
        },
        startStream()
      );
    } catch (err) {
      // H9：abort（卸载/重开/重试）触发的 AbortError 不当作错误展示
      const isAbort = err instanceof DOMException && err.name === "AbortError";
      if (!isAbort) {
        setError(err instanceof Error ? err.message : "继续庭审失败，请稍后重试");
      }
    } finally {
      abortStream();
    }
    setContinuing(false);
  };

  // 选择策略路线（单方对抗模式）
  const handleSelectStrategy = async (phase: number, routeId: string) => {
    setError("");
    try {
      await selectStrategy(caseId, phase, routeId);
      // 选择成功后，自动重新启动当前 phase 的流式生成
      setAwaitingStrategySelection(null);
      await handleStart();
    } catch (err) {
      setError(err instanceof Error ? err.message : "选择策略失败");
    }
  };

  // 加载庭审历史
  const loadHistory = async () => {
    try {
      const res = await getTrialHistory(caseId);
      setHistory(res.snapshots || []);
      setShowHistory(true);
    } catch {
      alert("加载历史失败");
    }
  };

  // 回退到指定阶段
  const handleReset = async (toPhase: number) => {
    if (
      !confirm(
        `确定要回退到 Phase ${toPhase} 重新运行吗？后续所有产出将被清空。`
      )
    )
      return;
    try {
      const res = await resetTrial(caseId, toPhase);
      setPhases(res.phases || []);
      setState((prev) =>
        prev
          ? {
              ...prev,
              current_phase: res.current_phase,
              phase1_confirmed: false,
              phase2_confirmed: false,
              phase3_confirmed: false,
              phase4_confirmed: false,
              phase5_confirmed: false,
              phase6_confirmed: false,
              phase7_confirmed: false,
            }
          : prev
      );
      setShowHistory(false);
      setHistory([]);
    } catch {
      alert("回退失败");
    }
  };

  // Phase 6 的特殊处理
  const phase6Data = useMemo(() => {
    const p6 = phases.find((p) => p.phase === 6);
    if (!p6) return null;
    return parsePhase6(p6.content);
  }, [phases]);

  if (!started) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center max-w-md">
          <div className="text-4xl mb-4">⚖️</div>
          <h1 className="text-xl font-bold text-gray-800 mb-2">庭审控制台</h1>
          <p className="text-sm text-gray-500 mb-6">
            案件编号：{caseId} · 代理模式：
            {mode === "asymmetric"
              ? userRole === "plaintiff"
                ? "单方模式 · 代理原告"
                : userRole === "defendant"
                ? "单方模式 · 代理被告"
                : "中立观察"
              : userRole === "plaintiff"
              ? "代理原告"
              : userRole === "defendant"
              ? "代理被告"
              : "中立观察"}
          </p>
          <button
            onClick={handleStart}
            disabled={continuing}
            className="bg-blue-600 text-white px-8 py-3 rounded-lg text-lg font-semibold hover:bg-blue-700 transition disabled:opacity-50 disabled:cursor-not-allowed"
          >
            开始模拟庭审
          </button>
          <p className="text-xs text-gray-400 mt-4">
            点击后将调用 AI 生成 Phase 1 内容，请保持页面打开
          </p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center max-w-md">
          <p className="text-red-600 text-lg mb-4">{error}</p>
          <button
            onClick={handleStart}
            disabled={continuing}
            className="bg-blue-600 text-white px-6 py-2 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
          >
            重试
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-full lg:max-w-5xl mx-auto p-4 lg:p-6 transition-all">
      {/* 顶部 */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <button
          onClick={() => router.push("/")}
          className="text-blue-600 text-sm hover:underline"
        >
          ← 返回首页
        </button>
        <div className="flex gap-2">
          <button
            onClick={loadHistory}
            className="bg-gray-600 text-white px-4 py-2 rounded-lg text-sm"
          >
            📜 历史记录
          </button>
          {started && state && state.current_phase >= 1 && (
            <FullReportExport
              caseId={caseId}
              currentPhase={state.current_phase}
              phases={phases}
            />
          )}
          {state?.current_phase === 8 && (
            <button
              onClick={() => router.push("/case/new")}
              className="bg-green-600 text-white px-4 py-2 rounded-lg text-sm"
            >
              🔄 新建庭审
            </button>
          )}
        </div>
      </div>

      <h1 className="text-2xl font-bold text-gray-800 mb-2">⚖️ 庭审控制台</h1>
      <p className="text-sm text-gray-500 mb-6">
        案件编号：{caseId} · 代理模式：
        {mode === "asymmetric"
          ? userRole === "plaintiff"
            ? "单方模式 · 代理原告"
            : userRole === "defendant"
            ? "单方模式 · 代理被告"
            : "中立观察"
          : userRole === "plaintiff"
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

      {/* Agent Skill 调用面板 */}
      <SkillCallPanel calls={skillCalls} />

      {/* 主内容区 */}
      <div className="mt-6 space-y-2">
        {phases.map((p) => {
          // Phase 6 特殊处理
          if (p.phase === 6 && phase6Data) {
            const crossMessages = parseCrossExam(phase6Data.crossExam);
            const liveCrossMsgs = streamPhase6Msgs
              .filter((m) => m.msg_type === "question" || m.msg_type === "answer")
              .map((m) => ({
                round: m.round || 0,
                speaker: m.speaker as "plaintiff" | "defendant",
                type: m.msg_type as "question" | "answer",
                content: m.content,
              }));
            const displayMessages =
              crossMessages.length > 0 ? crossMessages : liveCrossMsgs;

            const isCurrent = state?.current_phase === 6;
            const showConfirm = isCurrent && state && state.current_phase < 8 && !awaitingStrategySelection && !continuing;

            return (
              <div key={6}>
                {showConfirm && (
                  <div className="flex justify-end mb-2">
                    <button
                      onClick={() => handleConfirm(6)}
                      className="bg-green-600 text-white px-6 py-2 rounded-lg text-sm font-semibold hover:bg-green-700 transition"
                    >
                      确认并继续
                    </button>
                  </div>
                )}
                <PhaseContent
                  phase={6}
                  label="交叉询问"
                  isCurrent={isCurrent}
                  confirmed={(state?.current_phase || 0) > 6}

                  defaultExpanded={true}
                >
                  {displayMessages.length > 0 ? (
                    <ChatBubble messages={displayMessages} />
                  ) : isCurrent && (continuing || streamingPhase === 6 || streamPhase6Msgs.length > 0) ? (
                    <div className="max-w-2xl mx-auto py-6 text-center">
                      <div className="inline-flex items-center gap-2 text-sm text-gray-500">
                        <span className="inline-block w-2 h-2 bg-blue-500 rounded-full animate-pulse" />
                        交叉询问进行中，对话将在此逐条呈现…
                      </div>
                      <ChatBubble messages={[]} />
                    </div>
                  ) : (
                    <p className="text-gray-400 italic">暂无交叉询问记录</p>
                  )}
                </PhaseContent>

                <PhaseContent
                  phase={6}
                  label="举证质证"
                  isCurrent={isCurrent}
                  confirmed={(state?.current_phase || 0) > 6}
                  defaultExpanded={true}
                >
                  {(() => {
                    const persisted = parseEvidenceExam(phase6Data.evidenceExam);
                    const displayMessages =
                      persisted.length > 0
                        ? persisted.map((m: any) => ({
                            item: m.item,
                            speaker: m.speaker as "plaintiff" | "defendant" | "judge",
                            type: m.type as "focus" | "comment" | "cross_examine" | "ruling",
                            content: m.content,
                          }))
                        : streamEvidenceMsgs.map((m) => {
                            let type = m.msg_type;
                            if (m.msg_type === "guidance" && m.speaker === "judge") type = "focus";
                            else if (m.msg_type === "evidence_opinion" && m.speaker === "plaintiff") type = "comment";
                            else if (m.msg_type === "evidence_opinion" && m.speaker === "defendant") type = "cross_examine";
                            else if (m.msg_type === "ruling") type = "ruling";
                            return {
                              item: m.item || 0,
                              speaker: m.speaker as "plaintiff" | "defendant" | "judge",
                              type: type as "focus" | "comment" | "cross_examine" | "ruling",
                              content: m.content,
                            };
                          });
                    return displayMessages.length > 0 ? (
                      <ChatBubble messages={displayMessages} />
                    ) : isCurrent && (continuing || streamingPhase === 6 || streamEvidenceMsgs.length > 0) ? (
                      <div className="max-w-2xl mx-auto py-6 text-center">
                        <div className="inline-flex items-center gap-2 text-sm text-gray-500">
                          <span className="inline-block w-2 h-2 bg-blue-500 rounded-full animate-pulse" />
                          举证质证进行中，意见与裁定将在此逐条呈现…
                        </div>
                        <ChatBubble messages={[]} />
                      </div>
                    ) : (
                      <p className="text-gray-400 italic">暂无举证质证记录</p>
                    );
                  })()}
                </PhaseContent>
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
              : p.phase === 5
              ? state?.phase5_confirmed
              : p.phase === 6
              ? state?.phase6_confirmed
              : p.phase === 7
              ? state?.phase7_confirmed
              : p.phase === 8
              ? state?.phase8_confirmed
              : false;

          // 所有阶段都显示确认按钮，由用户控制推进（策略选择等待或生成中时不显示）
          const showConfirm = isCurrent && state && state.current_phase < 8 && !awaitingStrategySelection && !continuing;

          // 流式内容覆盖
          const displayContent =
            streamingPhase === p.phase ? streamingContent : p.content;

          return (
            <div key={p.phase}>
              {showConfirm && (
                <div className="flex justify-end mb-2">
                  <button
                    onClick={() => handleConfirm(p.phase)}
                    className="bg-green-600 text-white px-6 py-2 rounded-lg text-sm font-semibold hover:bg-green-700 transition"
                  >
                    确认并继续
                  </button>
                </div>
              )}
              {/* 策略路线卡片（单方对抗模式） */}
              {p.strategy_routes && p.strategy_routes.length > 0 && (
                <div className="mb-4 bg-indigo-50 border border-indigo-200 rounded-xl p-4">
                  <h3 className="text-sm font-semibold text-indigo-900 mb-3">
                    {awaitingStrategySelection && awaitingStrategySelection.phase === p.phase
                      ? "🧭 AI 生成的策略路线（请选择一条策略）"
                      : "🧭 AI 生成的策略路线"}
                  </h3>
                  <div className="space-y-3">
                    {p.strategy_routes.map((route) => {
                      const isSelected = route.route_id === p.selected_route;
                      const isWaiting = awaitingStrategySelection && awaitingStrategySelection.phase === p.phase;
                      return (
                        <div
                          key={route.route_id}
                          className={`p-3 rounded-lg border text-sm ${
                            isSelected
                              ? "bg-white border-indigo-400 shadow-sm"
                              : "bg-white/50 border-indigo-100 opacity-70"
                          }`}
                        >
                          <div className="flex items-center gap-2 mb-1">
                            <span className="font-bold text-indigo-700">
                              路线 {route.route_id}
                            </span>
                            {route.is_recommended && (
                              <span className="text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full">
                                AI 推荐
                              </span>
                            )}
                            {isSelected && (
                              <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">
                                已选用
                              </span>
                            )}
                          </div>
                          <div className="font-medium text-gray-800 mb-1">
                            {route.title}
                          </div>
                          <div className="text-xs text-gray-600 space-y-0.5">
                            <p>
                              <span className="font-semibold">核心主张：</span>
                              {route.core_theory}
                            </p>
                            <p>
                              <span className="font-semibold">法律依据：</span>
                              {route.legal_basis}
                            </p>
                            <p>
                              <span className="font-semibold">证据策略：</span>
                              {route.evidence_strategy}
                            </p>
                            <p className="text-red-600">
                              <span className="font-semibold">风险提示：</span>
                              {route.risk_warning}
                            </p>
                          </div>
                          {isWaiting && !isSelected && (
                            <div className="mt-2">
                              <button
                                onClick={() => handleSelectStrategy(p.phase, route.route_id)}
                                className="bg-indigo-600 text-white px-4 py-1.5 rounded-lg text-xs font-semibold hover:bg-indigo-700 transition"
                              >
                                选择此策略
                              </button>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
              <PhaseContent
                phase={p.phase}
                label={p.label}
                content={displayContent}
                defaultExpanded={p.phase === state?.current_phase}
                isCurrent={isCurrent}
                confirmed={phaseConfirmed}

                onEdit={
                  !continuing &&
                  !!p.content &&
                  (mode !== "asymmetric" ||
                    (userRole === "plaintiff" && (p.phase === 1 || p.phase === 2)) ||
                    (userRole === "defendant" && (p.phase === 3 || p.phase === 4)))
                    ? (edited) => handleConfirm(p.phase, edited)
                    : undefined
                }
              />
            </div>
          );
        })}

        {/* 持续加载 */}
        {continuing && (
          <div className="text-center py-8">
            <div className="animate-pulse text-lg text-gray-600 font-medium">庭审进行中</div>
            <div className="text-sm mt-2 text-blue-600 font-semibold">{currentPhaseLabel}</div>
            <div className="w-56 h-1.5 bg-gray-200 rounded-full mx-auto mt-4 overflow-hidden">
              <div className="h-full bg-blue-500 rounded-full animate-[shimmer_1.5s_infinite]" style={{ width: '60%' }} />
            </div>
            <div className="text-xs text-gray-400 mt-3">约 30-90 秒，请保持页面打开</div>
          </div>
        )}
      </div>

      {/* 历史记录弹窗 */}
      {showHistory && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl p-6 max-w-lg w-full max-h-[80vh] overflow-auto">
            <h2 className="text-xl font-bold mb-4">📜 庭审历史</h2>
            {history.length === 0 ? (
              <p className="text-gray-500">暂无历史记录</p>
            ) : (
              <div className="space-y-3">
                {history.map((h, idx) => (
                  <div
                    key={idx}
                    className="border rounded-lg p-3 hover:bg-gray-50 transition"
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-semibold text-sm">
                        Phase {h.phase} · {h.label}
                      </span>
                      <span className="text-xs text-gray-400">
                        {new Date(h.timestamp).toLocaleString()}
                      </span>
                    </div>
                    <p className="text-xs text-gray-600 mb-2 line-clamp-2">
                      {h.preview}
                    </p>
                    <button
                      onClick={() => handleReset(h.phase)}
                      className="text-xs bg-blue-600 text-white px-3 py-1 rounded hover:bg-blue-700"
                    >
                      回退到此处
                    </button>
                  </div>
                ))}
              </div>
            )}
            <div className="mt-4 flex gap-3">
              <button
                onClick={() => setShowHistory(false)}
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
