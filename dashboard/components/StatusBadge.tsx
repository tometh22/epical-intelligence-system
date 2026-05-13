export type Status = "idle" | "running" | "completed" | "error";

const statusConfig: Record<Status, { label: string; bg: string; text: string; dot: string }> = {
  idle: {
    label: "Idle",
    bg: "bg-zinc-700/50",
    text: "text-zinc-300",
    dot: "bg-zinc-400",
  },
  running: {
    label: "Running",
    bg: "bg-blue-900/40",
    text: "text-blue-300",
    dot: "bg-blue-400 animate-pulse",
  },
  completed: {
    label: "Completed",
    bg: "bg-emerald-900/40",
    text: "text-emerald-300",
    dot: "bg-emerald-400",
  },
  error: {
    label: "Error",
    bg: "bg-red-900/40",
    text: "text-red-300",
    dot: "bg-red-400",
  },
};

export default function StatusBadge({ status }: { status: Status }) {
  const config = statusConfig[status];

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${config.bg} ${config.text}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${config.dot}`} />
      {config.label}
    </span>
  );
}
