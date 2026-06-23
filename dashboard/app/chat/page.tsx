"use client";
import { useState } from "react";
import { startChat, ChatMessage } from "@/lib/api";
import { ChatWindow } from "@/components/ChatWindow";

export default function ChatPage() {
  const [sessionId, setSessionId] = useState("");
  const [customerName, setCustomerName] = useState("");
  const [customerTier, setCustomerTier] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [initialMessages, setInitialMessages] = useState<ChatMessage[]>([]);

  async function login() {
    if (!username.trim()) return;
    setLoading(true);
    setError("");
    try {
      const res = await startChat(username.trim(), password || undefined);
      setSessionId(res.session_id);
      setCustomerName(res.customer_name || username);
      setCustomerTier(res.customer_tier || "");
      if (res.reply) setInitialMessages([{ role: "assistant", content: res.reply }]);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  function reset() {
    setSessionId("");
    setInitialMessages([]);
    setUsername("");
    setPassword("");
    setError("");
    setCustomerName("");
    setCustomerTier("");
  }

  return (
    <div className="max-w-2xl mx-auto animate-fade-in">
      <div className="py-2 mb-4">
        <h1 className="text-lg font-semibold text-slate-900 dark:text-white tracking-tight">Support Chat</h1>
        <p className="text-xs text-slate-500 mt-0.5">
          Agentic customer support · cascade routing · EDBMS-backed
        </p>
      </div>

      {!sessionId ? (
        /* Login form */
        <div className="glass rounded-2xl p-6 max-w-sm mx-auto">
          <div className="mb-5">
            <div className="w-10 h-10 rounded-xl bg-indigo-500/15 border border-indigo-500/25 flex items-center justify-center mb-3">
              <svg className="w-5 h-5 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
              </svg>
            </div>
            <p className="text-sm font-semibold text-slate-900 dark:text-white">Sign in to chat</p>
            <p className="text-[11px] text-slate-500 mt-0.5">Demo accounts: alice, bob, carol · password: pass123</p>
          </div>
          <div className="space-y-3">
            <div>
              <label className="text-[10px] text-slate-500 uppercase tracking-widest font-mono mb-1.5 block">Username</label>
              <input
                type="text"
                placeholder="alice"
                value={username}
                onChange={e => setUsername(e.target.value)}
                onKeyDown={e => e.key === "Enter" && login()}
                autoFocus
                className="w-full bg-slate-900/[0.04] dark:bg-white/[0.04] border border-slate-200/70 dark:border-white/[0.08] rounded-xl px-3 py-2.5 text-sm text-slate-800 dark:text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500/40 transition-colors"
              />
            </div>
            <div>
              <label className="text-[10px] text-slate-500 uppercase tracking-widest font-mono mb-1.5 block">Password</label>
              <input
                type="password"
                placeholder="pass123"
                value={password}
                onChange={e => setPassword(e.target.value)}
                onKeyDown={e => e.key === "Enter" && login()}
                className="w-full bg-slate-900/[0.04] dark:bg-white/[0.04] border border-slate-200/70 dark:border-white/[0.08] rounded-xl px-3 py-2.5 text-sm text-slate-800 dark:text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500/40 transition-colors"
              />
            </div>
            {error && (
              <p className="text-[11px] text-red-400 flex items-center gap-1">
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
                </svg>
                {error}
              </p>
            )}
            <button
              onClick={login}
              disabled={loading || !username.trim()}
              className="w-full py-2.5 bg-indigo-500/20 hover:bg-indigo-500/30 disabled:opacity-40 disabled:cursor-not-allowed text-indigo-600 dark:text-indigo-300 text-sm font-medium rounded-xl border border-indigo-500/25 transition-all cursor-pointer"
            >
              {loading ? "Connecting…" : "Start Chat"}
            </button>
          </div>
        </div>
      ) : (
        /* Chat window */
        <div className="glass rounded-2xl overflow-hidden" style={{ height: "calc(100vh - 180px)", minHeight: "500px" }}>
          <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200/70 dark:border-white/[0.06]">
            <div className="flex items-center gap-3">
              <div className="w-7 h-7 rounded-lg bg-indigo-500/15 border border-indigo-500/25 flex items-center justify-center">
                <span className="text-[10px] font-bold text-indigo-400">{customerName[0]?.toUpperCase()}</span>
              </div>
              <div>
                <p className="text-sm font-medium text-slate-900 dark:text-white">{customerName}</p>
                {customerTier && (
                  <p className="text-[10px] text-slate-500 capitalize">{customerTier} member</p>
                )}
              </div>
            </div>
            <button
              onClick={reset}
              className="text-xs text-slate-400 dark:text-slate-600 hover:text-slate-600 dark:hover:text-slate-400 transition-colors cursor-pointer"
            >
              Sign out
            </button>
          </div>
          <div className="h-[calc(100%-52px)]">
            <ChatWindow
              sessionId={sessionId}
              initialMessages={initialMessages}
              onEnd={reset}
            />
          </div>
        </div>
      )}
    </div>
  );
}
