/**
 * Camera Map Page - OpenStreetMap-only Taiwan public camera map.
 * Phylax renders the map itself and aggregates public, licensed camera sources.
 */

import {
  addCamera,
  getCameraMapStatus,
  getPublicCameraMapCameras,
  getPublicCameraMapCamera,
} from '../api.js';
import { icon } from '../icons.js';
import { formatNumber, t } from '../i18n.js';

const DEFAULT_CENTER = { lat: 23.7, lng: 120.96 };
const DEFAULT_ZOOM = 7;
const FILTER_STORAGE_KEY = 'phylax.cameraMap.provider';
const LEAFLET_JS_URL = 'https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js';
const LEAFLET_CSS_URL = 'https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css';

const PROVIDER_COLORS = {
  freeway: '#60a5fa',
  thb: '#fbbf24',
  taichung: '#ff5a36',
  tainan: '#22c55e',
  keelung: '#a78bfa',
};

let leafletPromise = null;

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function sanitizeUrl(value) {
  if (typeof value !== 'string') return '';
  try {
    const parsed = new URL(value);
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return parsed.toString();
    }
  } catch {
    return '';
  }
  return '';
}

function providerLabel(provider, providerMeta = {}) {
  if (provider === 'all') return t('common.all');
  return providerMeta[provider]?.short_name || providerMeta[provider]?.name || provider;
}

function providerIcon(provider) {
  const map = {
    freeway: 'activity',
    thb: 'mapPin',
    taichung: 'camera',
    tainan: 'camera',
    keelung: 'camera',
  };
  return map[provider] || 'camera';
}

function buildStatusChip(status) {
  const value = String(status || 'unknown').toLowerCase();
  const label = value === 'online'
    ? t('mapPage.online')
    : value === 'offline'
      ? t('mapPage.offline')
      : t('mapPage.unknown');
  return `<span class="camera-map-provider-chip muted">${label}</span>`;
}

function readActiveProvider() {
  try {
    return window.localStorage.getItem(FILTER_STORAGE_KEY) || 'all';
  } catch {
    return 'all';
  }
}

function writeActiveProvider(provider) {
  try {
    window.localStorage.setItem(FILTER_STORAGE_KEY, provider);
  } catch {
    // Ignore storage failures and keep the in-memory state.
  }
}

function buildProviderFilter(providerMeta, activeProvider) {
  const entries = Object.entries(providerMeta || {}).sort((a, b) => {
    const scopeA = a[1]?.scope === 'nationwide' ? 0 : 1;
    const scopeB = b[1]?.scope === 'nationwide' ? 0 : 1;
    if (scopeA !== scopeB) return scopeA - scopeB;
    return providerLabel(a[0], providerMeta).localeCompare(providerLabel(b[0], providerMeta));
  });

  return [
    `<button class="chip ${activeProvider === 'all' ? 'active' : ''}" data-provider="all">${t('common.all')}</button>`,
    ...entries.map(([provider, meta]) => {
      const unavailable = meta?.available === false;
      const title = unavailable && meta?.last_error
        ? ` title="${escapeHtml(meta.last_error)}"`
        : '';
      return `
        <button
          class="chip ${activeProvider === provider ? 'active' : ''} ${unavailable ? 'is-unavailable' : ''}"
          data-provider="${escapeHtml(provider)}"${title}
        >
          ${escapeHtml(providerLabel(provider, providerMeta))}
          <span class="camera-map-filter-count">${formatNumber(meta?.count || 0)}</span>
        </button>
      `;
    }),
  ].join('');
}

function cameraMetaLine(camera) {
  const pieces = [
    camera.provider_name,
    camera.region || camera.country,
    camera.road_name,
    camera.location_mile,
  ].filter(Boolean);
  return escapeHtml(pieces.join(' | '));
}

