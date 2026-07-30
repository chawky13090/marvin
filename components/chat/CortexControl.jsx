'use client';
import { useEffect, useMemo, useState } from 'react';
import { BACKEND_URL } from '@/lib/backend';
import { CORTEX_AXES, DEFAULT_CORTEX_CONTRACT, cortexSummary } from '@/lib/cortex';

export default function CortexControl({
  contract,
  onChange,
  disabled = false,
  compact = false,
}) {
  const [open, setOpen] = useState(false);
  const [recipes, setRecipes] = useState([]);
  const [saving, setSaving] = useState(false);
  const [recipeName, setRecipeName] = useState('');
  const explicitCount = useMemo(() => CORTEX_AXES.filter(a => (contract?.[a.key] || 'auto') !== 'auto').length, [contract]);

  useEffect(() => {
    if (!open) return;
    fetch(`${BACKEND_URL}/api/cortex/recipes`).then(r => r.json()).then(d => setRecipes(d.recipes || [])).catch(() => {});
  }, [open]);

  const update = (key, value) => onChange({ ...DEFAULT_CORTEX_CONTRACT, ...contract, [key]: value });
  const saveRecipe = async () => {
    if (!recipeName.trim()) return;
    setSaving(true);
    try {
      const r = await fetch(`${BACKEND_URL}/api/cortex/recipes`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: recipeName.trim(), contract }),
      }).then(x => x.json());
      if (r.recipe) { setRecipes(prev => [...prev, r.recipe]); setRecipeName(''); }
    } finally { setSaving(false); }
  };

  return (
    <div style={{
      position: 'relative',
      marginBottom: compact ? 0 : 8,
      display: 'flex',
      alignItems: 'center',
      gap: compact ? 3 : 7,
      flexWrap: compact ? 'nowrap' : 'wrap',
      flexShrink: 0,
    }}>
      <button
        type="button"
        className={compact ? 'cortex-control-trigger cortex-control-trigger--compact' : 'cortex-control-trigger'}
        disabled={disabled}
        onClick={() => setOpen(v => !v)}
        title="Configurer le contrat de mission Cortex"
        style={{ display: 'flex', alignItems: 'center', gap: compact ? 5 : 7, maxWidth: compact ? 170 : '100%',
          minHeight: compact ? 34 : undefined, padding: compact ? '5px 8px' : '6px 11px', borderRadius: 999,
          border: `1px solid ${explicitCount ? 'rgba(56,189,248,.48)' : 'var(--border)'}`,
          background: explicitCount ? 'rgba(255,255,255,.07)' : 'var(--bg-glass)',
          color: explicitCount ? '#7dd3fc' : 'var(--text-secondary)', cursor: disabled ? 'not-allowed' : 'pointer',
          fontSize: compact ? 11 : 12, fontWeight: 650, overflow: 'hidden' }}>
        <span aria-hidden>✦</span>
        <span className="cortex-control-label" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          Cortex · {cortexSummary(contract)}
        </span>
        <span className="cortex-control-chevron" style={{ fontSize: 9 }}>▼</span>
      </button>
      {explicitCount > 0 && !compact && (
        <button type="button" onClick={() => onChange({ ...DEFAULT_CORTEX_CONTRACT })}
          style={{ position: 'relative', zIndex: open ? 112 : 'auto', border: 'none', background: 'transparent', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 11 }}>Réinitialiser</button>
      )}
      {contract?.pinned && !compact && <span style={{ color: '#fbbf24', fontSize: 11 }}>📌 conversation</span>}

      {open && (
        <>
          <div onClick={() => setOpen(false)} style={{ position: 'fixed', inset: 0, zIndex: 110 }} />
          <div className="cortex-control-popover" style={{ position: 'absolute', bottom: 'calc(100% + 8px)', left: 0, zIndex: 111, width: 'min(680px, calc(100vw - 48px))',
            maxHeight: 'min(620px, 72vh)', overflowY: 'auto', padding: 14, borderRadius: 16,
            background: 'var(--bg-secondary)', border: '1px solid var(--border-hover)', boxShadow: 'var(--shadow-lg)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, marginBottom: 12 }}>
              <div><div style={{ fontWeight: 750, color: 'var(--text-primary)' }}>✦ Contrat de mission Cortex</div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 3 }}>Marvin choisit automatiquement. Ne modifie que ce que tu veux imposer.</div></div>
              <button type="button" onClick={() => update('pinned', !contract?.pinned)}
                style={{ borderRadius: 9, padding: '5px 9px', border: '1px solid var(--border)', background: contract?.pinned ? 'rgba(251,191,36,.13)' : 'var(--bg-glass)', color: contract?.pinned ? '#fbbf24' : 'var(--text-muted)', cursor: 'pointer', fontSize: 11 }}>
                {contract?.pinned ? '📌 Épinglé' : 'Épingler'}
              </button>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(195px,1fr))', gap: 10 }}>
              {CORTEX_AXES.map(axis => (
                <label key={axis.key} style={{ display: 'flex', flexDirection: 'column', gap: 5, fontSize: 11, color: 'var(--text-muted)' }}>
                  <span style={{ fontWeight: 700 }}>{axis.label}</span>
                  <select value={contract?.[axis.key] || 'auto'} onChange={e => update(axis.key, e.target.value)}
                    style={{ width: '100%', borderRadius: 9, padding: '8px 9px', border: '1px solid var(--border)', background: 'var(--bg-primary)', color: 'var(--text-primary)', fontSize: 12 }}>
                    {axis.options.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </label>
              ))}
            </div>
            <div style={{ marginTop: 13, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 7 }}>Recettes de mission</div>
              {recipes.length > 0 && <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
                {recipes.map(recipe => <button type="button" key={recipe.id} onClick={() => onChange({ ...DEFAULT_CORTEX_CONTRACT, ...recipe.contract, recipe_id: recipe.id })}
                  style={{ borderRadius: 999, padding: '5px 9px', border: '1px solid var(--border)', background: 'var(--bg-glass)', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: 11 }}>{recipe.name}</button>)}
              </div>}
              <div style={{ display: 'flex', gap: 6 }}>
                <input value={recipeName} onChange={e => setRecipeName(e.target.value)} placeholder="Nom de la nouvelle recette"
                  style={{ flex: 1, minWidth: 120, borderRadius: 8, padding: '7px 9px', border: '1px solid var(--border)', background: 'var(--bg-primary)', color: 'var(--text-primary)', fontSize: 11 }} />
                <button type="button" disabled={saving || !recipeName.trim()} onClick={saveRecipe}
                  style={{ borderRadius: 8, padding: '7px 10px', border: '1px solid rgba(45,212,191,.35)', background: 'rgba(45,212,191,.1)', color: '#2dd4bf', cursor: 'pointer', fontSize: 11 }}>Enregistrer</button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
