import * as echarts from "/vendor/echarts/echarts.esm.min.mjs";
import { mean, quantileSorted } from "/vendor/simple-statistics/simple-statistics.mjs";

const loading = document.querySelector("#loading");
const error = document.querySelector("#error");
const content = document.querySelector("#content");
const reportId = decodeURIComponent(location.pathname.slice("/reports/view/".length));
const pairOutcomes = new Map([
  ["0,0", "firstPlayer"],
  ["1,1", "secondPlayer"],
  ["0,1", "candidate"],
  ["1,0", "opponent"],
]);

load();

async function load() {
  try {
    const response = await fetch(`/api/reports/${encodePath(reportId)}`);
    if (!response.ok) throw new Error("评测结果载入失败");
    loading.classList.add("hidden");
    content.classList.remove("hidden");
    render(await response.json());
  } catch (cause) {
    loading.classList.add("hidden");
    content.classList.add("hidden");
    error.textContent = cause.message;
    error.classList.remove("hidden");
  }
}

function render(report) {
  document.querySelector("#run-heading").textContent = report.run;
  document.querySelector("#experiment-heading").textContent = report.experiment;
  renderSummary(report);
  const plots = report.results.filter(hasM1).map(distributionBlock);
  document.querySelector("#distributions").replaceChildren(...plots.map(({ block }) => block));
  document.querySelector("#m1-empty").classList.toggle("hidden", plots.length !== 0);
  for (const plot of plots) {
    renderChart(plot.chart, plot.distribution, plot.quartiles, plot.names);
  }
}

function renderSummary(report) {
  const candidate = report.candidates.length === 1 ? report.candidates[0] : "参评方";
  const evaluations = report.results.map((result) => ({
    result,
    counts: pairedCounts(result.results),
  }));
  const hidden = new Set(
    ["draws", "truncations"].filter((key) => report.results.every((result) => result[key] === 0)),
  );
  renderSummaryTable(candidate, evaluations, hidden);
}

function renderSummaryTable(candidate, evaluations, hidden) {
  const hasOther = evaluations.some(({ counts }) => counts.other);
  const numbers = evaluations.map(({ result }) => summaryNumbers(result));
  const widths = numbers[0].map((_, index) => Math.max(...numbers.map((row) => row[index].length)));
  const [main, paired, columns] = summaryHeading(candidate, hasOther, hidden);
  document.querySelector("#summary-columns").replaceChildren(...columns);
  document.querySelector("#summary-heading").replaceChildren(main, paired);
  document
    .querySelector("#summary")
    .replaceChildren(
      ...evaluations.map(({ result, counts }, index) =>
        summaryRow(result, counts, hasOther, hidden, numbers[index], widths),
      ),
    );
}

function summaryNumbers(result) {
  return [
    number(result.games),
    number(result.wins),
    number(result.losses),
    result.average_m1 == null ? "-" : result.average_m1.toFixed(2),
  ];
}

function summaryHeading(candidate, hasOther, hidden) {
  const main = document.createElement("tr");
  const paired = document.createElement("tr");
  const labels = [
    ["评估对手", "", "row-column"],
    ["对局", "", "summary-column"],
    [`${candidate} 胜`, "", "summary-column"],
    [`${candidate} 负`, "", "summary-column"],
  ];
  if (!hidden.has("draws")) labels.push(["平局", "", "summary-column"]);
  if (!hidden.has("truncations")) labels.push(["截断", "", "summary-column"]);
  labels.push(
    ["M1", "summary-divider", "summary-column"],
    [`${candidate} 胜率`, "rate-heading", "summary-column"],
    ["先手胜率", "rate-heading", "summary-column"],
    ["后手胜率", "rate-heading", "summary-column"],
  );
  const columns = [];
  for (const [label, className, columnClass] of labels) {
    const cell = node("th", className, label);
    cell.rowSpan = 2;
    cell.scope = "col";
    main.append(cell);
    columns.push(node("col", columnClass, ""));
  }
  const pairGroup = node("th", "pair-group", "换边结果");
  pairGroup.colSpan = hasOther ? 5 : 4;
  pairGroup.scope = "colgroup";
  main.append(pairGroup);
  for (const label of [`${candidate} 必胜`, `${candidate} 必败`, "先手必胜", "后手必胜"]) {
    const cell = node("th", "rate-heading", label);
    cell.scope = "col";
    paired.append(cell);
    columns.push(node("col", "pair-column", ""));
  }
  if (hasOther) {
    const cell = node("th", "rate-heading", "未归类");
    cell.scope = "col";
    paired.append(cell);
    columns.push(node("col", "pair-column", ""));
  }
  return [main, paired, columns];
}

