const diceNames = ["冰", "水", "火", "雷", "风", "岩", "草", "万能"];
const elementNames = { cryo: "冰元素", hydro: "水元素", pyro: "火元素", electro: "雷元素", anemo: "风元素", geo: "岩元素", dendro: "草元素", physical: "物理" };
const elementDice = { cryo: 0, hydro: 1, pyro: 2, electro: 3, anemo: 4, geo: 5, dendro: 6 };
const dieSides = [
  [1, 7, 6],
  [4, 0, 2],
  [6, 3, 1],
  [2, 5, 4],
  [7, 1, 3],
  [3, 6, 7],
  [5, 2, 0],
  [0, 4, 5],
];
const phaseNames = { redraw: "选择要替换的起始手牌", roll: "选择要重掷的元素骰", action: "行动阶段", finished: "对局结束" };
let gameId;
let state;
let selected = new Set();
let pending = null;

const board = document.querySelector("#board");
const status = document.querySelector("#status");
const round = document.querySelector("#round");
const notice = document.querySelector("#notice");
const decision = document.querySelector("#decision");
const dialog = document.querySelector("#dialog");

document.querySelector("#restart").addEventListener("click", start);

async function start() {
  selected = new Set();
  pending = null;
  await request("/api/games", { method: "POST", body: JSON.stringify({}) }, true);
}

async function request(path, options = {}, creating = false) {
  notice.classList.add("hidden");
  try {
    const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "操作失败");
    if (creating) {
      gameId = payload.game_id;
      state = payload.state;
    } else {
      state = payload;
    }
    selected = new Set();
    pending = null;
    render();
  } catch (error) {
    notice.textContent = error.message;
    notice.classList.remove("hidden");
  }
}

function render() {
  round.textContent = `第 ${state.round} 回合`;
  status.textContent = state.phase === "finished"
    ? `玩家 ${state.winner + 1} 获胜`
    : `玩家 ${state.turn + 1} · ${phaseNames[state.phase]}`;
  const players = state.phase === "finished"
    ? state.players
    : [state.players[1 - state.turn], state.players[state.turn]];
  board.replaceChildren(...players.map(playerView));
  renderPhaseControl();
  renderDecision();
  renderDialog();
}

function playerView(player) {
  const current = state.phase !== "finished" && state.turn === player.id;
  const section = node("section", `player${current ? " current" : ""}`);
  const character = player.characters[player.active];
  const hp = counter(character, "hp");
  const energy = counter(character, "energy");
  const characterBox = node("div", "character");
  characterBox.innerHTML = `
    <div><div class="element">${elementNames[character.element]}</div><div class="character-name">${character.name}</div></div>
    <div class="meters">
      ${meter("生命", hp)}
      ${meter("充能", energy, "energy")}
      ${player.combat.map(modifier => `<div class="modifier">${modifier.name} · ${modifier.counters.map(value => `${value.name} ${value.value}`).join(" / ")}</div>`).join("")}
    </div>`;

  const center = node("div");
  const heading = node("div", "player-head");
  heading.innerHTML = `<div class="player-name">玩家 ${player.id + 1}</div>${current ? '<div class="turn-mark">操作中</div>' : player.ended ? '<div class="turn-mark">已结束</div>' : ""}`;
  const actions = node("div", "actions");
  actions.append(nodeText("p", "section-title", "角色行动"));
  for (const action of character.actions) {
    const button = node("button", "action");
    button.innerHTML = `<strong>${action.name}</strong><span class="detail">${costText(action.cost)} · ${action.tempo === "fast" ? "快速行动" : "战斗行动"}</span>`;
    button.disabled = !current || state.phase !== "action" || !!state.decision || !hasCounters(character, action.cost);
    button.addEventListener("click", () => openPayment({ kind: "skill", action: action.id }, action.name, action.cost, player));
    actions.append(button);
  }
  center.append(heading, actions, handView(player, current));

  const resources = node("div", "resources");
  resources.append(nodeText("p", "section-title", "元素骰"));
  resources.append(diceSummary(player.dice));
  const piles = node("div", "piles");
  piles.innerHTML = `<span>牌库 ${player.deck_count}</span><span>弃牌 ${player.discard_count}</span>`;
  resources.append(piles);
  if (state.phase === "action") {
    const end = node("button", "end");
    end.textContent = "结束回合";
    end.disabled = !current || !!state.decision;
    end.addEventListener("click", () => act({ kind: "end" }));
    resources.append(end);
  }
  section.append(characterBox, center, resources);
  return section;
}

