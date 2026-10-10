(() => {
  const root = document.documentElement;
  const saved = localStorage.getItem('the-edge-theme');
  if (saved === 'dark' || (!saved && matchMedia('(prefers-color-scheme: dark)').matches)) root.dataset.theme = 'dark';
  document.getElementById('theme')?.addEventListener('click', () => {
    root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('the-edge-theme', root.dataset.theme);
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
    document.getElementById('no-results').hidden = visible > 0;
  }));
})();
