import { useEffect, useState } from 'react'
import { listReplays, getReplay } from '../api/replay'
import type { ReplayDetail, ReplayListEntry } from '../types/state'
import { Board } from '../components/Board'
import { PolicyBars } from '../components/PolicyBars'
import { AttentionHeatmap } from '../components/AttentionHeatmap'
import { ValueTimeline } from '../components/ValueTimeline'
import { LegalActionList } from '../components/LegalActionList'
import { CheckpointPicker } from '../components/CheckpointPicker'

export function Replay() {
  const [entries, setEntries] = useState<ReplayListEntry[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [step, setStep] = useState(0)
  const [ckpt, setCkpt] = useState('')
  const [detail, setDetail] = useState<ReplayDetail | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  // Value history accumulates as the user scrubs — one entry per
  // fetched step, keyed by step index so the timeline doesn't
  // duplicate entries on re-scrubs.
  const [valueByStep, setValueByStep] = useState<Record<number, number>>({})

  useEffect(() => {
    listReplays()
      .then((r) => setEntries(r.replays))
      .catch((e) => setErr(String(e)))
  }, [])

  useEffect(() => {
    if (!selected) return
    setLoading(true)
    setErr(null)
    getReplay(selected, step, ckpt || undefined)
      .then((d) => {
        setDetail(d)
        if (d.agent && !d.agent.error) {
          setValueByStep((prev) => ({ ...prev, [step]: d.agent!.value }))
        }
      })
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false))
  }, [selected, step, ckpt])

  const onSelect = (rel: string) => {
    setSelected(rel)
    setStep(0)
    setValueByStep({})
  }

  const valueSeries = detail
    ? Array.from({ length: detail.total_steps + 1 }, (_, i) => valueByStep[i] ?? NaN)
        .filter((v) => !Number.isNaN(v))
    : []

  return (
    <div className="flex h-full">
      <aside className="w-64 border-r border-slate-700 p-3 overflow-auto bg-slate-950/60">
        <h2 className="text-sm font-semibold text-slate-200 mb-2">Replays</h2>
        {entries.length === 0 && (
          <div className="text-xs text-slate-500">no replays found</div>
        )}
        <ul className="flex flex-col gap-1">
          {entries.map((e) => (
            <li key={e.rel_path}>
              <button
                onClick={() => onSelect(e.rel_path)}
                className={`text-left w-full text-xs px-2 py-1 rounded ${
                  selected === e.rel_path
                    ? 'bg-sky-500/20 text-sky-200'
                    : 'hover:bg-slate-800 text-slate-300'
                }`}
                title={e.rel_path}
              >
                <div className="truncate">{e.scenario || e.rel_path}</div>
                <div className="text-[10px] text-slate-500 truncate">
                  {[e.session_id, ...e.curriculum, e.stage]
                    .filter(Boolean)
                    .join("/")}
                </div>
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <main className="flex-1 p-4 overflow-auto flex flex-col gap-4">
        <div className="flex items-center gap-3">
          <CheckpointPicker value={ckpt} onChange={setCkpt} />
          {loading && <span className="text-xs text-sky-300">loading…</span>}
          {err && <span className="text-xs text-rose-400">{err}</span>}
        </div>

        {detail && (
          <>
            <Board view={detail.view} />

            <div className="flex items-center gap-3">
              <button
                className="px-2 py-1 rounded bg-slate-700 text-slate-100 text-xs disabled:opacity-40"
                disabled={step <= 0}
                onClick={() => setStep((s) => Math.max(0, s - 1))}
              >
                ←
              </button>
              <input
                type="range"
                min={0}
                max={detail.total_steps}
                value={step}
                onChange={(e) => setStep(Number(e.target.value))}
                className="flex-1"
              />
              <button
                className="px-2 py-1 rounded bg-slate-700 text-slate-100 text-xs disabled:opacity-40"
                disabled={step >= detail.total_steps}
                onClick={() =>
                  setStep((s) => Math.min(detail.total_steps, s + 1))
                }
              >
                →
              </button>
              <span className="text-xs text-slate-400 tabular-nums">
                {step} / {detail.total_steps}
              </span>
            </div>

            {detail.agent && !detail.agent.error ? (
              <div className="grid grid-cols-2 gap-4">
                <section className="flex flex-col gap-2">
                  <h3 className="text-xs font-semibold text-slate-300">
                    Policy (value {detail.agent.value.toFixed(3)}, entropy{' '}
                    {detail.agent.entropy.toFixed(3)})
                  </h3>
                  <PolicyBars agent={detail.agent} />
                </section>
                <section className="flex flex-col gap-2">
                  <h3 className="text-xs font-semibold text-slate-300">Attention</h3>
                  <AttentionHeatmap layers={detail.agent.attention} />
                </section>
                <section className="col-span-2 flex flex-col gap-2">
                  <h3 className="text-xs font-semibold text-slate-300">
                    Value timeline
                  </h3>
                  <ValueTimeline values={valueSeries} currentStep={step} />
                </section>
                <section className="col-span-2 flex flex-col gap-2">
                  <h3 className="text-xs font-semibold text-slate-300">
                    Legal actions
                  </h3>
                  <LegalActionList
                    actions={
                      detail.agent?.legal_actions?.map((a, i) => ({
                        index: i,
                        kind_name: a.kind,  // replay's agent uses strings directly
                        name: a.name,
                        prob: detail.agent?.policy?.[i],
                      })) ?? []
                    }
                    disabled
                    topIndex={detail.agent?.top_k?.[0]?.index}
                  />
                </section>
              </div>
            ) : (
              <div className="text-xs text-slate-500">
                {detail.agent?.error ||
                  'supply a ckpt above to enable agent inspection'}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  )
}
