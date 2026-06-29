"use client";
import { useState } from "react";
import { startChat, ChatMessage } from "@/lib/api";
import { getUser } from "@/lib/auth";
import { ChatWindow } from "./ChatWindow";

type State = "closed" | "connecting" | "error" | "chat";

export function ChatWidget() {
  const [state, setState] = useState<State>("closed");
  const [sessionId, setSessionId] = useState("");
  const [customerName, setCustomerName] = useState("");
  const [error, setError] = useState("");
  const [initialMessages, setInitialMessages] = useState<ChatMessage[]>([]);

  async function open() {
    const user = getUser();
    if (!user) return;
    setState("connecting");
    try {
      const res = await startChat(user);
      setSessionId(res.session_id);
      setCustomerName(res.customer_name || user);
      setInitialMessages(res.reply ? [{ role: "assistant", content: res.reply }] : []);
      setState("chat");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Couldn't start chat");
      setState("error");
    }
  }

  function reset() {
    setState("closed");
    setSessionId("");
    setInitialMessages([]);
    setError("");
  }

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col items-end gap-2">
      {/* Expanded panel */}
      {state !== "closed" && (
        <div className="w-[360px] max-w-[calc(100vw-2rem)] rounded-2xl overflow-hidden bg-white/95 dark:bg-[#0a0f1e]/95 backdrop-blur-[48px] border border-white/60 dark:border-white/[0.10] shadow-2xl shadow-black/20 dark:shadow-black/50 animate-fade-in">
          {state === "connecting" && (
            <div className="p-8 flex flex-col items-center justify-center gap-3">
              <div className="w-6 h-6 border-2 border-indigo-500/30 border-t-indigo-400 rounded-full animate-spin" />
              <p className="text-[11px] text-slate-500">Starting your chat…</p>
            </div>
          )}
          {state === "error" && (
            <div className="p-5 flex flex-col gap-3">
              <p className="text-sm font-semibold text-slate-900 dark:text-white">Chat unavailable</p>
              <p className="text-[11px] text-red-400">{error}</p>
              <button
                onClick={reset}
                className="text-[11px] text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 transition-colors cursor-pointer"
              >
                Dismiss
              </button>
            </div>
          )}
          {state === "chat" && (
            <>
              <div className="px-4 pt-3 pb-0">
                <p className="text-[11px] text-slate-500">
                  Signed in as <span className="text-slate-700 dark:text-slate-300 font-medium">{customerName}</span>
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
        onClick={() => state === "closed" ? open() : reset()}
        className="w-12 h-12 rounded-full bg-indigo-500/20 hover:bg-indigo-500/30 border border-indigo-500/30 flex items-center justify-center shadow-lg shadow-indigo-500/20 transition-all cursor-pointer"
        aria-label="Open support chat"
      >
        {state === "closed" ? (
          <svg className="w-5 h-5 text-indigo-600 dark:text-indigo-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
          </svg>
        ) : (
          <svg className="w-4 h-4 text-indigo-600 dark:text-indigo-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
          </svg>
        )}
      </button>
    </div>
  );
}
