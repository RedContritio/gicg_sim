import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts'

interface Props {
  values: number[]
  currentStep?: number
}

export function ValueTimeline({ values, currentStep }: Props) {
  if (values.length === 0) {
    return <div className="text-xs text-slate-500">no value history</div>
  }
  const data = values.map((v, i) => ({ step: i, value: v }))

  return (
    <div className="h-32 w-full">
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
          <XAxis
            dataKey="step"
            tick={{ fontSize: 9, fill: '#94a3b8' }}
            stroke="#475569"
          />
          <YAxis
            tick={{ fontSize: 9, fill: '#94a3b8' }}
            stroke="#475569"
            width={32}
          />
          <Tooltip
            contentStyle={{
              background: '#0f172a',
              border: '1px solid #334155',
              fontSize: 11,
            }}
            formatter={(v) => (typeof v === 'number' ? v.toFixed(3) : String(v))}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke="#c084fc"
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
          {currentStep !== undefined && (
            <ReferenceLine
              x={currentStep}
              stroke="#38bdf8"
              strokeDasharray="2 2"
            />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
