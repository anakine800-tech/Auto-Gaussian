import { defineConfig } from 'vite';
// Keep the favicon a same-origin file; the UI CSP does not permit data URLs.
export default defineConfig({ build: { assetsInlineLimit: 0 } });
