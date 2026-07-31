'use strict';

const { app, BrowserWindow, globalShortcut, ipcMain, screen, shell, session } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

if (process.env.LOCALAPPDATA) {
  app.setPath('userData', path.join(process.env.LOCALAPPDATA, 'Marvin', 'DesktopAvatar'));
}

const ROOT = path.resolve(__dirname, '..');
const AVATAR_URL = 'http://127.0.0.1:3000/avatar';
const AVATAR_ORIGIN = new URL(AVATAR_URL).origin;
const MAIN_URL = 'http://127.0.0.1:3000/';
const ICON_PATH = path.join(ROOT, 'public', 'marvin-avatar.ico');
const OFFLINE_PATH = path.join(__dirname, 'offline.html');
const OFFLINE_URL = pathToFileURL(OFFLINE_PATH).href;
const PREFERENCES_PATH = path.join(app.getPath('userData'), 'window-state.json');
const STARTUP_LOG_PATH = path.join(app.getPath('userData'), 'startup.log');
const SHUTDOWN_LOG_PATH = path.join(app.getPath('userData'), 'shutdown.log');
const MIN_WIDTH = 390;
const MIN_HEIGHT = 470;
let windowRef = null;
let saveTimer = null;
let resizeState = null;
let resizeTimer = null;
let availabilityTimer = null;
let availabilityCheckRunning = false;

function rotateLog(logPath, maxBytes = 2 * 1024 * 1024, archives = 4) {
  try {
    if (!fs.existsSync(logPath) || fs.statSync(logPath).size < maxBytes) return;
    for (let index = archives; index >= 1; index -= 1) {
      const source = index === 1 ? logPath : `${logPath}.${index - 1}`;
      const destination = `${logPath}.${index}`;
      if (fs.existsSync(source)) {
        fs.rmSync(destination, { force: true });
        fs.renameSync(source, destination);
      }
    }
  } catch {
    // La rotation ne doit jamais empêcher le contrôle du cycle de vie.
  }
}

function readWindowState() {
  try { return JSON.parse(fs.readFileSync(PREFERENCES_PATH, 'utf8')); } catch { return {}; }
}

function saveWindowState() {
  if (!windowRef || windowRef.isDestroyed()) return;
  const temporary = PREFERENCES_PATH + '.tmp';
  const payload = JSON.stringify({ bounds: windowRef.getBounds() });
  try {
    fs.mkdirSync(path.dirname(PREFERENCES_PATH), { recursive: true });
    fs.writeFileSync(temporary, payload, { encoding: 'utf8', mode: 0o600 });
    fs.renameSync(temporary, PREFERENCES_PATH);
  } catch { try { fs.rmSync(temporary, { force: true }); } catch {} }
}

function scheduleWindowStateSave() {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(saveWindowState, 250);
}

function initialWindowBounds() {
  const stored = readWindowState().bounds;
  const fallback = { width: 520, height: 680 };
  if (!stored || ![stored.x, stored.y, stored.width, stored.height].every(Number.isFinite)) return fallback;
  const point = { x: stored.x + Math.round(stored.width / 2), y: stored.y + Math.round(stored.height / 2) };
  const work = screen.getDisplayNearestPoint(point).workArea;
  const width = Math.max(390, Math.min(stored.width, work.width));
  const height = Math.max(470, Math.min(stored.height, work.height));
  return {
    x: Math.max(work.x, Math.min(stored.x, work.x + work.width - width)),
    y: Math.max(work.y, Math.min(stored.y, work.y + work.height - height)),
    width, height,
  };
}

function probe(url, timeoutMs = 1200) {
  return new Promise((resolve) => {
    const request = http.get(url, { timeout: timeoutMs }, (response) => {
      response.resume();
      resolve(response.statusCode >= 200 && response.statusCode < 500);
    });
    request.on('timeout', () => request.destroy());
    request.on('error', () => resolve(false));
  });
}

async function probeMarvin() {
  const [frontend, backend] = await Promise.all([
    probe(AVATAR_URL),
    probe('http://127.0.0.1:8005/api/health'),
  ]);
  return frontend && backend;
}

function isAvatarUrl(value) {
  try {
    const parsed = new URL(value);
    return parsed.origin === AVATAR_ORIGIN && parsed.pathname.replace(/\/$/, '') === '/avatar';
  } catch {
    return false;
  }
}

