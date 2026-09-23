const table = document.querySelector("#evaluations");
const search = document.querySelector("#search");
const count = document.querySelector("#count");
const empty = document.querySelector("#empty");
const error = document.querySelector("#error");

let reports = [];

search.addEventListener("input", render);
load();

async function load() {
  try {
    const response = await fetch("/api/reports");
    if (!response.ok) throw new Error("评估结果载入失败");
    reports = await response.json();
    render();
  } catch (cause) {
    error.textContent = cause.message;
    error.classList.remove("hidden");
  }
}

function render() {
  const query = search.value.trim().toLowerCase();
  const filtered = reports.filter((item) => searchable(item).includes(query));
  table.replaceChildren(...filtered.map(reportRow));
  count.textContent = `${filtered.length} / ${reports.length} 次运行`;
  empty.classList.toggle("hidden", filtered.length !== 0);
}

function searchable(item) {
  return `${item.experiment} ${item.run} ${item.candidates.join(" ")} ${item.opponents.join(" ")}`.toLowerCase();
}

function reportRow(item) {
  const row = document.createElement("tr");
  appendCell(row, item.experiment, "experiment");
  appendCell(row, item.run, "run");
  appendCell(row, item.candidates.join(" · "));
  appendCell(row, item.opponents.join(" · "));
  appendCell(row, number(item.evaluations), "numeric");
  appendCell(row, number(item.games), "numeric");
  appendCell(row, `${item.m1_evaluations} / ${item.evaluations}`, "numeric");
  const action = document.createElement("td");
  const link = document.createElement("a");
  link.textContent = "查看报告";
  link.href = `/reports/view/${encodePath(item.id)}`;
  action.append(link);
  row.append(action);
  return row;
}

function appendCell(row, value, className = "") {
  const cell = document.createElement("td");
  cell.textContent = value;
  cell.className = className;
  row.append(cell);
}

function number(value) {
  return Number(value).toLocaleString("zh-CN");
}

function encodePath(path) {
  return path.split("/").map(encodeURIComponent).join("/");
}
