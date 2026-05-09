import { askVideoQuestion } from '../api.js';
import { createTimelineQaPanel } from './timelineQaPanel.js';
import { formatVideoTime, getLanguage, t, tList } from '../i18n.js';

export function createVideoQaPanel({
  videoId,
  getCurrentTimestamp = () => null,
  onSeekToEvent = null,
}) {
  return createTimelineQaPanel({
    resourceId: videoId,
    askQuestion: askVideoQuestion,
    getCurrentTimestamp,
    onSeekToEvent,
    suggestions: tList('videoQa.suggestions'),
    initialMessage: t('videoQa.initialMessage'),
    headerKicker: t('videoQa.kicker'),
    headerTitle: t('videoQa.title'),
    placeholder: t('videoQa.placeholder'),
    helpText: t('videoQa.helpText'),
    submitLabel: t('videoQa.submit'),
    submitPendingLabel: t('videoQa.pending'),
    loadingMessage: t('videoQa.loading'),
    emptyMessage: t('videoQa.empty'),
    noAnswerMessage: t('videoQa.noAnswer'),
    storageKey: `phylax-video-qa-memory:${videoId}:${getLanguage()}`,
    formatAnchorLabel: (value) => (Number.isFinite(value) && value >= 0
      ? t('timelineQa.anchorPrefix', { time: formatVideoTime(value) })
      : t('timelineQa.anchorWholeVideo')),
    formatEventTime: (value) => formatVideoTime(value),
  });
}
