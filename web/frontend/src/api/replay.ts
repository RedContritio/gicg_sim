import type {
  ReplayListResponse,
  ReplayDetail,
} from '../types/state'

export async function listReplays(): Promise<ReplayListResponse> {
  const r = await fetch('/api/replays')
  if (!r.ok) throw new Error(`listReplays: ${r.status}`)
  return r.json()
}

export async function refreshReplays(): Promise<{ count: number }> {
  const r = await fetch('/api/replays/refresh', { method: 'POST' })
  if (!r.ok) throw new Error(`refreshReplays: ${r.status}`)
  return r.json()
}

export async function getReplay(
  relPath: string,
  step: number,
  ckpt?: string,
): Promise<ReplayDetail> {
  const params = new URLSearchParams({ step: String(step) })
  if (ckpt) params.set('ckpt', ckpt)
  const r = await fetch(`/api/replay/${relPath}?${params}`)
  if (!r.ok) {
    const body = await r.text()
    throw new Error(`getReplay(${relPath}, ${step}): ${r.status} ${body}`)
  }
  return r.json()
}