function isAvatarOrigin(value) {
  try {
    return new URL(value).origin === AVATAR_ORIGIN;
  } catch {
    return false;
  }
}

function trustedSender(event) {
  const source = event.senderFrame?.url || '';
  return isAvatarUrl(source) || source === OFFLINE_URL;
}

function runDetached(command, args, { logPath = null } = {}) {
  return new Promise((resolve, reject) => {
    let output = 'ignore';
    let descriptor = null;
    try {
      if (logPath) {
        fs.mkdirSync(path.dirname(logPath), { recursive: true });
        rotateLog(logPath);
        descriptor = fs.openSync(logPath, 'a');
        fs.writeSync(descriptor, `\r\n[${new Date().toISOString()}] ${command} ${args.join(' ')}\r\n`);
        output = ['ignore', descriptor, descriptor];
      }
      const child = spawn(command, args, {
        cwd: ROOT,
        detached: true,
        windowsHide: true,
        stdio: output,
      });
      child.once('spawn', () => {
        child.unref();
        resolve({ pid: child.pid });
      });
      child.once('error', reject);
    } catch (error) {
      reject(error);
    } finally {
      if (descriptor !== null) fs.closeSync(descriptor);
    }
  });
}

function runToCompletion(command, args, { logPath, timeoutMs = 30000 } = {}) {
  return new Promise((resolve, reject) => {
    let settled = false;
    let stdout = '';
    let stderr = '';
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      callback(value);
    };
    const child = spawn(command, args, {
      cwd: ROOT,
      detached: false,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    child.stdout.on('data', (chunk) => { stdout += chunk.toString('utf8').slice(0, 16000); });
    child.stderr.on('data', (chunk) => { stderr += chunk.toString('utf8').slice(0, 16000); });
    const timer = setTimeout(() => {
      if (process.platform === 'win32' && child.pid) {
        const killer = spawn('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], {
          windowsHide: true,
          stdio: 'ignore',
        });
        killer.unref();
      } else {
        child.kill();
      }
      finish(reject, new Error(`Délai d'arrêt dépassé (${timeoutMs / 1000} s).`));
    }, timeoutMs);
    child.once('error', (error) => {
      clearTimeout(timer);
      finish(reject, error);
    });
    child.once('close', (code) => {
      clearTimeout(timer);
      if (logPath) {
        fs.mkdirSync(path.dirname(logPath), { recursive: true });
        rotateLog(logPath);
        fs.appendFileSync(
          logPath,
          `\r\n[${new Date().toISOString()}] exit=${code}\r\n${stdout}${stderr}`,
          'utf8',
        );
      }
      if (code === 0) {
        finish(resolve, { code, stdout, stderr });
      } else {
        finish(
          reject,
          new Error(
            stderr.trim()
            || stdout.trim()
            || `Le script d'arrêt s'est terminé avec le code ${code}.`,
          ),
        );
      }
    });
  });
}