function buildCameraList(cameras) {
  if (!cameras.length) {
    return `<div class="camera-map-list-empty">${t('mapPage.noVisibleCameras')}</div>`;
  }

  return cameras.slice(0, 18).map((camera) => `
    <button class="camera-map-list-item" data-camera-id="${escapeHtml(camera.id)}">
      <span class="camera-map-list-dot ${escapeHtml(camera.provider)}"></span>
      <span class="camera-map-list-copy">
        <strong>${escapeHtml(camera.title)}</strong>
        <span>${cameraMetaLine(camera)}</span>
      </span>
    </button>
  `).join('');
}

function buildSelectionHtml(camera, importing = false) {
  const previewUrl = sanitizeUrl(camera.preview_url || camera.stream_url || camera.detail_url);
  const sourcePage = sanitizeUrl(camera.source_page);
  const detailUrl = sanitizeUrl(camera.detail_url || camera.stream_url || camera.preview_url);
  const providerName = escapeHtml(camera.provider_name || camera.provider || t('mapPage.providerFallback'));
  const title = escapeHtml(camera.title || t('mapPage.untitled'));
  const region = escapeHtml(camera.region || camera.country || t('mapPage.unknownRegion'));
  const roadName = escapeHtml(camera.road_name || '');
  const locationMile = escapeHtml(camera.location_mile || '');
  const roadDirection = escapeHtml(camera.road_direction || '');
  const description = escapeHtml(camera.surveillance_description || '');
  const sourceAttribution = escapeHtml(camera.source_attribution || '');
  const statusChip = buildStatusChip(camera.status);
  const canImport = !!sanitizeUrl(camera.stream_url);

  return `
    <div class="camera-map-panel-body">
      <div class="camera-map-provider-row">
        <span class="camera-map-provider-chip">${icon(providerIcon(camera.provider), 12)} ${providerName}</span>
        ${statusChip}
        ${!canImport ? `<span class="camera-map-provider-chip muted">${t('mapPage.previewOnly')}</span>` : ''}
      </div>
      <h2 class="camera-map-panel-title">${title}</h2>
      <div class="camera-map-panel-meta">${region}</div>
      <div class="camera-map-category-row">
        ${roadName ? `<span class="camera-map-category">${icon('mapPin', 12)} ${roadName}</span>` : ''}
        ${locationMile ? `<span class="camera-map-category">${icon('layers', 12)} ${locationMile}</span>` : ''}
        ${roadDirection ? `<span class="camera-map-category">${icon('activity', 12)} ${roadDirection}</span>` : ''}
      </div>
      ${
        previewUrl
          ? `<img class="camera-map-preview" src="${previewUrl}" alt="${title}" loading="lazy" />`
          : `<div class="camera-map-preview camera-map-preview-empty">${icon('camera', 42)}</div>`
      }
      <div class="camera-map-panel-actions">
        <button class="btn btn-primary" id="camera-map-import-btn" ${canImport ? '' : 'disabled'}>
          ${icon('plus', 14)} ${importing ? t('common.importing') : t('mapPage.addToHub')}
        </button>
        ${detailUrl ? `<a class="btn btn-secondary" href="${detailUrl}" target="_blank" rel="noreferrer">${icon('externalLink', 14)} ${t('common.openSource')}</a>` : ''}
        ${sourcePage ? `<a class="btn btn-secondary" href="${sourcePage}" target="_blank" rel="noreferrer">${icon('layers', 14)} ${t('common.source')}</a>` : ''}
      </div>
      <div class="camera-map-attribution">
        ${description ? `${description}<br/>` : ''}
        ${sourceAttribution ? `${sourceAttribution}<br/>` : ''}
        ${t('mapPage.sourceLabel')}: ${providerName}<br/>
        ${t('mapPage.licenseLabel')}: ${escapeHtml(camera.license_name || t('mapPage.openData'))}
      </div>
    </div>
  `;
}

