export const DICE_NAMES = ['火', '冰', '水', '雷', '岩', '风', '草', '万能']

export function dieColorFromId(id: string) {
  return Number(id.split('-')[1])
}

export function selectedDiceCounts(selected: ReadonlySet<string>) {
  const counts = Array(DICE_NAMES.length).fill(0) as number[]
  for (const id of selected) {
    const color = dieColorFromId(id)
    if (color >= 0 && color < counts.length) counts[color] += 1
  }
  return counts
}
