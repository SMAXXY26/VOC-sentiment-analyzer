import "./globals.css";
import { Inter } from "next/font/google";
import { Nav } from "@/components/Nav";
import { ChatWidget } from "@/components/ChatWidget";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata = { title: "CX Analyzer", description: "Customer Experience Semantic Analysis Platform" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="bg-[#060b18] text-slate-100 h-screen overflow-hidden">
        <div className="flex h-screen">
          <Nav />
          <main className="flex-1 min-w-0 h-screen overflow-y-auto px-4 py-4">{children}</main>
        </div>
        <ChatWidget />
      </body>
    </html>
  );
}
