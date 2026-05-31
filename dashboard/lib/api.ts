export interface FeedbackAnalysis {
  normalized: { original: string; normalized: string; language: string; word_count: number };
  redacted: { text: string; pii_types_found: string[] };
  enrichment: { summary: string; key_topics: string[]; entities: string[]; context: string };
  taxonomy: { category: string; subcategory: string; confidence: number };
  sentiment: { sentiment: string; emotions: string[]; intensity: number };
  signals: { churn_risk: boolean; upsell_opportunity: boolean; feature_requests: string[]; bug_reports: string[]; competitor_mentions: string[] };
  risk: { escalate: boolean; risk_level: string; reason: string; suggested_action: string };
  executive: { executive_summary: string; key_action_items: string[]; priority_recommendations: string[]; overall_health_score: number };
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
  top_categories: Record<string, number>;
  top_feature_requests: string[];
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

const BASE = "/api";

export async function fetchAnalyses(limit = 50, q?: string): Promise<{ items: AnalysisItem[]; total: number }> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (q) params.set("q", q);
  const res = await fetch(`${BASE}/analyses?${params}`);
  return res.json();
}

export async function fetchSummary(): Promise<AnalysesSummary> {
  const res = await fetch(`${BASE}/analyses/summary`);
  return res.json();
}

export async function fetchSystem(): Promise<SystemStats> {
  const res = await fetch(`${BASE}/system`);
  return res.json();
}

export async function analyzeText(text: string): Promise<FeedbackAnalysis> {
  const res = await fetch(`${BASE}/analyze`, {
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
  const res = await fetch(`${BASE}/chat`, {
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
  const res = await fetch(`${BASE}/chat/${session_id}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function endChat(session_id: string): Promise<void> {
  await fetch(`${BASE}/chat/${session_id}`, { method: "DELETE", cache: "no-store" });
}
