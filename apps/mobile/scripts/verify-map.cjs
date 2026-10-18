// Browser checks for ⑥ map and ⑦ shared menu sheet. Run against `expo serve` after build:web.
// Google Maps is replaced by a fake SDK and FastAPI is mocked; every other external request is blocked.
// MAP_BUILD=test-key: build with EXPO_PUBLIC_GOOGLE_MAPS_BROWSER_API_KEY=test-browser-key (map scenarios).
// MAP_BUILD=keyless: build without the key (map-not-configured scenario only).
// PLAYWRIGHT_MODULE_PATH may point to an already installed Playwright package.
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const baseUrl = process.env.TEST_BASE_URL || 'http://localhost:8094';
const build = process.env.MAP_BUILD || 'test-key';

const places = [
  { google_place_id: 'test_restaurant_a', name: 'Test Soba', latitude: 35.68, longitude: 139.76, address: 'Test address A', distance_m: 42, has_public_menus: false, public_menu_count: 0 },
  { google_place_id: 'test_restaurant_b', name: 'Test Cafe', latitude: 35.681, longitude: 139.761, address: 'Test address B', distance_m: 84, has_public_menus: true, public_menu_count: 2 },
];
const history = (counts, score, dates = {}) => ({
  match_basis: 'name_key', last_confirmed_at: '2026-10-10T03:00:00Z', alpha: 1 + counts.contains, beta: 1 + counts.does_not_contain, score,
  has_conflict: counts.contains > 0 && counts.does_not_contain > 0, answer_counts: counts,
  last_answered_at: { contains: null, shared_utensils: null, does_not_contain: null, unknown: null, ...dates },
});
const allergen = (id, name, ai, storeHistory, notices = {}) => ({
  allergen_id: id, display_name: name, ai: { weight: null, ...ai }, store_history: storeHistory,
  notices: { history_conflict: false, history_shared_utensils: false, ...notices },
});
const dish = (key, extra = {}) => ({
  name_key: key, name: `${key}（原文）`, display_name: `${key} EN`, description: 'AI description of the dish', price: 1200, currency: 'JPY',
  allergens: [
    allergen(1, 'Egg', { status: 'unknown', source: 'unavailable', evidence: '' }, null),
    allergen(4, 'Shrimp', { status: 'explicit_present', source: 'menu_text', evidence: '海老' },
      history({ contains: 2, shared_utensils: 1, does_not_contain: 1, unknown: 1 }, 0.6,
        { contains: '2026-10-10T03:00:00Z', does_not_contain: '2026-10-01T03:00:00Z' }),
      { history_conflict: true, history_shared_utensils: true }),
  ],
  dietary_restrictions: [], ...extra,
});
const publicMenus = (placeId, dishes) => ({ google_place_id: placeId, match_basis: 'name_key', staff_answers_verified: false, dishes });
const cafeMenus = publicMenus('test_restaurant_b', [
  dish('tempura-soba'),
  dish('kake-soba', { price: null, allergens: [allergen(1, 'Egg', { status: 'possible', source: 'recipe_inference', evidence: 'often contains egg' },
    history({ contains: 0, shared_utensils: 0, does_not_contain: 0, unknown: 2 }, null, { unknown: '2026-10-09T00:00:00Z' })),
  allergen(4, 'Shrimp', { status: 'unknown', source: 'unavailable', evidence: '' }, null)] }),
  dish('zaru-soba', { display_name: '', allergens: [] }),
]);

