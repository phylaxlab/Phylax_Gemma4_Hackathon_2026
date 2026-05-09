/**
 * Home Page - Unified monitoring overview for live cameras and videos.
 */

import { getVideos, deleteVideo, updateVideo, getCameras } from '../api.js';
import { createCameraCard } from '../components/cameraCard.js';
import { createVideoCard } from '../components/videoCard.js';
import { icon } from '../icons.js';
import { formatNumber, t } from '../i18n.js';

export async function mountHomePage(container, navigate, params = {}) {
  const activeFilter = params.filter || 'all';
  const previewCleanups = [];

  const cleanup = () => {
    previewCleanups.forEach((dispose) => dispose());
  };

  container.innerHTML = `
    <section class="home-camera-shell">
      <div class="home-camera-header">
        <div class="home-camera-copy">
          <div class="feed-kicker">${t('home.camerasKicker')}</div>
          <h2 class="section-title">${t('home.camerasTitle')}</h2>
          <p class="feed-subtitle">${t('home.camerasSubtitle')}</p>
        </div>
        <div class="home-camera-actions">
          <button class="btn btn-secondary" id="home-camera-map-btn">${icon('mapPin', 16)} ${t('home.actions.map')}</button>
          <button class="btn btn-secondary" id="home-hub-btn">${icon('externalLink', 16)} ${t('home.actions.openHub')}</button>
          <button class="btn btn-primary" id="home-add-camera-btn">${icon('plus', 16)} ${t('home.actions.addCamera')}</button>
        </div>
      </div>
      <div class="video-grid camera-grid home-camera-grid" id="home-camera-grid">
        <div class="loading-spinner"></div>
      </div>
    </section>
    <div class="filter-chips" id="home-filters">
      <button class="chip ${activeFilter === 'all' ? 'active' : ''}" data-filter="all">${t('filters.all')}</button>
      <button class="chip ${activeFilter === 'analyzed' ? 'active' : ''}" data-filter="analyzed">${t('filters.analyzed')}</button>
      <button class="chip ${activeFilter === 'pending' ? 'active' : ''}" data-filter="pending">${t('filters.pending')}</button>
    </div>
    <div class="video-grid" id="video-grid">
      <div class="loading-spinner"></div>
    </div>
  `;

  let allVideos = [];
  let allCameras = [];

  const grid = container.querySelector('#video-grid');
  const cameraGrid = container.querySelector('#home-camera-grid');

  try {
    const [videoResult, cameraResult] = await Promise.allSettled([
      getVideos(1, 50),
      getCameras(),
    ]);

    if (videoResult.status === 'fulfilled') {
      allVideos = videoResult.value.videos || [];
    }
    if (cameraResult.status === 'fulfilled') {
      allCameras = cameraResult.value || [];
    }

    if (videoResult.status !== 'fulfilled' && cameraResult.status !== 'fulfilled') {
      throw videoResult.reason || cameraResult.reason || new Error('Unable to load home data');
    }
  } catch (error) {
    console.error('Failed to load home data:', error);
    grid.innerHTML = `
      <div class="empty-state" style="grid-column: 1 / -1;">
        <div class="empty-state-icon">${icon('alertTriangle', 56)}</div>
        <div class="empty-state-title">${t('home.connectionErrorTitle')}</div>
        <div class="empty-state-desc">${t('home.connectionErrorDesc')}</div>
      </div>
    `;
    if (cameraGrid) {
      cameraGrid.innerHTML = '';
    }
    return cleanup;
  }

  renderCameraGrid();

  function renderCameraGrid() {
    if (!cameraGrid) return;
    cameraGrid.innerHTML = '';

    if (!allCameras.length) {
      cameraGrid.innerHTML = `
        <div class="empty-state" style="grid-column: 1 / -1;">
          <div class="empty-state-icon">${icon('camera', 52)}</div>
          <div class="empty-state-title">${t('home.noCamerasTitle')}</div>
          <div class="empty-state-desc">${t('home.noCamerasDesc')}</div>
        </div>
      `;
      return;
    }

    allCameras.forEach((camera) => {
      const { card, disposePreview } = createCameraCard(camera, {
        onClick: (item) => navigate(`/camera/${item.id}`),
        showActions: false,
        previewFps: 5,
      });
      previewCleanups.push(disposePreview);
      cameraGrid.appendChild(card);
    });
  }

  function renderGrid(filter) {
    grid.innerHTML = '';

    let videos = allVideos;
    if (filter && filter !== 'all') {
      if (filter === 'analyzed') {
        videos = allVideos.filter((video) => video.status === 'done');
      } else if (filter === 'pending') {
        videos = allVideos.filter((video) => video.status === 'pending' || video.status === 'error');
      }
    }

    const countEl = container.querySelector('#feed-count');
    if (countEl) {
      countEl.textContent = t('home.videoCount', { count: formatNumber(videos.length) });
    }

    if (videos.length === 0) {
      const message = filter === 'all'
        ? t('home.noVideosDesc')
        : t('home.noFilterDesc', { filter: t(`filters.${filter}`) });
      grid.innerHTML = `
        <div class="empty-state" style="grid-column: 1 / -1;">
          <div class="empty-state-icon">${icon('video', 56)}</div>
          <div class="empty-state-title">${filter === 'all' ? t('home.noVideosTitle') : t('home.nothingTitle')}</div>
          <div class="empty-state-desc">${message}</div>
          ${filter === 'all' ? `<button class="btn btn-primary" style="margin-top:var(--space-xl);" onclick="window.location.hash='#/upload'">${icon('upload', 16)} ${t('home.uploadVideo')}</button>` : ''}
        </div>
      `;
      return;
    }

    videos.forEach((video) => {
      const card = createVideoCard(video, {
        onClick: (item) => navigate(`/watch/${item.id}`),
        onEdit: async (item, cardEl) => {
          const newTitle = prompt(t('home.renameVideoPrompt'), item.title);
          if (newTitle && newTitle.trim() !== '' && newTitle !== item.title) {
            try {
              const updated = await updateVideo(item.id, { title: newTitle.trim() });
              item.title = updated.title;
              const titleEl = cardEl.querySelector('.video-card-title');
              if (titleEl) {
                titleEl.textContent = updated.title;
                titleEl.title = updated.title;
              }
              showToast(t('home.titleUpdated'), 'success');
            } catch (error) {
              showToast(t('home.renameFailed', { message: error.message }), 'error');
            }
          }
        },
        onDelete: async (item, cardEl) => {
          if (!confirm(t('home.deleteVideoPrompt', { title: item.title }))) return;
          try {
            await deleteVideo(item.id);
            allVideos = allVideos.filter((entry) => entry.id !== item.id);
            cardEl.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
            cardEl.style.opacity = '0';
            cardEl.style.transform = 'scale(0.9)';
            setTimeout(() => renderGrid(currentFilter), 300);
            showToast(t('home.videoDeleted'), 'success');
          } catch (error) {
            showToast(t('home.deleteFailed', { message: error.message }), 'error');
          }
        },
      });
      grid.appendChild(card);
    });
  }

  let currentFilter = activeFilter;
  container.querySelectorAll('#home-filters .chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      currentFilter = chip.dataset.filter;
      container.querySelectorAll('#home-filters .chip').forEach((entry) => entry.classList.remove('active'));
      chip.classList.add('active');
      renderGrid(currentFilter);
    });
  });

  container.querySelector('#home-hub-btn')?.addEventListener('click', () => navigate('/hub'));
  container.querySelector('#home-camera-map-btn')?.addEventListener('click', () => navigate('/camera-map'));
  container.querySelector('#home-add-camera-btn')?.addEventListener('click', () => navigate('/hub/add'));

  renderGrid(activeFilter);
  return cleanup;
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
