"use client";
import "./globals.css";
import Link from "next/link";
import { usePathname } from "next/navigation";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  return (
    <html lang="en">
      <body className="bg-gray-950 text-gray-100 min-h-screen">
        <nav className="bg-gray-900 border-b border-gray-800 px-6 py-4 flex items-center gap-8">
          <span className="font-bold text-lg text-indigo-400 tracking-tight">CX Analyzer</span>
          <Link
            href="/outputs"
            className={`text-sm font-medium px-3 py-1.5 rounded-md transition-colors ${
              path.startsWith("/outputs")
                ? "bg-indigo-600 text-white"
                : "text-gray-400 hover:text-white hover:bg-gray-800"
            }`}
          >
            Outputs
          </Link>
          <Link
            href="/analyze"
            className={`text-sm font-medium px-3 py-1.5 rounded-md transition-colors ${
              path.startsWith("/analyze")
                ? "bg-indigo-600 text-white"
                : "text-gray-400 hover:text-white hover:bg-gray-800"
            }`}
          >
            Analyze
          </Link>
          <Link
            href="/system"
            className={`text-sm font-medium px-3 py-1.5 rounded-md transition-colors ${
              path.startsWith("/system")
                ? "bg-indigo-600 text-white"
                : "text-gray-400 hover:text-white hover:bg-gray-800"
            }`}
          >
            System
          </Link>
        </nav>
        <main className="p-6">{children}</main>
      </body>
    </html>
  );
}
