"use client";
import useSWR from "swr";
import { fetchSystem } from "@/lib/api";
import { SystemGauges } from "@/components/SystemGauges";

export default function SystemPage() {
  const { data, error } = useSWR("system", fetchSystem, { refreshInterval: 3000 });

  return (
    <div className="max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold text-white">System Stats</h1>
        <span className="text-xs text-gray-500">Refreshes every 3s</span>
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-800 rounded-lg p-4 mb-6 text-red-300 text-sm">
          Cannot reach API — make sure the FastAPI server is running on port 8080.
        </div>
      )}

      {data ? (
        <>
          <SystemGauges data={data} />
          <div className="mt-6 grid grid-cols-2 md:grid-cols-4 gap-4">
            <Stat label="RAM Total" value={`${data.ram_total_gb} GB`} />
            <Stat label="RAM Used" value={`${data.ram_used_gb} GB`} />
            <Stat label="GPU VRAM Total" value={data.gpu_total_mb != null ? `${Math.round(data.gpu_total_mb / 1024)} GB` : "N/A"} />
            <Stat label="GPU VRAM Used" value={data.gpu_used_mb != null ? `${data.gpu_used_mb} MB` : "N/A"} />
          </div>
        </>
      ) : (
        <p className="text-gray-500 text-sm text-center py-12">Connecting to API…</p>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className="text-lg font-semibold text-gray-200">{value}</p>
    </div>
  );
}
