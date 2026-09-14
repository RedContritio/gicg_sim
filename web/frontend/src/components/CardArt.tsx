import { useState } from 'react'
import cardArt from './cardArt.json'

// Illustration URLs from the repository's official card-data snapshot.
export function CardArt({ name }: { name: string }) {
  const [failed, setFailed] = useState(false)
  const url = (cardArt as Record<string, string>)[name]
  return url && !failed
    ? <img className="card-art" src={url} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
    : <span className="card-art-fallback" aria-hidden="true">{name.slice(0, 1)}</span>
}
