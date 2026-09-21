import { useEffect, useRef, useState } from 'react'
import { LiveClient, type LiveProfile, type OpponentSpec } from '../api/live'
import type { LegalAction, LiveFrame, StateView } from '../types/state'
import { ActionFlow } from '../components/ActionFlow'
import { Board } from '../components/Board'
import { MatchSetup } from '../components/MatchSetup'

type Selection = { kind: 'Card' | 'Switch'; slot: number; mode?: 'play' | 'tune' }

export function Live() {
  const [allChars, setAllChars] = useState<string[]>([])
  const [team0, setTeam0] = useState<string[]>([])
  const [team1, setTeam1] = useState<string[]>([])
  const [profile, setProfile] = useState<LiveProfile | null>(null)
  const [humanPlayer, setHumanPlayer] = useState<0 | 1>(0)
  const [opponent, setOpponent] = useState<OpponentSpec>({ type: 'semantic_rl' })
  const [selection, setSelection] = useState<Selection | null>(null)
  const [history, setHistory] = useState<string[]>([])
  const [view, setView] = useState<StateView | null>(null)
  const [legalActions, setLegalActions] = useState<LegalAction[]>([])
  const [currentPlayer, setCurrentPlayer] = useState(0)
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)
  const [gameHuman, setGameHuman] = useState<0 | 1>(0)
  const [gameOpponent, setGameOpponent] = useState('当前模型')
  const [err, setErr] = useState<string | null>(null)
  const [connState, setConnState] = useState<'idle' | 'connected' | 'reconnecting' | 'disconnected' | 'closed'>('idle')
  const [decisionKey, setDecisionKey] = useState(0)
  const [gameStage, setGameStage] = useState<HTMLDivElement | null>(null)
  const clientRef = useRef<LiveClient | null>(null)

  useEffect(() => {
    fetch('/api/live/profile')
      .then((response) => {
        if (!response.ok) throw new Error('无法读取对战配置')
        return response.json()
      })
      .then((next: LiveProfile) => {
        setProfile(next)
        setAllChars(next.characters)
        setTeam0(next.team_0)
        setTeam1(next.team_1)
      })
      .catch((error) => setErr(String(error)))
    return () => clientRef.current?.close()
  }, [])

  const onFrame = (frame: LiveFrame) => {
    setBusy(false)
    if (frame.type === 'error') {
      setErr(frame.message)
      return
    }
    setErr(null)
    setSelection(null)
    setDecisionKey((key) => key + 1)
    setGameHuman(frame.human_player as 0 | 1)
    setHistory(frame.history ?? [])
    setView(frame.view)
    setLegalActions(frame.legal_actions || [])
    setCurrentPlayer(frame.current_player)
    setDone(frame.done)
  }

  const validate = () => {
    if (opponent.type === 'semantic_rl') {
      if (!profile) return '对战配置仍在加载'
      if (!profile.available) return profile.unavailable_reason || '当前模型不可用'
      if (team0.length !== profile.team_size || team1.length !== profile.team_size) return `双方各选择 ${profile.team_size} 名角色`
      if (profile.disjoint_teams && team0.some((name) => team1.includes(name))) return '双方角色不能重叠'
    }
    if (team0.length === 0 || team1.length === 0) return '双方阵容不能为空'
    if ((opponent.type === 'az' || opponent.type === 'cfr') && !opponent.ckpt) return '请选择模型存档'
    if (opponent.type === 'mcts_pure' && opponent.n_simulations <= 0) return '搜索次数必须大于 0'
    return null
  }

  const start = async () => {
    const invalid = validate()
    if (invalid) {
      setErr(invalid)
      return
    }
    setErr(null)
    setGameOpponent(opponent.type === 'semantic_rl' ? profile?.name ?? '当前模型' : opponent.type === 'random' ? '随机练习对手' : opponent.type.toUpperCase())
    setView(null)
    setLegalActions([])
    setDone(false)
    setBusy(true)
    clientRef.current?.close()
    const client = new LiveClient(onFrame, setConnState)
    clientRef.current = client
    try {
      await client.connect()
      client.send({ type: 'new', profile_rules: true, team_0: team0, team_1: team1, opponent, human_player: humanPlayer })
    } catch (error) {
      clientRef.current = null
      setBusy(false)
      setConnState('disconnected')
      setErr(String(error))
    }
  }

  const pickAction = (index: number) => {
    if (!clientRef.current || done || busy) return
    setBusy(true)
    clientRef.current.send({ type: 'action', index })
  }

  const pickReroll = (counts: number[]) => {
    if (!clientRef.current || done || busy) return
    setBusy(true)
    clientRef.current.send({ type: 'reroll', counts })
  }

  const isHumanTurn = currentPlayer === gameHuman && !done && !busy
  const isReroll = legalActions.length > 0 && legalActions.every((action) => action.kind_name === 'Reroll')
  const outcome = view?.winner === gameHuman ? '你赢了' : view?.winner === 2 ? '平局' : '对方获胜'
  const castableCards = [...new Set(legalActions.filter((action) => action.kind_name === 'Card').map((action) => action.slot))]
  const tunableCards = [...new Set(legalActions.filter((action) => action.kind_name === 'Tune').map((action) => action.slot))]
  const playableCards = [...new Set([...castableCards, ...tunableCards])]
  const switchableChars = [...new Set(legalActions.filter((action) => action.kind_name === 'Switch').map((action) => action.slot))]

  return (
    <div className={`game-shell ${view ? 'match-active' : ''}`}>
      <MatchSetup
        profile={profile} team0={team0} team1={team1} allChars={allChars}
        humanPlayer={humanPlayer} opponent={opponent} started={!!view} busy={busy}
        onTeam0={setTeam0} onTeam1={setTeam1} onHumanPlayer={setHumanPlayer}
        onOpponent={setOpponent} onStart={start}
      />

      {err && <div role="alert" className="live-error">{err}</div>}
      {connState === 'reconnecting' && <div className="connection-banner">正在重新连接…</div>}
      {connState === 'disconnected' && <div className="connection-banner error">连接已断开，请重新开局</div>}

      {view && (
        <div className="live-workspace">
          <main className="live-playfield">
            <div className="match-bar">
              <div><span>对手</span><strong>{gameOpponent}</strong></div>
              <div className={`turn-status ${isHumanTurn ? 'ready' : ''}`} aria-live="polite">
                {done ? outcome : busy || !isHumanTurn ? <><i className="thinking-dot" />对方思考中</> : isReroll ? '选择重掷骰子' : '轮到你行动'}
              </div>
            </div>
            <div className="game-stage" ref={setGameStage}>
              <Board
                view={view}
                humanPlayer={gameHuman}
                selectedCard={selection?.kind === 'Card' ? selection.slot : undefined}
                selectedChar={selection?.kind === 'Switch' ? selection.slot : undefined}
                playableCards={playableCards}
                castableCards={castableCards}
                tunableCards={tunableCards}
                switchableChars={switchableChars}
                onPlayCard={isHumanTurn ? (_player, slot) => { setSelection({ kind: 'Card', slot }); setDecisionKey((key) => key + 1) } : undefined}
                onCardIntent={isHumanTurn ? (slot, mode) => { setSelection({ kind: 'Card', slot, mode }); setDecisionKey((key) => key + 1) } : undefined}
                onSelectChar={isHumanTurn ? (player, slot) => { if (player === gameHuman) { setSelection({ kind: 'Switch', slot }); setDecisionKey((key) => key + 1) } } : undefined}
              />
            </div>
          </main>

          <aside className="command-panel">
            {done ? (
              <div className="result-card"><span>对局结束</span><h2>{outcome}</h2><button onClick={start}>再来一局</button></div>
            ) : isHumanTurn ? (
              <ActionFlow
                key={decisionKey}
                view={view}
                humanPlayer={gameHuman}
                actions={legalActions}
                source={selection}
                onClearSource={() => { setSelection(null); setDecisionKey((key) => key + 1) }}
                onPick={pickAction}
                onReroll={pickReroll}
                dicePortalTarget={gameStage}
              />
            ) : (
              <div className="thinking-card"><span className="thinking-orbit" /><h2>对方正在思考</h2><p>模型完成决策后，对局会自动继续。</p></div>
            )}
            <details className="match-history">
              <summary>对局记录 <span>{history.length}</span></summary>
              <div>{[...history].reverse().map((line, index) => <p key={`${line}-${index}`}>{line}</p>)}</div>
            </details>
          </aside>
        </div>
      )}

      {!view && busy && <div className="match-loading"><span className="thinking-orbit" /><h2>正在准备对局</h2><p>模型载入后将自动开始。</p></div>}
    </div>
  )
}
