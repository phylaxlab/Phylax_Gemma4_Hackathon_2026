/**
 * Phylax - Main Application Entry Point
 * Hash-based SPA router with page lifecycle management.
 */

import './style.css';
import { renderHeader } from './components/header.js';
import { renderSidebar, updateSidebarActive } from './components/sidebar.js';
import { mountHomePage } from './pages/home.js';
import { mountWatchPage } from './pages/watch.js';
import { mountUploadPage } from './pages/upload.js';
import { mountHubPage } from './pages/hub.js';
import { mountCameraDashboard } from './pages/cameraDashboard.js';
import { mountSearchPage } from './pages/search.js';
import { mountAddCameraPage } from './pages/addCamera.js';
import { mountCameraMapPage } from './pages/cameraMap.js';
import { subscribeLanguage, t } from './i18n.js';

let currentPage = null;
let currentCleanup = null;
let currentHeaderCleanup = null;
let currentRouteParams = {};
let appRoot = null;
let routeCounter = 0;

function navigate(route, params = {}) {
  window.__navParams = params;

  const newHash = `#${route}`;
  if (window.location.hash === newHash || (!window.location.hash && newHash === '#/')) {
    void handleRoute();
  } else {
    window.location.hash = newHash;
  }
}

function parseHash() {
  const hash = window.location.hash.slice(1) || '/';
  const parts = hash.split('?');
  const path = parts[0];
  const queryString = parts[1] || '';

  const queryParams = {};
  if (queryString) {
    queryString.split('&').forEach((pair) => {
      const [key, val] = pair.split('=');
      queryParams[decodeURIComponent(key)] = decodeURIComponent(val || '');
    });
  }

  return { path, queryParams };
}

async function handleRoute() {
  const routeId = ++routeCounter;

  const { path, queryParams } = parseHash();
  const params = { ...queryParams, ...(window.__navParams || {}) };
  window.__navParams = null;
  currentRouteParams = params;

  const mainContent = document.getElementById('main-content');
  if (!mainContent) return;

  if (typeof currentCleanup === 'function') {
    currentCleanup();
    currentCleanup = null;
  }

  mainContent.innerHTML = '';
  currentPage = path;

  const baseRoute = '/' + (path.split('/')[1] || '');
  updateSidebarActive(baseRoute === '/' ? '/' : `/${path.split('/')[1]}`);

  if (path === '/' || path === '') {
    const cleanup = await mountHomePage(mainContent, navigate, params);
    if (routeId === routeCounter && typeof cleanup === 'function') {
      currentCleanup = cleanup;
    }
    return;
  }

  if (path.startsWith('/watch/')) {
    const videoId = parseInt(path.split('/')[2], 10);
    if (!Number.isNaN(videoId)) {
      const cleanup = await mountWatchPage(mainContent, navigate, videoId);
      if (routeId === routeCounter && typeof cleanup === 'function') {
        currentCleanup = cleanup;
      }
    }
    return;
  }

  if (path === '/upload') {
    const cleanup = mountUploadPage(mainContent, navigate);
    if (routeId === routeCounter && typeof cleanup === 'function') {
      currentCleanup = cleanup;
    }
    return;
  }

  if (path === '/live') {
    navigate('/');
    return;
  }

  if (path === '/camera-map') {
    const cleanup = await mountCameraMapPage(mainContent, navigate);
    if (routeId === routeCounter && typeof cleanup === 'function') {
      currentCleanup = cleanup;
    }
    return;
  }

  if (path === '/hub') {
    const cleanup = await mountHubPage(mainContent, navigate);
    if (routeId === routeCounter && typeof cleanup === 'function') {
      currentCleanup = cleanup;
    }
    return;
  }

  if (path === '/hub/add') {
    const cleanup = mountAddCameraPage(mainContent, navigate);
    if (routeId === routeCounter && typeof cleanup === 'function') {
      currentCleanup = cleanup;
    }
    return;
  }

  if (path.startsWith('/camera/')) {
    const cameraId = parseInt(path.split('/')[2], 10);
    if (!Number.isNaN(cameraId)) {
      const cleanup = await mountCameraDashboard(mainContent, navigate, cameraId);
      if (routeId === routeCounter && typeof cleanup === 'function') {
        currentCleanup = cleanup;
      }
    }
    return;
  }

  if (path === '/search') {
    const cleanup = mountSearchPage(mainContent, navigate, params.q || '');
    if (routeId === routeCounter && typeof cleanup === 'function') {
      currentCleanup = cleanup;
    }
    return;
  }

  mainContent.innerHTML = `
    <div class="empty-state">
      <div class="empty-state-icon">${icon404()}</div>
      <div class="empty-state-title">${t('route404.title')}</div>
      <div class="empty-state-desc">${t('route404.desc')}</div>
      <button class="btn btn-primary" style="margin-top:var(--space-xl);" onclick="window.location.hash='#/'">${t('route404.action')}</button>
    </div>
  `;
}

function icon404() {
  return `<svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M16 16s-1.5-2-4-2-4 2-4 2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg>`;
}

function renderShell() {
  if (!appRoot) return;

  appRoot.innerHTML = '';

  const header = renderHeader(appRoot, {
    onSearch: (query) => navigate('/search', { q: query }),
    onLogoClick: () => navigate('/'),
    onUploadClick: () => navigate('/upload'),
  });
  currentHeaderCleanup = header?.cleanup || null;

  const layout = document.createElement('div');
  layout.className = 'layout';

  renderSidebar(layout, '/', (route, params) => navigate(route, params));

  const mainContent = document.createElement('main');
  mainContent.className = 'main-content';
  mainContent.id = 'main-content';
  layout.appendChild(mainContent);

  appRoot.appendChild(layout);
}

async function rerenderApp() {
  if (typeof currentCleanup === 'function') {
    currentCleanup();
    currentCleanup = null;
  }

  if (typeof currentHeaderCleanup === 'function') {
    currentHeaderCleanup();
    currentHeaderCleanup = null;
  }

  window.__navParams = currentRouteParams;
  renderShell();
  await handleRoute();
}

function init() {
  appRoot = document.getElementById('app');
  if (!appRoot) return;

  renderShell();
  window.addEventListener('hashchange', handleRoute);
  subscribeLanguage(() => {
    void rerenderApp();
  });
  void handleRoute();
}

init();
