import path from 'path';

// v2.111 — proxy vers les outils Python (file_list/file_info/file_find/file_create_folder/
// file_rename/file_move/file_copy/file_delete) au lieu d'un accès fs Node direct. Seules les
// ~13 actions réellement câblées ici sont migrées — l'ancien lib/services/fileManager.js
// exportait aussi readFileContent/writeFileContent/searchTextInFiles/convertDocxToPdf/
// createDocx/editDocx/appendToDocx/getPdfInfo, confirmés SANS AUCUN appelant nulle part
// (grep avant migration) : du code mort, jamais porté ici. Les opérations de composition
// (organize par catégorie, batch*, calcul de nouveau nom) restent orchestrées ici en JS
// (pure logique de chaînes/boucles, aucun accès disque direct) mais chaque opération
// filesystem individuelle passe par un outil Python.
const BACKEND = (typeof window !== 'undefined' && window.location
  ? window.location.protocol + '//' + window.location.hostname + ':8005'
  : (process.env.NEXT_PUBLIC_BACKEND_URL || 'http://127.0.0.1:8005'));

const FILE_CATEGORIES = {
  Documents: ['.pdf', '.doc', '.docx', '.txt', '.xls', '.xlsx', '.ppt', '.pptx', '.odt', '.csv', '.rtf', '.md'],
  Images: ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.webp', '.ico', '.tiff'],
  Videos: ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm'],
  Musique: ['.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma', '.m4a'],
  Archives: ['.zip', '.rar', '.7z', '.tar', '.gz', '.bz2'],
  Programmes: ['.exe', '.msi', '.bat', '.cmd', '.ps1'],
};
function categoryFor(filename) {
  const ext = path.extname(filename).toLowerCase();
  for (const [cat, exts] of Object.entries(FILE_CATEGORIES)) {
    if (exts.includes(ext)) return cat;
  }
  return 'Autres';
}

async function callTool(toolName, args) {
  const r = await fetch(`${BACKEND}/api/tools`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ toolName, args }),
    signal: AbortSignal.timeout(30000),
  });
  if (!r.ok) throw new Error(`Backend ${r.status}`);
  const data = await r.json();
  const result = data.result ?? data;
  if (result && result.error) throw new Error(result.error);
  return result;
}

// Python renvoie 'modified' en "DD/MM/YYYY HH:MM" (affichage lisible) — reconstruit un ISO
// pour que `new Date(file.modified)` continue de fonctionner côté page.jsx sans y toucher.
function toIso(displayDate) {
  const m = /^(\d{2})\/(\d{2})\/(\d{4}) (\d{2}):(\d{2})$/.exec(displayDate || '');
  if (!m) return '';
  const [, dd, mm, yyyy, hh, min] = m;
  return `${yyyy}-${mm}-${dd}T${hh}:${min}:00`;
}

function transformEntry(e) {
  return {
    name: e.name,
    type: e.type,
    size: e.type === 'dossier' ? null : e.size,
    category: e.category,
    path: e.path,
    modified: toIso(e.modified),
  };
}

