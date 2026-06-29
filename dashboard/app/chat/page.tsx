"use client";
import { useEffect, useState } from "react";
import { startChat, endChat, ChatMessage } from "@/lib/api";
import { getUser } from "@/lib/auth";
import { ChatWindow } from "@/components/ChatWindow";

export default function ChatPage() {
  const [sessionId, setSessionId] = useState("");
  const [customerName, setCustomerName] = useState("");
  const [customerTier, setCustomerTier] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [initialMessages, setInitialMessages] = useState<ChatMessage[]>([]);

  useEffect(() => {
    const user = getUser();
    if (!user) { setLoading(false); return; }
    startChat(user)
      .then(res => {
        setSessionId(res.session_id);
        setCustomerName(res.customer_name || user);
        setCustomerTier(res.customer_tier || "");
        if (res.reply) setInitialMessages([{ role: "assistant", content: res.reply }]);
      })
      .catch(e => setError(e instanceof Error ? e.message : "Couldn't start chat"))
      .finally(() => setLoading(false));
  }, []);

  async function reset() {
    if (sessionId) await endChat(sessionId).catch(() => {});
    setSessionId("");
    setInitialMessages([]);
    setCustomerName("");
    setCustomerTier("");
    setError("");
    setLoading(true);
    const user = getUser();
    if (!user) { setLoading(false); return; }
    startChat(user)
      .then(res => {
        setSessionId(res.session_id);
        setCustomerName(res.customer_name || user);
        setCustomerTier(res.customer_tier || "");
        if (res.reply) setInitialMessages([{ role: "assistant", content: res.reply }]);
      })
      .catch(e => setError(e instanceof Error ? e.message : "Couldn't start chat"))
      .finally(() => setLoading(false));
  }

  return (
    <div className="max-w-2xl mx-auto h-full flex flex-col animate-fade-in">
      <div className="py-2 mb-4 shrink-0">
        <h1 className="text-lg font-semibold text-slate-900 dark:text-white tracking-tight">Support Chat</h1>
        <p className="text-xs text-slate-500 mt-0.5">Agentic customer support · cascade routing · EDBMS-backed</p>
      </div>

      {loading ? (
        <div className="flex-1 glass rounded-2xl flex items-center justify-center gap-3">
          <div className="w-5 h-5 border-2 border-indigo-500/30 border-t-indigo-400 rounded-full animate-spin" />
          <p className="text-sm text-slate-500">Starting session…</p>
        </div>
      ) : error ? (
        <div className="glass rounded-2xl p-6 text-center">
          <p className="text-sm text-red-500 mb-3">{error}</p>
          <button onClick={() => { setError(""); setLoading(true); reset(); }} className="text-xs text-indigo-500 hover:underline cursor-pointer">Retry</button>
        </div>
      ) : (
        <div className="glass rounded-2xl overflow-hidden flex-1" style={{ minHeight: "500px" }}>
          <div className="flex items-center justify-between px-5 py-3 border-b border-white/30 dark:border-white/[0.06] shrink-0">
            <div className="flex items-center gap-3">
              <div className="w-7 h-7 rounded-lg bg-indigo-500/15 border border-indigo-500/25 flex items-center justify-center">
                <span className="text-[10px] font-bold text-indigo-500 dark:text-indigo-400">{customerName[0]?.toUpperCase()}</span>
              </div>
              <div>
                <p className="text-sm font-medium text-slate-900 dark:text-white">{customerName}</p>
                {customerTier && <p className="text-[10px] text-slate-500 capitalize">{customerTier} member</p>}
              </div>
            </div>
            <button onClick={reset} className="text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors cursor-pointer">
              New session
            </button>
          </div>
          <div className="h-[calc(100%-52px)]">
            <ChatWindow sessionId={sessionId} initialMessages={initialMessages} onEnd={reset} />
          </div>
        </div>
      )}
    </div>
  );
}
