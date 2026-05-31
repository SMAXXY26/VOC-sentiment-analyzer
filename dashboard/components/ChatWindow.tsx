"use client";
import { useState, useRef, useEffect } from "react";
import { sendMessage, endChat, ChatMessage } from "@/lib/api";

const COMPLEX_SIGNALS = new Set([
  "why","explain","issue","complaint","escalate","broken","damaged",
  "refund","wrong","missing","urgent","angry","terrible","worst",
  "disappointed","frustrated","lost","impossible","unacceptable","fraud",
]);

function inferModel(text: string): "1.5B" | "7B" {
  const words = text.toLowerCase().split(/\s+/);
  const isComplex = words.length > 20 || words.some(w => COMPLEX_SIGNALS.has(w));
  return isComplex ? "7B" : "1.5B";
}

function TypingDots() {
  return (
    <div className="flex items-center gap-1 px-3 py-2">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-pulse"
          style={{ animationDelay: `${i * 150}ms` }}
        />
      ))}
    </div>
  );
}

function ModelChip({ model }: { model: "1.5B" | "7B" }) {
  return (
    <span className={`text-[9px] font-mono px-1.5 py-0.5 rounded-full border ${
      model === "1.5B"
        ? "text-emerald-400 border-emerald-500/30 bg-emerald-500/10"
        : "text-violet-400 border-violet-500/30 bg-violet-500/10"
    }`}>
      {model === "1.5B" ? "Draft 1.5B" : "Full 7B"}
    </span>
  );
}

interface Props {
  sessionId: string;
  initialMessages?: ChatMessage[];
  onEnd?: () => void;
  compact?: boolean;
}

export function ChatWindow({ sessionId, initialMessages = [], onEnd, compact = false }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [lastModel, setLastModel] = useState<"1.5B" | "7B">("7B");
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function send() {
    const text = input.trim();
    if (!text || loading) return;
    const model = inferModel(text);
    setLastModel(model);
    setMessages(m => [...m, { role: "user", content: text }]);
    setInput("");
    setLoading(true);
    try {
      const res = await sendMessage(sessionId, text);
      setMessages(m => [...m, { role: "assistant", content: res.reply }]);
    } catch {
      setMessages(m => [...m, { role: "assistant", content: "Sorry, something went wrong. Please try again." }]);
    } finally {
      setLoading(false);
    }
  }

  async function handleEnd() {
    await endChat(sessionId).catch(() => {});
    onEnd?.();
  }

  return (
    <div className={`flex flex-col ${compact ? "h-[460px]" : "h-full"}`}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-white/[0.06] shrink-0">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute h-full w-full rounded-full bg-emerald-400 opacity-50" />
            <span className="relative h-2 w-2 rounded-full bg-emerald-400" />
          </span>
          <span className="text-xs font-medium text-slate-300">CX Support</span>
          <ModelChip model={lastModel} />
        </div>
        <button
          onClick={handleEnd}
          className="text-[10px] text-slate-600 hover:text-slate-400 transition-colors cursor-pointer"
        >
          End chat
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2.5">
        {messages.length === 0 && (
          <p className="text-xs text-slate-600 text-center mt-8">
            Ask me about your orders, returns, or any product issues.
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[85%] text-xs rounded-2xl px-3 py-2 leading-relaxed ${
              m.role === "user"
                ? "bg-indigo-500/20 text-indigo-100 border border-indigo-500/20 rounded-tr-sm"
                : "bg-white/[0.05] text-slate-200 border border-white/[0.06] rounded-tl-sm"
            }`}>
              {m.content}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-white/[0.05] border border-white/[0.06] rounded-2xl rounded-tl-sm">
              <TypingDots />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="shrink-0 px-3 pb-3 pt-2 border-t border-white/[0.06]">
        <div className="flex gap-2 items-end">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder="Type a message…"
            rows={1}
            className="flex-1 resize-none bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500/40 transition-colors max-h-24 overflow-y-auto"
            style={{ minHeight: "36px" }}
          />
          <button
            onClick={send}
            disabled={loading || !input.trim()}
            className="flex items-center justify-center w-8 h-8 bg-indigo-500/20 hover:bg-indigo-500/30 disabled:opacity-40 disabled:cursor-not-allowed border border-indigo-500/25 rounded-xl transition-all cursor-pointer shrink-0"
          >
            <svg className="w-3.5 h-3.5 text-indigo-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 12 3.269 3.125A59.769 59.769 0 0 1 21.485 12 59.768 59.768 0 0 1 3.27 20.875L5.999 12Zm0 0h7.5" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
