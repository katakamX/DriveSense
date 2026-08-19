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
        /**
         * One superfamily, three jobs. Body and data share a skeleton and
         * metrics, which is what stops a table mixing prose and figures from
         * looking assembled out of two unrelated systems — the reason this is
         * Plex Mono rather than JetBrains Mono, whose sans is not this sans.
         *
         * `display` is the condensed cut, used for headers and the hero score
         * only. Condensed rather than a fourth family: it supplies the tension
         * a display face needs without a third webfont download.
         */
        sans: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
        display: ['"IBM Plex Sans Condensed"', '"IBM Plex Sans"', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
      letterSpacing: {
        /* Display headers are set tight; instrument labelling is set wide. */
        display: '-0.015em',
        label: '0.12em',
      },
    },
  },
  plugins: [],
} satisfies Config;
