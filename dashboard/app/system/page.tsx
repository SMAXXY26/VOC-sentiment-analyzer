"use client";
import useSWR from "swr";
import { fetchSystem } from "@/lib/api";
import { SystemGauges } from "@/components/SystemGauges";

function StatCard({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="glass rounded-2xl p-4 glass-hover">
      <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-2">{label}</p>
      <p className={`text-xl font-bold tabular-nums ${accent ? "text-indigo-600 dark:text-indigo-300" : "text-slate-800 dark:text-slate-200"}`}>{value}</p>
    </div>
  );
}

export default function SystemPage() {
  const { data, error } = useSWR("system", fetchSystem, { refreshInterval: 3000 });

  return (
    <div className="space-y-4 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between py-2">
        <div>
          <h1 className="text-lg font-semibold text-slate-900 dark:text-white tracking-tight">System Health</h1>
          <p className="text-xs text-slate-500 mt-0.5">Hardware utilization · refreshes every 3s</p>
        </div>
        <div className="flex items-center gap-2 glass rounded-xl px-3 py-1.5">
          <span className="relative flex h-2 w-2">
            <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-60 ${error ? "bg-red-400" : "bg-emerald-400"}`} />
            <span className={`relative inline-flex rounded-full h-2 w-2 ${error ? "bg-red-400" : "bg-emerald-400"}`} />
          </span>
          <span className="text-xs text-slate-600 dark:text-slate-400">{error ? "API unreachable" : "Connected"}</span>
        </div>
      </div>

      {error && (
        <div className="glass rounded-2xl p-4 border-l-2 border-red-500/40 text-red-600 dark:text-red-300 text-sm animate-fade-in">
          Cannot reach API — make sure the FastAPI server is running on port 8080.
        </div>
      )}

      {data ? (
        <>
          {/* Gauges */}
          <SystemGauges data={data} />

          {/* Detail stats */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <StatCard label="RAM Total" value={`${data.ram_total_gb} GB`} />
            <StatCard label="RAM Used" value={`${data.ram_used_gb} GB`} accent />
            <StatCard
              label="GPU VRAM Total"
              value={data.gpu_total_mb != null ? `${(data.gpu_total_mb / 1024).toFixed(1)} GB` : "N/A"}
            />
            <StatCard
              label="GPU VRAM Used"
              value={data.gpu_used_mb != null ? `${data.gpu_used_mb} MB` : "N/A"}
              accent={data.gpu_used_mb != null}
            />
          </div>

          {/* Endpoint info */}
          <div className="rounded-2xl glass glass-hover p-5">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-4">vLLM Inference</p>
            <div className="grid grid-cols-3 gap-4">
              {[
                { label: "CPU Usage", value: `${data.cpu_percent?.toFixed(1) ?? "—"}%`, high: (data.cpu_percent ?? 0) > 85 },
                { label: "RAM Usage", value: `${((data.ram_used_gb / data.ram_total_gb) * 100).toFixed(1)}%`, high: (data.ram_used_gb / data.ram_total_gb) > 0.85 },
                { label: "GPU Utilization", value: data.gpu_util_percent != null ? `${data.gpu_util_percent}%` : "N/A", high: (data.gpu_util_percent ?? 0) > 85 },
              ].map((s) => (
                <div key={s.label} className="text-center">
                  <p className={`text-2xl font-bold tabular-nums ${s.high ? "text-red-600 dark:text-red-300" : "text-slate-800 dark:text-slate-200"}`}>{s.value}</p>
                  <p className="text-[11px] text-slate-400 dark:text-slate-600 mt-1">{s.label}</p>
                </div>
              ))}
            </div>
          </div>
        </>
      ) : !error ? (
        <div className="flex items-center justify-center py-32">
          <div className="flex flex-col items-center gap-3">
            <div className="w-8 h-8 border-2 border-indigo-500/30 border-t-indigo-400 rounded-full animate-spin" />
            <p className="text-slate-500 text-sm">Connecting to API…</p>
          </div>
        </div>
      ) : null}
    </div>
  );
}
