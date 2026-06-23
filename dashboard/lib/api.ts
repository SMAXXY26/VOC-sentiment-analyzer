export interface FeedbackAnalysis {
  normalized: { original: string; normalized: string; language: string; word_count: number };
  redacted: { text: string; pii_types_found: string[] };
  enrichment: { summary: string; key_topics: string[]; entities: string[]; context: string };
  taxonomy: { category: string; subcategory: string; confidence: number };
  sentiment: { sentiment: string; emotions: string[]; intensity: number };
  signals: { churn_risk: boolean; upsell_opportunity: boolean; feature_requests: string[]; bug_reports: string[]; competitor_mentions: string[] };
  risk: { escalate: boolean; risk_level: string; reason: string; suggested_action: string };
  executive: { executive_summary: string; key_action_items: string[]; priority_recommendations: string[]; overall_health_score: number };
  experience?: {
    csi: {
      product_quality: number; delivery: number; commercial_process: number; marketing_performance: number;
      complaint_handling: number; company_personnel: number; technical_support: number; relation_building: number;
    };
    cxi: { satisfaction: number; loyalty: number; advocacy: number; value_for_money: number };
    csi_percent: number;
    cxi_percent: number;
  };
}

// Flat shape stored in Qdrant (used by /analyses)
export interface AnalysisItem {
  summary: string;
  category: string;
  subcategory?: string;
  sentiment: string;
  intensity: number;
  risk_level: string;
  escalate: boolean;
  churn_risk: boolean;
  feature_requests: string[];
  emotions: string[];
  source: string;
  raw_text?: string;
  feedback_id?: string;
  score?: number;
}

export interface AnalysesSummary {
  total: number;
  sentiment_distribution: Record<string, number>;
  escalation_count: number;
  churn_count: number;
  avg_intensity: number;
  avg_csi: number;
  avg_cxi: number;
  top_categories: Record<string, number>;
  top_feature_requests: string[];
  feature_request_counts?: Record<string, number>;
  word_frequencies?: Record<string, number>;
  daily_counts?: Record<string, number>;
  error?: string;
}

export interface SystemStats {
  cpu_percent: number;
  ram_used_gb: number;
  ram_total_gb: number;
  ram_percent: number;
  gpu_used_mb: number | null;
  gpu_total_mb: number | null;
  gpu_util_percent: number | null;
}

import { authHeaders, clearToken } from "./auth";

const BASE = "/api";

// Wraps fetch: attaches the bearer token and, on 401, clears the session and
// bounces to the login page.
async function authFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const res = await fetch(input, {
    ...init,
    headers: { ...(init.headers as Record<string, string> | undefined), ...authHeaders() },
  });
  if (res.status === 401 && typeof window !== "undefined") {
    clearToken();
    if (!window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
  }
  return res;
}

export interface SearchFilters {
  category?: string;
  sentiment?: string;
  risk_level?: string;
  escalate?: boolean;
  churn_risk?: boolean;
}

export async function fetchAnalyses(
  limit = 50,
  q?: string,
  filters?: SearchFilters,
): Promise<{ items: AnalysisItem[]; total: number }> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (q) params.set("q", q);
  if (filters) {
    for (const [k, v] of Object.entries(filters)) {
      if (v !== undefined && v !== "" && v !== false) params.set(k, String(v));
    }
  }
  const res = await authFetch(`${BASE}/analyses?${params}`);
  return res.json();
}

export async function fetchSummary(): Promise<AnalysesSummary> {
  const res = await authFetch(`${BASE}/analyses/summary`);
  return res.json();
}

export async function fetchSystem(): Promise<SystemStats> {
  const res = await authFetch(`${BASE}/system`);
  return res.json();
}

export async function analyzeText(text: string): Promise<FeedbackAnalysis> {
  const res = await authFetch(`${BASE}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
    cache: "no-store",  // never cache — analyze page is for testing
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ── Chat API ───────────────────────────────────────────────────────────────────

export interface ChatResponse {
  session_id: string;
  reply: string;
  quick_replies: string[];
  customer_name?: string;
  customer_tier?: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export async function startChat(
  customer_id: string,
  password?: string,
  message?: string,
): Promise<ChatResponse> {
  const res = await authFetch(`${BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ customer_id, password, message }),
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function sendMessage(
  session_id: string,
  message: string,
): Promise<ChatResponse> {
  const res = await authFetch(`${BASE}/chat/${session_id}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function endChat(session_id: string): Promise<void> {
  await authFetch(`${BASE}/chat/${session_id}`, { method: "DELETE", cache: "no-store" });
}