// The fake SDK mirrors the parts of the real API the app uses: callback loading, importLibrary,
// Map, AdvancedMarkerElement (a custom element with title, gmpClickable and gmp-click), and gm_authFailure.
const fakeSdk = mode => `(() => {
  const params = new URL(document.currentScript.src).searchParams;
  window.__sdk = window.__sdk || { scripts: 0, maps: 0, pans: 0, listeners: 0 };
  window.__sdk.scripts += 1;
  window.__sdk.keyParam = params.get('key');
  class FakeMap {
    constructor(element, options) {
      window.__sdk.maps += 1; window.__sdk.options = options;
      this.layer = document.createElement('div'); this.layer.className = 'fake-map'; element.appendChild(this.layer);
    }
    panTo() { window.__sdk.pans += 1; }
    setCenter() {}
  }
  class FakeMarker extends HTMLElement {
    constructor(options = {}) {
      super();
      this.className = 'fake-marker';
      for (const [key, value] of Object.entries(options)) this[key] = value;
      this.addEventListener('click', () => this.dispatchEvent(new Event('gmp-click')));
      this.addEventListener('keydown', event => { if (event.key === 'Enter') this.dispatchEvent(new Event('gmp-click')); });
    }
    set map(map) { this._map = map; if (map) map.layer.appendChild(this); else this.remove(); }
    get map() { return this._map || null; }
    set title(value) { this._title = value; this.setAttribute('title', value); this.setAttribute('aria-label', value); }
    get title() { return this._title || ''; }
    set gmpClickable(value) { if (value) { this.setAttribute('role', 'button'); this.tabIndex = 0; } }
    set content(node) { this.replaceChildren(node); }
    get content() { return this.firstChild; }
    addEventListener(type, listener, options) { if (type === 'gmp-click') window.__sdk.listeners += 1; super.addEventListener(type, listener, options); }
    removeEventListener(type, listener, options) { if (type === 'gmp-click') window.__sdk.listeners -= 1; super.removeEventListener(type, listener, options); }
  }
  if (!customElements.get('fake-marker')) customElements.define('fake-marker', FakeMarker);
  window.google = { maps: { importLibrary: async name => name === 'maps' ? { Map: FakeMap } : { AdvancedMarkerElement: customElements.get('fake-marker') } } };
  window[params.get('callback')]();
  ${mode === 'auth' ? "setTimeout(() => window.gm_authFailure && window.gm_authFailure(), 50);" : ''}
})();`;

