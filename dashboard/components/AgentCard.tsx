import Link from "next/link";
import StatusBadge, { type Status } from "./StatusBadge";

interface AgentCardProps {
  name: string;
  description: string;
  status: Status;
  lastRun?: string;
  href?: string;
  actionLabel?: string;
  disabled?: boolean;
}

export default function AgentCard({
  name,
  description,
  status,
  lastRun,
  href,
  actionLabel = "Open",
  disabled = false,
}: AgentCardProps) {
  return (
    <div className="rounded-xl border border-zinc-700/50 bg-zinc-800/50 p-6 flex flex-col gap-4 hover:border-zinc-600/50 transition-colors">
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-lg font-semibold text-zinc-100">{name}</h3>
          <p className="mt-1 text-sm text-zinc-400 leading-relaxed">
            {description}
          </p>
        </div>
        <StatusBadge status={status} />
      </div>

      <div className="mt-auto flex items-center justify-between pt-2 border-t border-zinc-700/30">
        <span className="text-xs text-zinc-500">
          {lastRun ? `Last run: ${lastRun}` : "Never run"}
        </span>
        {disabled ? (
          <button
            disabled
            className="rounded-lg bg-zinc-700/50 px-4 py-2 text-sm font-medium text-zinc-500 cursor-not-allowed"
          >
            Coming Soon
          </button>
        ) : href ? (
          <Link
            href={href}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 transition-colors"
          >
            {actionLabel}
          </Link>
        ) : null}
      </div>
    </div>
  );
}
