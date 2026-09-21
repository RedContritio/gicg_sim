import { useState, type DragEvent } from 'react'
import type { StateView, StatusView } from '../types/state'
import { CharPortrait } from './CharPortrait'
import { Hand } from './Hand'

interface Props {
  view: StateView
  onPlayCard?: (playerIdx: number, handIdx: number) => void
  onSelectChar?: (playerIdx: number, charIdx: number) => void
  humanPlayer?: number
  selectedCard?: number
  selectedChar?: number
  playableCards?: number[]
  switchableChars?: number[]
  castableCards?: number[]
  tunableCards?: number[]
  onCardIntent?: (handIdx: number, intent: 'play' | 'tune') => void
}
const elements = ['火', '冰', '水', '雷', '岩', '风', '草', '万能']
const phases: Record<string, string> = { select_active: '选择出战角色', action: '行动阶段', round_start: '回合开始', round_end: '回合结束', game_over: '对局结束' }

export function Board({ view, onPlayCard, onSelectChar, humanPlayer, selectedCard, selectedChar, playableCards, switchableChars, castableCards, tunableCards, onCardIntent }: Props) {
  const bottom = humanPlayer ?? 0
  const actor = view.acting_player ?? view.turn
  const [draggingCard, setDraggingCard] = useState<number | null>(null)
  const [dropZone, setDropZone] = useState<'play' | 'tune' | null>(null)

  const startCardDrag = (handIdx: number, event: DragEvent<HTMLButtonElement>) => {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('application/x-gicg-hand-card', String(handIdx))
    setDraggingCard(handIdx)
  }

  const finishCardDrag = () => {
    setDraggingCard(null)
    setDropZone(null)
  }

  const dropCard = (event: DragEvent, intent: 'play' | 'tune') => {
    event.preventDefault()
    event.stopPropagation()
    const handIdx = Number(event.dataTransfer.getData('application/x-gicg-hand-card'))
    const allowed = intent === 'play' ? castableCards : tunableCards
    if (Number.isInteger(handIdx) && allowed?.includes(handIdx)) onCardIntent?.(handIdx, intent)
    finishCardDrag()
  }

  const allowDrop = (event: DragEvent, intent: 'play' | 'tune') => {
    const allowed = intent === 'play' ? castableCards : tunableCards
    if (draggingCard === null || !allowed?.includes(draggingCard)) return
    event.preventDefault()
    if (intent === 'tune') event.stopPropagation()
    event.dataTransfer.dropEffect = 'move'
    setDropZone(intent)
  }
  return (
    <div className="game-board">
      {[1 - bottom, bottom].map((pi, row) => {
        const player = view.players[pi]
        const own = pi === humanPlayer
        const hidden = row === 0 && humanPlayer !== undefined
        const interactive = own && actor === pi && ['action', 'select_active'].includes(view.phase)
        return <div key={pi} className={`board-half ${row === 0 ? 'opponent-half' : 'own-half'}`}>
          <div className="player-label"><span className={`turn-dot ${actor === pi ? 'lit' : ''}`} />{humanPlayer === undefined ? `玩家 ${pi + 1}` : own ? '我方' : '对方'}<small>{player.alive_count} 位角色存活</small></div>
          <Hand hand={hidden ? null : player.hand} hidden={hidden} handCount={player.hand_count ?? player.hand?.length}
            deckCount={player.deck_count} selected={own ? selectedCard : undefined}
            playable={own ? playableCards : undefined}
            draggable={own ? playableCards : undefined} dragging={own ? draggingCard ?? undefined : undefined}
            onCardDragStart={own && interactive ? startCardDrag : undefined} onCardDragEnd={finishCardDrag}
            onPlay={interactive && view.phase === 'action' && onPlayCard ? (i) => onPlayCard(pi, i) : undefined} />
          <div className={`battle-row ${own && draggingCard !== null && castableCards?.includes(draggingCard) ? 'card-drop-ready' : ''} ${own && dropZone === 'play' ? 'drop-active' : ''}`}
            onDragOver={own ? (event) => allowDrop(event, 'play') : undefined}
            onDrop={own ? (event) => dropCard(event, 'play') : undefined}>
            {own && draggingCard !== null && castableCards?.includes(draggingCard) && <span className="field-drop-label">释放以打出卡牌</span>}
            <EffectZone title="支援区" effects={player.supports} />
            <div className="characters">{player.chars.map((char, ci) => <CharPortrait key={`${char.name}-${ci}`} char={char}
              isActive={player.active_char === ci} isCurrentTurn={actor === pi}
              isSelected={own && selectedChar === ci}
              onSelect={interactive && onSelectChar && (switchableChars === undefined || switchableChars.includes(ci)) ? () => onSelectChar(pi, ci) : undefined} />)}</div>
            <EffectZone title="召唤物区" effects={player.summons} />
            <div className={`dice-rail ${own && draggingCard !== null && tunableCards?.includes(draggingCard) ? 'card-drop-ready' : ''} ${own && dropZone === 'tune' ? 'drop-active' : ''}`}
              aria-label={hidden ? '对方骰子总数' : '元素骰'}
              onDragOver={own ? (event) => allowDrop(event, 'tune') : undefined}
              onDrop={own ? (event) => dropCard(event, 'tune') : undefined}>
              {own && draggingCard !== null && tunableCards?.includes(draggingCard) && <span className="dice-drop-label">释放以调和</span>}
              <span className="dice-total">◆ <b>{player.dice_count ?? player.dice?.reduce((a, b) => a + b, 0) ?? '—'}</b></span>
              {hidden ? <small>骰子总数</small> : player.dice?.map((n, i) => n > 0 && <span key={i} className={`element-die die-${i}`} title={`${elements[i]}元素骰 ${n} 个`}><span>{elements[i]}</span><b>{n}</b></span>)}
            </div>
          </div>
          {!!player.statuses?.length && <div className="team-statuses">{player.statuses.map((s, i) => <span key={`${s.name}-${i}`}>{s.name} <b>{s.value}</b></span>)}</div>}
        </div>
      })}
      <div className="round-ribbon"><span>第 {view.round} 回合</span><b>{view.winner >= 0 ? view.winner === 2 ? '平局' : view.winner === humanPlayer ? '你赢了' : `玩家 ${view.winner + 1} 获胜` : phases[view.phase] ?? view.phase}</b></div>
    </div>
  )
}

function EffectZone({ title, effects }: { title: string; effects?: StatusView[] }) {
  return <div className="effect-zone"><h3>{title}</h3><div className="effect-slots">
    {effects?.map((effect, i) => <div className="effect-card" key={`${effect.name}-${i}`} title={`${effect.name}：${effect.value}${effect.max > 0 ? `/${effect.max}` : ''}`}><span>{effect.name}</span><b>{effect.value}</b></div>)}
    {Array.from({ length: Math.max(0, 4 - (effects?.length ?? 0)) }, (_, i) => <div className="effect-empty" key={`empty-${i}`}>✧</div>)}
  </div>{effects === undefined && <small>暂无区域信息</small>}</div>
}
