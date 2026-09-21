// Mirror of gicg_engine/record/export_view.go::StateView.
// Shape comes from Go JSON tags, keep in sync when the Go struct changes.

export type Phase =
  | 'not_started'
  | 'select_active'
  | 'round_start'
  | 'action'
  | 'round_end'
  | 'game_over'
  | 'unknown'

export interface StatusView {
  name: string
  value: number
  max: number
}

export interface CardView {
  ref: number
  name: string
}

export interface CharView {
  element?: string
  name: string
  hp: number
  hp_max: number
  energy: number
  energy_max: number
  alive: boolean
  active: boolean
  statuses: StatusView[] | null
}

export interface PlayerView {
  supports?: StatusView[]
  summons?: StatusView[]
  dice_count?: number
  hand_count?: number
  dice?: number[]
  statuses?: StatusView[]
  active_char: number
  alive_count: number
  chars: CharView[]
  hand: CardView[] | null
  deck_count: number
}

export interface StateView {
  acting_player?: number
  phase: Phase
  round: number
  turn: number
  first_player: number
  winner: number
  players: [PlayerView, PlayerView]
}

// ---- Legal actions (from engine labels) ----

// What the live backend's _build_legal_actions emits per legal slot.
// Frontend uses this to render playable moves and to match clicks on
// hand / char portraits back to the action index.
export interface LegalAction {
  identity?: number[]
  payment?: number[]
  refs?: number[]
  index: number              // echo back in {'type':'action', index}
  kind: number               // numeric engine enum (0=Skill/1=Card/2=Switch/3=EndTurn)
  kind_name: string          // "Skill" | "Card" | "Switch" | "EndTurn"
  name: string               // DSL-resolved name
  slot: number               // hand_idx for Card, char_idx for Switch, -1 else
  prob?: number              // optional AI prior (future — currently unused)
}

// What replay_api returns under detail.agent.legal_actions. Different
// shape from live's LegalAction — the replay side predates the engine-
// label unification. Kept as its own type so they don't bleed.
export interface AgentLegalAction {
  kind: string               // "Skill" | "Card" | ...
  name: string
}

export interface TopKEntry {
  index: number
  kind: string
  name: string
  prob: number
}

export interface AttentionLayer {
  layer: number
  direction: string
  shape: number[]
  weights: number[][]
}

export interface AgentInspection {
  value: number
  entropy: number
  policy: number[]
  top_k: TopKEntry[]
  attention: AttentionLayer[]
  legal_actions: AgentLegalAction[]
  error?: string
}

// ---- API response shapes ----

export interface ReplayListEntry {
  rel_path: string
  session_id: string
  // Backend sends List[str] of curriculum dir parts (empty for
  // go_tests fixtures / legacy). Joined for display by the UI.
  curriculum: string[]
  stage: string | null
  scenario: string
  size_bytes: number
}

export interface ReplayListResponse {
  replays: ReplayListEntry[]
}

export interface ReplayDetail {
  rel_path: string
  stage: string
  step: number
  total_steps: number
  rounds: number
  winner: number
  teams: [string[], string[]]
  view: StateView
  agent: AgentInspection | null
}

// Live WebSocket frames
export interface LiveStateFrame {
  type: 'state'
  session_id?: string | null
  history?: string[]
  view: StateView
  done: boolean
  current_player: number
  human_player: number
  legal_actions: LegalAction[]
  winner?: number
  // Agent inspection is optional — populated only for opponent types
  // that expose priors (future: AZ / CFR under observe mode). Human-
  // vs-AI play doesn't require it.
  agent?: AgentInspection | null
}

export interface LiveErrorFrame {
  type: 'error'
  message: string
}

export type LiveFrame = LiveStateFrame | LiveErrorFrame
