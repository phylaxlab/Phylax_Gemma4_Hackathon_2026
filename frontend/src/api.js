/**
 * API Client - Centralized functions for all Phylax backend endpoints.
 * Uses fetch() for HTTP and WebSocket for live streaming.
 */

const API_BASE = '';  // Uses Vite proxy in dev, same origin in prod
const LANGUAGE_STORAGE_KEY = 'phylax.language';

function getRequestLanguage() {
  try {
    return window.localStorage.getItem(LANGUAGE_STORAGE_KEY) || 'en';
  } catch {
    return 'en';
  }
}

// -- Helper: Parse JSON response with error handling --
async function handleResponse(response) {
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`HTTP ${response.status}: ${body}`);
  }
  return response.json();
}

async function handleFileResponse(response, fallbackFilename) {
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`HTTP ${response.status}: ${body}`);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('content-disposition') || '';
  const filenameMatch = disposition.match(/filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i);
  const filename = decodeURIComponent(filenameMatch?.[1] || filenameMatch?.[2] || fallbackFilename);
  return { blob, filename };
}


// ============== Camera Hub Endpoints ==============

export async function addCamera(name, streamUrl, aiEnabled = true) {
  const res = await fetch(`${API_BASE}/api/cameras`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, stream_url: streamUrl, ai_enabled: aiEnabled })
  });
  return handleResponse(res);
}

export async function getCameras() {
  const params = new URLSearchParams({ language: getRequestLanguage() });
  const res = await fetch(`${API_BASE}/api/cameras?${params.toString()}`);
  return handleResponse(res);
}

export async function getCamera(id) {
  const params = new URLSearchParams({ language: getRequestLanguage() });
  const res = await fetch(`${API_BASE}/api/cameras/${id}?${params.toString()}`);
  return handleResponse(res);
}

export async function toggleCameraAI(id, enabled) {
  const res = await fetch(`${API_BASE}/api/cameras/${id}/ai`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled })
  });
  return handleResponse(res);
}

export async function setCameraLanguage(id, language = getRequestLanguage()) {
  const res = await fetch(`${API_BASE}/api/cameras/${id}/language`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ language })
  });
  return handleResponse(res);
}

export async function deleteCamera(id) {
  const res = await fetch(`${API_BASE}/api/cameras/${id}`, { method: 'DELETE' });
  return handleResponse(res);
}

