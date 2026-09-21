import { CheckpointPicker } from './CheckpointPicker'
import type { OpponentSpec } from '../api/live'

interface Props {
  value: OpponentSpec
  onChange: (v: OpponentSpec) => void
}

const TYPES: OpponentSpec['type'][] = ['semantic_rl', 'random', 'mcts_pure', 'az', 'cfr']

export function OpponentPicker({ value, onChange }: Props) {
  const setType = (t: OpponentSpec['type']) => {
    // Default fields per type
    if (t === 'semantic_rl') {
      onChange({ type: 'semantic_rl' })
    } else if (t === 'random') {
      onChange({ type: 'random' })
    } else if (t === 'mcts_pure') {
      onChange({ type: 'mcts_pure', n_simulations: 200 })
    } else if (t === 'az' || t === 'cfr') {
      onChange({ type: t, ckpt: '', n_simulations: 0 })
    }
  }

  const needsCkpt = value.type === 'az' || value.type === 'cfr'
  const hasBudget =
    value.type === 'mcts_pure' ||
    value.type === 'az' ||
    value.type === 'cfr'

  return (
    <div className="flex flex-col gap-1">
      <div className="text-xs text-slate-400">对手模型</div>
      <div className="flex flex-wrap gap-2 items-end">
        <select
          value={value.type}
          onChange={(e) => setType(e.target.value as OpponentSpec['type'])}
          className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200"
        >
          {TYPES.map((t) => (
            <option key={t} value={t}>
              {t === 'semantic_rl' ? '当前模型' : t === 'random' ? '随机练习对手' : t === 'mcts_pure' ? '纯搜索对手' : t.toUpperCase()}
            </option>
          ))}
        </select>

        {needsCkpt && (
          <CheckpointPicker
            value={(value as { ckpt: string }).ckpt}
            onChange={(c) =>
              onChange({
                ...(value as Exclude<OpponentSpec, { type: 'semantic_rl' } | { type: 'random' } | { type: 'mcts_pure'; n_simulations: number }>),
                ckpt: c,
              })
            }
          />
        )}

        {hasBudget && (
          <label className="flex flex-col gap-1 text-xs text-slate-400">
            搜索次数
            <input
              type="number"
              min={0}
              step={1}
              value={(value as { n_simulations?: number }).n_simulations ?? 0}
              onChange={(e) => {
                const n = Math.max(0, parseInt(e.target.value) || 0)
                if (value.type === 'mcts_pure') {
                  onChange({ type: 'mcts_pure', n_simulations: Math.max(1, n) })
                } else if (value.type === 'az' || value.type === 'cfr') {
                  onChange({ ...value, n_simulations: n })
                }
              }}
              className="w-20 bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200"
            />
          </label>
        )}
      </div>
      {value.type === 'mcts_pure' && (
        <div className="text-[10px] text-slate-500">
          不使用神经网络，仅通过局面搜索决策。
        </div>
      )}
      {value.type === 'az' && (
        <div className="text-[10px] text-slate-500">
          搜索次数为 0 时直接采用策略网络，否则结合搜索决策。
        </div>
      )}
      {value.type === 'cfr' && (
        <div className="text-[10px] text-slate-500">
          搜索次数为 0 时直接采用策略网络，否则结合搜索决策。
        </div>
      )}
      {value.type === 'random' && (
        <div className="text-[10px] text-slate-500">
          从当前合法行动中随机选择。
        </div>
      )}
    </div>
  )
}
