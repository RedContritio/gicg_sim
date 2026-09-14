import type { StateView, StatusView } from '../types/state'
import { CharPortrait } from './CharPortrait'
import { Hand } from './Hand'

interface Props {
  view: StateView
  onPlayCard?: (playerIdx: number, handIdx: number) => void
  onSelectChar?: (playerIdx: number, charIdx: number) => void
  humanPlayer?: number
}
const elements = ['火', '冰', '水', '雷', '岩', '风', '草', '万能']
const phases: Record<string, string> = { select_active: '选择出战角色', action: '行动阶段', round_start: '回合开始', round_end: '回合结束', game_over: '对局结束' }

export function Board({ view, onPlayCard, onSelectChar, humanPlayer }: Props) {
  const bottom = humanPlayer ?? 0
  const actor = view.acting_player ?? view.turn
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
            deckCount={player.deck_count} onPlay={interactive && view.phase === 'action' && onPlayCard ? (i) => onPlayCard(pi, i) : undefined} />
          <div className="battle-row">
            <EffectZone title="支援区" effects={player.supports} />
            <div className="characters">{player.chars.map((char, ci) => <CharPortrait key={`${char.name}-${ci}`} char={char}
              isActive={player.active_char === ci} isCurrentTurn={actor === pi}
              onSelect={interactive && onSelectChar ? () => onSelectChar(pi, ci) : undefined} />)}</div>
            <EffectZone title="召唤物区" effects={player.summons} />
            <div className="dice-rail" aria-label={hidden ? '对方骰子总数' : '元素骰'}>
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
