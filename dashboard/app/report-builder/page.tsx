"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import FileUpload from "@/components/FileUpload";
import StatusBadge from "@/components/StatusBadge";
import {
  runReportBuilder,
  getReportBuilderStatus,
  getDownloadUrl,
  type AgentStatus,
} from "@/lib/api";

export default function ReportBuilderPage() {
  const [primaryFile, setPrimaryFile] = useState<File | null>(null);
  const [secondaryFile, setSecondaryFile] = useState<File | null>(null);
  const [clientName, setClientName] = useState("");
  const [reportingPeriod, setReportingPeriod] = useState("");
  const [logoFile, setLogoFile] = useState<File | null>(null);
  const [theme, setTheme] = useState("dark");
  const [brandColor, setBrandColor] = useState("#FF1B6B");
  const [reportType, setReportType] = useState("crisis");
  const [briefEvento, setBriefEvento] = useState("");
  const [briefEje1, setBriefEje1] = useState("");
  const [briefEje2, setBriefEje2] = useState("");
  const [briefEje3, setBriefEje3] = useState("");
  const [briefHipotesis, setBriefHipotesis] = useState("");
  const [briefDecision, setBriefDecision] = useState("");
  const [briefLimitaciones, setBriefLimitaciones] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [agentStatus, setAgentStatus] = useState<AgentStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => stopPolling();
  }, [stopPolling]);

  const startPolling = useCallback(() => {
    stopPolling();
    pollingRef.current = setInterval(async () => {
      try {
        const status = await getReportBuilderStatus();
        setAgentStatus(status);
        if (status.status === "completed" || status.status === "error") {
          stopPolling();
          setIsSubmitting(false);
          if (status.status === "error") {
            setError(status.message || "Agent encountered an error");
          }
        }
      } catch {
        // Keep polling on network errors
      }
    }, 3000);
  }, [stopPolling]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (
      !primaryFile ||
      !clientName ||
      !reportingPeriod ||
      !briefEvento.trim() ||
      !briefDecision.trim() ||
      !briefEje1.trim()
    ) {
      return;
    }

    setIsSubmitting(true);
    setError(null);
    setAgentStatus({ status: "running" });

    try {
      await runReportBuilder({
        primaryFile,
        clientName,
        reportingPeriod,
        brief: {
          evento: briefEvento,
          eje_1: briefEje1,
          eje_2: briefEje2,
          eje_3: briefEje3,
          hipotesis: briefHipotesis,
          decision: briefDecision,
          limitaciones: briefLimitaciones,
        },
        secondaryFile: secondaryFile || undefined,
        logoFile: logoFile || undefined,
        theme,
        brandColor,
        reportType,
      });
      startPolling();
    } catch (err) {
      setIsSubmitting(false);
      setAgentStatus({ status: "error" });
      setError(err instanceof Error ? err.message : "Failed to start agent");
    }
  };

  const isFormValid =
    primaryFile &&
    clientName.trim() &&
    reportingPeriod.trim() &&
    briefEvento.trim() &&
    briefDecision.trim() &&
    briefEje1.trim();

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-zinc-100">Report Builder</h1>
        <p className="mt-1 text-sm text-zinc-400">
          Upload data files and generate comprehensive client reports
        </p>
      </div>

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-3">
        {/* Form Section */}
        <div className="lg:col-span-2">
          <form onSubmit={handleSubmit} className="space-y-6">
            <div className="rounded-xl border border-zinc-700/50 bg-zinc-800/50 p-6 space-y-6">
              <h2 className="text-lg font-semibold text-zinc-100">
                Data Sources
              </h2>

              <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                <div>
                  <FileUpload
                    label="Export de social listening *"
                    accept=".csv,.xlsx,.xls,.zip"
                    onFileSelect={setPrimaryFile}
                    hint="CSV, Excel o ZIP con menciones de redes."
                  />
                </div>
                <div>
                  <FileUpload
                    label="Export de scraping (opcional)"
                    accept=".csv,.xlsx,.xls,.zip"
                    onFileSelect={setSecondaryFile}
                    hint="Excel multi-hoja (IG, TikTok, Facebook)."
                  />
                </div>
              </div>

              <div className="rounded-lg border border-zinc-700/30 bg-zinc-900/30 p-3">
                <p className="text-xs text-zinc-500">
                  Subí el export de social listening y, opcionalmente, un
                  scraping multi-hoja (Excel). Se unifican en un solo dataset y
                  los duplicados (mismo texto + plataforma + fecha) se remueven
                  automáticamente.
                </p>
              </div>
            </div>

            <div className="rounded-xl border border-zinc-700/50 bg-zinc-800/50 p-6 space-y-4">
              <h2 className="text-lg font-semibold text-zinc-100">
                Report Settings
              </h2>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <label className="block text-sm font-medium text-zinc-300 mb-2">
                    Client Name *
                  </label>
                  <input
                    type="text"
                    value={clientName}
                    onChange={(e) => setClientName(e.target.value)}
                    placeholder="e.g. Acme Corporation"
                    className="w-full rounded-lg border border-zinc-600 bg-zinc-800 px-4 py-2.5 text-sm text-zinc-100 placeholder-zinc-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-zinc-300 mb-2">
                    Reporting Period *
                  </label>
                  <input
                    type="text"
                    value={reportingPeriod}
                    onChange={(e) => setReportingPeriod(e.target.value)}
                    placeholder="e.g. Marzo 2026"
                    className="w-full rounded-lg border border-zinc-600 bg-zinc-800 px-4 py-2.5 text-sm text-zinc-100 placeholder-zinc-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-zinc-700/50 bg-zinc-800/50 p-6 space-y-4">
              <h2 className="text-lg font-semibold text-zinc-100">
                Advanced Settings
              </h2>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <label className="block text-sm font-medium text-zinc-300 mb-2">
                    Theme
                  </label>
                  <div className="flex gap-4">
                    <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
                      <input
                        type="radio"
                        name="theme"
                        value="dark"
                        checked={theme === "dark"}
                        onChange={(e) => setTheme(e.target.value)}
                        className="accent-blue-500"
                      />
                      <span>Dark (Intelligence)</span>
                    </label>
                    <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
                      <input
                        type="radio"
                        name="theme"
                        value="light"
                        checked={theme === "light"}
                        onChange={(e) => setTheme(e.target.value)}
                        className="accent-blue-500"
                      />
                      <span>Light (Corporate)</span>
                    </label>
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-zinc-300 mb-2">
                    Brand Color
                  </label>
                  <div className="flex items-center gap-3">
                    <input
                      type="color"
                      value={brandColor}
                      onChange={(e) => setBrandColor(e.target.value)}
                      className="h-10 w-10 rounded border border-zinc-600 bg-zinc-800 cursor-pointer"
                    />
                    <input
                      type="text"
                      value={brandColor}
                      onChange={(e) => setBrandColor(e.target.value)}
                      placeholder="#FF1B6B"
                      className="w-full rounded-lg border border-zinc-600 bg-zinc-800 px-4 py-2.5 text-sm text-zinc-100 placeholder-zinc-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    />
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <label className="block text-sm font-medium text-zinc-300 mb-2">
                    Report Type
                  </label>
                  <select
                    value={reportType}
                    onChange={(e) => setReportType(e.target.value)}
                    className="w-full rounded-lg border border-zinc-600 bg-zinc-800 px-4 py-2.5 text-sm text-zinc-100 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  >
                    <option value="crisis">Crisis</option>
                    <option value="campaign">Campaign</option>
                    <option value="monitoring">Monitoring</option>
                  </select>
                </div>

                <div>
                  <FileUpload
                    label="Client Logo (optional)"
                    accept=".svg,.png,.jpg,.jpeg"
                    onFileSelect={setLogoFile}
                    hint="SVG or PNG, max 1MB"
                  />
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-zinc-700/50 bg-zinc-800/50 p-6 space-y-5">
              <div>
                <h2 className="text-lg font-semibold text-zinc-100">
                  Brief del análisis
                </h2>
                <p className="mt-1 text-xs text-zinc-500">
                  Antes de generar el informe respondé estas cinco preguntas. Es
                  lo que decide la calidad editorial: el sistema escribe a
                  partir de lo que pongas acá.
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-zinc-300 mb-2">
                  ¿Qué evento o período analizamos y por qué le importa al
                  cliente? *
                </label>
                <textarea
                  value={briefEvento}
                  onChange={(e) => setBriefEvento(e.target.value)}
                  rows={3}
                  placeholder="No el nombre del evento — la razón de negocio detrás. Ej: 'Federico Aguiló necesita decidir si hacer más piezas como la entrevista de Hacedores'."
                  className="w-full rounded-lg border border-zinc-600 bg-zinc-800 px-4 py-2.5 text-sm text-zinc-100 placeholder-zinc-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-zinc-300 mb-2">
                  Tres ejes del análisis *
                </label>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <input
                    type="text"
                    value={briefEje1}
                    onChange={(e) => setBriefEje1(e.target.value)}
                    placeholder="Eje 1"
                    className="w-full rounded-lg border border-zinc-600 bg-zinc-800 px-4 py-2.5 text-sm text-zinc-100 placeholder-zinc-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                  <input
                    type="text"
                    value={briefEje2}
                    onChange={(e) => setBriefEje2(e.target.value)}
                    placeholder="Eje 2"
                    className="w-full rounded-lg border border-zinc-600 bg-zinc-800 px-4 py-2.5 text-sm text-zinc-100 placeholder-zinc-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                  <input
                    type="text"
                    value={briefEje3}
                    onChange={(e) => setBriefEje3(e.target.value)}
                    placeholder="Eje 3"
                    className="w-full rounded-lg border border-zinc-600 bg-zinc-800 px-4 py-2.5 text-sm text-zinc-100 placeholder-zinc-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>
                <p className="mt-1 text-xs text-zinc-500">
                  Eje 1 obligatorio. Si el cliente no los explicitó, inferilos
                  antes de empezar.
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-zinc-300 mb-2">
                  ¿Qué hipótesis previa tiene el cliente sobre lo que va a
                  encontrar?
                </label>
                <textarea
                  value={briefHipotesis}
                  onChange={(e) => setBriefHipotesis(e.target.value)}
                  rows={2}
                  placeholder="El análisis tiene que confirmarla, matizarla o invertirla con evidencia."
                  className="w-full rounded-lg border border-zinc-600 bg-zinc-800 px-4 py-2.5 text-sm text-zinc-100 placeholder-zinc-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-zinc-300 mb-2">
                  ¿Qué decisión concreta tiene que poder tomar después de leer
                  el informe? *
                </label>
                <input
                  type="text"
                  value={briefDecision}
                  onChange={(e) => setBriefDecision(e.target.value)}
                  placeholder="Una sola frase. No 'entender mejor la conversación'."
                  className="w-full rounded-lg border border-zinc-600 bg-zinc-800 px-4 py-2.5 text-sm text-zinc-100 placeholder-zinc-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-zinc-300 mb-2">
                  ¿Qué no vamos a poder responder con este dataset?
                </label>
                <textarea
                  value={briefLimitaciones}
                  onChange={(e) => setBriefLimitaciones(e.target.value)}
                  rows={2}
                  placeholder="Va al informe. Distingue un análisis honesto de uno que infla conclusiones."
                  className="w-full rounded-lg border border-zinc-600 bg-zinc-800 px-4 py-2.5 text-sm text-zinc-100 placeholder-zinc-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={!isFormValid || isSubmitting}
              className={`w-full rounded-xl px-6 py-3 text-sm font-semibold transition-colors ${
                isFormValid && !isSubmitting
                  ? "bg-blue-600 text-white hover:bg-blue-500"
                  : "bg-zinc-700 text-zinc-500 cursor-not-allowed"
              }`}
            >
              {isSubmitting ? (
                <span className="flex items-center justify-center gap-2">
                  <svg
                    className="h-4 w-4 animate-spin"
                    fill="none"
                    viewBox="0 0 24 24"
                  >
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                    />
                  </svg>
                  Generating Report...
                </span>
              ) : (
                "Generate Report"
              )}
            </button>
          </form>
        </div>

        {/* Status Sidebar */}
        <div className="space-y-6">
          <div className="rounded-xl border border-zinc-700/50 bg-zinc-800/50 p-6">
            <h2 className="text-lg font-semibold text-zinc-100 mb-4">
              Agent Status
            </h2>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-zinc-400">Status</span>
                <StatusBadge status={agentStatus?.status || "idle"} />
              </div>
              {agentStatus?.started_at && (
                <div className="flex items-center justify-between">
                  <span className="text-sm text-zinc-400">Started</span>
                  <span className="text-sm text-zinc-300">
                    {agentStatus.started_at}
                  </span>
                </div>
              )}
              {agentStatus?.completed_at && (
                <div className="flex items-center justify-between">
                  <span className="text-sm text-zinc-400">Completed</span>
                  <span className="text-sm text-zinc-300">
                    {agentStatus.completed_at}
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Merge Stats */}
          {agentStatus?.status === "completed" &&
            agentStatus.result?.merge_stats && (
              <div className="rounded-xl border border-zinc-700/50 bg-zinc-800/50 p-6">
                <h3 className="text-sm font-semibold text-zinc-300 mb-3">
                  Merge Stats
                </h3>
                <div className="space-y-2 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-zinc-400">Social listening</span>
                    <span className="font-medium text-zinc-200">
                      {agentStatus.result.merge_stats.youscan.toLocaleString()} menciones
                    </span>
                  </div>
                  {agentStatus.result.merge_stats.scrapping > 0 && (
                    <div className="flex items-center justify-between">
                      <span className="text-zinc-400">Scraping de redes</span>
                      <span className="font-medium text-zinc-200">
                        {agentStatus.result.merge_stats.scrapping.toLocaleString()} menciones
                      </span>
                    </div>
                  )}
                  <div className="border-t border-zinc-700/50 pt-2 flex items-center justify-between">
                    <span className="text-zinc-300 font-medium">Total unificado</span>
                    <span className="font-bold text-zinc-100">
                      {agentStatus.result.merge_stats.total_unified.toLocaleString()}
                    </span>
                  </div>
                  {agentStatus.result.merge_stats.duplicates_removed > 0 && (
                    <div className="flex items-center justify-between text-amber-400/80">
                      <span>Duplicados removidos</span>
                      <span>{agentStatus.result.merge_stats.duplicates_removed}</span>
                    </div>
                  )}
                </div>
              </div>
            )}

          {/* QA Audit */}
          {agentStatus?.status === "completed" &&
            agentStatus.result?.qa_status && (
              <div className="rounded-xl border border-zinc-700/50 bg-zinc-800/50 p-6">
                <h3 className="text-sm font-semibold text-zinc-300 mb-3">
                  QA Audit
                </h3>
                <div className="space-y-2 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-zinc-400">Status</span>
                    <StatusBadge
                      status={
                        agentStatus.result.qa_status === "APROBADO"
                          ? "completed"
                          : agentStatus.result.qa_status === "REVISAR"
                          ? "running"
                          : "error"
                      }
                    />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-zinc-400">Result</span>
                    <span
                      className={`text-sm font-medium ${
                        agentStatus.result.qa_status === "APROBADO"
                          ? "text-emerald-400"
                          : agentStatus.result.qa_status === "REVISAR"
                          ? "text-amber-400"
                          : "text-red-400"
                      }`}
                    >
                      {agentStatus.result.qa_status}
                    </span>
                  </div>
                  {(agentStatus.result.qa_errors ?? 0) > 0 && (
                    <div className="flex items-center justify-between">
                      <span className="text-zinc-400">Errors</span>
                      <span className="font-medium text-red-400">
                        {agentStatus.result.qa_errors}
                      </span>
                    </div>
                  )}
                  {(agentStatus.result.qa_warnings ?? 0) > 0 && (
                    <div className="flex items-center justify-between">
                      <span className="text-zinc-400">Warnings</span>
                      <span className="font-medium text-amber-400">
                        {agentStatus.result.qa_warnings}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            )}

          {isSubmitting && (
            <div className="rounded-xl border border-blue-700/30 bg-blue-900/10 p-6">
              <div className="flex items-center gap-3">
                <svg
                  className="h-5 w-5 animate-spin text-blue-400"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  />
                </svg>
                <div>
                  <p className="text-sm font-medium text-blue-300">
                    Processing...
                  </p>
                  <p className="text-xs text-blue-400/70">
                    Polling for updates every 3 seconds
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Error Display */}
      {error && (
        <div className="mt-8 rounded-xl border border-red-700/30 bg-red-900/10 p-6">
          <div className="flex items-start gap-3">
            <svg
              className="mt-0.5 h-5 w-5 text-red-400 shrink-0"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={1.5}
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 9v3.75m9-.75a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 3.75h.008v.008H12v-.008Z"
              />
            </svg>
            <div>
              <p className="text-sm font-medium text-red-300">Error</p>
              <p className="mt-1 text-sm text-red-400/80">{error}</p>
            </div>
          </div>
        </div>
      )}

      {/* Results Section */}
      {agentStatus?.status === "completed" && agentStatus.result && (
        <div className="mt-8 space-y-6">
          <h2 className="text-xl font-bold text-zinc-100">Results</h2>

          {/* Summary Metrics */}
          {agentStatus.result.metrics && (
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              {Object.entries(agentStatus.result.metrics).map(
                ([key, value]) => (
                  <div
                    key={key}
                    className="rounded-xl border border-zinc-700/50 bg-zinc-800/50 p-4"
                  >
                    <p className="text-xs text-zinc-500 uppercase tracking-wider">
                      {key.replace(/_/g, " ")}
                    </p>
                    <p className="mt-1 text-2xl font-bold text-zinc-100">
                      {value}
                    </p>
                  </div>
                ),
              )}
            </div>
          )}

          {/* Data Quality Warnings */}
          {agentStatus.result.data_quality_warnings &&
            agentStatus.result.data_quality_warnings.length > 0 && (
              <div className="rounded-xl border border-amber-700/30 bg-amber-900/10 p-6">
                <h3 className="text-sm font-semibold text-amber-300 mb-3">
                  Data Quality Warnings
                </h3>
                <ul className="space-y-2">
                  {agentStatus.result.data_quality_warnings.map(
                    (warning, i) => (
                      <li
                        key={i}
                        className="flex items-start gap-2 text-sm text-amber-200/80"
                      >
                        <span className="mt-1 text-amber-400">&#8226;</span>
                        {warning}
                      </li>
                    ),
                  )}
                </ul>
              </div>
            )}

          {/* Download Buttons */}
          {agentStatus.result.output_files && (
            <div className="flex flex-wrap gap-4">
              {agentStatus.result.output_files.docx && (
                <a
                  href={getDownloadUrl(agentStatus.result.output_files.docx)}
                  className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-500 transition-colors"
                >
                  <svg
                    className="h-4 w-4"
                    fill="none"
                    viewBox="0 0 24 24"
                    strokeWidth={1.5}
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3"
                    />
                  </svg>
                  Download .docx
                </a>
              )}
              {agentStatus.result.output_files.html && (
                <a
                  href={getDownloadUrl(agentStatus.result.output_files.html)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 rounded-lg bg-gradient-to-r from-pink-600 to-cyan-500 px-5 py-2.5 text-sm font-medium text-white hover:opacity-90 transition-opacity"
                >
                  <svg
                    className="h-4 w-4"
                    fill="none"
                    viewBox="0 0 24 24"
                    strokeWidth={1.5}
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25"
                    />
                  </svg>
                  View HTML Report
                </a>
              )}
              {agentStatus.result.output_files.json && (
                <a
                  href={getDownloadUrl(agentStatus.result.output_files.json)}
                  className="inline-flex items-center gap-2 rounded-lg border border-zinc-600 bg-zinc-800 px-5 py-2.5 text-sm font-medium text-zinc-200 hover:bg-zinc-700 transition-colors"
                >
                  <svg
                    className="h-4 w-4"
                    fill="none"
                    viewBox="0 0 24 24"
                    strokeWidth={1.5}
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3"
                    />
                  </svg>
                  Download .json
                </a>
              )}
              {agentStatus.result.output_files.qa && (
                <a
                  href={getDownloadUrl(agentStatus.result.output_files.qa)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 rounded-lg border border-amber-600/50 bg-amber-900/20 px-5 py-2.5 text-sm font-medium text-amber-200 hover:bg-amber-900/30 transition-colors"
                >
                  <svg
                    className="h-4 w-4"
                    fill="none"
                    viewBox="0 0 24 24"
                    strokeWidth={1.5}
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 0 0 2.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 0 0-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 0 0 .75-.75 2.25 2.25 0 0 0-.1-.664m-5.8 0A2.251 2.251 0 0 1 13.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25Z"
                    />
                  </svg>
                  View QA Report
                </a>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
