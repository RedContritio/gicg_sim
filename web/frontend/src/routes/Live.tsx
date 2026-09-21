import { useEffect, useRef, useState } from 'react'
import { LiveClient, type LiveProfile, type OpponentSpec } from '../api/live'

import type { LegalAction, LiveFrame, StateView } from '../types/state'
import { Board } from '../components/Board'
import { LegalActionList } from '../components/LegalActionList'
import { OpponentPicker } from '../components/OpponentPicker'

export function Live() {
  const [allChars, setAllChars] = useState<string[]>([])
  const [team0, setTeam0] = useState<string[]>([])
  const [team1, setTeam1] = useState<string[]>([])
  const [profile, setProfile] = useState<LiveProfile | null>(null)
  const [humanPlayer, setHumanPlayer] = useState<0 | 1>(0)
  const [opponent, setOpponent] = useState<OpponentSpec>({
    type: 'semantic_rl',
  })

  const [selection, setSelection] = useState<{ kind: string; slot: number } | null>(null)
  const [gameOpponent, setGameOpponent] = useState('当前 RL 模型')
  const [history, setHistory] = useState<string[]>([])
  const [view, setView] = useState<StateView | null>(null)
  const [legalActions, setLegalActions] = useState<LegalAction[]>([])
  const [currentPlayer, setCurrentPlayer] = useState<number>(0)
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)
  const [gameHuman, setGameHuman] = useState<0 | 1>(0)
  const [err, setErr] = useState<string | null>(null)
  const [connState, setConnState] = useState<
    'idle' | 'connected' | 'reconnecting' | 'disconnected' | 'closed'
  >('idle')
  const clientRef = useRef<LiveClient | null>(null)

  useEffect(() => {
    fetch('/api/live/profile').then((r) => { if (!r.ok) throw new Error('无法读取对战配置'); return r.json() })
      .then((profile: LiveProfile) => {
        setProfile(profile)
        setAllChars(profile.characters)
        setTeam0(profile.team_0)
        setTeam1(profile.team_1)
      })
      .catch((e) => setErr(String(e)))
    return () => {
      clientRef.current?.close()
    }
  }, [])

  const onFrame = (frame: LiveFrame) => {
    setBusy(false)
    setSelection(null)
    if (frame.type === 'error') {
      setErr(frame.message)
      return
    }
    setErr(null)
    setGameHuman(frame.human_player as 0 | 1)
    setHistory(frame.history ?? [])
    setView(frame.view)
    setLegalActions(frame.legal_actions || [])
    setCurrentPlayer(frame.current_player)
    setDone(frame.done)
  }

  const validate = (): string | null => {
    if (opponent.type === 'semantic_rl') {
      if (!profile) return '对战配置仍在加载'
      if (!profile.available) return profile.unavailable_reason || '当前 RL 模型不可用'
      if (team0.length !== profile.team_size || team1.length !== profile.team_size) {
        return `双方各选择 ${profile.team_size} 名角色`
      }
      if (profile.disjoint_teams && team0.some((name) => team1.includes(name))) {
        return '双方角色不能重叠'
      }
    }
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
    setGameOpponent(opponent.type === 'semantic_rl' ? '当前 RL 模型' : opponent.type === 'random' ? '随机对手 · 练习对局' : opponent.type)
    setView(null)
    setLegalActions([])
    setDone(false)
    setBusy(true)

    // Close the previous client before creating a new one — otherwise
    // stale WS messages from the old session bleed into this state.
    clientRef.current?.close()

    const c = new LiveClient(onFrame, (state) => setConnState(state))
    clientRef.current = c
    try {
      await c.connect()
      c.send({
        type: 'new',
        profile_rules: true,
        team_0: team0,
        team_1: team1,
        opponent,
        human_player: humanPlayer,
      })
    } catch (e) {
      // Connection failed — clear ref so pickAction doesn't throw
      // on the dead client (A8).
      clientRef.current = null
      setBusy(false)
      setConnState('disconnected')
      setErr(String(e))
    }
  }

  const pickAction = (idx: number) => {
    if (!clientRef.current || done || busy) return
    setBusy(true)
    clientRef.current.send({ type: 'action', index: idx })
  }

  const playCard = (_playerIdx: number, handIdx: number) => {
    if (!view) return
    setSelection({ kind: 'Card', slot: handIdx })
  }

  const selectChar = (playerIdx: number, charIdx: number) => {
    if (playerIdx !== gameHuman || !view) return
    setSelection({ kind: 'Switch', slot: charIdx })
  }

  const isHumanTurn = currentPlayer === gameHuman && !done && !busy

  return (
    <div className="game-shell flex flex-col h-full overflow-y-auto p-3 md:p-5 gap-3">
      <details className="match-settings" open={!view}><summary>对战设置 · 阵容与对手</summary>
      <p className="text-xs text-slate-400 mb-3">
        {profile
          ? `${profile.name}。每队选择 ${profile.team_size} 名角色；${profile.allow_overlap ? '双方阵容可重叠' : '双方阵容不可重叠'}。沿用训练牌组与最多 ${profile.max_rounds} 回合规则。${
              profile.evaluation && typeof profile.evaluation.score === 'number'
                ? ` 评估：对 F1-D${profile.evaluation.opponent_depth ?? 2} 胜率 ${(profile.evaluation.score * 100).toFixed(1)}%（${profile.evaluation.scenarios ?? '?'} 场景）。`
                : ''
            }`
          : '正在读取当前模型与训练规则…'}
      </p>
      <div className="flex flex-wrap items-end gap-3 p-3 rounded-lg border border-slate-700 bg-slate-900/60">
        <TeamPicker
          label={`阵容 P0${humanPlayer === 0 ? ' (you)' : ''}`}
          team={team0}
          setTeam={setTeam0}
          allChars={allChars}
          limit={profile?.team_size ?? 1}
        />
        <TeamPicker
          label={`阵容 P1${humanPlayer === 1 ? ' (you)' : ''}`}
          team={team1}
          setTeam={setTeam1}
          allChars={allChars}
          limit={profile?.team_size ?? 1}
        />
        <div className="flex flex-col gap-1">
          <div className="text-xs text-slate-400">我的席位</div>
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
          {connState === 'idle' ? '开始对战' : '重新开局'}
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
        {profile && !profile.available && !err && opponent.type === 'semantic_rl' && (
          <span className="text-xs text-rose-400">
            当前 RL 模型不可用：{profile.unavailable_reason}
          </span>
        )}
        {done && view && (
          <span className="text-xs text-amber-300">
            对局结束：{view.winner === gameHuman ? '你赢了' : view.winner === 2 ? '平局' : '对方获胜'}
          </span>
        )}
        {view && !done && isHumanTurn && view.phase === 'select_active' && (
          <span className="text-xs text-sky-300">
            点击角色选择出战
          </span>
        )}
        {view && !done && isHumanTurn && view.phase === 'action' && (
          <span className="text-xs text-sky-300">
            轮到你了：在下方选择行动与骰子支付
          </span>
        )}
        {view && !done && !isHumanTurn && (
          <span className="text-xs text-slate-400">对方行动中…</span>
        )}
      </div>

      </details>
      {err && view && <p role="alert" className="text-sm text-rose-300">{err}</p>}
      {view && (
        <>
          <div className="flex justify-between gap-2 text-xs text-slate-300"><span>{gameOpponent}</span><span aria-live="polite">{done ? (view.winner === gameHuman ? '你赢了' : view.winner === 2 ? '平局' : '对方获胜') : isHumanTurn ? '等待你的行动' : '对方行动中…'}</span></div>
          <Board
            view={view}
            humanPlayer={gameHuman}
            onPlayCard={isHumanTurn ? playCard : undefined}
            onSelectChar={isHumanTurn ? selectChar : undefined}
          />
          <section className="action-dock flex flex-col gap-2">
            <h3 className="text-xs font-semibold text-slate-300">
              {done ? '对局结束' : !isHumanTurn ? '对方行动中…' : view.phase === 'select_active' ? '选择出战角色，再确认出战' : selection ? '选择目标与支付方式，再执行行动' : '轮到你了 · 使用技能，或点击手牌与角色查看行动'}
              {selection && <button className="ml-3 underline text-amber-200" onClick={() => setSelection(null)}>返回全部行动</button>}
            </h3>
            <LegalActionList
              view={view}
              humanPlayer={gameHuman}
              actions={selection ? legalActions.filter(a => (a.kind_name === selection.kind || (selection.kind === 'Card' && a.kind_name === 'Tune')) && a.slot === selection.slot) : legalActions.filter(a => a.kind_name !== 'Card' && a.kind_name !== 'Switch' && a.kind_name !== 'Tune')}
              onPick={pickAction}
              disabled={!isHumanTurn}
            />
          </section>
          <details className="text-xs text-slate-300"><summary>对局记录</summary><div className="max-h-40 overflow-auto flex flex-col-reverse">{[...history].reverse().map((line, i) => <div key={i}>{line}</div>)}</div></details>
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
  limit: number
}

function TeamPicker({ label, team, setTeam, allChars, limit }: TeamPickerProps) {
  const toggle = (name: string) => {
    setTeam(team.includes(name) ? team.filter((n) => n !== name) : team.length < limit ? [...team, name] : team)
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
      <div className="flex flex-wrap gap-1">
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
            {name}{team.includes(name) ? ` ${team.indexOf(name) + 1}` : ''}
          </button>
        ))}
      </div>
    </div>
  )
}
