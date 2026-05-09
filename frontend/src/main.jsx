import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Braces,
  ChevronLeft,
  ChevronRight,
  Clipboard,
  Database,
  FileDown,
  History,
  Loader2,
  Play,
  RefreshCw,
  Search,
  Sparkles,
  TableProperties,
  Terminal,
} from "lucide-react";
import "./styles.css";

const sampleQuestions = [
  "Show all students enrolled in Java course",
  "Which course categories have earned the most money?",
  "Show students with partial payments and pending amount",
  "Which students are enrolled in more than one course?",
];

const defaultSavedQueries = [
  "Which SaaS customers have overdue invoice balance?",
  "Which organizations have the highest AI SQL Copilot adoption?",
  "Show students with partial payments and pending amount",
];

const schemaRelationships = [
  ["students", "enrollments", "id -> student_id"],
  ["courses", "enrollments", "id -> course_id"],
  ["enrollments", "payments", "id -> enrollment_id"],
  ["organizations", "app_users", "id -> organization_id"],
  ["organizations", "subscriptions", "id -> organization_id"],
  ["plans", "subscriptions", "id -> plan_id"],
  ["subscriptions", "invoices", "id -> subscription_id"],
  ["organizations", "usage_events", "id -> organization_id"],
  ["app_users", "usage_events", "id -> user_id"],
  ["organizations", "support_tickets", "id -> organization_id"],
  ["app_users", "support_tickets", "id -> opened_by_user_id"],
  ["organizations", "feature_adoption", "id -> organization_id"],
  ["feature_flags", "feature_adoption", "id -> feature_flag_id"],
];

const schemaNodeLayout = {
  students: { x: 24, y: 64 },
  courses: { x: 24, y: 176 },
  enrollments: { x: 250, y: 120 },
  payments: { x: 476, y: 120 },
  organizations: { x: 24, y: 356 },
  app_users: { x: 250, y: 292 },
  plans: { x: 250, y: 404 },
  subscriptions: { x: 476, y: 356 },
  invoices: { x: 476, y: 468 },
  usage_events: { x: 250, y: 548 },
  support_tickets: { x: 476, y: 580 },
  feature_flags: { x: 24, y: 628 },
  feature_adoption: { x: 250, y: 660 },
  query_history: { x: 476, y: 700 },
};

const schemaDomains = [
  { id: "all", label: "All", tables: [] },
  { id: "education", label: "Education", tables: ["students", "courses", "enrollments", "payments"] },
  {
    id: "saas",
    label: "SaaS",
    tables: [
      "organizations",
      "app_users",
      "plans",
      "subscriptions",
      "invoices",
      "usage_events",
      "support_tickets",
      "feature_flags",
      "feature_adoption",
    ],
  },
  { id: "system", label: "System", tables: ["query_history"] },
];

const tableDescriptions = {
  students: "Education learners with city and join date metadata.",
  courses: "Course catalog with category and fee.",
  enrollments: "Bridge table connecting students to courses.",
  payments: "Education payments linked to enrollments.",
  organizations: "SaaS customer accounts with region, industry, and lifecycle.",
  app_users: "Users inside SaaS customer organizations.",
  plans: "Pricing plans with seats and included usage.",
  subscriptions: "Active, trialing, and past-due customer subscriptions.",
  invoices: "Monthly SaaS invoice amounts, balances, and payment status.",
  usage_events: "Aggregated product usage events by account and user.",
  support_tickets: "Customer support cases by priority and lifecycle.",
  feature_flags: "Product capabilities available for rollout/adoption.",
  feature_adoption: "Per-organization feature usage and adoption strength.",
  query_history: "Saved agent runs and execution status.",
};

