"use client";

// 智能案卷录入页
// 支持：粘贴大段文字 AI 解析 / 上传文件 / 手动填写

import { useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { parseText, parseFile, createCase } from "@/lib/api";

export default function NewCasePage() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 表单字段
  const [caseTitle, setCaseTitle] = useState("");
  const [facts, setFacts] = useState("");
  const [evidence, setEvidence] = useState("");
  const [claims, setClaims] = useState("");

  // 智能录入
  const [pasteText, setPasteText] = useState("");
  const [parsing, setParsing] = useState(false);
  const [parseError, setParseError] = useState("");

  // 提交
  const [submitting, setSubmitting] = useState(false);

  // 代理模式
  const [userRole, setUserRole] = useState("neutral");

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
      }
    } catch {
      setParseError("解析失败，请检查后端是否启动");
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
      }
    } catch {
      setParseError("文件解析失败，请检查后端是否启动");
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
      const res = await createCase({ case_title: caseTitle, facts, evidence, claims });
      const caseId = res.case_id;
      // 跳转到庭审页，附带代理模式
      router.push(`/trial/${caseId}?role=${userRole}`);
    } catch {
      alert("提交失败，请检查后端是否启动");
    }
    setSubmitting(false);
  };

  return (
    <div className="max-w-4xl mx-auto p-6">
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

        {/* 代理模式 */}
        <div>
          <label className="block text-sm font-semibold text-gray-700 mb-2">
            代理模式
          </label>
          <div className="flex gap-3">
            {[
              { value: "neutral", label: "👀 中立观察", desc: "双方法律意见自动生成" },
              { value: "plaintiff", label: "🎯 代理原告", desc: "原告策略分步确认可修改" },
              { value: "defendant", label: "🛡️ 代理被告", desc: "被告策略分步确认可修改" },
            ].map((opt) => (
              <button
                key={opt.value}
                onClick={() => setUserRole(opt.value)}
                className={`flex-1 p-3 rounded-lg text-sm text-left border
                  ${
                    userRole === opt.value
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

        <button
          onClick={handleSubmit}
          disabled={submitting || !caseTitle || !facts || !evidence || !claims}
          className="w-full bg-green-600 text-white px-6 py-4 rounded-xl text-lg font-semibold
                     disabled:opacity-50 hover:bg-green-700 transition shadow-lg"
        >
          {submitting ? "提交中..." : "🔨 开始模拟庭审"}
        </button>
      </div>
    </div>
  );
}
