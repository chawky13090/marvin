import assert from 'node:assert/strict';
import {
  NAVIGATION_MODES,
  normalizeNavigationMode,
  resolveNavigationMode,
  routeNavigationMode,
  routePreferenceKey,
} from '../lib/navigationLayout.mjs';

assert.deepEqual(NAVIGATION_MODES, ['auto', 'focus', 'rail', 'full', 'classic']);
assert.equal(normalizeNavigationMode('unexpected'), 'auto');

assert.equal(routeNavigationMode('/'), 'focus');
assert.equal(routeNavigationMode('/recherche'), 'focus');
assert.equal(routeNavigationMode('/code'), 'rail');
assert.equal(routeNavigationMode('/missions/active'), 'rail');
assert.equal(routeNavigationMode('/emails'), 'full');
assert.equal(routePreferenceKey('/code/mission/42'), '/code');
assert.equal(routePreferenceKey('/'), '/');

assert.equal(resolveNavigationMode({ pathname: '/emails' }), 'full');
assert.equal(resolveNavigationMode({ pathname: '/emails', preference: 'rail' }), 'rail');
assert.equal(resolveNavigationMode({
  pathname: '/emails',
  preference: 'rail',
  routePreference: 'focus',
}), 'focus');
assert.equal(resolveNavigationMode({
  pathname: '/emails',
  preference: 'classic',
  routePreference: 'full',
  compact: true,
}), 'focus');

console.log('Navigation adaptative OK - politiques, priorités, responsive et rollback classique.');
