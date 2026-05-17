import type { LiveFrame } from '../types/state'

// Opponent spec mirrors training.matchup.LOADERS keys.
// For "az" / "cfr": ckpt path required, n_simulations optional (0 = argmax).
// For "mcts_pure":   n_simulations required (>0).
// For "random":      no extra fields.
export type OpponentSpec =
  | { type: 'random' }
  | { type: 'mcts_pure'; n_simulations: number }
  | { type: 'az'; ckpt: string; n_simulations?: number }
  | { type: 'cfr'; ckpt: string; n_simulations?: number }

export interface LiveNewMessage {
  type: 'new'
  team_0: string[]
  team_1: string[]
  card_pool?: string[] | null
  data_dir?: string
  human_player?: 0 | 1
  opponent: OpponentSpec
  seed?: number
}

export interface LiveActionMessage {
  type: 'action'
  index: number
}

export type LiveOutbound = LiveNewMessage | LiveActionMessage

// Reconnection policy: up to MAX_RECONNECT attempts with exponential
// backoff starting at INITIAL_BACKOFF_MS. After a successful
// reconnect we re-send the last "new" message so the session
// restarts on the server. Idempotent: multiple connect() calls close
// the current socket first.
const MAX_RECONNECT_ATTEMPTS = 3
const INITIAL_BACKOFF_MS = 500

export class LiveClient {
  private ws: WebSocket | null = null
  private onFrame: (frame: LiveFrame) => void
  private onStateChange?: (state: 'connected' | 'disconnected' | 'reconnecting' | 'closed') => void
  private lastNew: LiveNewMessage | null = null
  private reconnectAttempts = 0
  private userClosed = false

  constructor(
    onFrame: (frame: LiveFrame) => void,
    onStateChange?: (state: 'connected' | 'disconnected' | 'reconnecting' | 'closed') => void,
  ) {
    this.onFrame = onFrame
    this.onStateChange = onStateChange
  }

  connect(): Promise<void> {
    this.userClosed = false
    return this._openSocket()
  }

  private _openSocket(): Promise<void> {
    // Close any existing socket before opening a new one.
    if (this.ws) {
      this.ws.onclose = null
      this.ws.close()
      this.ws = null
    }
    return new Promise((resolve, reject) => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      const url = `${proto}://${location.host}/ws/live`
      const ws = new WebSocket(url)
      ws.onopen = () => {
        this.reconnectAttempts = 0
        this.onStateChange?.('connected')
        resolve()
      }
      ws.onerror = () => reject(new Error('WebSocket error'))
      ws.onclose = () => {
        this.ws = null
        if (this.userClosed) {
          this.onStateChange?.('closed')
          return
        }
        // Try to reconnect.
        if (this.reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
          this.reconnectAttempts += 1
          this.onStateChange?.('reconnecting')
          const delay = INITIAL_BACKOFF_MS * Math.pow(2, this.reconnectAttempts - 1)
          setTimeout(() => {
            this._openSocket()
              .then(() => {
                // Replay last "new" so the session resumes on the server.
                // Any mid-game state is lost — the server builds a fresh
                // GicgEnv from the original team/opponent spec.
                if (this.lastNew) {
                  try {
                    this._rawSend(this.lastNew)
                  } catch (e) {
                    console.error('resend on reconnect failed', e)
                  }
                }
              })
              .catch(() => {
                // Next close event will trigger the next attempt.
              })
          }, delay)
        } else {
          this.onStateChange?.('disconnected')
        }
      }
      ws.onmessage = (ev) => {
        try {
          const frame: LiveFrame = JSON.parse(ev.data)
          this.onFrame(frame)
        } catch (e) {
          console.error('bad frame', e)
        }
      }
      this.ws = ws
    })
  }

  private _rawSend(msg: LiveOutbound) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('WebSocket not connected')
    }
    this.ws.send(JSON.stringify(msg))
  }

  send(msg: LiveOutbound) {
    if (msg.type === 'new') {
      // Cache so reconnect can resume.
      this.lastNew = msg
    }
    this._rawSend(msg)
  }

  close() {
    this.userClosed = true
    this.ws?.close()
    this.ws = null
  }
}
