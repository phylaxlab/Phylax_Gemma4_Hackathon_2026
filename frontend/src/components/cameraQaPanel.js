import { askCameraQuestion } from '../api.js';
import { createTimelineQaPanel } from './timelineQaPanel.js';
import { formatRelativeClock, getLanguage, t, tList } from '../i18n.js';

export function createCameraQaPanel({
  cameraId,
  getCurrentTimestamp = () => null,
  onSeekToEvent = null,
}) {
  return createTimelineQaPanel({
    resourceId: cameraId,
    askQuestion: askCameraQuestion,
    getCurrentTimestamp,
    onSeekToEvent,
    suggestions: tList('cameraQa.suggestions'),
    initialMessage: t('cameraQa.initialMessage'),
    headerKicker: t('cameraQa.kicker'),
    headerTitle: t('cameraQa.title'),
    placeholder: t('cameraQa.placeholder'),
    helpText: t('cameraQa.helpText'),
    submitLabel: t('cameraQa.submit'),
    submitPendingLabel: t('cameraQa.pending'),
    loadingMessage: t('cameraQa.loading'),
    emptyMessage: t('cameraQa.empty'),
    noAnswerMessage: t('cameraQa.noAnswer'),
    storageKey: `phylax-camera-qa-memory:${cameraId}:${getLanguage()}`,
    panelClassName: 'camera-detective-panel',
    formatAnchorLabel: (value) => (Number.isFinite(value) && value > 0
      ? t('timelineQa.anchorPrefix', { time: formatRelativeClock(value) })
      : t('timelineQa.anchorRecentWindow')),
    formatEventTime: (value) => formatRelativeClock(value),
  });
}
