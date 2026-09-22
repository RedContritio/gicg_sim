const diceNames = ["冰", "水", "火", "雷", "风", "岩", "草", "万能"];
const diceIds = ["cryo", "hydro", "pyro", "electro", "anemo", "geo", "dendro", "omni"];
const elementNames = {
  cryo: "冰元素",
  hydro: "水元素",
  pyro: "火元素",
  electro: "雷元素",
  anemo: "风元素",
  geo: "岩元素",
  dendro: "草元素",
  physical: "物理",
  piercing: "穿透",
};
const reactionNames = {
  vaporize: "蒸发",
  melt: "融化",
  overloaded: "超载",
  superconduct: "超导",
  electro_charged: "感电",
  frozen: "冻结",
  swirl: "扩散",
  crystallize: "结晶",
  burning: "燃烧",
  bloom: "绽放",
  quicken: "原激化",
  shatter: "碎冰",
};
const elementDice = { cryo: 0, hydro: 1, pyro: 2, electro: 3, anemo: 4, geo: 5, dendro: 6 };
const counterNames = {
  hp: "生命",
  energy: "充能",
  nightsoul: "夜魂值",
  fighting_spirit: "战意",
  bite_stacks: "浪势充能",
  uses: "可用次数",
  rounds: "持续回合",
  power: "强化",
};
const switchCost = { dice: Array(8).fill(0), any: 1, counters: [] };
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
const phaseNames = {
  select_active: "选择初始出战角色",
  redraw: "选择要替换的起始手牌",
  roll: "选择要重掷的元素骰",
  action: "行动阶段",
  finished: "对局结束",
};
let gameId;
let state;
let rules;
let definitions;
let setup;
let teams;
let selected = new Set();
let pending = null;

const lobby = document.querySelector("#lobby");
const game = document.querySelector("#game");
const board = document.querySelector("#board");
const status = document.querySelector("#status");
const round = document.querySelector("#round");
const notice = document.querySelector("#notice");
const decision = document.querySelector("#decision");
const dialog = document.querySelector("#dialog");

document.querySelector("#start").addEventListener("click", start);
document.querySelector("#restart").addEventListener("click", start);

async function start() {
  selected = new Set();
  pending = null;
  await request(
    "/api/games",
    {
      method: "POST",
      body: JSON.stringify({ player_one: teams[0], player_two: teams[1] }),
    },
    true,
  );
}

async function loadSetup() {
  notice.classList.add("hidden");
  try {
    const response = await fetch("/api/setup");
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "阵容载入失败");
    setup = payload;
    teams = payload.players.map((characters) => [...characters]);
    renderLobby();
  } catch (error) {
    notice.textContent = error.message;
    notice.classList.remove("hidden");
  }
}

function renderLobby() {
  const selectors = document.querySelector("#team-selectors");
  selectors.replaceChildren(...teams.map(teamSelector));
  const ready = teams.every((team) => team.length === setup.team_size);
  const startButton = document.querySelector("#start");
  startButton.disabled = !ready;
  startButton.textContent = ready ? "开始对局" : `每队选择 ${setup.team_size} 名角色`;
}

function teamSelector(team, player) {
  const section = node("section", "team-selector");
  section.append(
    nodeText("h3", "", `玩家 ${player + 1}`),
    nodeText("p", "team-count", `${team.length} / ${setup.team_size}`),
  );
  const characters = node("div", "character-options");
  for (const character of setup.characters) {
    const active = team.includes(character.id);
    const button = node("button", `character-option${active ? " selected" : ""}`);
    button.innerHTML = `<span>${elementNames[character.element]}</span><strong>${character.name}</strong>`;
    button.addEventListener("click", () => toggleCharacter(player, character.id));
    characters.append(button);
  }
  section.append(characters);
  return section;
}

function toggleCharacter(player, character) {
  const team = teams[player];
  const index = team.indexOf(character);
  if (index >= 0) team.splice(index, 1);
  else if (team.length < setup.team_size) team.push(character);
  renderLobby();
}

