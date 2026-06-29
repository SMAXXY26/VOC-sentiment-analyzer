"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { login } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await login(username, password);
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-[80vh] flex items-center justify-center">
      <form onSubmit={onSubmit} className="w-full max-w-sm glass rounded-2xl p-7 border border-slate-200/70 dark:border-white/[0.07] animate-scale-in">
        <h1 className="text-lg font-semibold text-slate-900 dark:text-white tracking-tight">Sign in</h1>
        <p className="text-[11px] text-slate-500 mt-0.5 font-mono mb-6">CX Analyzer dashboard</p>

        <label className="block text-[11px] font-mono uppercase tracking-wider text-slate-500 mb-1.5">Username</label>
        <input
          type="text" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus autoComplete="username"
          className="w-full glass rounded-xl px-3 py-2 text-sm text-slate-800 dark:text-slate-200 focus:outline-none focus:border-indigo-500/50 mb-4"
        />

        <label className="block text-[11px] font-mono uppercase tracking-wider text-slate-500 mb-1.5">Password</label>
        <input
          type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password"
          className="w-full glass rounded-xl px-3 py-2 text-sm text-slate-800 dark:text-slate-200 focus:outline-none focus:border-indigo-500/50 mb-5"
        />

        {error && <p className="text-xs text-red-500 mb-4">{error}</p>}

        <button
          type="submit" disabled={busy || !username || !password}
          className="w-full px-4 py-2.5 bg-indigo-500/90 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-xl transition-all cursor-pointer"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
