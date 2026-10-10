(() => {
  'use strict';

  const answerPrefix = 'the-edge-answer:';
  const fallbackExcerpt = 'Open the original article for the full report.';

  function readAnswer(storage, id) {
    try {
      return { value: storage.getItem(answerPrefix + id) || '', available: true };
    } catch {
      return { value: '', available: false };
    }
  }

  function saveAnswer(storage, id, value) {
    try {
      storage.setItem(answerPrefix + id, value);
      return true;
    } catch {
      return false;
    }
  }

  function cleanExcerpt(value) {
    const text = value.replace(/\s+/g, ' ').trim().replace(
      /\s*(?:The post|This post)\s+.{0,240}?\s+appeared first on\s+.{1,120}?[.!?]?\s*$/i, ''
    ).trim().replace(/(?:\s*(?:\.{3}|…|\[\.\.\.\]))+$/, '').trim();
    const boundaries = [...text.matchAll(/[.!?]["”’]?(?=\s|$)/g)];
    let previous = 0;
    let end = 0;
    let count = 0;
    for (const match of boundaries) {
      const candidate = match.index + match[0].length;
      if (candidate - previous < 25) continue;
      if (candidate > 360) break;
      end = candidate;
      previous = candidate;
      if (++count === 3) break;
    }
    return end ? text.slice(0, end).trim() : fallbackExcerpt;
  }

  function buildPrompt({ title, url, publisher, excerpt, answer }) {
    return `I am checking my understanding of a news article.\n\n` +
      `Title: ${title}\nPublisher: ${publisher}\nOriginal article: ${url}\n` +
      `Available RSS excerpt: ${excerpt}\n` +
      `My explanation: ${answer.trim() || '(No explanation yet. Please explain the central problem using the available evidence.)'}\n\n` +
      `Check whether my explanation captures the central problem. Identify inaccuracies, missing mechanisms, and important nuances. Briefly explain what I understood correctly, then ask ONE thoughtful follow-up question. Keep the response concise and avoid unnecessary praise. Clearly distinguish what the supplied excerpt supports from anything that requires reading the full article. If you can access the original article, you may use it for a better evaluation; otherwise say that your assessment is based only on the excerpt and my explanation.`;
  }

  async function copyPrompt(clipboard, prompt) {
    try {
      if (!clipboard?.writeText) return false;
      await clipboard.writeText(prompt);
      return true;
    } catch {
      return false;
    }
  }

  async function stableId(story, url) {
    if (story.dataset.articleId) return story.dataset.articleId;
    try {
      const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(url));
      return [...new Uint8Array(digest)].slice(0, 8).map(byte => byte.toString(16).padStart(2, '0')).join('');
    } catch {
      return `url:${url}`;
    }
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { readAnswer, saveAnswer, cleanExcerpt, buildPrompt, copyPrompt, stableId };
  }
  if (typeof document === 'undefined') return;

  function storage() {
    try { return window.localStorage; } catch { return null; }
  }

  const root = document.documentElement;
  let theme = null;
  try { theme = storage()?.getItem('the-edge-theme'); } catch { /* storage blocked */ }
  if (theme === 'dark' || (!theme && window.matchMedia?.('(prefers-color-scheme: dark)').matches)) root.dataset.theme = 'dark';
  document.getElementById('theme')?.addEventListener('click', () => {
    root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
    try { storage()?.setItem('the-edge-theme', root.dataset.theme); } catch { /* theme still works */ }
  });

  const filters = [...document.querySelectorAll('.filter')];
  const stories = [...document.querySelectorAll('.story')];
  filters.forEach(button => button.addEventListener('click', () => {
    const value = button.dataset.filter;
    let visible = 0;
    filters.forEach(item => {
      const active = item === button;
      item.classList.toggle('active', active);
      item.setAttribute('aria-pressed', String(active));
    });
    stories.forEach(story => {
      story.hidden = value !== 'All' && story.dataset.category !== value;
      if (!story.hidden) visible++;
    });
    const empty = document.getElementById('no-results');
    if (empty) empty.hidden = visible > 0;
  }));

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  function showManualPrompt(panel, prompt, status) {
    let fallback = panel.querySelector('.prompt-fallback');
    if (!fallback) {
      fallback = element('div', 'prompt-fallback');
      const label = element('label', '', 'Copy this prompt manually:');
      const field = element('textarea', 'prompt-text');
      field.readOnly = true;
      field.rows = 5;
      label.append(field);
      const copy = element('button', 'quiet-button', 'Copy prompt');
      copy.type = 'button';
      copy.addEventListener('click', async () => {
        field.select();
        try {
          if (!(await copyPrompt(navigator.clipboard, field.value)) && !document.execCommand('copy')) {
            throw new Error('copy blocked');
          }
          status.textContent = 'Prompt copied. Paste it into ChatGPT.';
        } catch {
          status.textContent = 'Select the prompt and copy it with your keyboard, then paste it into ChatGPT.';
        }
      });
      fallback.append(label, copy);
      panel.append(fallback);
    }
    const field = fallback.querySelector('textarea');
    field.value = prompt;
    fallback.hidden = false;
    field.select();
  }

  async function addLearnMode(story, position) {
    const titleLink = story.querySelector('h2 a');
    const description = story.querySelector('.description');
    const meta = story.querySelector('.meta');
    const readLink = story.querySelector('.read-link') || meta?.querySelector('a');
    if (!titleLink || !description || !readLink) return;

    const title = titleLink.textContent.trim();
    const url = titleLink.href;
    const publisher = meta?.querySelector('span')?.textContent.trim() || 'Publisher not listed';
    const excerpt = cleanExcerpt(description.textContent);
    description.textContent = excerpt;
    if (!story.querySelector('.excerpt-label') && excerpt !== fallbackExcerpt) {
      description.before(element('span', 'excerpt-label', 'Source excerpt'));
    }
    if (meta) story.querySelector('h2')?.after(meta);
    readLink.classList.add('read-link');
    readLink.textContent = 'Read article ↗';
    readLink.target = '_blank';
    readLink.rel = 'noopener noreferrer';

    const id = await stableId(story, url);
    const actions = element('div', 'story-actions');
    const toggle = element('button', 'learn-toggle', 'Test understanding');
    toggle.type = 'button';
    const panel = element('div', 'learn-panel');
    panel.id = `learn-${position}`;
    panel.hidden = true;
    toggle.setAttribute('aria-controls', panel.id);
    toggle.setAttribute('aria-expanded', 'false');
    toggle.addEventListener('click', () => {
      panel.hidden = !panel.hidden;
      toggle.setAttribute('aria-expanded', String(!panel.hidden));
    });
    actions.append(readLink, toggle);
    story.append(actions, panel);

    const question = element('p', 'learn-question', 'What was the main problem, and why does it matter?');
    const label = element('label', 'learn-label', 'Your explanation');
    const answer = element('textarea', 'learn-answer');
    answer.id = `answer-${position}`;
    answer.rows = 3;
    answer.placeholder = 'Explain the problem, the proposed solution, and why it matters in your own words...';
    label.htmlFor = answer.id;
    const note = element('p', 'learn-note', 'Answers are saved in this browser only.');
    const stored = readAnswer(storage(), id);
    answer.value = stored.value;
    if (!stored.available) note.textContent = 'Browser storage is unavailable; this answer will not persist.';
    answer.addEventListener('input', () => {
      if (!saveAnswer(storage(), id, answer.value)) {
        note.textContent = 'Browser storage is unavailable; this answer will not persist.';
      }
    });

    const discuss = element('button', 'quiet-button discuss-button', 'Discuss with ChatGPT ↗');
    discuss.type = 'button';
    const status = element('p', 'learn-status');
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    discuss.addEventListener('click', async () => {
      const prompt = buildPrompt({ title, url, publisher, excerpt, answer: answer.value });
      const copying = copyPrompt(navigator.clipboard, prompt);
      let opened = false;
      try { opened = !!window.open('https://chatgpt.com/', '_blank', 'noopener,noreferrer'); } catch { /* blocked */ }
      if (await copying) {
        status.textContent = 'Prompt copied. Paste it into ChatGPT.';
      } else {
        showManualPrompt(panel, prompt, status);
        status.textContent = 'Clipboard access is blocked. Copy the prompt below, then paste it into ChatGPT.';
      }
      if (!opened) {
        const link = element('a', 'chatgpt-fallback', 'Open ChatGPT ↗');
        link.href = 'https://chatgpt.com/';
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        status.append(' ', link);
      }
    });
    panel.append(question, label, answer, note, discuss, status);
  }

  stories.forEach((story, index) => {
    addLearnMode(story, index + 1).catch(() => { /* Reading links remain usable. */ });
  });
})();
