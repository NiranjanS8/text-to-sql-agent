import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  Braces,
  Clipboard,
  Database,
  History,
  Loader2,
  Play,
  RefreshCw,
  Search,
  Sparkles,
  TableProperties,
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

  return (
    <main className="app">
      <section className="command-deck">
        <header className="masthead">
          <div>
            <p className="kicker">SQLite agent console</p>
            <h1>Text-to-SQL Agent</h1>
          </div>
          <StatusPill health={health} />
        </header>

        <form className="query-console" onSubmit={runQuery}>
          <label htmlFor="question">Ask a database question</label>
          <div className="input-row">
            <Search size={20} aria-hidden="true" />
            <textarea
              id="question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Ask about students, courses, enrollments, or payments"
              rows={3}
            />
          </div>
          <div className="console-actions">
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

        <AnswerPanel answer={answer} isLoading={isLoading} />
        <ResultsTable rows={answer?.data || []} rowCount={answer?.row_count || 0} />
      </section>

      <aside className="intel-rail">
        <SchemaPanel schema={schema} onRefresh={loadSchema} />
        <HistoryPanel
          records={history}
          onRefresh={loadHistory}
          onSelect={(record) => setQuestion(record.question)}
        />
      </aside>
    </main>
  );
}

function StatusPill({ health }) {
  const label = health === "online" ? "API online" : health === "offline" ? "API offline" : "Checking API";
  return (
    <div className={`status-pill ${health}`}>
      <Activity size={16} />
      {label}
    </div>
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

      <article className="answer-card sql">
        <span>
          <Braces size={16} />
          Generated SQL
        </span>
        <pre>{answer?.sql || answer?.original_sql || "SELECT ..."}</pre>
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
        <span>{rowCount} rows</span>
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

function SchemaPanel({ schema, onRefresh }) {
  return (
    <section className="rail-panel">
      <div className="panel-title">
        <h2>
          <Database size={18} />
          Schema
        </h2>
        <button type="button" className="tool-button" onClick={onRefresh} title="Refresh schema">
          <RefreshCw size={16} />
        </button>
      </div>
      <div className="schema-stack">
        {Object.entries(schema).map(([table, columns]) => (
          <details key={table} open={["students", "courses"].includes(table)}>
            <summary>{table}</summary>
            <p>{columns.map((column) => `${column.name} ${column.type}`).join(", ")}</p>
          </details>
        ))}
      </div>
    </section>
  );
}

function HistoryPanel({ records, onRefresh, onSelect }) {
  return (
    <section className="rail-panel">
      <div className="panel-title">
        <h2>
          <History size={18} />
          History
        </h2>
        <button type="button" className="tool-button" onClick={onRefresh} title="Refresh history">
          <RefreshCw size={16} />
        </button>
      </div>
      <div className="history-stack">
        {records.length ? (
          records.map((record) => (
            <button key={record.id} type="button" onClick={() => onSelect(record)}>
              <strong>{record.question}</strong>
              <span>{record.execution_status}</span>
            </button>
          ))
        ) : (
          <p className="empty-state compact">No saved queries yet.</p>
        )}
      </div>
    </section>
  );
}

createRoot(document.getElementById("root")).render(<App />);

