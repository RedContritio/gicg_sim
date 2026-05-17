import type { StateView } from '../types/state'
import { CharPortrait } from './CharPortrait'
import { Hand } from './Hand'

interface Props {
  view: StateView
  onPlayCard?: (playerIdx: number, handIdx: number) => void
  onSelectChar?: (playerIdx: number, charIdx: number) => void
  humanPlayer?: number
}

export function Board({ view, onPlayCard, onSelectChar, humanPlayer }: Props) {
  return (
    <div className="flex flex-col gap-3 p-4 bg-slate-900/80 rounded-xl border border-slate-700">
      <div className="flex items-center justify-between text-xs text-slate-300">
        <div className="flex gap-3">
          <span>
            Phase <span className="text-slate-100 font-medium">{view.phase}</span>
          </span>
          <span>
            Round <span className="text-slate-100 font-medium">{view.round}</span>
          </span>
          <span>
            Turn P<span className="text-slate-100 font-medium">{view.turn}</span>
          </span>
        </div>
        {view.winner >= 0 && (
          <span className="px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 font-medium">
            Winner: P{view.winner}
          </span>
        )}
      </div>

      {/* P1 (top) */}
      <PlayerRow
        view={view}
        playerIdx={1}
        onPlayCard={onPlayCard}
        onSelectChar={onSelectChar}
        humanPlayer={humanPlayer}
      />

      <div className="border-t border-slate-700/60" />

      {/* P0 (bottom) */}
      <PlayerRow
        view={view}
        playerIdx={0}
        onPlayCard={onPlayCard}
        onSelectChar={onSelectChar}
        humanPlayer={humanPlayer}
      />
    </div>
  )
}

interface RowProps {
  view: StateView
  playerIdx: number
  onPlayCard?: (playerIdx: number, handIdx: number) => void
  onSelectChar?: (playerIdx: number, charIdx: number) => void
  humanPlayer?: number
}

function PlayerRow({ view, playerIdx, onPlayCard, onSelectChar, humanPlayer }: RowProps) {
  const pv = view.players[playerIdx]
  const isHuman = humanPlayer === playerIdx
  // In PhaseSelectActive the acting player picks their active char but
  // view.turn semantics differ, so also treat select_active as the
  // human's interactive moment.
  const isActionTurn = view.turn === playerIdx && view.phase === 'action'
  const isSelectTurn = view.turn === playerIdx && view.phase === 'select_active'
  const isCurrentTurn = isActionTurn || isSelectTurn
  const handClickable = isHuman && isActionTurn && onPlayCard
    ? (idx: number) => onPlayCard(playerIdx, idx)
    : undefined

  return (
    <div className="flex items-start gap-4">
      <div className="flex flex-col items-center gap-1 min-w-[4rem]">
        <div
          className={`text-xs font-semibold px-2 py-0.5 rounded ${
            isCurrentTurn
              ? 'bg-sky-500/30 text-sky-200'
              : 'bg-slate-800 text-slate-400'
          }`}
        >
          P{playerIdx}
          {isHuman && ' (you)'}
        </div>
      </div>
      <div className="flex gap-2">
        {pv.chars.map((c, ci) => {
          // Clickable under either select_active (initial pick) or
          // action phase (voluntary switch). The parent resolves the
          // (player, char) to a concrete legal-action index — if it
          // can't find one it just ignores the click.
          const canPick = isHuman && isCurrentTurn && !!onSelectChar && c.alive
          return (
            <CharPortrait
              key={ci}
              char={c}
              isActive={pv.active_char === ci}
              isCurrentTurn={isCurrentTurn}
              onSelect={canPick ? () => onSelectChar!(playerIdx, ci) : undefined}
            />
          )
        })}
      </div>
      <div className="flex-1">
        <Hand
          hand={pv.hand}
          deckCount={pv.deck_count}
          onPlay={handClickable}
          dimmed={!isCurrentTurn && isHuman}
        />
      </div>
    </div>
  )
}
