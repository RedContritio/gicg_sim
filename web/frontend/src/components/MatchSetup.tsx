import type { LiveProfile, OpponentSpec } from '../api/live'
import { OpponentPicker } from './OpponentPicker'

interface Props {
  profile: LiveProfile | null
  team0: string[]
  team1: string[]
  allChars: string[]
  humanPlayer: 0 | 1
  opponent: OpponentSpec
  started: boolean
  busy: boolean
  onTeam0: (team: string[]) => void
  onTeam1: (team: string[]) => void
  onHumanPlayer: (side: 0 | 1) => void
  onOpponent: (opponent: OpponentSpec) => void
  onStart: () => void
}

export function MatchSetup({
  profile, team0, team1, allChars, humanPlayer, opponent, started, busy,
  onTeam0, onTeam1, onHumanPlayer, onOpponent, onStart,
}: Props) {
  const modelName = opponent.type === 'semantic_rl'
    ? profile?.name ?? '当前模型'
    : opponent.type === 'random' ? '随机练习对手' : opponent.type.toUpperCase()
  return (
    <details className="match-settings" open={!started}>
      <summary><span>对战设置</span><strong>{modelName}</strong></summary>
      <div className="setup-grid">
        <TeamPicker label="先手阵容" team={team0} setTeam={onTeam0} allChars={allChars} limit={profile?.team_size ?? 1} />
        <TeamPicker label="后手阵容" team={team1} setTeam={onTeam1} allChars={allChars} limit={profile?.team_size ?? 1} />
        <div className="setup-field">
          <span>我的席位</span>
          <div className="segmented-control">
            <button className={humanPlayer === 0 ? 'active' : ''} onClick={() => onHumanPlayer(0)}>先手</button>
            <button className={humanPlayer === 1 ? 'active' : ''} onClick={() => onHumanPlayer(1)}>后手</button>
          </div>
        </div>
      </div>
      <details className="advanced-settings">
        <summary>高级设置</summary>
        <OpponentPicker value={opponent} onChange={onOpponent} />
      </details>
      {profile && (
        <div className="model-summary">
          <span className={profile.available ? 'available' : 'unavailable'}>{profile.available ? '模型可用' : '模型不可用'}</span>
          <span>每队 {profile.team_size} 人</span>
          <span>最多 {profile.max_rounds} 回合</span>
          {profile.inference.n_simulations > 0 && <span>{profile.inference.n_simulations} 次搜索</span>}
        </div>
      )}
      <button className="start-match" disabled={busy} onClick={onStart}>{started ? '重新开局' : '开始对战'}</button>
    </details>
  )
}

interface TeamPickerProps {
  label: string
  team: string[]
  setTeam: (team: string[]) => void
  allChars: string[]
  limit: number
}

function TeamPicker({ label, team, setTeam, allChars, limit }: TeamPickerProps) {
  const toggle = (name: string) => {
    if (team.includes(name)) setTeam(team.filter((member) => member !== name))
    else if (team.length < limit) setTeam([...team, name])
  }
  return (
    <div className="setup-field team-field">
      <span>{label} · {team.length}/{limit}</span>
      <div className="team-options">
        {allChars.length === 0 && <small>正在读取角色…</small>}
        {allChars.map((name) => (
          <button key={name} className={team.includes(name) ? 'selected' : ''} onClick={() => toggle(name)}>
            {name}{team.includes(name) ? <i>{team.indexOf(name) + 1}</i> : null}
          </button>
        ))}
      </div>
    </div>
  )
}
