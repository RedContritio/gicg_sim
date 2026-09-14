import type { CharView } from '../types/state'
import { CardArt } from './CardArt'

interface Props {
  char: CharView
  isActive: boolean
  isCurrentTurn?: boolean
  onSelect?: () => void
}

export function CharPortrait({ char, isActive, isCurrentTurn, onSelect }: Props) {
  const clickable = !!onSelect && char.alive
  return (
    <div className={`character-wrap ${isActive ? 'active' : ''}`}>
      <button disabled={!clickable} onClick={onSelect}
        className={`character-card element-${char.element ?? 'none'} ${!char.alive ? 'defeated' : ''} ${isCurrentTurn && isActive ? 'has-turn' : ''}`}
        title={`${char.name} · 生命 ${char.hp}/${char.hp_max} · 充能 ${char.energy}/${char.energy_max}${clickable ? ' · 点击选择' : ''}`}>
        <CardArt key={char.name} name={char.name} />
        <span className="hp-gem" aria-label={`生命 ${char.hp}/${char.hp_max}`}>{char.hp}</span>
        <span className="character-name">{char.name}</span>
        <span className="energy-track" aria-label={`充能 ${char.energy}/${char.energy_max}`}>
          {Array.from({ length: char.energy_max }, (_, i) => <span key={i} className={i < char.energy ? 'charged' : ''}>◆</span>)}
        </span>
        {!char.alive && <span className="defeated-label">已倒下</span>}
      </button>
      <div className="character-statuses">
        {char.statuses?.map((s, i) => <span key={`${s.name}-${i}`} title={`${s.name}：${s.value}${s.max > 0 ? `/${s.max}` : ''}`}>{s.name} <b>{s.value}</b></span>)}
      </div>
    </div>
  )
}
