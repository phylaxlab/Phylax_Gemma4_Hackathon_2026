/**
 * Sidebar Component - Left navigation panel with page links.
 */

import { icon } from '../icons.js';
import { t } from '../i18n.js';

const NAV_ITEMS = [
  { id: 'home', iconName: 'home', route: '/' },
  { id: 'map', iconName: 'mapPin', route: '/camera-map' },
  { id: 'hub', iconName: 'camera', route: '/hub' },
  { id: 'upload', iconName: 'upload', route: '/upload' },
];

export function renderSidebar(container, activeRoute = '/', onNavigate = null) {
  const sidebar = document.createElement('nav');
  sidebar.className = 'sidebar';
  sidebar.id = 'main-sidebar';

  sidebar.innerHTML = NAV_ITEMS.map((item) => {
    const isActive = activeRoute === item.route ? 'active' : '';
    const label = t(`nav.${item.id}`);
    return `
      <div class="sidebar-item ${isActive}" data-route="${item.route}" title="${label}" aria-label="${label}">
        <span class="icon">${icon(item.iconName, 20)}</span>
      </div>
    `;
  }).join('');

  container.appendChild(sidebar);

  sidebar.querySelectorAll('[data-route]').forEach((element) => {
    element.addEventListener('click', () => {
      onNavigate?.(element.dataset.route);
    });
  });
}

export function updateSidebarActive(route) {
  const sidebar = document.getElementById('main-sidebar');
  if (!sidebar) return;

  sidebar.querySelectorAll('.sidebar-item').forEach((element) => {
    element.classList.toggle('active', element.dataset.route === route);
  });
}
