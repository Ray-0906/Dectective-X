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

const formatIstTimestamp = (value) => {
  if (!value) return 'Unknown time'
  try {
    return new Date(value).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })
  } catch (error) {
    return String(value)
  }
}

const generateMessageId = () => {
  if (typeof crypto !== 'undefined' && crypto?.randomUUID) {
    return crypto.randomUUID()
  }
  return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

const hasInvestigationContent = (result) => {
  if (!result) return false
  const { messages, calls, locations, graph_insights: graphInsights, narrative, report, summary } = result
  return (
    Boolean(narrative) ||
    Boolean(report) ||
    Boolean(summary) ||
    (Array.isArray(messages) && messages.length > 0) ||
    (Array.isArray(calls) && calls.length > 0) ||
    (Array.isArray(locations) && locations.length > 0) ||
    (Array.isArray(graphInsights) && graphInsights.length > 0)
  )
}

const buildMarkdownFromResult = (result) => {
  if (!result) return ''

  const lines = []
  lines.push('# Investigation Report')
  lines.push(`Generated at: ${formatIstTimestamp(new Date().toISOString())}`)
  lines.push('')

  lines.push('## Query Summary')
  lines.push(result.summary?.trim() || 'No summary provided.')
  lines.push('')

  if (result.narrative) {
    lines.push('## Narrative Brief')
    lines.push(result.narrative.trim())
    lines.push('')
  }

  if (Array.isArray(result.messages) && result.messages.length > 0) {
    lines.push('## Messages')
    result.messages.forEach((message) => {
      const direction = message.receiver ? `${message.sender} → ${message.receiver}` : message.sender
      lines.push(
        `- ${formatIstTimestamp(message.timestamp)} — ${direction}: ${message.content}`
      )
      if (Array.isArray(message.keywords) && message.keywords.length > 0) {
        lines.push(`  - Keywords: ${message.keywords.join(', ')}`)
      }
    })
    lines.push('')
  }

  if (Array.isArray(result.calls) && result.calls.length > 0) {
    lines.push('## Calls')
    result.calls.forEach((call) => {
      lines.push(
        `- ${formatIstTimestamp(call.timestamp)} — ${call.caller ?? 'Unknown caller'} → ${call.callee ?? 'Unknown callee'} (${call.type}, ${call.duration_seconds} sec)`
      )
      if (call.location) {
        lines.push(`  - Location: ${call.location}`)
      }
    })
    lines.push('')
  }

  if (Array.isArray(result.locations) && result.locations.length > 0) {
    lines.push('## Locations')
    result.locations.forEach((location) => {
      lines.push(
        `- ${formatIstTimestamp(location.timestamp)} — ${location.contact ?? 'Unknown contact'} @ (${location.latitude ?? '—'}, ${location.longitude ?? '—'})`
      )
      if (location.accuracy_meters) {
        lines.push(`  - Accuracy: ${location.accuracy_meters} m`)
      }
    })
    lines.push('')
  }

  if (Array.isArray(result.graph_insights) && result.graph_insights.length > 0) {
    lines.push('## Graph Insights')
    result.graph_insights.forEach((insight) => {
      lines.push(`- ${insight}`)
    })
    lines.push('')
  }

  if (result.report) {
    lines.push('## Full Narrative Report')
    lines.push(result.report.trim())
    lines.push('')
  }

  return lines.join('\n')
}

const LoadingMessage = () => (
  <div className="rounded-2xl border border-indigo-500/30 bg-indigo-500/5 p-6 shadow-lg shadow-indigo-950/20">
    <div className="flex items-center gap-3">
      <span className="h-4 w-4 rounded-full border-2 border-indigo-400/40 border-t-indigo-300/90 animate-spin" />
      <span className="text-sm text-indigo-100/90">Analyzing evidence and building the narrative…</span>
    </div>
    <div className="mt-6 space-y-3">
      <div className="h-2 rounded-full bg-indigo-500/20 animate-pulse" />
      <div className="h-2 w-3/4 rounded-full bg-indigo-500/10 animate-pulse" />
      <div className="h-2 w-2/4 rounded-full bg-indigo-500/20 animate-pulse" />
    </div>
  </div>
)

const ErrorMessage = ({ message }) => (
  <div className="rounded-2xl border border-rose-500/40 bg-rose-500/10 p-5 text-sm text-rose-100 shadow-lg shadow-rose-950/20">
    <p className="font-semibold text-rose-200">Query failed</p>
    <p className="mt-1 leading-relaxed">{message}</p>
    <p className="mt-3 text-xs text-rose-200/70">Confirm backend connectivity and try again.</p>
  </div>
)

const InvestigationResult = ({ result }) => {
  if (!result) return null
  const hasContent = hasInvestigationContent(result)

  if (!hasContent) {
    return (
      <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-6 text-sm text-slate-300 shadow-lg shadow-slate-950/20">
        <p className="font-medium text-slate-100">No matching evidence found.</p>
        <p className="mt-2 text-slate-400">
          Try broadening the timeframe, removing filters, or re-running ingestion with additional UFDR sources.
        </p>
      </div>
    )
  }

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-0 shadow-2xl shadow-slate-950/40">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-800 bg-slate-900/80 px-6 py-4">
        <div>
          <h3 className="text-base font-semibold text-white">Investigation summary</h3>
          <p className="mt-1 text-xs text-slate-400">Evidence rendered in IST for frontline review.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {result.summary && (
            <span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-3 py-1 text-xs font-medium text-emerald-200">
              {result.summary}
            </span>
          )}
          {result.narrative && (
            <span className="rounded-full border border-indigo-500/30 bg-indigo-500/10 px-3 py-1 text-xs font-medium text-indigo-200">
              LLM brief ready
            </span>
          )}
        </div>
      </div>

      <div className="space-y-8 px-6 py-6">
        {result.narrative && (
          <article className="rounded-xl border border-indigo-500/30 bg-indigo-500/10 p-5 text-sm leading-relaxed text-indigo-100">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-indigo-200/90">LLM Investigator Brief</h4>
            <p className="mt-2 text-base text-indigo-50">{result.narrative}</p>
          </article>
        )}

        {Array.isArray(result.messages) && result.messages.length > 0 && (
          <div>
            <h4 className="text-sm font-semibold uppercase tracking-wide text-slate-300">Relevant messages</h4>
            <div className="mt-3 grid gap-4 lg:grid-cols-2">
              {result.messages.map((message) => (
                <article key={message.message_id} className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                  <div className="flex items-center justify-between text-xs text-slate-400">
                    <span>{formatIstTimestamp(message.timestamp)}</span>
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

        {Array.isArray(result.calls) && result.calls.length > 0 && (
          <div>
            <h4 className="text-sm font-semibold uppercase tracking-wide text-slate-300">Call activity</h4>
            <div className="mt-3 grid gap-3 lg:grid-cols-2">
              {result.calls.map((call) => (
                <article key={call.call_id} className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-sm text-slate-200">
                  <div className="flex items-center justify-between text-xs text-slate-400">
                    <span>{formatIstTimestamp(call.timestamp)}</span>
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

        {Array.isArray(result.locations) && result.locations.length > 0 && (
          <div>
            <h4 className="text-sm font-semibold uppercase tracking-wide text-slate-300">Location trail</h4>
            <div className="mt-3 grid gap-3 lg:grid-cols-2">
              {result.locations.map((location) => (
                <article key={location.location_id} className="rounded-xl border border-sky-500/30 bg-sky-500/5 p-4 text-sm text-sky-100">
                  <div className="flex items-center justify-between text-xs text-sky-200/80">
                    <span>{formatIstTimestamp(location.timestamp)}</span>
                    <span className="rounded-full border border-sky-500/40 bg-sky-500/10 px-2 py-0.5 text-[10px] uppercase tracking-wide text-sky-100">
                      {location.accuracy_meters ? `${location.accuracy_meters}m` : 'Location'}
                    </span>
                  </div>
                  <p className="mt-2 text-base font-semibold text-white">{location.contact ?? 'Unknown contact'}</p>
                  <dl className="mt-3 grid grid-cols-2 gap-2 text-xs">
                    <div>
                      <dt className="uppercase tracking-wide text-sky-200/70">Latitude</dt>
                      <dd className="text-white">{location.latitude ?? '—'}</dd>
                    </div>
                    <div>
                      <dt className="uppercase tracking-wide text-sky-200/70">Longitude</dt>
                      <dd className="text-white">{location.longitude ?? '—'}</dd>
                    </div>
                  </dl>
                </article>
              ))}
            </div>
          </div>
        )}

        {Array.isArray(result.graph_insights) && result.graph_insights.length > 0 && (
          <div>
            <h4 className="text-sm font-semibold uppercase tracking-wide text-slate-300">Graph insights</h4>
            <ul className="mt-3 space-y-2 text-sm text-slate-200">
              {result.graph_insights.map((insight, index) => (
                <li key={index} className="rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 py-2">
                  {insight}
                </li>
              ))}
            </ul>
          </div>
        )}

        {result.report && (
          <div>
            <h4 className="text-sm font-semibold uppercase tracking-wide text-slate-300">Full narrative report</h4>
            <pre className="mt-3 whitespace-pre-wrap rounded-xl border border-slate-800 bg-slate-900/70 p-4 text-sm leading-relaxed text-slate-100">
{result.report}
            </pre>
          </div>
        )}
      </div>
    </div>
  )
}

function App() {
  const [health, setHealth] = useState({ state: 'checking' })

  const [caseId, setCaseId] = useState('CASE-01')
  const [dataPath, setDataPath] = useState('')
  const [ufdrFile, setUfdrFile] = useState(null)
  const [ingestLoading, setIngestLoading] = useState(false)
  const [ingestStats, setIngestStats] = useState(null)
  const [ingestError, setIngestError] = useState(null)

  const [queryText, setQueryText] = useState(DEFAULT_QUERY)
  const [limit, setLimit] = useState(5)
  const [queryLoading, setQueryLoading] = useState(false)
  const [queryResult, setQueryResult] = useState(null)
  const [queryError, setQueryError] = useState(null)
  const [history, setHistory] = useState([])
  const [showAdvanced, setShowAdvanced] = useState(false)

  const fileInputRef = useRef(null)
  const chatScrollRef = useRef(null)

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

  useEffect(() => {
    if (!chatScrollRef.current) return
    chatScrollRef.current.scrollTop = chatScrollRef.current.scrollHeight
  }, [history])

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

    const prompt = queryText.trim()
    const requestId = generateMessageId()
    const timestamp = new Date().toISOString()

    setHistory((previous) => [
      ...previous,
      { id: requestId, query: prompt, status: 'loading', timestamp, limit },
    ])

    setQueryLoading(true)
    setQueryError(null)

    try {
      const response = await runQuery({ query: prompt, limit })
      setHistory((previous) =>
        previous.map((entry) =>
          entry.id === requestId
            ? { ...entry, status: 'success', result: response }
            : entry
        )
      )
      setQueryResult(response)
      setQueryText('')
    } catch (error) {
      const message = error.message ?? 'Query failed'
      setHistory((previous) =>
        previous.map((entry) =>
          entry.id === requestId ? { ...entry, status: 'error', error: message } : entry
        )
      )
      setQueryError(message)
    } finally {
      setQueryLoading(false)
    }
  }

  const handleExportMarkdown = () => {
    if (!queryResult || !hasInvestigationContent(queryResult)) {
      return
    }
    const markdown = buildMarkdownFromResult(queryResult)
    const safeCaseId = (caseId || 'case').replace(/[^a-z0-9_-]/gi, '_').toLowerCase()
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
    const blob = new Blob([markdown], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${safeCaseId || 'case'}_investigation_${timestamp}.md`
    document.body.appendChild(anchor)
    anchor.click()
    document.body.removeChild(anchor)
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  const healthBadgeClass = STATUS_STYLES[health.state] ?? STATUS_STYLES.checking
  const exportDisabled = !queryResult || !hasInvestigationContent(queryResult)

  const ingestStatsEntries = useMemo(() => {
    if (!ingestStats) return []
    return Object.entries(ingestStats)
  }, [ingestStats])

  return (
    <div className="flex min-h-screen flex-col bg-slate-950 text-slate-100">
      <header className="border-b border-slate-900/80 bg-gradient-to-r from-slate-950 via-slate-900 to-slate-950">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-6 py-6 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.4em] text-slate-500">UFDR Intelligence Suite</p>
            <h1 className="mt-1 text-2xl font-semibold text-white md:text-3xl">Detective X — Analyst Console</h1>
            <p className="mt-2 text-sm text-slate-400 md:max-w-2xl">
              Blend UFDR ingestion, cross-channel retrieval, and Gemini-powered narratives inside a streamlined, chat-first investigation workspace.
            </p>
          </div>
          <div className="flex flex-col items-start gap-2 md:items-end">
            <span className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium ${healthBadgeClass}`}>
              <span className="h-2 w-2 rounded-full bg-current" />
              {health.state === 'ok' && 'API online'}
              {health.state === 'checking' && 'Checking API health…'}
              {health.state === 'error' && 'API unreachable'}
            </span>
            <span className="text-xs text-slate-500">Base URL: {API_BASE_URL}</span>
            {health.error && <span className="text-xs text-rose-400">{health.error.message ?? String(health.error)}</span>}
          </div>
        </div>
      </header>

      <div className="flex flex-1 flex-col md:flex-row">
        <aside className="w-full flex-shrink-0 border-b border-slate-900/80 bg-slate-950/70 md:w-[360px] md:border-b-0 md:border-r">
          <div className="flex h-full flex-col gap-8 overflow-y-auto px-6 py-8">
            <section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5 shadow-lg shadow-slate-950/20">
              <h2 className="text-sm font-semibold text-white">Ingest UFDR Collections</h2>
              <p className="mt-1 text-xs leading-relaxed text-slate-400">
                Upload new UFDR archives or point to server paths to refresh the evidence lake. Each ingestion resets the SQLite store, vector index, and knowledge graph.
              </p>

              <form className="mt-5 space-y-4" onSubmit={handleIngest}>
                <div className="grid gap-2">
                  <label htmlFor="caseId" className="text-xs font-medium text-slate-300">
                    Case ID
                  </label>
                  <input
                    id="caseId"
                    type="text"
                    value={caseId}
                    onChange={(event) => setCaseId(event.target.value)}
                    className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-emerald-500 focus:ring focus:ring-emerald-500/20"
                    placeholder="CASE-01"
                  />
                </div>

                <div className="grid gap-2">
                  <label htmlFor="ufdrFile" className="text-xs font-medium text-slate-300">
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
                    className="block w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 file:mr-3 file:cursor-pointer file:rounded file:border-0 file:bg-slate-800 file:px-3 file:py-2 file:text-xs file:text-slate-200"
                  />
                  <p className="text-[11px] text-slate-500">Supports .ufdr, .zip, .tar.gz. Archives are unpacked server-side prior to ingestion.</p>
                  {ufdrFile && <span className="text-[11px] text-emerald-300">Selected: {ufdrFile.name}</span>}
                </div>

                <div className="grid gap-2">
                  <label htmlFor="dataPath" className="text-xs font-medium text-slate-300">
                    Custom data path (optional)
                  </label>
                  <input
                    id="dataPath"
                    type="text"
                    value={dataPath}
                    onChange={(event) => setDataPath(event.target.value)}
                    className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-emerald-500 focus:ring focus:ring-emerald-500/20"
                    placeholder="Leave empty to use bundled sample"
                  />
                </div>

                {ingestError && (
                  <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
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

              {ingestStatsEntries.length > 0 && (
                <div className="mt-6">
                  <h3 className="text-xs font-medium uppercase tracking-wide text-slate-400">Artifacts generated</h3>
                  <dl className="mt-3 grid grid-cols-2 gap-3 text-sm">
                    {ingestStatsEntries.map(([key, value]) => (
                      <div key={key} className="rounded-xl border border-slate-800 bg-slate-900/70 p-3">
                        <dt className="text-[11px] uppercase tracking-wide text-slate-500">{formatLabel(key)}</dt>
                        <dd className="mt-1 text-lg font-semibold text-white">{value}</dd>
                      </div>
                    ))}
                  </dl>
                </div>
              )}
            </section>

            <section className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5 text-xs text-slate-400 shadow-lg shadow-slate-950/20">
              <h2 className="text-sm font-semibold text-white">Workflow tips</h2>
              <ul className="mt-3 space-y-2 leading-relaxed">
                <li>Use natural language like “latest crypto chats with overseas brokers last week”.</li>
                <li>Toggle advanced query limits from the chat composer when you need more evidence.</li>
                <li>Export the latest investigation packet as Markdown for handover or briefing notes.</li>
              </ul>
            </section>
          </div>
        </aside>

        <section className="flex flex-1 flex-col bg-slate-950/40">
          <div className="flex items-center justify-between border-b border-slate-900/80 bg-slate-950/80 px-6 py-4">
            <div>
              <h2 className="text-lg font-semibold text-white">Investigation workspace</h2>
              <p className="text-xs text-slate-400">Chat with the UFDR assistant. Responses render detailed evidence, always in IST.</p>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setQueryText(DEFAULT_QUERY)}
                className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs font-medium text-slate-300 transition hover:border-slate-600 hover:text-white"
              >
                Insert sample prompt
              </button>
              <button
                type="button"
                onClick={handleExportMarkdown}
                disabled={exportDisabled}
                className="inline-flex items-center gap-2 rounded-lg bg-indigo-500 px-4 py-2 text-xs font-semibold text-indigo-950 transition hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <svg
                  aria-hidden="true"
                  viewBox="0 0 24 24"
                  className="h-4 w-4 fill-current"
                  focusable="false"
                >
                  <path d="M12 3a1 1 0 0 1 1 1v9.586l2.293-2.293a1 1 0 1 1 1.414 1.414l-4 4a1 1 0 0 1-1.414 0l-4-4a1 1 0 0 1 1.414-1.414L11 13.586V4a1 1 0 0 1 1-1Zm-7 14a1 1 0 0 1 1-1h12a1 1 0 1 1 0 2H6a1 1 0 0 1-1-1Z" />
                </svg>
                Export Markdown
              </button>
            </div>
          </div>

          <div ref={chatScrollRef} className="flex-1 overflow-y-auto px-6 py-6">
            <div className="mx-auto flex max-w-5xl flex-col gap-8">
              {history.length === 0 && (
                <div className="rounded-2xl border border-dashed border-slate-800 bg-slate-900/50 p-10 text-center">
                  <p className="text-sm text-slate-400">
                    Start by running a query from the composer below. Responses will appear here as conversational evidence briefs.
                  </p>
                </div>
              )}

              {history.map((entry) => (
                <div key={entry.id} className="flex flex-col gap-4">
                  <div className="self-end max-w-3xl rounded-2xl bg-indigo-600 px-4 py-3 text-sm font-medium text-indigo-50 shadow-xl shadow-indigo-950/40">
                    {entry.query}
                  </div>
                  <div className="self-start w-full">
                    {entry.status === 'loading' && <LoadingMessage />}
                    {entry.status === 'error' && <ErrorMessage message={entry.error} />}
                    {entry.status === 'success' && <InvestigationResult result={entry.result} />}
                  </div>
                  <div className="self-center text-[11px] uppercase tracking-wide text-slate-500">
                    {formatIstTimestamp(entry.timestamp)}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="border-t border-slate-900/80 bg-slate-950/90 px-6 py-5">
            <form className="mx-auto flex max-w-5xl flex-col gap-4" onSubmit={handleQuery}>
              <div className="flex items-center gap-3 rounded-2xl border border-slate-800 bg-slate-900/70 px-4 py-3 shadow-inner shadow-slate-950">
                <textarea
                  id="query"
                  rows={queryText.split('\n').length}
                  value={queryText}
                  onChange={(event) => setQueryText(event.target.value)}
                  placeholder="Ask the assistant for chats, calls, locations, or summaries…"
                  className="h-full flex-1 resize-none bg-transparent text-sm text-slate-100 outline-none placeholder:text-slate-600"
                  disabled={queryLoading}
                />
                <button
                  type="submit"
                  disabled={queryLoading || !queryText.trim()}
                  className="inline-flex items-center justify-center rounded-full bg-indigo-500 p-3 text-indigo-950 transition hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {queryLoading ? (
                    <span className="h-4 w-4 rounded-full border-2 border-indigo-200/60 border-t-indigo-900 animate-spin" />
                  ) : (
                    <svg
                      aria-hidden="true"
                      viewBox="0 0 24 24"
                      className="h-4 w-4 fill-current"
                      focusable="false"
                    >
                      <path d="M3.172 4.172a2 2 0 0 1 2.117-.483l15.01 5.696a2 2 0 0 1 0 3.73l-15.01 5.696A2 2 0 0 1 3 17.255V13.4l8.525-1.399L3 10.6V6.745a2 2 0 0 1 .172-.573Z" />
                    </svg>
                  )}
                </button>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-slate-500">
                <button
                  type="button"
                  onClick={() => setShowAdvanced((value) => !value)}
                  className="inline-flex items-center gap-1 rounded-full border border-slate-700 px-3 py-1 text-[11px] font-medium text-slate-300 transition hover:border-slate-600 hover:text-white"
                >
                  <svg
                    aria-hidden="true"
                    viewBox="0 0 24 24"
                    className="h-3.5 w-3.5 fill-current"
                    focusable="false"
                  >
                    <path d="M8 6a2 2 0 1 1-4 0 2 2 0 0 1 4 0Zm12 0a2 2 0 1 1-4 0 2 2 0 0 1 4 0ZM8 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0Zm12 0a2 2 0 1 1-4 0 2 2 0 0 1 4 0ZM7 6h10v2H7V6Zm0 6h10v2H7v-2Zm0 6h10v2H7v-2Z" />
                  </svg>
                  {showAdvanced ? 'Hide advanced options' : 'Show advanced options'}
                </button>
                {queryError && <span className="text-xs text-rose-400">{queryError}</span>}
              </div>

              {showAdvanced && (
                <div className="flex flex-wrap items-center gap-4 rounded-2xl border border-slate-800 bg-slate-900/50 px-4 py-3 text-xs text-slate-300">
                  <label className="flex items-center gap-2">
                    <span className="uppercase tracking-wide text-slate-400">Max results</span>
                    <input
                      type="number"
                      min={1}
                      max={20}
                      value={limit}
                      onChange={(event) => setLimit(Number(event.target.value) || 5)}
                      className="w-20 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100 outline-none focus:border-indigo-500"
                    />
                  </label>
                  <p className="text-[11px] text-slate-500">Adjust for broader sweeps or tighter snapshots (1-20).</p>
                </div>
              )}
            </form>
          </div>
        </section>
      </div>

      <footer className="border-t border-slate-900/80 bg-slate-950/80 py-6">
        <div className="mx-auto flex max-w-7xl flex-col gap-2 px-6 text-xs text-slate-500 md:flex-row md:items-center md:justify-between">
          <span>Smart India Hackathon prototype • Detective X UFDR Assistant</span>
          <span>Backend must be running on {API_BASE_URL}</span>
        </div>
      </footer>
    </div>
  )
}

export default App
