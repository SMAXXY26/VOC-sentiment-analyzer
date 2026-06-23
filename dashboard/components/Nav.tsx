"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useTheme } from "@/components/ThemeProvider";
import { logout } from "@/lib/auth";

const NAV_ITEMS = [
  {
    href: "/outputs",
    label: "Outputs",
    icon: (
      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 5.625c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125" />
      </svg>
    ),
  },
  {
    href: "/analyze",
    label: "Analyze",
    icon: (
      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="m3.75 13.5 10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
      </svg>
    ),
  },
  {
    href: "/system",
    label: "System",
    icon: (
      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 3v1.5M4.5 8.25H3m18 0h-1.5M4.5 12H3m18 0h-1.5m-15 3.75H3m18 0h-1.5M8.25 19.5V21M12 3v1.5m0 15V21m3.75-18v1.5m0 15V21m-9-1.5h10.5a2.25 2.25 0 0 0 2.25-2.25V6.75a2.25 2.25 0 0 0-2.25-2.25H6.75A2.25 2.25 0 0 0 4.5 6.75v10.5a2.25 2.25 0 0 0 2.25 2.25Zm.75-12h9v9h-9v-9Z" />
      </svg>
    ),
  },
  {
    href: "/chat",
    label: "Chat",
    icon: (
      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
      </svg>
    ),
  },
];

export function Nav() {
  const path = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const { theme, toggle } = useTheme();
  return (
    <nav
      className={`shrink-0 md:h-screen flex md:flex-col gap-1 p-3 bg-white/70 dark:bg-black/40 backdrop-blur-2xl border-b md:border-b-0 md:border-r border-slate-200 dark:border-white/[0.08] shadow-xl shadow-black/5 dark:shadow-black/30 transition-all duration-300 ${
        collapsed ? "md:w-16" : "md:w-52"
      }`}
    >
      {/* Logo */}
      <div className="flex items-center gap-2 md:mb-2 md:pb-3 md:border-b border-slate-200 dark:border-white/[0.08]">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center shadow-lg shadow-indigo-500/30 shrink-0">
          <span className="text-white text-[11px] font-bold tracking-tight">CX</span>
        </div>
        {!collapsed && <span className="font-semibold text-sm text-slate-800 dark:text-white/90 tracking-tight whitespace-nowrap">Analyzer</span>}
      </div>

      {/* Links */}
      <div className="flex md:flex-col gap-1 flex-1">
        {NAV_ITEMS.map((item) => {
          const active = path.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              title={item.label}
              className={`flex items-center gap-2.5 text-xs font-medium px-3 py-2 rounded-xl transition-all duration-200 cursor-pointer select-none ${
                collapsed ? "md:justify-center" : ""
              } ${
                active
                  ? "bg-indigo-500/15 dark:bg-indigo-500/20 text-indigo-600 dark:text-indigo-300 border border-indigo-500/25 shadow-sm shadow-indigo-500/10"
                  : "text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 hover:bg-slate-900/[0.04] dark:hover:bg-white/[0.05]"
              }`}
            >
              <span className="shrink-0">{item.icon}</span>
              {!collapsed && <span className="whitespace-nowrap">{item.label}</span>}
            </Link>
          );
        })}
      </div>

      {/* Live indicator */}
      <div className={`hidden md:flex items-center gap-1.5 py-2 ${collapsed ? "justify-center" : "px-3"}`}>
        <span className="relative flex h-2 w-2 shrink-0">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-50" />
          <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-400" />
        </span>
        {!collapsed && <span className="text-[11px] text-slate-500">Live</span>}
      </div>

      {/* Theme toggle */}
      <button
        onClick={toggle}
        title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        className={`flex items-center gap-2.5 text-xs font-medium px-3 py-2 rounded-xl text-slate-500 hover:text-slate-900 dark:hover:text-slate-200 hover:bg-slate-900/[0.04] dark:hover:bg-white/[0.05] transition-all duration-200 cursor-pointer select-none ${
          collapsed ? "md:justify-center" : ""
        }`}
      >
        {theme === "dark" ? (
          // Sun
          <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v2.25m6.364.386-1.591 1.591M21 12h-2.25m-.386 6.364-1.591-1.591M12 18.75V21m-4.773-4.227-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0Z" />
          </svg>
        ) : (
          // Moon
          <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21.752 15.002A9.72 9.72 0 0 1 18 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 0 0 3 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 0 0 9.002-5.998Z" />
          </svg>
        )}
        {!collapsed && <span className="whitespace-nowrap">{theme === "dark" ? "Light" : "Dark"} mode</span>}
      </button>

      {/* Logout */}
      <button
        onClick={logout}
        title="Sign out"
        className={`flex items-center gap-2.5 text-xs font-medium px-3 py-2 rounded-xl text-slate-500 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-500/[0.06] transition-all duration-200 cursor-pointer select-none ${
          collapsed ? "md:justify-center" : ""
        }`}
      >
        <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0 0 13.5 3h-6a2.25 2.25 0 0 0-2.25 2.25v13.5A2.25 2.25 0 0 0 7.5 21h6a2.25 2.25 0 0 0 2.25-2.25V15m3 0 3-3m0 0-3-3m3 3H9" />
        </svg>
        {!collapsed && <span className="whitespace-nowrap">Sign out</span>}
      </button>

      {/* Collapse toggle (desktop only) */}
      <button
        onClick={() => setCollapsed((c) => !c)}
        title={collapsed ? "Expand" : "Collapse"}
        className={`hidden md:flex items-center gap-2.5 text-xs font-medium px-3 py-2 rounded-xl text-slate-500 hover:text-slate-900 dark:hover:text-slate-200 hover:bg-slate-900/[0.04] dark:hover:bg-white/[0.05] transition-all duration-200 cursor-pointer select-none ${
          collapsed ? "justify-center" : ""
        }`}
      >
        <svg
          className={`w-4 h-4 shrink-0 transition-transform duration-300 ${collapsed ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={1.8}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5 8.25 12l7.5-7.5" />
        </svg>
        {!collapsed && <span className="whitespace-nowrap">Collapse</span>}
      </button>
    </nav>
  );
}
