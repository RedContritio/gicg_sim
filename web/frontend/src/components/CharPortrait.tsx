import type { CharView } from '../types/state'

interface Props {
  char: CharView
  isActive: boolean
  isCurrentTurn?: boolean
  // When set, the portrait becomes a clickable button — used in live
  // mode for both initial select_active picks AND voluntary mid-game
  // switches. Clicking calls onSelect(). Disabled dead chars never
  // call back regardless.
  onSelect?: () => void
}

export function CharPortrait({ char, isActive, isCurrentTurn, onSelect }: Props) {
  const hpPct = char.hp_max > 0 ? (char.hp / char.hp_max) * 100 : 0
  const hpColor =
    hpPct > 60 ? 'bg-emerald-500' : hpPct > 30 ? 'bg-amber-500' : 'bg-rose-500'
  const ring = isActive
    ? isCurrentTurn
      ? 'ring-2 ring-sky-400 shadow-sky-400/50 shadow-lg'
      : 'ring-2 ring-slate-300'
    : 'ring-1 ring-slate-600'
  const dead = !char.alive
  const clickable = onSelect !== undefined && !dead
  const interactiveCls = clickable
    ? 'cursor-pointer hover:ring-2 hover:ring-sky-300 hover:scale-[1.03]'
    : ''

  return (
    <div
      role={clickable ? 'button' : undefined}
      tabIndex={clickable ? 0 : undefined}
      onClick={clickable ? onSelect : undefined}
      onKeyDown={clickable ? (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onSelect!()
        }
      } : undefined}
      className={`flex flex-col items-center gap-1 rounded-lg p-2 transition-all ${ring} ${interactiveCls} ${
        dead ? 'opacity-30 grayscale' : 'bg-slate-800/70'
      }`}
      title={char.name}
    >
      <div className="w-16 h-16 rounded-full bg-gradient-to-br from-slate-600 to-slate-800 flex items-center justify-center text-2xl font-semibold text-slate-100">
        {char.name[0] || '?'}
      </div>
      <div className="text-xs font-medium text-slate-100">{char.name}</div>
      <div className="w-full h-1.5 bg-slate-900 rounded overflow-hidden">
        <div
          className={`h-full ${hpColor} transition-all`}
          style={{ width: `${hpPct}%` }}
        />
      </div>
      <div className="text-[10px] text-slate-300 tabular-nums">
        HP {char.hp}/{char.hp_max}
      </div>
      <div className="flex gap-0.5">
        {Array.from({ length: char.energy_max }).map((_, i) => (
          <span
            key={i}
            className={`w-1.5 h-1.5 rounded-full ${
              i < char.energy ? 'bg-amber-300' : 'bg-slate-700'
            }`}
          />
        ))}
      </div>
      {char.statuses && char.statuses.length > 0 && (
        <div className="flex flex-wrap gap-0.5 justify-center max-w-[5rem]">
          {char.statuses.map((s) => (
            <span
              key={s.name}
              className="text-[9px] px-1 py-[1px] rounded bg-violet-900/60 text-violet-200 whitespace-nowrap"
              title={`${s.name}: ${s.value}${s.max > 0 ? `/${s.max}` : ''}`}
            >
              {s.name} {s.value}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