export async function GET(req) {
  const { searchParams } = new URL(req.url);
  const action = searchParams.get('action') || 'list';
  const dirPath = searchParams.get('path') || '.';
  const pattern = searchParams.get('q');
  const filePath = searchParams.get('file');

  try {
    if (action === 'info' && filePath) {
      const info = await callTool('file_info', { path: filePath });
      return Response.json({ success: true, ...info });
    }

    if (action === 'search' && pattern) {
      // include_dirs=false (défaut Python) → uniquement des fichiers dans les résultats.
      // file_find renvoie un champ 'type' incohérent selon la méthode utilisée (l'index
      // Windows Search y met un type MIME/extension comme ".txt", pas "fichier"/"dossier")
      // — ne JAMAIS s'y fier ; avec include_dirs=false le type est toujours 'fichier'.
      const r = await callTool('file_find', { path: dirPath, pattern: `*${pattern}*`, max_results: 50, include_dirs: false });
      const results = (r.results || []).map((f) => ({
        name: f.name,
        type: 'fichier',
        size: typeof f.size === 'number' ? `${(f.size / 1024).toFixed(1)} Ko` : (f.size ?? null),
        path: f.path,
        category: categoryFor(f.name || ''),
      }));
      return Response.json({ success: true, results });
    }

    if (action === 'sandbox') {
      return Response.json({ success: true, sandboxRoot: process.platform === 'win32' ? 'C:\\' : '/' });
    }

    const r = await callTool('file_list', { path: dirPath });
    const files = (r.files || []).map(transformEntry);
    return Response.json({ success: true, files, currentDir: r.currentDir || dirPath, sandboxRoot: process.platform === 'win32' ? 'C:\\' : '/' });
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
}

export async function POST(req) {
  try {
    const body = await req.json();
    const { action, parentPath, folderName, directoryPath } = body;

    if (action === 'createFolder') {
      const fullPath = path.join(parentPath || '.', folderName);
      await callTool('file_create_folder', { path: fullPath });
      return Response.json({ success: true, path: fullPath });
    }

    if (action === 'organize') {
      const dir = directoryPath || '.';
      const listing = await callTool('file_list', { path: dir });
      const moved = [];
      for (const entry of listing.files || []) {
        if (entry.type === 'dossier') continue;
        const category = categoryFor(entry.name);
        if (category === 'Autres') continue; // ne pas déplacer les fichiers non catégorisés
        const destDir = path.join(listing.currentDir || dir, category);
        // Toujours passer le chemin de fichier COMPLET (dossier + nom), jamais juste le
        // dossier destination : file_move ne recrée le nom source que si la destination
        // est déjà un dossier EXISTANT — sinon il traite la destination comme un nom de
        // fichier littéral (bug réel trouvé en testant : "Images"/"Videos" créés comme
        // fichiers vides au lieu de dossiers, la 1ère fois que le dossier n'existait pas).
        const destFile = path.join(destDir, entry.name);
        try {
          await callTool('file_move', { source: entry.path, destination: destFile });
          moved.push({ name: entry.name, category, from: entry.path, to: destFile });
        } catch (e) {
          // une erreur sur 1 fichier ne doit pas interrompre le classement des autres
        }
      }
      return Response.json({ success: true, movedCount: moved.length, details: moved });
    }

    return Response.json({ error: 'Action non reconnue' }, { status: 400 });
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
}

export async function PATCH(req) {
  try {
    const body = await req.json();
    const { action, filePath, newName, destinationDir } = body;

    if (action === 'rename') {
      const r = await callTool('file_rename', { source: filePath, new_name: newName });
      return Response.json({ success: true, oldPath: filePath, newPath: r.new_path });
    }

    if (action === 'move') {
      const dest = path.join(destinationDir, path.basename(filePath));
      const r = await callTool('file_move', { source: filePath, destination: dest });
      return Response.json({ success: true, oldPath: filePath, newPath: r.destination });
    }

    return Response.json({ error: 'Action non reconnue' }, { status: 400 });
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
}

export async function DELETE(req) {
  try {
    const body = await req.json();
    if (Array.isArray(body.filePaths)) {
      const deleted = [];
      const errors = [];
      for (const fp of body.filePaths) {
        try {
          await callTool('file_delete', { path: fp, confirmed: true });
          deleted.push(fp);
        } catch (e) {
          errors.push({ path: fp, error: e.message });
        }
      }
      return Response.json({ success: errors.length === 0, deleted, errors });
    }
    await callTool('file_delete', { path: body.filePath, confirmed: true });
    return Response.json({ success: true, deleted: body.filePath });
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
}

// ── Opérations par lot ──────────────────────────────────

export async function PUT(req) {
  try {
    const body = await req.json();
    const { action, filePaths, destinationDir, pattern } = body;

    if (action === 'batchMove' && Array.isArray(filePaths) && destinationDir) {
      const moved = [];
      const errors = [];
      for (const fp of filePaths) {
        try {
          // Chemin complet, pas juste le dossier — cf. commentaire dans l'action 'organize'.
          const dest = path.join(destinationDir, path.basename(fp));
          const r = await callTool('file_move', { source: fp, destination: dest });
          moved.push({ from: fp, to: r.destination });
        } catch (e) {
          errors.push({ path: fp, error: e.message });
        }
      }
      return Response.json({ success: errors.length === 0, moved, errors });
    }

    if (action === 'batchCopy' && Array.isArray(filePaths) && destinationDir) {
      const copied = [];
      const errors = [];
      for (const fp of filePaths) {
        try {
          const dest = path.join(destinationDir, path.basename(fp));
          const r = await callTool('file_copy', { source: fp, destination: dest });
          copied.push({ from: fp, to: r.destination || dest });
        } catch (e) {
          errors.push({ path: fp, error: e.message });
        }
      }
      return Response.json({ success: errors.length === 0, copied, errors });
    }

    if (action === 'batchRename' && Array.isArray(filePaths) && pattern) {
      const renamed = [];
      const errors = [];
      let i = 1;
      for (const fp of filePaths) {
        try {
          const ext = path.extname(fp);
          const newName = pattern.replace('{n}', i).replace('{ext}', ext.slice(1)) + ext;
          const r = await callTool('file_rename', { source: fp, new_name: newName });
          renamed.push({ from: fp, to: r.new_path });
          i++;
        } catch (e) {
          errors.push({ path: fp, error: e.message });
        }
      }
      return Response.json({ success: errors.length === 0, renamed, errors });
    }

    return Response.json({ error: 'Action non reconnue' }, { status: 400 });
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
}
