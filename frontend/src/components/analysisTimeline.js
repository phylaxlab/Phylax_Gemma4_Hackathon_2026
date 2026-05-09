/**
 * AnalysisTimeline Component — Visual timeline bar with event markers.
 * Shows colored dots on a track representing detected events at their timestamps.
 */

/**
 * Format a timestamp in seconds to MM:SS.
 */
function formatTime(sec) {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

/**
 * Create the analysis timeline bar with markers.
 * @param {Array} events - Array of analysis event objects.
 * @param {number} duration - Total video duration in seconds.
 * @param {function} onMarkerClick - Callback when a marker is clicked (receives event).
 * @returns {HTMLElement}
 */
export function createAnalysisTimeline(events, duration, onMarkerClick = null) {
  const container = document.createElement('div');
  container.className = 'timeline-bar';
  container.id = 'analysis-timeline';

  if (!events || events.length === 0 || duration <= 0) {
    return container;
  }

  events.forEach(event => {
    const position = (event.timestamp_sec / duration) * 100;
    if (position < 0 || position > 100) return;

    const marker = document.createElement('div');
    marker.className = `timeline-marker type-${event.event_type || 'none'}`;
    marker.style.left = `${position}%`;
    marker.title = `${formatTime(event.timestamp_sec)} — ${event.summary || event.description || 'Event'}`;

    // Tooltip element
    const tooltip = document.createElement('div');
    tooltip.className = 'timeline-tooltip';
    tooltip.textContent = `${formatTime(event.timestamp_sec)} — ${event.summary || 'Event'}`;
    marker.appendChild(tooltip);

    if (onMarkerClick) {
      marker.addEventListener('click', (e) => {
        e.stopPropagation();
        onMarkerClick(event);
      });
    }

    container.appendChild(marker);
  });

  return container;
}

/**
 * Create a rolling timeline for live camera events.
 * @param {Array} events - Recent camera events with absolute epoch timestamps.
 * @param {number} windowSeconds - Visible rolling window in seconds.
 * @param {number|null} currentAnalyzingTs - Epoch timestamp currently under analysis.
 * @param {function} onMarkerClick - Callback when a marker is clicked.
 * @returns {HTMLElement}
 */
export function createRollingTimeline(events, windowSeconds = 300, currentAnalyzingTs = null, onMarkerClick = null) {
  const wrapper = document.createElement('div');
  wrapper.className = 'camera-timeline-wrapper';

  const container = document.createElement('div');
  container.className = 'timeline-bar camera-timeline-bar';
  container.id = 'camera-analysis-timeline';

  const labels = document.createElement('div');
  labels.className = 'camera-timeline-labels';
  labels.innerHTML = `
    <span>5 min ago</span>
    <span>Now</span>
  `;

  const now = Date.now() / 1000;
  const start = now - windowSeconds;

  if (currentAnalyzingTs && currentAnalyzingTs >= start && currentAnalyzingTs <= now) {
    const progress = document.createElement('div');
    progress.className = 'camera-timeline-progress';
    progress.style.width = `${((currentAnalyzingTs - start) / windowSeconds) * 100}%`;
    container.appendChild(progress);
  }

  if (events && events.length > 0) {
    events.forEach(event => {
      const position = ((event.timestamp_sec - start) / windowSeconds) * 100;
      if (position < 0 || position > 100) return;

      const marker = document.createElement('div');
      marker.className = `timeline-marker type-${event.event_type || 'none'}`;
      marker.style.left = `${position}%`;

      const secondsAgo = Math.max(0, Math.round(now - event.timestamp_sec));
      const minutesAgo = Math.floor(secondsAgo / 60);
      const remainder = secondsAgo % 60;
      marker.title = `${minutesAgo}:${String(remainder).padStart(2, '0')} ago - ${event.summary || event.description || 'Event'}`;

      const tooltip = document.createElement('div');
      tooltip.className = 'timeline-tooltip';
      tooltip.textContent = `${minutesAgo}:${String(remainder).padStart(2, '0')} ago - ${event.summary || 'Event'}`;
      marker.appendChild(tooltip);

      if (onMarkerClick) {
        marker.addEventListener('click', (e) => {
          e.stopPropagation();
          onMarkerClick(event);
        });
      }

      container.appendChild(marker);
    });
  }

  wrapper.appendChild(container);
  wrapper.appendChild(labels);
  return wrapper;
}
