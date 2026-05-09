/**
 * Watch Page - Video player with AI analysis timeline and event panel.
 */

import {
  getVideo,
  getAnalysisEvents,
  startAnalysis,
  getAnalysisStatus,
  deleteVideo,
  updateVideo,
  deleteAnalysisEvents,
  exportVideoInvestigationReport,
} from '../api.js';
import { createVideoPlayer } from '../components/videoPlayer.js';
import { createAnalysisTimeline } from '../components/analysisTimeline.js';
import { createEventPanel, highlightEvent } from '../components/eventPanel.js';
import { createVideoQaPanel } from '../components/videoQaPanel.js';
import { icon } from '../icons.js';
import { formatDurationClock, t } from '../i18n.js';

const POLL_INTERVAL = 3000;
const MOTION_FILTER_STORAGE_KEY = 'phylax-motion-filter';
const ANALYSIS_DETAIL_STORAGE_KEY = 'phylax-analysis-detail-mode';
const ANALYSIS_INTERVAL_STORAGE_KEY = 'phylax-analysis-interval-seconds';

export async function mountWatchPage(container, navigate, videoId) {
  container.innerHTML = '<div class="loading-spinner"></div>';

  let pollInterval = null;
  let videoQaPanel = null;
  let qaAnchorRefreshHandler = null;
  let qaAnchorVideoEl = null;
  let playerController = null;

  const cleanup = () => {
    if (pollInterval) {
      clearInterval(pollInterval);
      pollInterval = null;
    }
    if (qaAnchorVideoEl && qaAnchorRefreshHandler) {
      qaAnchorVideoEl.removeEventListener('timeupdate', qaAnchorRefreshHandler);
      qaAnchorVideoEl.removeEventListener('loadedmetadata', qaAnchorRefreshHandler);
    }
    playerController?.destroy?.();
    videoQaPanel?.destroy();
  };

  try {
    const savedMotionSettings = loadMotionSettings();
    const savedDetailMode = loadDetailMode();
    const savedAnalysisInterval = loadAnalysisInterval();
    const [video, events] = await Promise.all([
      getVideo(videoId),
      getAnalysisEvents(videoId),
    ]);

    container.innerHTML = '';
    container.classList.add('fade-in');

    const layout = document.createElement('div');
    layout.className = 'watch-layout';
    const leftCol = document.createElement('div');

    const { element: playerEl, videoEl, seekTo, destroy } = createVideoPlayer(videoId);
    playerController = { destroy };
    leftCol.appendChild(playerEl);

    qaAnchorRefreshHandler = () => videoQaPanel?.refreshAnchor();
    qaAnchorVideoEl = videoEl;
    videoEl.addEventListener('timeupdate', qaAnchorRefreshHandler);
    videoEl.addEventListener('loadedmetadata', qaAnchorRefreshHandler);

    const timeline = createAnalysisTimeline(events, video.duration, (event) => {
      seekTo(event.timestamp_sec);
      highlightEvent(event.id);
    });
    leftCol.appendChild(timeline);

    const statusClass = video.status === 'done'
      ? 'severity-low'
      : video.status === 'error'
        ? 'severity-high'
        : 'severity-medium';

    const statusLabel = getVideoStatusLabel(video.status);

    const info = document.createElement('div');
    info.className = 'player-info';
    info.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:flex-start;">
        <h1 class="player-title" id="video-title-display">${video.title}</h1>
        <button class="btn btn-secondary" id="edit-title-btn" title="${t('watchPage.titleEdit')}" style="padding:var(--space-sm); margin-left:var(--space-md); border:none;">
          ${icon('edit', 18)}
        </button>
      </div>
      <div class="player-meta">
        <span>${video.video_type === 'live' ? t('videoCard.liveRecording') : t('watchPage.uploaded')}</span>
        <span class="meta-dot"></span>
        <span>${formatDurationClock(video.duration)}</span>
        <span class="meta-dot"></span>
        <span>${t('watchPage.status')}: <strong class="${statusClass}">${statusLabel}</strong></span>
      </div>
      <div class="analysis-settings-card">
        <div class="analysis-settings-header">
          <div class="analysis-settings-title">${icon('activity', 16)} ${t('watchPage.analysis')}</div>
        </div>
        <div class="analysis-settings-body">
          <label class="analysis-settings-label" for="analysis-detail-mode">${t('watchPage.detailMode')}</label>
          <select id="analysis-detail-mode" class="analysis-mode-select">
            <option value="careful" ${savedDetailMode === 'careful' ? 'selected' : ''}>${t('watchPage.careful')}</option>
            <option value="fast" ${savedDetailMode === 'fast' ? 'selected' : ''}>${t('watchPage.fast')}</option>
          </select>
          <div class="analysis-settings-help">${t('watchPage.detailHelp')}</div>
          <div class="analysis-settings-divider"></div>
          <label class="analysis-settings-label" for="analysis-interval-seconds">${t('watchPage.analysisInterval')}</label>
          <select id="analysis-interval-seconds" class="analysis-mode-select">
            ${[1, 2, 5, 10, 15, 30, 60].map((seconds) => `
              <option value="${seconds}" ${savedAnalysisInterval === seconds ? 'selected' : ''}>
                ${t('watchPage.intervalSeconds', { value: seconds })}
              </option>
            `).join('')}
          </select>
          <div class="analysis-settings-help">${t('watchPage.analysisIntervalHelp')}</div>
          <div class="analysis-settings-divider"></div>
          <div class="analysis-settings-inline">
            <div class="analysis-settings-subtitle">${t('watchPage.motionFilter')}</div>
            <label class="analysis-settings-toggle">
              <input type="checkbox" id="motion-filter-enabled" ${savedMotionSettings.enabled ? 'checked' : ''} />
              <span>${t('watchPage.enable')}</span>
            </label>
          </div>
          <label class="analysis-settings-label" for="motion-threshold">
            ${t('watchPage.threshold', { value: savedMotionSettings.threshold })}
          </label>
          <input
            type="range"
            min="0"
            max="10"
            step="1"
            value="${savedMotionSettings.threshold}"
            id="motion-threshold"
            class="analysis-threshold-slider"
            ${savedMotionSettings.enabled ? '' : 'disabled'}
          />
          <div class="analysis-settings-help">${t('watchPage.motionHelp')}</div>
        </div>
      </div>
      <div class="player-actions" id="player-actions">
        ${video.status === 'pending' || video.status === 'error' ? `
          <button class="btn btn-primary" id="start-analysis-btn">
            ${icon('signal', 16)} ${video.status === 'error' ? t('watchPage.retryAnalysis') : t('watchPage.startAnalysis')}
          </button>
        ` : ''}
        ${video.status === 'analyzing' ? `
          <button class="btn btn-secondary" disabled style="display:flex;align-items:center;gap:var(--space-sm);">
            <div class="loading-spinner" style="width:16px;height:16px;margin:0;border-width:2px;"></div>
            ${t('watchPage.analyzing')} <span id="analysis-progress">0</span>%
          </button>
        ` : ''}
        ${video.status === 'done' ? `
          <button class="btn btn-secondary" id="reanalyze-btn" title="${t('watchPage.reanalyze')}">
            ${icon('signal', 16)} ${t('watchPage.reanalyze')}
          </button>
        ` : ''}
        <button class="btn btn-secondary" id="report-btn">
          ${icon('folder', 16)} ${t('watchPage.report')}
        </button>
        <button class="btn btn-secondary" id="back-btn">
          ${icon('arrowLeft', 16)} ${t('common.back')}
        </button>
        <button class="btn btn-secondary" id="delete-video-btn" style="color:var(--color-danger);">
          ${icon('trash', 16)} ${t('common.delete')}
        </button>
      </div>
    `;
    leftCol.appendChild(info);

    const rightColStack = document.createElement('div');
    rightColStack.className = 'side-panel-stack';

    videoQaPanel = createVideoQaPanel({
      videoId,
      getCurrentTimestamp: () => videoEl.currentTime,
      onSeekToEvent: (event) => {
        seekTo(event.timestamp_sec);
        if (event.event_id != null) {
          highlightEvent(event.event_id);
        }
      },
    });
    rightColStack.appendChild(videoQaPanel.element);

    const eventPanel = createEventPanel(events, (event) => {
      seekTo(event.timestamp_sec);
    });
    rightColStack.appendChild(eventPanel);
    videoQaPanel?.refreshAnchor();

    layout.appendChild(leftCol);
    layout.appendChild(rightColStack);
    container.appendChild(layout);

    const startBtn = container.querySelector('#start-analysis-btn');
    const detailModeSelect = container.querySelector('#analysis-detail-mode');
    const analysisIntervalSelect = container.querySelector('#analysis-interval-seconds');
    const motionToggle = container.querySelector('#motion-filter-enabled');
    const motionThreshold = container.querySelector('#motion-threshold');

    function getMotionSettings() {
      return {
        detail_mode: detailModeSelect?.value || 'careful',
        analysis_interval_seconds: Number(analysisIntervalSelect?.value || 10),
        motion_filter_enabled: !!motionToggle?.checked,
        motion_threshold: Number(motionThreshold?.value || 0),
      };
    }

    function persistMotionSettings() {
      const settings = getMotionSettings();
      localStorage.setItem(MOTION_FILTER_STORAGE_KEY, JSON.stringify({
        enabled: settings.motion_filter_enabled,
        threshold: settings.motion_threshold,
      }));
      localStorage.setItem(ANALYSIS_DETAIL_STORAGE_KEY, settings.detail_mode);
      localStorage.setItem(ANALYSIS_INTERVAL_STORAGE_KEY, String(settings.analysis_interval_seconds));
    }

    detailModeSelect?.addEventListener('change', persistMotionSettings);
    analysisIntervalSelect?.addEventListener('change', persistMotionSettings);

    motionToggle?.addEventListener('change', () => {
      motionThreshold.disabled = !motionToggle.checked;
      const label = container.querySelector('label[for="motion-threshold"]');
      if (label) {
        label.textContent = t('watchPage.threshold', { value: motionThreshold.value });
      }
      persistMotionSettings();
    });

    motionThreshold?.addEventListener('input', () => {
      const label = container.querySelector('label[for="motion-threshold"]');
      if (label) {
        label.textContent = t('watchPage.threshold', { value: motionThreshold.value });
      }
      persistMotionSettings();
    });

    if (startBtn) {
      startBtn.addEventListener('click', async () => {
        try {
          await startAnalysis(videoId, getMotionSettings());
          showToast(t('watchPage.analysisStarted'), 'success');
          navigate(`/watch/${videoId}`);
        } catch (error) {
          showToast(t('watchPage.analysisFailed', { message: error.message }), 'error');
        }
      });
    }

    const reanalyzeBtn = container.querySelector('#reanalyze-btn');
    if (reanalyzeBtn) {
      reanalyzeBtn.addEventListener('click', async () => {
        if (!confirm(t('watchPage.reanalysisPrompt'))) return;
        try {
          await deleteAnalysisEvents(videoId);
          await startAnalysis(videoId, getMotionSettings());
          showToast(t('watchPage.reanalysisStarted'), 'success');
          navigate(`/watch/${videoId}`);
        } catch (error) {
          showToast(t('watchPage.genericFailed', { message: error.message }), 'error');
        }
      });
    }

    container.querySelector('#back-btn')?.addEventListener('click', () => {
      navigate('/');
    });

    const editBtn = container.querySelector('#edit-title-btn');
    const titleDisplay = container.querySelector('#video-title-display');
    if (editBtn && titleDisplay) {
      editBtn.addEventListener('click', async () => {
        const newTitle = prompt(t('watchPage.renamePrompt'), video.title);
        if (newTitle && newTitle.trim() !== '' && newTitle !== video.title) {
          try {
            await updateVideo(videoId, { title: newTitle.trim() });
            video.title = newTitle.trim();
            titleDisplay.textContent = video.title;
            showToast(t('watchPage.titleUpdated'), 'success');
          } catch (error) {
            showToast(t('watchPage.updateFailed', { message: error.message }), 'error');
          }
        }
      });
    }

    const deleteBtn = container.querySelector('#delete-video-btn');
    if (deleteBtn) {
      deleteBtn.addEventListener('click', async () => {
        if (!confirm(t('watchPage.deletePrompt'))) return;
        try {
          await deleteVideo(videoId);
          showToast(t('watchPage.deleted'), 'success');
          navigate('/');
        } catch (error) {
          showToast(t('watchPage.deleteFailed', { message: error.message }), 'error');
        }
      });
    }

    container.querySelector('#report-btn')?.addEventListener('click', async (event) => {
      const button = event.currentTarget;
      const originalText = button.innerHTML;
      button.innerHTML = `${icon('clock', 16)} ${t('watchPage.reporting')}`;
      button.disabled = true;

      try {
        const payload = videoQaPanel?.buildReportPayload?.() || { messages: [] };
        const result = await exportVideoInvestigationReport(videoId, payload);
        downloadBlob(result.blob, result.filename);
        button.innerHTML = `<span style="color: var(--color-success)">${icon('checkCircle', 16)} ${t('watchPage.reportReady')}</span>`;
        showToast(t('watchPage.reportReady'), 'success');
      } catch (error) {
        showToast(t('watchPage.reportFailed', { message: error.message }), 'error');
        button.innerHTML = originalText;
      } finally {
        setTimeout(() => {
          button.innerHTML = originalText;
          button.disabled = false;
        }, 2500);
      }
    });

    if (video.status === 'analyzing') {
      pollInterval = startProgressPolling(container, navigate, videoId);
    }

    return cleanup;
  } catch (error) {
    console.error('Failed to load video:', error);
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">${icon('alertTriangle', 56)}</div>
        <div class="empty-state-title">${t('watchPage.notFoundTitle')}</div>
        <div class="empty-state-desc">${error.message}</div>
        <button class="btn btn-primary" style="margin-top:var(--space-xl);" onclick="window.location.hash='#/'">${icon('arrowLeft', 16)} ${t('watchPage.goHome')}</button>
      </div>
    `;
    return cleanup;
  }
}

