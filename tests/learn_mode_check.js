// Package-free browser behavior checks for the shared progressive enhancement.
const assert = require('node:assert/strict');
const { createHash, webcrypto } = require('node:crypto');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const script = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
const helpers = require('../app.js');

class Node {
  constructor(tag, className = '', text = '') {
    this.tagName = tag.toLowerCase();
    this.className = className;
    this._text = text;
    this.children = [];
    this.parentElement = null;
    this.dataset = {};
    this.attributes = {};
    this.listeners = {};
    this.hidden = false;
  }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this._text = String(value); this.children = []; }
  get previousElementSibling() {
    if (!this.parentElement) return null;
    return this.parentElement.children[this.parentElement.children.indexOf(this) - 1] || null;
  }
  get classList() {
    return {
      add: name => { this.className = [...new Set([...this.className.split(' '), name])].join(' ').trim(); },
      toggle: (name, force) => {
        const names = new Set(this.className.split(' ').filter(Boolean));
        if (force) names.add(name); else names.delete(name);
        this.className = [...names].join(' ');
      },
    };
  }
  append(...nodes) {
    for (let node of nodes) {
      if (typeof node === 'string') node = new Node('#text', '', node);
      if (node.parentElement) node.parentElement.children.splice(node.parentElement.children.indexOf(node), 1);
      node.parentElement = this;
      this.children.push(node);
    }
  }
  insert(next, node) {
    if (node.parentElement) node.parentElement.children.splice(node.parentElement.children.indexOf(node), 1);
    node.parentElement = this;
    this.children.splice(this.children.indexOf(next), 0, node);
  }
  before(node) { this.parentElement.insert(this, node); }
  after(node) {
    const parent = this.parentElement;
    const index = parent.children.indexOf(this);
    if (node.parentElement) node.parentElement.children.splice(node.parentElement.children.indexOf(node), 1);
    node.parentElement = parent;
    parent.children.splice(index + 1, 0, node);
  }
  matches(selector) {
    if (selector.startsWith('.')) return this.className.split(' ').includes(selector.slice(1));
    return this.tagName === selector;
  }
  querySelector(selector) {
    if (selector === 'h2 a') return this.querySelector('h2')?.querySelector('a') || null;
    for (const child of this.children) {
      if (child.matches(selector)) return child;
      const found = child.querySelector(selector);
      if (found) return found;
    }
    return null;
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  getAttribute(name) { return this.attributes[name]; }
  addEventListener(name, handler) { (this.listeners[name] ||= []).push(handler); }
  async fire(name) { for (const handler of this.listeners[name] || []) await handler(); }
  select() { this.selected = true; }
}

function makeStory() {
  const story = new Node('article', 'story');
  story.dataset.category = 'Energy & Power Markets';
  const heading = new Node('h2');
  const title = new Node('a', '', 'Grid storage helps balance supply');
  title.href = 'https://example.com/grid?a=1&b=2';
  heading.append(title);
  const description = new Node('p', 'description',
    'Flexible storage helps balance electricity supply. The post Grid storage appeared first on Example News.');
  const meta = new Node('div', 'meta');
  meta.append(new Node('span', '', 'Example News'), new Node('time', '', '2026-10-10'));
  const read = new Node('a', '', 'Read original ↗');
  read.href = title.href;
  meta.append(read);
  story.append(heading, description, meta);
  return { story, title, description, meta, read };
}

function runPage(options = {}) {
  const card = makeStory();
  const filter = new Node('button', 'filter');
  filter.dataset.filter = 'AI & Technology';
  const noResults = new Node('p');
  const theme = new Node('button');
  const storage = options.storage || {
    getItem: key => options.values?.get(key) || null,
    setItem: (key, value) => options.values?.set(key, value),
  };
  const document = {
    documentElement: { dataset: {} },
    querySelectorAll: selector => selector === '.story' ? [card.story] : [filter],
    getElementById: id => id === 'theme' ? theme : noResults,
    createElement: tag => {
      if (options.failEnhancement) throw new Error('simulated Learn Mode failure');
      return new Node(tag);
    },
    execCommand: () => false,
  };
  const copied = [];
  const opened = [];
  const window = {
    localStorage: storage,
    matchMedia: () => ({ matches: false }),
    open: url => { opened.push(url); return options.popupBlocked ? null : {}; },
  };
  const navigator = {
    clipboard: options.clipboardBlocked ? { writeText: async () => { throw Error('blocked'); } } :
      { writeText: async value => { copied.push(value); } },
  };
  vm.runInNewContext(script, { document, window, navigator, crypto: webcrypto, TextEncoder, module: undefined });
  return { ...card, filter, noResults, copied, opened };
}

