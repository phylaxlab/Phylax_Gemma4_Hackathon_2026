/**
 * Search Page - Event search with text-based and AI-powered modes.
 */

import { searchEvents, aiSearch, getThumbnailUrl } from '../api.js';
import { createSearchBar } from '../components/searchBar.js';
import { icon } from '../icons.js';
import { formatNumber, formatTimeOfDay, formatVideoTime, t } from '../i18n.js';

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function getEventTypeIcon(eventType) {
  const map = {
    motion: 'activity',
    person: 'user',
    vehicle: 'car',
    anomaly: 'alertTriangle',
    none: 'eye',
  };
  return map[eventType] || 'eye';
}

function getEventTypeLabel(eventType) {
  const normalized = String(eventType || 'none').toLowerCase();
  const label = t(`eventPanel.filters.${normalized}`);
  return label === `eventPanel.filters.${normalized}`
    ? t('searchResult.eventFallback')
    : label;
}

export function mountSearchPage(container, navigate, initialQuery = '') {
  container.innerHTML = '';

  const title = document.createElement('div');
  title.className = 'section-title';
  title.innerHTML = `${icon('search', 24)} ${t('searchPage.title')}`;
  container.appendChild(title);

  const resultsContainer = document.createElement('div');
  resultsContainer.id = 'search-results';

  const searchBar = createSearchBar(initialQuery, async ({ query, mode }) => {
    await performSearch(resultsContainer, query, mode, navigate);
  });
  container.appendChild(searchBar);
  container.appendChild(resultsContainer);

  if (initialQuery) {
    void performSearch(resultsContainer, initialQuery, 'ai', navigate);
  }
}

async function performSearch(container, query, mode, navigate) {
  container.innerHTML = `
    <div style="text-align:center;padding:var(--space-xl);">
      <div class="loading-spinner"></div>
      <div style="font-size:var(--font-size-sm);color:var(--text-tertiary);margin-top:var(--space-md);">
        ${mode === 'ai' ? t('searchPage.loadingAi') : t('searchPage.loadingText')}
      </div>
    </div>
  `;

  try {
    const data = mode === 'ai'
      ? await aiSearch(query)
      : await searchEvents(query);

    renderResults(container, data, query, navigate);
  } catch (error) {
    console.error('Search failed:', error);
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">${icon('alertTriangle', 56)}</div>
        <div class="empty-state-title">${t('searchPage.failedTitle')}</div>
        <div class="empty-state-desc">${escapeHtml(error.message)}</div>
      </div>
    `;
  }
}

function renderResults(container, data, query, navigate) {
  container.innerHTML = '';

  const header = document.createElement('div');
  header.className = 'search-results-header';
  header.innerHTML = `
    <div class="search-results-count">
      ${escapeHtml(t('searchPage.found', { count: formatNumber(data.total || 0), query }))}
    </div>
  `;
  container.appendChild(header);

  if (!data.results || data.results.length === 0) {
    container.innerHTML += `
      <div class="empty-state">
        <div class="empty-state-icon">${icon('search', 56)}</div>
        <div class="empty-state-title">${t('searchPage.noResultsTitle')}</div>
        <div class="empty-state-desc">${t('searchPage.noResultsDesc')}</div>
      </div>
    `;
    return;
  }

  data.results.forEach((result) => {
    const item = document.createElement('div');
    item.className = 'search-result-item';

    const isCameraResult = result.resource_type === 'camera' || result.camera_id != null;
    const thumbUrl = isCameraResult
      ? result.preview_url
      : getThumbnailUrl(result.thumbnail);
    const thumbHtml = thumbUrl
      ? `<img src="${escapeHtml(thumbUrl)}" alt="${escapeHtml(result.video_title)}" />`
      : `<div style="display:flex;align-items:center;justify-content:center;width:100%;height:100%;color:var(--text-tertiary);">${icon(isCameraResult ? 'camera' : 'film', 32)}</div>`;
    const sourceIcon = isCameraResult ? 'camera' : 'film';
    const timestampLabel = isCameraResult
      ? formatTimeOfDay(result.timestamp_sec)
      : formatVideoTime(result.timestamp_sec);

    item.innerHTML = `
      <div class="search-result-thumb">${thumbHtml}</div>
      <div class="search-result-info">
        <div class="search-result-title">${icon(sourceIcon, 15)} ${escapeHtml(result.video_title)}</div>
        <div class="search-result-time">
          ${icon('clock', 14)} ${timestampLabel}
          <span class="event-type-badge event-type-${result.event_type}" style="margin-left:var(--space-sm);">
            ${icon(getEventTypeIcon(result.event_type), 12)} ${escapeHtml(getEventTypeLabel(result.event_type))}
          </span>
          ${result.relevance_score > 0 ? `<span style="margin-left:var(--space-sm);color:var(--text-tertiary);font-size:var(--font-size-xs);">${t('common.score')}: ${escapeHtml(result.relevance_score)}/10</span>` : ''}
        </div>
        <div class="search-result-desc">${escapeHtml(result.description || result.summary || t('searchResult.descriptionFallback'))}</div>
      </div>
    `;

    item.addEventListener('click', () => {
      if (isCameraResult && result.camera_id != null) {
        navigate(`/camera/${result.camera_id}`, { t: result.timestamp_sec });
      } else if (result.video_id != null) {
        navigate(`/watch/${result.video_id}`, { t: result.timestamp_sec });
      }
    });

    container.appendChild(item);
  });
}
