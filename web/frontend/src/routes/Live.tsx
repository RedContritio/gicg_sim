import { useEffect, useRef, useState } from 'react'
import { LiveClient, type OpponentSpec } from '../api/live'
import { listChars } from '../api/data'
import type { LegalAction, LiveFrame, StateView } from '../types/state'
import { Board } from '../components/Board'
import { LegalActionList } from '../components/LegalActionList'
import { OpponentPicker } from '../components/OpponentPicker'

export function Live() {
  const [allChars, setAllChars] = useState<string[]>([])
  const [team0, setTeam0] = useState<string[]>([])
  const [team1, setTeam1] = useState<string[]>([])
  const [humanPlayer, setHumanPlayer] = useState<0 | 1>(0)
  const [opponent, setOpponent] = useState<OpponentSpec>({
    type: 'mcts_pure',
    n_simulations: 200,
  })

  const [view, setView] = useState<StateView | null>(null)
  const [legalActions, setLegalActions] = useState<LegalAction[]>([])
  const [currentPlayer, setCurrentPlayer] = useState<number>(0)
  const [done, setDone] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [connState, setConnState] = useState<
    'idle' | 'connected' | 'reconnecting' | 'disconnected' | 'closed'
  >('idle')
  const clientRef = useRef<LiveClient | null>(null)

  useEffect(() => {
    listChars()
      .then((chars) => {
        setAllChars(chars)
        if (chars.length > 0) {
          setTeam0((t) => (t.length === 0 ? [chars[0]] : t))
          setTeam1((t) =>
            t.length === 0 ? [chars[1] ?? chars[0]] : t,
          )
        }
      })
      .catch((e) => setErr(String(e)))
    return () => {
      clientRef.current?.close()
    }
  }, [])

  const onFrame = (frame: LiveFrame) => {
    if (frame.type === 'error') {
      setErr(frame.message)
      return
    }
    setErr(null)
    setView(frame.view)
    setLegalActions(frame.legal_actions || [])
    setCurrentPlayer(frame.current_player)
    setDone(frame.done)
  }

  const validate = (): string | null => {
    if (team0.length === 0) return 'Team P0 is empty'
    if (team1.length === 0) return 'Team P1 is empty'
    if (opponent.type === 'az' || opponent.type === 'cfr') {
      if (!opponent.ckpt) {
        return `${opponent.type} opponent requires a ckpt`
      }
    }
    if (opponent.type === 'mcts_pure' && opponent.n_simulations <= 0) {
      return 'mcts_pure requires n_simulations > 0'
    }
    return null
  }

  const start = async () => {
    const invalid = validate()
    if (invalid) {
      setErr(invalid)
      return
    }
    setErr(null)
    setView(null)
    setLegalActions([])
    setDone(false)

    // Close the previous client before creating a new one — otherwise
    // stale WS messages from the old session bleed into this state.
    clientRef.current?.close()

    const c = new LiveClient(onFrame, (state) => setConnState(state))
    clientRef.current = c
    try {
      await c.connect()
      c.send({
        type: 'new',
        team_0: team0,
        team_1: team1,
        opponent,
        human_player: humanPlayer,
      })
    } catch (e) {
      // Connection failed — clear ref so pickAction doesn't throw
      // on the dead client (A8).
      clientRef.current = null
      setConnState('disconnected')
      setErr(String(e))
    }
  }

  const pickAction = (idx: number) => {
    if (!clientRef.current || done) return
    clientRef.current.send({ type: 'action', index: idx })
  }

  const playCard = (_playerIdx: number, handIdx: number) => {
    if (!view) return
    // Match by hand slot (backend sends slot=hand_idx for Card actions).
    // This is the correct disambiguation when the hand holds multiple
    // copies of the same card name.
    const act = legalActions.find(
      (a) => a.kind_name === 'Card' && a.slot === handIdx,
    )
    if (act) pickAction(act.index)
  }

  const selectChar = (playerIdx: number, charIdx: number) => {
    if (playerIdx !== humanPlayer || !view) return
    // Match by char slot. Covers both PhaseAction's voluntary Switch
    // action (kind_name === 'Switch') and PhaseSelectActive's initial
    // pick, which the engine models as Switch as well.
    const act = legalActions.find(
      (a) => a.kind_name === 'Switch' && a.slot === charIdx,
    )
    if (act) pickAction(act.index)
  }

  const isHumanTurn = currentPlayer === humanPlayer && !done

  return (
    <div className="flex flex-col h-full overflow-y-auto p-4 gap-4">
      <div className="flex flex-wrap items-end gap-3 p-3 rounded-lg border border-slate-700 bg-slate-900/60">
        <TeamPicker
          label={`Team P0${humanPlayer === 0 ? ' (you)' : ''}`}
          team={team0}
          setTeam={setTeam0}
          allChars={allChars}
        />
        <TeamPicker
          label={`Team P1${humanPlayer === 1 ? ' (you)' : ''}`}
          team={team1}
          setTeam={setTeam1}
          allChars={allChars}
        />
        <div className="flex flex-col gap-1">
          <div className="text-xs text-slate-400">You play as</div>
          <div className="flex gap-1">
            {[0, 1].map((side) => (
              <button
                key={side}
                onClick={() => setHumanPlayer(side as 0 | 1)}
                className={`text-xs px-2 py-1 rounded border ${
                  humanPlayer === side
                    ? 'bg-sky-500/30 border-sky-400 text-sky-100'
                    : 'bg-slate-800 border-slate-600 text-slate-300 hover:border-slate-400'
                }`}
              >
                P{side}
              </button>
            ))}
          </div>
        </div>
        <OpponentPicker value={opponent} onChange={setOpponent} />
        <button
          onClick={start}
          className="px-3 py-1 rounded bg-sky-500 hover:bg-sky-400 text-slate-950 text-sm font-medium"
        >
          {connState === 'idle' ? 'Start' : 'Restart'}
        </button>
        {connState === 'reconnecting' && (
          <span className="text-xs text-amber-300">
            reconnecting...
          </span>
        )}
        {connState === 'disconnected' && (
          <span className="text-xs text-rose-400">
            disconnected — press Restart
          </span>
        )}
        {err && <span className="text-xs text-rose-400">{err}</span>}
        {done && view && (
          <span className="text-xs text-amber-300">
            Game over (winner P{view.winner})
          </span>
        )}
        {view && !done && isHumanTurn && view.phase === 'select_active' && (
          <span className="text-xs text-sky-300">
            Click a character to select your starting active
          </span>
        )}
        {view && !done && isHumanTurn && view.phase === 'action' && (
          <span className="text-xs text-sky-300">
            Your turn — click a card, char, or legal action
          </span>
        )}
        {view && !done && !isHumanTurn && (
          <span className="text-xs text-slate-400">Opponent thinking…</span>
        )}
      </div>

      {view && (
        <>
          <Board
            view={view}
            humanPlayer={humanPlayer}
            onPlayCard={playCard}
            onSelectChar={selectChar}
          />
          <section className="flex flex-col gap-2">
            <h3 className="text-xs font-semibold text-slate-300">
              Your moves {!isHumanTurn && '(waiting for opponent)'}
            </h3>
            <LegalActionList
              actions={legalActions}
              onPick={pickAction}
              disabled={!isHumanTurn}
            />
          </section>
        </>
      )}
    </div>
  )
}

interface TeamPickerProps {
  label: string
  team: string[]
  setTeam: (t: string[]) => void
  allChars: string[]
}

function TeamPicker({ label, team, setTeam, allChars }: TeamPickerProps) {
  const toggle = (name: string) => {
    setTeam(team.includes(name) ? team.filter((n) => n !== name) : [...team, name])
  }
  if (allChars.length === 0) {
    return (
      <div className="flex flex-col gap-1">
        <div className="text-xs text-slate-400">{label}</div>
        <div className="text-xs text-slate-600">loading chars…</div>
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-1">
      <div className="text-xs text-slate-400">{label}</div>
      <div className="flex gap-1">
        {allChars.map((name) => (
          <button
            key={name}
            onClick={() => toggle(name)}
            className={`text-xs px-2 py-1 rounded border ${
              team.includes(name)
                ? 'bg-sky-500/30 border-sky-400 text-sky-100'
                : 'bg-slate-800 border-slate-600 text-slate-300 hover:border-slate-400'
            }`}
          >
            {name}
          </button>
        ))}
      </div>
    </div>
  )
}
