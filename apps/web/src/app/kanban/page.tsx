"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import AppShell from "@/components/AppShell";
import { authedFetch } from "@/lib/api";
import { useAuthedUser } from "@/lib/useAuthedUser";
import styles from "./kanban.module.css";

type Card = {
  id: string;
  column_name: string;
  title: string;
  description: string;
  position: number;
  document_id: string | null;
};

type Board = {
  id: string;
  title: string;
  columns: string[];
  cards: Card[];
};

const DEFAULT_BOARD_TITLE = "My Board";

export default function KanbanPage() {
  const { checking, email } = useAuthedUser();
  const [board, setBoard] = useState<Board | null>(null);
  const [loading, setLoading] = useState(true);
  const [addingColumn, setAddingColumn] = useState<string | null>(null);
  const [newCardTitle, setNewCardTitle] = useState("");
  const draggedCardId = useRef<string | null>(null);
  const [dragOverColumn, setDragOverColumn] = useState<string | null>(null);

  const loadBoard = useCallback(async () => {
    const listRes = await authedFetch("/api/boards");
    const listBody = await listRes.json();
    const boards = listBody.boards ?? [];

    let boardId: string;
    if (boards.length === 0) {
      const createRes = await authedFetch("/api/boards", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ title: DEFAULT_BOARD_TITLE }),
      });
      const created = await createRes.json();
      boardId = created.id;
    } else {
      boardId = boards[0].id;
    }

    const boardRes = await authedFetch(`/api/boards/${boardId}`);
    const boardBody = await boardRes.json();
    setBoard(boardBody);
    setLoading(false);
  }, []);

  useEffect(() => {
    if (checking) return;
    loadBoard();
  }, [checking, loadBoard]);

  function cardsInColumn(columnName: string): Card[] {
    if (!board) return [];
    return board.cards
      .filter((c) => c.column_name === columnName)
      .sort((a, b) => a.position - b.position);
  }

  async function handleAddCard(columnName: string) {
    const title = newCardTitle.trim();
    if (!title || !board) return;
    setNewCardTitle("");
    setAddingColumn(null);

    const res = await authedFetch(`/api/boards/${board.id}/cards`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ column_name: columnName, title }),
    });
    const card: Card = await res.json();
    setBoard((prev) => (prev ? { ...prev, cards: [...prev.cards, card] } : prev));
  }

  async function handleDeleteCard(cardId: string) {
    await authedFetch(`/api/cards/${cardId}`, { method: "DELETE" });
    setBoard((prev) =>
      prev ? { ...prev, cards: prev.cards.filter((c) => c.id !== cardId) } : prev
    );
  }

  function handleDragStart(cardId: string) {
    draggedCardId.current = cardId;
  }

  function handleDragEnd() {
    draggedCardId.current = null;
    setDragOverColumn(null);
  }

  async function handleDrop(columnName: string, dropIndex: number) {
    const cardId = draggedCardId.current;
    setDragOverColumn(null);
    if (!cardId || !board) return;

    const columnCards = cardsInColumn(columnName).filter((c) => c.id !== cardId);
    const before = columnCards[dropIndex - 1];
    const after = columnCards[dropIndex];
    // Insert between neighbors by averaging their positions — see
    // kanban_storage.py's module docstring for why position is a
    // float. Falls back to a fresh gap at either end of the column.
    const newPosition =
      before && after
        ? (before.position + after.position) / 2
        : before
          ? before.position + 1000
          : after
            ? after.position - 1000
            : 0;

    // Optimistic local update — the PATCH persists it, but the board
    // feels instant, and a page reload (the exit criteria's actual
    // test) reads back whatever the PATCH really wrote.
    setBoard((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        cards: prev.cards.map((c) =>
          c.id === cardId ? { ...c, column_name: columnName, position: newPosition } : c
        ),
      };
    });

    await authedFetch(`/api/cards/${cardId}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ column_name: columnName, position: newPosition }),
    });
  }

  if (checking || loading) return null;
  if (!board) return null;

  return (
    <AppShell userEmail={email}>
    <div className={styles.page}>
      <div className={styles.pageHeader}>
        <h1>{board.title}</h1>
      </div>

      <div className={styles.board}>
        {board.columns.map((columnName) => {
          const cards = cardsInColumn(columnName);
          return (
            <div
              key={columnName}
              className={`${styles.column} ${dragOverColumn === columnName ? styles.dragOver : ""}`}
              onDragOver={(e) => {
                e.preventDefault();
                setDragOverColumn(columnName);
              }}
              onDragLeave={() => setDragOverColumn(null)}
              onDrop={(e) => {
                e.preventDefault();
                handleDrop(columnName, cards.length);
              }}
            >
              <div className={styles.columnHead}>
                <span className={styles.name}>{columnName}</span>
                <span className={styles.count}>{cards.length}</span>
              </div>

              {cards.map((card, index) => (
                <div
                  key={card.id}
                  className={styles.card}
                  draggable
                  onDragStart={() => handleDragStart(card.id)}
                  onDragEnd={handleDragEnd}
                  onDragOver={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    setDragOverColumn(columnName);
                  }}
                  onDrop={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    handleDrop(columnName, index);
                  }}
                >
                  <div className={styles.cardTitle}>{card.title}</div>
                  {card.description && (
                    <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                      {card.description}
                    </div>
                  )}
                  <button
                    className={styles.deleteButton}
                    onClick={() => handleDeleteCard(card.id)}
                    aria-label="Delete card"
                  >
                    ×
                  </button>
                </div>
              ))}

              <div className={styles.addCardRow}>
                {addingColumn === columnName ? (
                  <div className={styles.addCardInputWrap}>
                    <input
                      autoFocus
                      type="text"
                      placeholder="Card title"
                      value={newCardTitle}
                      onChange={(e) => setNewCardTitle(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleAddCard(columnName);
                        if (e.key === "Escape") {
                          setAddingColumn(null);
                          setNewCardTitle("");
                        }
                      }}
                    />
                    <div className={styles.addCardActions}>
                      <button
                        className={styles.addCardConfirm}
                        onClick={() => handleAddCard(columnName)}
                      >
                        Add
                      </button>
                      <button
                        className={styles.addCardCancel}
                        onClick={() => {
                          setAddingColumn(null);
                          setNewCardTitle("");
                        }}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    className={styles.addCardTrigger}
                    onClick={() => setAddingColumn(columnName)}
                  >
                    + Add card
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
    </AppShell>
  );
}
