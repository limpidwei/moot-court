"use client";

// 庭后法官问答组件

import { useState } from "react";
import { askJudge } from "@/lib/api";

export default function JudgeQA({ caseId }: { caseId: string }) {
  const [question, setQuestion] = useState("");
  const [qaList, setQaList] = useState<{ q: string; a: string }[]>([]);
  const [loading, setLoading] = useState(false);

  const handleAsk = async () => {
    if (!question.trim()) return;
    setLoading(true);
    try {
      const res = await askJudge(caseId, question);
      setQaList([...qaList, { q: question, a: res.answer }]);
      setQuestion("");
    } catch {
      alert("法官问答失败，请检查后端是否运行");
    }
    setLoading(false);
  };

  return (
    <div className="mt-8 border-t pt-6">
      <h3 className="text-lg font-bold text-gray-800 mb-4">
        💬 向法官继续提问
      </h3>
      <p className="text-sm text-gray-500 mb-4">
        基于庭审记录和判决，法官可以回答你对案件的进一步疑问。
      </p>

      {qaList.map((qa, i) => (
        <div key={i} className="mb-4">
          <div className="bg-blue-50 text-blue-900 px-4 py-2 rounded-lg text-sm font-semibold">
            🙋 {qa.q}
          </div>
          <div className="bg-gray-50 text-gray-700 px-4 py-3 rounded-lg text-sm mt-1 whitespace-pre-wrap">
            ⚖️ {qa.a}
          </div>
        </div>
      ))}

      <div className="flex gap-2">
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAsk()}
          placeholder="例如：如果补充一份还款记录，结果会变吗？"
          className="flex-1 px-4 py-2 border rounded-lg text-sm"
          disabled={loading}
        />
        <button
          onClick={handleAsk}
          disabled={loading || !question.trim()}
          className="bg-blue-600 text-white px-6 py-2 rounded-lg text-sm font-semibold disabled:opacity-50"
        >
          {loading ? "思考中..." : "提问"}
        </button>
      </div>
    </div>
  );
}
