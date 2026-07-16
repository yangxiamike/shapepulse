import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "手动跟踪市场",
  description: "本地、快速、可解释的 A 股手工选股与行情终端。",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