async function main() {
  const url = 'https://example.com/grid?a=1&b=2';
  const id = createHash('sha256').update(url).digest('hex').slice(0, 16);
  assert.equal(await helpers.stableId({ dataset: {} }, url), id);
  assert.equal(helpers.cleanExcerpt('A complete account explains the grid problem. The post Grid appeared first on Example.'),
    'A complete account explains the grid problem.');
  assert.equal(helpers.cleanExcerpt('A short teaser that trails off...'),
    'Open the original article for the full report.');
  const values = new Map();
  assert.equal(helpers.saveAnswer({ setItem: (key, value) => values.set(key, value) }, id, 'My answer'), true);
  assert.equal(helpers.readAnswer({ getItem: key => values.get(key) }, id).value, 'My answer');
  assert.equal(helpers.saveAnswer({ setItem: () => { throw Error('blocked'); } }, id, 'x'), false);
  assert.equal(helpers.readAnswer({ getItem: () => { throw Error('blocked'); } }, id).available, false);
  assert.equal(await helpers.copyPrompt({ writeText: async () => { throw Error('blocked'); } }, 'prompt'), false);
  assert.match(helpers.buildPrompt({ title: 'T', url, publisher: 'P', excerpt: 'E', answer: '' }), /No explanation yet/);

  const page = runPage({ values });
  await new Promise(resolve => setTimeout(resolve, 30));
  const { story, meta, description, read } = page;
  const panel = story.querySelector('.learn-panel');
  const toggle = story.querySelector('.learn-toggle');
  assert.ok(panel && toggle);
  assert.equal(panel.hidden, true);
  assert.ok(story.children.indexOf(meta) < story.children.indexOf(description));
  assert.equal(read.textContent, 'Read article ↗');
  assert.equal(read.target, '_blank');
  assert.equal(read.href, url);
  assert.equal(panel.querySelector('textarea').value, 'My answer');
  await toggle.fire('click');
  assert.equal(panel.hidden, false);
  assert.equal(toggle.getAttribute('aria-expanded'), 'true');
  const answer = panel.querySelector('.learn-answer');
  answer.value = 'Storage smooths variable supply.';
  await answer.fire('input');
  assert.equal(values.get(`the-edge-answer:${id}`), answer.value);
  await panel.querySelector('.discuss-button').fire('click');
  assert.equal(page.opened[0], 'https://chatgpt.com/');
  assert.match(page.copied[0], /Storage smooths variable supply/);
  assert.match(page.copied[0], /central problem/);
  assert.match(page.copied[0], /ONE thoughtful follow-up question/);
  assert.match(page.copied[0], /https:\/\/example.com\/grid\?a=1&b=2/);
  await page.filter.fire('click');
  assert.equal(story.hidden, true);
  assert.equal(page.noResults.hidden, false);

  const archive = runPage({ values }); // Same article on another edition uses the same stable key.
  await new Promise(resolve => setTimeout(resolve, 30));
  assert.equal(archive.story.querySelector('.learn-answer').value, 'Storage smooths variable supply.');

  const blocked = runPage({
    storage: { getItem: () => { throw Error('blocked'); }, setItem: () => { throw Error('blocked'); } },
    clipboardBlocked: true,
    popupBlocked: true,
  });
  await new Promise(resolve => setTimeout(resolve, 30));
  const blockedPanel = blocked.story.querySelector('.learn-panel');
  assert.match(blockedPanel.querySelector('.learn-note').textContent, /unavailable/);
  await blockedPanel.querySelector('.learn-answer').fire('input');
  await blockedPanel.querySelector('.discuss-button').fire('click');
  assert.ok(blockedPanel.querySelector('.prompt-fallback'));
  assert.match(blockedPanel.querySelector('.prompt-text').value, /Example News/);
  assert.equal(blocked.story.querySelector('.read-link').href, url);

  const broken = runPage({ failEnhancement: true });
  await new Promise(resolve => setTimeout(resolve, 30));
  assert.equal(broken.read.parentElement, broken.meta);
  assert.equal(broken.title.href, url);
  await broken.filter.fire('click');
  assert.equal(broken.story.hidden, true);
  console.log('Learn Mode browser checks passed');
}

main().catch(error => { console.error(error); process.exitCode = 1; });
