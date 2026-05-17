import type { CardView } from '../types/state'

interface Props {
  hand: CardView[] | null
  deckCount: number
  // When set, cards become clickable and call onPlay(handIdx) on click.
  onPlay?: (idx: number) => void
  dimmed?: boolean
}

export function Hand({ hand, deckCount, onPlay, dimmed }: Props) {
  const cards = hand ?? []
  return (
    <div
      className={`flex items-center gap-2 ${
        dimmed ? 'opacity-60' : ''
      }`}
    >
      <div className="flex gap-1.5">
        {cards.length === 0 && (
          <div className="text-xs text-slate-500 italic">(empty hand)</div>
        )}
        {cards.map((card, i) => (
          <button
            key={`${card.ref}-${i}`}
            disabled={!onPlay}
            onClick={() => onPlay?.(i)}
            className={`w-16 h-24 rounded-md border border-slate-600 bg-gradient-to-b from-slate-700 to-slate-900 flex items-center justify-center text-xs font-medium text-slate-100 px-1 text-center leading-tight ${
              onPlay
                ? 'cursor-pointer hover:border-sky-400 hover:shadow-sky-400/40 hover:shadow-md'
                : 'cursor-default'
            }`}
            title={card.name}
          >
            {card.name}
          </button>
        ))}
      </div>
      <div className="text-xs text-slate-400 whitespace-nowrap">
        Deck: {deckCount}
      </div>
    </div>
  )
}
