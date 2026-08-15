import { defineConfig, mergeConfig } from 'vitest/config';

import viteConfig from './vite.config';

// Merged rather than redefined so the `@` alias has one definition. A test
// suite that resolved imports differently from the build would be testing a
// module graph the application never has.
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      include: ['src/**/*.test.{ts,tsx}'],
    },
  }),
);
