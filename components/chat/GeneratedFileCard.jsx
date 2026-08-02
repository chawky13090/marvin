'use client';
import { useState } from 'react';
import { useToast } from '@/components/ui/Toast';
import { BACKEND_URL } from '@/lib/backend';

// v2.128 — les outils qui GÉNÈRENT un document (PDF/Word/Excel...) renvoyaient juste
// { success, message, path } → rendu par le fallback "succès générique" (un simple ✅),
// obligeant l'utilisateur à aller chercher le fichier lui-même sur le disque. Demandé
// explicitement (« j'aimerais pouvoir cliquer et ouvrir les documents générés directement
// depuis le chat »). Détecté par EXTENSION du path plutôt que par nom d'outil un par un
// (file_create_pdf, document_generate, billing_quote_pdf, file_convert_docx_to_pdf...
// tous partagent la même forme de résultat) — plus robuste à un futur outil de génération.
export const DOCUMENT_EXTENSIONS = new Set([
  'pdf', 'docx', 'doc', 'rtf', 'odt', 'xlsx', 'xls', 'csv', 'pptx', 'ppt', 'txt', 'md',
  // v2.145 — webapp_create ("ChatGPT Sites") génère une mini-appli HTML autonome ;
  // pc_open_file (os.startfile) ouvre déjà un .html dans le navigateur par défaut,
  // zéro code supplémentaire nécessaire côté ouverture — juste la reconnaître ici.
  'html', 'htm',
]);
// v2.142 — code_python capture désormais les fichiers écrits par le code exécuté (Code
// Interpreter local) : le cas le plus courant est un graphique matplotlib. Set séparé
// (pas fusionné à DOCUMENT_EXTENSIONS) pour permettre un rendu en VIGNETTE plutôt qu'une
// simple icône cliquable — voir GeneratedFileCard.
export const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp']);

function docIcon(ext) {
  const map = {
    pdf: '📕', docx: '📝', doc: '📝', rtf: '📝', odt: '📝',
    xlsx: '📗', xls: '📗', csv: '📗', pptx: '📊', ppt: '📊', txt: '📄', md: '📄',
    html: '🌐', htm: '🌐',
  };
  return map[ext] || '📄';
}

// v2.183 — laisser le choix du format même APRÈS génération (demandé explicitement) :
// docx<->pdf uniquement pour l'instant (voir document_convert_format côté backend).
const CONVERTIBLE_TARGET = { docx: 'pdf', pdf: 'docx' };

export default function GeneratedFileCard({ path, message, securityWarning }) {
  const [status, setStatus] = useState('idle'); // idle | opening | error
  const [converting, setConverting] = useState(false);
  const { toast } = useToast();
  const fileName = path.split(/[\\/]/).pop() || path;
  const ext = (fileName.split('.').pop() || '').toLowerCase();
  const isImage = IMAGE_EXTENSIONS.has(ext);
  const convertTarget = CONVERTIBLE_TARGET[ext];

  const handleOpen = async () => {
    setStatus('opening');
    try {
      const res = await fetch(`${BACKEND_URL}/api/tools`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ toolName: 'pc_open_file', args: { path, confirmed: true } }),
      });
      const data = await res.json();
      setStatus(data?.result?.success ? 'idle' : 'error');
    } catch {
      setStatus('error');
    }
  };

  const handleConvert = async (e) => {
    e.stopPropagation();
    if (!convertTarget || converting) return;
    setConverting(true);
    try {
      const res = await fetch(`${BACKEND_URL}/api/tools`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          toolName: 'document_convert_format',
          args: { path, target_format: convertTarget, confirmed: true },
        }),
      });
      const data = await res.json();
      if (data?.result?.success) {
        toast.success(`Converti en ${convertTarget.toUpperCase()}`, data.result.path.split(/[\\/]/).pop());
      } else {
        toast.error('Échec de la conversion', data?.result?.error || data?.error || '');
      }
    } catch (err) {
      toast.error('Échec de la conversion', err.message);
    } finally {
      setConverting(false);
    }
  };

  // v2.142 — un fichier image (graphique généré par code_python) se prête à une
  // VIGNETTE inline plutôt qu'à une simple icône — sert le fichier via l'endpoint
  // déjà existant /api/files/raw (utilisé ailleurs pour la visionneuse de fichiers).
  if (isImage) {
    return (
      <div>
        <div
          onClick={handleOpen}
          title={`${path} — cliquer pour ouvrir`}
          style={{
            display: 'inline-block', padding: '8px', background: 'var(--bg-tertiary)',
            border: '1px solid var(--border)', borderRadius: '8px', cursor: 'pointer',
          }}
        >
          <img
            src={`${BACKEND_URL}/api/files/raw?path=${encodeURIComponent(path)}`}
            alt={fileName}
            style={{ maxWidth: '360px', maxHeight: '320px', display: 'block', borderRadius: '4px' }}
          />
          <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '6px', textAlign: 'center' }}>
            {fileName}{message ? ` — ${message}` : ''}
          </div>
        </div>
        {securityWarning && (
          <div style={{
            marginTop: '6px', padding: '8px 12px',
            background: 'var(--danger-bg, rgba(239,68,68,0.08))', border: '1px solid var(--danger)',
            borderRadius: '6px', fontSize: '11px', color: 'var(--danger)', whiteSpace: 'pre-wrap',
          }}>
            {securityWarning}
          </div>
        )}
      </div>
    );
  }

  return (
    <div>
      <div
        onClick={handleOpen}
        title={path}
        style={{
          display: 'flex', alignItems: 'center', gap: '10px',
          padding: '10px 14px', background: 'var(--bg-tertiary)',
          border: '1px solid var(--border)', borderRadius: '8px',
          cursor: status === 'opening' ? 'wait' : 'pointer',
        }}
      >
        <span style={{ fontSize: '22px' }}>{docIcon(ext)}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 'var(--font-xs)', color: 'var(--accent-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {fileName}
          </div>
          {message && (
            <div style={{ fontSize: '11px', color: 'var(--success)', marginTop: '2px' }}>✅ {message}</div>
          )}
          {status === 'error' && (
            <div style={{ fontSize: '11px', color: 'var(--danger)', marginTop: '2px' }}>Impossible d'ouvrir le fichier — vérifie qu'il existe toujours.</div>
          )}
        </div>
        <span style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
          {status === 'opening' ? '⏳ Ouverture...' : '📂 Ouvrir'}
        </span>
        {convertTarget && (
          <span
            onClick={handleConvert}
            title={`Convertir en .${convertTarget}`}
            style={{
              fontSize: 'var(--font-xs)', color: 'var(--accent-secondary)', whiteSpace: 'nowrap',
              cursor: converting ? 'wait' : 'pointer', borderLeft: '1px solid var(--border)', paddingLeft: '10px',
            }}
          >
            {converting ? '⏳ Conversion...' : `⇄ En .${convertTarget}`}
          </span>
        )}
      </div>
      {/* v2.133 — filet déterministe étendu au CONTENU des documents générés (pas seulement
          la réponse de chat visible) : le PDF GLPI qui a motivé ce chantier avait son problème
          dans le contenu du document, jamais dans le texte de chat lui-même. */}
      {securityWarning && (
        <div style={{
          marginTop: '6px', padding: '8px 12px',
          background: 'var(--danger-bg, rgba(239,68,68,0.08))', border: '1px solid var(--danger)',
          borderRadius: '6px', fontSize: '11px', color: 'var(--danger)', whiteSpace: 'pre-wrap',
        }}>
          {securityWarning}
        </div>
      )}
    </div>
  );
}
