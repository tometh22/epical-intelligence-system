const placeholderAlerts = [
  {
    id: 1,
    type: "warning" as const,
    message: "Report Builder queue has 3 pending tasks",
    time: "2 min ago",
  },
  {
    id: 2,
    type: "info" as const,
    message: "System backup completed successfully",
    time: "15 min ago",
  },
  {
    id: 3,
    type: "success" as const,
    message: "Weekly metrics report generated for Acme Corp",
    time: "1 hr ago",
  },
];

const typeStyles = {
  warning: {
    bg: "bg-amber-900/20",
    border: "border-amber-700/30",
    dot: "bg-amber-400",
    text: "text-amber-200",
  },
  info: {
    bg: "bg-blue-900/20",
    border: "border-blue-700/30",
    dot: "bg-blue-400",
    text: "text-blue-200",
  },
  success: {
    bg: "bg-emerald-900/20",
    border: "border-emerald-700/30",
    dot: "bg-emerald-400",
    text: "text-emerald-200",
  },
};

export default function AlertsPanel() {
  return (
    <div className="rounded-xl border border-zinc-700/50 bg-zinc-800/50 p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-base font-semibold text-zinc-100">Active Alerts</h3>
        <span className="rounded-full bg-zinc-700/50 px-2 py-0.5 text-xs text-zinc-400">
          {placeholderAlerts.length}
        </span>
      </div>
      <div className="space-y-3">
        {placeholderAlerts.map((alert) => {
          const style = typeStyles[alert.type];
          return (
            <div
              key={alert.id}
              className={`flex items-start gap-3 rounded-lg border p-3 ${style.bg} ${style.border}`}
            >
              <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${style.dot}`} />
              <div className="flex-1 min-w-0">
                <p className={`text-sm ${style.text}`}>{alert.message}</p>
                <p className="mt-0.5 text-xs text-zinc-500">{alert.time}</p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