function showToast(message, type = 'info') {
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s';
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

function loadLeaflet() {
  if (window.L) {
    return Promise.resolve(window.L);
  }
  if (leafletPromise) {
    return leafletPromise;
  }

  leafletPromise = new Promise((resolve, reject) => {
    if (!document.getElementById('phylax-leaflet-css')) {
      const link = document.createElement('link');
      link.id = 'phylax-leaflet-css';
      link.rel = 'stylesheet';
      link.href = LEAFLET_CSS_URL;
      document.head.appendChild(link);
    }

    const existing = document.getElementById('phylax-leaflet-js');
    if (existing) {
      existing.addEventListener('load', () => resolve(window.L), { once: true });
      existing.addEventListener('error', () => reject(new Error('Leaflet failed to load.')), { once: true });
      return;
    }

    const script = document.createElement('script');
    script.id = 'phylax-leaflet-js';
    script.src = LEAFLET_JS_URL;
    script.async = true;
    script.onerror = () => reject(new Error('Leaflet failed to load.'));
    script.onload = () => resolve(window.L);
    document.head.appendChild(script);
  });

  return leafletPromise;
}

async function createMapController(canvasEl) {
  const L = await loadLeaflet();
  const renderer = L.canvas({ padding: 0.4 });
  const map = L.map(canvasEl, {
    zoomControl: true,
    attributionControl: true,
    preferCanvas: true,
  }).setView([DEFAULT_CENTER.lat, DEFAULT_CENTER.lng], DEFAULT_ZOOM);

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors',
  }).addTo(map);

  return {
    setDefaultView() {
      map.setView([DEFAULT_CENTER.lat, DEFAULT_CENTER.lng], DEFAULT_ZOOM);
    },
    getBoundsQuery() {
      const bounds = map.getBounds();
      return {
        northLat: bounds.getNorth(),
        eastLon: bounds.getEast(),
        southLat: bounds.getSouth(),
        westLon: bounds.getWest(),
      };
    },
    onViewportChange(callback) {
      map.on('moveend', callback);
      return () => map.off('moveend', callback);
    },
    createMarker(camera, onClick) {
      const marker = L.circleMarker([camera.lat, camera.lng], {
        renderer,
        color: '#ffffff',
        weight: 2,
        fillColor: PROVIDER_COLORS[camera.provider] || '#ff5a36',
        fillOpacity: 1,
        radius: 6,
      }).addTo(map);
      marker.on('click', () => onClick(camera));
      return {
        remove() {
          marker.remove();
        },
      };
    },
    destroy() {
      map.remove();
    },
  };
}

function providerHealthMessage(providerMeta, activeProvider) {
  if (activeProvider !== 'all' && providerMeta[activeProvider]?.available === false) {
    return t('mapPage.sourceUnavailable', {
      provider: providerLabel(activeProvider, providerMeta),
      error: providerMeta[activeProvider]?.last_error || t('common.unknown'),
    });
  }

  const unavailable = Object.entries(providerMeta || {})
    .filter(([, meta]) => meta?.available === false)
    .map(([provider]) => providerLabel(provider, providerMeta));

  if (unavailable.length) {
    return t('mapPage.sourcesUnavailable', {
      providers: unavailable.join(', '),
    });
  }

  return '';
}

