import { useMemo, useState } from 'react'
import type { LegalAction, StateView } from '../types/state'
import { DiceSelectionDialog } from './DicePicker'
import { DICE_NAMES, selectedDiceCounts } from './dice'

interface SourceSelection {
  kind: 'Card' | 'Switch'
  slot: number
  mode?: 'play' | 'tune'
}

interface Props {
  view: StateView
  humanPlayer: number
  actions: LegalAction[]
  disabled?: boolean
  source?: SourceSelection | null
  onClearSource?: () => void
  onPick: (index: number) => void
  onReroll: (counts: number[]) => void
  dicePortalTarget?: HTMLElement | null
}

type Step = 'action' | 'target' | 'payment' | 'confirm'

const KIND_NAMES: Record<string, string> = {
  Skill: '使用技能',
  Card: '打出卡牌',
  Switch: '切换角色',
  EndTurn: '结束回合',
  Tune: '元素调和',
}

function actionKey(action: LegalAction) {
  const identity = action.identity ?? []
  const aux = action.kind_name === 'Tune' ? -1 : identity[2] ?? -1
  return JSON.stringify([
    action.kind_name,
    action.name,
    action.slot,
    identity[0] ?? -1,
    identity[1] ?? -1,
    aux,
  ])
}

function targetKey(action: LegalAction) {
  return `${action.identity?.[3] ?? -1}:${action.identity?.[4] ?? -1}`
}

function groupBy<T>(items: T[], keyOf: (item: T) => string) {
  const groups = new Map<string, T[]>()
  for (const item of items) groups.set(keyOf(item), [...(groups.get(keyOf(item)) ?? []), item])
  return groups
}

function paymentLabel(action: LegalAction) {
  if (action.kind_name === 'Tune') {
    const element = DICE_NAMES[action.identity?.[2] ?? -1] ?? ''
    return element ? `消耗${element}骰进行调和` : '元素调和'
  }
  return action.payment
    ?.map((count, index) => count > 0 ? `${DICE_NAMES[index]} × ${count}` : '')
    .filter(Boolean)
    .join(' ') || '无需消耗骰子'
}

function sortPayments(actions: LegalAction[]) {
  return [...actions].sort((left, right) => {
    const omni = (left.payment?.[7] ?? 0) - (right.payment?.[7] ?? 0)
    return omni || left.index - right.index
  })
}

function initialDecision(actions: LegalAction[], source?: SourceSelection | null) {
  const fallback = {
    step: 'action' as Step,
    chosenActions: [] as LegalAction[],
    targetActions: [] as LegalAction[],
    choice: null as LegalAction | null,
  }
  if (source?.kind !== 'Card' || !source.mode) return fallback
  if (source.mode === 'tune' && actions.length > 0) {
    return {
      ...fallback,
      step: 'payment' as Step,
      chosenActions: actions,
      targetActions: sortPayments(actions),
    }
  }
  const groups = groupBy(actions, actionKey)
  if (groups.size !== 1) return fallback
  const chosenActions = [...groups.values()][0]
  const targets = groupBy(chosenActions, targetKey)
  const hasTarget = targets.size > 1 || chosenActions.some(
    (action) => (action.identity?.[3] ?? -1) >= 0 && (action.identity?.[4] ?? -1) >= 0,
  )
  if (hasTarget) return { ...fallback, step: 'target' as Step, chosenActions }
  const targetActions = sortPayments(chosenActions)
  const needsPayment = targetActions.length > 1 || targetActions.some(
    (action) => (action.payment ?? []).some((count) => count > 0),
  )
  if (needsPayment) return { ...fallback, step: 'payment' as Step, chosenActions, targetActions }
  return {
    step: 'confirm' as Step,
    chosenActions,
    targetActions,
    choice: targetActions[0],
  }
}

