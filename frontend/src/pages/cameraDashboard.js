/**
 * Camera Dashboard - Live camera monitoring with replay controls.
 */

import {
  getCameraStreamUrl,
  getCameraSnapshotUrl,
  getCameraEvents,
  deleteCamera,
  getCamera,
  toggleCameraAI,
  setCameraLanguage,
  getCameraReplayBuffer,
  analyzeRecentCameraWindow,
  exportCameraInvestigationReport,
} from '../api.js';
import { createEventPanel } from '../components/eventPanel.js';
import { createRollingTimeline } from '../components/analysisTimeline.js';
import { createCameraQaPanel } from '../components/cameraQaPanel.js';
import { icon } from '../icons.js';
import { formatRelativeClock, formatRelativeTime, getLanguage, t } from '../i18n.js';

const POLL_INTERVAL = 5000;
const SNAPSHOT_FALLBACK_INTERVAL = 1000;
const CAMERA_TIMELINE_WINDOW_SEC = 300;
const CAMERA_LIVE_STREAM_FPS = 16;
const CAMERA_EVENT_FETCH_LIMIT = 80;

export async function mountCameraDashboard(container, navigate, cameraId) {
  container.innerHTML = '<div class="loading-spinner"></div>';

  let pollInterval = null;
  let replayTimer = null;
  let streamHealthTimer = null;
  let pollInFlight = false;
  let disposed = false;
  let cameraQaPanel = null;

  const cleanup = () => {
    disposed = true;
    if (pollInterval) clearInterval(pollInterval);
    if (replayTimer) clearInterval(replayTimer);
    if (streamHealthTimer) clearTimeout(streamHealthTimer);
    cameraQaPanel?.destroy();
  };

  try {
    const [camera, initialEvents, initialBuffer] = await Promise.all([
      getCamera(cameraId),
      getCameraEvents(cameraId, CAMERA_EVENT_FETCH_LIMIT),
      getCameraReplayBuffer(cameraId).catch(() => ({ frames: [], window_seconds: CAMERA_TIMELINE_WINDOW_SEC })),
    ]);

    let events = initialEvents;
    let replayBuffer = initialBuffer;
    let currentAiState = camera.ai_enabled;
    let currentAnalyzingTs = camera.current_analyzing_ts;
    let waivedCount = camera.waived_count || 0;
    let lastWaivedTs = camera.last_waived_ts || null;
    let lastWaivedSummary = camera.last_waived_summary || '';
    let lastWaivedEventType = camera.last_waived_event_type || '';
    let lastWaivedSeverity = camera.last_waived_severity || '';
    let recentAiReviews = camera.recent_ai_reviews || [];
    let mergedPanelItems = mergeCameraPanelItems(events, recentAiReviews);
    let isReplayMode = false;
    let isReplayPlaying = false;
    let replayIndex = Math.max(0, (replayBuffer.frames || []).length - 1);
    let liveStreamSrc = '';
    let liveStreamAttemptedAt = 0;
    let liveImageLoadedAt = 0;
    let liveFallbackMode = false;
    let liveFallbackActivatedAt = 0;
    let lastLiveSnapshotAt = 0;

    container.innerHTML = '';
    container.classList.add('fade-in');

    setCameraLanguage(cameraId, getLanguage()).catch(() => {});

    if (currentAiState) {
      analyzeRecentCameraWindow(cameraId).catch(() => {});
    }

    const layout = document.createElement('div');
    layout.className = 'watch-layout';

    const leftCol = document.createElement('div');
    leftCol.className = 'watch-main';

    const playerWrapper = document.createElement('div');
    playerWrapper.className = 'player-container';
    playerWrapper.id = 'camera-player-wrapper';

    const playerImage = document.createElement('img');
    playerImage.alt = camera.name;
    playerImage.style.width = '100%';
    playerImage.style.height = '100%';
    playerImage.style.objectFit = 'contain';
    playerImage.src = getCameraStreamUrl(cameraId);

    const liveBadge = document.createElement('div');
    liveBadge.className = 'live-indicator';
    liveBadge.id = 'camera-live-badge';
    liveBadge.innerHTML = `<span class="live-dot"></span>${t('common.liveUpper')}`;

    playerWrapper.appendChild(playerImage);
    playerWrapper.appendChild(liveBadge);
    leftCol.appendChild(playerWrapper);

    const replayControls = document.createElement('div');
    replayControls.className = 'camera-replay-controls';
    replayControls.innerHTML = `
      <div class="camera-replay-actions">
        <button class="icon-btn" id="camera-live-btn" title="${t('cameraPage.live')}" aria-label="${t('cameraPage.live')}">${icon('radio', 18)}</button>
        <button class="icon-btn" id="camera-play-btn" title="${t('cameraPage.play')}" aria-label="${t('cameraPage.play')}">${icon('play', 18)}</button>
        <span class="camera-replay-status" id="camera-replay-status">${t('cameraPage.watchingLive')}</span>
        <button class="icon-btn" id="camera-fullscreen-btn" title="${t('cameraPage.fullscreen')}" aria-label="${t('cameraPage.fullscreen')}">${icon('fullscreenCorners', 18)}</button>
      </div>
      <input type="range" min="0" max="0" value="0" step="1" class="camera-replay-slider" id="camera-replay-slider" />
      <div class="camera-replay-labels">
        <span>${t('cameraPage.fiveMinAgo')}</span>
        <span id="camera-replay-time">${t('cameraPage.liveStatus')}</span>
        <span>${t('cameraPage.nowLabel')}</span>
      </div>
    `;
    playerWrapper.appendChild(replayControls);

    const info = document.createElement('div');
    info.className = 'player-info';
    info.innerHTML = `
      <div class="player-summary">
        <div class="player-title-wrap">
          <h1 class="player-title">${camera.name}</h1>
          <div class="player-meta">
            <span>${t('cameraPage.ipCamera')}</span>
            <span class="meta-dot"></span>
            <span id="meta-ai-status" style="color:${currentAiState ? 'var(--accent-primary)' : 'var(--text-secondary)'}">
              ${currentAiState ? t('cameraPage.aiActive') : t('cameraPage.aiPaused')}
            </span>
          </div>
        </div>
        <div class="player-actions">
          <button class="icon-btn action-icon-btn" id="back-btn" title="${t('common.back')}" aria-label="${t('common.back')}">
            ${icon('arrowLeft', 18)}
          </button>
          <button class="icon-btn action-icon-btn" id="report-btn" title="${t('cameraPage.report')}" aria-label="${t('cameraPage.report')}">
            ${icon('folder', 18)}
          </button>
          <button class="icon-btn action-icon-btn" id="toggle-ai-btn" style="color:${currentAiState ? 'var(--color-danger)' : 'var(--color-success)'}" title="${currentAiState ? t('cameraPage.stopAi') : t('cameraPage.startAi')}" aria-label="${currentAiState ? t('cameraPage.stopAi') : t('cameraPage.startAi')}">
            ${currentAiState ? icon('xCircle', 18) : icon('play', 18)}
          </button>
          <button class="icon-btn action-icon-btn danger" id="delete-cam-btn" title="${t('cameraPage.removeCamera')}" aria-label="${t('cameraPage.removeCamera')}">
            ${icon('trash', 18)}
          </button>
        </div>
      </div>
      <div class="waived-feedback" id="waived-feedback">
        ${icon('checkCircle', 14)}
        <span id="waived-feedback-text"></span>
      </div>
    `;
    leftCol.appendChild(info);

    let timelineEl = createRollingTimeline(
      events,
      CAMERA_TIMELINE_WINDOW_SEC,
      currentAnalyzingTs,
      (event) => {
        jumpToEvent(event);
        highlightCameraEvent(event.id);
      },
    );
    leftCol.appendChild(timelineEl);

    const rightColStack = document.createElement('div');
    rightColStack.className = 'side-panel-stack';

    cameraQaPanel = createCameraQaPanel({
      cameraId,
      getCurrentTimestamp: () => {
        if (isReplayMode) {
          return replayBuffer.frames?.[replayIndex]?.timestamp_sec ?? null;
        }
        return replayBuffer.frames?.[(replayBuffer.frames || []).length - 1]?.timestamp_sec
          || null;
      },
      onSeekToEvent: (event) => {
        jumpToEvent(event);
      },
    });
    rightColStack.appendChild(cameraQaPanel.element);

    let rightCol = createEventPanel(mergedPanelItems, (event) => {
      jumpToEvent(event);
    }, currentAiState, currentAnalyzingTs);
    rightColStack.appendChild(rightCol);

    layout.appendChild(leftCol);
    layout.appendChild(rightColStack);
    container.appendChild(layout);

    const liveBtn = container.querySelector('#camera-live-btn');
    const playBtn = container.querySelector('#camera-play-btn');
    const fullscreenBtn = container.querySelector('#camera-fullscreen-btn');
    const replaySlider = container.querySelector('#camera-replay-slider');
    const replayStatus = container.querySelector('#camera-replay-status');
    const replayTime = container.querySelector('#camera-replay-time');
    const liveBadgeEl = container.querySelector('#camera-live-badge');

    playerImage.addEventListener('load', () => {
      liveImageLoadedAt = Date.now();
      if (!isReplayMode && playerImage.dataset.sourceMode === 'stream') {
        liveFallbackMode = false;
        liveFallbackActivatedAt = 0;
      }
    });

    playerImage.addEventListener('error', () => {
      if (isReplayMode) return;
      switchToLiveSnapshotFallback(true);
    });

    function getLiveStreamSrc() {
      return getCameraStreamUrl(cameraId, {
        fps: CAMERA_LIVE_STREAM_FPS,
      });
    }

    function getLiveSnapshotSrc() {
      lastLiveSnapshotAt = Date.now();
      return getCameraSnapshotUrl(cameraId, lastLiveSnapshotAt);
    }

    function refreshLiveSnapshot(force = false) {
      if (isReplayMode || !liveFallbackMode) return;
      if (!force && Date.now() - lastLiveSnapshotAt < SNAPSHOT_FALLBACK_INTERVAL) return;
      playerImage.dataset.sourceMode = 'snapshot';
      playerImage.src = getLiveSnapshotSrc();
    }

    function scheduleStreamHealthCheck() {
      if (streamHealthTimer) {
        clearTimeout(streamHealthTimer);
      }
      const requestedAt = liveStreamAttemptedAt;
      streamHealthTimer = setTimeout(() => {
        if (disposed || isReplayMode || liveFallbackMode) return;
        if (!liveImageLoadedAt || liveImageLoadedAt < requestedAt) {
          switchToLiveSnapshotFallback();
        }
      }, 2500);
    }

    function switchToLiveSnapshotFallback(force = false) {
      if (isReplayMode) return;
      if (!force && liveFallbackMode) {
        refreshLiveSnapshot();
        return;
      }
      liveFallbackMode = true;
      liveFallbackActivatedAt = Date.now();
      refreshLiveSnapshot(true);
    }

    function syncLiveStreamSource(force = false) {
      if (isReplayMode) return;
      if (liveFallbackMode && !force) {
        playerImage.dataset.sourceMode = 'snapshot';
        playerImage.src = getLiveSnapshotSrc();
        return;
      }
      const nextSrc = getLiveStreamSrc();
      if (!force && nextSrc === liveStreamSrc) return;
      liveStreamSrc = nextSrc;
      liveStreamAttemptedAt = Date.now();
      playerImage.dataset.sourceMode = 'stream';
      playerImage.src = nextSrc;
      scheduleStreamHealthCheck();
    }

    function renderStatus() {
      const toggleBtn = container.querySelector('#toggle-ai-btn');
      const statusText = container.querySelector('#meta-ai-status');

      if (toggleBtn) {
        const label = currentAiState ? t('cameraPage.stopAi') : t('cameraPage.startAi');
        toggleBtn.innerHTML = currentAiState
          ? icon('xCircle', 18)
          : icon('play', 18);
        toggleBtn.title = label;
        toggleBtn.setAttribute('aria-label', label);
        toggleBtn.style.color = currentAiState ? 'var(--color-danger)' : 'var(--color-success)';
      }

      if (statusText) {
        statusText.textContent = currentAiState ? t('cameraPage.aiActive') : t('cameraPage.aiPaused');
        statusText.style.color = currentAiState ? 'var(--accent-primary)' : 'var(--text-secondary)';
      }

      renderWaivedFeedback();
    }

    function renderWaivedFeedback() {
      const feedback = container.querySelector('#waived-feedback');
      const text = container.querySelector('#waived-feedback-text');
      if (!feedback || !text) return;

      if (!currentAiState || !lastWaivedTs) {
        feedback.classList.remove('active');
        text.textContent = '';
        return;
      }

      const eventType = lastWaivedEventType || 'normal';
      const severity = lastWaivedSeverity || 'Normal';
      const summary = lastWaivedSummary || t('cameraPage.routineScene');
      text.textContent = t('cameraPage.waived', {
        eventType,
        severity,
        time: formatRelativeTime(lastWaivedTs),
        summary,
        count: waivedCount,
      });
      feedback.classList.add('active');
    }

    function renderReplayControls() {
      const frames = replayBuffer.frames || [];
      const fullscreenLabel = document.fullscreenElement
        ? t('cameraPage.exitFullscreen')
        : t('cameraPage.fullscreen');
      fullscreenBtn.innerHTML = icon('fullscreenCorners', 18);
      fullscreenBtn.title = fullscreenLabel;
      fullscreenBtn.setAttribute('aria-label', fullscreenLabel);

      replaySlider.max = Math.max(0, frames.length - 1);
      replaySlider.value = frames.length ? replayIndex : 0;
      replaySlider.disabled = frames.length === 0;
      const progressPct = frames.length > 1 ? (replayIndex / (frames.length - 1)) * 100 : 100;
      replaySlider.style.setProperty('--progress', `${progressPct}%`);

      if (!frames.length) {
        replayStatus.textContent = t('cameraPage.replayWarmup');
        replayTime.textContent = t('cameraPage.liveStatus');
        cameraQaPanel?.refreshAnchor();
        return;
      }

      if (isReplayMode) {
        const frame = frames[replayIndex];
        playerImage.dataset.sourceMode = 'replay';
        playerImage.src = `${frame.url}?t=${Date.now()}`;
        liveBadgeEl.style.display = 'none';
        replayStatus.textContent = isReplayPlaying ? t('cameraPage.replayPlaying') : t('cameraPage.replayPaused');
        replayTime.textContent = formatReplayLabel(frame.timestamp_sec, frames[frames.length - 1].timestamp_sec);
        playBtn.innerHTML = isReplayPlaying
          ? icon('stop', 18)
          : icon('play', 18);
        playBtn.title = isReplayPlaying ? t('cameraPage.pause') : t('cameraPage.play');
        playBtn.setAttribute('aria-label', playBtn.title);
        cameraQaPanel?.refreshAnchor();
      } else {
        syncLiveStreamSource();
        liveBadgeEl.style.display = '';
        replayStatus.textContent = t('cameraPage.watchingLive');
        replayTime.textContent = t('cameraPage.liveStatus');
        playBtn.innerHTML = icon('play', 18);
        playBtn.title = t('cameraPage.play');
        playBtn.setAttribute('aria-label', t('cameraPage.play'));
        cameraQaPanel?.refreshAnchor();
      }
    }

    function stopReplayPlayback() {
      isReplayPlaying = false;
      if (replayTimer) {
        clearInterval(replayTimer);
        replayTimer = null;
      }
      renderReplayControls();
    }

    function startReplayPlayback() {
      const frames = replayBuffer.frames || [];
      if (!frames.length) return;

      isReplayMode = true;
      isReplayPlaying = true;
      if (replayTimer) clearInterval(replayTimer);

      replayTimer = setInterval(() => {
        if (disposed) {
          stopReplayPlayback();
          return;
        }

        if (replayIndex >= frames.length - 1) {
          stopReplayPlayback();
          return;
        }

        replayIndex += 1;
        renderReplayControls();
      }, 500);

      renderReplayControls();
    }

    function jumpToEvent(event) {
      const frames = replayBuffer.frames || [];
      if (!frames.length) return;

      const oldestTs = frames[0]?.timestamp_sec ?? 0;
      const latestTs = frames[frames.length - 1]?.timestamp_sec ?? 0;
      if (event.timestamp_sec < oldestTs || event.timestamp_sec > latestTs) {
        showToast(t('cameraPage.outsideWindow'), 'info');
        return;
      }

      let nearestIndex = 0;
      let nearestDiff = Infinity;
      frames.forEach((frame, index) => {
        const diff = Math.abs(frame.timestamp_sec - event.timestamp_sec);
        if (diff < nearestDiff) {
          nearestDiff = diff;
          nearestIndex = index;
        }
      });

      replayIndex = nearestIndex;
      isReplayMode = true;
      stopReplayPlayback();
      renderReplayControls();
    }

    container.querySelector('#back-btn')?.addEventListener('click', () => {
      navigate('/hub');
    });

    container.querySelector('#report-btn')?.addEventListener('click', async (event) => {
      const button = event.currentTarget;
      const originalIcon = button.innerHTML;
      const originalTitle = button.title;
      button.innerHTML = icon('clock', 18);
      button.title = t('cameraPage.reporting');
      button.setAttribute('aria-label', t('cameraPage.reporting'));
      button.disabled = true;

      try {
        const payload = cameraQaPanel?.buildReportPayload?.() || { messages: [] };
        const result = await exportCameraInvestigationReport(cameraId, payload);
        downloadBlob(result.blob, result.filename);
        button.innerHTML = icon('checkCircle', 18);
        button.title = t('cameraPage.reportReady');
        button.setAttribute('aria-label', t('cameraPage.reportReady'));
        showToast(t('cameraPage.reportReady'), 'success');
      } catch (error) {
        showToast(t('cameraPage.reportFailed', { message: error.message }), 'error');
        button.innerHTML = originalIcon;
        button.title = originalTitle;
        button.setAttribute('aria-label', originalTitle);
      } finally {
        setTimeout(() => {
          button.innerHTML = originalIcon;
          button.title = originalTitle;
          button.setAttribute('aria-label', originalTitle);
          button.disabled = false;
        }, 2500);
      }
    });

    container.querySelector('#toggle-ai-btn')?.addEventListener('click', async (event) => {
      const button = event.currentTarget;
      button.disabled = true;

      try {
        const updated = await toggleCameraAI(cameraId, !currentAiState);
        currentAiState = updated.ai_enabled;
        if (currentAiState) {
          analyzeRecentCameraWindow(cameraId).catch(() => {});
        }
        renderStatus();
        showToast(currentAiState ? t('cameraPage.enabled') : t('cameraPage.pausedToast'), 'success');
      } catch (error) {
        showToast(t('cameraPage.toggleFailed', { message: error.message }), 'error');
      } finally {
        button.disabled = false;
      }
    });

    container.querySelector('#delete-cam-btn')?.addEventListener('click', async () => {
      if (!confirm(t('cameraPage.deletePrompt'))) return;

      try {
        await deleteCamera(cameraId);
        navigate('/hub');
      } catch (error) {
        showToast(t('cameraPage.removeFailed', { message: error.message }), 'error');
      }
    });

    liveBtn.addEventListener('click', () => {
      stopReplayPlayback();
      isReplayMode = false;
      liveFallbackMode = false;
      liveFallbackActivatedAt = 0;
      replayIndex = Math.max(0, (replayBuffer.frames || []).length - 1);
      renderReplayControls();
    });

    playBtn.addEventListener('click', () => {
      if (isReplayPlaying) {
        stopReplayPlayback();
        return;
      }
      startReplayPlayback();
    });

    replaySlider.addEventListener('input', (event) => {
      replayIndex = Number(event.target.value);
      isReplayMode = true;
      stopReplayPlayback();
      renderReplayControls();
    });

    fullscreenBtn.addEventListener('click', async () => {
      if (!document.fullscreenElement) {
        await playerWrapper.requestFullscreen?.();
      } else {
        await document.exitFullscreen?.();
      }
    });

    document.addEventListener('fullscreenchange', renderReplayControls);

    pollInterval = setInterval(async () => {
      try {
        if (disposed || pollInFlight) return;
        pollInFlight = true;

        const [newEvents, camStatus, newBuffer] = await Promise.all([
          getCameraEvents(cameraId, CAMERA_EVENT_FETCH_LIMIT),
          getCamera(cameraId),
          getCameraReplayBuffer(cameraId).catch(() => replayBuffer),
        ]);

        const prevFrameCount = (replayBuffer.frames || []).length;
        const newFrameCount = (newBuffer.frames || []).length;
        const prevLatestTs = replayBuffer.latest_timestamp_sec;
        const nextReviews = camStatus.recent_ai_reviews || [];
        const currentReviewId = recentAiReviews[0]?.id ?? null;
        const nextReviewId = nextReviews[0]?.id ?? null;

        const eventDataChanged =
          newEvents.length !== events.length ||
          (newEvents[0] && events[0] && newEvents[0].id !== events[0].id) ||
          camStatus.last_waived_ts !== lastWaivedTs ||
          (camStatus.waived_count || 0) !== waivedCount ||
          nextReviewId !== currentReviewId;

        const replayDataChanged =
          newFrameCount !== prevFrameCount ||
          newBuffer.latest_timestamp_sec !== prevLatestTs;

        const statusChanged =
          camStatus.ai_enabled !== currentAiState ||
          camStatus.current_analyzing_ts !== currentAnalyzingTs;

        currentAiState = camStatus.ai_enabled;
        currentAnalyzingTs = camStatus.current_analyzing_ts;
        waivedCount = camStatus.waived_count || 0;
        lastWaivedTs = camStatus.last_waived_ts || null;
        lastWaivedSummary = camStatus.last_waived_summary || '';
        lastWaivedEventType = camStatus.last_waived_event_type || '';
        lastWaivedSeverity = camStatus.last_waived_severity || '';
        recentAiReviews = nextReviews;
        mergedPanelItems = mergeCameraPanelItems(newEvents, nextReviews);
        replayBuffer = newBuffer;

        if (!isReplayMode) {
          replayIndex = Math.max(0, newFrameCount - 1);
        } else if (replayIndex >= newFrameCount) {
          replayIndex = Math.max(0, newFrameCount - 1);
        }

        if (!isReplayMode && liveFallbackMode && Date.now() - liveFallbackActivatedAt >= 12000) {
          liveFallbackMode = false;
          syncLiveStreamSource(true);
        }

        renderStatus();
        renderReplayControls();

        if (eventDataChanged || statusChanged || replayDataChanged) {
          events = newEvents;

          const newTimelineEl = createRollingTimeline(
            events,
            CAMERA_TIMELINE_WINDOW_SEC,
            currentAnalyzingTs,
            (event) => {
              jumpToEvent(event);
              highlightCameraEvent(event.id);
            },
          );
          leftCol.replaceChild(newTimelineEl, timelineEl);
          timelineEl = newTimelineEl;
        }

        if (eventDataChanged) {
          const newRightCol = createEventPanel(mergedPanelItems, (event) => {
            jumpToEvent(event);
          }, currentAiState, currentAnalyzingTs);
          rightColStack.replaceChild(newRightCol, rightCol);
          rightCol = newRightCol;
        }
      } catch (error) {
        console.error('Polling error', error);
      } finally {
        pollInFlight = false;
      }
    }, POLL_INTERVAL);

    renderStatus();
    syncLiveStreamSource(true);
    renderReplayControls();

    return () => {
      document.removeEventListener('fullscreenchange', renderReplayControls);
      cleanup();
    };
  } catch (error) {
    const message = String(error?.message || '');
    if (message.startsWith('HTTP 404')) {
      container.innerHTML = `
          <div class="empty-state">
            <div class="empty-state-icon">${icon('camera', 56)}</div>
            <div class="empty-state-title">${t('watchPage.notFoundTitle')}</div>
          <div class="empty-state-desc">${message}</div>
          <button class="btn btn-primary" id="camera-missing-back-btn">${icon('arrowLeft', 16)} ${t('common.back')}</button>
        </div>
      `;
      container.querySelector('#camera-missing-back-btn')?.addEventListener('click', () => navigate('/hub'));
      return cleanup;
    }
    container.innerHTML = `<div class="empty-state">${t('cameraPage.errorLoading', { message: error.message })}</div>`;
    return cleanup;
  }
}

