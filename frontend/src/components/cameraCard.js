import { getCameraSnapshotUrl, getCameraStreamUrl } from '../api.js';
import { icon } from '../icons.js';
import { formatRelativeTime, t } from '../i18n.js';

export function createCameraCard(camera, options = {}) {
  const {
    onClick = null,
    onEdit = null,
    onDelete = null,
    showActions = true,
    previewFps = 8,
  } = options;

  const card = document.createElement('div');
  card.className = `video-card camera-card ${camera.ai_enabled ? 'camera-card-ai-active' : ''}`;
  card.id = `camera-card-${camera.id}`;

  const thumbnail = document.createElement('div');
  thumbnail.className = 'video-card-thumbnail';

  const imgBg = document.createElement('img');
  imgBg.src = getCameraStreamUrl(camera.id, previewFps);
  imgBg.alt = camera.name;
  imgBg.loading = 'lazy';

  const fallback = document.createElement('div');
  fallback.style.width = '100%';
  fallback.style.height = '100%';
  fallback.style.display = 'none';
  fallback.style.alignItems = 'center';
  fallback.style.justifyContent = 'center';
  fallback.style.color = 'var(--text-tertiary)';
  fallback.innerHTML = icon('camera', 48);

  imgBg.addEventListener('error', () => {
    if (!imgBg.dataset.snapshotFallback) {
      imgBg.dataset.snapshotFallback = '1';
      imgBg.src = getCameraSnapshotUrl(camera.id, Date.now());
      return;
    }
    imgBg.style.display = 'none';
    fallback.style.display = 'flex';
  });

  thumbnail.appendChild(imgBg);
  thumbnail.appendChild(fallback);

  const statusBadge = document.createElement('div');
  statusBadge.className = 'video-card-badge badge-live';
  statusBadge.textContent = t('cameraCard.liveBadge');
  thumbnail.appendChild(statusBadge);

  if (camera.ai_enabled) {
    const aiBadge = document.createElement('div');
    aiBadge.className = 'camera-ai-badge';
    aiBadge.innerHTML = `${icon('brain', 12)} ${t('cameraCard.aiActive')}`;
    thumbnail.appendChild(aiBadge);
  }

  const durationLabel = document.createElement('div');
  durationLabel.className = 'video-card-duration';
  durationLabel.textContent = t('cameraCard.preview');
  thumbnail.appendChild(durationLabel);

  if (showActions) {
    const actions = document.createElement('div');
    actions.className = 'video-card-actions';
    actions.dataset.preventNav = '';
    actions.innerHTML = `
      <button class="video-card-action-btn" data-action="edit" title="${t('cameraCard.renameTitle')}">
        ${icon('edit', 14)}
      </button>
      <button class="video-card-action-btn video-card-action-danger" data-action="delete" title="${t('cameraCard.deleteTitle')}">
        ${icon('trash', 14)}
      </button>
    `;
    thumbnail.appendChild(actions);
  }

  const info = document.createElement('div');
  info.className = 'video-card-info';

  const avatar = document.createElement('div');
  avatar.className = 'video-card-avatar';
  avatar.setAttribute('aria-hidden', 'true');
  avatar.innerHTML = icon(camera.ai_enabled ? 'brain' : 'camera', 14);

  const copy = document.createElement('div');
  copy.className = 'video-card-copy';

  const title = document.createElement('div');
  title.className = 'video-card-title';
  title.textContent = camera.name;
  title.title = camera.name;

  const meta = document.createElement('div');
  meta.className = 'video-card-meta';
  const dateObj = new Date(String(camera.created_at || '').replace(' ', 'T') + 'Z');
  const timeStr = Number.isNaN(dateObj.getTime())
    ? t('cameraCard.addedRecently')
    : formatRelativeTime(dateObj.getTime() / 1000);
  meta.innerHTML = `
    <span>${camera.ai_enabled ? t('cameraCard.realtimeAi') : t('cameraCard.realtimePreview')}</span>
    <span class="meta-dot"></span>
    <span>${t('cameraCard.addedAt', { time: timeStr })}</span>
  `;

  copy.appendChild(title);
  copy.appendChild(meta);

  if (camera.last_ai_review_ts && camera.last_ai_review_summary) {
    const reviewMeta = document.createElement('div');
    reviewMeta.className = 'video-card-submeta';
    const prefix = camera.last_ai_review_is_error
      ? t('cameraCard.aiUnavailable')
      : camera.last_ai_review_is_waived
        ? t('cameraCard.lastWaived')
        : t('cameraCard.lastAnalysis');
    const summary = String(camera.last_ai_review_summary || '').trim();
    reviewMeta.textContent = `${prefix} ${formatRelativeTime(camera.last_ai_review_ts)} - ${summary}`;
    reviewMeta.title = reviewMeta.textContent;
    copy.appendChild(reviewMeta);
  }

  info.appendChild(avatar);
  info.appendChild(copy);

  card.appendChild(thumbnail);
  card.appendChild(info);

  card.addEventListener('click', (event) => {
    if (event.target.closest('[data-prevent-nav]')) return;
    onClick?.(camera);
  });

  const editBtn = card.querySelector('[data-action="edit"]');
  if (editBtn) {
    editBtn.addEventListener('click', (event) => {
      event.stopPropagation();
      onEdit?.(camera, card);
    });
  }

  const deleteBtn = card.querySelector('[data-action="delete"]');
  if (deleteBtn) {
    deleteBtn.addEventListener('click', (event) => {
      event.stopPropagation();
      onDelete?.(camera, card);
    });
  }

  return {
    card,
    disposePreview() {
      imgBg.src = '';
    },
  };
}
