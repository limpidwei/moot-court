"use client";

import { useRouter } from "next/navigation";

export default function HomePage() {
  const router = useRouter();

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4">
      <div className="text-center max-w-lg">
        <h1 className="text-5xl font-bold text-gray-800 mb-4">⚖️</h1>
        <h1 className="text-3xl font-bold text-gray-800 mb-3">模拟法庭</h1>
        <p className="text-gray-500 mb-8 leading-relaxed">
          输入案情和证据，AI 法官与双方律师即刻按照
          《中华人民共和国民事诉讼法》程序进行模拟庭审。
          <br />
          生成起诉状、答辩状、证据目录、交叉询问、判决书，
          并给出量化的胜率评估。
        </p>

        <div className="space-y-3">
          <button
            onClick={() => router.push("/case/new")}
            className="w-full bg-blue-600 text-white px-8 py-4 rounded-xl text-lg font-semibold
                       hover:bg-blue-700 transition shadow-lg shadow-blue-200"
          >
            📋 新建庭审
          </button>
          <button
            onClick={() => router.push("/history")}
            className="w-full bg-gray-100 text-gray-600 px-8 py-4 rounded-xl text-lg
                       hover:bg-gray-200 transition"
          >
            📂 历史记录（开发中）
          </button>
        </div>

        <div className="mt-12 grid grid-cols-3 gap-4 text-center text-sm text-gray-400">
          <div>
            <div className="text-2xl mb-1">📝</div>
            <div>智能录入</div>
            <div className="text-xs">粘贴/上传自动解析</div>
          </div>
          <div>
            <div className="text-2xl mb-1">⚡</div>
            <div>8 阶段庭审</div>
            <div className="text-xs">按民诉法程序</div>
          </div>
          <div>
            <div className="text-2xl mb-1">📊</div>
            <div>量化胜率</div>
            <div className="text-xs">四维度加权评估</div>
          </div>
        </div>
      </div>
    </div>
  );
}
