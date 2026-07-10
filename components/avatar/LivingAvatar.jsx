'use client';

/**
 * LivingAvatar — indicateur de statut de Marvin : un cœur minimal qui pulse
 * doucement au repos et s'accélère quand `thinking` est vrai. Pensé comme le
 * badge d'un outil IA professionnel (pas un avatar figuratif) : géométrique,
 * sobre, un seul accent de couleur.
 *
 * 100% SVG + CSS (GPU). Props : size (px), thinking (bool), idleBeat/activeBeat (s).
 */
export default function LivingAvatar({ size = 120, thinking = false, idleBeat = 2.6, activeBeat = 0.9 }) {
  const beat = thinking ? activeBeat : idleBeat;
  return (
    <div className="la-root" style={{ width: size, height: size, position: 'relative', display: 'inline-block' }}>
      <style>{`
        .la-root .la-ring   { transform-origin: 60px 60px; animation: laSpin 14s linear infinite; opacity: ${thinking ? 0.9 : 0.35}; }
        .la-root .la-core   { transform-origin: 60px 60px; animation: laBeat var(--beat,2.6s) ease-in-out infinite; }
        .la-root .la-halo   { transform-origin: 60px 60px; animation: laHalo var(--beat,2.6s) ease-in-out infinite; }
        @keyframes laSpin { to { transform: rotate(360deg); } }
        @keyframes laBeat {
          0%,100% { transform: scale(1); }
          50%     { transform: scale(1.08); }
        }
        @keyframes laHalo { 0%,100% { opacity:.25 } 50%{ opacity:.55 } }
        @media (prefers-reduced-motion: reduce){
          .la-root .la-ring,.la-root .la-core,.la-root .la-halo{animation:none!important}
        }
      `}</style>
      <svg viewBox="0 0 120 120" width={size} height={size} style={{ '--beat': beat + 's' }} xmlns="http://www.w3.org/2000/svg">
        <defs>
          <radialGradient id="laCore" cx="50%" cy="50%" r="50%">
            <stop offset="0%"  stopColor="#8fc4ff" />
            <stop offset="55%" stopColor="#4f8cff" />
            <stop offset="100%" stopColor="#4f8cff" stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* Halo doux */}
        <circle className="la-halo" cx="60" cy="60" r="42" fill="url(#laCore)" opacity="0.3" />

        {/* Anneau de statut (tourne plus vite / plus visible quand Marvin travaille) */}
        <circle className="la-ring" cx="60" cy="60" r="46" fill="none" stroke="#4f8cff"
                strokeWidth="2" strokeDasharray="6 10" strokeLinecap="round" />

        {/* Cadre géométrique sobre */}
        <rect x="26" y="26" width="68" height="68" rx="18" fill="rgba(16,17,22,0.7)" stroke="rgba(228,228,231,0.14)" strokeWidth="1.5" />

        {/* Cœur de statut */}
        <g className="la-core">
          <circle cx="60" cy="60" r="11" fill="url(#laCore)" />
          <circle cx="60" cy="60" r="11" fill="none" stroke="#8fc4ff" strokeOpacity="0.5" strokeWidth="1" />
        </g>
      </svg>
    </div>
  );
}