function App() {
  const [question, setQuestion] = useState(sampleQuestions[0]);
  const [schema, setSchema] = useState({});
  const [history, setHistory] = useState([]);
  const [answer, setAnswer] = useState(null);
  const [health, setHealth] = useState("checking");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [isSchemaOpen, setIsSchemaOpen] = useState(true);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [requireApproval, setRequireApproval] = useState(false);
  const [savedQueries, setSavedQueries] = useState(() => loadSavedQueries());

  useEffect(() => {
    loadHealth();
    loadSchema();
    loadHistory();
  }, []);

  async function loadHealth() {
    try {
      const response = await fetch("/health");
      const payload = await response.json();
      setHealth(payload.status === "ok" ? "online" : "degraded");
    } catch {
      setHealth("offline");
    }
  }

  async function loadSchema() {
    const response = await fetch("/schema");
    const payload = await response.json();
    setSchema(payload.tables || {});
  }

  async function loadHistory() {
    const response = await fetch("/history?limit=8");
    const payload = await response.json();
    setHistory(payload.history || []);
  }

  async function runQuery(event) {
    event.preventDefault();
    if (!question.trim()) return;

    setIsLoading(true);
    setError("");

    try {
      const response = await fetch("/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question.trim(), require_approval: requireApproval }),
      });
      const payload = await readApiResponse(response);

      if (!response.ok) {
        throw new Error(payload.detail || "The agent could not answer that question.");
      }

      setAnswer(payload);
      await loadHistory();
    } catch (err) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  }

  async function approveSql() {
    if (!answer?.sql || !answer?.question) return;

    setIsLoading(true);
    setError("");

    try {
      const response = await fetch("/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: answer.question, sql: answer.sql }),
      });
      const payload = await readApiResponse(response);

      if (!response.ok) {
        throw new Error(payload.detail || "The approved SQL could not be executed.");
      }

      setAnswer(payload);
      await loadHistory();
    } catch (err) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  }

  async function copySql() {
    const sql = answer?.sql || answer?.original_sql;
    if (!sql) return;
    await navigator.clipboard.writeText(sql);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  }

  function exportResults() {
    const rows = answer?.data || [];
    if (!rows.length) return;

    const csv = toCsv(rows);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${slugify(answer?.question || "query-results")}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function saveCurrentQuestion() {
    const trimmed = question.trim();
    if (!trimmed) return;
    updateSavedQueries([trimmed, ...savedQueries.filter((saved) => saved !== trimmed)].slice(0, 12));
  }

  function removeSavedQuery(savedQuestion) {
    updateSavedQueries(savedQueries.filter((saved) => saved !== savedQuestion));
  }

  function updateSavedQueries(nextQueries) {
    setSavedQueries(nextQueries);
    window.localStorage.setItem("textToSqlSavedQueries", JSON.stringify(nextQueries));
  }

  return (
    <div className="app-shell">
      <nav className="top-nav">
        <div className="brand-lockup">
          <span className="brand-mark">SQL_ARCHITECT</span>
          <StatusPill health={health} />
        </div>
        <div className="nav-actions" aria-label="System controls">
          <button type="button" title="Signals">
            <Activity size={18} />
          </button>
          <button type="button" title="Terminal">
            <Terminal size={18} />
          </button>
        </div>
      </nav>

      <main
        className={`workbench ${isSchemaOpen ? "" : "schema-collapsed"} ${
          isHistoryOpen ? "" : "history-collapsed"
        }`}
      >
        <SchemaPanel
          schema={schema}
          onRefresh={loadSchema}
          isOpen={isSchemaOpen}
          onToggle={() => setIsSchemaOpen((value) => !value)}
        />

        <section className="data-canvas">
          <div className="canvas-inner">
            <section className="query-stage">
              <form className="query-console" onSubmit={runQuery}>
                <label htmlFor="question">Natural language prompt</label>
                <div className="input-row">
                  <Search size={20} aria-hidden="true" />
                  <textarea
                    id="question"
                    aria-label="Ask a database question"
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    placeholder="Ask about students, courses, enrollments, or payments"
                    rows={4}
                  />
                </div>
                <div className="console-footer">
                  <div className="sample-strip" aria-label="Sample questions">
                    {sampleQuestions.map((sample) => (
                      <button key={sample} type="button" onClick={() => setQuestion(sample)}>
                        {sample}
                      </button>
                    ))}
                  </div>
                  <div className="execution-controls">
                    <button className="save-query-button" type="button" onClick={saveCurrentQuestion}>
                      Save query
                    </button>
                    <label className="approval-toggle">
                      <input
                        type="checkbox"
                        checked={requireApproval}
                        onChange={(event) => setRequireApproval(event.target.checked)}
                      />
                      Review SQL before execute
                    </label>
                    <button className="run-button" type="submit" disabled={isLoading}>
                      {isLoading ? <Loader2 className="spin" size={18} /> : <Play size={18} />}
                      {isLoading ? "Running" : requireApproval ? "Generate SQL" : "Run query"}
                    </button>
                  </div>
                </div>
                {error ? (
                  <p className="error-line">
                    <AlertTriangle size={16} />
                    {error}
                  </p>
                ) : null}
              </form>
            </section>

            <FinalAnswerBand answer={answer} isLoading={isLoading} />
            <ApprovalPanel answer={answer} isLoading={isLoading} onApprove={approveSql} />
            <ResultsTable rows={answer?.data || []} rowCount={answer?.row_count || 0} onExport={exportResults} />
            <section className="analysis-grid">
              <SqlPanel answer={answer} onCopy={copySql} copied={copied} />
              <InsightPanel answer={answer} />
            </section>
          </div>
        </section>

        <HistoryPanel
          records={history}
          savedQueries={savedQueries}
          onRefresh={loadHistory}
          onSelect={(record) => setQuestion(record.question)}
          onSelectSaved={(saved) => setQuestion(saved)}
          onRemoveSaved={removeSavedQuery}
          isOpen={isHistoryOpen}
          onToggle={() => setIsHistoryOpen((value) => !value)}
        />
      </main>
    </div>
  );
}