async function waitForMarvin(maxMs = 90000) {
  const deadline = Date.now() + maxMs;
  while (Date.now() < deadline) {
    if (await probeMarvin()) return true;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  return false;
}

async function waitForMarvinStop(maxMs = 20000) {
  const deadline = Date.now() + maxMs;
  while (Date.now() < deadline) {
    const [frontendRunning, backendRunning] = await Promise.all([
      probe(AVATAR_URL),
      probe('http://127.0.0.1:8005/api/health'),
    ]);
    if (!frontendRunning && !backendRunning) return true;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return false;
}

async function loadAvailableView({ force = false } = {}) {
  if (!windowRef || windowRef.isDestroyed()) return;
  if (availabilityCheckRunning) return;
  availabilityCheckRunning = true;
  try {
    const available = await probeMarvin();
    if (!windowRef || windowRef.isDestroyed()) return;
    const current = windowRef.webContents.getURL();
    if (available && (force || !isAvatarUrl(current))) {
      await windowRef.loadURL(AVATAR_URL);
    } else if (!available && (force || current !== OFFLINE_URL)) {
      await windowRef.loadFile(OFFLINE_PATH);
    }
  } finally {
    availabilityCheckRunning = false;
  }
}

function startAvailabilityMonitor() {
  if (availabilityTimer) clearInterval(availabilityTimer);
  availabilityTimer = setInterval(() => {
    loadAvailableView().catch(() => {});
  }, 2000);
}

function createWindow() {
  const initialBounds = initialWindowBounds();
  windowRef = new BrowserWindow({
    ...initialBounds,
    minWidth: MIN_WIDTH,
    minHeight: MIN_HEIGHT,
    frame: false,
    show: false,
    skipTaskbar: false,
    transparent: false,
    resizable: true,
    hasShadow: true,
    alwaysOnTop: true,
    backgroundColor: '#09090b',
    title: 'Marvin',
    icon: ICON_PATH,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
    },
  });
  windowRef.setAlwaysOnTop(true, 'floating');
  windowRef.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  windowRef.webContents.on('will-navigate', (event, target) => {
    if (!isAvatarUrl(target) && target !== OFFLINE_URL) event.preventDefault();
  });
  windowRef.webContents.on('did-fail-load', (_event, errorCode, _description, validatedUrl, isMainFrame) => {
    if (!isMainFrame || errorCode === -3 || !isAvatarUrl(validatedUrl)) return;
    // Without this fallback Chromium replaces Marvin with ERR_CONNECTION_REFUSED,
    // leaving no start control when Next.js stops after the initial load.
    windowRef.loadFile(OFFLINE_PATH).catch(() => {});
  });
  windowRef.once('ready-to-show', () => {
    if (!windowRef || windowRef.isDestroyed()) return;
    windowRef.show();
    windowRef.focus();
  });
  windowRef.on('move', scheduleWindowStateSave);
  windowRef.on('resize', scheduleWindowStateSave);
  loadAvailableView({ force: true });
  startAvailabilityMonitor();
}

function stopResize() {
  if (resizeTimer) clearInterval(resizeTimer);
  resizeTimer = null;
  resizeState = null;
}

function startResize(edge) {
  if (!windowRef || windowRef.isDestroyed() || !/^(n|s|e|w|ne|nw|se|sw)$/.test(String(edge))) return false;
  stopResize();
  resizeState = { edge, startCursor: screen.getCursorScreenPoint(), startBounds: windowRef.getBounds() };
  resizeTimer = setInterval(() => {
    if (!windowRef || windowRef.isDestroyed() || !resizeState) return stopResize();
    const point = screen.getCursorScreenPoint();
    const work = screen.getDisplayNearestPoint(point).workArea;
    const dx = point.x - resizeState.startCursor.x;
    const dy = point.y - resizeState.startCursor.y;
    const base = resizeState.startBounds;
    let { x, y, width, height } = base;
    if (resizeState.edge.includes('e')) width = Math.max(MIN_WIDTH, base.width + dx);
    if (resizeState.edge.includes('w')) {
      width = Math.max(MIN_WIDTH, base.width - dx);
      x = base.x + (base.width - width);
    }
    if (resizeState.edge.includes('s')) height = Math.max(MIN_HEIGHT, base.height + dy);
    if (resizeState.edge.includes('n')) {
      height = Math.max(MIN_HEIGHT, base.height - dy);
      y = base.y + (base.height - height);
    }
    width = Math.min(width, work.width);
    height = Math.min(height, work.height);
    x = Math.max(work.x, Math.min(x, work.x + work.width - width));
    y = Math.max(work.y, Math.min(y, work.y + work.height - height));
    windowRef.setBounds({ x: Math.round(x), y: Math.round(y), width: Math.round(width), height: Math.round(height) }, false);
  }, 16);
  return true;
}

function setWindowMode(mode) {
  if (!windowRef || windowRef.isDestroyed()) return { mode: 'expanded' };
  const target = mode === 'compact' ? { width: 390, height: 470 } : { width: 560, height: 760 };
  const current = windowRef.getBounds();
  const center = { x: current.x + Math.round(current.width / 2), y: current.y + Math.round(current.height / 2) };
  const work = screen.getDisplayNearestPoint(center).workArea;
  const width = Math.min(target.width, work.width);
  const height = Math.min(target.height, work.height);
  const x = Math.max(work.x, Math.min(center.x - Math.round(width / 2), work.x + work.width - width));
  const y = Math.max(work.y, Math.min(center.y - Math.round(height / 2), work.y + work.height - height));
  windowRef.setBounds({ x, y, width, height }, true);
  return { mode: mode === 'compact' ? 'compact' : 'expanded', bounds: windowRef.getBounds() };
}

if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => {
    if (windowRef) {
      if (windowRef.isMinimized()) windowRef.restore();
      windowRef.show();
      windowRef.focus();
    }
  });
  app.whenReady().then(() => {
    session.defaultSession.setPermissionCheckHandler((webContents, permission, requestingOrigin, details) => (
      permission === 'media'
      && isAvatarOrigin(requestingOrigin)
      && details?.mediaType === 'audio'
      && isAvatarUrl(webContents?.getURL() || '')
    ));
    session.defaultSession.setPermissionRequestHandler((webContents, permission, callback, details) => {
      const mediaTypes = Array.isArray(details?.mediaTypes) ? details.mediaTypes : [];
      callback(
        permission === 'media'
        && isAvatarUrl(details?.requestingUrl || webContents.getURL())
        && mediaTypes.length > 0
        && mediaTypes.every((type) => type === 'audio')
      );
    });
    createWindow();
    globalShortcut.register('CommandOrControl+Shift+Space', () => {
      if (!windowRef || windowRef.isDestroyed()) return createWindow();
      if (windowRef.isMinimized()) windowRef.restore();
      windowRef.show();
      windowRef.focus();
    });
  });
}

