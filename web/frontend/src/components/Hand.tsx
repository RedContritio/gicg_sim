import type { CardView } from '../types/state'
import { CardArt } from './CardArt'

interface Props {
  hand: CardView[] | null
  deckCount: number
  handCount?: number
  hidden?: boolean
  onPlay?: (idx: number) => void
  dimmed?: boolean
}

export function Hand({ hand, deckCount, handCount, hidden, onPlay, dimmed }: Props) {
  const count = handCount ?? hand?.length
  return (
    <div className={`hand-area ${hidden ? 'hidden-hand' : ''} ${dimmed ? 'waiting-hand' : ''}`}>
      <span className="deck-info">牌库 <b>{deckCount}</b> · 手牌 <b>{count ?? '—'}</b></span>
      {hidden ? <div className="card-backs" aria-label={`对方手牌 ${count ?? '未知'} 张`}>
        {Array.from({ length: Math.min(count ?? 0, 10) }, (_, i) => <span className="card-back" key={i}>✧</span>)}
      </div> : <div className="hand-cards">
        {(hand ?? []).map((card, i) => <button key={`${card.ref}-${i}`} className="hand-card" disabled={!onPlay} onClick={() => onPlay?.(i)} title={`${card.name} · 点击查看可用行动与支付`}>
          <CardArt key={card.name} name={card.name} /><span>{card.name}</span>
        </button>)}
        {hand?.length === 0 && <span className="empty-hand">暂无手牌</span>}
      </div>}
    </div>
  )
}
