import AgentCard from "@/components/AgentCard";
import AlertsPanel from "@/components/AlertsPanel";

const agents = [
  {
    name: "Report Builder",
    description:
      "Generates comprehensive client reports from raw data files. Produces Word documents with executive summaries, charts, and actionable insights.",
    status: "idle" as const,
    lastRun: "Apr 7, 2026 — 3:42 PM",
    href: "/report-builder",
    actionLabel: "Build Report",
    disabled: false,
  },
  {
    name: "Prospecting Agent",
    description:
      "Identifies and qualifies potential leads using market data, intent signals, and ICP matching algorithms.",
    status: "idle" as const,
    lastRun: undefined,
    disabled: true,
  },
  {
    name: "Content Authority",
    description:
      "Creates SEO-optimized content briefs, blog posts, and thought leadership pieces aligned with your brand voice.",
    status: "idle" as const,
    lastRun: undefined,
    disabled: true,
  },
  {
    name: "Monitor Agent",
    description:
      "Tracks competitor activity, market trends, and brand mentions across the web in real time.",
    status: "idle" as const,
    lastRun: undefined,
    disabled: true,
  },
];

const recentActivity = [
  {
    id: 1,
    agent: "Report Builder",
    action: "Generated Q1 report for Acme Corp",
    time: "Today, 3:42 PM",
    status: "completed" as const,
  },
  {
    id: 2,
    agent: "Report Builder",
    action: "Generated monthly metrics for Globex Inc",
    time: "Yesterday, 11:15 AM",
    status: "completed" as const,
  },
  {
    id: 3,
    agent: "Report Builder",
    action: "Failed to process corrupted CSV file",
    time: "Apr 5, 2026 — 9:30 AM",
    status: "error" as const,
  },
];

const statusDot: Record<string, string> = {
  completed: "bg-emerald-400",
  error: "bg-red-400",
  running: "bg-blue-400 animate-pulse",
  idle: "bg-zinc-400",
};

export default function DashboardPage() {
  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-zinc-100">Dashboard</h1>
        <p className="mt-1 text-sm text-zinc-400">
          Monitor and manage your AI agents
        </p>
      </div>

      {/* Agent Cards Grid */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-2 mb-8">
        {agents.map((agent) => (
          <AgentCard key={agent.name} {...agent} />
        ))}
      </div>

      {/* Bottom Section: Alerts + Activity */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <AlertsPanel />

        {/* Recent Activity */}
        <div className="rounded-xl border border-zinc-700/50 bg-zinc-800/50 p-6">
          <h3 className="text-base font-semibold text-zinc-100 mb-4">
            Recent Activity
          </h3>
          <div className="space-y-4">
            {recentActivity.map((item) => (
              <div
                key={item.id}
                className="flex items-start gap-3"
              >
                <span
                  className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${statusDot[item.status]}`}
                />
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-zinc-200">{item.action}</p>
                  <div className="mt-0.5 flex items-center gap-2">
                    <span className="text-xs text-zinc-500">{item.agent}</span>
                    <span className="text-zinc-600">·</span>
                    <span className="text-xs text-zinc-500">{item.time}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