async function readApiResponse(response) {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }

  const text = await response.text();
  if (response.status === 429 || /rate limit|too many requests|quota/i.test(text)) {
    return {
      detail:
        "The LLM provider is rate limiting requests right now. Please wait a minute and try again.",
    };
  }

  return {
    detail: response.ok
      ? text
      : "The server returned an unexpected response. Please try again or check the backend logs.",
  };
}

function loadSavedQueries() {
  try {
    const stored = JSON.parse(window.localStorage.getItem("textToSqlSavedQueries") || "null");
    return Array.isArray(stored) && stored.length ? stored : defaultSavedQueries;
  } catch {
    return defaultSavedQueries;
  }
}

function StatusPill({ health }) {
  const label = health === "online" ? "API online" : health === "offline" ? "API offline" : "Checking API";
  return (
    <div className={`status-pill ${health}`}>
      <span className="status-led" />
      {label}
    </div>
  );
}

function toCsv(rows) {
  const columns = Object.keys(rows[0] || {});
  const header = columns.map(escapeCsvCell).join(",");
  const body = rows.map((row) => columns.map((column) => escapeCsvCell(row[column])).join(","));
  return [header, ...body].join("\n");
}

function escapeCsvCell(value) {
  const text = String(value ?? "");
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function slugify(value) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 64) || "query-results";
}

function StatusBadge({ status, corrected }) {
  const label = corrected ? "corrected" : status || "standby";
  return <span className={`status-badge ${label}`}>{label}</span>;
}

function SqlPanel({ answer, onCopy, copied }) {
  const corrected = answer?.corrected_sql?.length > 0;
  const sql = answer?.sql || answer?.original_sql || "SELECT ...";

  return (
    <section className="sql-workspace">
      <div className="panel-title">
        <h2>
          <Braces size={18} />
          Generated SQL
        </h2>
        <div className="panel-actions">
          <StatusBadge status={answer?.status} corrected={corrected} />
          <button type="button" className="text-action" onClick={onCopy} disabled={!answer}>
            <Clipboard size={15} />
            {copied ? "Copied" : "Copy SQL"}
          </button>
        </div>
      </div>
      <pre className="sql-code">{sql}</pre>
      <div className="sql-meta">
        <span>Retries: {answer?.retry_count ?? 0}</span>
        <span>Rows: {answer?.row_count ?? 0}</span>
      </div>
    </section>
  );
}

function FinalAnswerBand({ answer, isLoading }) {
  const corrected = answer?.corrected_sql?.length > 0;
  const message = getFinalAnswerMessage(answer, isLoading);

  return (
    <section className="final-answer-band" aria-live="polite">
      <div>
        <span className="final-answer-label">
          <Sparkles size={16} />
          Final answer
        </span>
        <p className="final-answer-message">{message}</p>
      </div>
      <div className="final-answer-meta" aria-label="Answer status">
        <StatusBadge status={answer?.status} corrected={corrected} />
        <span>{answer?.row_count ?? 0} rows</span>
        <span>{answer?.retry_count ?? 0} retries</span>
      </div>
    </section>
  );
}

function getFinalAnswerMessage(answer, isLoading) {
  if (isLoading) {
    return "Generating SQL, validating it, and checking the database.";
  }

  if (!answer) {
    return "Ask a question to generate SQL, inspect the rows, and get a concise answer.";
  }

  return answer.final_answer || "The query completed, but no final answer was returned.";
}

