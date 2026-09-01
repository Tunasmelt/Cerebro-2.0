import React from 'react';

/**
 * @startingPoint section="Components" subtitle="Primary, secondary, ghost, and danger actions" viewport="700x150"
 */
export interface ButtonProps {
  /** Visual style. primary = violet (main CTA), secondary = teal (confirm/secondary action), ghost = outline (low emphasis), danger = red (destructive). */
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'sm' | 'md';
  children: React.ReactNode;
  disabled?: boolean;
  onClick?: () => void;
}

export function Button(props: ButtonProps): JSX.Element;
