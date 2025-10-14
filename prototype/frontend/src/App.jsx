import { useEffect, useMemo, useRef, useState } from 'react'
import { API_BASE_URL, healthCheck, runQuery, triggerIngest, uploadUfdr } from './lib/api'

const DEFAULT_QUERY = 'Show foreign crypto messages after 10 pm'

const STATUS_STYLES = {
  checking: 'bg-slate-800/80 text-slate-200 border border-slate-700',
  ok: 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/30',
  error: 'bg-rose-500/10 text-rose-300 border border-rose-500/30',
}

const formatLabel = (key) =>
  key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase())

function App() {
  const [health, setHealth] = useState({ state: 'checking' })

  const [caseId, setCaseId] = useState('CASE-01')
  const [dataPath, setDataPath] = useState('')
  const [ufdrFile, setUfdrFile] = useState(null)
  const [ingestLoading, setIngestLoading] = useState(false)
  const [ingestStats, setIngestStats] = useState(null)
  const [ingestError, setIngestError] = useState(null)

  const fileInputRef = useRef(null)

  const [queryText, setQueryText] = useState(DEFAULT_QUERY)
  const [limit, setLimit] = useState(5)
  const [queryLoading, setQueryLoading] = useState(false)
  const [queryResult, setQueryResult] = useState(null)
  const [queryError, setQueryError] = useState(null)

  useEffect(() => {
    let active = true
    ;(async () => {
      const result = await healthCheck()
      if (!active) return
      if (result.ok) {
        setHealth({ state: 'ok', details: result.result })
      } else {
        setHealth({ state: 'error', error: result.error })
      }
    })()

    return () => {
      active = false
    }
  }, [])

  const handleIngest = async (event) => {
    event.preventDefault()
    setIngestLoading(true)
    setIngestError(null)
    try {
      let resolvedDataPath = dataPath.trim() || null

      if (ufdrFile) {
        const uploadResponse = await uploadUfdr(ufdrFile)
        const uploadedPath = uploadResponse.data_path ?? uploadResponse.path ?? null
        if (!uploadedPath) {
          throw new Error('Upload completed but no data path was returned by the server.')
        }
        resolvedDataPath = uploadedPath
      }

      const response = await triggerIngest({
        caseId: caseId.trim() || 'CASE-01',
        reset: true,
        dataPath: resolvedDataPath,
      })
      setIngestStats(response.ingested)
      if (ufdrFile && fileInputRef.current) {
        fileInputRef.current.value = ''
      }
      setUfdrFile(null)
    } catch (error) {
      setIngestError(error.message ?? 'Failed to ingest UFDR bundle')
    } finally {
      setIngestLoading(false)
    }
  }

  const handleQuery = async (event) => {
    event.preventDefault()
    if (!queryText.trim()) return
    setQueryLoading(true)
    setQueryError(null)
    try {
      const response = await runQuery({ query: queryText.trim(), limit })
      setQueryResult(response)
    } catch (error) {
      setQueryError(error.message ?? 'Query failed')
    } finally {
      setQueryLoading(false)
    }
  }

  const healthBadgeClass = STATUS_STYLES[health.state] ?? STATUS_STYLES.checking

  const hasResults = useMemo(() => {
    if (!queryResult) return false
    const { messages, calls, graph_insights: graphInsights } = queryResult
    return (
      (messages && messages.length > 0) ||
      (calls && calls.length > 0) ||
      (graphInsights && graphInsights.length > 0) ||
      Boolean(queryResult.summary)
    )
  }, [queryResult])

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 bg-gradient-to-r from-slate-950 via-slate-900 to-slate-950">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 px-6 py-8 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-sm uppercase tracking-wide text-slate-400">AI-Powered UFDR Assistant</p>
            <h1 className="mt-1 text-2xl font-semibold text-white md:text-3xl">Conversational forensic intelligence dashboard</h1>
            <p className="mt-2 text-sm text-slate-400 md:max-w-xl">
              Upload parsed UFDR bundles, trigger ingestion, and surface actionable chats, calls, and linkage insights via natural language.
            </p>
          </div>
          <div className="flex flex-col items-start gap-2 md:items-end">
            <span className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium ${healthBadgeClass}`}>
              <span className="h-2 w-2 rounded-full bg-current" />
              {health.state === 'ok' && 'API online'}
              {health.state === 'checking' && 'Checking API health...'}
              {health.state === 'error' && 'API unreachable'}
            </span>
            <span className="text-xs text-slate-500">Base URL: {API_BASE_URL}</span>
            {health.error && <span className="text-xs text-rose-400">{health.error.message ?? String(health.error)}</span>}
          </div>
        </div>
      </header>

      <main className="mx-auto flex max-w-6xl flex-col gap-10 px-6 py-10">
        <section className="grid gap-6 lg:grid-cols-2">
          <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-6 shadow-lg shadow-slate-950/40">
            <h2 className="text-lg font-semibold text-white">Ingest UFDR data</h2>
            <p className="mt-1 text-sm text-slate-400">
              Upload a UFDR archive or provide a server path to trigger the backend pipeline that normalizes contacts, chats, calls, and graph knowledge.
            </p>

            <form className="mt-6 space-y-4" onSubmit={handleIngest}>
              <div className="grid gap-2">
                <label htmlFor="caseId" className="text-sm font-medium text-slate-300">
                  Case ID
                </label>
                <input
                  id="caseId"
                  type="text"
                  value={caseId}
                  onChange={(event) => setCaseId(event.target.value)}
                  className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-emerald-500 focus:ring focus:ring-emerald-500/20"
                  placeholder="CASE-01"
                />
              </div>

              <div className="grid gap-2">
                <label htmlFor="ufdrFile" className="text-sm font-medium text-slate-300">
                  Upload UFDR archive (optional)
                </label>
                <input
                  id="ufdrFile"
                  ref={fileInputRef}
                  type="file"
                  accept=".zip,.ufdr,.tar,.gz,.tgz"
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    setUfdrFile(file ?? null)
                  }}
                  className="block w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 file:mr-3 file:cursor-pointer file:rounded file:border-0 file:bg-slate-800 file:px-3 file:py-2 file:text-sm file:text-slate-200"
                />
                <p className="text-xs text-slate-500">
                  Supported formats: .ufdr, .zip, .tar.gz. The archive is extracted server-side and automatically used for ingestion.
                </p>
                {ufdrFile && (
                  <span className="text-xs text-emerald-300">Selected file: {ufdrFile.name}</span>
                )}
              </div>

              <div className="grid gap-2">
                <label htmlFor="dataPath" className="text-sm font-medium text-slate-300">
                  Custom data path (optional)
                </label>
                <input
                  id="dataPath"
                  type="text"
                  value={dataPath}
                  onChange={(event) => setDataPath(event.target.value)}
                  className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-emerald-500 focus:ring focus:ring-emerald-500/20"
                  placeholder="Leave empty to use bundled sample or uploaded archive"
                />
                <p className="text-xs text-slate-500">Point to an extracted UFDR directory if you have your own dataset.</p>
              </div>

              {ingestError && (
                <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                  {ingestError}
                </div>
              )}

              <button
                type="submit"
                disabled={ingestLoading}
                className="inline-flex w-full items-center justify-center rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-emerald-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {ingestLoading ? 'Ingesting…' : 'Run ingestion pipeline'}
              </button>
            </form>

            {ingestStats && (
              <div className="mt-6">
                <h3 className="text-sm font-medium text-slate-200">Artifacts generated</h3>
                <dl className="mt-3 grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
                  {Object.entries(ingestStats).map(([key, value]) => (
                    <div key={key} className="rounded-xl border border-slate-800 bg-slate-900/80 p-3">
                      <dt className="text-xs uppercase tracking-wide text-slate-400">{formatLabel(key)}</dt>
                      <dd className="mt-1 text-lg font-semibold text-white">{value}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            )}
          </div>

          <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-6 shadow-lg shadow-slate-950/40">
            <h2 className="text-lg font-semibold text-white">Ask a forensic question</h2>
            <p className="mt-1 text-sm text-slate-400">
              Combine precise filters with semantic search to reveal suspicious activity instantly.
            </p>

            <form className="mt-6 space-y-5" onSubmit={handleQuery}>
              <div className="grid gap-2">
                <label htmlFor="query" className="text-sm font-medium text-slate-300">
                  Investigator prompt
                </label>
                <textarea
                  id="query"
                  rows={4}
                  value={queryText}
                  onChange={(event) => setQueryText(event.target.value)}
                  className="rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-indigo-500 focus:ring focus:ring-indigo-500/20"
                  placeholder="Show me chat records containing crypto addresses"
                />
              </div>

              <div className="flex items-center justify-between gap-4">
                <label htmlFor="limit" className="text-sm font-medium text-slate-300">
                  Max results
                </label>
                <input
                  id="limit"
                  type="number"
                  min={1}
                  max={20}
                  value={limit}
                  onChange={(event) => setLimit(Number(event.target.value) || 5)}
                  className="w-24 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-indigo-500 focus:ring focus:ring-indigo-500/20"
                />
              </div>

              {queryError && (
                <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                  {queryError}
                </div>
              )}

              <button
                type="submit"
                disabled={queryLoading || !queryText.trim()}
                className="inline-flex w-full items-center justify-center rounded-lg bg-indigo-500 px-4 py-2 text-sm font-semibold text-indigo-950 transition hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {queryLoading ? 'Searching evidence…' : 'Run natural language search'}
              </button>
            </form>
          </div>
        </section>

        <section className="rounded-2xl border border-slate-800 bg-slate-900/30 p-6 shadow-lg shadow-slate-950/30">
          <div className="flex flex-col gap-3 border-b border-slate-800 pb-5 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-white">Investigation results</h2>
              <p className="mt-1 text-sm text-slate-400">Summaries, raw evidence, and graph insights returned from the AI pipeline.</p>
            </div>
            {queryResult?.summary && (
              <span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-4 py-2 text-xs font-medium text-emerald-200">
                {queryResult.summary}
              </span>
            )}
          </div>

          {!hasResults && (
            <div className="flex flex-col items-center justify-center gap-3 py-12 text-center text-slate-500">
              <div className="flex h-12 w-12 items-center justify-center rounded-full border border-slate-800 bg-slate-900/60 text-slate-400">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-5 w-5">
                  <path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm0 18a8 8 0 1 1 0-16 8 8 0 0 1 0 16Zm-.75-5.25h1.5V17h-1.5v-2.25ZM11 7h2v6h-2V7Z" />
                </svg>
              </div>
              <p className="text-sm">Run a query to populate the evidence board.</p>
            </div>
          )}

          {hasResults && (
            <div className="mt-6 space-y-8">
              {queryResult?.messages?.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-300">Relevant messages</h3>
                  <div className="mt-3 grid gap-4 lg:grid-cols-2">
                    {queryResult.messages.map((message) => (
                      <article key={message.message_id} className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                        <div className="flex items-center justify-between text-xs text-slate-400">
                          <span>{new Date(message.timestamp).toLocaleString()}</span>
                          <span className="rounded-full border border-indigo-500/30 bg-indigo-500/10 px-2 py-0.5 text-[10px] uppercase tracking-wide text-indigo-200">
                            {message.app ?? 'Unknown app'}
                          </span>
                        </div>
                        <div className="mt-2 text-sm text-slate-200">
                          <p>
                            <span className="font-semibold text-white">{message.sender}</span>
                            {message.receiver ? (
                              <>
                                <span className="text-slate-500"> → </span>
                                <span className="font-semibold text-white">{message.receiver}</span>
                              </>
                            ) : (
                              <span className="text-slate-500"> (broadcast)</span>
                            )}
                          </p>
                        </div>
                        <p className="mt-3 text-sm leading-relaxed text-slate-100">{message.content}</p>
                        {message.keywords?.length > 0 && (
                          <div className="mt-3 flex flex-wrap gap-2 text-[11px] uppercase tracking-wide text-amber-200">
                            {message.keywords.map((keyword) => (
                              <span key={keyword} className="rounded-full border border-amber-400/40 bg-amber-500/10 px-2 py-0.5">
                                {keyword}
                              </span>
                            ))}
                          </div>
                        )}
                      </article>
                    ))}
                  </div>
                </div>
              )}

              {queryResult?.calls?.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-300">Call activity</h3>
                  <div className="mt-3 grid gap-3 lg:grid-cols-2">
                    {queryResult.calls.map((call) => (
                      <article key={call.call_id} className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-sm text-slate-200">
                        <div className="flex items-center justify-between text-xs text-slate-400">
                          <span>{new Date(call.timestamp).toLocaleString()}</span>
                          <span className="rounded-full border border-fuchsia-500/30 bg-fuchsia-500/10 px-2 py-0.5 text-[10px] uppercase tracking-wide text-fuchsia-200">
                            {call.type}
                          </span>
                        </div>
                        <p className="mt-2 font-medium text-white">
                          {call.caller ?? 'Unknown caller'}
                          <span className="text-slate-500"> → </span>
                          {call.callee ?? 'Unknown callee'}
                        </p>
                        <dl className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-400">
                          <div>
                            <dt className="uppercase tracking-wide">Duration</dt>
                            <dd className="text-slate-200">{call.duration_seconds} sec</dd>
                          </div>
                          <div>
                            <dt className="uppercase tracking-wide">Location</dt>
                            <dd className="text-slate-200">{call.location ?? 'Unknown'}</dd>
                          </div>
                        </dl>
                      </article>
                    ))}
                  </div>
                </div>
              )}

              {queryResult?.graph_insights?.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-300">Graph insights</h3>
                  <ul className="mt-3 space-y-2 text-sm text-slate-200">
                    {queryResult.graph_insights.map((insight, index) => (
                      <li key={index} className="rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 py-2">
                        {insight}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </section>
      </main>

      <footer className="border-t border-slate-900/80 bg-slate-950/80 py-6">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 px-6 text-xs text-slate-500 md:flex-row md:items-center md:justify-between">
          <span>Smart India Hackathon prototype • UFDR Forensic Assistant</span>
          <span>Backend must be running on {API_BASE_URL}</span>
        </div>
      </footer>
    </div>
  )
}

export default App
