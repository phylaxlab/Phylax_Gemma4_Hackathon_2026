/**
 * Header Component - Top navigation bar with logo, search, actions, and language switcher.
 */

import { icon } from '../icons.js';
import { getSearchSuggestions } from '../api.js';
import { getLanguage, getSupportedLanguages, setLanguage, t } from '../i18n.js';

export function renderHeader(container, handlers = {}) {
  const header = document.createElement('header');
  header.className = 'header';
  header.id = 'main-header';

  const languages = getSupportedLanguages();
  const currentLanguage = getLanguage();

  header.innerHTML = `
    <div class="header-left">
      <button class="header-menu-btn" id="menu-toggle" aria-label="${t('header.toggleMenu')}">
        ${icon('menu', 20)}
      </button>
      <div class="header-logo" id="header-logo">
        <img src="/phylax-logo.png" alt="Phylax" class="header-logo-image" />
      </div>
    </div>

    <div class="header-center">
      <div class="search-container">
        <div class="search-input-wrap">
          <input
            type="text"
            class="search-input"
            id="global-search-input"
            placeholder="${t('header.searchPlaceholder')}"
            autocomplete="off"
          />
          <div class="search-dropdown" id="global-search-dropdown"></div>
        </div>
        <button class="search-btn" id="global-search-btn" aria-label="${t('header.searchAria')}">
          ${icon('search', 18)}
        </button>
      </div>
    </div>

    <div class="header-right">
      <label class="header-language" for="header-language-select">
        <span class="header-language-label" title="${t('common.language')}" aria-hidden="true">${icon('globe', 14)}</span>
        <select class="header-language-select" id="header-language-select" aria-label="${t('common.language')}">
          ${languages.map((language) => `
            <option value="${language.code}" ${language.code === currentLanguage ? 'selected' : ''}>${language.label}</option>
          `).join('')}
        </select>
      </label>
      <button class="icon-btn header-upload-icon" id="header-upload-btn" title="${t('header.upload')}" aria-label="${t('header.upload')}">
        ${icon('upload', 17)}
      </button>
    </div>
  `;

  container.appendChild(header);

  const searchInput = header.querySelector('#global-search-input');
  const searchBtn = header.querySelector('#global-search-btn');
  const logo = header.querySelector('#header-logo');
  const uploadBtn = header.querySelector('#header-upload-btn');
  const menuBtn = header.querySelector('#menu-toggle');
  const languageSelect = header.querySelector('#header-language-select');
  const dropdown = header.querySelector('#global-search-dropdown');

  let debounceTimer = null;
  let activeIndex = -1;
  let currentSuggestions = [];

  const doSearch = (queryOverride = null) => {
    const query = queryOverride || searchInput.value.trim();
    if (query && handlers.onSearch) {
      dropdown.classList.remove('active');
      handlers.onSearch(query);
    }
  };

  const renderDropdown = () => {
    if (currentSuggestions.length === 0) {
      dropdown.classList.remove('active');
      return;
    }

    dropdown.innerHTML = currentSuggestions.map((suggestion, index) => `
      <div class="search-suggestion-item ${index === activeIndex ? 'focused' : ''}" data-index="${index}">
        ${icon('search', 14)} <span>${suggestion}</span>
      </div>
    `).join('');
    dropdown.classList.add('active');

    dropdown.querySelectorAll('.search-suggestion-item').forEach((item) => {
      item.addEventListener('click', () => {
        searchInput.value = currentSuggestions[Number(item.dataset.index)];
        doSearch();
      });
    });
  };

  searchInput.addEventListener('input', (event) => {
    const value = event.target.value.trim();
    activeIndex = -1;

    if (value.length < 2) {
      currentSuggestions = [];
      renderDropdown();
      return;
    }

    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(async () => {
      dropdown.innerHTML = `<div class="search-suggestion-item" style="justify-content:center;">${icon('signal', 14)} ${t('common.thinking')}</div>`;
      dropdown.classList.add('active');

      try {
        const response = await getSearchSuggestions(value);
        currentSuggestions = response.suggestions || [];
        renderDropdown();
      } catch (error) {
        console.error('Suggestion error:', error);
        currentSuggestions = [];
        renderDropdown();
      }
    }, 400);
  });

  searchInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      if (activeIndex >= 0 && currentSuggestions[activeIndex]) {
        searchInput.value = currentSuggestions[activeIndex];
      }
      doSearch();
      return;
    }

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      if (currentSuggestions.length > 0) {
        activeIndex = (activeIndex + 1) % currentSuggestions.length;
        renderDropdown();
      }
      return;
    }

    if (event.key === 'ArrowUp') {
      event.preventDefault();
      if (currentSuggestions.length > 0) {
        activeIndex = (activeIndex - 1 + currentSuggestions.length) % currentSuggestions.length;
        renderDropdown();
      }
      return;
    }

    if (event.key === 'Escape') {
      currentSuggestions = [];
      renderDropdown();
    }
  });

  function handleDocumentClick(event) {
    if (!header.querySelector('.search-container').contains(event.target)) {
      dropdown.classList.remove('active');
    }
  }

  searchBtn.addEventListener('click', () => doSearch());
  document.addEventListener('click', handleDocumentClick);

  menuBtn.addEventListener('click', () => {
    document.body.classList.toggle('sidebar-collapsed');
  });

  logo.addEventListener('click', () => {
    handlers.onLogoClick?.();
  });

  uploadBtn.addEventListener('click', () => {
    handlers.onUploadClick?.();
  });

  languageSelect?.addEventListener('change', () => {
    setLanguage(languageSelect.value);
  });

  header.cleanup = () => {
    clearTimeout(debounceTimer);
    document.removeEventListener('click', handleDocumentClick);
  };

  return header;
}
