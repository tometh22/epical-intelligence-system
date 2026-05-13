export default function MonitorPage() {
  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-zinc-100">Monitor Agent</h1>
        <p className="mt-1 text-sm text-zinc-400">
          Real-time competitive intelligence and brand monitoring
        </p>
      </div>

      <div className="flex items-center justify-center py-24">
        <div className="max-w-md text-center">
          <div className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-zinc-800 border border-zinc-700/50">
            <svg
              className="h-8 w-8 text-zinc-500"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={1.5}
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z"
              />
            </svg>
          </div>
          <h2 className="text-xl font-semibold text-zinc-200 mb-3">
            Coming Soon
          </h2>
          <p className="text-sm text-zinc-400 leading-relaxed">
            The Monitor Agent will continuously track competitor activity,
            industry trends, and brand mentions across the web. It provides
            real-time alerts, sentiment analysis, and periodic intelligence
            briefings to keep your team ahead of market shifts.
          </p>
          <div className="mt-6 inline-flex items-center gap-2 rounded-full bg-zinc-800 px-4 py-2 text-xs font-medium text-zinc-400 border border-zinc-700/50">
            <span className="h-2 w-2 rounded-full bg-amber-400" />
            In Development
          </div>
        </div>
      </div>
    </div>
  );
}
