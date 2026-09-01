import React from 'react';

export function Card({ title, meta, children, interactive = false }) {
  return (
    <>
      <style>{`
        .cerebro-card {
          background: var(--bg-elevated);
          border: 1px solid var(--border-subtle);
          border-radius: var(--radius-lg);
          padding: var(--space-4);
          display: flex;
          flex-direction: column;
          gap: var(--space-2);
          transition: background var(--duration-base) var(--ease-soft),
                      border-color var(--duration-base) var(--ease-soft),
                      transform var(--duration-fast) var(--ease-soft);
        }
        .cerebro-card.interactive { cursor: pointer; }
        .cerebro-card.interactive:hover { background: var(--bg-elevated-hover); border-color: var(--border-strong); }
        .cerebro-card.interactive:active { transform: scale(0.99); border-color: var(--accent-primary-border); }
        .cerebro-card-title { font-family: var(--font-ui); font-size: var(--text-md); font-weight: var(--weight-semibold); color: var(--text-primary); }
        .cerebro-card-meta { font-family: var(--font-mono); font-size: var(--text-xs); color: var(--text-secondary); }
        .cerebro-card-body { font-family: var(--font-ui); font-size: var(--text-sm); color: var(--text-secondary); line-height: var(--leading-sm); }
      `}</style>
      <div className={`cerebro-card${interactive ? ' interactive' : ''}`}>
        {title ? <div className="cerebro-card-title">{title}</div> : null}
        {meta ? <div className="cerebro-card-meta">{meta}</div> : null}
        {children ? <div className="cerebro-card-body">{children}</div> : null}
      </div>
    </>
  );
}
