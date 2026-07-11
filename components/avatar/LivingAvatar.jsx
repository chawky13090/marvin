'use client';

/**
 * LivingAvatar — indicateur de statut de Marvin : un cœur minimal qui pulse
 * doucement au repos et s'accélère quand `thinking` est vrai. Pensé comme le
 * badge d'un outil IA professionnel (pas un avatar figuratif) : géométrique,
 * sobre, un seul accent de couleur.
 *
 * v2.169 — retravaillé pour plus de profondeur (demande explicite : "le logo doit
 * être engageant, meilleur et plus travaillé") : double halo bicolore (bleu + cyan,
 * les deux couleurs d'accent déjà en place dans le thème), dégradé du cœur à 2 tons
 * au lieu d'un bleu plat, éclat orbital qui tourne en continu (signale une présence
 * "vivante" sans être distrayant), anneau au tracé plus fin.
 *
 * 100% SVG + CSS (GPU). Props : size (px), thinking (bool), idleBeat/activeBeat (s).
 */
export default function LivingAvatar({ size = 120, thinking = false, idleBeat = 2.6, activeBeat = 0.9 }) {
  const beat = thinking ? activeBeat : idleBeat;
  return (
    <div className="la-root" style={{ width: size, height: size, position: 'relative', display: 'inline-block' }}>
      <style>{`
        .la-root .la-ring    { transform-origin: 60px 60px; animation: laSpin 16s linear infinite; opacity: ${thinking ? 0.95 : 0.4}; }
        .la-root .la-orbit   { transform-origin: 60px 60px; animation: laSpin ${thinking ? '2.4s' : '6s'} linear infinite; }
        .la-root .la-core    { transform-origin: 60px 60px; animation: laBeat var(--beat,2.6s) ease-in-out infinite; }
        .la-root .la-halo    { transform-origin: 60px 60px; animation: laHalo var(--beat,2.6s) ease-in-out infinite; }
        .la-root .la-halo2   { transform-origin: 60px 60px; animation: laHalo var(--beat,2.6s) ease-in-out infinite reverse; }
        @keyframes laSpin { to { transform: rotate(360deg); } }
        @keyframes laBeat {
          0%,100% { transform: scale(1); }
          50%     { transform: scale(1.1); }
        }
        @keyframes laHalo { 0%,100% { opacity:.22 } 50%{ opacity:.5 } }
        @media (prefers-reduced-motion: reduce){
          .la-root .la-ring,.la-root .la-orbit,.la-root .la-core,.la-root .la-halo,.la-root .la-halo2{animation:none!important}
        }
      `}</style>
      <svg viewBox="0 0 120 120" width={size} height={size} style={{ '--beat': beat + 's' }} xmlns="http://www.w3.org/2000/svg">
        <defs>
          <radialGradient id="laCore" cx="42%" cy="38%" r="65%">
            <stop offset="0%"  stopColor="#c3e0ff" />
            <stop offset="40%" stopColor="#4f8cff" />
            <stop offset="100%" stopColor="#1d5fd6" />
          </radialGradient>
          <radialGradient id="laHaloBlue" cx="50%" cy="50%" r="50%">
            <stop offset="0%"  stopColor="#4f8cff" />
            <stop offset="100%" stopColor="#4f8cff" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="laHaloCyan" cx="50%" cy="50%" r="50%">
            <stop offset="0%"  stopColor="#38bdf8" />
            <stop offset="100%" stopColor="#38bdf8" stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* Double halo bicolore — profondeur chromatique */}
        <circle className="la-halo"  cx="54" cy="56" r="40" fill="url(#laHaloBlue)" opacity="0.28" />
        <circle className="la-halo2" cx="66" cy="64" r="36" fill="url(#laHaloCyan)" opacity="0.22" />

        {/* Cadre géométrique sobre */}
        <rect x="26" y="26" width="68" height="68" rx="18" fill="rgba(16,17,22,0.7)" stroke="rgba(228,228,231,0.14)" strokeWidth="1.5" />

        {/* Anneau de statut (tracé plus fin, tourne plus vite / plus visible quand Marvin travaille) */}
        <circle className="la-ring" cx="60" cy="60" r="46" fill="none" stroke="#4f8cff"
                strokeWidth="1.5" strokeDasharray="3 9" strokeLinecap="round" />

        {/* Éclat orbital — signale une présence active sans être distrayant */}
        <g className="la-orbit">
          <circle cx="60" cy="17" r="2.4" fill="#8fe3ff" />
        </g>

        {/* Cœur de statut — dégradé à 2 tons + reflet */}
        <g className="la-core">
          <circle cx="60" cy="60" r="12" fill="url(#laCore)" />
          <circle cx="60" cy="60" r="12" fill="none" stroke="#8fc4ff" strokeOpacity="0.45" strokeWidth="1" />
          <circle cx="56" cy="56" r="3.2" fill="#ffffff" opacity="0.55" />
        </g>
      </svg>
    </div>
  );
}
