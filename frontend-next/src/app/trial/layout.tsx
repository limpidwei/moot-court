import { Suspense } from "react";

// P4 修复：trial/[caseId]/page.tsx 使用 useSearchParams，Next.js 要求必须在 Suspense 边界内。
// 此 layout 为 trial 路由树下的所有页面提供统一的 Suspense fallback。
export default function TrialLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-pulse text-gray-500">加载庭审中...</div>
      </div>
    }>
      {children}
    </Suspense>
  );
}