function ApprovalPanel({ answer, isLoading, onApprove }) {
  if (answer?.status !== "awaiting_approval") return null;

  return (
    <section className="approval-panel">
      <div>
        <span>
          <CheckCircle2 size={16} />
          Human approval required
        </span>
        <p>Review the generated read-only SQL below, then approve it to execute against SQLite.</p>
      </div>
      <button className="approve-button" type="button" onClick={onApprove} disabled={isLoading}>
        {isLoading ? <Loader2 className="spin" size={18} /> : <CheckCircle2 size={18} />}
        Approve and execute
      </button>
    </section>
  );
}

function InsightPanel({ answer }) {
  const corrected = answer?.corrected_sql?.length > 0;

  return (
    <section className="answer-panel" aria-live="polite">
      <article className="answer-card">
        <span>
          <Clipboard size={16} />
          Explanation
        </span>
        <p>{answer?.explanation || "The SQL explanation will appear here."}</p>
      </article>

      <article className={`answer-card ${corrected ? "corrected" : ""}`}>
        <span>
          <RefreshCw size={16} />
          Correction trace
        </span>
        {corrected ? (
          <pre>{answer.corrected_sql.join("\n\n")}</pre>
        ) : (
          <p>{answer ? "No correction was needed." : "Retries and repaired SQL will appear here."}</p>
        )}
      </article>
    </section>
  );
}

