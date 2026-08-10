import type { HTMLAttributes, ReactNode } from 'react';

interface PanelProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
}

export function Panel({ children, className = '', ...rest }: PanelProps) {
  return (
    <div
      className={`rounded-lg border border-border-subtle bg-surface-raised ${className}`}
      {...rest}
    >
      {children}
    </div>
  );
}
