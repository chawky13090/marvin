'use client';

import { useState, useEffect, useCallback } from 'react';

const BACKEND = (typeof window !== 'undefined' && window.location ? window.location.protocol + '//' + window.location.hostname + ':8005' : (process.env.NEXT_PUBLIC_BACKEND_URL || 'http://127.0.0.1:8005'));

const KIND = {
  lan:       { label: 'Wi-Fi / réseau local', color: '#34d399', note: 'Rapide sur le même Wi-Fi — l\'adresse change selon le lieu.' },
  tailscale: { label: 'Tailscale (stable)',   color: '#c084fc', note: 'Ne change JAMAIS, marche même à distance. À mettre en favori ! 👍' },
  autre:     { label: 'Autre réseau',         color: '#60a5fa', note: '' },
  virtuel:   { label: 'Adaptateur virtuel',   color: '#6b7280', note: 'Probablement inutile (VM).' },
};

function AddrCard({ addr, recommended }) {
  const k = KIND[addr.kind] || KIND.autre;
  const [copied, setCopied] = useState(false);
  const copy = () => { navigator.clipboard?.writeText(addr.url).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }); };
  return (
    <div style={{ display: 'flex', gap: 16, alignItems: 'center', padding: '16px 18px', borderRadius: 16,
      background: recommended ? 'rgba(192,132,252,0.07)' : 'rgba(255,255,255,0.03)',
      border: `1px solid ${recommended ? 'rgba(192,132,252,0.35)' : 'var(--border)'}` }}>
      <img src={`${BACKEND}/api/network/qr?url=${encodeURIComponent(addr.url)}`} alt="QR" width={104} height={104}
        style={{ borderRadius: 10, background: '#fff', padding: 6, flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: k.color }}>{k.label}</span>
          {addr.primary && <span style={{ fontSize: 10, color: '#34d399', border: '1px solid rgba(52,211,153,0.4)', borderRadius: 6, padding: '1px 6px' }}>ACTUEL</span>}
          {recommended && <span style={{ fontSize: 10, color: '#c084fc', border: '1px solid rgba(192,132,252,0.5)', borderRadius: 6, padding: '1px 6px' }}>RECOMMANDÉ</span>}
        </div>
        <div onClick={copy} title="Copier" style={{ fontSize: 19, fontWeight: 800, color: 'var(--text-primary)', margin: '6px 0', cursor: 'pointer', wordBreak: 'break-all' }}>
          {addr.url} <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{copied ? '✅ copié' : '📋'}</span>
        </div>
        {k.note && <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{k.note}</div>}
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>via {addr.interface}</div>
      </div>
    </div>
  );
}

export default function MobilePage() {
  const [net, setNet] = useState(null);
  const [err, setErr] = useState('');

  const load = useCallback(async () => {
    try { const r = await fetch(`${BACKEND}/api/network`).then(r => r.json()); setNet(r); setErr(''); }
    catch { setErr('Backend injoignable.'); }
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 8000); return () => clearInterval(t); }, [load]); // auto-update si l'IP change

  const addrs = (net?.addresses || []).filter(a => a.kind !== 'virtuel');
  const virtuals = (net?.addresses || []).filter(a => a.kind === 'virtuel');
  const tailscale = addrs.find(a => a.kind === 'tailscale');
  const lanPrimary = addrs.find(a => a.kind === 'lan' && a.primary) || addrs.find(a => a.kind === 'lan');
  const rest = addrs.filter(a => a !== tailscale && a !== lanPrimary);

  return (
    <div style={{ height: '100vh', overflowY: 'auto', background: 'var(--bg-primary)', color: 'var(--text-primary)', padding: '28px 32px' }}>
      <div style={{ maxWidth: 720, margin: '0 auto' }}>
        <h1 style={{ margin: 0, fontSize: '1.6rem', color: '#34d399' }}>📱 Accès mobile</h1>
        <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 6 }}>
          Ouvre une de ces adresses sur ton téléphone (ou scanne le QR code). La liste se met à jour automatiquement quand tu changes de réseau.
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 20 }}>
          PC : <strong style={{ color: 'var(--text-secondary)' }}>{net?.hostname || '…'}</strong> · <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: '#34d399' }} /> mise à jour en direct
        </div>

        {err && <div style={{ color: '#f87171', fontSize: 13, marginBottom: 12 }}>{err}</div>}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {tailscale && <AddrCard addr={tailscale} recommended />}
          {lanPrimary && <AddrCard addr={lanPrimary} recommended={!tailscale} />}
          {rest.map(a => <AddrCard key={a.ip} addr={a} />)}
          {addrs.length === 0 && !err && <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>Recherche des adresses réseau…</div>}
        </div>

        {!tailscale && (
          <div style={{ marginTop: 18, padding: '14px 16px', background: 'rgba(192,132,252,0.06)', border: '1px solid rgba(192,132,252,0.25)', borderRadius: 12, fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
            💡 <strong>Astuce anti-changement d'IP :</strong> installe <a href="https://tailscale.com/download" target="_blank" rel="noreferrer" style={{ color: '#c084fc' }}>Tailscale</a> (gratuit) sur ton PC et ton téléphone. Tu obtiens une adresse qui <strong>ne change jamais</strong>, même quand tu changes de lieu, et qui marche aussi à distance (hors Wi-Fi).
          </div>
        )}

        {virtuals.length > 0 && (
          <details style={{ marginTop: 16 }}>
            <summary style={{ fontSize: 12, color: 'var(--text-muted)', cursor: 'pointer' }}>Adresses d'adaptateurs virtuels ({virtuals.length}) — généralement inutiles</summary>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
              {virtuals.map(a => <AddrCard key={a.ip} addr={a} />)}
            </div>
          </details>
        )}

        <div style={{ marginTop: 22, fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.7 }}>
          ⚠️ Si ça ne charge pas sur le téléphone : vérifie que le PC et le téléphone sont sur le <strong>même Wi-Fi</strong>, et autorise les ports 3000/8005 dans le pare-feu Windows si demandé. Le frontend doit avoir été lancé avec <code>npm run dev</code> (déjà configuré pour le réseau).
        </div>
      </div>
    </div>
  );
}
