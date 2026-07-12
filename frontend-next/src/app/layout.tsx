import type { Metadata } from "next";
import "./globals.css";
import AuthGuard from "@/components/AuthGuard";
import UserMenu from "@/components/UserMenu";

export const metadata: Metadata = {
  title: "模拟法庭 — AI 庭审系统",
  description: "输入案情和证据，AI 法官与双方律师即刻开庭",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body className="bg-gray-50 min-h-screen">
        <AuthGuard>
          <header className="bg-white shadow-sm border-b border-gray-200">
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
              <div className="flex justify-between items-center h-16">
                <div className="flex items-center">
                  <h1 className="text-xl font-bold text-gray-900">
                    ⚖️ 模拟法庭
                  </h1>
                </div>
                <UserMenu />
              </div>
            </div>
          </header>
          <main>{children}</main>
        </AuthGuard>
      </body>
    </html>
  );
}
