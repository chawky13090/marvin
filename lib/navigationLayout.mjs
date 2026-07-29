export const NAVIGATION_MODES = Object.freeze(['auto', 'focus', 'rail', 'full', 'classic']);

const FOCUS_ROUTES = Object.freeze(['/', '/recherche', '/redaction']);
const RAIL_ROUTES = Object.freeze([
  '/code',
  '/missions',
  '/forge',
  '/agents',
  '/workflows',
  '/evolution',
  '/market',
]);

export function normalizeNavigationMode(value) {
  return NAVIGATION_MODES.includes(value) ? value : 'auto';
}

export function routeNavigationMode(pathname) {
  const path = typeof pathname === 'string' && pathname ? pathname : '/';
  if (FOCUS_ROUTES.some(route => route === '/' ? path === '/' : path.startsWith(route))) {
    return 'focus';
  }
  if (RAIL_ROUTES.some(route => path.startsWith(route))) return 'rail';
  return 'full';
}

export function routePreferenceKey(pathname) {
  const segment = String(pathname || '/').split('/').filter(Boolean)[0];
  return segment ? `/${segment}` : '/';
}

export function resolveNavigationMode({
  pathname = '/',
  preference = 'auto',
  routePreference = 'auto',
  compact = false,
} = {}) {
  if (compact) return 'focus';
  const routeMode = normalizeNavigationMode(routePreference);
  if (routeMode !== 'auto') return routeMode;
  const globalMode = normalizeNavigationMode(preference);
  if (globalMode !== 'auto') return globalMode;
  return routeNavigationMode(pathname);
}

