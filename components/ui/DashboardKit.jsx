'use client';

/**
 * DashboardKit — briques réutilisables pour toute page de type tableau de bord
 * (jauges, barres, cartes stat, mini-graphes, panneaux à défilement propre).
 * Extrait de la refonte de /monitoring (v2.100) pour éviter que la prochaine
 * page-dashboard réinvente les mêmes styles inline à la main.
 */

// ── Gauge circulaire ────────────────────────────────────────────────────────
// `invert` : pour une jauge où un pourcentage ÉLEVÉ est BON (ex. score de santé),
// inverse le seuil de couleur (par défaut : haut = mauvais, ex. usage CPU/RAM/disque).
// `suffix` : texte après la valeur ("%" par défaut, mettre "/100" pour un score).
export function CircleGauge({ value, max = 100, label, color = '#4f8cff', size = 120, invert = false, suffix = '%' }) {
  const radius = 44;
  const circumference = 2 * Math.PI * radius;
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  const offset = circumference - (pct / 100) * circumference;
  const textColor = invert
    ? (pct >= 95 ? '#34d399' : pct >= 70 ? '#f97316' : '#ef4444')
    : (pct > 85 ? '#ef4444' : pct > 60 ? '#f97316' : color);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '6px' }}>
      <svg width={size} height={size} viewBox="0 0 100 100">
        <circle cx="50" cy="50" r={radius} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="8" />
        <circle
          cx="50" cy="50" r={radius}
          fill="none" stroke={textColor} strokeWidth="8"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform="rotate(-90 50 50)"
          style={{ transition: 'stroke-dashoffset 0.6s ease, stroke 0.3s ease' }}
        />
        <text x="50" y="46" textAnchor="middle" fill={textColor} fontSize="18" fontWeight="700" fontFamily="monospace">
          {Math.round(value)}{suffix}
        </text>
        <text x="50" y="62" textAnchor="middle" fill="rgba(255,255,255,0.4)" fontSize="9">
          {label}
        </text>
      </svg>
    </div>
  );
}

// ── Barre horizontale (ex: usage disque) ───────────────────────────────────
export function BarRow({ label, used, total, color = '#4f8cff' }) {
  const pct = total > 0 ? Math.round((used / total) * 100) : 0;
  const barColor = pct > 85 ? '#ef4444' : pct > 65 ? '#f97316' : color;
  return (
    <div style={{ marginBottom: '10px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
        <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'monospace' }}>{label}</span>
        <span style={{ fontSize: '11px', color: barColor, fontFamily: 'monospace' }}>
          {used.toFixed(1)} / {total.toFixed(1)} GB ({pct}%)
        </span>
      </div>
      <div style={{ height: '6px', background: 'rgba(255,255,255,0.06)', borderRadius: '3px', overflow: 'hidden' }}>
        <div style={{
          height: '100%', width: `${pct}%`, background: barColor,
          borderRadius: '3px', transition: 'width 0.6s ease',
          boxShadow: `0 0 6px ${barColor}44`,
        }} />
      </div>
    </div>
  );
}

// ── Stat card ───────────────────────────────────────────────────────────────
export function StatCard({ label, value, unit = '', color = 'var(--text-secondary)', icon = '' }) {
  return (
    <div style={{
      background: 'rgba(255,255,255,0.03)',
      border: '1px solid rgba(255,255,255,0.07)',
      borderRadius: '10px',
      padding: '14px 18px',
      display: 'flex',
      flexDirection: 'column',
      gap: '4px',
      minWidth: '110px',
    }}>
      <div style={{ fontSize: '11px', color: 'var(--text-muted)', letterSpacing: '0.06em' }}>{icon} {label}</div>
      <div style={{ fontSize: '1.35rem', fontWeight: 700, fontFamily: 'monospace', color }}>
        {value}<span style={{ fontSize: '0.75rem', fontWeight: 400, opacity: 0.6, marginLeft: '3px' }}>{unit}</span>
      </div>
    </div>
  );
}

// ── Historique mini-graphe (sparkline) ──────────────────────────────────────
export function Sparkline({ data, color = '#4f8cff', height = 40, width = 160 }) {
  if (!data || data.length < 2) return null;
  const max = Math.max(...data, 1);
  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - (v / max) * (height - 4);
    return `${x},${y}`;
  }).join(' ');

  return (
    <svg width={width} height={height} style={{ overflow: 'visible' }}>
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <polyline
        points={`0,${height} ${points} ${width},${height}`}
        fill={`${color}18`} stroke="none"
      />
    </svg>
  );
}

// ── Panneau (carte avec titre + zone d'action, hauteur/scroll maîtrisables) ──
// Pattern « défilement indépendant » : passer style={{ maxHeight: N }} pour que
// le panneau garde une hauteur fixe et fasse défiler SON contenu, plutôt que de
// pousser toute la page vers le bas (voir /monitoring, v2.100).
export function Panel({ title, action, children, style }) {
  return (
    <div style={{
      background: 'rgba(255,255,255,0.03)',
      border: '1px solid rgba(255,255,255,0.07)',
      borderRadius: '14px',
      display: 'flex', flexDirection: 'column',
      minHeight: 0,
      ...style,
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '16px 20px 12px', flexShrink: 0,
      }}>
        <span style={{ fontWeight: 600, fontSize: '0.95rem' }}>{title}</span>
        {action}
      </div>
      {children}
    </div>
  );
}
