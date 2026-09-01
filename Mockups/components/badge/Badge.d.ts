import React from 'react';

/**
 * @startingPoint section="Components" subtitle="Status labels — neutral, live, success, and locked (amber, encryption only)" viewport="700x90"
 */
export interface BadgeProps {
  /** locked is reserved exclusively for encryption/lock-related state. */
  variant?: 'neutral' | 'live' | 'success' | 'locked';
  /** Adds a small status dot; on "live" it pulses with the retrieval-pulse timing. */
  dot?: boolean;
  children: React.ReactNode;
}

export function Badge(props: BadgeProps): JSX.Element;
