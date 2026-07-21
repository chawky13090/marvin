'use client';

import { useId } from 'react';

/**
 * LivingAvatar — boucle de Möbius fonctionnelle : le flux lumineux circule
 * doucement au repos et accélère quand Marvin travaille. Le croisement central
 * possède un vrai plan avant/arrière pour donner l'illusion d'un ruban continu.
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
  const uid = useId().replace(/:/g, '');
  const ribbon = `${uid}-ribbon`;
  const glow = `${uid}-glow`;
  return (
    <div className="la-root" style={{ width: size, height: size, position: 'relative', display: 'inline-block' }}>
      <style>{`
        .la-root { perspective: 310px; transform-style:preserve-3d; }
        .la-root .la-mobius  { transform-box:fill-box; transform-origin:center; transform-style:preserve-3d; animation: laMobius3D ${thinking ? '2.4s' : '7.5s'} linear infinite; }
        .la-root .la-flow    { animation: laFlow ${thinking ? '1.5s' : '5.5s'} linear infinite; }
        .la-root .la-orbit   { transform-origin: 60px 60px; animation: laSpin ${thinking ? '3s' : '10s'} linear infinite; opacity:${thinking ? 0.9 : 0.45}; }
        .la-root .la-eye     { transform-origin:center; animation:laBlink 7s ease-in-out infinite; }
        .la-root .la-halo    { transform-origin: 60px 60px; animation: laHalo var(--beat,2.6s) ease-in-out infinite; }
        @keyframes laSpin { to { transform: rotate(360deg); } }
        @keyframes laMobius3D {
          0%   { transform:perspective(310px) rotateX(-9deg) rotateY(0deg) scale(1); filter:brightness(1); }
          25%  { transform:perspective(310px) rotateX(7deg) rotateY(90deg) scale(1.035); filter:brightness(1.18); }
          50%  { transform:perspective(310px) rotateX(-9deg) rotateY(180deg) scale(1); filter:brightness(.88); }
          75%  { transform:perspective(310px) rotateX(7deg) rotateY(270deg) scale(1.035); filter:brightness(1.18); }
          100% { transform:perspective(310px) rotateX(-9deg) rotateY(360deg) scale(1); filter:brightness(1); }
        }
        @keyframes laFlow { to { stroke-dashoffset: -96; } }
        @keyframes laHalo { 0%,100% { opacity:.2; transform:scale(.94) } 50%{ opacity:.52; transform:scale(1.06) } }
        @keyframes laBlink { 0%,45%,49%,100% { transform:scaleY(1) } 47% { transform:scaleY(.12) } }
        @media (prefers-reduced-motion: reduce){
          .la-root .la-mobius,.la-root .la-flow,.la-root .la-orbit,.la-root .la-halo,.la-root .la-eye{animation:none!important;transform:none!important}
        }
      `}</style>
      <svg viewBox="0 0 120 120" width={size} height={size} style={{ '--beat': beat + 's' }} xmlns="http://www.w3.org/2000/svg">
        <defs>
          <linearGradient id={ribbon} x1="18" y1="34" x2="102" y2="86" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#2357d8" />
            <stop offset=".28" stopColor="#4f8cff" />
            <stop offset=".53" stopColor="#b8e8ff" />
            <stop offset=".72" stopColor="#35c8f5" />
            <stop offset="1" stopColor="#3563e9" />
          </linearGradient>
          <radialGradient id={glow} cx="50%" cy="50%" r="50%">
            <stop offset="0" stopColor="#4f8cff" stopOpacity=".48" />
            <stop offset="1" stopColor="#38bdf8" stopOpacity="0" />
          </radialGradient>
          <filter id={`${uid}-soft`} x="-35%" y="-45%" width="170%" height="190%">
            <feGaussianBlur stdDeviation="4" />
          </filter>
        </defs>

        <ellipse className="la-halo" cx="60" cy="60" rx="48" ry="35" fill={`url(#${glow})`} filter={`url(#${uid}-soft)`} />
        {/* Châssis du robot : discret pour laisser le ruban de Möbius dominer. */}
        <path d="M33 35 Q60 22 87 35 Q96 42 96 61 Q96 82 85 91 Q60 101 35 91 Q24 82 24 61 Q24 42 33 35Z"
              fill="#0c111d" stroke="#90c8ff" strokeOpacity=".22" strokeWidth="1.4" />
        <path d="M60 29 V19" stroke="#6aa9ff" strokeWidth="2.5" strokeLinecap="round" />
        <circle cx="60" cy="16" r="3.5" fill="#8fe3ff" stroke="#3563e9" strokeWidth="1.5" />
        <rect x="18" y="52" width="7" height="20" rx="3.5" fill="#17233a" stroke="#4f8cff" strokeOpacity=".5" />
        <rect x="95" y="52" width="7" height="20" rx="3.5" fill="#17233a" stroke="#4f8cff" strokeOpacity=".5" />
        <g className="la-mobius">
          {/* Ombre du ruban complet. */}
          <path d="M20 60 C31 31 45 31 60 60 C75 89 89 89 100 60 C89 31 75 31 60 60 C45 89 31 89 20 60"
                fill="none" stroke="#07101f" strokeWidth="19" strokeLinecap="round" strokeLinejoin="round" opacity=".92" />
          {/* Ruban principal : un huit continu, base géométrique de la boucle de Möbius. */}
          <path d="M20 60 C31 31 45 31 60 60 C75 89 89 89 100 60 C89 31 75 31 60 60 C45 89 31 89 20 60"
                fill="none" stroke={`url(#${ribbon})`} strokeWidth="13" strokeLinecap="round" strokeLinejoin="round" />
          {/* Flux d'activité borné au ruban. */}
          <path className="la-flow" d="M20 60 C31 31 45 31 60 60 C75 89 89 89 100 60 C89 31 75 31 60 60 C45 89 31 89 20 60"
                fill="none" stroke="#e6f7ff" strokeWidth="2.2" strokeLinecap="round" strokeDasharray="16 80" opacity={thinking ? '.92' : '.58'} />
          {/* Surépaisseur au croisement : le brin montant passe réellement au premier plan. */}
          <path d="M51 43 C54 48 57 54 60 60 C63 66 66 72 70 77"
                fill="none" stroke="#07101f" strokeWidth="19" strokeLinecap="round" />
          <path d="M51 43 C54 48 57 54 60 60 C63 66 66 72 70 77"
                fill="none" stroke={`url(#${ribbon})`} strokeWidth="13" strokeLinecap="round" />
          <path d="M52 42 C56 49 58 55 61 60" fill="none" stroke="#ffffff" strokeWidth="2" strokeLinecap="round" opacity=".58" />
        </g>
        {/* Regard asymétrique : précis à gauche, complice à droite. */}
        <g className="la-eye">
          <ellipse cx="41" cy="59" rx="7" ry="5" fill="#07101f" stroke="#8fe3ff" strokeWidth="1.2" />
          <circle cx="43" cy="58" r="2.2" fill="#d9f5ff" />
          <path d="M73 60 Q79 54 86 58 Q80 64 73 60Z" fill="#07101f" stroke="#8fe3ff" strokeWidth="1.2" />
          <circle cx="80" cy="58.5" r="1.8" fill="#d9f5ff" />
        </g>
        <path d="M72 50 Q80 46 87 50" fill="none" stroke="#8fe3ff" strokeWidth="1.8" strokeLinecap="round" opacity=".72" />
        <path d="M51 83 Q60 87 70 81" fill="none" stroke="#4f8cff" strokeWidth="1.8" strokeLinecap="round" opacity=".65" />
        <g className="la-orbit"><circle cx="60" cy="12" r="2" fill="#a9e8ff" /><circle cx="60" cy="12" r="5" fill="none" stroke="#4f8cff" opacity=".25" /></g>
      </svg>
    </div>
  );
}
