"use client";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Nav } from "@/components/Nav";
import { ChatWidget } from "@/components/ChatWidget";
import { getToken } from "@/lib/auth";

/**
 * Client-side auth gate. Redirects to /login when no token is present, and owns
 * the app chrome (Nav + ChatWidget) so the login page renders without it.
 * Backend endpoints are independently protected — this is just UX.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [checked, setChecked] = useState(false);
  const isLogin = pathname === "/login";

  useEffect(() => {
    if (!isLogin && !getToken()) {
      router.replace("/login");
    } else {
      setChecked(true);
    }
  }, [isLogin, pathname, router]);

  // Login page renders bare — no nav/chat chrome.
  if (isLogin) return <>{children}</>;

  // Avoid flashing protected content before the token check resolves.
  if (!checked) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-indigo-500/30 border-t-indigo-400 rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <>
      <div className="flex flex-col md:flex-row min-h-screen md:h-screen">
        <Nav />
        <main className="flex-1 min-w-0 md:h-screen overflow-y-auto px-4 py-4">{children}</main>
      </div>
      <ChatWidget />
    </>
  );
}
