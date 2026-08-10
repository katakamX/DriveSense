import type { ReactNode } from 'react';

export type BadgeTone = 'neutral' | 'low' | 'moderate' | 'high' | 'critical';

const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: 'border-border-subtle bg-surface-overlay text-content-secondary',
  low: 'border-risk-low/30 bg-risk-low/10 text-risk-low',
  moderate: 'border-risk-moderate/30 bg-risk-moderate/10 text-risk-moderate',
  high: 'border-risk-high/30 bg-risk-high/10 text-risk-high',
  critical: 'border-risk-critical/30 bg-risk-critical/10 text-risk-critical',
};

interface BadgeProps {
  children: ReactNode;
  tone?: BadgeTone;
}

export function Badge({ children, tone = 'neutral' }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${TONE_CLASSES[tone]}`}
    >
      {children}
    </span>
  );
}