async function request(path, options = {}, creating = false) {
  notice.classList.add("hidden");
  try {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "操作失败");
    if (creating) {
      gameId = payload.game_id;
      rules = payload.rules;
      definitions = new Map(
        [...rules.characters, ...rules.modifiers, ...rules.cards].map((value) => [value.id, value]),
      );
      state = hydrate(payload.state);
      lobby.classList.add("hidden");
      game.classList.remove("hidden");
      round.classList.remove("hidden");
      document.querySelector("#restart").classList.remove("hidden");
    } else {
      state = hydrate(payload);
    }
    selected = new Set();
    pending = null;
    render();
  } catch (error) {
    notice.textContent = error.message;
    notice.classList.remove("hidden");
  }
}

function hydrate(raw) {
  return {
    ...raw,
    ruleset: rules.hash,
    players: raw.players.map((player, id) => {
      const previews = raw.action_previews[id];
      return {
        ...player,
        id,
        deck_count: player.deck.length,
        discard_count: player.discard.length,
        hand: player.hand.map((definition, hand) =>
          cardView(definition, hand, previews.cards[hand]),
        ),
        characters: player.characters.map((character, slot) =>
          characterView(character, slot, slot === player.active ? previews.skills : []),
        ),
        switch: {
          tempo: previews.switch.tempo,
          cost: effectiveCost(switchCost, undefined, previews.switch),
        },
        combat: modifierViews(player.combat),
        summons: modifierViews(player.summons),
        supports: modifierViews(player.supports),
      };
    }),
  };
}

function cardView(definition, hand, preview) {
  const card = definitions.get(definition);
  return {
    hand,
    id: card.id,
    name: card.name,
    description: card.description,
    tempo: preview.tempo,
    cost: effectiveCost(card.action.cost, undefined, preview),
  };
}

function characterView(character, slot, previews) {
  const definition = definitions.get(character.definition);
  return {
    slot,
    id: definition.id,
    name: definition.name,
    element: definition.element,
    counters: counterViews(definition.counters, character.counters),
    auras: character.auras,
    actions: definition.actions.map((action) => {
      const preview = previews.find((value) => value.id === action.id);
      return {
        id: action.id,
        name: action.name,
        tempo: preview?.tempo ?? action.tempo,
        cost: effectiveCost(action.cost, definition.counters, preview),
      };
    }),
    modifiers: modifierViews(character.modifiers),
  };
}

function modifierViews(modifiers) {
  return modifiers.map((modifier) => {
    const definition = definitions.get(modifier.definition);
    return {
      instance: modifier.instance,
      id: definition.id,
      name: definition.name,
      zone: definition.zone,
      counters: counterViews(definition.counters, modifier.counters),
    };
  });
}

function counterViews(schema, values) {
  return schema.fields.map((definition, index) => ({ ...definition, value: values[index] }));
}

function costView(cost, schema) {
  return {
    ...cost,
    counters: cost.counters.map((value) => ({
      name: schema.fields[value.field].name,
      require: value.require,
    })),
  };
}

function effectiveCost(cost, schema, preview) {
  const value = costView(cost, schema);
  if (!preview) return value;
  return { ...value, dice: preview.dice, any: preview.any };
}

function render() {
  round.textContent = `第 ${state.round} 回合`;
  const phase =
    state.phase === "finished"
      ? `玩家 ${state.winner + 1} 获胜${state.finish_reason === "concede" ? " · 对手认输" : ""}`
      : `玩家 ${state.turn + 1} · ${phaseNames[state.phase]}`;
  const reaction = state.last_reaction ? ` · ${reactionNames[state.last_reaction.kind]}` : "";
  status.textContent = phase + reaction;
  const controller = state.decision?.player ?? state.turn;
  const players =
    state.phase === "finished"
      ? state.players
      : [state.players[1 - controller], state.players[controller]];
  board.replaceChildren(...players.map(playerView));
  renderPhaseControl();
  renderDecision();
  renderDialog();
}

