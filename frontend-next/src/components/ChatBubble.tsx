"use client";

// 微信气泡式对话组件 — 用于交叉询问展示

export interface ChatMessage {
  round: number;
  speaker: "plaintiff" | "defendant" | "judge";
  type: "question" | "answer" | "guidance";
  content: string;
}

export default function ChatBubble({ messages }: { messages: ChatMessage[] }) {
  return (
    <div className="space-y-3 max-w-2xl mx-auto py-4">
      {messages.map((msg, idx) => {
        const isPlaintiff = msg.speaker === "plaintiff";
        const isDefendant = msg.speaker === "defendant";
        const isJudge = msg.speaker === "judge";

        const roleName = isPlaintiff
          ? "原告律师"
          : isDefendant
          ? "被告律师"
          : "法官";
        const typeName =
          msg.type === "question"
            ? "提问"
            : msg.type === "answer"
            ? "回答"
            : "引导";

        return (
          <div
            key={idx}
            className={`flex ${isJudge ? "justify-center" : ""} ${
              isPlaintiff ? "justify-end" : ""
            } ${isDefendant ? "justify-start" : ""}`}
          >
            <div
              className={`max-w-[75%] px-4 py-3 rounded-2xl text-sm leading-relaxed
                ${
                  isPlaintiff
                    ? "bg-blue-500 text-white rounded-br-md"
                    : ""
                }
                ${
                  isDefendant
                    ? "bg-gray-100 text-gray-800 rounded-bl-md"
                    : ""
                }
                ${
                  isJudge
                    ? "bg-yellow-50 border border-yellow-300 text-gray-700 italic text-center max-w-[85%] rounded-lg"
                    : ""
                }
              `}
            >
              <div
                className={`text-xs mb-1 font-semibold ${
                  isPlaintiff
                    ? "text-blue-100"
                    : isDefendant
                    ? "text-gray-400"
                    : "text-yellow-600"
                }`}
              >
                {roleName} {typeName} · 第{msg.round}轮
              </div>
              <div className="whitespace-pre-wrap">{msg.content}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