export async function mountCameraMapPage(container, navigate) {
  let disposed = false;
  let markers = [];
  let mapController = null;
  let unbindViewport = null;
  let activeProvider = readActiveProvider();
  let visibleCameras = [];
  let requestToken = 0;
  let providerMeta = {};
  let idleTimer = null;

  const cleanup = () => {
    disposed = true;
    if (idleTimer) {
      clearTimeout(idleTimer);
      idleTimer = null;
    }
    if (unbindViewport) {
      unbindViewport();
      unbindViewport = null;
    }
    markers.forEach((marker) => marker.remove());
    markers = [];
    mapController?.destroy?.();
    mapController = null;
  };

  container.innerHTML = '<div class="loading-spinner"></div>';

  try {
    const status = await getCameraMapStatus();
    if (disposed) return cleanup;
    providerMeta = status.providers || {};
    if (activeProvider !== 'all' && !providerMeta[activeProvider]) {
      activeProvider = 'all';
    }

    container.innerHTML = `
      <section class="camera-map-shell fade-in">
        <div class="camera-map-hero">
          <div>
            <div class="feed-kicker">${t('mapPage.kicker')}</div>
            <h1 class="section-title">${icon('mapPin', 28)} ${t('mapPage.title')}</h1>
            <p class="camera-map-subtitle">${t('mapPage.subtitle')}</p>
          </div>
          <div class="camera-map-hero-actions">
            <button class="btn btn-secondary" id="camera-map-reset-btn">${icon('layers', 16)} ${t('mapPage.reset')}</button>
            <button class="btn btn-primary" id="camera-map-refresh-btn">${icon('activity', 16)} ${t('mapPage.refresh')}</button>
          </div>
        </div>

        <div class="camera-map-engine-note" id="camera-map-engine-note">
          ${icon('mapPin', 16)} ${t('mapPage.engineNote')}
        </div>
        <div class="camera-map-provider-filter" id="camera-map-provider-filter"></div>

        <div class="camera-map-layout">
          <div class="camera-map-canvas-wrap">
            <div class="camera-map-status" id="camera-map-status">${t('mapPage.loadingAll')}</div>
            <div class="camera-map-canvas" id="camera-map-canvas"></div>
          </div>

          <aside class="camera-map-panel">
            <div class="camera-map-panel-header">
              <div>
                <div class="camera-map-panel-eyebrow">${t('mapPage.selection')}</div>
                <div class="camera-map-panel-heading">${t('mapPage.details')}</div>
              </div>
              <div class="event-count-badge" id="camera-map-count">${t('mapPage.count', { count: formatNumber(0) })}</div>
            </div>

            <div class="camera-map-selection" id="camera-map-selection">
              <div class="camera-map-placeholder">
                <div class="camera-map-placeholder-icon">${icon('camera', 42)}</div>
                <div class="camera-map-placeholder-title">${t('mapPage.pickCamera')}</div>
                <div class="camera-map-placeholder-copy">${t('mapPage.pickCameraDesc')}</div>
              </div>
            </div>

            <div class="camera-map-list-shell">
              <div class="camera-map-panel-eyebrow">${t('mapPage.visibleCameras')}</div>
              <div class="camera-map-list" id="camera-map-list"></div>
            </div>

            <div class="camera-map-attribution">
              ${(status.notes || []).map((note) => escapeHtml(note)).join('<br/>')}
            </div>
          </aside>
        </div>
      </section>
    `;

    const canvasEl = container.querySelector('#camera-map-canvas');
    const statusEl = container.querySelector('#camera-map-status');
    const countEl = container.querySelector('#camera-map-count');
    const listEl = container.querySelector('#camera-map-list');
    const selectionEl = container.querySelector('#camera-map-selection');
    const providerFilterEl = container.querySelector('#camera-map-provider-filter');
    const engineNoteEl = container.querySelector('#camera-map-engine-note');

    mapController = await createMapController(canvasEl);
    if (disposed) return cleanup;
    canvasEl.classList.add('camera-map-osm');

    function updateEngineNote() {
      const total = Object.values(providerMeta).reduce((sum, meta) => sum + Number(meta?.count || 0), 0);
      const activeLabel = providerLabel(activeProvider, providerMeta);
      engineNoteEl.innerHTML = `
        ${icon('mapPin', 16)}
        ${escapeHtml(t('mapPage.engineNoteWithCount', {
          count: formatNumber(total),
          filter: activeLabel,
        }))}
      `;
    }

    function bindProviderFilter() {
      providerFilterEl.innerHTML = buildProviderFilter(providerMeta, activeProvider);
      providerFilterEl.querySelectorAll('[data-provider]').forEach((button) => {
        button.addEventListener('click', () => {
          activeProvider = button.dataset.provider;
          writeActiveProvider(activeProvider);
          bindProviderFilter();
          updateEngineNote();
          refreshViewport(false);
        });
      });
    }

    function updateStatusLabel(baseText) {
      const warning = providerHealthMessage(providerMeta, activeProvider);
      statusEl.textContent = warning ? `${baseText} | ${warning}` : baseText;
      statusEl.classList.toggle('is-warning', Boolean(warning));
    }

    function setSelection(camera, importing = false) {
      selectionEl.innerHTML = buildSelectionHtml(camera, importing);
      selectionEl.querySelector('#camera-map-import-btn')?.addEventListener('click', async () => {
        const streamUrl = sanitizeUrl(camera.stream_url);
        if (!streamUrl) return;
        setSelection(camera, true);
        try {
          const created = await addCamera(camera.title, streamUrl);
          showToast(t('mapPage.cameraAdded'), 'success');
          navigate(`/camera/${created.id}`);
        } catch (err) {
          setSelection(camera, false);
          showToast(t('mapPage.addFailed', { message: err.message }), 'error');
        }
      });
    }

    function clearMarkers() {
      markers.forEach((marker) => marker.remove());
      markers = [];
    }

    function renderMarkers(cameras) {
      clearMarkers();
      visibleCameras = cameras;
      countEl.textContent = t('mapPage.visibleCount', { count: formatNumber(cameras.length) });
      listEl.innerHTML = buildCameraList(cameras);
      listEl.querySelectorAll('[data-camera-id]').forEach((button) => {
        button.addEventListener('click', async () => {
          const camera = visibleCameras.find((item) => item.id === button.dataset.cameraId);
          if (!camera) return;
          await openCamera(camera);
        });
      });

      cameras.forEach((camera) => {
        markers.push(mapController.createMarker(camera, openCamera));
      });
    }

    async function openCamera(camera) {
      setSelection(camera, false);
      try {
        const data = await getPublicCameraMapCamera(camera.provider, camera.source_id);
        if (disposed) return;
        setSelection(data.camera, false);
      } catch (err) {
        setSelection(camera, false);
        showToast(t('mapPage.addFailed', { message: err.message }), 'error');
      }
    }

    async function refreshViewport(forceRefresh = false) {
      const bounds = mapController.getBoundsQuery();
      if (!bounds) {
        updateStatusLabel(t('mapPage.waitingBounds'));
        return;
      }

      const token = ++requestToken;
      updateStatusLabel(t('mapPage.loadingProvider', {
        provider: providerLabel(activeProvider, providerMeta),
      }));

      try {
        const data = await getPublicCameraMapCameras(bounds, activeProvider, forceRefresh);
        if (disposed || token !== requestToken) return;

        if (forceRefresh) {
          const refreshedStatus = await getCameraMapStatus();
          providerMeta = refreshedStatus.providers || providerMeta;
          bindProviderFilter();
          updateEngineNote();
        }

        renderMarkers(data.cameras || []);
        updateStatusLabel(t('mapPage.loadedCount', { count: formatNumber(data.count || 0) }));
      } catch (err) {
        if (disposed || token !== requestToken) return;
        updateStatusLabel(`${t('mapPage.unavailableTitle')}: ${err.message}`);
        renderMarkers([]);
      }
    }

    unbindViewport = mapController.onViewportChange(() => {
      if (idleTimer) {
        clearTimeout(idleTimer);
      }
      idleTimer = setTimeout(() => refreshViewport(false), 140);
    });

    container.querySelector('#camera-map-refresh-btn')?.addEventListener('click', () => refreshViewport(true));
    container.querySelector('#camera-map-reset-btn')?.addEventListener('click', () => {
      mapController.setDefaultView();
    });

    bindProviderFilter();
    updateEngineNote();
    await refreshViewport(false);
    return cleanup;
  } catch (err) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">${icon('alertTriangle', 56)}</div>
        <div class="empty-state-title">${t('mapPage.unavailableTitle')}</div>
        <div class="empty-state-desc">${escapeHtml(err.message)}</div>
      </div>
    `;
    return cleanup;
  }
}
