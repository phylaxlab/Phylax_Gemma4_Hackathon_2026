/**
 * Add Camera Page - Dedicated camera setup flow.
 */

import { addCamera } from '../api.js';
import { icon } from '../icons.js';
import { t } from '../i18n.js';

export function mountAddCameraPage(container, navigate) {
  container.innerHTML = `
    <div class="upload-area">
      <div class="feed-kicker">${t('addCameraPage.kicker')}</div>
      <div class="section-title">
        ${icon('camera', 24)} ${t('addCameraPage.title')}
      </div>
      <div class="feed-subtitle" style="margin-bottom:var(--space-xl);">
        ${t('addCameraPage.subtitle')}
      </div>

      <div class="settings-card">
        <div class="input-group">
          <label class="input-label" for="camera-name">${t('addCameraPage.nameLabel')}</label>
          <input type="text" class="input-field" id="camera-name" placeholder="${t('addCameraPage.namePlaceholder')}" />
        </div>

        <div class="input-group">
          <label class="input-label" for="camera-url">${t('addCameraPage.urlLabel')}</label>
          <textarea class="input-field input-field-multiline" id="camera-url" placeholder="${t('addCameraPage.urlPlaceholder')}"></textarea>
        </div>

        <div class="input-group">
          <label class="checkbox-row">
            <input type="checkbox" id="camera-ai-enabled" checked />
            <span>${t('addCameraPage.enableAi')}</span>
          </label>
        </div>

        <div class="camera-hints">
          <div class="camera-hint-item">${icon('radio', 14)} ${t('addCameraPage.hint1')}</div>
          <div class="camera-hint-item">${icon('signal', 14)} ${t('addCameraPage.hint2')}</div>
        </div>

        <div class="player-actions" style="margin-top:var(--space-xl);">
          <button class="btn btn-secondary" id="cancel-camera-btn">${icon('arrowLeft', 16)} ${t('addCameraPage.back')}</button>
          <button class="btn btn-primary" id="save-camera-btn">${icon('plus', 16)} ${t('addCameraPage.add')}</button>
        </div>
      </div>
    </div>
  `;

  const nameInput = container.querySelector('#camera-name');
  const urlInput = container.querySelector('#camera-url');
  const aiToggle = container.querySelector('#camera-ai-enabled');
  const saveBtn = container.querySelector('#save-camera-btn');
  const cancelBtn = container.querySelector('#cancel-camera-btn');

  cancelBtn.addEventListener('click', () => navigate('/hub'));

  saveBtn.addEventListener('click', async () => {
    const name = nameInput.value.trim();
    const streamUrl = urlInput.value.trim();
    const aiEnabled = aiToggle.checked;

    if (!name) {
      showToast(t('addCameraPage.nameRequired'), 'error');
      nameInput.focus();
      return;
    }

    if (!streamUrl) {
      showToast(t('addCameraPage.urlRequired'), 'error');
      urlInput.focus();
      return;
    }

    saveBtn.disabled = true;
    saveBtn.innerHTML = `${icon('clock', 16)} ${t('addCameraPage.connecting')}`;

    try {
      const camera = await addCamera(name, streamUrl, aiEnabled);
      showToast(t('addCameraPage.added'), 'success');
      navigate(`/camera/${camera.id}`);
    } catch (error) {
      showToast(t('addCameraPage.addFailed', { message: error.message }), 'error');
      saveBtn.disabled = false;
      saveBtn.innerHTML = `${icon('plus', 16)} ${t('addCameraPage.add')}`;
    }
  });
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