function ResultsTable({ rows, rowCount, onExport }) {
  const columns = useMemo(() => (rows.length ? Object.keys(rows[0]) : []), [rows]);

  return (
    <section className="results-panel">
      <div className="panel-title">
        <h2>
          <TableProperties size={18} />
          Results
        </h2>
        <div className="panel-actions">
          <span>{rowCount} rows</span>
          <button type="button" className="text-action" disabled={!rows.length} onClick={onExport}>
            <FileDown size={15} />
            Export
          </button>
        </div>
      </div>
      {!rows.length ? (
        <div className="empty-state">No rows to display yet.</div>
      ) : (
        <div className="table-frame">
          <table>
            <thead>
              <tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={index}>
                  {columns.map((column) => (
                    <td key={column}>{String(row[column] ?? "")}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function SchemaPanel({ schema, onRefresh, isOpen, onToggle }) {
  const tableCount = Object.keys(schema).length;
  const [activeDomain, setActiveDomain] = useState("all");
  const [selectedTable, setSelectedTable] = useState(null);
  const [diagramMode, setDiagramMode] = useState("visual");
  const activeDomainConfig = schemaDomains.find((domain) => domain.id === activeDomain) || schemaDomains[0];
  const visibleTables = Object.entries(schema).filter(
    ([table]) => activeDomain === "all" || activeDomainConfig.tables.includes(table),
  );
  const visibleSchema = Object.fromEntries(visibleTables);
  const selectedColumns = selectedTable ? schema[selectedTable] || [] : [];

  return (
    <aside className={`schema-rail ${isOpen ? "" : "is-collapsed"}`}>
      <CollapsedRailButton
        icon={<Database size={18} />}
        label="Open schema"
        isVisible={!isOpen}
        onClick={onToggle}
      />
      <div className="rail-content" aria-hidden={!isOpen}>
        <div className="panel-title">
          <h2>
            <Database size={18} />
            Schema Explorer
          </h2>
          <div className="panel-actions">
            <button type="button" className="tool-button" onClick={onRefresh} title="Refresh schema">
              <RefreshCw size={16} />
            </button>
            <button type="button" className="tool-button" onClick={onToggle} title="Close schema">
              <ChevronLeft size={17} />
            </button>
          </div>
        </div>
        <div className="rail-summary">
          <strong>{tableCount}</strong>
          <span>tables indexed</span>
        </div>
        <div className="schema-tabs" role="tablist" aria-label="Schema domains">
          {schemaDomains.map((domain) => (
            <button
              key={domain.id}
              type="button"
              className={activeDomain === domain.id ? "active" : ""}
              onClick={() => {
                setActiveDomain(domain.id);
                setSelectedTable(null);
              }}
            >
              {domain.label}
            </button>
          ))}
        </div>
        <SchemaMermaidDiagram
          schema={visibleSchema}
          mode={diagramMode}
          onModeChange={setDiagramMode}
          selectedTable={selectedTable}
          onSelectTable={setSelectedTable}
        />
        <TableDetailDrawer table={selectedTable} columns={selectedColumns} onClose={() => setSelectedTable(null)} />
        <div className="schema-stack">
          {visibleTables.map(([table, columns]) => (
            <details key={table} open={selectedTable === table || ["students", "courses"].includes(table)}>
              <summary>
                <button type="button" onClick={() => setSelectedTable(table)}>
                  {table}
                </button>
                <em>{columns.length}</em>
              </summary>
              <div className="column-list">
                {columns.map((column) => (
                  <span key={column.name} className="column-item">
                    <strong>{column.name}</strong>
                    <ColumnBadges column={column} />
                    <em>{column.type}</em>
                  </span>
                ))}
              </div>
            </details>
          ))}
        </div>
      </div>
    </aside>
  );
}

function SchemaMermaidDiagram({ schema, mode, onModeChange, selectedTable, onSelectTable }) {
  const tableNames = Object.keys(schema);
  const availableTables = new Set(tableNames);
  const nodes = tableNames
    .map((table) => ({ table, ...(schemaNodeLayout[table] || fallbackNodePosition(table, tableNames)) }))
    .sort((a, b) => a.y - b.y || a.x - b.x);
  const relationships = schemaRelationships.filter(
    ([source, target]) => availableTables.has(source) && availableTables.has(target),
  );
  const mermaidSource = buildMermaidSource(tableNames, relationships);

  return (
    <section className="schema-diagram" aria-label="Mermaid schema table diagram">
      <div className="schema-diagram-title">
        <span>Mermaid ERD</span>
        <div className="schema-mode-toggle" aria-label="Diagram mode">
          <button type="button" className={mode === "visual" ? "active" : ""} onClick={() => onModeChange("visual")}>
            Visual
          </button>
          <button type="button" className={mode === "source" ? "active" : ""} onClick={() => onModeChange("source")}>
            Source
          </button>
        </div>
      </div>
      {mode === "source" ? (
        <pre className="mermaid-source">{mermaidSource}</pre>
      ) : (
      <div className="schema-diagram-scroll">
        <svg viewBox="0 0 660 800" role="img" aria-label="Schema relationship diagram">
          <defs>
            <marker id="schema-arrow" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
              <path d="M0,0 L8,4 L0,8 Z" />
            </marker>
          </defs>
          {relationships.map(([source, target, label]) => {
            const sourceNode = schemaNodeLayout[source] || fallbackNodePosition(source, tableNames);
            const targetNode = schemaNodeLayout[target] || fallbackNodePosition(target, tableNames);
            const x1 = sourceNode.x + 160;
            const y1 = sourceNode.y + 24;
            const x2 = targetNode.x;
            const y2 = targetNode.y + 24;
            const midX = (x1 + x2) / 2;
            const isActive = selectedTable && (selectedTable === source || selectedTable === target);
            return (
              <g key={`${source}-${target}`} className={isActive ? "is-active" : ""}>
                <path
                  className="schema-link"
                  d={`M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`}
                  markerEnd="url(#schema-arrow)"
                />
                <text className="schema-link-label" x={midX - 28} y={(y1 + y2) / 2 - 4}>
                  {label}
                </text>
              </g>
            );
          })}
          {nodes.map(({ table, x, y }) => (
            <g
              key={table}
              className={`schema-node ${selectedTable === table ? "is-selected" : ""}`}
              onClick={() => onSelectTable(table)}
              role="button"
              tabIndex="0"
            >
              <rect x={x} y={y} width="160" height="48" />
              <text x={x + 12} y={y + 21}>{table}</text>
              <text className="schema-node-meta" x={x + 12} y={y + 36}>
                {(schema[table] || []).length} columns
              </text>
            </g>
          ))}
        </svg>
      </div>
      )}
    </section>
  );
}

function TableDetailDrawer({ table, columns, onClose }) {
  if (!table) return null;
  const relations = schemaRelationships.filter(([source, target]) => source === table || target === table);

  return (
    <section className="table-drawer" aria-label={`${table} table details`}>
      <div className="table-drawer-header">
        <div>
          <span>Table detail</span>
          <h3>{table}</h3>
        </div>
        <button type="button" className="text-action" onClick={onClose}>
          Close
        </button>
      </div>
      <p>{tableDescriptions[table] || "Database table available to the Text-to-SQL agent."}</p>
      <div className="table-drawer-meta">
        <span>{columns.length} columns</span>
        <span>{relations.length} links</span>
      </div>
      <div className="drawer-column-list">
        {columns.map((column) => (
          <span key={column.name}>
            <strong>{column.name}</strong>
            <ColumnBadges column={column} />
          </span>
        ))}
      </div>
    </section>
  );
}

function ColumnBadges({ column }) {
  const badges = getColumnBadges(column);
  return (
    <span className="column-badges" aria-label={`${column.name} column badges`}>
      {badges.map((badge) => (
        <i key={badge}>{badge}</i>
      ))}
    </span>
  );
}

function getColumnBadges(column) {
  const name = column.name.toLowerCase();
  const badges = [];
  if (column.primary_key) badges.push("PK");
  if (name.endsWith("_id") && !column.primary_key) badges.push("FK");
  if (name.includes("status") || name.includes("priority") || name.includes("tier") || name.includes("stage")) badges.push("ENUM");
  if (name.includes("amount") || name.includes("price") || name.includes("fee")) badges.push("MONEY");
  if (name.endsWith("_on") || name.includes("date") || name.includes("month")) badges.push("DATE");
  if (name.includes("email")) badges.push("PII");
  return badges.length ? badges : ["COL"];
}

function buildMermaidSource(tableNames, relationships) {
  const lines = ["erDiagram"];
  relationships.forEach(([source, target, label]) => {
    lines.push(`  ${source} ||--o{ ${target} : "${label}"`);
  });
  tableNames.forEach((table) => {
    if (!relationships.some(([source, target]) => source === table || target === table)) {
      lines.push(`  ${table}`);
    }
  });
  return lines.join("\n");
}

function fallbackNodePosition(table, tableNames) {
  const index = tableNames.indexOf(table);
  return {
    x: 24 + (index % 3) * 226,
    y: 64 + Math.floor(index / 3) * 112,
  };
}

function HistoryPanel({ records, savedQueries, onRefresh, onSelect, onSelectSaved, onRemoveSaved, isOpen, onToggle }) {
  return (
    <aside className={`history-rail ${isOpen ? "" : "is-collapsed"}`}>
      <CollapsedRailButton
        icon={<History size={18} />}
        label="Open history"
        isVisible={!isOpen}
        onClick={onToggle}
      />
      <div className="rail-content" aria-hidden={!isOpen}>
        <div className="panel-title">
          <h2>
            <History size={18} />
            History
          </h2>
          <div className="panel-actions">
            <button type="button" className="tool-button" onClick={onRefresh} title="Refresh history">
              <RefreshCw size={16} />
            </button>
            <button type="button" className="tool-button" onClick={onToggle} title="Close history">
              <ChevronRight size={17} />
            </button>
          </div>
        </div>
        <div className="rail-summary">
          <strong>{records.length}</strong>
          <span>recent runs</span>
        </div>
        <div className="history-section-title">
          <span>Saved collection</span>
          <em>{savedQueries.length}</em>
        </div>
        <div className="saved-query-stack">
          {savedQueries.map((saved) => (
            <div className="saved-query-item" key={saved}>
              <button type="button" onClick={() => onSelectSaved(saved)}>
                {saved}
              </button>
              <button type="button" className="remove-saved" onClick={() => onRemoveSaved(saved)} title="Remove saved query">
                x
              </button>
            </div>
          ))}
        </div>
        <div className="history-section-title">
          <span>Recent history</span>
          <em>{records.length}</em>
        </div>
        <div className="history-stack">
          {records.length ? (
            records.map((record) => (
              <button key={record.id} type="button" onClick={() => onSelect(record)}>
                <strong>{record.question}</strong>
                <span>{record.execution_status} / click to rerun</span>
              </button>
            ))
          ) : (
            <p className="empty-state compact">No saved queries yet.</p>
          )}
        </div>
      </div>
    </aside>
  );
}

function CollapsedRailButton({ icon, label, isVisible, onClick }) {
  if (!isVisible) return null;

  return (
    <button type="button" className="collapsed-rail-button" onClick={onClick} title={label} aria-label={label}>
      {icon}
      <span>{label.replace("Open ", "")}</span>
    </button>
  );
}

createRoot(document.getElementById("root")).render(<App />);
