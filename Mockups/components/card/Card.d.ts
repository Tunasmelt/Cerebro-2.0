import React from 'react';

/**
 * @startingPoint section="Components" subtitle="Elevated surface for notes and nodes, default/hover/active" viewport="700x200"
 */
export interface CardProps {
  title?: string;
  /** Rendered in monospace — chunk IDs, timestamps, file sizes. */
  meta?: string;
  children?: React.ReactNode;
  /** Adds hover/active affordances for clickable cards (e.g. a note in a list). */
  interactive?: boolean;
}

export function Card(props: CardProps): JSX.Element;