function playerView(player) {
  const current =
    state.phase !== "finished" && (state.decision?.player ?? state.turn) === player.id;
  const section = node("section", `player${current ? " current" : ""}`);
  const character = player.characters[player.active];
  const characterBox = teamView(player, current);

  const center = node("div");
  const heading = node("div", "player-head");
  heading.innerHTML = `<div class="player-name">玩家 ${player.id + 1}</div>${current ? '<div class="turn-mark">操作中</div>' : player.ended ? '<div class="turn-mark">已结束</div>' : ""}`;
  const actions = node("div", "actions");
  actions.append(nodeText("p", "section-title", `${character.name} · 角色行动`));
  for (const action of character.actions) {
    const button = node("button", "action");
    button.innerHTML = `<strong>${action.name}</strong><span class="detail">${costText(action.cost)} · ${action.tempo === "fast" ? "快速行动" : "战斗行动"}</span>`;
    button.disabled =
      !current ||
      state.phase !== "action" ||
      !!state.decision ||
      !hasCounters(character, action.cost);
    button.addEventListener("click", () =>
      openPayment({ kind: "skill", action: action.id }, action.name, action.cost, player),
    );
    actions.append(button);
  }
  center.append(heading, actions, handView(player, current));

  const resources = node("div", "resources");
  resources.append(nodeText("p", "section-title", "元素骰"));
  resources.append(diceSummary(player.dice));
  const piles = node("div", "piles");
  piles.innerHTML = `<span>牌库 ${player.deck_count}</span><span>弃牌 ${player.discard_count}</span>`;
  resources.append(piles);
  resources.append(
    modifierZone("出战状态", player.combat),
    modifierZone("召唤物", player.summons),
    modifierZone("支援", player.supports),
  );
  appendPlayerControls(resources, current);
  section.append(characterBox, center, resources);
  return section;
}

function appendPlayerControls(resources, current) {
  if (state.phase === "action") {
    const end = node("button", "end");
    end.textContent = "结束回合";
    end.disabled = !current || !!state.decision;
    end.addEventListener("click", () => act({ kind: "end" }));
    resources.append(end);
  }
  if (current && state.phase !== "finished") {
    const concede = nodeText("button", "concede", "认输");
    concede.addEventListener("click", () => {
      if (window.confirm("确认认输？")) act({ kind: "concede" });
    });
    resources.append(concede);
  }
}

function teamView(player, current) {
  const team = node("div", "team");
  player.characters.forEach((character) => {
    const hp = counter(character, "hp");
    const active = character.slot === player.active;
    const button = node(
      "button",
      `team-character${active ? " active" : ""}${hp.value === 0 ? " defeated" : ""}`,
    );
    button.innerHTML = `
      <span class="element">${elementNames[character.element]}</span>
      <strong>${character.name}</strong>
      <span class="counter-list">${character.counters.map(counterText).join("")}</span>
      ${character.auras.length ? `<span class="aura">附着 · ${character.auras.map((aura) => elementNames[aura]).join(" / ")}</span>` : ""}
      ${character.modifiers.map(modifierText).join("")}`;
    const canSwitch =
      current && state.phase === "action" && !state.decision && !active && hp.value > 0;
    button.disabled = !canSwitch;
    if (canSwitch) {
      button.addEventListener("click", () =>
        openPayment(
          { kind: "switch", slot: character.slot },
          `切换至${character.name}`,
          player.switch.cost,
          player,
        ),
      );
    }
    team.append(button);
  });
  return team;
}

function counterText(value) {
  const label = counterNames[value.name] || value.name;
  return `<span>${label} ${value.value}/${value.max}</span>`;
}

function modifierText(modifier) {
  const counters = modifier.counters.map(
    (value) => `${counterNames[value.name] || value.name} ${value.value}`,
  );
  return `<span class="modifier">${modifier.name}${counters.length ? ` · ${counters.join(" / ")}` : ""}</span>`;
}

function modifierZone(label, modifiers) {
  const section = node("div", `modifier-zone${modifiers.length ? "" : " empty"}`);
  section.append(nodeText("p", "section-title", label));
  for (const modifier of modifiers) {
    const item = node("div");
    item.innerHTML = modifierText(modifier);
    section.append(item);
  }
  if (!modifiers.length) section.append(nodeText("span", "detail", "无"));
  return section;
}