export function ActionFlow({
  view,
  humanPlayer,
  actions,
  disabled,
  source,
  onClearSource,
  onPick,
  onReroll,
  dicePortalTarget,
}: Props) {
  const visibleActions = useMemo(() => {
    if (!source) return actions.filter((action) => !['Card', 'Switch', 'Tune'].includes(action.kind_name))
    return actions.filter((action) => {
      const sameSlot = action.slot === source.slot
      if (!sameSlot) return false
      if (source.kind === 'Switch') return action.kind_name === 'Switch'
      if (source.mode === 'play') return action.kind_name === 'Card'
      if (source.mode === 'tune') return action.kind_name === 'Tune'
      return action.kind_name === 'Card' || action.kind_name === 'Tune'
    })
  }, [actions, source])
  const actionGroups = useMemo(() => groupBy(visibleActions, actionKey), [visibleActions])
  const initial = initialDecision(visibleActions, source)
  const [step, setStep] = useState<Step>(initial.step)
  const [chosenActions, setChosenActions] = useState<LegalAction[]>(initial.chosenActions)
  const [targetActions, setTargetActions] = useState<LegalAction[]>(initial.targetActions)
  const [choice, setChoice] = useState<LegalAction | null>(initial.choice)
  const [selectedDice, setSelectedDice] = useState<Set<string>>(new Set())

  const restart = () => {
    setStep('action')
    setChosenActions([])
    setTargetActions([])
    setChoice(null)
    setSelectedDice(new Set())
  }

  const toPayment = (next: LegalAction[]) => {
    const sorted = sortPayments(next)
    setTargetActions(sorted)
    setChoice(null)
    setSelectedDice(new Set())
    if (sorted[0]?.kind_name === 'Tune' || sorted.some((action) => (action.payment ?? []).some((count) => count > 0)) || sorted.length > 1) {
      setStep('payment')
      return
    }
    setChoice(sorted[0])
    setStep('confirm')
  }

  const chooseAction = (next: LegalAction[]) => {
    setChosenActions(next)
    const targets = groupBy(next, targetKey)
    const hasTarget = next.some((action) => (action.identity?.[3] ?? -1) >= 0 && (action.identity?.[4] ?? -1) >= 0)
    if (hasTarget || targets.size > 1) {
      setStep('target')
      return
    }
    toPayment(next)
  }

  const targetGroups = groupBy(chosenActions, targetKey)
  const selected = choice ?? targetActions[0] ?? chosenActions[0]
  const actionHasTarget = targetGroups.size > 1 || chosenActions.some((action) => (action.identity?.[3] ?? -1) >= 0 && (action.identity?.[4] ?? -1) >= 0)
  const actionNeedsPayment = targetActions[0]?.kind_name === 'Tune' || targetActions.some((action) => (action.payment ?? []).some((count) => count > 0)) || targetActions.length > 1

  const goBack = () => {
    if (step === 'target') {
      restart()
    } else if (step === 'payment') {
      setSelectedDice(new Set())
      if (actionHasTarget) setStep('target')
      else restart()
    } else if (step === 'confirm') {
      setChoice(null)
      if (actionNeedsPayment) setStep('payment')
      else if (actionHasTarget) setStep('target')
      else restart()
    }
  }

  if (actions.length > 0 && actions.every((action) => action.kind_name === 'Reroll')) {
    const pool = view.players[humanPlayer]?.dice ?? Array(DICE_NAMES.length).fill(0)
    const counts = selectedDiceCounts(selectedDice)
    const count = selectedDice.size
    return (
      <div className="decision-flow reroll-flow">
        <div className="decision-heading">
          <div><span className="decision-kicker">回合准备</span><h2>选择重掷骰子</h2></div>
        </div>
        <p className="reroll-guidance">在中央选择要重掷的骰子。</p>
        <DiceSelectionDialog
          kicker="回合准备"
          title="选择重掷骰子"
          guidance="选中的骰子将在确认后一起重掷，未选中的骰子会保留。"
          status={count === 0 ? '保留全部骰子' : `已选择 ${count} 枚骰子`}
          confirmLabel={count === 0 ? '全部保留并继续' : `重掷 ${count} 枚骰子`}
          pool={pool}
          selected={selectedDice}
          onChange={setSelectedDice}
          disabled={disabled}
          onConfirm={() => onReroll(counts)}
          portalTarget={dicePortalTarget}
        />
      </div>
    )
  }

  const pool = view.players[humanPlayer]?.dice ?? Array(DICE_NAMES.length).fill(0)
  const paymentCounts = selectedDiceCounts(selectedDice)
  const choosingTuneDie = targetActions[0]?.kind_name === 'Tune'
  const requiredDice = choosingTuneDie
    ? 1
    : targetActions.length > 0
      ? Math.max(0, ...targetActions.map((action) => (action.payment ?? []).reduce((sum, count) => sum + count, 0)))
      : 0
  const paymentChoice = targetActions.find((action) => {
    if (choosingTuneDie) {
      return selectedDice.size === 1 && (action.identity?.[2] ?? -1) === paymentCounts.findIndex((count) => count > 0)
    }
    return (action.payment ?? []).every((count, color) => count === paymentCounts[color])
  }) ?? null
  const tuneColors = choosingTuneDie
    ? new Set(targetActions.map((action) => action.identity?.[2] ?? -1).filter((color) => color >= 0))
    : undefined
  const completeButInvalid = selectedDice.size === requiredDice && paymentChoice === null

  if (actions.length === 0) {
    return <div className="decision-empty">当前没有可执行的行动</div>
  }

  return (
    <div className="decision-flow">
      <div className="decision-heading">
        <div>
          <span className="decision-kicker">你的回合</span>
          <h2>{{ action: '选择行动', target: '选择目标', payment: '选择支付方式', confirm: '确认行动' }[step]}</h2>
        </div>
        {(step !== 'action' || source) && (
          <button className="decision-back" onClick={() => {
            if (step === 'action') onClearSource?.()
            else goBack()
          }}>返回</button>
        )}
      </div>

      <div className="decision-steps" aria-label="行动步骤">
        {(['action', 'target', 'payment', 'confirm'] as Step[]).map((item, index) => (
          <span key={item} className={item === step ? 'active' : ''}>{index + 1}</span>
        ))}
      </div>

      {source && step === 'action' && (
        <div className="source-chip">
          {source.kind === 'Card'
            ? source.mode === 'tune' ? `第 ${source.slot + 1} 张手牌 · 元素调和` : `已选择第 ${source.slot + 1} 张手牌`
            : `已选择第 ${source.slot + 1} 名角色`}
        </div>
      )}

      {step === 'action' && (
        <div className="decision-options">
          {actionGroups.size === 0 && (
            <div className="decision-empty">请在棋盘上选择要出战的角色</div>
          )}
          {[...actionGroups.entries()].map(([key, group]) => {
            const action = group[0]
            return (
              <button
                key={key}
                disabled={disabled}
                className={`decision-option ${action.kind_name === 'EndTurn' ? 'end-turn' : ''}`}
                onClick={() => chooseAction(group)}
              >
                <span>{KIND_NAMES[action.kind_name] ?? action.kind_name}</span>
                <b>{action.name}</b>
                {action.kind_name === 'Card' && <small>手牌 {action.slot + 1}</small>}
                {action.kind_name === 'Tune' && <small>选择一个元素骰进行调和</small>}
              </button>
            )
          })}
        </div>
      )}

      {step === 'target' && (
        <div className="decision-options">
          {[...targetGroups.entries()].map(([key, group]) => {
            const targetPlayer = group[0].identity?.[3] ?? -1
            const targetChar = group[0].identity?.[4] ?? -1
            const target = view.players[targetPlayer]?.chars[targetChar]
            const side = targetPlayer === humanPlayer ? '我方' : '对方'
            return (
              <button key={key} disabled={disabled} className="decision-option target-option" onClick={() => toPayment(group)}>
                <span>{target ? side : '行动目标'}</span>
                <b>{target?.name ?? '无需指定目标'}</b>
                {target && <small>生命 {target.hp} / {target.hp_max}</small>}
              </button>
            )
          })}
        </div>
      )}

      {step === 'payment' && (
        <>
          <div className="dice-selection-pending">请在中央选择骰子</div>
          <DiceSelectionDialog
            kicker={choosingTuneDie ? '元素调和' : '行动支付'}
            title={choosingTuneDie ? '选择要转换的骰子' : '选择支付骰子'}
            guidance={choosingTuneDie ? '选择一枚非当前出战角色元素的骰子。' : `为本次行动选择 ${requiredDice} 枚骰子。`}
            status={`已选择 ${selectedDice.size} / ${requiredDice} 枚`}
            error={completeButInvalid ? '这组骰子无法用于本次行动，请调整选择。' : null}
            confirmLabel={choosingTuneDie ? '确认调和骰子' : '选定这组骰子'}
            confirmDisabled={disabled || paymentChoice === null}
            pool={pool}
            selected={selectedDice}
            onChange={setSelectedDice}
            maxSelected={requiredDice}
            selectableColors={tuneColors}
            disabled={disabled}
            onBack={goBack}
            portalTarget={dicePortalTarget}
            onConfirm={() => {
              if (!paymentChoice) return
              setChoice(paymentChoice)
              setStep('confirm')
            }}
          />
        </>
      )}

      {step === 'confirm' && selected && (
        <div className="decision-confirm">
          <div className="confirm-summary">
            <span>{KIND_NAMES[selected.kind_name] ?? selected.kind_name}</span>
            <strong>{selected.name}</strong>
            {(selected.identity?.[3] ?? -1) >= 0 && (selected.identity?.[4] ?? -1) >= 0 && (
              <span>目标：{selected.identity?.[3] === humanPlayer ? '我方' : '对方'} {view.players[selected.identity![3]]?.chars[selected.identity![4]]?.name}</span>
            )}
            <span>支付：{paymentLabel(selected)}</span>
          </div>
          <button className="confirm-action" disabled={disabled} onClick={() => onPick(selected.index)}>确认执行</button>
        </div>
      )}
    </div>
  )
}
