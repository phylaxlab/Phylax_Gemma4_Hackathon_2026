import { icon } from '../icons.js';
import { translateAnalysisEvents } from '../api.js';
import { getLanguage, t } from '../i18n.js';

const QA_MEMORY_VERSION = 1;
const MAX_QA_MEMORY_MESSAGES = 40;
const HISTORY_PAYLOAD_TURNS = 12;

function createMessage(role, content, extra = {}) {
  return {
    id: `${role}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
    role,
    content,
    ...extra,
  };
}

export function createTimelineQaPanel({
  resourceId,
  askQuestion,
  getCurrentTimestamp = () => null,
  onSeekToEvent = null,
  suggestions = [],
  initialMessage = 'Ask about the timeline, suspicious behavior, or key moments.',
  headerKicker = 'Clue Trace',
  headerTitle = 'Keyframe Trace',
  placeholder = 'Ask about suspicious moments, key frames, before/after changes, or what matters most...',
  helpText = 'The current playback time is used as an anchor when available. Click a clue card to jump there.',
  submitLabel = 'Find Clues',
  submitPendingLabel = 'Tracing...',
  loadingMessage = 'Tracing the timeline and gathering the strongest clue frames...',
  emptyMessage = 'Ask the first question to start tracing the timeline.',
  noAnswerMessage = 'I could not build a grounded answer from this timeline yet.',
  storageKey = null,
  panelClassName = '',
  formatAnchorLabel = () => t('timelineQa.anchorWholeTimeline'),
  formatEventTime = () => '',
}) {
  const panel = document.createElement('section');
  panel.className = `video-qa-panel ${panelClassName}`.trim();
  const restoredMessages = loadMemoryMessages(storageKey);

  const state = {
    messages: [
      createMessage('assistant', initialMessage, { intro: true }),
      ...restoredMessages,
    ],
    sending: false,
    draft: '',
  };

  function historyPayload() {
    return state.messages
      .filter((message) => (message.role === 'user' || message.role === 'assistant') && !message.loading && !message.intro)
      .slice(-HISTORY_PAYLOAD_TURNS)
      .map(serializeHistoryMessage);
  }

  function persistMemory() {
    saveMemoryMessages(storageKey, state.messages);
  }

  function render() {
    panel.innerHTML = `
      <div class="video-qa-header">
        <div>
          <div class="video-qa-kicker">${escapeHtml(headerKicker)}</div>
          <div class="video-qa-title">${icon('brain', 18)} ${escapeHtml(headerTitle)}</div>
        </div>
        <div class="video-qa-anchor">
          ${icon('clock', 14)}
          <span>${escapeHtml(renderAnchorLabel())}</span>
        </div>
      </div>
      <div class="video-qa-suggestions"></div>
      <div class="video-qa-messages"></div>
      <form class="video-qa-composer">
        <textarea
          class="video-qa-input"
          rows="3"
          placeholder="${escapeHtml(placeholder)}"
        >${escapeHtml(state.draft)}</textarea>
        <div class="video-qa-actions">
          <div class="video-qa-help">${escapeHtml(helpText)}</div>
          <button type="submit" class="btn btn-primary"${state.sending ? ' disabled' : ''}>
            ${state.sending ? `${icon('clock', 16)} ${escapeHtml(submitPendingLabel)}` : `${icon('search', 16)} ${escapeHtml(submitLabel)}`}
          </button>
        </div>
      </form>
    `;

    renderSuggestions();
    renderMessages();
    bindComposer();
  }

  function renderAnchorLabel() {
    return formatAnchorLabel(getCurrentTimestamp?.());
  }

  function renderSuggestions() {
    const suggestionsEl = panel.querySelector('.video-qa-suggestions');
    if (!suggestionsEl) return;

    if (!suggestions.length) {
      suggestionsEl.innerHTML = '';
      return;
    }

    suggestionsEl.innerHTML = suggestions.map((question) => `
      <button type="button" class="video-qa-chip">${escapeHtml(question)}</button>
    `).join('');

    suggestionsEl.querySelectorAll('.video-qa-chip').forEach((button, index) => {
      button.addEventListener('click', () => {
        void submitQuestion(suggestions[index]);
      });
    });
  }

  function renderMessages() {
    const messagesEl = panel.querySelector('.video-qa-messages');
    if (!messagesEl) return;

    messagesEl.innerHTML = '';

    if (state.messages.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'video-qa-empty';
      empty.textContent = emptyMessage;
      messagesEl.appendChild(empty);
      return;
    }

    state.messages.forEach((message) => {
      const item = document.createElement('article');
      item.className = `video-qa-message is-${message.role}`;

      const meta = document.createElement('div');
      meta.className = 'video-qa-message-meta';
      meta.innerHTML = `
        <span class="video-qa-role">${message.role === 'assistant' ? 'Gemma' : t('timelineQa.you')}</span>
        ${message.confidence ? `<span class="video-qa-confidence is-${message.confidence}">${escapeHtml(renderConfidenceLabel(message.confidence))}</span>` : ''}
      `;
      item.appendChild(meta);

      const body = document.createElement('div');
      body.className = 'video-qa-message-body';
      body.textContent = message.content;

      if (Array.isArray(message.agent_trace) && message.agent_trace.length > 0) {
        const trace = document.createElement('details');
        trace.className = 'video-qa-trace';

        const traceTitle = document.createElement('summary');
        traceTitle.className = 'video-qa-trace-title';
        traceTitle.innerHTML = `
          <span>${escapeHtml(t('timelineQa.agentTraceTitle'))}</span>
          <span class="video-qa-trace-toggle">${escapeHtml(t('timelineQa.expandDetails'))}</span>
        `;
        trace.appendChild(traceTitle);

        const traceBody = document.createElement('div');
        traceBody.className = 'video-qa-trace-body';
        message.agent_trace.forEach((step) => {
          const traceStep = document.createElement('div');
          traceStep.className = 'video-qa-trace-step';
          traceStep.innerHTML = `
            <div class="video-qa-trace-step-icon">${renderTraceIcon(step.step)}</div>
            <div class="video-qa-trace-step-copy">
              <strong>${escapeHtml(step.title || step.step || 'Step')}</strong>
              <span>${escapeHtml(step.detail || '')}</span>
            </div>
          `;
          traceBody.appendChild(traceStep);
        });
        trace.appendChild(traceBody);

        item.appendChild(trace);
      }

      const reconstruction = renderReconstruction(message.reconstruction, {
        onSeekToEvent,
        formatEventTime,
        relevantEvents: message.relevant_events || [],
      });
      if (reconstruction) {
        item.appendChild(reconstruction);
      }

      item.appendChild(body);

      if (Array.isArray(message.relevant_events) && message.relevant_events.length > 0) {
        const clues = document.createElement('div');
        clues.className = 'video-qa-clues';

        const clueTitle = document.createElement('div');
        clueTitle.className = 'video-qa-clue-group-title';
        clueTitle.textContent = t('timelineQa.clueGroupTitle');
        clues.appendChild(clueTitle);

        message.relevant_events.forEach((event) => {
          const clue = document.createElement('button');
          clue.type = 'button';
          clue.className = 'video-qa-clue';
          const previewUrl = String(event.preview_url || '').trim();
          clue.innerHTML = `
            ${previewUrl ? `<img class="video-qa-clue-preview" src="${escapeHtml(previewUrl)}" alt="${escapeHtml(t('common.preview'))}" loading="lazy" />` : ''}
            <span>${icon('clock', 12)} ${escapeHtml(formatEventTime(event.timestamp_sec))}</span>
            <strong>${escapeHtml(event.summary || event.description || event.event_type || t('timelineQa.eventFallback'))}</strong>
            <small>${escapeHtml(event.description || event.event_type || t('timelineQa.analysisEvent'))}</small>
          `;
          clue.addEventListener('click', () => {
            onSeekToEvent?.(event);
          });
          clues.appendChild(clue);
        });
        item.appendChild(clues);
      }

      if (message.follow_up_suggestion) {
        const followUp = document.createElement('button');
        followUp.type = 'button';
        followUp.className = 'video-qa-follow-up';
        followUp.innerHTML = `${icon('plus', 14)} ${escapeHtml(message.follow_up_suggestion)}`;
        followUp.addEventListener('click', () => {
          state.draft = message.follow_up_suggestion;
          const input = panel.querySelector('.video-qa-input');
          if (input) {
            input.value = state.draft;
            input.focus();
          }
        });
        item.appendChild(followUp);
      }

      messagesEl.appendChild(item);
    });

    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function bindComposer() {
    const form = panel.querySelector('.video-qa-composer');
    const input = panel.querySelector('.video-qa-input');
    if (!form || !input) return;

    input.addEventListener('input', () => {
      state.draft = input.value;
    });

    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        void submitQuestion();
      }
    });

    form.addEventListener('submit', (event) => {
      event.preventDefault();
      void submitQuestion();
    });
  }

  async function submitQuestion(explicitQuestion = '') {
    const question = (explicitQuestion || state.draft || '').trim();
    if (!question || state.sending) {
      return;
    }

    const history = [...historyPayload(), { role: 'user', content: question }];
    const userMessage = createMessage('user', question);
    const pendingMessage = createMessage('assistant', loadingMessage, {
      loading: true,
    });
    state.messages = [...state.messages, userMessage, pendingMessage];
    state.draft = '';
    state.sending = true;
    persistMemory();
    render();

    try {
      const currentTimestampSec = getCurrentTimestamp?.();
      const response = await askQuestion(resourceId, {
        question,
        language: getLanguage(),
        current_timestamp_sec: Number.isFinite(currentTimestampSec) ? currentTimestampSec : null,
        history,
      });
      const localizedResponse = await localizeQaResponse(response, getLanguage());

      state.messages = state.messages.filter((message) => !message.loading);
      state.messages.push(createMessage('assistant', localizedResponse.answer || noAnswerMessage, {
        confidence: localizedResponse.confidence || 'low',
        relevant_events: localizedResponse.relevant_events || [],
        follow_up_suggestion: localizedResponse.follow_up_suggestion || '',
        agent_trace: localizedResponse.agent_trace || [],
        reconstruction: localizedResponse.reconstruction || null,
      }));
      persistMemory();
    } catch (error) {
      state.messages = state.messages.filter((message) => !message.loading);
      state.messages.push(createMessage('assistant', t('timelineQa.followUpError', { message: error.message }), {
        confidence: 'low',
      }));
      persistMemory();
    } finally {
      state.sending = false;
      render();
    }
  }

  render();

    return {
      element: panel,
      ask: submitQuestion,
      buildReportPayload() {
        const currentTimestampSec = getCurrentTimestamp?.();
        return {
          language: getLanguage(),
          current_timestamp_sec: Number.isFinite(currentTimestampSec) ? Number(currentTimestampSec) : null,
          messages: state.messages
            .filter((message) => !message.loading && !message.intro && (message.role === 'user' || message.role === 'assistant'))
            .map((message) => ({
              role: message.role,
              content: message.content,
              confidence: message.confidence || null,
              relevant_events: Array.isArray(message.relevant_events) ? message.relevant_events : [],
              agent_trace: Array.isArray(message.agent_trace) ? message.agent_trace : [],
              reconstruction: message.reconstruction || null,
            })),
        };
      },
      refreshAnchor() {
        const anchor = panel.querySelector('.video-qa-anchor span');
        if (anchor) {
          anchor.textContent = renderAnchorLabel();
      }
    },
    destroy() {
      panel.remove();
    },
  };
}

async function localizeQaResponse(response, language) {
  if (!response || language === 'en') {
    return response;
  }

  const relevantEvents = Array.isArray(response.relevant_events) ? response.relevant_events : [];
  const eventPayload = relevantEvents
    .filter((event) => event && (event.summary || event.description))
    .map((event) => ({
      id: String(event.event_id ?? event.timestamp_sec ?? Math.random()),
      summary: String(event.summary || ''),
      description: String(event.description || ''),
    }));

  const storyBeats = Array.isArray(response?.reconstruction?.story_beats)
    ? response.reconstruction.story_beats.filter((beat) => beat && (beat.title || beat.detail))
    : [];
  const beatPayload = storyBeats.map((beat, index) => ({
    id: `beat:${index}:${beat.event_id ?? ''}:${beat.timestamp_sec ?? ''}`,
    summary: String(beat.title || ''),
    description: String(beat.detail || ''),
  }));

  if (!eventPayload.length && !beatPayload.length) {
    return response;
  }

  try {
    const translated = await translateAnalysisEvents(language, [...eventPayload, ...beatPayload]);
    const itemMap = new Map((translated.items || []).map((item) => [String(item.id), item]));

    return {
      ...response,
      relevant_events: relevantEvents.map((event) => {
        const translatedEvent = itemMap.get(String(event.event_id ?? event.timestamp_sec ?? ''));
        return translatedEvent
          ? {
              ...event,
              summary: translatedEvent.summary || event.summary || '',
              description: translatedEvent.description || event.description || '',
            }
          : event;
      }),
      reconstruction: response.reconstruction
        ? {
            ...response.reconstruction,
            story_beats: storyBeats.map((beat, index) => {
              const translatedBeat = itemMap.get(`beat:${index}:${beat.event_id ?? ''}:${beat.timestamp_sec ?? ''}`);
              return translatedBeat
                ? {
                    ...beat,
                    title: translatedBeat.summary || beat.title || '',
                    detail: translatedBeat.description || beat.detail || '',
                  }
                : beat;
            }),
          }
        : response.reconstruction,
    };
  } catch (error) {
    console.debug('QA clue translation unavailable:', error);
    return response;
  }
}

function renderConfidenceLabel(value) {
  if (value === 'high') return t('timelineQa.confidenceHigh');
  if (value === 'medium') return t('timelineQa.confidenceMedium');
  return t('timelineQa.confidenceLow');
}

function renderTraceIcon(step) {
  if (step === 'interpret') return icon('brain', 14);
  if (step === 'scan') return icon('search', 14);
  if (step === 'expand') return icon('layers', 14);
  if (step === 'deep_review') return icon('eye', 14);
  return icon('checkCircle', 14);
}

function serializeHistoryMessage(message) {
  return {
    role: message.role,
    content: message.content,
    confidence: message.confidence || null,
    relevant_events: Array.isArray(message.relevant_events) ? message.relevant_events : [],
    follow_up_suggestion: message.follow_up_suggestion || '',
    agent_trace: Array.isArray(message.agent_trace) ? message.agent_trace : [],
    reconstruction: message.reconstruction || null,
  };
}

function loadMemoryMessages(storageKey) {
  if (!storageKey) {
    return [];
  }
  try {
    const raw = localStorage.getItem(storageKey);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    if (!parsed || parsed.version !== QA_MEMORY_VERSION || !Array.isArray(parsed.messages)) {
      return [];
    }
    return parsed.messages
      .map(normalizeMemoryMessage)
      .filter(Boolean)
      .slice(-MAX_QA_MEMORY_MESSAGES);
  } catch {
    return [];
  }
}

function saveMemoryMessages(storageKey, messages) {
  if (!storageKey) {
    return;
  }
  try {
    const payload = {
      version: QA_MEMORY_VERSION,
      messages: messages
        .filter((message) => !message.loading && !message.intro && (message.role === 'user' || message.role === 'assistant'))
        .map(serializeHistoryMessage)
        .slice(-MAX_QA_MEMORY_MESSAGES),
    };
    localStorage.setItem(storageKey, JSON.stringify(payload));
  } catch {
    // Memory is a convenience layer; answering should still work if storage is unavailable.
  }
}

function normalizeMemoryMessage(message) {
  if (!message || typeof message !== 'object') {
    return null;
  }
  const role = message.role === 'user' ? 'user' : message.role === 'assistant' ? 'assistant' : '';
  const content = String(message.content || '').trim();
  if (!role || !content) {
    return null;
  }
  return createMessage(role, content, {
    confidence: message.confidence || null,
    relevant_events: Array.isArray(message.relevant_events) ? message.relevant_events : [],
    follow_up_suggestion: message.follow_up_suggestion || '',
    agent_trace: Array.isArray(message.agent_trace) ? message.agent_trace : [],
    reconstruction: message.reconstruction || null,
  });
}

function renderReconstruction(reconstruction, { onSeekToEvent, formatEventTime, relevantEvents = [] }) {
  if (!reconstruction || typeof reconstruction !== 'object') {
    return null;
  }

  const headline = String(reconstruction.headline || '').trim();
  const summary = String(reconstruction.summary || '').trim();
  const storyBeats = Array.isArray(reconstruction.story_beats)
    ? reconstruction.story_beats.filter((beat) => beat && typeof beat === 'object')
    : [];
  const actors = normalizeStringList(reconstruction.actors);
  const reviewFocus = normalizeStringList(reconstruction.review_focus);
  const openQuestions = normalizeStringList(reconstruction.open_questions);
  const previewByEventId = new Map();
  const relevantList = Array.isArray(relevantEvents) ? relevantEvents : [];
  relevantList.forEach((event) => {
    if (!event || typeof event !== 'object') return;
    if (event.event_id != null && event.preview_url) {
      previewByEventId.set(String(event.event_id), String(event.preview_url));
    }
  });

  if (!headline && !summary && !storyBeats.length && !actors.length && !reviewFocus.length && !openQuestions.length) {
    return null;
  }

  const card = document.createElement('section');
  card.className = 'video-qa-reconstruction';

  const title = document.createElement('div');
  title.className = 'video-qa-evidence-title';
  title.textContent = t('timelineQa.reconstructionTitle');
  card.appendChild(title);

  if (headline) {
    const headlineEl = document.createElement('div');
    headlineEl.className = 'video-qa-reconstruction-headline';
    headlineEl.textContent = headline;
    card.appendChild(headlineEl);
  }

  if (summary) {
    const summaryLabel = document.createElement('div');
    summaryLabel.className = 'video-qa-section-title';
    summaryLabel.textContent = t('timelineQa.reconstructionSummary');
    card.appendChild(summaryLabel);

    const summaryEl = document.createElement('div');
    summaryEl.className = 'video-qa-reconstruction-summary';
    summaryEl.textContent = summary;
    card.appendChild(summaryEl);
  }

  if (storyBeats.length > 0) {
    const timelineLabel = document.createElement('div');
    timelineLabel.className = 'video-qa-section-title';
    timelineLabel.textContent = t('timelineQa.reconstructionTimeline');
    card.appendChild(timelineLabel);

    const beatList = document.createElement('div');
    beatList.className = 'video-qa-story-beats';

    storyBeats.forEach((beat) => {
      const beatEl = document.createElement(onSeekToEvent ? 'button' : 'div');
      beatEl.className = `video-qa-story-beat${onSeekToEvent ? '' : ' is-static'}`;
      if (beatEl instanceof HTMLButtonElement) {
        beatEl.type = 'button';
      }

      const phase = String(beat.phase || 'key').trim().toLowerCase();
      const timeText = Number.isFinite(Number(beat.timestamp_sec))
        ? (formatEventTime(Number(beat.timestamp_sec)) || t('timelineQa.unknown'))
        : t('timelineQa.unknown');
      const titleText = String(beat.title || beat.detail || t('timelineQa.eventFallback')).trim();
      const detailText = String(beat.detail || '').trim();
      const previewUrl = String(
        beat.preview_url
          || (beat.event_id != null ? previewByEventId.get(String(beat.event_id)) : '')
          || ''
      ).trim();
      if (previewUrl) {
        beatEl.classList.add('has-preview');
      }

      beatEl.innerHTML = `
        ${previewUrl ? `<img class="video-qa-story-beat-preview" src="${escapeHtml(previewUrl)}" alt="${escapeHtml(t('common.preview'))}" loading="lazy" />` : ''}
        <div class="video-qa-story-beat-copy">
          <div class="video-qa-story-beat-meta">
            <span class="video-qa-story-beat-phase">${escapeHtml(renderPhaseLabel(phase))}</span>
            <span>${icon('clock', 12)} ${escapeHtml(timeText)}</span>
          </div>
          <strong class="video-qa-story-beat-title">${escapeHtml(titleText)}</strong>
          ${detailText ? `<span class="video-qa-story-beat-detail">${escapeHtml(detailText)}</span>` : ''}
        </div>
      `;

      if (onSeekToEvent && Number.isFinite(Number(beat.timestamp_sec))) {
        beatEl.addEventListener('click', () => {
          onSeekToEvent({
            event_id: beat.event_id ?? null,
            timestamp_sec: Number(beat.timestamp_sec),
            summary: titleText,
            description: detailText,
          });
        });
      }

      beatList.appendChild(beatEl);
    });

    card.appendChild(beatList);
  }

  appendPillSection(card, t('timelineQa.reconstructionActors'), actors);
  appendNoteSection(card, t('timelineQa.reconstructionFocus'), reviewFocus);
  appendNoteSection(card, t('timelineQa.reconstructionOpenQuestions'), openQuestions, true);

  return card;
}

function appendPillSection(container, title, items) {
  if (!Array.isArray(items) || items.length === 0) {
    return;
  }

  const label = document.createElement('div');
  label.className = 'video-qa-section-title';
  label.textContent = title;
  container.appendChild(label);

  const list = document.createElement('div');
  list.className = 'video-qa-pill-list';
  items.forEach((item) => {
    const pill = document.createElement('span');
    pill.className = 'video-qa-pill';
    pill.textContent = item;
    list.appendChild(pill);
  });
  container.appendChild(list);
}

function appendNoteSection(container, title, items, muted = false) {
  if (!Array.isArray(items) || items.length === 0) {
    return;
  }

  const label = document.createElement('div');
  label.className = 'video-qa-section-title';
  label.textContent = title;
  container.appendChild(label);

  const list = document.createElement('div');
  list.className = `video-qa-note-list${muted ? ' is-muted' : ''}`;
  items.forEach((item) => {
    const note = document.createElement('div');
    note.className = 'video-qa-note-item';
    note.textContent = item;
    list.appendChild(note);
  });
  container.appendChild(list);
}

function normalizeStringList(value) {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => String(item || '').trim())
    .filter(Boolean)
    .slice(0, 6);
}

function renderPhaseLabel(phase) {
  if (phase === 'before') return t('timelineQa.phaseBefore');
  if (phase === 'after') return t('timelineQa.phaseAfter');
  return t('timelineQa.phaseKey');
}

function escapeHtml(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}