ipcMain.handle('marvin:status', async (event) => trustedSender(event) ? { running: await probeMarvin() } : { running: false });
ipcMain.handle('marvin:start', async (event) => {
  if (!trustedSender(event)) return { success: false, error: 'Origine refusée.' };
    if (!(await probeMarvin())) {
    try {
      const command = process.env.ComSpec || 'cmd.exe';
      await runDetached(command, ['/d', '/c', 'call', path.join(ROOT, 'start.bat')], { logPath: STARTUP_LOG_PATH });
    } catch (error) {
      return { success: false, error: `Démarrage impossible : ${error?.message || error}` };
    }
  }
  const success = await waitForMarvin();
  if (success) await loadAvailableView();
  return success
    ? { success: true }
    : { success: false, error: `Marvin n'a pas répondu sous 90 secondes. Journal : ${STARTUP_LOG_PATH}` };
});
ipcMain.handle('marvin:stop', async (event) => {
  if (!trustedSender(event)) return { success: false, error: 'Origine refusée.' };
  try {
    await runToCompletion(
      'powershell.exe',
      [
        '-NoProfile',
        '-NonInteractive',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        path.join(ROOT, 'scripts', 'stop-marvin.ps1'),
      ],
      { logPath: SHUTDOWN_LOG_PATH, timeoutMs: 70000 },
    );
    if (!(await waitForMarvinStop())) {
      return {
        success: false,
        error: `Marvin répond encore après l'arrêt. Journal : ${SHUTDOWN_LOG_PATH}`,
      };
    }
    setTimeout(() => loadAvailableView(), 100);
    return { success: true };
  } catch (error) {
    return {
      success: false,
      error: `Arrêt impossible : ${error?.message || error}. Journal : ${SHUTDOWN_LOG_PATH}`,
    };
  }
});
ipcMain.handle('marvin:open-main', async (event) => {
  if (!trustedSender(event)) return { success: false, error: 'Origine refusée.' };
  try {
    await shell.openExternal(MAIN_URL, { activate: true });
    // L'avatar est toujours au premier plan : le réduire évite de donner
    // l'impression que le navigateur ne s'est pas ouvert derrière lui.
    if (windowRef && !windowRef.isDestroyed()) windowRef.minimize();
    return { success: true };
  } catch (error) {
    return { success: false, error: `Ouverture impossible : ${error?.message || error}` };
  }
});
ipcMain.handle('marvin:window-mode', (event, mode) => {
  if (!trustedSender(event)) return { mode: 'expanded', error: 'Origine refusée.' };
  return setWindowMode(mode);
});
ipcMain.on('marvin:resize-start', (event, edge) => { if (trustedSender(event)) startResize(edge); });
ipcMain.on('marvin:resize-stop', (event) => { if (trustedSender(event)) stopResize(); });
ipcMain.handle('marvin:minimize', (event) => {
  if (!trustedSender(event) || !windowRef || windowRef.isDestroyed()) return { success: false };
  windowRef.minimize();
  return { success: true };
});
ipcMain.handle('marvin:quit-avatar', (event) => {
  if (trustedSender(event)) app.quit();
});

app.on('before-quit', () => {
  stopResize();
  if (availabilityTimer) clearInterval(availabilityTimer);
  availabilityTimer = null;
  if (saveTimer) clearTimeout(saveTimer);
  saveWindowState();
  globalShortcut.unregisterAll();
});
app.on('window-all-closed', () => app.quit());
