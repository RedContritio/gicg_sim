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
  refs?: number[]
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
  // 支付推荐排序（09-20）：万能骰是稀缺通用资源，默认推荐应优先用元素
  // （杂色）骰支付 — 小组内按万能用量升序排，默认落在第一个（零万能
  // 或最少万能）的组合上。用户仍可手动展开下拉换其他组合。
  const OMNI = 7
  const omniCount = (a: DisplayAction) => a.payment?.[OMNI] ?? 0
  for (const choices of groups.values()) {
    choices.sort((x, y) => omniCount(x) - omniCount(y))
  }

  // 重掷阶段（09-20）：回合开始的重掷决策帧。引擎按「每颜色选数量，
  // 最后确认」拆成多个帧，每帧的合法动作 kind 均为 Reroll（refs 颜色
  // 8 = 确认帧）。渲染专用面板替代普通行动列表。
  const DICE_NAMES = ['火', '冰', '水', '雷', '岩', '风', '草', '万能']
  if (actions.length > 0 && actions.every(a => a.kind_name === 'Reroll')) {
    const confirm = actions.find(a => (a.refs?.[2] ?? -1) === 8)
    const color = actions[0].refs?.[2] ?? -1
    const pool = (humanPlayer !== undefined && view) ? view.players[humanPlayer]?.dice : undefined
    return (
      <div className="rounded-lg border border-amber-700/60 bg-amber-950/30 p-3">
        <div className="text-sm font-medium text-amber-200 mb-2">
          {confirm ? '重掷确认' : `重掷阶段 · ${DICE_NAMES[color] ?? `颜色${color}`}骰`}
        </div>
        {pool && (
          <div className="text-xs text-slate-300 mb-2">
            当前骰子：{pool.map((n, i) => n > 0 ? `${DICE_NAMES[i]}×${n}` : '').filter(Boolean).join(' ') || '（无）'}
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          {confirm ? (
            <button
              disabled={disabled}
              onClick={() => onPick?.(confirm.index)}
              className="rounded px-3 py-1 text-sm border border-amber-500 bg-amber-800/60 hover:bg-amber-700 text-amber-100 disabled:opacity-40"
            >
              {confirm.name || '确认重投'}
            </button>
          ) : (
            actions.map(a => (
              <button
                key={a.index}
                disabled={disabled}
                onClick={() => onPick?.(a.index)}
                className={`rounded px-3 py-1 text-sm border transition-colors disabled:opacity-40 ${
                  (a.refs?.[1] ?? 0) === 0
                    ? 'border-slate-600 bg-slate-800 text-slate-300 hover:bg-slate-700'
                    : 'border-amber-600 bg-amber-900/40 text-amber-100 hover:bg-amber-800/60'
                }`}
              >
                {a.name}
              </button>
            ))
          )}
        </div>
        <div className="text-xs text-slate-500 mt-2">提示：万能骰通用但稀缺，一般留在手里用元素骰支付。</div>
      </div>
    )
  }
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
              <span className="text-slate-400">{{ Skill: '技能', Card: '出牌', Switch: '出战', EndTurn: '结束回合', Tune: '调和', Reroll: '重掷' }[a.kind_name] ?? a.kind_name} ·</span>{' '}
              {a.name}{slotSuffix}{target && <span className="ml-1 text-emerald-200">→ {humanPlayer === undefined ? `P${targetPlayer}` : targetPlayer === humanPlayer ? '己方' : '敌方'} {target}</span>}
              {a.payment && a.kind_name !== 'Reroll' && <span className="ml-2 text-amber-200">{paymentLabel(a)}</span>}
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
