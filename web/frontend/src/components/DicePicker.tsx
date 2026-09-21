import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { createPortal } from 'react-dom'
import { DICE_NAMES, dieColorFromId } from './dice'

interface PickerProps {
  pool: number[]
  selected: ReadonlySet<string>
  onChange: (selected: Set<string>) => void
  maxSelected?: number
  selectableColors?: ReadonlySet<number>
  disabled?: boolean
}

interface DialogProps extends PickerProps {
  kicker: string
  title: string
  guidance: string
  status: string
  error?: string | null
  confirmLabel: string
  confirmDisabled?: boolean
  onConfirm: () => void
  onBack?: () => void
  portalTarget?: HTMLElement | null
}

interface Gesture {
  pointerId: number
  selecting: boolean
  visited: Set<string>
}

export function DicePicker({
  pool,
  selected,
  onChange,
  maxSelected = Number.POSITIVE_INFINITY,
  selectableColors,
  disabled,
}: PickerProps) {
  const selectedRef = useRef(new Set(selected))
  const gestureRef = useRef<Gesture | null>(null)

  useEffect(() => {
    selectedRef.current = new Set(selected)
  }, [selected])

  const changeDie = (id: string, selecting: boolean) => {
    const next = new Set(selectedRef.current)
    if (selecting) {
      if (next.size >= maxSelected) return
      next.add(id)
    } else {
      next.delete(id)
    }
    selectedRef.current = next
    onChange(next)
  }

  const dieAt = (clientX: number, clientY: number) => {
    const element = document.elementFromPoint(clientX, clientY)?.closest<HTMLElement>('[data-die-id]')
    if (!element || element.getAttribute('aria-disabled') === 'true') return null
    return element.dataset.dieId ?? null
  }

  const beginGesture = (event: ReactPointerEvent<HTMLDivElement>) => {
    const id = (event.target as HTMLElement).closest<HTMLElement>('[data-die-id]')?.dataset.dieId
    if (!id || disabled) return
    const color = dieColorFromId(id)
    if (selectableColors && !selectableColors.has(color)) return
    event.preventDefault()
    const selecting = !selectedRef.current.has(id)
    if (selecting && selectedRef.current.size >= maxSelected) return
    gestureRef.current = { pointerId: event.pointerId, selecting, visited: new Set([id]) }
    event.currentTarget.setPointerCapture(event.pointerId)
    changeDie(id, selecting)
  }

  const continueGesture = (event: ReactPointerEvent<HTMLDivElement>) => {
    const gesture = gestureRef.current
    if (!gesture || gesture.pointerId !== event.pointerId) return
    event.preventDefault()
    const id = dieAt(event.clientX, event.clientY)
    if (!id || gesture.visited.has(id)) return
    const color = dieColorFromId(id)
    if (selectableColors && !selectableColors.has(color)) return
    gesture.visited.add(id)
    changeDie(id, gesture.selecting)
  }

  const endGesture = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (gestureRef.current?.pointerId !== event.pointerId) return
    gestureRef.current = null
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }

  const tokens = pool.flatMap((count, color) =>
    Array.from({ length: count }, (_, ordinal) => ({
      id: `die-${color}-${ordinal}`,
      color,
    })),
  )

  return (
    <div
      className="dice-picker"
      onPointerDown={beginGesture}
      onPointerMove={continueGesture}
      onPointerUp={endGesture}
      onPointerCancel={endGesture}
    >
      {tokens.map(({ id, color }) => {
        const isSelected = selected.has(id)
        const isSelectable = !disabled && (!selectableColors || selectableColors.has(color))
        return (
          <button
            type="button"
            key={id}
            data-die-id={id}
            className={`octahedron-die die-color-${color} ${isSelected ? 'selected' : ''}`}
            aria-label={`${DICE_NAMES[color]}骰${isSelected ? '，已选择' : ''}`}
            aria-pressed={isSelected}
            aria-disabled={!isSelectable}
            tabIndex={isSelectable ? 0 : -1}
            onClick={(event) => {
              if (event.detail === 0 && isSelectable) changeDie(id, !selectedRef.current.has(id))
            }}
          >
            <svg viewBox="0 0 100 120" aria-hidden="true">
              <polygon className="die-face die-face-left" points="50,3 50,59 7,59" />
              <polygon className="die-face die-face-top" points="50,3 93,59 50,59" />
              <polygon className="die-face die-face-bottom" points="7,59 50,59 50,117" />
              <polygon className="die-face die-face-right" points="50,59 93,59 50,117" />
              <polygon className="die-outline" points="50,3 93,59 50,117 7,59" />
            </svg>
            <span>{DICE_NAMES[color]}</span>
            <i aria-hidden="true">✓</i>
          </button>
        )
      })}
    </div>
  )
}

export function DiceSelectionDialog({
  kicker,
  title,
  guidance,
  status,
  error,
  confirmLabel,
  confirmDisabled,
  onConfirm,
  onBack,
  portalTarget,
  ...pickerProps
}: DialogProps) {
  const [observing, setObserving] = useState(false)

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (observing) setObserving(false)
      else onBack?.()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [observing, onBack])

  if (!portalTarget) return null

  if (observing) {
    return createPortal(
      <div className="dice-observation-shield">
        <button type="button" className="dice-observe-return" onClick={() => setObserving(false)}>
          <EyeIcon />
          <span>继续选择</span>
        </button>
      </div>,
      portalTarget,
    )
  }

  return createPortal(
    <div className="dice-dialog-layer">
      <section className="dice-dialog" role="dialog" aria-modal="true" aria-labelledby="dice-dialog-title">
        <header>
          <div>
            <span>{kicker}</span>
            <h2 id="dice-dialog-title">{title}</h2>
          </div>
          <div className="dice-dialog-tools">
            <button type="button" className="dice-observe" onClick={() => setObserving(true)}>
              <EyeIcon />
              <span>查看局面</span>
            </button>
            {onBack && <button type="button" className="dice-dialog-close" onClick={onBack} aria-label="返回">×</button>}
          </div>
        </header>
        <p>{guidance}</p>
        <DicePicker {...pickerProps} />
        <div className={`dice-selection-status ${error ? 'invalid' : ''}`} aria-live="polite">
          <strong>{status}</strong>
          <span>{error ?? '单击切换一枚；按住并拖过骰子可连续选择或取消。'}</span>
        </div>
        <footer>
          {onBack && <button type="button" className="dice-dialog-back" onClick={onBack}>返回</button>}
          <button type="button" className="confirm-action" disabled={confirmDisabled} onClick={onConfirm}>{confirmLabel}</button>
        </footer>
      </section>
    </div>,
    portalTarget,
  )
}

function EyeIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M2.5 12s3.4-6 9.5-6 9.5 6 9.5 6-3.4 6-9.5 6-9.5-6-9.5-6Z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  )
}
