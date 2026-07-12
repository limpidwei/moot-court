"use client";

// 智能案卷录入页
// 支持：粘贴大段文字 AI 解析 / 上传文件 / 手动填写

import { useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { parseText, parseFile, createCase } from "@/lib/api";
import ModelConfigPanel from "@/components/ModelConfigPanel";
import type { LLMConfig } from "@/lib/api";

export default function NewCasePage() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 表单字段
  const [caseTitle, setCaseTitle] = useState("");
  const [facts, setFacts] = useState("");
  const [evidence, setEvidence] = useState("");
  const [claims, setClaims] = useState("");

  // 案卷原始材料（双轨制保留）
  const [sourceMaterials, setSourceMaterials] = useState("");

  // 智能录入
  const [pasteText, setPasteText] = useState("");
  const [parsing, setParsing] = useState(false);
  const [parseError, setParseError] = useState("");

  // 提交
  const [submitting, setSubmitting] = useState(false);

  // 模式选择
  const [mode, setMode] = useState("neutral");
  const [userSide, setUserSide] = useState("");
  const [userStrategyHint, setUserStrategyHint] = useState("");

  // 对抗强度（单方对抗模式下有效）
  const [adversarialIntensity, setAdversarialIntensity] = useState(3);

  // LLM 配置
  const [llmConfig, setLlmConfig] = useState<LLMConfig | null>(null);

  const handlePasteParse = async () => {
    if (!pasteText.trim()) return;
    setParsing(true);
    setParseError("");
    try {
      const result = await parseText(pasteText);
      if (result.error) {
        setParseError(result.error);
      } else {
        setCaseTitle(result.case_title || "");
        setFacts(result.facts || "");
        setEvidence(
          (result.evidence_list || [])
            .map(
              (e: { name: string; type: string; description: string }, i: number) =>
                `${i + 1}. ${e.name}（${e.type}）—— ${e.description}`
            )
            .join("\n")
        );
        setClaims((result.claims || []).join("\n"));
        setSourceMaterials(result.raw_text || pasteText);
      }
    } catch (e: any) {
      setParseError(e.message || "解析失败，请检查网络连接");
    }
    setParsing(false);
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setParsing(true);
    setParseError("");
    try {
      const result = await parseFile(file);
      if (result.error) {
        setParseError(result.error);
      } else {
        setCaseTitle(result.case_title || "");
        setFacts(result.facts || "");
        setEvidence(
          (result.evidence_list || [])
            .map(
              (e: { name: string; type: string; description: string }, i: number) =>
                `${i + 1}. ${e.name}（${e.type}）—— ${e.description}`
            )
            .join("\n")
        );
        setClaims((result.claims || []).join("\n"));
        setSourceMaterials(result.raw_text || "");
      }
    } catch (e: any) {
      setParseError(e.message || "文件解析失败，请检查网络连接");
    }
    setParsing(false);
  };

  const handleSubmit = async () => {
    if (!caseTitle || !facts || !evidence || !claims) {
      alert("请填写完整的案卷信息");
      return;
    }
    setSubmitting(true);
    try {
      const payload: {
        case_title: string;
        facts: string;
        evidence: string;
        claims: string;
        mode: string;
        user_side: string;
        user_strategy_hint: string;
        source_materials: string;
        adversarial_intensity: number;
        llm_config?: LLMConfig;
      } = {
        case_title: caseTitle,
        facts,
        evidence,
        claims,
        mode,
        user_side: userSide,
        user_strategy_hint: userStrategyHint,
        source_materials: sourceMaterials,
        adversarial_intensity: adversarialIntensity,
      };
      if (llmConfig) {
        payload.llm_config = llmConfig;
      }
      const res = await createCase(payload);
      const caseId = res.case_id;
      const startRole = mode === "asymmetric" ? userSide : "neutral";
      router.push(`/trial/${caseId}?role=${startRole}`);
    } catch {
      alert("提交失败，请检查后端是否启动");
    }
    setSubmitting(false);
  };

  return (
    <div className="max-w-4xl mx-auto p-4 lg:p-6">
      <button
        onClick={() => router.push("/")}
        className="text-blue-600 text-sm mb-6 hover:underline"
      >
        ← 返回首页
      </button>

      <h1 className="text-2xl font-bold text-gray-800 mb-2">📋 新建庭审</h1>
      <p className="text-gray-500 mb-8">
        粘贴起诉状全文或上传文件，AI 自动提取结构化信息。
      </p>

      {/* 智能录入区 */}
      <div className="bg-blue-50 border border-blue-200 rounded-xl p-6 mb-8">
        <h2 className="font-semibold text-blue-900 mb-3">🤖 智能录入</h2>
        <p className="text-sm text-blue-700 mb-3">
          粘贴完整的起诉状、判决书或案情描述，AI 自动提取案由、事实、证据和诉讼请求。
        </p>
        <textarea
          value={pasteText}
          onChange={(e) => setPasteText(e.target.value)}
          placeholder="在此粘贴文本...（例如：原告A公司与被告B公司于2024年3月1日签订《购销合同》...）"
          className="w-full h-32 p-3 border border-blue-200 rounded-lg text-sm
                     focus:ring-2 focus:ring-blue-400 focus:border-transparent"
        />
        <div className="flex gap-3 mt-3">
          <button
            onClick={handlePasteParse}
            disabled={parsing || !pasteText.trim()}
            className="bg-blue-600 text-white px-5 py-2 rounded-lg text-sm font-semibold
                       disabled:opacity-50 hover:bg-blue-700"
          >
            {parsing ? "解析中..." : "🔍 智能解析"}
          </button>
          <button
            onClick={() => fileInputRef.current?.click()}
            className="bg-white text-blue-600 border border-blue-300 px-5 py-2
                       rounded-lg text-sm hover:bg-blue-50"
          >
            📁 上传文件
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".txt,.docx,.pdf"
            onChange={handleFileUpload}
            className="hidden"
          />
        </div>
        {parseError && (
          <p className="text-red-600 text-sm mt-2">{parseError}</p>
        )}
      </div>

      {/* 模型配置 */}
      <ModelConfigPanel value={llmConfig} onChange={setLlmConfig} />

      {/* 表单区 */}
      <div className="space-y-5">
        <div>
          <label className="block text-sm font-semibold text-gray-700 mb-1">
            案由
          </label>
          <input
            type="text"
            value={caseTitle}
            onChange={(e) => setCaseTitle(e.target.value)}
            placeholder="例如：买卖合同纠纷"
            className="w-full px-4 py-2 border rounded-lg text-sm"
          />
        </div>

        <div>
          <label className="block text-sm font-semibold text-gray-700 mb-1">
            案情事实
          </label>
          <textarea
            value={facts}
            onChange={(e) => setFacts(e.target.value)}
            placeholder="按时间顺序描述案件经过..."
            className="w-full h-36 px-4 py-2 border rounded-lg text-sm"
          />
        </div>

        <div>
          <label className="block text-sm font-semibold text-gray-700 mb-1">
            证据清单
          </label>
          <textarea
            value={evidence}
            onChange={(e) => setEvidence(e.target.value)}
            placeholder="每行一项证据，标注类型..."
            className="w-full h-32 px-4 py-2 border rounded-lg text-sm"
          />
        </div>

        <div>
          <label className="block text-sm font-semibold text-gray-700 mb-1">
            诉讼请求
          </label>
          <textarea
            value={claims}
            onChange={(e) => setClaims(e.target.value)}
            placeholder="逐项列出诉讼请求..."
            className="w-full h-28 px-4 py-2 border rounded-lg text-sm"
          />
        </div>

        {/* 模式选择 */}
        <div>
          <label className="block text-sm font-semibold text-gray-700 mb-2">
            庭审模式
          </label>
          <div className="flex gap-3">
            {[
              { value: "neutral", label: "👀 中立观察", desc: "双方材料均已知，AI 自动生成全流程" },
              { value: "asymmetric", label: "⚔️ 单方对抗", desc: "只输入单方材料，AI 生成对方材料" },
            ].map((opt) => (
              <button
                key={opt.value}
                onClick={() => {
                  setMode(opt.value);
                  if (opt.value === "neutral") setUserSide("");
                }}
                className={`flex-1 p-3 rounded-lg text-sm text-left border
                  ${
                    mode === opt.value
                      ? "border-blue-400 bg-blue-50"
                      : "border-gray-200 hover:bg-gray-50"
                  }`}
              >
                <div className="font-semibold">{opt.label}</div>
                <div className="text-xs text-gray-500 mt-1">{opt.desc}</div>
              </button>
            ))}
          </div>
        </div>

        {/* 单方对抗：选择扮演角色 */}
        {mode === "asymmetric" && (
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-2">
              你选择扮演
            </label>
            <div className="flex gap-3">
              {[
                { value: "plaintiff", label: "🎯 原告律师", desc: "掌握原告材料，被告材料由 AI 生成" },
                { value: "defendant", label: "🛡️ 被告律师", desc: "掌握被告材料，原告材料由 AI 生成" },
              ].map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setUserSide(opt.value)}
                  className={`flex-1 p-3 rounded-lg text-sm text-left border
                    ${
                      userSide === opt.value
                        ? "border-blue-400 bg-blue-50"
                        : "border-gray-200 hover:bg-gray-50"
                    }`}
                >
                  <div className="font-semibold">{opt.label}</div>
                  <div className="text-xs text-gray-500 mt-1">{opt.desc}</div>
                </button>
              ))}
            </div>

            {/* 策略倾向（可选） */}
            <div className="mt-4">
              <label className="block text-sm font-semibold text-gray-700 mb-1">
                策略倾向（可选）
              </label>
              <textarea
                value={userStrategyHint}
                onChange={(e) => setUserStrategyHint(e.target.value)}
                placeholder="例如：主张合同无效 / 主张对方违约 / 主张不可抗力..."
                className="w-full h-20 px-4 py-2 border rounded-lg text-sm"
              />
              <p className="text-xs text-gray-400 mt-1">
                填写后 AI 会优先按此方向生成策略路线
              </p>
            </div>

            {/* 对抗强度滑块 */}
            <div className="mt-6 bg-gray-50 border border-gray-200 rounded-lg p-4">
              <label className="block text-sm font-semibold text-gray-700 mb-3">
                🤖 AI 对手对抗强度
              </label>
              <div className="flex items-center gap-4">
                <span className="text-xs text-gray-500 whitespace-nowrap">保守</span>
                <input
                  type="range"
                  min={1}
                  max={5}
                  step={1}
                  value={adversarialIntensity}
                  onChange={(e) => setAdversarialIntensity(Number(e.target.value))}
                  className="flex-1 h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
                />
                <span className="text-xs text-gray-500 whitespace-nowrap">激进</span>
              </div>
              <div className="flex justify-between text-xs text-gray-400 mt-1 px-1">
                <span>1</span><span>2</span><span>3</span><span>4</span><span>5</span>
              </div>
              <p className="text-xs text-gray-600 mt-2 font-medium">
                {adversarialIntensity <= 2 && "强度 1-2（保守）：AI 对手较弱，主要依赖事实解释，几乎不编造新证据"}
                {adversarialIntensity === 3 && "强度 3（平衡）：AI 对手适中，允许编造聊天记录和证人证言"}
                {adversarialIntensity >= 4 && "强度 4-5（激进）：AI 对手较强，允许更多类型的对抗性证据"}
              </p>
            </div>
          </div>
        )}

        <button
          onClick={handleSubmit}
          disabled={
            submitting ||
            !caseTitle ||
            !facts ||
            !evidence ||
            !claims ||
            (mode === "asymmetric" && !userSide)
          }
          className="w-full bg-green-600 text-white px-6 py-4 rounded-xl text-lg font-semibold
                     disabled:opacity-50 hover:bg-green-700 transition shadow-lg"
        >
          {submitting ? "提交中..." : "🔨 开始模拟庭审"}
        </button>
      </div>
    </div>
  );
}
