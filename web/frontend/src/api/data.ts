// TTL-based in-memory cache for the data endpoints. These are hit on
// every Live / Replay page mount; the underlying scans are
// inexpensive but not free (checkpoints rglobs artifacts/). A 10s
// TTL keeps the browser UI snappy without introducing staleness that
// surprises the operator during a training session.
const CACHE_TTL_MS = 10_000

interface CacheEntry<T> {
  value: T
  t: number
}
const _cache: Map<string, CacheEntry<unknown>> = new Map()

async function cachedFetchJson<T>(url: string, pick: (body: unknown) => T): Promise<T> {
  const hit = _cache.get(url) as CacheEntry<T> | undefined
  if (hit && Date.now() - hit.t < CACHE_TTL_MS) return hit.value
  const r = await fetch(url)
  if (!r.ok) throw new Error(`${url}: ${r.status}`)
  const body = await r.json()
  const value = pick(body)
  _cache.set(url, { value, t: Date.now() })
  return value
}

export function invalidateDataCache(): void {
  _cache.clear()
}

export async function listChars(): Promise<string[]> {
  return cachedFetchJson('/api/data/chars', (b) =>
    ((b as { chars?: string[] }).chars ?? []),
  )
}

export async function listCards(): Promise<string[]> {
  return cachedFetchJson('/api/data/cards', (b) =>
    ((b as { cards?: string[] }).cards ?? []),
  )
}

export interface CheckpointEntry {
  path: string
  session_id: string
  stage: string
  kind: 'main' | 'partial' | 'failed' | 'pool' | 'legacy' | 'other'
  label: string
  mtime: number
}

export async function listCheckpoints(): Promise<CheckpointEntry[]> {
  return cachedFetchJson('/api/checkpoints', (b) =>
    ((b as { checkpoints?: CheckpointEntry[] }).checkpoints ?? []),
  )
}