function handView(player, current) {
  const hand = node("div", "hand");
  hand.append(nodeText("p", "section-title", `手牌 · ${player.hand.length}`));
  if (!current && state.phase !== "finished") {
    const backs = node("div", "card-backs");
    for (let index = 0; index < player.hand.length; index++)
      backs.append(nodeText("span", "card-back", "✧"));
    hand.append(backs);
    return hand;
  }
  for (const card of player.hand) {
    const wrapper = node(
      "div",
      `card${state.phase === "redraw" && selected.has(card.hand) ? " selected" : ""}`,
    );
    const title = node("button", "card-main");
    const tempo = card.tempo === "fast" ? "快速行动" : "战斗行动";
    title.innerHTML = `<strong>${card.name}</strong><span class="detail">${card.description}<br>${costText(card.cost)} · ${tempo}</span>`;
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
    confirm.addEventListener("click", () =>
      act({ kind: "redraw", selected: [...selected].sort((a, b) => a - b) }),
    );
    control.append(confirm);
  } else {
    const player = state.players[state.turn];
    control.append(selectableDice(player.dice, true));
    const confirm = nodeText(
      "button",
      "confirm",
      selected.size ? `重掷 ${selected.size} 枚` : "保留全部骰子",
    );
    confirm.addEventListener("click", () => act({ kind: "reroll", payment: selectedCounts() }));
    control.append(confirm);
  }
  game.insertBefore(control, decision);
}

function openPayment(command, title, cost, player) {
  pending = { type: "payment", command, title, cost, player };
  selected = new Set();
  renderDialog();
}

function openTune(hand, player) {
  pending = {
    type: "tune",
    hand,
    player,
    target: elementDice[player.characters[player.active].element],
  };
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
  panel.append(
    nodeText(
      "p",
      "detail",
      pending.type === "payment"
        ? `请选择 ${costText(pending.cost)}`
        : `选择 1 枚要转化为${diceNames[pending.target]}元素的骰子`,
    ),
  );
  panel.append(selectableDice(pending.player.dice, false, pending.type === "tune", pending.target));
  const footer = node("div", "dialog-actions");
  const cancel = nodeText("button", "ghost", "取消");
  cancel.addEventListener("click", closeDialog);
  const confirm = nodeText(
    "button",
    "confirm",
    pending.type === "payment" ? "确认支付" : "确认调和",
  );
  if (pending.type === "payment") {
    confirm.disabled = !validPayment(selectedCounts(), pending.cost);
    confirm.addEventListener("click", () => act({ ...pending.command, payment: selectedCounts() }));
  } else {
    const chosen = [...selected];
    confirm.disabled =
      chosen.length !== 1 ||
      chosen[0].startsWith("7-") ||
      chosen[0].startsWith(`${pending.target}-`);
    confirm.addEventListener("click", () =>
      act({
        kind: "tune",
        hand: pending.hand,
        die: diceIds[Number([...selected][0].split("-")[0])],
      }),
    );
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
      button.setAttribute(
        "aria-label",
        `${diceNames[color]}元素骰${selected.has(id) ? "，已选择" : ""}`,
      );
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
  selected.forEach((id) => {
    counts[Number(String(id).split("-")[0])] += 1;
  });
  return counts;
}

function validPayment(payment, cost) {
  const total = payment.reduce((sum, value) => sum + value, 0);
  const required = cost.dice.reduce((sum, value) => sum + value, 0) + cost.any;
  if (total !== required) return false;
  const missing = cost.dice
    .slice(0, 7)
    .reduce((sum, value, index) => sum + Math.max(0, value - payment[index]), 0);
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
    const button = nodeText("button", "", choiceLabel(option));
    button.addEventListener("click", () =>
      request(`/api/games/${gameId}/choices`, {
        method: "POST",
        body: JSON.stringify({ decision: state.decision.id, option: index }),
      }),
    );
    decision.append(button);
  });
  decision.classList.remove("hidden");
}

function choiceLabel(option) {
  if (!option.label.startsWith("character:")) return option.label;
  const character = state.players[state.decision.player].characters[Number(option.id)];
  return `切换至${character.name}`;
}

function act(body) {
  return request(`/api/games/${gameId}/actions`, { method: "POST", body: JSON.stringify(body) });
}

function hasCounters(character, cost) {
  return cost.counters.every(
    (required) => counter(character, required.name).value >= required.require,
  );
}

function counter(character, name) {
  return character.counters.find((value) => value.name === name);
}

function costText(cost) {
  const parts = [];
  cost.dice.forEach((count, index) => {
    if (count) parts.push(`${diceNames[index]} ${count}`);
  });
  if (cost.any) parts.push(`任意 ${cost.any}`);
  cost.counters.forEach((value) => {
    parts.push(`${counterNames[value.name] || value.name} ${value.require}`);
  });
  return parts.length ? parts.join(" · ") : "无消耗";
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

loadSetup();