function handView(player, current) {
  const hand = node("div", "hand");
  hand.append(nodeText("p", "section-title", `手牌 · ${player.hand.length}`));
  if (!current && state.phase !== "finished") {
    const backs = node("div", "card-backs");
    for (let index = 0; index < player.hand.length; index++) backs.append(nodeText("span", "card-back", "✧"));
    hand.append(backs);
    return hand;
  }
  for (const card of player.hand) {
    const wrapper = node("div", `card${state.phase === "redraw" && selected.has(card.hand) ? " selected" : ""}`);
    const title = node("button", "card-main");
    title.innerHTML = `<strong>${card.name}</strong><span class="detail">${card.description}<br>${costText(card.cost)} · 快速行动</span>`;
    title.disabled = !current || !["redraw", "action"].includes(state.phase) || !!state.decision;
    title.addEventListener("click", () => {
      if (state.phase === "redraw") toggleSelected(card.hand);
      else openPayment({ kind: "card", hand: card.hand }, card.name, card.cost, player);
    });
    wrapper.append(title);
    if (current && state.phase === "action") {
      const tune = nodeText("button", "tune", "元素调和");
      tune.addEventListener("click", () => openTune(card.hand, player));
      wrapper.append(tune);
    }
    hand.append(wrapper);
  }
  return hand;
}

function renderPhaseControl() {
  document.querySelector("#phase-control")?.remove();
  if (!["redraw", "roll"].includes(state.phase)) return;
  const control = node("section", "phase-control");
  control.id = "phase-control";
  if (state.phase === "redraw") {
    control.append(nodeText("strong", "", `已选择 ${selected.size} 张手牌`));
    const confirm = nodeText("button", "confirm", selected.size ? "替换所选手牌" : "保留起始手牌");
    confirm.addEventListener("click", () => act({ kind: "redraw", selected: [...selected].sort((a, b) => a - b) }));
    control.append(confirm);
  } else {
    const player = state.players[state.turn];
    control.append(selectableDice(player.dice, true));
    const confirm = nodeText("button", "confirm", selected.size ? `重掷 ${selected.size} 枚` : "保留全部骰子");
    confirm.addEventListener("click", () => act({ kind: "reroll", payment: selectedCounts() }));
    control.append(confirm);
  }
  document.querySelector("main").insertBefore(control, decision);
}

function openPayment(command, title, cost, player) {
  pending = { type: "payment", command, title, cost, player };
  selected = new Set();
  renderDialog();
}

function openTune(hand, player) {
  pending = { type: "tune", hand, player, target: elementDice[player.characters[player.active].element] };
  selected = new Set();
  renderDialog();
}

function renderDialog() {
  if (!pending) {
    dialog.classList.add("hidden");
    dialog.replaceChildren();
    return;
  }
  const panel = node("div", "dialog-panel");
  panel.append(nodeText("h2", "", pending.type === "payment" ? pending.title : "元素调和"));
  panel.append(nodeText("p", "detail", pending.type === "payment" ? `请选择 ${costText(pending.cost)}` : `选择 1 枚要转化为${diceNames[pending.target]}元素的骰子`));
  panel.append(selectableDice(pending.player.dice, false, pending.type === "tune", pending.target));
  const footer = node("div", "dialog-actions");
  const cancel = nodeText("button", "ghost", "取消");
  cancel.addEventListener("click", closeDialog);
  const confirm = nodeText("button", "confirm", pending.type === "payment" ? "确认支付" : "确认调和");
  if (pending.type === "payment") {
    confirm.disabled = !validPayment(selectedCounts(), pending.cost);
    confirm.addEventListener("click", () => act({ ...pending.command, payment: selectedCounts() }));
  } else {
    const chosen = [...selected];
    confirm.disabled = chosen.length !== 1 || chosen[0].startsWith("7-") || chosen[0].startsWith(`${pending.target}-`);
    confirm.addEventListener("click", () => act({ kind: "tune", hand: pending.hand, die: Number([...selected][0].split("-")[0]) }));
  }
  footer.append(cancel, confirm);
  panel.append(footer);
  dialog.replaceChildren(panel);
  dialog.classList.remove("hidden");
}

