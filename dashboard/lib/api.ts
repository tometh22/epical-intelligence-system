const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface AgentStatus {
  status: "idle" | "running" | "completed" | "error";
  message?: string;
  started_at?: string;
  completed_at?: string;
  result?: AgentResult;
}

export interface MergeStats {
  youscan: number;
  scrapping: number;
  total_unified: number;
  duplicates_removed: number;
}

export interface AgentResult {
  summary?: Record<string, unknown>;
  output_files?: { docx?: string; json?: string; html?: string; qa?: string };
  data_quality_warnings?: string[];
  metrics?: Record<string, string | number>;
  source_counts?: Record<string, number>;
  merge_stats?: MergeStats;
  qa_status?: string;  // "APROBADO" | "REVISAR" | "NO ENVIAR"
  qa_errors?: number;
  qa_warnings?: number;
}

export interface ReportBuilderBrief {
  evento: string;
  eje_1: string;
  eje_2: string;
  eje_3: string;
  hipotesis: string;
  decision: string;
  limitaciones: string;
}

export interface RunReportBuilderInput {
  primaryFile: File;
  clientName: string;
  reportingPeriod: string;
  brief: ReportBuilderBrief;
  secondaryFile?: File;
  logoFile?: File;
  theme?: string;
  brandColor?: string;
  reportType?: string;
}

export async function runReportBuilder(
  input: RunReportBuilderInput,
): Promise<{ status: string; message: string }> {
  const formData = new FormData();
  formData.append("file", input.primaryFile);
  formData.append("client_name", input.clientName);
  formData.append("period", input.reportingPeriod);
  formData.append("brief_evento", input.brief.evento);
  formData.append("brief_eje_1", input.brief.eje_1);
  formData.append("brief_eje_2", input.brief.eje_2);
  formData.append("brief_eje_3", input.brief.eje_3);
  formData.append("brief_hipotesis", input.brief.hipotesis);
  formData.append("brief_decision", input.brief.decision);
  formData.append("brief_limitaciones", input.brief.limitaciones);
  if (input.secondaryFile) formData.append("file2", input.secondaryFile);
  if (input.logoFile) formData.append("logo", input.logoFile);
  if (input.theme) formData.append("theme", input.theme);
  if (input.brandColor) formData.append("brand_color", input.brandColor);
  if (input.reportType) formData.append("report_type", input.reportType);

  const res = await fetch(`${BASE_URL}/api/agents/report-builder/run`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(error.detail || `HTTP ${res.status}`);
  }

  return res.json();
}

export async function getReportBuilderStatus(): Promise<AgentStatus> {
  const res = await fetch(`${BASE_URL}/api/agents/report-builder/status`);

  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }

  return res.json();
}

export async function getAgentLogs(agentName: string): Promise<string> {
  const res = await fetch(`${BASE_URL}/api/logs/${agentName}`);

  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }

  const data = await res.json();
  return data.logs || data.content || JSON.stringify(data, null, 2);
}

export function getDownloadUrl(path: string): string {
  return `${BASE_URL}${path}`;
}
