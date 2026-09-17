import { useEffect, useState } from 'react'
import { listCheckpoints, type CheckpointEntry } from '../api/data'

interface Props {
  value: string
  onChange: (path: string) => void
  // When true, include non-main ckpts (partial/failed/pool/legacy).
  // Defaults to false so the common case shows only proper passes.
  includeAll?: boolean
}

/**
 * Dropdown populated from /api/checkpoints. Entries are grouped by
 * session and labeled with stage + kind. Selecting one writes its
 * absolute path via `onChange`, which the parent wires into the
 * replay/live request.
 *
 * Refresh button re-scans the artifacts tree so newly-trained ckpts
 * (from an in-progress session like p0_elo) show up without a full
 * page reload.
 */
export function CheckpointPicker({ value, onChange, includeAll = false }: Props) {
  const [entries, setEntries] = useState<CheckpointEntry[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [showAll, setShowAll] = useState(includeAll)

  const refresh = () => {
    setLoading(true)
    setErr(null)
    listCheckpoints()
      .then(setEntries)
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    let cancelled = false
    listCheckpoints()
      .then((items) => {
        if (!cancelled) setEntries(items)
      })
      .catch((e) => {
        if (!cancelled) setErr(String(e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const filtered = showAll
    ? entries
    : entries.filter((e) => e.kind === 'main')

  // Group by session_id for optgroup rendering.
  const bySession = new Map<string, CheckpointEntry[]>()
  for (const e of filtered) {
    const list = bySession.get(e.session_id) ?? []
    list.push(e)
    bySession.set(e.session_id, list)
  }

  return (
    <div className="flex w-full min-w-0 flex-wrap items-center gap-2">
      <label className="text-xs text-slate-400">ckpt:</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full min-w-0 bg-slate-800 border border-slate-600 rounded px-2 py-1 text-slate-100 text-xs sm:w-auto sm:min-w-[24rem]"
      >
        <option value="">— select a checkpoint —</option>
        {Array.from(bySession.entries()).map(([sess, list]) => (
          <optgroup key={sess} label={sess}>
            {list.map((e) => (
              <option key={e.path} value={e.path}>
                {e.label}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      <label className="text-xs text-slate-500 flex items-center gap-1 cursor-pointer">
        <input
          type="checkbox"
          checked={showAll}
          onChange={(e) => setShowAll(e.target.checked)}
          className="w-3 h-3"
        />
        show all
      </label>
      <button
        onClick={refresh}
        disabled={loading}
        className="text-xs px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-100 disabled:opacity-40"
        title="Re-scan artifacts tree for new checkpoints"
      >
        {loading ? '…' : '↻'}
      </button>
      {err && <span className="text-xs text-rose-400">{err}</span>}
      <span className="text-[10px] text-slate-500">
        {filtered.length}/{entries.length}
      </span>
    </div>
  )
}
