"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { authedFetch } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";
import styles from "./tasks.module.css";

type Todo = {
  id: string;
  title: string;
  completed: boolean;
  completed_at: string | null;
  document_id: string | null;
};

export default function TasksPage() {
  const router = useRouter();
  const [checking, setChecking] = useState(true);
  const [todos, setTodos] = useState<Todo[]>([]);
  const [newTitle, setNewTitle] = useState("");
  const [completedOpen, setCompletedOpen] = useState(false);

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (!session) {
        router.replace("/signin");
        return;
      }
      setChecking(false);
    });
  }, [router]);

  useEffect(() => {
    if (checking) return;
    authedFetch("/api/todos")
      .then((res) => res.json())
      .then((body) => setTodos(body.todos ?? []));
  }, [checking]);

  async function handleAdd() {
    const title = newTitle.trim();
    if (!title) return;
    setNewTitle("");

    const res = await authedFetch("/api/todos", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ title }),
    });
    const todo: Todo = await res.json();
    setTodos((prev) => [todo, ...prev]);
  }

  async function handleToggle(todo: Todo) {
    const nowCompleted = !todo.completed;
    // Optimistic update — the actual completed_at is derived
    // server-side (todo_storage.py never trusts a client-supplied
    // timestamp), so the real value arrives on the next fetch; this is
    // just so the checkbox and completed-section move instantly.
    setTodos((prev) =>
      prev.map((t) => (t.id === todo.id ? { ...t, completed: nowCompleted } : t))
    );

    const res = await authedFetch(`/api/todos/${todo.id}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ completed: nowCompleted }),
    });
    const updated: Todo = await res.json();
    setTodos((prev) => prev.map((t) => (t.id === todo.id ? updated : t)));
  }

  async function handleDelete(id: string) {
    await authedFetch(`/api/todos/${id}`, { method: "DELETE" });
    setTodos((prev) => prev.filter((t) => t.id !== id));
  }

  if (checking) return null;

  const active = todos.filter((t) => !t.completed);
  const completed = todos.filter((t) => t.completed);

  return (
    <div className={styles.page}>
      <div className={styles.pageHeader}>
        <h1>Tasks</h1>
        <span className={styles.backLink} onClick={() => router.push("/graph")}>
          ← Back to Brain
        </span>
      </div>

      <div className={styles.addRow}>
        <span className={styles.plus}>+</span>
        <input
          type="text"
          placeholder="Add a task and press Enter…"
          value={newTitle}
          onChange={(e) => setNewTitle(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleAdd();
          }}
        />
      </div>

      <div className={styles.list}>
        {active.length === 0 && (
          <div className={styles.emptyState}>No tasks yet — add one above.</div>
        )}
        {active.map((todo) => (
          <div key={todo.id} className={styles.row}>
            <button
              className={styles.checkbox}
              onClick={() => handleToggle(todo)}
              aria-label="Mark complete"
            />
            <span className={styles.taskText}>{todo.title}</span>
            <button
              className={styles.deleteButton}
              onClick={() => handleDelete(todo.id)}
              aria-label="Delete task"
            >
              ×
            </button>
          </div>
        ))}
      </div>

      {completed.length > 0 && (
        <div className={styles.completedSection}>
          <button
            className={styles.completedToggle}
            onClick={() => setCompletedOpen((open) => !open)}
          >
            <span className={`${styles.chevron} ${completedOpen ? styles.chevronOpen : ""}`}>
              ▸
            </span>
            Completed ({completed.length})
          </button>
          {completedOpen && (
            <div className={styles.list}>
              {completed.map((todo) => (
                <div key={todo.id} className={`${styles.row} ${styles.rowDone}`}>
                  <button
                    className={`${styles.checkbox} ${styles.checkboxChecked}`}
                    onClick={() => handleToggle(todo)}
                    aria-label="Mark incomplete"
                  />
                  <span className={styles.taskText}>{todo.title}</span>
                  <button
                    className={styles.deleteButton}
                    onClick={() => handleDelete(todo.id)}
                    aria-label="Delete task"
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
