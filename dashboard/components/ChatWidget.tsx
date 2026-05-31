"use client";
import { useState } from "react";
import { startChat, ChatMessage } from "@/lib/api";
import { ChatWindow } from "./ChatWindow";

type State = "closed" | "login" | "chat";

export function ChatWidget() {
  const [state, setState] = useState<State>("closed");
  const [sessionId, setSessionId] = useState("");
  const [customerName, setCustomerName] = useState("");
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
      if (res.reply) setInitialMessages([{ role: "assistant", content: res.reply }]);
      setState("chat");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  function reset() {
    setState("login");
    setSessionId("");
    setInitialMessages([]);
    setUsername("");
    setPassword("");
    setError("");
  }

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col items-end gap-2">
      {/* Expanded panel */}
      {state !== "closed" && (
        <div className="w-[360px] rounded-2xl overflow-hidden bg-[#0a0f1e]/95 backdrop-blur-2xl border border-white/[0.10] shadow-2xl shadow-black/50 animate-fade-in">
          {state === "login" && (
            <div className="p-5">
              <p className="text-sm font-semibold text-white mb-0.5">CX Support Chat</p>
              <p className="text-[11px] text-slate-500 mb-4">Sign in to access your orders and get help.</p>
              <div className="space-y-2.5">
                <input
                  type="text"
                  placeholder="Username (try: alice)"
                  value={username}
                  onChange={e => setUsername(e.target.value)}
                  onKeyDown={e => e.key === "Enter" && login()}
                  className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500/40 transition-colors"
                />
                <input
                  type="password"
                  placeholder="Password (try: pass123)"
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  onKeyDown={e => e.key === "Enter" && login()}
                  className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500/40 transition-colors"
                />
                {error && <p className="text-[11px] text-red-400">{error}</p>}
                <button
                  onClick={login}
                  disabled={loading || !username.trim()}
                  className="w-full py-2 bg-indigo-500/20 hover:bg-indigo-500/30 disabled:opacity-40 disabled:cursor-not-allowed text-indigo-300 text-sm font-medium rounded-xl border border-indigo-500/25 transition-all cursor-pointer"
                >
                  {loading ? "Connecting…" : "Start Chat"}
                </button>
              </div>
            </div>
          )}
          {state === "chat" && (
            <>
              <div className="px-4 pt-3 pb-0">
                <p className="text-[11px] text-slate-500">
                  Signed in as <span className="text-slate-300 font-medium">{customerName}</span>
                </p>
              </div>
              <ChatWindow
                sessionId={sessionId}
                initialMessages={initialMessages}
                onEnd={reset}
                compact
              />
            </>
          )}
        </div>
      )}

      {/* Bubble button */}
      <button
        onClick={() => setState(s => s === "closed" ? "login" : "closed")}
        className="w-12 h-12 rounded-full bg-indigo-500/20 hover:bg-indigo-500/30 border border-indigo-500/30 flex items-center justify-center shadow-lg shadow-indigo-500/20 transition-all cursor-pointer"
        aria-label="Open support chat"
      >
        {state === "closed" ? (
          <svg className="w-5 h-5 text-indigo-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
          </svg>
        ) : (
          <svg className="w-4 h-4 text-indigo-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
          </svg>
        )}
      </button>
    </div>
  );
}
