import { getThumbnailUrl } from '../api.js';
import { icon } from '../icons.js';
import { formatRelativeTime, formatVideoTime, t } from '../i18n.js';

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function getBadgeClass(status) {
  const map = {
    analyzing: 'badge-analyzing',
    done: 'badge-done',
    pending: 'badge-pending',
    live: 'badge-live',
    error: 'badge-pending',
  };
  return map[status] || 'badge-pending';
}

function getBadgeLabel(status) {
  const map = {
    analyzing: t('videoCard.analyzing'),
    done: t('videoCard.done'),
    pending: t('videoCard.pending'),
    live: t('videoCard.live'),
    error: t('videoCard.error'),
  };
  return map[status] || status;
}

export function createVideoCard(video, handlers = {}) {
  if (typeof handlers === 'function') {
    handlers = { onClick: handlers };
  }

  const { onClick, onDelete, onEdit } = handlers;

  const card = document.createElement('div');
  card.className = 'video-card';
  card.id = `video-card-${video.id}`;

  const thumbUrl = getThumbnailUrl(video.thumbnail);
  const thumbHtml = thumbUrl
    ? `<img src="${thumbUrl}" alt="${escapeHtml(video.title)}" loading="lazy" />`
    : `<div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;color:var(--text-tertiary);">${icon('film', 48)}</div>`;

  const timeAgo = getTimeAgo(video.upload_time);

  card.innerHTML = `
    <div class="video-card-thumbnail">
      ${thumbHtml}
      <span class="video-card-duration">${formatVideoTime(video.duration)}</span>
      <span class="video-card-badge ${getBadgeClass(video.status)}">${getBadgeLabel(video.status)}</span>
      <div class="video-card-actions" data-prevent-nav>
        <button class="video-card-action-btn" data-action="edit" title="${t('videoCard.renameTitle')}">
          ${icon('edit', 14)}
        </button>
        <button class="video-card-action-btn video-card-action-danger" data-action="delete" title="${t('videoCard.deleteTitle')}">
          ${icon('trash', 14)}
        </button>
      </div>
    </div>
    <div class="video-card-info">
      <div class="video-card-avatar" aria-hidden="true">${icon(video.video_type === 'live' ? 'radio' : 'shield', 14)}</div>
      <div class="video-card-copy">
        <div class="video-card-title" title="${escapeHtml(video.title)}">${escapeHtml(video.title)}</div>
        <div class="video-card-meta">
          <span>${video.video_type === 'live' ? t('videoCard.liveRecording') : t('videoCard.uploadedVideo')}</span>
          <span class="meta-dot"></span>
          <span>${timeAgo}</span>
        </div>
      </div>
    </div>
  `;

  card.addEventListener('click', (event) => {
    if (event.target.closest('[data-prevent-nav]')) return;
    onClick?.(video);
  });

  const editBtn = card.querySelector('[data-action="edit"]');
  if (editBtn) {
    editBtn.addEventListener('click', (event) => {
      event.stopPropagation();
      onEdit?.(video, card);
    });
  }

  const deleteBtn = card.querySelector('[data-action="delete"]');
  if (deleteBtn) {
    deleteBtn.addEventListener('click', (event) => {
      event.stopPropagation();
      onDelete?.(video, card);
    });
  }

  return card;
}

function getTimeAgo(dateStr) {
  try {
    const date = new Date(dateStr.replace(' ', 'T') + 'Z');
    return formatRelativeTime(date.getTime() / 1000);
  } catch {
    return dateStr;
  }
}
