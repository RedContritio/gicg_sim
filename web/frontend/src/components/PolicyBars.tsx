import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from 'recharts'
import type { AgentInspection } from '../types/state'

interface Props {
  agent: AgentInspection
}

export function PolicyBars({ agent }: Props) {
  if (agent.policy.length === 0 || agent.legal_actions.length === 0) {
    return <div className="text-xs text-slate-500">no policy</div>
  }
  const data = agent.legal_actions.map((a, i) => ({
    label: `${a.kind}:${a.name}`,
    prob: agent.policy[i] ?? 0,
    index: i,
  }))
  const max = Math.max(...data.map((d) => d.prob), 0.01)

  return (
    <div className="h-56 w-full">
      <ResponsiveContainer>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 4, right: 32, left: 96, bottom: 4 }}
        >
          <XAxis
            type="number"
            domain={[0, max]}
            tick={{ fontSize: 10, fill: '#94a3b8' }}
            stroke="#475569"
          />
          <YAxis
            dataKey="label"
            type="category"
            tick={{ fontSize: 10, fill: '#cbd5e1' }}
            stroke="#475569"
            width={96}
          />
          <Tooltip
            contentStyle={{
              background: '#0f172a',
              border: '1px solid #334155',
              fontSize: 11,
            }}
            formatter={(v) => (typeof v === 'number' ? v.toFixed(3) : String(v))}
          />
          <Bar dataKey="prob" radius={[0, 4, 4, 0]}>
            {data.map((d, i) => (
              <Cell
                key={i}
                fill={d.prob === max ? '#38bdf8' : '#475569'}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