function startProgressPolling(container, navigate, videoId) {
  const interval = setInterval(async () => {
    try {
      const status = await getAnalysisStatus(videoId);
      const progressEl = container.querySelector('#analysis-progress');

      if (progressEl) {
        progressEl.textContent = Math.round(status.progress * 100);
      }

      if (status.status === 'done' || status.status === 'error') {
        clearInterval(interval);
        navigate(`/watch/${videoId}`);
      }
    } catch {
      clearInterval(interval);
    }
  }, POLL_INTERVAL);

  return interval;
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

function loadMotionSettings() {
  try {
    const raw = localStorage.getItem(MOTION_FILTER_STORAGE_KEY);
    if (!raw) {
      return { enabled: false, threshold: 4 };
    }
    const parsed = JSON.parse(raw);
    return {
      enabled: !!parsed.enabled,
      threshold: Math.max(0, Math.min(10, Number(parsed.threshold ?? 4))),
    };
  } catch {
    return { enabled: false, threshold: 4 };
  }
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename || 'investigation-report.pdf';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function loadDetailMode() {
  try {
    const raw = localStorage.getItem(ANALYSIS_DETAIL_STORAGE_KEY);
    return raw === 'fast' ? 'fast' : 'careful';
  } catch {
    return 'careful';
  }
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

function getVideoStatusLabel(status) {
  if (status === 'done') return t('watchPage.reviewed');
  if (status === 'error') return t('watchPage.analysisFailedLabel');
  if (status === 'analyzing') return t('videoCard.analyzing');
  if (status === 'pending') return t('videoCard.pending');
  return status;
}
