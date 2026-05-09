import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertTriangle,
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
  const [isHistoryOpen, setIsHistoryOpen] = useState(true);

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
        body: JSON.stringify({ question: question.trim() }),
      });
      const payload = await response.json();

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

  async function copySql() {
    const sql = answer?.sql || answer?.original_sql;
    if (!sql) return;
    await navigator.clipboard.writeText(sql);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
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
                  <button className="run-button" type="submit" disabled={isLoading}>
                    {isLoading ? <Loader2 className="spin" size={18} /> : <Play size={18} />}
                    {isLoading ? "Running" : "Run query"}
                  </button>
                </div>
                {error ? (
                  <p className="error-line">
                    <AlertTriangle size={16} />
                    {error}
                  </p>
                ) : null}
              </form>
            </section>

            <ResultsTable rows={answer?.data || []} rowCount={answer?.row_count || 0} />
            <section className="analysis-grid">
              <SqlPanel answer={answer} onCopy={copySql} copied={copied} />
              <AnswerPanel answer={answer} isLoading={isLoading} />
            </section>
          </div>
        </section>

        <HistoryPanel
          records={history}
          onRefresh={loadHistory}
          onSelect={(record) => setQuestion(record.question)}
          isOpen={isHistoryOpen}
          onToggle={() => setIsHistoryOpen((value) => !value)}
        />
      </main>
    </div>
  );
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

function AnswerPanel({ answer, isLoading }) {
  const corrected = answer?.corrected_sql?.length > 0;

  return (
    <section className="answer-panel" aria-live="polite">
      <article className="answer-card final">
        <span>
          <Sparkles size={16} />
          Final answer
        </span>
        <p>{isLoading ? "The agent is generating SQL and checking the database." : answer?.final_answer || "Run a query to see the answer."}</p>
      </article>

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

function ResultsTable({ rows, rowCount }) {
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
          <button type="button" className="text-action" disabled={!rows.length}>
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
        <div className="schema-stack">
          {Object.entries(schema).map(([table, columns]) => (
            <details key={table} open={["students", "courses"].includes(table)}>
              <summary>
                <span>{table}</span>
                <em>{columns.length}</em>
              </summary>
              <div className="column-list">
                {columns.map((column) => (
                  <span key={column.name}>
                    {column.name} <em>{column.type}</em>
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

function HistoryPanel({ records, onRefresh, onSelect, isOpen, onToggle }) {
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
