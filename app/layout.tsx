import type { Metadata } from "next";
import "./globals.css";
import "./office.css";
import "./review.css";

export const metadata: Metadata = {
  title: "AI 오피스",
  description: "국회·홈 등 사무실별 자동화 현황을 한 사이트에서 보는 픽셀 오피스",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
