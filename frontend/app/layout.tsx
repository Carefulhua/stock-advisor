import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "个股分析 - stock-advisor",
  description: "A股 K线与技术指标分析",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
