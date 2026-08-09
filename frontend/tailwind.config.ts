import type { Config } from 'tailwindcss';

/**
 * Tailwind reads from the CSS custom properties defined in src/styles/tokens.css
 * rather than defining colours here. Tokens stay the single source of truth, so
 * the design system can evolve without touching component classes — and the
 * default Tailwind palette (which makes projects look generic) is never used.
 */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        surface: {
          base: 'var(--surface-base)',
          raised: 'var(--surface-raised)',
          overlay: 'var(--surface-overlay)',
        },
        border: {
          subtle: 'var(--border-subtle)',
          strong: 'var(--border-strong)',
        },
        content: {
          primary: 'var(--content-primary)',
          secondary: 'var(--content-secondary)',
          muted: 'var(--content-muted)',
        },
        accent: {
          DEFAULT: 'var(--accent)',
          muted: 'var(--accent-muted)',
        },
        risk: {
          low: 'var(--risk-low)',
          moderate: 'var(--risk-moderate)',
          high: 'var(--risk-high)',
          critical: 'var(--risk-critical)',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
} satisfies Config;
