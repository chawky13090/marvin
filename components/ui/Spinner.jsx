'use client';

/** Petit sablier rotatif (CSS pur). `size` en px, `inline` pour l'aligner dans du texte. */
export function Spinner({ size = 14, style }) {
  return <span className="spinner-ring" style={{ width: size, height: size, ...style }} />;
}

/**
 * Ligne "Chargement…" standard avec sablier — remplace les textes "Chargement..."
 * bruts pour que l'utilisateur voie tout de suite que Marvin travaille.
 */
export function LoadingRow({ label = 'Chargement…', size = 14 }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 4px', color: 'var(--text-muted)', fontSize: 12.5 }}>
      <Spinner size={size} />
      <span>{label}</span>
    </div>
  );
}

export default Spinner;
