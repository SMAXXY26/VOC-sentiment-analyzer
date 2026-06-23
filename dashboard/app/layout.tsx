import "./globals.css";
import { Inter } from "next/font/google";
import { AuthGate } from "@/components/AuthGate";
import { ThemeProvider } from "@/components/ThemeProvider";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata = { title: "CX Analyzer", description: "Customer Experience Semantic Analysis Platform" };

// Applies the persisted theme to <html> before first paint to avoid a flash of
// the wrong theme. Defaults to dark when nothing is stored.
const noFlashScript = `(function(){try{var t=localStorage.getItem('theme');if(t!=='light'){document.documentElement.classList.add('dark');}}catch(e){document.documentElement.classList.add('dark');}try{if(localStorage.getItem('nav_collapsed')==='1'){document.documentElement.classList.add('nav-collapsed');}}catch(e){}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: noFlashScript }} />
      </head>
      <body className="bg-slate-50 text-slate-900 dark:bg-[#060b18] dark:text-slate-100 min-h-screen md:h-screen md:overflow-hidden transition-colors duration-300">
        <ThemeProvider>
          <AuthGate>{children}</AuthGate>
        </ThemeProvider>
      </body>
    </html>
  );
}