(async () => {
  const browser = await chromium.launch({ headless: true });
  let completed = 0;
  async function run(name, options, check) {
    if ((options.build || 'test-key') !== build) return;
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const requests = [];
    const errors = [];
    const sdkMode = { value: options.sdk || 'ok' };
    await context.addInitScript(({ mode, loggedIn, allergens }) => {
      localStorage.setItem('meelyze.walkthrough.seen', '1');
      if (loggedIn) {
        sessionStorage.setItem('meelyze.account_token', 'test-account-token');
        sessionStorage.setItem('meelyze.account_token_expires_at', '2099-01-01T00:00:00Z');
        if (allergens) sessionStorage.setItem('meelyze.selected_allergen_ids', allergens);
      }
      window.__locationCalls = 0;
      Object.defineProperty(navigator, 'geolocation', { configurable: true, value: {
        getCurrentPosition(success, failure) {
          window.__locationCalls += 1;
          if (mode === 'denied') { failure({ code: 1 }); return; }
          success({ coords: { latitude: 35.68, longitude: 139.76 } });
        },
      } });
    }, { mode: options.location || 'success', loggedIn: options.loggedIn !== false, allergens: options.allergens === undefined ? '[4,1]' : options.allergens });
    await context.route('**/*', async route => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.origin === new URL(baseUrl).origin) return route.continue();
      if (url.hostname === 'maps.googleapis.com' && url.pathname === '/maps/api/js') {
        requests.push({ path: 'maps-sdk', query: url.searchParams, headers: request.headers() });
        if (sdkMode.value === 'fail') return route.abort();
        return route.fulfill({ status: 200, contentType: 'text/javascript', body: fakeSdk(sdkMode.value) });
      }
      if (!url.pathname.startsWith('/api/v1/')) return route.abort();
      const headers = { 'access-control-allow-origin': new URL(baseUrl).origin, 'access-control-allow-headers': '*', 'access-control-allow-methods': 'GET,POST,OPTIONS' };
      if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers });
      requests.push({ path: url.pathname, query: url.searchParams, headers: request.headers() });
      if (url.pathname.endsWith('/places/nearby')) {
        const count = requests.filter(r => r.path.endsWith('/places/nearby')).length;
        const payload = (options.nearby && options.nearby(count)) || { places, attribution: 'Google Maps' };
        return route.fulfill({ status: 200, headers, json: payload });
      }
      const match = url.pathname.match(/\/places\/([^/]+)\/public-menus$/);
      if (match) {
        const placeId = decodeURIComponent(match[1]);
        const reply = options.publicMenus ? options.publicMenus(placeId) : { json: placeId === 'test_restaurant_b' ? cafeMenus : publicMenus(placeId, []) };
        if (reply.delay) await new Promise(resolve => setTimeout(resolve, reply.delay));
        return route.fulfill({ status: reply.status || 200, headers, json: reply.json }).catch(() => undefined);
      }
      return route.abort();
    });
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    page.setDefaultTimeout(8000);
    try {
      await page.goto(baseUrl + (options.path || '/map'));
      await check(page, requests, sdkMode);
      assert.deepEqual(errors, []);
      completed += 1;
      console.log(`PASS ${name}`);
    } finally { await context.close(); }
  }
  const pins = page => page.locator('.fake-map fake-marker[role=button]');
  const pin = (page, name) => page.locator(`.fake-map fake-marker[role=button][title^="${name},"]`);
  const sheet = page => page.getByRole('dialog');
  const nearbyCount = requests => requests.filter(r => r.path.endsWith('/places/nearby')).length;
  const menuRequests = requests => requests.filter(r => r.path.endsWith('/public-menus'));
  const noHorizontalOverflow = async page => assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));

  try {
    await run('Keyless build: map not configured, list and sheet still work, no SDK request', { build: 'keyless' }, async (page, requests) => {
      await page.getByText(/The map is not set up in this build/).waitFor();
      await page.getByRole('button', { name: /Test Cafe, 2 shared dishes/ }).click();
      await sheet(page).getByText('tempura-soba EN').waitFor();
      assert.equal(requests.filter(r => r.path === 'maps-sdk').length, 0);
    });

    await run('Map, pins, and the shared menu table', {}, async (page, requests) => {
      await pins(page).nth(1).waitFor();
      assert.equal(await pins(page).count(), 2);
      assert.equal(await page.locator('.fake-map fake-marker[title="Your location"]').count(), 1);
      assert.equal(await pin(page, 'Test Cafe').innerText(), '2');
      assert.equal(await pin(page, 'Test Cafe').getAttribute('title'), 'Test Cafe, 2 shared dishes');
      assert.equal(await pin(page, 'Test Soba').getAttribute('title'), 'Test Soba, no shared menus yet');
      const sdk = await page.evaluate(() => window.__sdk);
      assert.equal(sdk.scripts, 1); assert.equal(sdk.maps, 1); assert.equal(sdk.keyParam, 'test-browser-key');
      assert.equal(sdk.options.zoom, 15); assert.ok(sdk.options.mapId);
      assert.equal(sdk.options.disableDefaultUI, true); assert.equal(sdk.options.zoomControl, true);
      assert.equal(sdk.options.streetViewControl, false); assert.equal(sdk.options.clickableIcons, false);
      assert.equal(nearbyCount(requests), 1);
      const nearby = requests.find(r => r.path.endsWith('/places/nearby'));
      assert.equal(nearby.query.get('radius_m'), '500'); assert.equal(nearby.headers.authorization, undefined);
      assert.equal(menuRequests(requests).length, 0, 'no prefetch of shared menus');
      assert.equal(await page.getByRole('button', { name: /Test Cafe, 2 shared dishes, 84 metres away/ }).count(), 0, 'no list under a working map');
      const layout = await page.evaluate(() => ({ map: document.querySelector('[aria-label="Map of nearby restaurants"]').getBoundingClientRect().bottom,
        footer: document.querySelector('nav[aria-label="Main navigation"]').getBoundingClientRect().top }));
      assert.ok(Math.abs(layout.footer - layout.map) <= 2, `map fills down to the footer (${layout.map} vs ${layout.footer})`);
      await page.getByRole('button', { name: 'Reload nearby restaurants' }).waitFor();

      await pin(page, 'Test Cafe').click();
      const dialog = sheet(page);
      await dialog.getByText('tempura-soba EN').waitFor();
      const sent = menuRequests(requests);
      assert.equal(sent.length, 1);
      assert.equal(sent[0].path, '/api/v1/places/test_restaurant_b/public-menus');
      assert.equal(sent[0].query.get('allergen_ids'), '1,4');
      assert.equal(sent[0].query.get('locale'), 'en');
      assert.equal(sent[0].query.get('dietary_restriction_ids'), null);
      assert.equal(sent[0].headers.authorization, undefined);
      // Count follows the fetched dishes (3), not the earlier nearby count (2).
      await dialog.getByText('3 shared dishes').waitFor();
      assert.equal(await dialog.locator('table tbody').count(), 3);
      for (const header of ['Dish', 'Price', 'AI estimate', 'Public staff answers', 'Notes']) {
        await dialog.getByRole('columnheader', { name: header }).waitFor();
      }
      const text = await dialog.innerText();
      for (const expected of ['tempura-soba（原文）', '¥1,200', 'Not listed', 'Listed on menu', 'From the menu text', 'Evidence: “海老”',
        'No public staff answers for this item.', 'Contains: 2', 'Shared utensils: 1', 'Does not contain: 1', 'Unknown: 1',
        'History index 0.60', 'No Contains / Does not contain answers yet', 'Staff answers disagree', 'Shared utensils were reported.',
        'Some staff answered Unknown.', 'No information. This does not mean it is absent.', 'not verified', 'AI-generated description',
        'Google Maps', 'No selected allergens to show for this dish.', 'zaru-soba（原文）']) {
        assert.ok(text.includes(expected), `missing: ${expected}`);
      }
      for (const forbidden of [/\bsafe\b/i, /verified by/i, /official/i, /0%/]) assert.ok(!forbidden.test(text), `forbidden: ${forbidden}`);
      await noHorizontalOverflow(page);
      await page.keyboard.press('Escape');
      await sheet(page).waitFor({ state: 'detached' });
      // Re-opening fetches again with the latest settings.
      await page.evaluate(() => sessionStorage.setItem('meelyze.selected_allergen_ids', '[7]'));
      await pin(page, 'Test Cafe').click();
      await sheet(page).getByText('tempura-soba EN').waitFor();
      assert.equal(menuRequests(requests).at(-1).query.get('allergen_ids'), '7');
      assert.equal(await page.evaluate(() => window.__sdk.maps), 1, 'sheet open/close does not recreate the map');
    });

    await run('Pin A then B quickly: only B is shown; closing while loading stays closed', {
      publicMenus: id => id === 'test_restaurant_a' ? { delay: 1200, json: publicMenus(id, [dish('late-a')]) } : { json: cafeMenus },
    }, async (page, requests) => {
      await pin(page, 'Test Soba').waitFor();
      await pin(page, 'Test Soba').click();
      await sheet(page).getByText('Loading shared menus…').waitFor();
      await page.keyboard.press('Escape');
      await sheet(page).waitFor({ state: 'detached' });
      await pin(page, 'Test Cafe').click();
      await sheet(page).getByText('tempura-soba EN').waitFor();
      await page.waitForTimeout(1500);
      assert.equal(await sheet(page).getByText('late-a EN').count(), 0);
      assert.equal(await sheet(page).getByRole('heading', { name: 'Test Cafe' }).count(), 1);
      await page.keyboard.press('Escape');
      await pin(page, 'Test Soba').click();
      await sheet(page).getByText('Loading shared menus…').waitFor();
      await page.keyboard.press('Escape');
      await page.waitForTimeout(1500);
      assert.equal(await sheet(page).count(), 0, 'a late response does not reopen the sheet');
      assert.equal(menuRequests(requests).length, 3);
    });

    await run('Keyboard: Enter on a pin opens the sheet, Escape closes and returns focus', {}, async page => {
      await pin(page, 'Test Cafe').waitFor();
      await pin(page, 'Test Cafe').focus();
      await page.keyboard.press('Enter');
      await sheet(page).getByText('tempura-soba EN').waitFor();
      assert.equal(await sheet(page).getAttribute('aria-label'), 'Test Cafe shared menus');
      await page.keyboard.press('Escape');
      await sheet(page).waitFor({ state: 'detached' });
      await page.waitForFunction(() => document.activeElement?.getAttribute('title') === 'Test Cafe, 2 shared dishes');
    });

    await run('Restaurant without shared menus: empty state, Scan hands the candidate to ⑧ for Confirm', {}, async (page, requests) => {
      await pin(page, 'Test Soba').click();
      await sheet(page).getByText('No shared menus yet.').waitFor();
      await sheet(page).getByRole('button', { name: 'Scan the menu at this restaurant' }).click();
      await page.waitForURL(url => url.pathname === '/places/select');
      const url = new URL(page.url());
      assert.equal(url.searchParams.get('google_place_id'), 'test_restaurant_a');
      assert.equal(url.searchParams.get('restaurant_name'), null, 'no name in the URL');
      assert.ok(!url.search.includes('35.68'), 'no coordinates in the URL');
      await page.getByText('Test Soba', { exact: true }).waitFor();
      await page.getByText('Google Maps').waitFor();
      const before = nearbyCount(requests);
      await page.getByRole('button', { name: 'Confirm', exact: true }).click();
      await page.waitForURL(url => url.pathname === '/capture');
      assert.equal(new URL(page.url()).searchParams.get('google_place_id'), 'test_restaurant_a');
      await page.getByText('Test Soba', { exact: true }).filter({ visible: true }).waitFor();
      assert.equal(nearbyCount(requests), before, '⑧ does not search again for a handed-over candidate');
      const stored = await page.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }));
      assert.ok(!stored.includes('Test Soba') && !stored.includes('35.68'), 'no restaurant data in storage');
    });

    await run('Reload and recenter: explicit search only, no duplicate pins or listeners', {
      nearby: count => count >= 2 ? { places: [places[1], { ...places[0], google_place_id: 'test_restaurant_c', name: 'Test Ramen' }], attribution: 'Google Maps' } : null,
    }, async (page, requests) => {
      await pins(page).nth(1).waitFor();
      await page.getByRole('button', { name: 'Back to my location' }).click();
      await page.waitForTimeout(300);
      assert.equal(nearbyCount(requests), 1, 'recenter does not search');
      await page.getByRole('button', { name: 'Reload nearby restaurants' }).click();
      await pin(page, 'Test Ramen').waitFor();
      assert.equal(nearbyCount(requests), 2, 'reload searches once');
      assert.equal(await page.evaluate(() => window.__locationCalls), 2, 'reload takes a fresh location');
      assert.equal(await pin(page, 'Test Soba').count(), 0, 'stale pin removed');
      assert.equal(await pins(page).count(), 2);
      assert.equal(await page.evaluate(() => window.__sdk.listeners), 2);
      assert.equal(await page.locator('.fake-map fake-marker[title="Your location"]').count(), 1);
      await page.getByRole('button', { name: 'Reload nearby restaurants' }).click();
      await page.waitForFunction(() => window.__locationCalls === 3);
      await page.waitForFunction(() => document.querySelectorAll('.fake-map fake-marker[role=button]').length === 2);
      assert.equal(nearbyCount(requests), 3, 'each reload searches once');
      assert.equal(await page.evaluate(() => window.__sdk.maps), 1);
    });

    await run('Location denied: no search or map, Scan still works, no automatic re-prompt', { location: 'denied' }, async (page, requests) => {
      await page.getByRole('alert').filter({ hasText: /Current location is unavailable: location access is denied/ }).waitFor();
      await page.getByText('Current location is unavailable, so the map is not shown.').waitFor();
      assert.equal(nearbyCount(requests), 0);
      await page.getByRole('button', { name: 'Profile', exact: true }).click();
      await page.waitForURL(url => url.pathname === '/profiles');
      await page.getByRole('button', { name: 'Map', exact: true }).click();
      await page.waitForURL(url => url.pathname === '/map');
      await page.getByRole('alert').filter({ hasText: /location access is denied/ }).waitFor();
      assert.equal(await page.evaluate(() => window.__locationCalls), 1, 'not asked again automatically');
      await page.getByRole('button', { name: 'Reload nearby restaurants' }).click();
      await page.waitForFunction(() => window.__locationCalls === 2);
      await page.getByRole('button', { name: 'Scan', exact: true }).click();
      await page.waitForURL(url => url.pathname === '/places/select');
    });

    await run('SDK load failure recovers with Retry map', { sdk: 'fail' }, async (page, requests, sdkMode) => {
      await page.getByText(/The map could not be loaded/).waitFor();
      await page.getByRole('button', { name: /Test Cafe/ }).waitFor();
      sdkMode.value = 'ok';
      await page.getByRole('button', { name: 'Retry map' }).click();
      await pins(page).nth(1).waitFor();
      assert.equal(await page.getByRole('button', { name: /Test Cafe, 2 shared dishes, 84 metres away/ }).count(), 0, 'fallback list hidden once the map shows');
      assert.equal(requests.filter(r => r.path === 'maps-sdk').length, 2);
      assert.equal(await page.locator('script[src*="maps.googleapis.com"]').count(), 1, 'failed script removed');
    });

    await run('SDK auth failure shows a settings message and keeps the list usable', { sdk: 'auth' }, async page => {
      await page.getByText(/The map could not be authorised/).waitFor();
      assert.equal(await page.getByRole('button', { name: 'Retry map' }).count(), 0);
      await page.getByRole('button', { name: /Test Soba/ }).click();
      await sheet(page).getByText('No shared menus yet.').waitFor();
    });

    await run('Public API 429: error, retry disabled, no automatic resend', {
      publicMenus: () => ({ status: 429, json: { error: { code: 'rate_limited', message: 'test' } } }),
    }, async (page, requests) => {
      await pin(page, 'Test Cafe').click();
      await sheet(page).getByRole('alert').filter({ hasText: /Too many requests/ }).waitFor();
      assert.equal(await sheet(page).getByRole('button', { name: 'Try again' }).isDisabled(), true);
      await page.waitForTimeout(800);
      assert.equal(menuRequests(requests).length, 1);
    });

    for (const [label, reply, message] of [
      ['503', { status: 503, json: { error: { code: 'service_unavailable', message: 'x' } } }, /unavailable right now/],
      ['mismatched place ID', { json: publicMenus('other_place', []) }, /incomplete/],
      ['invalid dish', { json: publicMenus('test_restaurant_b', [{ name_key: 'x' }]) }, /incomplete/],
    ]) {
      await run(`Public API ${label}: error with manual retry`, { publicMenus: () => reply }, async (page, requests) => {
        await pin(page, 'Test Cafe').click();
        await sheet(page).getByRole('alert').filter({ hasText: message }).waitFor();
        await sheet(page).getByRole('button', { name: 'Try again' }).click();
        await page.waitForFunction(() => true);
        await sheet(page).getByRole('alert').waitFor();
        assert.equal(menuRequests(requests).length, 2);
      });
    }

    await run('No allergen selection: no public request, guided to Profile', { allergens: null }, async (page, requests) => {
      await pin(page, 'Test Cafe').click();
      await sheet(page).getByRole('button', { name: 'Choose allergens' }).click();
      await page.waitForURL(url => url.pathname === '/profiles/edit');
      assert.equal(menuRequests(requests).length, 0);
    });

    await run('More than 20 shared dishes are all listed in API order', {
      publicMenus: id => ({ json: publicMenus(id, Array.from({ length: 22 }, (_, i) => dish(`dish-${String(i).padStart(2, '0')}`))) }),
    }, async page => {
      await pin(page, 'Test Cafe').click();
      await sheet(page).getByText('22 shared dishes').waitFor();
      assert.equal(await sheet(page).locator('table tbody').count(), 22);
      const first = await sheet(page).locator('table tbody th').first().innerText();
      const last = await sheet(page).locator('table tbody th').last().innerText();
      assert.ok(first.startsWith('dish-00 EN') && last.startsWith('dish-21 EN'));
      await noHorizontalOverflow(page);
    });

    await run('Logged out: no location, SDK, or API request', { loggedIn: false }, async (page, requests) => {
      await page.waitForURL(url => url.pathname === '/login');
      await page.waitForTimeout(300);
      assert.equal(requests.length, 0);
      assert.equal(await page.evaluate(() => window.__locationCalls), 0);
    });

    console.log(`${completed} map scenarios passed (${build} build); Google Maps and FastAPI were mocked.`);
  } finally { await browser.close(); }
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