function summaryRow(result, counts, hasOther, hidden, numbers, widths) {
  const row = document.createElement("tr");
  const opponent = document.createElement("th");
  const name = document.createElement("strong");
  const record = document.createElement("small");
  opponent.className = "summary-opponent";
  opponent.scope = "row";
  name.textContent = result.opponent_name;
  record.textContent = result.record;
  opponent.append(name, record);
  row.append(opponent);
  appendCell(row, alignedNumber(numbers[0], widths[0]), "muted", "align-number");
  appendCell(row, alignedNumber(numbers[1], widths[1]), "emphasized", "align-number");
  appendCell(row, alignedNumber(numbers[2], widths[2]), "emphasized", "align-number");
  if (!hidden.has("draws")) {
    appendCell(row, number(result.draws), result.draws ? "alert" : "muted");
  }
  if (!hidden.has("truncations")) {
    appendCell(row, number(result.truncations), result.truncations ? "alert" : "muted");
  }
  appendCell(row, alignedNumber(numbers[3], widths[3]), "muted", "summary-divider align-number");
  appendRate(row, result.wins, result.games, "report-rate-primary");
  const first = seatCounts(result, 0);
  const second = seatCounts(result, 1);
  appendRate(row, first.wins, first.games);
  appendRate(row, second.wins, second.games);
  for (const value of [
    counts.candidate,
    counts.opponent,
    counts.firstPlayer,
    counts.secondPlayer,
  ]) {
    appendRate(row, value, counts.total, "pair-result");
  }
  if (hasOther) appendRate(row, counts.other, counts.total, "pair-result");
  return row;
}

function alignedNumber(value, width) {
  return value.padStart(width, "\u2007");
}

function appendCell(row, value, tone, className = "") {
  const cell = document.createElement("td");
  cell.className = `report-${tone} ${className}`.trim();
  if (tone === "emphasized") {
    const strong = document.createElement("strong");
    strong.textContent = value;
    cell.append(strong);
  } else {
    cell.textContent = value;
  }
  row.append(cell);
}

function seatCounts(result, seat) {
  const games = result.results.filter((game) => game.candidate_seat === seat);
  const wins = games.filter((game) => game.candidate_won).length;
  return { wins, games: games.length };
}

function evaluationHeading(result, detail) {
  const header = document.createElement("div");
  header.className = "evaluation-heading";
  const title = document.createElement("h3");
  const meta = document.createElement("span");
  title.textContent = `${result.candidate_name} vs ${result.opponent_name}`;
  meta.textContent = `${result.record} · ${detail}`;
  header.append(title, meta);
  return header;
}

function appendRate(row, value, total, className = "") {
  const cell = document.createElement("td");
  const rate = document.createElement("strong");
  const count = document.createElement("small");
  cell.className = `report-rate ${className}`.trim();
  rate.textContent = percent(value / total);
  count.textContent = `${value}/${total}`;
  cell.append(rate, count);
  row.append(cell);
}

function pairedCounts(games) {
  const pairs = new Map();
  for (const game of games) {
    if (!pairs.has(game.seed)) pairs.set(game.seed, new Map());
    if (pairs.get(game.seed).has(game.candidate_seat)) throw new Error("同一种子包含重复座位");
    pairs.get(game.seed).set(game.candidate_seat, game);
  }
  const counts = { firstPlayer: 0, secondPlayer: 0, candidate: 0, opponent: 0, other: 0 };
  for (const pair of pairs.values()) counts[classifyPair(pair)] += 1;
  counts.total = pairs.size;
  return counts;
}

function classifyPair(pair) {
  const first = pair.get(0);
  const second = pair.get(1);
  if (!first || !second || first.draw || second.draw || first.truncated || second.truncated) {
    return "other";
  }
  const outcome = pairOutcomes.get(`${first.winner},${second.winner}`);
  if (!outcome) throw new Error("换边结果包含无效胜者");
  return outcome;
}

function hasM1(result) {
  return result.results.every((game) => Number.isFinite(game.m1));
}

