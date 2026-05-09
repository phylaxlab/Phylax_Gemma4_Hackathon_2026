/**
 * SearchBar Component - Inline search with text / AI mode toggle.
 */

import { icon } from '../icons.js';
import { t } from '../i18n.js';

export function createSearchBar(initialQuery = '', onSearch = null) {
  const container = document.createElement('div');
  container.id = 'page-search-bar';

  container.innerHTML = `
    <div style="display:flex;gap:var(--space-md);align-items:center;margin-bottom:var(--space-lg);">
      <div class="search-container" style="max-width:100%;flex:1;">
        <div class="search-input-wrap">
          <input
            type="text"
            class="search-input"
            id="page-search-input"
            placeholder="${t('searchPage.inputPlaceholder')}"
            value="${initialQuery}"
            style="border-radius:var(--radius-full) 0 0 var(--radius-full);"
          />
        </div>
        <button class="search-btn" id="page-search-btn" style="border-radius:0 var(--radius-full) var(--radius-full) 0;" aria-label="${t('common.search')}">
          ${icon('search', 18)}
        </button>
      </div>
    </div>
    <div class="filter-chips" id="search-mode-chips">
      <button class="chip" data-mode="text">${icon('zap', 14)} ${t('searchPage.quickMode')}</button>
      <button class="chip active" data-mode="ai">${icon('signal', 14)} ${t('searchPage.aiMode')}</button>
    </div>
  `;

  let mode = 'ai';

  const input = container.querySelector('#page-search-input');
  const button = container.querySelector('#page-search-btn');
  const chips = container.querySelectorAll('[data-mode]');

  chips.forEach((chip) => {
    chip.addEventListener('click', () => {
      mode = chip.dataset.mode;
      chips.forEach((entry) => entry.classList.remove('active'));
      chip.classList.add('active');
    });
  });

  const doSearch = () => {
    const query = input.value.trim();
    if (query && onSearch) {
      onSearch({ query, mode });
    }
  };

  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      doSearch();
    }
  });
  button.addEventListener('click', doSearch);

  return container;
}
