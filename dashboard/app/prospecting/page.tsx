export default function ProspectingPage() {
  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-zinc-100">Prospecting Agent</h1>
        <p className="mt-1 text-sm text-zinc-400">
          Intelligent lead identification and qualification
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
                d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z"
              />
            </svg>
          </div>
          <h2 className="text-xl font-semibold text-zinc-200 mb-3">
            Coming Soon
          </h2>
          <p className="text-sm text-zinc-400 leading-relaxed">
            The Prospecting Agent will automatically identify and qualify
            potential leads by analyzing market data, tracking intent signals,
            and matching against your ideal customer profile. It will integrate
            with your CRM to enrich and score leads in real time.
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
