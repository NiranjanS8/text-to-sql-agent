const askForm = document.querySelector("#askForm");
const questionInput = document.querySelector("#questionInput");
const askButton = document.querySelector("#askButton");
const sampleButton = document.querySelector("#sampleButton");
const errorLine = document.querySelector("#errorLine");
const finalAnswer = document.querySelector("#finalAnswer");
const sqlOutput = document.querySelector("#sqlOutput");
const explanationOutput = document.querySelector("#explanationOutput");
const rowCount = document.querySelector("#rowCount");
const tableWrap = document.querySelector("#tableWrap");
const schemaList = document.querySelector("#schemaList");
const historyList = document.querySelector("#historyList");
const healthStatus = document.querySelector("#healthStatus");
const refreshSchemaButton = document.querySelector("#refreshSchemaButton");
const refreshHistoryButton = document.querySelector("#refreshHistoryButton");

const sampleQuestion = "Show all students enrolled in Java course";

askForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = questionInput.value.trim();
  if (!question) return;

  setLoading(true);
  errorLine.textContent = "";

  try {
    const response = await fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });

    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "The agent could not process that question.");
    }

    renderAnswer(payload);
    await loadHistory();
  } catch (error) {
    errorLine.textContent = error.message;
  } finally {
    setLoading(false);
  }
});

sampleButton.addEventListener("click", () => {
  questionInput.value = sampleQuestion;
  questionInput.focus();
});

refreshSchemaButton.addEventListener("click", loadSchema);
refreshHistoryButton.addEventListener("click", loadHistory);

async function loadHealth() {
  try {
    const response = await fetch("/health");
    const payload = await response.json();
    healthStatus.textContent = payload.status === "ok" ? "API online" : "API issue";
    healthStatus.classList.toggle("is-ok", payload.status === "ok");
  } catch {
    healthStatus.textContent = "API offline";
    healthStatus.classList.remove("is-ok");
  }
}

async function loadSchema() {
  schemaList.innerHTML = `<p class="empty-state">Loading schema...</p>`;
  try {
    const response = await fetch("/schema");
    const payload = await response.json();
    schemaList.innerHTML = "";
    Object.entries(payload.tables).forEach(([tableName, columns]) => {
      const item = document.createElement("article");
      item.className = "schema-item";
      item.innerHTML = `
        <strong>${escapeHtml(tableName)}</strong>
        <span>${columns.map((column) => `${escapeHtml(column.name)} ${escapeHtml(column.type)}`).join(", ")}</span>
      `;
      schemaList.appendChild(item);
    });
  } catch {
    schemaList.innerHTML = `<p class="empty-state">Schema unavailable.</p>`;
  }
}

async function loadHistory() {
  historyList.innerHTML = `<li><span>Loading history...</span></li>`;
  try {
    const response = await fetch("/history?limit=6");
    const payload = await response.json();
    historyList.innerHTML = "";
    if (!payload.history.length) {
      historyList.innerHTML = `<li><span>No saved queries yet.</span></li>`;
      return;
    }

    payload.history.forEach((record) => {
      const item = document.createElement("li");
      item.innerHTML = `
        <strong>${escapeHtml(record.question)}</strong>
        <span>${escapeHtml(record.execution_status)} · ${escapeHtml(record.generated_sql)}</span>
      `;
      historyList.appendChild(item);
    });
  } catch {
    historyList.innerHTML = `<li><span>History unavailable.</span></li>`;
  }
}

function renderAnswer(payload) {
  finalAnswer.textContent = payload.final_answer || "No answer returned.";
  sqlOutput.textContent = payload.sql || payload.original_sql || "No SQL returned.";
  explanationOutput.textContent = payload.explanation || "No explanation returned.";
  rowCount.textContent = `${payload.row_count || 0} ${payload.row_count === 1 ? "row" : "rows"}`;

  if (payload.error) {
    errorLine.textContent = payload.error;
  }

  renderTable(payload.data || []);
}

function renderTable(rows) {
  if (!rows.length) {
    tableWrap.innerHTML = `<p class="empty-state">No rows returned.</p>`;
    return;
  }

  const columns = Object.keys(rows[0]);
  const header = columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("");
  const body = rows
    .map((row) => {
      const cells = columns.map((column) => `<td>${escapeHtml(String(row[column] ?? ""))}</td>`).join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");

  tableWrap.innerHTML = `<table><thead><tr>${header}</tr></thead><tbody>${body}</tbody></table>`;
}

function setLoading(isLoading) {
  askButton.disabled = isLoading;
  askButton.textContent = isLoading ? "Running..." : "Run query";
}

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (character) => {
    const entities = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    };
    return entities[character];
  });
}

loadHealth();
loadSchema();
loadHistory();
