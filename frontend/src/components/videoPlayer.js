/**
 * VideoPlayer Component — HTML5 video player wrapper.
 * Provides a container with the video element and basic controls.
 */

import { getVideoStreamUrl } from '../api.js';
import { icon } from '../icons.js';
import { t } from '../i18n.js';

/**
 * Create a video player for a given video ID.
 * @param {number} videoId - The video ID to stream.
 * @returns {{ element: HTMLElement, videoEl: HTMLVideoElement, seekTo: function }}
 */
export function createVideoPlayer(videoId) {
  const container = document.createElement('div');
  container.className = 'player-container';
  container.id = 'video-player-container';

  const video = document.createElement('video');
  video.id = 'main-video-player';
  video.controls = true;
  video.controlsList = 'nofullscreen';
  video.autoplay = false;
  video.preload = 'metadata';
  video.src = getVideoStreamUrl(videoId);

  container.appendChild(video);

  const fullscreenBtn = document.createElement('button');
  fullscreenBtn.type = 'button';
  fullscreenBtn.className = 'player-fullscreen-btn';
  container.appendChild(fullscreenBtn);

  function renderFullscreenButton() {
    const isFullscreen = document.fullscreenElement === container;
    const label = isFullscreen ? t('cameraPage.exitFullscreen') : t('cameraPage.fullscreen');
    fullscreenBtn.innerHTML = icon('fullscreenCorners', 18);
    fullscreenBtn.title = label;
    fullscreenBtn.setAttribute('aria-label', label);
  }

  fullscreenBtn.addEventListener('click', async () => {
    try {
      if (document.fullscreenElement === container) {
        await document.exitFullscreen?.();
      } else {
        await container.requestFullscreen?.();
      }
    } catch (error) {
      console.debug('Fullscreen unavailable:', error);
    }
  });

  const handleFullscreenChange = () => renderFullscreenButton();
  document.addEventListener('fullscreenchange', handleFullscreenChange);
  renderFullscreenButton();

  /**
   * Seek the video to a specific timestamp in seconds.
   */
  function seekTo(seconds) {
    video.currentTime = seconds;
    video.play();
  }

  return {
    element: container,
    videoEl: video,
    seekTo,
    destroy() {
      document.removeEventListener('fullscreenchange', handleFullscreenChange);
    },
  };
}
