import React from 'react';

export function Button({ variant = 'primary', size = 'md', children, disabled = false, ...props }) {
  return (
    <>
      <style>{`
        .cerebro-btn {
          font-family: var(--font-ui);
          font-weight: var(--weight-medium);
          border-radius: var(--radius-md);
          border: 1px solid;
          cursor: pointer;
          transition: background var(--duration-base) var(--ease-soft),
                      border-color var(--duration-base) var(--ease-soft),
                      color var(--duration-base) var(--ease-soft),
                      opacity var(--duration-base) var(--ease-soft);
        }
        .cerebro-btn-md { font-size: var(--text-sm); padding: var(--space-2) var(--space-4); }
        .cerebro-btn-sm { font-size: var(--text-xs); padding: var(--space-1) var(--space-3); }
        .cerebro-btn:disabled { opacity: 0.4; cursor: not-allowed; }

        .cerebro-btn-primary { background: var(--accent-primary); border-color: transparent; color: var(--text-on-accent); }
        .cerebro-btn-primary:hover:not(:disabled) { background: var(--accent-primary-hover); }
        .cerebro-btn-primary:active:not(:disabled) { background: var(--accent-primary-active); }

        .cerebro-btn-secondary { background: var(--accent-secondary); border-color: transparent; color: var(--text-on-accent); }
        .cerebro-btn-secondary:hover:not(:disabled) { background: var(--accent-secondary-hover); }
        .cerebro-btn-secondary:active:not(:disabled) { background: var(--accent-secondary-active); }

        .cerebro-btn-ghost { background: transparent; border-color: var(--border-default); color: var(--text-primary); }
        .cerebro-btn-ghost:hover:not(:disabled) { background: var(--bg-elevated-hover); border-color: var(--border-strong); }
        .cerebro-btn-ghost:active:not(:disabled) { background: var(--border-subtle); }

        .cerebro-btn-danger { background: var(--danger); border-color: transparent; color: var(--text-primary); }
        .cerebro-btn-danger:hover:not(:disabled) { background: var(--danger-hover); }
        .cerebro-btn-danger:active:not(:disabled) { background: var(--danger-active); }
      `}</style>
      <button
        className={`cerebro-btn cerebro-btn-${variant} cerebro-btn-${size}`}
        disabled={disabled}
        {...props}
      >
        {children}
      </button>
    </>
  );
}