function selectableDice(pool, reroll, tune = false, tuneTarget = -1) {
  const list = node("div", "dice-picker");
  pool.forEach((count, color) => {
    for (let ordinal = 0; ordinal < count; ordinal++) {
      const id = `${color}-${ordinal}`;
      const button = node("button", `die-token${selected.has(id) ? " selected" : ""}`);
      button.innerHTML = dieSvg(color);
      button.setAttribute("aria-label", `${diceNames[color]}元素骰${selected.has(id) ? "，已选择" : ""}`);
      if (tune && (color === tuneTarget || color === 7)) button.disabled = true;
      button.addEventListener("click", () => {
        if (tune) selected.clear();
        selected.has(id) ? selected.delete(id) : selected.add(id);
        reroll ? render() : renderDialog();
      });
      list.append(button);
    }
  });
  return list;
}

function closeDialog() {
  selected = new Set();
  pending = null;
  renderDialog();
}

function toggleSelected(index) {
  selected.has(index) ? selected.delete(index) : selected.add(index);
  render();
}

function selectedCounts() {
  const counts = Array(8).fill(0);
  selected.forEach(id => { counts[Number(String(id).split("-")[0])] += 1; });
  return counts;
}

function validPayment(payment, cost) {
  const total = payment.reduce((sum, value) => sum + value, 0);
  const required = cost.dice.reduce((sum, value) => sum + value, 0) + cost.any;
  if (total !== required) return false;
  const missing = cost.dice.slice(0, 7).reduce((sum, value, index) => sum + Math.max(0, value - payment[index]), 0);
  return payment[7] >= missing;
}

function diceSummary(values) {
  const dice = node("div", "dice");
  values.forEach((count, color) => {
    for (let ordinal = 0; ordinal < count; ordinal++) {
      const value = node("span", "die-token die-static");
      value.innerHTML = dieSvg(color);
      value.setAttribute("aria-label", `${diceNames[color]}元素骰`);
      dice.append(value);
    }
  });
  return dice;
}

function dieSvg(color) {
  const [left, right, bottom] = dieSides[color];
  return `<svg viewBox="0 0 100 115" aria-hidden="true">
    <polygon class="die-side die-side-left" data-color="${left}" points="50,14 16,73 3,17" />
    <polygon class="die-side die-side-right" data-color="${right}" points="50,14 97,17 84,73" />
    <polygon class="die-side die-side-bottom" data-color="${bottom}" points="16,73 84,73 50,110" />
    <polygon class="die-front" data-color="${color}" points="50,14 84,73 16,73" />
    <polyline class="die-outline" points="3,17 50,14 97,17 84,73 50,110 16,73 3,17" />
    <text x="50" y="57" text-anchor="middle">${diceNames[color]}</text>
  </svg>`;
}

function renderDecision() {
  if (!state.decision) {
    decision.classList.add("hidden");
    return;
  }
  decision.replaceChildren(nodeText("div", "", `玩家 ${state.decision.player + 1} 请选择`));
  state.decision.options.forEach((option, index) => {
    const button = nodeText("button", "", option.label);
    button.addEventListener("click", () => request(`/api/games/${gameId}/choices`, { method: "POST", body: JSON.stringify({ decision: state.decision.id, option: index }) }));
    decision.append(button);
  });
  decision.classList.remove("hidden");
}

function act(body) {
  return request(`/api/games/${gameId}/actions`, { method: "POST", body: JSON.stringify(body) });
}

function hasCounters(character, cost) {
  return cost.counters.every(required => counter(character, required.name).value >= required.require);
}

function counter(character, name) {
  return character.counters.find(value => value.name === name);
}

function costText(cost) {
  const parts = [];
  cost.dice.forEach((count, index) => { if (count) parts.push(`${diceNames[index]} ${count}`); });
  if (cost.any) parts.push(`任意 ${cost.any}`);
  cost.counters.forEach(value => parts.push(`${value.name === "energy" ? "充能" : value.name} ${value.require}`));
  return parts.length ? parts.join(" · ") : "无消耗";
}

function meter(label, value, className = "") {
  return `<div><div class="meter-line"><span>${label}</span><span>${value.value} / ${value.max}</span></div><div class="meter ${className}"><i style="width:${value.value / value.max * 100}%"></i></div></div>`;
}

function node(tag, className = "") {
  const value = document.createElement(tag);
  value.className = className;
  return value;
}

function nodeText(tag, className, text) {
  const value = node(tag, className);
  value.textContent = text;
  return value;
}

start();
