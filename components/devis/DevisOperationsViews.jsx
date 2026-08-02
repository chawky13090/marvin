'use client';
import { useCallback, useEffect, useState } from 'react';
import { LoadingRow } from '@/components/ui/Spinner';
import { btn, card, input, tool } from './devisShared';

function StatBox({ label, value, color }) {
  return (
    <div style={{ ...card, textAlign: 'center', padding: '14px 12px' }}>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 800, color: color || 'var(--text-primary)', marginTop: 6, fontFamily: 'monospace' }}>{value}</div>
    </div>
  );
}
const PRICING_BADGE = {
  opensource: { t: 'Open source', c: '#22c55e' }, free: { t: 'Gratuit', c: '#22c55e' },
  freemium: { t: 'Freemium', c: '#3b82f6' }, paid: { t: 'Payant', c: '#4f8cff' },
  saas: { t: 'SaaS', c: '#a855f7' }, unknown: { t: '—', c: '#888' },
};
export function KbView({ showToast }) {
  const [tools_, setTools] = useState([]);
  const [cats, setCats] = useState([]);
  const [cat, setCat] = useState(null);
  const [q, setQ] = useState('');
  const [need, setNeed] = useState('');
  const [reco, setReco] = useState(null);
  const [recoBusy, setRecoBusy] = useState(false);

  const load = useCallback(async () => {
    const r = await tool('it_kb_list', cat ? { category: cat } : {});
    setTools(r.tools || []); setCats(r.categories || []);
  }, [cat]);
  useEffect(() => { load(); }, [load]);

  const search = async () => {
    const r = await tool('it_kb_search', { query: q.trim() });
    setTools(r.tools || []);
  };
  const recommend = async () => {
    if (!need.trim()) return;
    setRecoBusy(true); setReco(null);
    try { const r = await tool('it_kb_recommend', { need: need.trim() }); setReco(r); }
    finally { setRecoBusy(false); }
  };

  const shown = q.trim() ? tools_ : (cat ? tools_ : tools_);

  return (
    <div style={{ maxWidth: 920 }}>
      <h1 style={{ fontSize: '22px', fontWeight: 800, color: 'var(--text-primary)', margin: '0 0 6px' }}>🧠 Base de connaissances IT de Marvin</h1>
      <p style={{ color: 'var(--text-muted)', fontSize: 13, margin: '0 0 18px' }}>
        Catalogue d'outils & logiciels IT, consultable instantanément (sans recherche web). Utilisé par le chat, l'Agent Documentation Technique et les devis.
      </p>

      {/* Recommandation par besoin */}
      <div style={{ ...card, marginBottom: 18, borderColor: 'rgba(168,85,247,0.3)' }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: '#a855f7', marginBottom: 8 }}>🎯 Recommandation par besoin</div>
        <div style={{ display: 'flex', gap: 8 }}>
          <input value={need} onChange={e => setNeed(e.target.value)} onKeyDown={e => e.key === 'Enter' && recommend()}
            placeholder="ex: sauvegarde pour une mairie budget limité · pare-feu souverain · supervision réseau gratuite" style={input} />
          <button onClick={recommend} disabled={recoBusy || !need.trim()} style={{ ...btn('primary'), opacity: (recoBusy || !need.trim()) ? 0.5 : 1, whiteSpace: 'nowrap' }}>
            {recoBusy ? '…' : 'Recommander'}
          </button>
        </div>
        {reco && reco.recommendations && (
          <div style={{ marginTop: 12 }}>
            {reco.recommendations.map((r, i) => (
              <div key={i} style={{ padding: '8px 10px', marginBottom: 6, borderRadius: 8,
                background: i === 0 ? 'rgba(34,197,94,0.08)' : 'transparent', border: '1px solid var(--border)' }}>
                <span style={{ fontWeight: 700, color: i === 0 ? '#22c55e' : 'var(--text-primary)', fontSize: 13 }}>
                  {i === 0 ? '⭐ ' : ''}{r.name}</span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 8 }}>{r.category} · {r.vendor}</span>
                <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 2 }}>{r.why} {r.typical_price ? `· ${r.typical_price}` : ''}</div>
              </div>
            ))}
          </div>
        )}
        {reco && !reco.recommendations && <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8 }}>{reco.message}</div>}
      </div>

      {/* Recherche + filtres catégories */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <input value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === 'Enter' && search()}
          placeholder="Rechercher un outil (antivirus, sauvegarde VM, accès distant…)" style={input} />
        <button onClick={search} style={btn()}>Chercher</button>
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 14 }}>
        <button onClick={() => { setCat(null); setQ(''); }} style={{ ...btn(), padding: '4px 10px', fontSize: 11, opacity: cat ? 0.6 : 1 }}>Tout</button>
        {cats.map(c => (
          <button key={c} onClick={() => { setCat(c); setQ(''); }} style={{ ...btn(), padding: '4px 10px', fontSize: 11, opacity: cat === c ? 1 : 0.6, fontWeight: cat === c ? 700 : 400 }}>{c}</button>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(280px,1fr))', gap: 10 }}>
        {shown.map(t => {
          const pb = PRICING_BADGE[t.pricing_model] || PRICING_BADGE.unknown;
          return (
            <div key={t.id} style={{ ...card, padding: '12px 14px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <span style={{ fontWeight: 700, fontSize: 13, color: 'var(--text-primary)' }}>{t.name}</span>
                <span style={{ fontSize: 9, padding: '2px 7px', borderRadius: 10, background: pb.c + '22', color: pb.c, fontWeight: 700, whiteSpace: 'nowrap' }}>{pb.t}</span>
              </div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', margin: '2px 0 6px' }}>{t.category} · {t.vendor}</div>
              <div style={{ fontSize: 11, color: 'var(--text-secondary)', lineHeight: 1.5 }}>{t.description}</div>
              {t.best_for && <div style={{ fontSize: 10, color: '#4f8cff', marginTop: 6 }}>👍 {t.best_for}</div>}
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, fontSize: 10, color: 'var(--text-muted)' }}>
                <span>{t.typical_price || ''}</span>
                {t.platforms && <span>{t.platforms}</span>}
              </div>
            </div>
          );
        })}
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 12 }}>{shown.length} outil(s) · Marvin peut enrichir cette base au fil des recherches.</div>
    </div>
  );
}

