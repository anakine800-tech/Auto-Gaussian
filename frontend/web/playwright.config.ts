import { defineConfig } from '@playwright/test';
const installedPython = process.env.AUTOG_TEST_PYTHON;
const sourcePython = process.env.AUTOG_SOURCE_PYTHON ?? '../.venv/bin/python';
const shellQuote = (value: string) => "'" + value.replace(/'/g, "'\\''") + "'";
export default defineConfig({
  testDir: './tests', fullyParallel: false, workers: 1, retries: 0,
  reporter: 'list', timeout: 15000,
  use: { baseURL: 'http://127.0.0.1:18765', browserName: 'chromium', channel: 'chrome', viewport: { width: 1440, height: 960 } },
  webServer: {
    command: installedPython ? `${shellQuote(installedPython)} -I -B ../scripts/ui_test_server.py --installed` : `${shellQuote(sourcePython)} -B ../scripts/ui_test_server.py`,
    url: 'http://127.0.0.1:18765', reuseExistingServer: false,
    env: { PYTHONDONTWRITEBYTECODE: '1' }, timeout: 15000,
  },
});
