import { useState } from 'react'
import type { StateView } from '../types/state'

// Minimal shape the component needs — accepts both LegalAction (live)
// and a mapped AgentLegalAction-with-prob (replay) without depending
// on either concrete type.
export interface DisplayAction {
  index: number
  kind_name: string
  name: string
  slot?: number
  identity?: number[]
  payment?: number[]
  prob?: number
}

interface Props {
  view?: StateView
  humanPlayer?: number
  actions: DisplayAction[]
  onPick?: (index: number) => void
  disabled?: boolean
  topIndex?: number
}

export function LegalActionList({ actions, onPick, disabled, topIndex, view, humanPlayer }: Props) {
  const [selected, setSelected] = useState<Record<string, number>>({})
  const groups = new Map<string, DisplayAction[]>()
  for (const action of actions) {
    const key = action.identity ? JSON.stringify(action.identity) : String(action.index)
    groups.set(key, [...(groups.get(key) ?? []), action])
  }
  const paymentLabel = (a: DisplayAction) => a.kind_name === 'Tune' ? `弃置此牌 · 转换${['火','冰','水','雷','岩','风','草','万能'][a.identity?.[2] ?? -1] ?? ''}骰` : a.payment?.map((n, i) => n ? `${['火','冰','水','雷','岩','风','草','万能'][i]}×${n}` : '').filter(Boolean).join(' ') || '无需骰子'
  if (actions.length === 0) {
    return <div className="text-xs text-slate-500">没有可用行动；请选择其他卡牌或角色</div>
  }
  return (
    <div className="action-grid">
      {[...groups].map(([key, choices]) => {
        const a = choices.find(c => c.index === selected[key]) ?? choices[0]
        const targetPlayer = a.identity?.[3] ?? -1
        const targetChar = a.identity?.[4] ?? -1
        const target = targetPlayer >= 0 && targetChar >= 0 ? view?.players[targetPlayer]?.chars[targetChar]?.name : null
        const isTop = topIndex === a.index
        // Show slot suffix for Card (hand idx) so duplicate-name
        // picks are distinguishable in the list.
        const slotSuffix =
          a.kind_name === 'Card' && typeof a.slot === 'number' && a.slot >= 0
            ? ` · 手牌 ${a.slot + 1}`
            : ''
        return (
          <div key={key} className="action-choice">
          <button
            disabled={disabled}
            onClick={() => onPick?.(a.index)}
            className={`flex-1 flex items-center justify-between gap-2 rounded px-2 py-1 text-xs border transition-colors ${
              disabled
                ? 'border-slate-800 bg-slate-900 text-slate-500 cursor-default'
                : 'border-slate-700 bg-slate-800 hover:border-sky-400 hover:bg-slate-700 cursor-pointer'
            } ${isTop ? 'border-amber-400/60' : ''}`}
          >
            <span className="truncate">
              <span className="text-slate-400">{{ Skill: '技能', Card: '出牌', Switch: '出战', EndTurn: '结束回合', Tune: '调和' }[a.kind_name] ?? a.kind_name} ·</span>{' '}
              {a.name}{slotSuffix}{target && <span className="ml-1 text-emerald-200">→ {humanPlayer === undefined ? `P${targetPlayer}` : targetPlayer === humanPlayer ? '己方' : '敌方'} {target}</span>}
              {a.payment && <span className="ml-2 text-amber-200">{paymentLabel(a)}</span>}
            </span>
            {typeof a.prob === 'number' && (
              <span className="tabular-nums text-slate-400">
                {a.prob.toFixed(3)}
              </span>
            )}
          </button>
          {choices.length > 1 && <select aria-label={`${a.name} 支付方式`} disabled={disabled} value={a.index}
            onChange={e => setSelected(prev => ({...prev, [key]: Number(e.target.value)}))}
            className="max-w-64 bg-slate-800 text-amber-200 rounded p-1 text-xs border border-slate-600">
            {choices.map(c => <option key={c.index} value={c.index}>{paymentLabel(c)}</option>)}
          </select>}
          </div>
        )
      })}
    </div>
  )
}
