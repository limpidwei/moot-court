import type { Metadata } from "next";
import "./globals.css";

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
      <body className="bg-gray-50 min-h-screen">{children}</body>
    </html>
  );
}
