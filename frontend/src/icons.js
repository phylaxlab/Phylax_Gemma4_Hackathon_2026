/**
 * Icons Module - Inline SVG icon library for Phylax.
 * All icons use a consistent 24x24 viewBox with stroke-based design.
 * Inspired by Lucide / Heroicons aesthetic.
 */

const ICON_DEFAULTS = 'width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"';

export const icons = {
  // Navigation
  menu: `<svg ${ICON_DEFAULTS}><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>`,

  home: `<svg ${ICON_DEFAULTS}><path d="M3 9.5L12 3l9 6.5V20a1 1 0 01-1 1H4a1 1 0 01-1-1V9.5z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>`,

  upload: `<svg ${ICON_DEFAULTS}><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>`,

  video: `<svg ${ICON_DEFAULTS}><rect x="2" y="4" width="15" height="16" rx="2"/><path d="M17 8l5-3v14l-5-3V8z"/></svg>`,

  search: `<svg ${ICON_DEFAULTS}><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>`,

  camera: `<svg ${ICON_DEFAULTS}><path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z"/><circle cx="12" cy="13" r="4"/></svg>`,
  mapPin: `<svg ${ICON_DEFAULTS}><path d="M12 21s-6-5.33-6-11a6 6 0 1112 0c0 5.67-6 11-6 11z"/><circle cx="12" cy="10" r="2.5"/></svg>`,
  globe: `<svg ${ICON_DEFAULTS}><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/></svg>`,

  // Actions
  play: `<svg ${ICON_DEFAULTS}><polygon points="5 3 19 12 5 21 5 3"/></svg>`,

  stop: `<svg ${ICON_DEFAULTS}><rect x="6" y="6" width="12" height="12" rx="1"/></svg>`,

  arrowLeft: `<svg ${ICON_DEFAULTS}><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>`,

  // Status
  brain: `<svg ${ICON_DEFAULTS}><path d="M9.5 2A5.5 5.5 0 005 7.5c0 1.08.31 2.09.85 2.94L4 12.5l1.5 1.5 2.5-1c.85.65 1.9 1 3 1s2.15-.35 3-1l2.5 1 1.5-1.5-1.85-2.06c.54-.85.85-1.86.85-2.94A5.5 5.5 0 0014.5 2h-5z"/><path d="M8 10v2m4-2v2m4-2v2"/></svg>`,

  zap: `<svg ${ICON_DEFAULTS}><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>`,

  shield: `<svg ${ICON_DEFAULTS}><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>`,

  eye: `<svg ${ICON_DEFAULTS}><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`,

  clock: `<svg ${ICON_DEFAULTS}><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,

  alertTriangle: `<svg ${ICON_DEFAULTS}><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,

  checkCircle: `<svg ${ICON_DEFAULTS}><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>`,

  // Content
  folder: `<svg ${ICON_DEFAULTS}><path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/></svg>`,

  film: `<svg ${ICON_DEFAULTS}><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="2" y1="7" x2="7" y2="7"/><line x1="2" y1="17" x2="7" y2="17"/><line x1="17" y1="7" x2="22" y2="7"/><line x1="17" y1="17" x2="22" y2="17"/></svg>`,

  image: `<svg ${ICON_DEFAULTS}><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>`,

  grid: `<svg ${ICON_DEFAULTS}><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>`,

  list: `<svg ${ICON_DEFAULTS}><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>`,

  // Live / Stream
  radio: `<svg ${ICON_DEFAULTS}><circle cx="12" cy="12" r="2"/><path d="M16.24 7.76a6 6 0 010 8.49m-8.48-.01a6 6 0 010-8.49m11.31-2.82a10 10 0 010 14.14m-14.14 0a10 10 0 010-14.14"/></svg>`,

  wifi: `<svg ${ICON_DEFAULTS}><path d="M5 12.55a11 11 0 0114.08 0"/><path d="M1.42 9a16 16 0 0121.16 0"/><path d="M8.53 16.11a6 6 0 016.95 0"/><line x1="12" y1="20" x2="12.01" y2="20"/></svg>`,

  cast: `<svg ${ICON_DEFAULTS}><path d="M2 16.1A5 5 0 015.9 20M2 12.05A9 9 0 019.95 20M2 8V6a2 2 0 012-2h16a2 2 0 012 2v12a2 2 0 01-2 2h-6"/><line x1="2" y1="20" x2="2.01" y2="20"/></svg>`,

  maximize: `<svg ${ICON_DEFAULTS}><path d="M8 3H5a2 2 0 00-2 2v3"/><path d="M16 3h3a2 2 0 012 2v3"/><path d="M8 21H5a2 2 0 01-2-2v-3"/><path d="M16 21h3a2 2 0 002-2v-3"/></svg>`,

  fullscreenCorners: `<svg ${ICON_DEFAULTS}><polyline points="9 3 3 3 3 9"/><polyline points="15 3 21 3 21 9"/><polyline points="3 15 3 21 9 21"/><polyline points="21 15 21 21 15 21"/></svg>`,

  // Misc
  plus: `<svg ${ICON_DEFAULTS}><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>`,

  edit: `<svg ${ICON_DEFAULTS}><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>`,

  x: `<svg ${ICON_DEFAULTS}><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,

  xCircle: `<svg ${ICON_DEFAULTS}><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,

  moreVertical: `<svg ${ICON_DEFAULTS}><circle cx="12" cy="12" r="1"/><circle cx="12" cy="5" r="1"/><circle cx="12" cy="19" r="1"/></svg>`,

  externalLink: `<svg ${ICON_DEFAULTS}><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>`,

  trash: `<svg ${ICON_DEFAULTS}><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>`,

  activity: `<svg ${ICON_DEFAULTS}><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>`,

  // Severity
  circleDot: `<svg ${ICON_DEFAULTS}><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="2" fill="currentColor"/></svg>`,

  user: `<svg ${ICON_DEFAULTS}><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`,

  car: `<svg ${ICON_DEFAULTS}><path d="M5 17h14v-5l-2-6H7L5 12v5z"/><circle cx="7.5" cy="17.5" r="1.5"/><circle cx="16.5" cy="17.5" r="1.5"/><path d="M5 12h14"/></svg>`,

  motion: `<svg ${ICON_DEFAULTS}><path d="M13 4v16"/><path d="M17 4v16"/><path d="M21 4v16"/><path d="M9 4v16"/><path d="M5 4v16"/><path d="M1 4v16"/></svg>`,

  // Filter / Category
  filter: `<svg ${ICON_DEFAULTS}><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>`,

  layers: `<svg ${ICON_DEFAULTS}><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>`,

  signal: `<svg ${ICON_DEFAULTS}><path d="M2 20h.01"/><path d="M7 20v-4"/><path d="M12 20v-8"/><path d="M17 20V8"/><path d="M22 4v16"/></svg>`,
};

/**
 * Create an icon element with optional custom size.
 * @param {string} name - Icon name from the icons object.
 * @param {number} [size=20] - Icon size in pixels.
 * @param {string} [className=''] - Additional CSS class.
 * @returns {string} HTML string of the SVG icon.
 */
export function icon(name, size = 20, className = '') {
  const svg = icons[name] || icons.alertTriangle;
  const cls = className ? ` class="${className}"` : '';
  return svg.replace(
    /width="\d+"/, `width="${size}"`
  ).replace(
    /height="\d+"/, `height="${size}"`
  ).replace(
    '<svg ', `<svg${cls} `
  );
}
