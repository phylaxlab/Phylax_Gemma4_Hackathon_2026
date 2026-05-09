/**
 * Hub Page - Manage and monitor external IP cameras.
 */

import { getCameras, updateCamera, deleteCamera } from '../api.js';
import { createCameraCard } from '../components/cameraCard.js';
import { icon } from '../icons.js';
import { t } from '../i18n.js';

export async function mountHubPage(container, navigate) {
  container.innerHTML = '<div class="loading-spinner"></div>';
  const previewCleanups = [];

  const cleanup = () => {
    previewCleanups.forEach((dispose) => dispose());
  };

  try {
    let cameras = await getCameras();

    container.innerHTML = '';
    container.classList.add('fade-in');

    const header = document.createElement('div');
    header.className = 'section-header';
    header.innerHTML = `
      <div style="display:flex; align-items:center; gap:var(--space-sm);">
        ${icon('camera', 28, 'text-primary')}
        <h1 class="section-title">${t('hub.title')}</h1>
      </div>
      <button class="btn btn-primary" id="add-cam-btn">
        ${icon('plus', 16)} ${t('hub.addCamera')}
      </button>
    `;
    container.appendChild(header);

    const grid = document.createElement('div');
    grid.className = 'video-grid camera-grid';

    if (cameras.length === 0) {
      grid.innerHTML = `
        <div class="empty-state" style="grid-column: 1 / -1; margin-top:var(--space-2xl);">
          <div class="empty-state-icon">${icon('camera', 56)}</div>
          <div class="empty-state-title">${t('hub.emptyTitle')}</div>
          <div class="empty-state-desc">${t('hub.emptyDesc')}</div>
        </div>
      `;
    } else {
      cameras.forEach((camera) => {
        const { card, disposePreview } = createCameraCard(camera, {
          onClick: (item) => navigate(`/camera/${item.id}`),
          onEdit: async (item, cardEl) => {
            const newName = prompt(t('hub.renamePrompt'), item.name);
            if (!newName || newName.trim() === '' || newName === item.name) return;

            try {
              const updated = await updateCamera(item.id, { name: newName.trim() });
              item.name = updated.name;
              const titleEl = cardEl.querySelector('.video-card-title');
              if (titleEl) {
                titleEl.textContent = updated.name;
                titleEl.title = updated.name;
              }
              showToast(t('hub.updated'), 'success');
            } catch (error) {
              showToast(t('hub.updateFailed', { message: error.message }), 'error');
            }
          },
          onDelete: async (item, cardEl) => {
            if (!confirm(t('hub.removePrompt', { title: item.name }))) return;
            try {
              await deleteCamera(item.id);
              cameras = cameras.filter((entry) => entry.id !== item.id);
              cardEl.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
              cardEl.style.opacity = '0';
              cardEl.style.transform = 'scale(0.95)';
              setTimeout(() => navigate('/hub'), 300);
              showToast(t('hub.removed'), 'success');
            } catch (error) {
              showToast(t('hub.removeFailed', { message: error.message }), 'error');
            }
          },
        });
        previewCleanups.push(disposePreview);
        grid.appendChild(card);
      });
    }

    container.appendChild(grid);

    container.querySelector('#add-cam-btn')?.addEventListener('click', () => {
      navigate('/hub/add');
    });

    return cleanup;
  } catch (error) {
    container.innerHTML = `<div class="empty-state">${t('hub.loadError', { message: error.message })}</div>`;
    return cleanup;
  }
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
