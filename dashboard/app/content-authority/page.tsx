export default function ContentAuthorityPage() {
  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-zinc-100">Content Authority</h1>
        <p className="mt-1 text-sm text-zinc-400">
          AI-powered content creation and optimization
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
                d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L10.582 16.07a4.5 4.5 0 0 1-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 0 1 1.13-1.897l8.932-8.931Zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0 1 15.75 21H5.25A2.25 2.25 0 0 1 3 18.75V8.25A2.25 2.25 0 0 1 5.25 6H10"
              />
            </svg>
          </div>
          <h2 className="text-xl font-semibold text-zinc-200 mb-3">
            Coming Soon
          </h2>
          <p className="text-sm text-zinc-400 leading-relaxed">
            The Content Authority agent will generate SEO-optimized content
            briefs, blog posts, case studies, and thought leadership pieces.
            It learns your brand voice, analyzes competitor content gaps, and
            produces publish-ready material aligned with your content strategy.
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