function distributionBlock(result) {
  const distribution = m1Distribution(result.results);
  const statistics = m1Statistics(result.results);
  const block = document.createElement("article");
  block.className = "distribution-block";
  block.append(evaluationHeading(result, `${number(result.games)} 局`));
  const chartWrap = document.createElement("div");
  chartWrap.className = "chart-wrap";
  const chart = document.createElement("div");
  chart.className = "chart";
  chart.setAttribute("role", "img");
  chart.setAttribute(
    "aria-label",
    `${result.candidate_name} 对阵 ${result.opponent_name} 的 M1 分布`,
  );
  chartWrap.append(chart, statisticsLine(statistics));
  block.append(chartWrap);
  return {
    block,
    chart,
    distribution,
    quartiles: statistics.quartiles,
    names: [result.candidate_name, result.opponent_name],
  };
}

function statisticsLine(statistics) {
  const line = document.createElement("div");
  line.className = "distribution-stats";
  const values = [
    ["均值", statistics.mean.toFixed(2)],
    ["Q1", formatStatistic(statistics.quartiles[0])],
    ["Q2", formatStatistic(statistics.quartiles[1])],
    ["Q3", formatStatistic(statistics.quartiles[2])],
  ];
  for (const [label, value] of values) {
    const item = document.createElement("span");
    const name = document.createElement("small");
    const metric = document.createElement("strong");
    name.textContent = label;
    metric.textContent = value;
    item.append(name, metric);
    line.append(item);
  }
  return line;
}

function node(tag, className, text) {
  const element = document.createElement(tag);
  element.className = className;
  element.textContent = text;
  return element;
}

function m1Distribution(games) {
  const rows = new Map();
  for (const game of games) {
    const row = rows.get(game.m1) || { m1: game.m1, candidate: 0, opponent: 0, other: 0 };
    if (game.candidate_won) row.candidate += 1;
    else if (game.draw || game.truncated) row.other += 1;
    else row.opponent += 1;
    rows.set(game.m1, row);
  }
  const minimum = Math.min(...rows.keys());
  const maximum = Math.max(...rows.keys());
  return Array.from({ length: maximum - minimum + 1 }, (_, index) => {
    const m1 = minimum + index;
    return rows.get(m1) || { m1, candidate: 0, opponent: 0, other: 0 };
  });
}

function m1Statistics(games) {
  const values = games.map((game) => game.m1).sort((left, right) => left - right);
  return {
    mean: mean(values),
    quartiles: [0.25, 0.5, 0.75].map((probability) => quantileSorted(values, probability)),
  };
}

function renderChart(element, distribution, quartiles, names) {
  const chart = echarts.init(element);
  chart.setOption(chartOptions(distribution, quartiles, names));
  window.addEventListener("resize", () => chart.resize());
}

function chartOptions(distribution, quartiles, names) {
  const source = [
    ["M1", `${names[0]} 胜局`, `${names[1]} 胜局`, "其他"],
    ...distribution.map((row) => [row.m1, row.candidate, row.opponent, row.other]),
  ];
  const series = [
    lineSeries(`${names[0]} 胜局`, "#43d6c5"),
    lineSeries(`${names[1]} 胜局`, "#ef8158"),
  ];
  if (distribution.some((row) => row.other)) series.push(lineSeries("其他", "#91a5af"));
  series[0].markLine = {
    silent: true,
    symbol: "none",
    lineStyle: { color: "#a98be8", type: "dashed" },
    label: { color: "#d8c9ff", formatter: ({ name }) => name },
    data: quartiles.map((value, index) => ({ name: `Q${index + 1}`, xAxis: value })),
  };
  return {
    animationDuration: 350,
    color: ["#43d6c5", "#ef8158", "#91a5af"],
    dataset: { source },
    legend: { top: 0, textStyle: { color: "#c9d6dc" } },
    tooltip: { trigger: "axis" },
    grid: { left: 54, right: 28, top: 54, bottom: 82 },
    xAxis: { type: "value", minInterval: 1, name: "M1", axisLabel: { color: "#91a5af" } },
    yAxis: { type: "value", minInterval: 1, name: "局数", axisLabel: { color: "#91a5af" } },
    series,
  };
}

function lineSeries(name, color) {
  return {
    name,
    type: "line",
    encode: { x: "M1", y: name },
    symbolSize: 7,
    lineStyle: { color, width: 3 },
    itemStyle: { color },
  };
}

function number(value) {
  return Number(value).toLocaleString("zh-CN");
}

function percent(value) {
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function formatStatistic(value) {
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

function encodePath(path) {
  return path.split("/").map(encodeURIComponent).join("/");
}
