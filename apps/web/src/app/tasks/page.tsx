"use client";

import { useEffect, useState } from "react";

import AppShell from "@/components/AppShell";
import RouteLoading from "@/components/RouteLoading";
import { authedFetch } from "@/lib/api";
import { useAuthedUser } from "@/lib/useAuthedUser";
import styles from "./tasks.module.css";

type Priority = "low" | "medium" | "high";
type Filter = "all" | Priority;
type Todo = {
  id: string;
  title: string;
  priority: Priority;
  completed: boolean;
  completed_at: string | null;
  document_id: string | null;
};

type TaskRowProps = {
  todo: Todo;
  done?: boolean;
  editingId: string | null;
  editingTitle: string;
  setEditingId: (id: string | null) => void;
  setEditingTitle: (title: string) => void;
  patchTodo: (todo: Todo, updates: Partial<Pick<Todo, "title" | "priority" | "completed">>) => Promise<void>;
  saveTitle: (todo: Todo) => Promise<void>;
  deleteTodo: (id: string) => Promise<void>;
};

function TaskRow({ todo, done = false, editingId, editingTitle, setEditingId, setEditingTitle, patchTodo, saveTitle, deleteTodo }: TaskRowProps) {
  const priority = todo.priority ?? "medium";
  const priorityClass = priority === "high" ? styles.priorityHigh : priority === "low" ? styles.priorityLow : styles.priorityMedium;
  return (
    <div className={`${styles.row} ${done ? styles.rowDone : ""}`}>
      <button className={`${styles.checkbox} ${done ? styles.checkboxChecked : ""}`} onClick={() => void patchTodo(todo, { completed: !todo.completed })} aria-label={done ? "Mark incomplete" : "Mark complete"} />
      <span className={`${styles.priorityDot} ${priorityClass}`} aria-hidden="true" />
      {editingId === todo.id ? <input className={styles.editInput} autoFocus value={editingTitle} onChange={(event) => setEditingTitle(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void saveTitle(todo); if (event.key === "Escape") setEditingId(null); }} onBlur={() => void saveTitle(todo)} /> : <button className={styles.taskText} onClick={() => { setEditingId(todo.id); setEditingTitle(todo.title); }}>{todo.title}</button>}
      {!done && <select className={styles.rowPriority} value={priority} onChange={(event) => void patchTodo(todo, { priority: event.target.value as Priority })} aria-label={`Priority for ${todo.title}`}><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select>}
      <button className={styles.deleteButton} onClick={() => void deleteTodo(todo.id)} aria-label="Delete task">×</button>
    </div>
  );
}

export default function TasksPage() {
  const { checking, email } = useAuthedUser();
  const [todos, setTodos] = useState<Todo[]>([]);
  const [newTitle, setNewTitle] = useState("");
  const [newPriority, setNewPriority] = useState<Priority>("medium");
  const [filter, setFilter] = useState<Filter>("all");
  const [completedOpen, setCompletedOpen] = useState(false);
  const [loadingTodos, setLoadingTodos] = useState(true);
  const [addError, setAddError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");

  useEffect(() => {
    if (checking) return;
    authedFetch("/api/todos").then((res) => res.json()).then((body) => setTodos(body.todos ?? [])).finally(() => setLoadingTodos(false));
  }, [checking]);

  async function handleAdd() {
    const title = newTitle.trim();
    if (!title) return;
    setNewTitle("");
    setAddError(null);
    try {
      const res = await authedFetch("/api/todos", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ title, priority: newPriority }),
      });
      if (!res.ok) throw new Error();
      const todo: Todo = await res.json();
      setTodos((prev) => [todo, ...prev]);
    } catch {
      setAddError("Couldn't add that task. Try again.");
    }
  }

  async function patchTodo(todo: Todo, updates: Partial<Pick<Todo, "title" | "priority" | "completed">>) {
    const optimistic = { ...todo, ...updates };
    setTodos((prev) => prev.map((item) => item.id === todo.id ? optimistic : item));
    const res = await authedFetch(`/api/todos/${todo.id}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(updates),
    });
    if (!res.ok) {
      setTodos((prev) => prev.map((item) => item.id === todo.id ? todo : item));
      return;
    }
    const updated: Todo = await res.json();
    setTodos((prev) => prev.map((item) => item.id === todo.id ? updated : item));
  }

  async function saveTitle(todo: Todo) {
    const title = editingTitle.trim();
    if (title && title !== todo.title) await patchTodo(todo, { title });
    setEditingId(null);
  }

  async function handleDelete(id: string) {
    const res = await authedFetch(`/api/todos/${id}`, { method: "DELETE" });
    if (res.ok) setTodos((prev) => prev.filter((todo) => todo.id !== id));
  }

  if (checking) return <RouteLoading />;

  const active = todos.filter((todo) => !todo.completed && (filter === "all" || (todo.priority ?? "medium") === filter));
  const completed = todos.filter((todo) => todo.completed && (filter === "all" || (todo.priority ?? "medium") === filter));

  return (
    <AppShell userEmail={email}>
      <main className={styles.page}>
        <header className={styles.pageHeader}>
          <h1>Tasks</h1>
          <div className={styles.filters} aria-label="Filter tasks by priority">
            {(["all", "high", "medium", "low"] as Filter[]).map((value) => <button key={value} className={`${styles.filterButton} ${filter === value ? `${styles.filterActive} ${styles[`filterActive${value[0].toUpperCase()}${value.slice(1)}`]}` : ""}`} onClick={() => setFilter(value)}>{value}</button>)}
          </div>
        </header>
        <div className={styles.addRow}>
          <span className={styles.plus}>+</span>
          <input type="text" placeholder="Add a task and press Enter…" value={newTitle} onChange={(event) => setNewTitle(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void handleAdd(); }} />
          <select className={styles.prioritySelect} value={newPriority} onChange={(event) => setNewPriority(event.target.value as Priority)} aria-label="New task priority"><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select>
        </div>
        {addError && <div className={styles.addError}>{addError}</div>}
        <div className={styles.list}>
          {loadingTodos ? <div className={styles.emptyState}>Loading tasks…</div> : active.length === 0 ? <div className={styles.emptyState}>{filter === "all" ? "No tasks yet — add one above." : `No ${filter}-priority tasks.`}</div> : active.map((todo) => <TaskRow key={todo.id} todo={todo} editingId={editingId} editingTitle={editingTitle} setEditingId={setEditingId} setEditingTitle={setEditingTitle} patchTodo={patchTodo} saveTitle={saveTitle} deleteTodo={handleDelete} />)}
        </div>
        {completed.length > 0 && <section className={styles.completedSection}><button className={styles.completedToggle} onClick={() => setCompletedOpen((open) => !open)}><span className={`${styles.chevron} ${completedOpen ? styles.chevronOpen : ""}`}>▸</span>Completed ({completed.length})</button>{completedOpen && <div className={styles.list}>{completed.map((todo) => <TaskRow key={todo.id} todo={todo} done editingId={editingId} editingTitle={editingTitle} setEditingId={setEditingId} setEditingTitle={setEditingTitle} patchTodo={patchTodo} saveTitle={saveTitle} deleteTodo={handleDelete} />)}</div>}</section>}
      </main>
    </AppShell>
  );
}
