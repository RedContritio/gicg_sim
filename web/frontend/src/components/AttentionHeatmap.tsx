import { useState } from 'react'
import type { AttentionLayer } from '../types/state'

interface Props {
  layers: AttentionLayer[]
}

export function AttentionHeatmap({ layers }: Props) {
  const [selected, setSelected] = useState(0)
  if (layers.length === 0) {
    return <div className="text-xs text-slate-500">no attention captured</div>
  }
  const active = layers[Math.min(selected, layers.length - 1)]
  const weights = active.weights
  const nRows = weights.length
  const nCols = weights[0]?.length ?? 0
  if (nRows === 0 || nCols === 0) {
    return <div className="text-xs text-slate-500">empty attention</div>
  }

  // Find max for normalization.
  let max = 0
  for (const row of weights) for (const v of row) if (v > max) max = v
  const denom = max > 0 ? max : 1

  const cell = 10
  const pad = 4
  const width = nCols * cell + pad * 2
  const height = nRows * cell + pad * 2

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2 text-xs text-slate-300">
        <span>layer</span>
        <select
          value={selected}
          onChange={(e) => setSelected(Number(e.target.value))}
          className="bg-slate-800 border border-slate-600 rounded px-1 py-0.5"
        >
          {layers.map((l, i) => (
            <option key={i} value={i}>
              L{l.layer} {l.direction}
            </option>
          ))}
        </select>
        <span className="text-slate-500">
          {nRows}×{nCols}
        </span>
      </div>
      <svg
        width={width}
        height={height}
        className="bg-slate-950 rounded"
      >
        {weights.map((row, ri) =>
          row.map((v, ci) => {
            const t = v / denom
            const hue = 220
            const light = 10 + t * 70
            return (
              <rect
                key={`${ri}-${ci}`}
                x={pad + ci * cell}
                y={pad + ri * cell}
                width={cell - 1}
                height={cell - 1}
                fill={`hsl(${hue}, 80%, ${light}%)`}
              >
                <title>
                  q={ri} k={ci} w={v.toFixed(4)}
                </title>
              </rect>
            )
          }),
        )}
      </svg>
    </div>
  )
}
