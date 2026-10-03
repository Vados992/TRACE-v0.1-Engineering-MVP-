'use strict';
(async () => {
  const out = document.getElementById('releases');
  try {
    const response = await fetch('/api/public/releases');
    if (!response.ok) throw new Error('Публичные материалы временно недоступны.');
    const releases = await response.json();
    out.replaceChildren();
    if (!releases.length) out.textContent = 'Одобренных публикаций пока нет.';
    for (const release of releases) {
      const card = document.createElement('article'); card.className = 'card';
      for (const [tag, text] of [['h2',release.title], ['p',release.summary], ['small',release.published_at]]) {
        const element = document.createElement(tag); element.textContent = text; card.append(element);
      }
      out.append(card);
    }
  } catch (error) { out.textContent = error.message; }
})();
