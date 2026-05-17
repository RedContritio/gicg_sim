// Minimal shape the component needs — accepts both LegalAction (live)
// and a mapped AgentLegalAction-with-prob (replay) without depending
// on either concrete type.
export interface DisplayAction {
  index: number
  kind_name: string
  name: string
  slot?: number
  prob?: number
}

interface Props {
  actions: DisplayAction[]
  onPick?: (index: number) => void
  disabled?: boolean
  topIndex?: number
}

export function LegalActionList({ actions, onPick, disabled, topIndex }: Props) {
  if (actions.length === 0) {
    return <div className="text-xs text-slate-500">no legal actions</div>
  }
  return (
    <div className="flex flex-col gap-1 max-h-64 overflow-auto">
      {actions.map((a) => {
        const isTop = topIndex === a.index
        // Show slot suffix for Card (hand idx) so duplicate-name
        // picks are distinguishable in the list.
        const slotSuffix =
          a.kind_name === 'Card' && typeof a.slot === 'number' && a.slot >= 0
            ? ` (hand#${a.slot})`
            : ''
        return (
          <button
            key={a.index}
            disabled={disabled}
            onClick={() => onPick?.(a.index)}
            className={`flex items-center justify-between gap-2 rounded px-2 py-1 text-xs border transition-colors ${
              disabled
                ? 'border-slate-800 bg-slate-900 text-slate-500 cursor-default'
                : 'border-slate-700 bg-slate-800 hover:border-sky-400 hover:bg-slate-700 cursor-pointer'
            } ${isTop ? 'border-amber-400/60' : ''}`}
          >
            <span className="truncate">
              <span className="text-slate-400">{a.kind_name}:</span>{' '}
              {a.name}{slotSuffix}
            </span>
            {typeof a.prob === 'number' && (
              <span className="tabular-nums text-slate-400">
                {a.prob.toFixed(3)}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