// ── Factures & encaissements ────────────────────────────────────────────────────
const INV_STATUS = {
  draft: { label: 'Brouillon', color: '#888' }, sent: { label: 'Envoyée', color: '#3b82f6' },
  paid: { label: 'Payée', color: '#22c55e' }, partial: { label: 'Partielle', color: '#f59e0b' },
  overdue: { label: 'En retard', color: '#ef4444' }, cancelled: { label: 'Annulée', color: '#666' },
};

export function InvoicesView({ clients, quotes, reload, showToast }) {
  const [invoices, setInvoices] = useState([]);
  const [dash, setDash] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [inv, d] = await Promise.all([
        tool('billing_invoice_list', {}),
        tool('billing_revenue_dashboard', {}),
      ]);
      setInvoices(inv.invoices || []);
      setDash(d.success ? d : null);
    } catch (e) { showToast('Erreur : ' + e.message, 'error'); }
    finally { setLoading(false); }
  }, [showToast]);
  useEffect(() => { load(); }, [load]);

  const acceptedQuotes = quotes.filter(q => q.status === 'accepted');

  const createFromQuote = async (qid) => {
    const r = await tool('billing_invoice_create', { from_quote_id: qid });
    if (r.success) { showToast(r.message, 'success'); load(); } else showToast(r.error || 'Erreur', 'error');
  };
  const markPaid = async (iid) => {
    const r = await tool('billing_invoice_mark_paid', { invoice_id: iid });
    if (r.success) { showToast(r.message, 'success'); load(); } else showToast(r.error || 'Erreur', 'error');
  };

  return (
    <div style={{ maxWidth: 900 }}>
      <h1 style={{ fontSize: '22px', fontWeight: 800, color: 'var(--text-primary)', margin: '0 0 16px' }}>🧾 Factures & pilotage commercial</h1>

      {dash && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 12, marginBottom: 20 }}>
          <StatBox label="CA facturé" value={`${dash.revenue.invoiced_ttc.toFixed(0)} €`} color="#4f8cff" />
          <StatBox label="Encaissé" value={`${dash.revenue.collected_ttc.toFixed(0)} €`} color="#22c55e" />
          <StatBox label="Impayés" value={`${dash.revenue.unpaid_ttc.toFixed(0)} €`} color={dash.revenue.unpaid_ttc > 0 ? '#f59e0b' : '#22c55e'} />
          <StatBox label="MRR (récurrent)" value={`${dash.recurring.mrr_ht.toFixed(0)} €`} color="#a855f7" />
          <StatBox label="Taux conversion" value={`${dash.pipeline.win_rate_pct}%`} color="#3b82f6" />
        </div>
      )}

      {acceptedQuotes.length > 0 && (
        <div style={{ ...card, marginBottom: 16 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 8 }}>Devis acceptés à facturer</div>
          {acceptedQuotes.map(q => (
            <div key={q.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0' }}>
              <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{q.number} · {q.client_name} · {q.total_ttc?.toFixed(0)}€</span>
              <button onClick={() => createFromQuote(q.id)} style={{ ...btn('primary'), fontSize: 11, padding: '4px 10px' }}>→ Facturer</button>
            </div>
          ))}
        </div>
      )}

      <div style={{ ...card }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 12 }}>Factures ({invoices.length})</div>
        {loading ? <LoadingRow />
          : invoices.length === 0 ? <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>Aucune facture. Facturez un devis accepté ci-dessus.</div>
          : invoices.map(i => {
            const st = INV_STATUS[i.is_overdue ? 'overdue' : i.status] || INV_STATUS.draft;
            return (
              <div key={i.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderBottom: '1px solid var(--border)' }}>
                <div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>{i.number} · {i.client_name}</div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>Émise {i.issue_date} · échéance {i.due_date || '—'}</div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ fontSize: 13, fontWeight: 700, fontFamily: 'monospace', color: 'var(--text-primary)' }}>{i.total_ttc?.toFixed(2)} €</span>
                  <span style={{ fontSize: 9, padding: '2px 8px', borderRadius: 10, background: st.color + '22', color: st.color, fontWeight: 700 }}>{st.label}</span>
                  {i.status !== 'paid' && i.status !== 'cancelled' && (
                    <button onClick={() => markPaid(i.id)} style={{ ...btn(), fontSize: 10, padding: '3px 8px' }}>✓ Encaisser</button>
                  )}
                </div>
              </div>
            );
          })}
      </div>
    </div>
  );
}
