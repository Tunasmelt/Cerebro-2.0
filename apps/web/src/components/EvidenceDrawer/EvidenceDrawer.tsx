"use client";

import { useEffect, useRef, useState } from "react";

import { authedFetch } from "@/lib/api";
import type { Citation } from "@/lib/graph/types";
import styles from "./EvidenceDrawer.module.css";

type Evidence = {
  chunk_id: string;
  document: { id: string; title: string; layout_status?: string };
  surface?: { page_number: number | null; kind: string };
  surfaces?: { page_number: number | null }[];
  source_page_number?: number | null;
  region: null | {
    region_type: string;
    bbox: [number, number, number, number] | null;
    content: string;
    semantic_summary: string | null;
    text_start: number | null;
    text_end: number | null;
  };
  heading_path?: string[];
  nearby?: { region_id: string; region_type: string; content: string }[];
  render_url: string | null;
  legacy: boolean;
  content?: string;
};

export type EvidenceDrawerProps = {
  citation: Citation | null;
  onClose: () => void;
};

export default function EvidenceDrawer({ citation, onClose }: EvidenceDrawerProps) {
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "missing" | "locked" | "error">("loading");
  const [zoom, setZoom] = useState(100);
  const [selectedPage, setSelectedPage] = useState<number | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLElement>(null);
  const priorFocus = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!citation) return;
    priorFocus.current = document.activeElement as HTMLElement | null;
    setEvidence(null);
    setState("loading");
    setZoom(100);
    const controller = new AbortController();
    const pageQuery = selectedPage ? `?page=${selectedPage}` : "";
    authedFetch(`/api/chunks/${encodeURIComponent(citation.chunk_id)}/evidence${pageQuery}`, {
      signal: controller.signal,
    })
      .then(async (response) => {
        if (response.status === 423) return setState("locked");
        if (response.status === 404) return setState("missing");
        if (!response.ok) return setState("error");
        setEvidence((await response.json()) as Evidence);
        setState("ready");
      })
      .catch((error: unknown) => {
        if ((error as { name?: string }).name !== "AbortError") setState("error");
      });
    requestAnimationFrame(() => closeRef.current?.focus());
    return () => controller.abort();
  }, [citation, selectedPage]);

  useEffect(() => setSelectedPage(null), [citation?.chunk_id]);

  useEffect(() => {
    if (!citation) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        onClose();
      } else if (event.key === "Tab") {
        const focusable = [...(drawerRef.current?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), a[href], input:not([disabled]), [tabindex]:not([tabindex="-1"])'
        ) ?? [])];
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    }
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [citation, onClose]);

  useEffect(() => {
    if (citation) return;
    priorFocus.current?.focus();
  }, [citation]);

  if (!citation) return null;
  const bbox = evidence?.region?.bbox;
  const pageNumbers = (evidence?.surfaces ?? [])
    .map((surface) => surface.page_number)
    .filter((page): page is number => page !== null);
  const currentPage = evidence?.surface?.page_number ?? null;
  const currentPageIndex = currentPage === null ? -1 : pageNumbers.indexOf(currentPage);

  return (
    <div className={styles.backdrop} onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <aside ref={drawerRef} className={styles.drawer} role="dialog" aria-modal="true" aria-label="Citation evidence">
        <header className={styles.header}>
          <div>
            <span className={styles.eyebrow}>Source evidence</span>
            <h2>{evidence?.document.title ?? citation.document_title ?? "Document"}</h2>
          </div>
          <button ref={closeRef} className={styles.close} onClick={onClose} aria-label="Close evidence">×</button>
        </header>

        {state === "loading" && <div className={styles.state}>Loading exact evidence…</div>}
        {state === "locked" && <div className={styles.state}>This document is sealed. Exact evidence stays unavailable until it is unsealed.</div>}
        {state === "missing" && <div className={styles.state}>This is a legacy citation. Open the document in Brain to inspect its available context.</div>}
        {state === "error" && <div className={styles.state}>Evidence could not be loaded. Try again.</div>}

        {state === "ready" && evidence && (
          <div className={styles.body}>
            <div className={styles.meta}>
              {evidence.surface?.page_number && <span>Page {evidence.surface.page_number}</span>}
              {evidence.region?.region_type && <span>{evidence.region.region_type}</span>}
              {evidence.document.layout_status === "partial" && <span>Partial layout</span>}
            </div>
            {pageNumbers.length > 1 && currentPageIndex >= 0 && (
              <div className={styles.pageControls} aria-label="Evidence page navigation">
                <button disabled={currentPageIndex === 0} onClick={() => setSelectedPage(pageNumbers[currentPageIndex - 1])}>Previous</button>
                <span>{currentPageIndex + 1} / {pageNumbers.length}</span>
                <button disabled={currentPageIndex === pageNumbers.length - 1} onClick={() => setSelectedPage(pageNumbers[currentPageIndex + 1])}>Next</button>
              </div>
            )}
            {evidence.heading_path && evidence.heading_path.length > 0 && (
              <div className={styles.headingPath}>{evidence.heading_path.join(" / ")}</div>
            )}

            {evidence.render_url ? (
              <>
                <div className={styles.zoomControls} aria-label="Evidence zoom controls">
                  <button onClick={() => setZoom((value) => Math.max(50, value - 25))} aria-label="Zoom out">−</button>
                  <span>{zoom}%</span>
                  <button onClick={() => setZoom((value) => Math.min(250, value + 25))} aria-label="Zoom in">+</button>
                </div>
                <div className={styles.viewport}>
                  <div className={styles.page} style={{ width: `${zoom}%` }}>
                    {/* Signed evidence URLs are short-lived and cannot be configured as a static Next image host. */}
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={evidence.render_url} alt={`Evidence page ${evidence.surface?.page_number ?? ""}`} />
                    {bbox && <span className={styles.highlight} style={{ left: `${bbox[0] * 100}%`, top: `${bbox[1] * 100}%`, width: `${(bbox[2] - bbox[0]) * 100}%`, height: `${(bbox[3] - bbox[1]) * 100}%` }} />}
                  </div>
                </div>
              </>
            ) : evidence.region ? (
              <pre className={styles.textEvidence}><mark>{evidence.region.content}</mark></pre>
            ) : (
              <div className={styles.state}>{evidence.content || "No exact region is available for this legacy citation."}</div>
            )}

            {evidence.region?.semantic_summary && <p className={styles.summary}>{evidence.region.semantic_summary}</p>}
            {evidence.nearby && evidence.nearby.length > 0 && (
              <section className={styles.nearby}>
                <h3>Nearby context</h3>
                {evidence.nearby.map((region) => <p key={region.region_id}>{region.content}</p>)}
              </section>
            )}
          </div>
        )}
      </aside>
    </div>
  );
}
