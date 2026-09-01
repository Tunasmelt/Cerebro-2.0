import React from 'react';

export function Input({ label, placeholder, mono = false, disabled = false, defaultValue, ...props }) {
  return (
    <>
      <style>{`
        .cerebro-field { display: flex; flex-direction: column; gap: var(--space-1); font-family: var(--font-ui); }
        .cerebro-field label {
          font-size: var(--text-xs);
          color: var(--text-secondary);
          font-weight: var(--weight-medium);
        }
        .cerebro-input {
          background: var(--bg-elevated);
          border: 1px solid var(--border-default);
          border-radius: var(--radius-md);
          color: var(--text-primary);
          padding: var(--space-2) var(--space-3);
          font-size: var(--text-sm);
          font-family: var(--font-ui);
          transition: border-color var(--duration-base) var(--ease-soft),
                      box-shadow var(--duration-base) var(--ease-soft);
        }
        .cerebro-input.mono { font-family: var(--font-mono); }
        .cerebro-input::placeholder { color: var(--text-disabled); }
        .cerebro-input:hover:not(:disabled) { border-color: var(--border-strong); }
        .cerebro-input:focus {
          outline: none;
          border-color: var(--accent-primary);
          box-shadow: 0 0 0 3px var(--accent-primary-subtle);
        }
        .cerebro-input:disabled { opacity: 0.4; cursor: not-allowed; }
      `}</style>
      <div className="cerebro-field">
        {label ? <label>{label}</label> : null}
        <input
          className={`cerebro-input${mono ? ' mono' : ''}`}
          placeholder={placeholder}
          disabled={disabled}
          defaultValue={defaultValue}
          {...props}
        />
      </div>
    </>
  );
}
