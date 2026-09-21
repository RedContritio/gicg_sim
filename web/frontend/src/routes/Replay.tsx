import { useEffect, useState } from 'react'
import { getReplay, listReplays, refreshReplays } from '../api/replay'
import type { ReplayDetail, ReplayListEntry } from '../types/state'
import { Board } from '../components/Board'

export function Replay() {
  const [entries, setEntries] = useState<ReplayListEntry[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [step, setStep] = useState(0)
  const [detail, setDetail] = useState<ReplayDetail | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [playing, setPlaying] = useState(false)

  const loadList = () => {
    setLoading(true)
    listReplays()
      .then((response) => {
        setEntries(response.replays)
        setSelected((current) => current ?? response.replays[0]?.rel_path ?? null)
      })
      .catch((error) => setErr(String(error)))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    let cancelled = false
    listReplays()
      .then((response) => {
        if (cancelled) return
        setEntries(response.replays)
        setSelected(response.replays[0]?.rel_path ?? null)
      })
      .catch((error) => { if (!cancelled) setErr(String(error)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!selected) return
    let cancelled = false
    getReplay(selected, step)
      .then((next) => { if (!cancelled) setDetail(next) })
      .catch((error) => { if (!cancelled) setErr(String(error)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [selected, step])

  useEffect(() => {
    if (!playing || !detail) return
    if (step >= detail.total_steps) return
    const timer = window.setTimeout(() => {
      const next = step + 1
      setLoading(true)
      setStep(next)
      if (next >= detail.total_steps) setPlaying(false)
    }, 800)
    return () => window.clearTimeout(timer)
  }, [playing, detail, step])

  const selectReplay = (relPath: string) => {
    setPlaying(false)
    setErr(null)
    setLoading(true)
    setDetail(null)
    setSelected(relPath)
    setStep(0)
  }

  const changeStep = (next: number) => {
    if (!detail) return
    setErr(null)
    setLoading(true)
    setStep(Math.max(0, Math.min(detail.total_steps, next)))
  }

  const refresh = async () => {
    setLoading(true)
    setErr(null)
    try {
      await refreshReplays()
      loadList()
    } catch (error) {
      setErr(String(error))
      setLoading(false)
    }
  }

  return (
    <div className="replay-shell">
      <aside className="replay-library">
        <div className="replay-library-heading">
          <div><span>对局档案</span><strong>{entries.length} 场</strong></div>
          <button disabled={loading} onClick={refresh} title="刷新回放">↻</button>
        </div>
        {entries.length === 0 && !loading && <div className="replay-empty">暂无可用回放</div>}
        <ul>
          {entries.map((entry) => (
            <li key={entry.rel_path}>
              <button className={selected === entry.rel_path ? 'active' : ''} onClick={() => selectReplay(entry.rel_path)} title={entry.rel_path}>
                <strong>{entry.scenario || '未命名对局'}</strong>
                <span>{[...entry.curriculum, entry.stage].filter(Boolean).join(' · ') || entry.session_id}</span>
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <main className="replay-viewer">
        {err && <div role="alert" className="live-error">{err}</div>}
        {!detail && (loading || selected) && <div className="match-loading"><span className="thinking-orbit" /><h2>正在载入回放</h2></div>}
        {!detail && !loading && !selected && !err && <div className="replay-welcome"><span>✧</span><h2>选择一场对局</h2><p>查看每一步行动和牌局状态。</p></div>}
        {detail && (
          <>
            <div className="replay-toolbar">
              <div className="replay-title">
                <span>{detail.stage || '对局回放'}</span>
                <strong>{detail.teams[0].join('、')} 对阵 {detail.teams[1].join('、')}</strong>
              </div>
              <div className="replay-controls">
                <button disabled={step <= 0} onClick={() => changeStep(step - 1)} aria-label="上一步">←</button>
                <button className="play-toggle" onClick={() => setPlaying((value) => !value)}>{playing ? '暂停' : '播放'}</button>
                <button disabled={step >= detail.total_steps} onClick={() => changeStep(step + 1)} aria-label="下一步">→</button>
                <span>{step} / {detail.total_steps}</span>
              </div>
              <input aria-label="回放进度" type="range" min={0} max={detail.total_steps} value={step} onChange={(event) => changeStep(Number(event.target.value))} />
            </div>
            <Board view={detail.view} />
          </>
        )}
      </main>
    </div>
  )
}
