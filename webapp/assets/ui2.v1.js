/* Shared Progressor look for Gym Diary. It adds a home block above the day's exercises and a
   segmented control; routes, cards and every native handler stay the page's own. */
(() => {
  'use strict';
  const root = document.documentElement, key = 'progressor.ui', modulesKey = 'gym.ui2.modules';
  const el = (tag, props, ...children) => {
    const node = document.createElement(tag);
    for (const [name, value] of Object.entries(props || {})) { if (name.startsWith('on')) node.addEventListener(name.slice(2), value); else if (value != null && value !== false) node.setAttribute(name, value === true ? '' : value); }
    node.append(...children.filter(child => child != null));
    return node;
  };
  const go = route => { location.hash = '#' + route; };
  // Optional blocks. Only the workout of the day is always shown; the rest is the person's choice.
  const modules = [
    {id: 'week', title: 'Остаток недели', on: true},
    {id: 'volume', title: 'Объём за сегодня', on: false},
    {id: 'stats', title: 'Статистика упражнений', on: false, open: () => go('library')},
    {id: 'measure', title: 'Замеры тела', on: false, open: () => go('measurements')},
    {id: 'awards', title: 'Достижения', on: false, open: () => go('achievements')},
    {id: 'team', title: 'Команды', on: false, open: () => document.getElementById('drawerTeamsBtn')?.click()},
    {id: 'pace', title: 'Продуктивность', on: false, open: () => document.getElementById('productivityBtn')?.click()}];
  function enabled() {
    let saved = null; try { saved = JSON.parse(localStorage.getItem(modulesKey) || 'null'); } catch {}
    return new Set(Array.isArray(saved) ? saved.filter(id => modules.some(m => m.id === id)) : modules.filter(m => m.on).map(m => m.id));
  }
  function save(set) { try { localStorage.setItem(modulesKey, JSON.stringify([...set])); } catch {} }
  let built = false, home = null, seg = null, plan = null, shade = null, timer = 0;
  async function loadPlan() {
    try { const response = await fetch('/gymapi_prod/day/today', {cache: 'no-store'}); if (response.ok) plan = await response.json(); } catch {}
    paint();
  }
  function cards() {
    const list = [...document.querySelectorAll('#cards .exercise-card')];
    return {list, done: list.filter(card => card.classList.contains('is-done')).length};
  }
  function start() {
    const next = cards().list.find(card => !card.classList.contains('is-done')) || cards().list[0];
    if (!next) { go('settings'); return; }
    next.scrollIntoView({behavior: 'smooth', block: 'center'});
    if (!next.classList.contains('expanded')) next.click();
  }
  function closeSheet() { shade?.remove(); shade = null; }
  function openModules() {
    closeSheet();
    const set = enabled();
    const sheet = el('div', {class: 'u2-sheet', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Мой экран'}, el('h3', null, 'Мой экран'), el('p', null, 'Что показывать на главном экране зала.'),
      el('button', {type: 'button', class: 'u2-toggle', 'aria-pressed': 'true', disabled: true}, el('span', null, 'Тренировка дня'), el('span', null, 'всегда')),
      ...modules.map(module => {
        const button = el('button', {type: 'button', class: 'u2-toggle', 'aria-pressed': String(set.has(module.id)), onclick: () => {
          if (set.has(module.id)) set.delete(module.id); else set.add(module.id);
          save(set); button.setAttribute('aria-pressed', String(set.has(module.id))); button.lastChild.textContent = set.has(module.id) ? 'вкл' : 'выкл'; paint();
        }}, el('span', null, module.title), el('span', null, set.has(module.id) ? 'вкл' : 'выкл'));
        return button;
      }),
      el('button', {type: 'button', class: 'btn primary', style: 'width:100%;margin-top:14px', onclick: closeSheet}, 'Готово'));
    shade = el('div', {class: 'u2-shade', onclick: event => { if (event.target === shade) closeSheet(); }}, sheet);
    document.body.append(shade);
  }
  function paint() {
    if (!built) return;
    const route = (location.hash || '#today').slice(1);
    for (const button of seg.children) button.setAttribute('aria-pressed', String(button.dataset.route === route));
    const {list, done} = cards(), set = enabled();
    const days = plan?.active_days || [], finished = (plan?.completed_days || []).length;
    const label = document.getElementById('dayTitle')?.textContent.trim();
    const hero = el('div', {class: 'u2-hero'}, el('small', null, list.length ? 'Тренировка дня' : 'На этот день упражнений нет'),
      el('strong', null, list.length && label && label !== '—' ? label : 'Зал'),
      el('small', null, list.length ? `${done} из ${list.length} упражнений` : 'Начните свободную тренировку или настройте план'),
      el('div', {class: 'u2-bar'}, el('i', {style: `width:${list.length ? Math.round(done / list.length * 100) : 0}%`})),
      el('div', {class: 'u2-actions'}, list.length ? el('button', {type: 'button', onclick: start}, done && done < list.length ? 'Продолжить' : done ? 'Открыть' : 'Начать') : el('button', {type: 'button', onclick: () => go('allExercises')}, 'Свободная тренировка'),
        list.length ? el('button', {type: 'button', onclick: () => go('allExercises')}, 'Свободная') : el('button', {type: 'button', onclick: () => go('settings')}, 'План')));
    const blocks = [];
    for (const module of modules) {
      if (!set.has(module.id)) continue;
      if (module.id === 'week') { if (days.length) blocks.push(el('div', {class: 'u2-row tint'}, el('span', null, el('b', null, 'На этой неделе осталось'), el('small', null, `тренировочных дней в цикле: ${days.length}`)), el('em', null, `${Math.max(0, days.length - finished)} из ${days.length}`))); continue; }
      if (module.id === 'volume') { const text = document.getElementById('finishTotal')?.textContent.split(':')[1]?.trim(); blocks.push(el('div', {class: 'u2-row tint'}, el('span', null, el('b', null, 'Объём за сегодня')), el('em', null, text || '0 кг'))); continue; }
      blocks.push(el('button', {type: 'button', class: 'u2-row', onclick: module.open}, el('span', null, el('b', null, module.title)), el('span', {'aria-hidden': 'true'}, '›')));
    }
    home.replaceChildren(hero, ...blocks, el('button', {type: 'button', class: 'u2-add', onclick: openModules}, 'Настроить экран'));
  }
  const schedule = () => { clearTimeout(timer); timer = setTimeout(paint, 120); };
  function build() {
    if (built) return;
    const shell = document.getElementById('todayShell'), header = document.querySelector('.app-header');
    if (!shell || !header) return;
    built = true;
    seg = el('div', {class: 'u2-seg u2-only', role: 'group', 'aria-label': 'Разделы зала'}, ...[['today', 'Сегодня'], ['allExercises', 'Свободная'], ['library', 'Статистика'], ['measurements', 'Замеры'], ['settings', 'Настройки']].map(([route, label]) =>
      el('button', {type: 'button', 'data-route': route, 'aria-pressed': 'false', onclick: () => go(route)}, label)));
    header.append(seg);
    home = el('div', {class: 'u2-home u2-only'});
    shell.prepend(home);
    const list = document.getElementById('cards');
    if (list) new MutationObserver(schedule).observe(list, {childList: true, subtree: true, attributes: true, attributeFilter: ['class']});
    const title = document.getElementById('dayTitle');
    if (title) new MutationObserver(schedule).observe(title, {childList: true, characterData: true, subtree: true});
    window.addEventListener('hashchange', schedule);
    // The page follows Telegram's dark scheme; the shared look is light, so pin the page's own light rules.
    const pin = () => { if (root.dataset.pgUi === '2' && root.dataset.theme !== 'light') root.dataset.theme = 'light'; };
    new MutationObserver(pin).observe(root, {attributes: true, attributeFilter: ['data-theme']}); pin();
    paint(); void loadPlan();
  }
  function apply(on) {
    try { if (on) localStorage.setItem(key, '2'); else localStorage.removeItem(key); } catch {}
    if (on) { root.dataset.pgUi = '2'; build(); } else delete root.dataset.pgUi;
  }
  const ready = () => { if (root.dataset.pgUi === '2') build(); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready); else ready();
  Promise.resolve(window.Progressor?.ready).then(session => { if (session) apply(session.home === true); }).catch(() => {});
})();