function formatReplayLabel(frameTimestamp, latestTimestamp) {
  const delta = Math.max(0, Math.round(latestTimestamp - frameTimestamp));
  const minutes = Math.floor(delta / 60);
  const seconds = delta % 60;
  if (delta === 0) return t('cameraPage.nowLabel');
  return `${minutes}:${String(seconds).padStart(2, '0')} ${t('common.ago')}`;
}

function mergeCameraPanelItems(events, reviews) {
  const waivedReviews = (reviews || [])
    .filter((review) => review.is_waived || review.is_error)
    .map((review) => ({
      ...review,
      id: review.id || -Math.round(review.timestamp_sec * 1000),
      summary: review.is_error
        ? review.summary || t('cameraPage.reviewUnavailable')
        : review.summary || review.frame_observation || t('cameraPage.routineScene'),
      description: review.temporal_assessment || review.description || review.frame_observation || '',
    }));

  return [...waivedReviews, ...(events || [])]
    .sort((a, b) => (b.timestamp_sec || 0) - (a.timestamp_sec || 0));
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

function highlightCameraEvent(eventId) {
  const panel = document.getElementById('event-panel');
  if (!panel) return;

  panel.querySelectorAll('.event-item').forEach((element) => {
    element.classList.remove('active');
  });

  const target = document.getElementById(`event-item-${eventId}`);
  if (target) {
    target.classList.add('active');
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
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
