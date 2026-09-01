import React from 'react';

const DOT_COLOR = {
  neutral: 'var(--text-secondary)',
  live: 'var(--accent-primary)',
  success: 'var(--accent-secondary)',
  locked: 'var(--accent-locked)',
};

export function Badge({ variant = 'neutral', children, dot = false }) {
  return (
    <>
      <style>{`
        @keyframes cerebro-badge-pulse {
          0% { transform: scale(1); opacity: 1; }
          70% { transform: scale(1.9); opacity: 0; }
          100% { transform: scale(1.9); opacity: 0; }
        }
        .cerebro-badge {
          display: inline-flex;
          align-items: center;
          gap: var(--space-1);
          font-family: var(--font-ui);
          font-size: var(--text-xs);
          font-weight: var(--weight-medium);
          padding: 2px var(--space-3);
          border-radius: var(--radius-pill);
          border: 1px solid;
          line-height: var(--leading-xs);
        }
        .cerebro-badge-neutral { background: var(--bg-elevated); border-color: var(--border-default); color: var(--text-secondary); }
        .cerebro-badge-live { background: var(--accent-primary-subtle); border-color: var(--accent-primary-border); color: var(--accent-primary-hover); }
        .cerebro-badge-success { background: var(--accent-secondary-subtle); border-color: transparent; color: var(--accent-secondary); }
        .cerebro-badge-locked { background: var(--accent-locked-subtle); border-color: transparent; color: var(--accent-locked); }
        .cerebro-badge-dot-wrap { position: relative; width: 6px; height: 6px; }
        .cerebro-badge-dot { position: absolute; inset: 0; border-radius: 50%; background: currentColor; }
        .cerebro-badge-dot-ping { position: absolute; inset: 0; border-radius: 50%; background: currentColor; animation: cerebro-badge-pulse var(--duration-pulse) var(--ease-pulse) infinite; }
      `}</style>
      <span className={`cerebro-badge cerebro-badge-${variant}`}>
        {dot ? (
          <span className="cerebro-badge-dot-wrap" style={{ color: DOT_COLOR[variant] }}>
            <span className="cerebro-badge-dot" />
            <span className="cerebro-badge-dot-ping" />
          </span>
        ) : null}
        {children}
      </span>
    </>
  );
}
