/* Run extracted, unmodified shipped functions against controlled native reads. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');
const sourcePath = process.env.GYM_PICKER_HTML || path.join(__dirname, '../webapp/index.html');
const html = fs.readFileSync(sourcePath, 'utf8');
function section(start, end) {
  const a = html.indexOf(start), b = html.indexOf(end, a);
  assert(a >= 0 && b > a, `Missing shipped source section: ${start}`);
  return html.slice(a, b);
}
const overlayListener = html.match(/^    document\.addEventListener\('progressor:overlay-open'.*$/m);
assert(overlayListener, 'Missing shipped Core overlay listener');
const source = section('    function applyRoute(route)', '    function navigateTo(') + '\n' +
  section('    async function loadSubscriptionOverview()', '    function renderSubscriptionScreen()') + '\n' +
  section('    function openPaywall(', '    async function startSubscriptionPayment(') + '\n' + overlayListener[0];
const plans = [
  {code: '1m', title: '1 месяц', amount_rub: 299, amount_stars: 230},
  {code: '6m', title: '6 месяцев', amount_rub: 1490, amount_stars: 1150},
  {code: '12m', title: '12 месяцев', amount_rub: 2490, amount_stars: 1900},
];
function fixture({cached = false, route = 'subscription'} = {}) {
  const classes = () => {
    const values = new Set();
    return {add: x => values.add(x), remove: x => values.delete(x), contains: x => values.has(x),
      toggle(x, on) { if (on) values.add(x); else values.delete(x); }};
  };
  const nodes = new Map(), listeners = new Map(), reads = [], payments = [], rendered = [];
  let coreOpen = false;
  function node(id) {
    if (!nodes.has(id)) nodes.set(id, {id, classList: classes(), innerHTML: '',
      querySelectorAll() {
        return [...this.innerHTML.matchAll(/data-plan-code="([^"]+)" data-payment-method="([^"]+)"/g)]
          .map(match => ({dataset: {planCode: match[1], paymentMethod: match[2]}, addEventListener() {}}));
      }});
    return nodes.get(id);
  }
  const state = {currentRoute: route, acting: {userId: null}, editor: {open: false}, manage: {mode: 'normal'},
    tour: {active: false}, uiCache: {screens: [], menuItems: []}, allExercises: {},
    settings: {measurements: {}, view: 'menu', trainer: {loading: false}, share: {loading: false}},
    subscription: {loading: false, plans: cached ? plans : [], payment: {}}, paywall: {open: false}};
  const noop = () => {};
  const context = {state, window: {Progressor: {refreshSurface: noop}},
    document: {body: {classList: classes()}, getElementById: node, querySelectorAll: () => [],
      querySelector: () => coreOpen ? node('core') : null,
      addEventListener(name, fn) { const list = listeners.get(name) || []; list.push(fn); listeners.set(name, list); }},
    ROUTE_TITLES: {today: 'Сегодня', subscription: 'Подписка', allExercises: 'Все упражнения'},
    flushInlineNumberInput: () => Promise.resolve(), renderSubscriptionScreen: () => rendered.push(state.currentRoute),
    updateDrawerSubscriptionStatus: noop, scheduleDeferredAction: noop,
    apiFetch(url, options) {
      assert.equal(url, '/gymapi/subscription/overview');
      assert.equal(options.silent, true); assert.equal(options.method, undefined);
      let resolve, reject;
      const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
      reads.push({url, resolve, reject}); return promise;
    },
    startSubscriptionPayment: (...args) => payments.push(args), runUiAction: (_label, action) => action(),
    navigateTo: noop, toast: noop, stopTour: noop,
  };
  for (const name of ['closeAllExerciseSheet', 'closeAllExercisesDonePopup', 'syncHeaderTitle',
    'syncAllExercisesHeaderButton', 'applyTitleFrame', 'setVisible', 'updateAddButtonVisibility',
    'closeEditor', 'closeManageAddSheet', 'setManageMenu', 'closeFinishPopover', 'setManageMode',
    'closeDrawer', 'updateSettingsAccess', 'updateCoachModeUI', 'updateBackButton', 'syncFinishFabVisibility']) context[name] = noop;
  vm.createContext(context); vm.runInContext(source, context, {filename: sourcePath});
  return {context, state, reads, payments, rendered, node,
    shown: () => node('planPickerSheet').classList.contains('show'),
    release(index = 0, value = plans) { reads[index].resolve({active: false, plans: value, features: []}); },
    setCore(value, dispatch = true) { coreOpen = value; if (value && dispatch) for (const fn of listeners.get('progressor:overlay-open') || []) fn({type: 'progressor:overlay-open'}); },
  };
}
function assertNormalPicker(f) {
  assert(f.shown(), 'Current picker should be shown');
  const content = f.node('planPickerContent').innerHTML;
  const buttons = f.node('planPickerContent').querySelectorAll('[data-plan-code]');
  assert.equal(buttons.length, 6);
  for (const plan of plans) {
    assert.equal(buttons.filter(x => x.dataset.planCode === plan.code && x.dataset.paymentMethod === 'rub').length, 1);
    assert.equal(buttons.filter(x => x.dataset.planCode === plan.code && x.dataset.paymentMethod === 'stars').length, 1);
    assert(content.includes(`${plan.amount_rub} ₽`)); assert(content.includes(`${plan.amount_stars} ⭐`));
  }
  assert(content.includes('1 месяц')); assert(content.includes('6 месяцев')); assert(content.includes('12 месяцев'));
  assert.equal(f.payments.length, 0, 'Opening the picker cannot start a payment');
}
test('cached native plans open synchronously with existing RUB/Stars pairs and no read/payment', async () => {
  const f = fixture({cached: true}); const work = f.context.openPlanPicker();
  assertNormalPicker(f); await work; assert.equal(f.reads.length, 0);
});
test('uncached current intent performs one unchanged native GET and opens normally on release', async () => {
  const f = fixture(); const work = f.context.openPlanPicker();
  assert.equal(f.reads.length, 1); assert.equal(f.shown(), false); f.release(); await work;
  assertNormalPicker(f); assert.equal(f.reads.length, 1);
});
test('leaving the origin route while the native GET waits prevents a picker over Today', async () => {
  const f = fixture(); const work = f.context.openPlanPicker(); f.context.applyRoute('today');
  assert.equal(f.state.currentRoute, 'today'); f.release(); await work;
  assert.equal(f.shown(), false); assert.equal(f.reads.length, 1); assert.equal(f.payments.length, 0);
  assert.equal(f.state.subscription.plans.length, 3, 'Cancellation leaves the ordinary read/cache completion intact');
});
test('leaving and returning before release cannot revive the previous opening', async () => {
  const f = fixture(); const work = f.context.openPlanPicker(); f.context.applyRoute('today'); f.context.applyRoute('subscription');
  f.release(); await work; assert.equal(f.shown(), false); assert.equal(f.state.currentRoute, 'subscription');
});
test('Close invalidates a queued opening even before its sheet exists', async () => {
  const f = fixture(); const work = f.context.openPlanPicker(); f.context.closePlanPicker(); f.release(); await work;
  assert.equal(f.shown(), false); assert.equal(f.reads.length, 1);
});
test('Core overlay opening invalidates the queued intent even if Core closes before release', async () => {
  const f = fixture(); const work = f.context.openPlanPicker(); f.setCore(true); f.setCore(false); f.release(); await work;
  assert.equal(f.shown(), false); assert.equal(f.payments.length, 0);
});
test('Core opening still stops the existing optional tour while cancelling a queued picker', async () => {
  const f = fixture(); let stopped = 0; f.state.tour.active = true;
  f.context.stopTour = () => { stopped += 1; f.state.tour.active = false; };
  const work = f.context.openPlanPicker(); f.setCore(true); f.release(); await work;
  assert.equal(stopped, 1); assert.equal(f.state.tour.active, false); assert.equal(f.shown(), false);
});
test('already visible Core prevents cached or delayed picker reveal without a payment', async () => {
  const cached = fixture({cached: true}); cached.setCore(true, false); await cached.context.openPlanPicker(); assert.equal(cached.shown(), false);
  const delayed = fixture(); const work = delayed.context.openPlanPicker(); delayed.setCore(true, false); delayed.release(); await work;
  assert.equal(delayed.shown(), false); assert.equal(delayed.reads.length, 1); assert.equal(delayed.payments.length, 0);
});
test('older response cannot replace a newer opening or revive it after the newer picker closes', async () => {
  const f = fixture(); const old = f.context.openPlanPicker(); const current = f.context.openPlanPicker();
  assert.equal(f.reads.length, 2, 'Keep each explicit opening own read; no transport abort/dedup introduced');
  f.release(1); await current; assertNormalPicker(f); f.context.closePlanPicker(); f.release(0); await old;
  assert.equal(f.shown(), false); assert.equal(f.payments.length, 0);
});
test('older read completion cannot replace the currently visible newer picker', async () => {
  const f = fixture(); const old = f.context.openPlanPicker(); const current = f.context.openPlanPicker();
  f.release(1); await current; const currentContent = f.node('planPickerContent').innerHTML;
  f.release(0, [{code: 'legacy', title: 'Superseded response', amount_rub: 1, amount_stars: 1}]); await old;
  assert.equal(f.shown(), true); assert.equal(f.node('planPickerContent').innerHTML, currentContent);
  assert.equal(f.reads.length, 2); assert.equal(f.payments.length, 0);
});
test('Core overlay closes a shown picker and a fresh explicit opening works after Core closes', async () => {
  const f = fixture({cached: true}); await f.context.openPlanPicker(); assertNormalPicker(f);
  f.setCore(true); assert.equal(f.shown(), false); f.setCore(false);
  await f.context.openPlanPicker(); assertNormalPicker(f); assert.equal(f.reads.length, 0);
});
test('cached paywall opening on Today keeps its ordinary origin route and paired plans', async () => {
  const f = fixture({cached: true, route: 'today'}); await f.context.openPlanPicker();
  assertNormalPicker(f); assert.equal(f.state.currentRoute, 'today'); assert.equal(f.reads.length, 0);
});
test('route cancellation closes an already shown picker and a fresh explicit opening still works', async () => {
  const f = fixture({cached: true}); await f.context.openPlanPicker(); assertNormalPicker(f);
  f.context.applyRoute('today'); assert.equal(f.shown(), false);
  f.context.applyRoute('subscription'); await f.context.openPlanPicker(); assertNormalPicker(f);
});
test('same-route rendering keeps a current pending intent and read failure retains normal unavailable state', async () => {
  const f = fixture(); const work = f.context.openPlanPicker(); f.context.applyRoute('subscription'); f.release(); await work; assertNormalPicker(f);
  const failed = fixture(); const unavailable = failed.context.openPlanPicker(); failed.reads[0].reject(new Error('synthetic unavailable')); await unavailable;
  assert.equal(failed.shown(), true); assert(failed.node('planPickerContent').innerHTML.includes('Тарифы недоступны'));
  assert.equal(failed.state.subscription.loading, false); assert.equal(failed.reads.length, 1); assert.equal(failed.payments.length, 0);
});
