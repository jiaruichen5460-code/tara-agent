import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AuthGate } from "@/components/auth-gate";

import "./globals.css";

export const metadata: Metadata = {
  title: "Tara Agent",
  description: "Tara Agent",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body><AuthGate>{children}</AuthGate></body>
    </html>
  );
}
