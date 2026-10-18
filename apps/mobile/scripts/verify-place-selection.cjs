// Run against `expo serve` after build:web. All external requests are mocked or blocked.
// PLAYWRIGHT_MODULE_PATH may point to an already installed Playwright package.
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const baseUrl = process.env.TEST_BASE_URL || 'http://localhost:8094';
const places = [
  { google_place_id: 'test_restaurant_a', name: 'Test Soba', latitude: 35.68, longitude: 139.76, address: 'Test address A', distance_m: 42, has_public_menus: false, public_menu_count: 0 },
  { google_place_id: 'test_restaurant_b', name: 'Test Cafe', latitude: 35.681, longitude: 139.761, address: 'Test address B', distance_m: 84, has_public_menus: true, public_menu_count: 2 },
];
const analysis = { menu_id: 'test-menu', google_place_id: places[0].google_place_id, analysis_token: 'test-analysis-token', analysis_expires_at: '2099-01-01T00:00:00Z', ai_model: 'test', prompt_version: 'v5', analyzed_at: '2026-10-18T00:00:00Z', locale: 'en', dishes: [] };

(async () => {
  const browser = await chromium.launch({ headless: true });
  let completed = 0;
  async function run(name, options, check) {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const requests = [];
    const errors = [];
    await context.addInitScript(({ mode, loggedIn }) => {
      localStorage.setItem('meelyze.walkthrough.seen', '1');
      if (loggedIn) {
        sessionStorage.setItem('meelyze.account_token', 'test-account-token');
        sessionStorage.setItem('meelyze.account_token_expires_at', '2099-01-01T00:00:00Z');
        sessionStorage.setItem('meelyze.selected_allergen_ids', '[1,4]');
      }
      window.__locationCalls = 0;
      Object.defineProperty(navigator, 'geolocation', { configurable: true, value: mode === 'unsupported' ? undefined : {
        getCurrentPosition(success, failure) {
          window.__locationCalls += 1;
          if (mode === 'pending') { window.__lateLocation = () => success({ coords: { latitude: 35.68, longitude: 139.76 } }); return; }
          if (mode === 'denied') { failure({ code: 1 }); return; }
          if (mode === 'timeout') { failure({ code: 3 }); return; }
          success({ coords: { latitude: 35.68, longitude: 139.76 } });
        },
      }});
    }, { mode: options.location || 'success', loggedIn: options.loggedIn !== false });
    await context.route('**/*', async route => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.origin === new URL(baseUrl).origin) return route.continue();
      if (!url.pathname.startsWith('/api/v1/')) return route.abort();
      const headers = { 'access-control-allow-origin': new URL(baseUrl).origin, 'access-control-allow-headers': '*', 'access-control-allow-methods': 'GET,POST,OPTIONS' };
      if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers });
      requests.push({ path: url.pathname, query: url.searchParams, headers: request.headers(), body: request.postData() });
      if (url.pathname.endsWith('/places/nearby')) {
        if (options.networkFailure) return route.abort();
        return route.fulfill({ status: options.status || 200, headers, json: options.payload || { places, attribution: 'Google Maps' } });
      }
      if (url.pathname.endsWith('/menus/analyze')) return route.fulfill({ status: 201, headers, json: analysis });
      if (url.pathname.endsWith('/menus/test-menu')) return route.fulfill({ status: 200, headers, json: analysis });
      return route.abort();
    });
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    page.setDefaultTimeout(8000);
    try {
      await page.goto(baseUrl + (options.path || '/places/select'));
      await check(page, requests);
      assert.deepEqual(errors, []);
      completed += 1;
      console.log(`PASS ${name}`);
    } finally { await context.close(); }
  }
  const confirm = page => page.getByRole('button', { name: 'Confirm', exact: true });
  const skip = page => page.getByRole('button', { name: 'Skip', exact: true });
  const restaurant = page => page.getByRole('radio', { name: /Test Soba/ });
  const capture = page => page.waitForURL(url => url.pathname === '/capture');
  async function upload(page) {
    const image = await page.evaluate(() => {
      const canvas = document.createElement('canvas'); canvas.width = 200; canvas.height = 200;
      canvas.getContext('2d').fillRect(0, 0, 200, 200);
      return canvas.toDataURL('image/png').split(',')[1];
    });
    await page.locator('input[type=file]').last().setInputFiles({ name: 'test.png', mimeType: 'image/png', buffer: Buffer.from(image, 'base64') });
    await page.waitForURL(url => url.pathname === '/capture/preview');
    await page.getByRole('button', { name: /Analyze/ }).waitFor();
  }
  try {
    await run('FastAPI contract, explicit selection, preview and result Retake preserve restaurant', {}, async (page, requests) => {
      await restaurant(page).waitFor();
      assert.equal(await confirm(page).isDisabled(), true);
      assert.equal(requests.length, 1);
      assert.equal(requests[0].query.get('radius_m'), '500');
      assert.equal(requests[0].query.get('locale'), 'en');
      assert.equal(requests[0].headers.authorization, undefined);
      await restaurant(page).click();
      await confirm(page).click(); await capture(page);
      assert.equal(new URL(page.url()).searchParams.get('google_place_id'), 'test_restaurant_a');
      await upload(page);
      assert.equal(requests.filter(r => r.path.endsWith('/menus/analyze')).length, 0);
      await page.getByRole('button', { name: /Retake/ }).click(); await capture(page);
      assert.equal(new URL(page.url()).searchParams.get('google_place_id'), 'test_restaurant_a');
      await upload(page);
      await page.getByRole('button', { name: /Analyze/ }).click();
      await page.waitForURL(url => url.pathname === '/menu');
      const sent = requests.find(r => r.path.endsWith('/menus/analyze'));
      assert.ok(sent.body.includes('name="google_place_id"\r\n\r\ntest_restaurant_a'));
      assert.equal(sent.headers.authorization, 'Bearer test-account-token');
      await page.getByRole('button', { name: /Retake/ }).click(); await capture(page);
      assert.equal(new URL(page.url()).searchParams.get('google_place_id'), 'test_restaurant_a');
    });
    await run('Scan goes to selection; Skip clears old restaurant and omits it from Analyze', {}, async (page, requests) => {
      await restaurant(page).click(); await confirm(page).click(); await capture(page);
      await page.getByRole('button', { name: 'Scan', exact: true }).click();
      await page.waitForURL(url => url.pathname === '/places/select');
      await restaurant(page).waitFor();
      assert.equal(await confirm(page).isDisabled(), true);
      await skip(page).click(); await capture(page);
      assert.ok(!new URL(page.url()).searchParams.get('google_place_id'));
      for (const item of await page.getByText('Test Soba', { exact: true }).all()) assert.equal(await item.isVisible(), false);
      await upload(page);
      await page.getByRole('button', { name: /Retake/ }).click(); await capture(page);
      assert.ok(!new URL(page.url()).searchParams.get('google_place_id'));
      await upload(page); await page.getByRole('button', { name: /Analyze/ }).click();
      await page.waitForURL(url => url.pathname === '/menu');
      const sent = requests.find(r => r.path.endsWith('/menus/analyze'));
      assert.ok(!sent.body.includes('name="google_place_id"'));
    });
    for (const [mode, message] of [['denied', /Location access is denied/], ['timeout', /Location took too long/], ['unsupported', /Location is unavailable/]]) {
      await run(`Location ${mode}: no API request, Skip available`, { location: mode }, async (page, requests) => {
        await page.getByRole('alert').filter({ hasText: message }).waitFor();
        assert.equal(requests.length, 0);
        await skip(page).click(); await capture(page);
      });
    }
    await run('Skip during pending location ignores late callback', { location: 'pending' }, async (page, requests) => {
      await page.getByText('Finding your location…').waitFor();
      await skip(page).click(); await capture(page);
      await page.evaluate(() => window.__lateLocation());
      assert.equal(requests.length, 0);
      assert.equal(new URL(page.url()).pathname, '/capture');
    });
    for (const status of [429, 503]) {
      await run(`API ${status}: error, retry and Skip`, { status, payload: { error: { code: 'test', message: 'test' } } }, async page => {
        await page.getByRole('alert').waitFor(); await page.getByRole('button', { name: 'Try again' }).waitFor();
        await skip(page).click(); await capture(page);
      });
    }
    await run('Network failure: retry and Skip', { networkFailure: true }, async page => {
      await page.getByRole('alert').waitFor(); await skip(page).click(); await capture(page);
    });
    await run('Empty candidates: no automatic confirmation', { payload: { places: [], attribution: 'Google Maps' } }, async page => {
      await page.getByText(/No nearby restaurants found/).waitFor();
      assert.equal(await confirm(page).isDisabled(), true);
      await skip(page).click(); await capture(page);
    });
    await run('Malformed API response is rejected', { payload: { places: [{ name: 'Invalid' }], attribution: 'Google Maps' } }, async page => {
      await page.getByRole('alert').waitFor(); assert.equal(await confirm(page).isDisabled(), true);
    });
    // The name is handed over in memory only (task 03). A URL name is ignored, and after a reload the
    // candidate is shown as "Selected restaurant" instead of a possibly different restaurant's name.
    await run('Inherited restaurant requires confirmation and can be skipped', { path: '/places/select?google_place_id=test_restaurant_b&restaurant_name=Wrong%20Name' }, async (page, requests) => {
      await page.getByText('Selected restaurant', { exact: true }).waitFor();
      assert.equal(await page.getByText('Wrong Name').count(), 0);
      assert.equal(requests.length, 0);
      assert.equal(await page.evaluate(() => window.__locationCalls), 0);
      await skip(page).click(); await capture(page);
      assert.ok(!new URL(page.url()).searchParams.get('google_place_id'));
    });
    await run('Logged out: no location prompt or nearby API request', { loggedIn: false }, async (page, requests) => {
      await page.waitForURL(url => url.pathname === '/login');
      assert.equal(requests.length, 0);
      assert.equal(await page.evaluate(() => window.__locationCalls), 0);
    });
    console.log(`${completed} browser scenarios passed; external services were mocked.`);
  } finally { await browser.close(); }
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
