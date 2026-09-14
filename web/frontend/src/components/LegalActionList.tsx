import { useState } from 'react'

// Minimal shape the component needs — accepts both LegalAction (live)
// and a mapped AgentLegalAction-with-prob (replay) without depending
// on either concrete type.
export interface DisplayAction {
  index: number
  kind_name: string
  name: string
  slot?: number
  identity?: number[]
  payment?: number[]
  prob?: number
}

interface Props {
  actions: DisplayAction[]
  onPick?: (index: number) => void
  disabled?: boolean
  topIndex?: number
}

export function LegalActionList({ actions, onPick, disabled, topIndex }: Props) {
  const [selected, setSelected] = useState<Record<string, number>>({})
  const groups = new Map<string, DisplayAction[]>()
  for (const action of actions) {
    const key = action.identity ? JSON.stringify(action.identity) : String(action.index)
    groups.set(key, [...(groups.get(key) ?? []), action])
  }
  const paymentLabel = (a: DisplayAction) => a.payment?.map((n, i) => n ? `${['火','冰','水','雷','岩','风','草','万能'][i]}×${n}` : '').filter(Boolean).join(' ') || '无需骰子'
  if (actions.length === 0) {
    return <div className="text-xs text-slate-500">no legal actions</div>
  }
  return (
    <div className="flex flex-col gap-1 max-h-64 overflow-auto">
      {[...groups].map(([key, choices]) => {
        const a = choices.find(c => c.index === selected[key]) ?? choices[0]
        const isTop = topIndex === a.index
        // Show slot suffix for Card (hand idx) so duplicate-name
        // picks are distinguishable in the list.
        const slotSuffix =
          a.kind_name === 'Card' && typeof a.slot === 'number' && a.slot >= 0
            ? ` (hand#${a.slot})`
            : ''
        return (
          <div key={key} className="flex gap-2 items-center">
          <button
            disabled={disabled}
            onClick={() => onPick?.(a.index)}
            className={`flex-1 flex items-center justify-between gap-2 rounded px-2 py-1 text-xs border transition-colors ${
              disabled
                ? 'border-slate-800 bg-slate-900 text-slate-500 cursor-default'
                : 'border-slate-700 bg-slate-800 hover:border-sky-400 hover:bg-slate-700 cursor-pointer'
            } ${isTop ? 'border-amber-400/60' : ''}`}
          >
            <span className="truncate">
              <span className="text-slate-400">{a.kind_name}:</span>{' '}
              {a.name}{slotSuffix}
              {a.payment && <span className="ml-2 text-amber-200">{paymentLabel(a)}</span>}
            </span>
            {typeof a.prob === 'number' && (
              <span className="tabular-nums text-slate-400">
                {a.prob.toFixed(3)}
              </span>
            )}
          </button>
          {choices.length > 1 && <select aria-label={`${a.name} 支付方式`} disabled={disabled} value={a.index}
            onChange={e => setSelected(prev => ({...prev, [key]: Number(e.target.value)}))}
            className="max-w-64 bg-slate-800 text-amber-200 rounded p-1 text-xs border border-slate-600">
            {choices.map(c => <option key={c.index} value={c.index}>{paymentLabel(c)}</option>)}
          </select>}
          </div>
        )
      })}
    </div>
  )
}
