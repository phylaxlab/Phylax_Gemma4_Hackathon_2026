/**
 * Upload Page - Drag-and-drop video upload with progress tracking.
 */

import { uploadVideo, startAnalysis } from '../api.js';
import { icon } from '../icons.js';
import { t } from '../i18n.js';

const ANALYSIS_INTERVAL_STORAGE_KEY = 'phylax-analysis-interval-seconds';

export function mountUploadPage(container, navigate) {
  container.innerHTML = `
    <div class="upload-area">
      <div class="section-title">
        ${icon('upload', 24)} ${t('uploadPage.title')}
      </div>

      <div class="input-group">
        <label class="input-label" for="upload-title">${t('uploadPage.titleLabel')}</label>
        <input type="text" class="input-field" id="upload-title" placeholder="${t('uploadPage.titlePlaceholder')}" />
      </div>

      <div class="analysis-settings-card" style="margin-bottom:var(--space-lg);">
        <div class="analysis-settings-header">
          <div class="analysis-settings-title">${icon('activity', 16)} ${t('watchPage.analysis')}</div>
        </div>
        <div class="analysis-settings-body">
          <label class="analysis-settings-label" for="upload-analysis-interval">${t('watchPage.analysisInterval')}</label>
          <select id="upload-analysis-interval" class="analysis-mode-select">
            ${[1, 2, 5, 10, 15, 30, 60].map((seconds) => `
              <option value="${seconds}" ${loadAnalysisInterval() === seconds ? 'selected' : ''}>
                ${t('watchPage.intervalSeconds', { value: seconds })}
              </option>
            `).join('')}
          </select>
          <div class="analysis-settings-help">${t('watchPage.analysisIntervalHelp')}</div>
        </div>
      </div>

      <div class="upload-dropzone" id="upload-dropzone">
        <div class="upload-icon">${icon('film', 48)}</div>
        <div class="upload-text">${t('uploadPage.dropTitle')}</div>
        <div class="upload-subtext">${t('uploadPage.dropDesc')}</div>
        <input type="file" id="upload-file-input" accept="video/*" style="display:none;" />
      </div>

      <div class="upload-progress" id="upload-progress" style="display:none;">
        <div class="progress-bar-track">
          <div class="progress-bar-fill" id="upload-progress-fill" style="width:0%;"></div>
        </div>
        <div class="upload-status" id="upload-status">${t('uploadPage.uploading')}</div>
      </div>

      <div id="upload-result" style="display:none;margin-top:var(--space-xl);text-align:center;">
        <div style="margin-bottom:var(--space-md);color:var(--color-success);">${icon('checkCircle', 48)}</div>
        <div style="font-size:var(--font-size-lg);font-weight:600;margin-bottom:var(--space-sm);">${t('uploadPage.complete')}</div>
        <div style="font-size:var(--font-size-sm);color:var(--text-secondary);margin-bottom:var(--space-xs);" id="upload-result-msg"></div>
        <div style="font-size:var(--font-size-xs);color:var(--text-tertiary);margin-bottom:var(--space-xl);">${t('uploadPage.readySoon')}</div>
        <div style="display:flex;gap:var(--space-md);justify-content:center;flex-wrap:wrap;">
          <button class="btn btn-primary" id="analyze-now-btn">${icon('signal', 16)} ${t('common.analyzeNow')}</button>
          <button class="btn btn-secondary" id="watch-now-btn">${icon('play', 16)} ${t('common.watch')}</button>
          <button class="btn btn-secondary" id="upload-another-btn">${icon('upload', 16)} ${t('common.uploadAnother')}</button>
        </div>
      </div>
    </div>
  `;

  const dropzone = container.querySelector('#upload-dropzone');
  const fileInput = container.querySelector('#upload-file-input');
  const titleInput = container.querySelector('#upload-title');
  const progressSection = container.querySelector('#upload-progress');
  const progressFill = container.querySelector('#upload-progress-fill');
  const statusText = container.querySelector('#upload-status');
  const resultSection = container.querySelector('#upload-result');
  const resultMsg = container.querySelector('#upload-result-msg');

  let uploadedVideo = null;

  dropzone.addEventListener('click', () => fileInput.click());

  dropzone.addEventListener('dragover', (event) => {
    event.preventDefault();
    dropzone.classList.add('drag-over');
  });

  dropzone.addEventListener('dragleave', () => {
    dropzone.classList.remove('drag-over');
  });

  dropzone.addEventListener('drop', (event) => {
    event.preventDefault();
    dropzone.classList.remove('drag-over');
    const files = event.dataTransfer.files;
    if (files.length > 0) {
      void handleFile(files[0]);
    }
  });

  fileInput.addEventListener('change', () => {
    if (fileInput.files.length > 0) {
      void handleFile(fileInput.files[0]);
    }
  });

  async function handleFile(file) {
    const ext = file.name.split('.').pop().toLowerCase();
    const allowed = ['mp4', 'avi', 'mov', 'mkv', 'webm', 'flv'];
    if (!allowed.includes(ext)) {
      showToast(t('uploadPage.unsupportedFormat'), 'error');
      return;
    }

    if (file.size > 500 * 1024 * 1024) {
      showToast(t('uploadPage.fileTooLarge'), 'error');
      return;
    }

    dropzone.style.display = 'none';
    progressSection.style.display = 'block';

    try {
      const title = titleInput.value.trim() || undefined;

      uploadedVideo = await uploadVideo(file, title, (percent) => {
        progressFill.style.width = `${percent}%`;
        if (percent < 100) {
          statusText.textContent = `${t('uploadPage.uploading')} ${percent}%`;
        } else {
          statusText.textContent = t('uploadPage.saving');
        }
      });

      progressSection.style.display = 'none';
      resultSection.style.display = 'block';
      resultMsg.textContent = t('uploadPage.success', {
        title: uploadedVideo.title,
        size: formatSize(file.size),
      });
    } catch (error) {
      statusText.textContent = t('uploadPage.uploadFailed', { message: error.message });
      progressFill.style.background = 'var(--color-danger)';
    }
  }

  container.querySelector('#upload-result').addEventListener('click', async (event) => {
    const button = event.target.closest('button');
    if (!button || !uploadedVideo) return;

    if (button.id === 'analyze-now-btn') {
      try {
        const interval = Number(container.querySelector('#upload-analysis-interval')?.value || 10);
        localStorage.setItem(ANALYSIS_INTERVAL_STORAGE_KEY, String(interval));
        await startAnalysis(uploadedVideo.id, {
          analysis_interval_seconds: interval,
        });
        showToast(t('uploadPage.analysisStarted'), 'success');
        navigate(`/watch/${uploadedVideo.id}`);
      } catch (error) {
        showToast(t('uploadPage.actionFailed', { message: error.message }), 'error');
      }
      return;
    }

    if (button.id === 'watch-now-btn') {
      navigate(`/watch/${uploadedVideo.id}`);
      return;
    }

    if (button.id === 'upload-another-btn') {
      mountUploadPage(container, navigate);
    }
  });
}

function loadAnalysisInterval() {
  try {
    const raw = Number(localStorage.getItem(ANALYSIS_INTERVAL_STORAGE_KEY) || 10);
    const allowed = [1, 2, 5, 10, 15, 30, 60];
    return allowed.includes(raw) ? raw : 10;
  } catch {
    return 10;
  }
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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
