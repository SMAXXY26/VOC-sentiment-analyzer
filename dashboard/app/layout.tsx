import "./globals.css";
import { Inter } from "next/font/google";
import { Nav } from "@/components/Nav";
import { ChatWidget } from "@/components/ChatWidget";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata = { title: "CX Analyzer", description: "Customer Experience Semantic Analysis Platform" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="bg-[#060b18] text-slate-100 min-h-screen">
        <Nav />
        <main className="pt-20 px-4 pb-10 max-w-[1600px] mx-auto">{children}</main>
        <ChatWidget />
      </body>
    </html>
  );
}