export async function updateCamera(id, data) {
  const res = await fetch(`${API_BASE}/api/cameras/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  return handleResponse(res);
}

export async function getCameraEvents(id, limit = 50, windowSeconds = null) {
  let url = `${API_BASE}/api/cameras/${id}/events?limit=${limit}&language=${encodeURIComponent(getRequestLanguage())}`;
  if (windowSeconds != null) {
    url += `&window_seconds=${windowSeconds}`;
  }
  const res = await fetch(url);
  return handleResponse(res);
}

export async function analyzeRecentCameraWindow(id) {
  const res = await fetch(`${API_BASE}/api/cameras/${id}/analyze_recent`, {
    method: 'POST',
  });
  return handleResponse(res);
}

export async function getCameraReplayBuffer(id) {
  const res = await fetch(`${API_BASE}/api/cameras/${id}/buffer`);
  return handleResponse(res);
}

export async function askCameraQuestion(id, payload) {
  const res = await fetch(`${API_BASE}/api/cameras/${id}/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return handleResponse(res);
}

export async function exportCameraInvestigationReport(id, payload) {
  const res = await fetch(`${API_BASE}/api/cameras/${id}/report`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return handleFileResponse(res, `phylax-investigation-camera-${id}.pdf`);
}

export function getCameraStreamUrl(id, options = null) {
  const params = new URLSearchParams();
  if (typeof options === 'number') {
    params.set('fps', String(options));
  } else if (options && typeof options === 'object') {
    if (options.fps != null) {
      params.set('fps', String(options.fps));
    }
    if (options.cacheBust) {
      params.set('t', String(options.cacheBust));
    }
  }
  const suffix = params.size ? `?${params.toString()}` : '';
  return `${API_BASE}/api/cameras/${id}/stream${suffix}`;
}

export function getCameraSnapshotUrl(id, cacheBust = '') {
  const suffix = cacheBust ? `?t=${encodeURIComponent(cacheBust)}` : '';
  return `${API_BASE}/api/cameras/${id}/snapshot${suffix}`;
}

export async function getCameraMapStatus() {
  const res = await fetch(`${API_BASE}/api/camera-map/status`);
  return handleResponse(res);
}

export async function getPublicCameraMapCameras(bounds = null, provider = 'all', forceRefresh = false) {
  const params = new URLSearchParams({ provider });
  if (bounds) {
    params.set('northLat', String(bounds.northLat));
    params.set('eastLon', String(bounds.eastLon));
    params.set('southLat', String(bounds.southLat));
    params.set('westLon', String(bounds.westLon));
  }
  if (forceRefresh) {
    params.set('forceRefresh', 'true');
  }
  const res = await fetch(`${API_BASE}/api/camera-map/cameras?${params.toString()}`);
  return handleResponse(res);
}

export async function getPublicCameraMapCamera(provider, sourceId) {
  const res = await fetch(`${API_BASE}/api/camera-map/cameras/${encodeURIComponent(provider)}/${encodeURIComponent(sourceId)}`);
  return handleResponse(res);
}


// ============== Video Endpoints ==============

/**
 * Upload a video file with optional title.
 * @param {File} file - The video file to upload.
 * @param {string} [title] - Optional title override.
 * @param {function} [onProgress] - Progress callback (0-100).
 * @returns {Promise<Object>} The created video object.
 */
export async function uploadVideo(file, title = '', onProgress = null) {
  const formData = new FormData();
  formData.append('file', file);
  if (title) formData.append('title', title);

  // Use XMLHttpRequest for progress tracking
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API_BASE}/api/videos/upload`);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        reject(new Error(`Upload failed: ${xhr.status}`));
      }
    };

    xhr.onerror = () => reject(new Error('Upload network error'));
    xhr.send(formData);
  });
}

/**
 * Fetch a paginated list of videos.
 */
export async function getVideos(page = 1, pageSize = 20, videoType = null) {
  let url = `${API_BASE}/api/videos?page=${page}&page_size=${pageSize}`;
  if (videoType) url += `&video_type=${videoType}`;
  const res = await fetch(url);
  return handleResponse(res);
}

/**
 * Get a single video by ID.
 */
export async function getVideo(videoId) {
  const res = await fetch(`${API_BASE}/api/videos/${videoId}`);
  return handleResponse(res);
}

/**
 * Delete a video.
 */
export async function deleteVideo(videoId) {
  const res = await fetch(`${API_BASE}/api/videos/${videoId}`, { method: 'DELETE' });
  return handleResponse(res);
}

/**
 * Update a video's details (e.g., title).
 */
export async function updateVideo(videoId, data) {
  const res = await fetch(`${API_BASE}/api/videos/${videoId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  return handleResponse(res);
}

/**
 * Get the streaming URL for a video.
 */
export function getVideoStreamUrl(videoId) {
  return `${API_BASE}/api/videos/${videoId}/stream`;
}

/**
 * Get the thumbnail URL for a video.
 */
export function getThumbnailUrl(thumbnail) {
  if (!thumbnail) return null;
  return `${API_BASE}/thumbnails/${thumbnail}`;
}


// ============== Analysis Endpoints ==============

/**
 * Start AI analysis for a video.
 */
export async function startAnalysis(videoId, options = {}) {
  const res = await fetch(`${API_BASE}/api/analysis/start/${videoId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(options),
  });
  return handleResponse(res);
}

/**
 * Get analysis status for a video.
 */
export async function getAnalysisStatus(videoId) {
  const res = await fetch(`${API_BASE}/api/analysis/status/${videoId}`);
  return handleResponse(res);
}

/**
 * Get all analysis events for a video.
 */
export async function getAnalysisEvents(videoId) {
  const params = new URLSearchParams({ language: getRequestLanguage() });
  const res = await fetch(`${API_BASE}/api/analysis/events/${videoId}?${params.toString()}`);
  return handleResponse(res);
}

export async function translateAnalysisEvents(targetLanguage, items) {
  const res = await fetch(`${API_BASE}/api/analysis/translate-events`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target_language: targetLanguage, items }),
  });
  return handleResponse(res);
}

/**
 * Delete all analysis events for a video (reset to 'pending' for re-analysis).
 */
export async function deleteAnalysisEvents(videoId) {
  const res = await fetch(`${API_BASE}/api/analysis/events/${videoId}`, { method: 'DELETE' });
  return handleResponse(res);
}

export async function askVideoQuestion(videoId, payload) {
  const res = await fetch(`${API_BASE}/api/analysis/ask/${videoId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return handleResponse(res);
}

export async function exportVideoInvestigationReport(videoId, payload) {
  const res = await fetch(`${API_BASE}/api/analysis/report/${videoId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return handleFileResponse(res, `phylax-investigation-video-${videoId}.pdf`);
}


// ============== Search Endpoints ==============

/**
 * Text-based keyword search.
 */
export async function searchEvents(query) {
  const res = await fetch(`${API_BASE}/api/search?q=${encodeURIComponent(query)}`);
  return handleResponse(res);
}

/**
 * AI-powered natural language search.
 */
export async function aiSearch(query) {
  const res = await fetch(`${API_BASE}/api/search/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
  });
  return handleResponse(res);
}

/**
 * Get AI-powered search suggestions.
 */
export async function getSearchSuggestions(query) {
  const res = await fetch(`${API_BASE}/api/search/suggestions?q=${encodeURIComponent(query)}`);
  return handleResponse(res);
}


// ============== Live Stream Endpoints ==============

/**
 * Start a new live stream session.
 */
export async function startStream(title) {
  const res = await fetch(`${API_BASE}/api/stream/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  });
  return handleResponse(res);
}

/**
 * Stop a live stream session.
 */
export async function stopStream(sessionId) {
  const res = await fetch(`${API_BASE}/api/stream/stop/${sessionId}`, { method: 'POST' });
  return handleResponse(res);
}

/**
 * Create a WebSocket connection for live streaming.
 * @param {number} sessionId - The active session ID.
 * @param {function} onMessage - Callback for incoming messages (analysis results).
 * @returns {WebSocket}
 */
export function connectStreamWebSocket(sessionId, onMessage) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  const ws = new WebSocket(`${protocol}//${host}/ws/stream/${sessionId}`);

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (onMessage) onMessage(data);
  };

  ws.onerror = (err) => {
    console.error('WebSocket error:', err);
  };

  return ws;
}


// ============== Health Check ==============

export async function healthCheck() {
  const res = await fetch(`${API_BASE}/api/health`);
  return handleResponse(res);
}
