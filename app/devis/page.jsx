'use client';
import { useState, useEffect, useCallback, useMemo } from 'react';
import { LoadingRow } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';

import { InvoicesView, KbView } from '@/components/devis/DevisOperationsViews';
import { api, btn, card, input, tool } from '@/components/devis/devisShared';

// ── Styles ────────────────────────────────────────────────────────────────────
const CLIENT_TYPES = [
  { value: 'mairie', label: '🏛️ Mairie / Collectivité' },
  { value: 'pme', label: '🏢 PME' },
  { value: 'asso', label: '🤝 Association' },
  { value: 'particulier', label: '👤 Particulier' },
  { value: 'autre', label: '📋 Autre' },
];

const TIER_INFO = {
  basic:    { label: 'Basic',    color: '#22c55e', desc: 'Formule essentielle' },
  standard: { label: 'Standard', color: '#4f8cff', desc: 'Recommandée' },
  premium:  { label: 'Premium',  color: '#a855f7', desc: 'Complète' },
  custom:   { label: 'Sur mesure', color: '#3b82f6', desc: 'Personnalisée' },
};

const STATUS_INFO = {
  draft:    { label: 'Brouillon', color: '#888' },
  sent:     { label: 'Envoyé',    color: '#3b82f6' },
  accepted: { label: 'Accepté',   color: '#22c55e' },
  refused:  { label: 'Refusé',    color: '#ef4444' },
  expired:  { label: 'Expiré',    color: '#f59e0b' },
};

// ── API helpers ───────────────────────────────────────────────────────────────
export default function DevisPage() {
  const [view, setView] = useState('list');    // list | client | analyze | quote
  const [clients, setClients] = useState([]);
  const [quotes, setQuotes] = useState([]);
  const [catalog, setCatalog] = useState([]);
  const [selectedClient, setSelectedClient] = useState(null);
  const [selectedQuote, setSelectedQuote] = useState(null);
  const [loading, setLoading] = useState(true);
  const { toast: realToast } = useToast();

  const showToast = (msg, type = 'info') => {
    (realToast[type] || realToast.info)(msg);
  };

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [c, q, cat] = await Promise.all([
        api('/api/billing/clients'),
        api('/api/billing/quotes'),
        api('/api/billing/catalog'),
      ]);
      setClients(c.clients || []);
      setQuotes(q.quotes || []);
      setCatalog(cat.services || []);
    } catch (e) {
      showToast('Erreur chargement : ' + e.message, 'error');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden', background: 'var(--bg-primary)' }}>
      {/* Sidebar */}
      <div style={{
        width: '280px', flexShrink: 0,
        borderRight: '1px solid var(--border)',
        background: 'var(--bg-secondary)',
        overflowY: 'auto',
        padding: '16px 12px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '20px', padding: '0 6px' }}>
          <span style={{ fontSize: '22px' }}>📋</span>
          <div>
            <div style={{ fontWeight: 800, color: 'var(--text-primary)', fontSize: '14px' }}>Devis IT</div>
            <div style={{ fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '0.05em' }}>FACTURATION</div>
          </div>
        </div>

        <button onClick={() => { setSelectedClient(null); setSelectedQuote(null); setView('client'); }}
          style={{ ...btn('primary'), width: '100%', marginBottom: '8px' }}>
          ➕ Nouveau client
        </button>
        <button onClick={() => { setSelectedQuote(null); setView('analyze'); }}
          style={{ ...btn(), width: '100%', marginBottom: '8px' }}>
          🔍 Analyser un besoin
        </button>
        <button onClick={() => { setView('compare'); }}
          style={{ ...btn(), width: '100%', marginBottom: '8px' }}>
          🔎 Comparateur prix web
        </button>
        <button onClick={() => { setView('invoices'); }}
          style={{ ...btn(), width: '100%', marginBottom: '8px' }}>
          🧾 Factures & encaissements
        </button>
        <button onClick={() => { setView('kb'); }}
          style={{ ...btn(), width: '100%', marginBottom: '16px' }}>
          🧠 Base d'outils IT
        </button>

        <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: 700, letterSpacing: '0.08em', marginBottom: '8px', padding: '0 6px' }}>
          CLIENTS ({clients.length})
        </div>
        {clients.map(c => (
          <div key={c.id}
            onClick={() => { setSelectedClient(c); setSelectedQuote(null); setView('client'); }}
            style={{
              padding: '8px 10px', marginBottom: '4px',
              borderRadius: '6px', cursor: 'pointer',
              background: selectedClient?.id === c.id ? 'rgba(79, 140, 255,0.12)' : 'transparent',
              border: '1px solid ' + (selectedClient?.id === c.id ? 'rgba(79, 140, 255,0.3)' : 'transparent'),
              transition: 'all 0.15s',
            }}>
            <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {CLIENT_TYPES.find(t => t.value === c.client_type)?.label.split(' ')[0]} {c.name}
            </div>
            <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '2px' }}>
              {c.contact_name || c.contact_email || '—'}
            </div>
          </div>
        ))}

        <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: 700, letterSpacing: '0.08em', margin: '16px 6px 8px' }}>
          DEVIS RÉCENTS ({quotes.length})
        </div>
        {quotes.slice(0, 15).map(q => (
          <div key={q.id}
            onClick={() => { setSelectedQuote(q); setView('quote'); }}
            style={{
              padding: '8px 10px', marginBottom: '4px',
              borderRadius: '6px', cursor: 'pointer',
              background: selectedQuote?.id === q.id ? 'rgba(79, 140, 255,0.12)' : 'transparent',
              border: '1px solid ' + (selectedQuote?.id === q.id ? 'rgba(79, 140, 255,0.3)' : 'transparent'),
            }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-primary)' }}>{q.number}</span>
              <span style={{ fontSize: '9px', padding: '1px 6px', borderRadius: '10px',
                  background: STATUS_INFO[q.status]?.color + '22',
                  color: STATUS_INFO[q.status]?.color, fontWeight: 700 }}>
                {STATUS_INFO[q.status]?.label}
              </span>
            </div>
            <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '2px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {q.client_name} · {q.total_ttc?.toFixed(0)}€ TTC
            </div>
          </div>
        ))}
      </div>

      {/* Main */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '24px 32px', position: 'relative' }}>
        {loading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: '60px' }}><LoadingRow /></div>
        ) : view === 'list' ? (
          <DashboardView clients={clients} quotes={quotes} setView={setView}
            setSelectedClient={setSelectedClient} setSelectedQuote={setSelectedQuote} />
        ) : view === 'client' ? (
          <ClientView client={selectedClient} setClient={setSelectedClient} catalog={catalog}
            quotes={quotes.filter(q => q.client_id === selectedClient?.id)}
            reload={reload} setView={setView} showToast={showToast}
            setSelectedQuote={setSelectedQuote} />
        ) : view === 'analyze' ? (
          <AnalyzeView catalog={catalog} clients={clients} setView={setView}
            setSelectedClient={setSelectedClient} reload={reload} showToast={showToast} />
        ) : view === 'quote' ? (
          <QuoteView quote={selectedQuote} client={clients.find(c => c.id === selectedQuote?.client_id)}
            catalog={catalog} reload={reload} showToast={showToast} setView={setView} />
        ) : view === 'compare' ? (
          <CompareView showToast={showToast} />
        ) : view === 'invoices' ? (
          <InvoicesView clients={clients} quotes={quotes} reload={reload} showToast={showToast} />
        ) : view === 'kb' ? (
          <KbView showToast={showToast} />
        ) : null}
      </div>
    </div>
  );
}

// ── Dashboard ─────────────────────────────────────────────────────────────────
function DashboardView({ clients, quotes, setView, setSelectedClient, setSelectedQuote }) {
  const stats = useMemo(() => ({
    total: quotes.reduce((s, q) => s + (q.total_ttc || 0), 0),
    margin: quotes.reduce((s, q) => s + (q.margin || 0), 0),
    accepted: quotes.filter(q => q.status === 'accepted').length,
    pending: quotes.filter(q => ['draft', 'sent'].includes(q.status)).length,
  }), [quotes]);

  return (
    <div>
      <h1 style={{ fontSize: '1.6rem', fontWeight: 800, marginBottom: '6px' }}>📋 Assistant Devis & Facturation IT</h1>
      <p style={{ color: 'var(--text-secondary)', fontSize: '13px', marginBottom: '24px' }}>
        Préparation commerciale assistée pour mairies, PME et associations.
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '14px', marginBottom: '24px' }}>
        <StatCard icon="👥" label="Clients" value={clients.length} />
        <StatCard icon="📄" label="Devis" value={quotes.length} />
        <StatCard icon="💰" label="CA potentiel" value={`${stats.total.toFixed(0)}€`} />
        <StatCard icon="📈" label="Marge totale" value={`${stats.margin.toFixed(0)}€`} />
        <StatCard icon="✅" label="Acceptés" value={stats.accepted} />
        <StatCard icon="⏳" label="En attente" value={stats.pending} />
      </div>

      <div style={card}>
        <h3 style={{ fontSize: '14px', fontWeight: 700, marginBottom: '14px', color: 'var(--text-primary)' }}>🚀 Démarrage rapide</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '12px' }}>
          <QuickAction icon="➕" title="Nouveau client" desc="Ajouter un client (mairie/PME/asso) à votre base"
            onClick={() => { setSelectedClient(null); setView('client'); }} />
          <QuickAction icon="🔍" title="Analyser un besoin" desc="L'IA analyse le besoin et suggère prestations + tarifs"
            onClick={() => setView('analyze')} />
          <QuickAction icon="📊" title="Comparer Basic/Std/Premium" desc="Présenter 3 niveaux d'offre au client"
            onClick={() => setView('analyze')} />
        </div>
      </div>

      <TradeLoader />
    </div>
  );
}

const TRADES = [
  { v: 'plomberie', l: '🔧 Plomberie' }, { v: 'électricité', l: '⚡ Électricité' },
  { v: 'peinture', l: '🎨 Peinture' }, { v: 'menuiserie', l: '🪚 Menuiserie' },
  { v: 'jardinage', l: '🌿 Jardinage' }, { v: 'ménage', l: '🧹 Ménage' },
  { v: 'coiffure_esthétique', l: '💇 Coiffure/Esthétique' }, { v: 'photographie', l: '📷 Photographie' },
  { v: 'web_design', l: '💻 Web/Design' }, { v: 'conseil', l: '💡 Conseil/Coaching' },
  { v: 'comptabilité', l: '🧮 Comptabilité' },
];
function TradeLoader() {
  const [busy, setBusy] = useState(null);
  const { toast } = useToast();
  const load = async (trade) => {
    setBusy(trade);
    try {
      const r = await tool('billing_seed_trade', { trade });
      if (r.error) toast.error(r.error);
      else toast.success(r.message || 'Catalogue chargé');
    } catch (e) { toast.error('Erreur : ' + e.message); }
    finally { setBusy(null); }
  };
  return (
    <div style={{ ...card, marginTop: 16 }}>
      <h3 style={{ fontSize: '14px', fontWeight: 700, marginBottom: '4px', color: 'var(--text-primary)' }}>🧰 Catalogue par métier</h3>
      <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: '0 0 12px' }}>
        Devis & factures pour <strong>tout métier</strong>, pas seulement l'IT. Chargez les prestations types d'un métier en un clic.
      </p>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {TRADES.map(t => (
          <button key={t.v} onClick={() => load(t.v)} disabled={!!busy}
            style={{ ...btn(), padding: '7px 12px', fontSize: 12, opacity: busy === t.v ? 0.5 : 1 }}>
            {busy === t.v ? '⏳ ' : ''}{t.l}
          </button>
        ))}
      </div>
    </div>
  );
}

function StatCard({ icon, label, value }) {
  return (
    <div style={card}>
      <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{icon} {label}</div>
      <div style={{ fontSize: '1.6rem', fontWeight: 800, color: 'var(--text-primary)', marginTop: '4px' }}>{value}</div>
    </div>
  );
}

function QuickAction({ icon, title, desc, onClick }) {
  return (
    <button onClick={onClick} style={{
      ...card, cursor: 'pointer', textAlign: 'left', border: '1px solid var(--border)',
      transition: 'all 0.15s', display: 'flex', flexDirection: 'column', gap: '6px',
    }}
      onMouseEnter={(e) => { e.currentTarget.style.borderColor = '#4f8cff'; e.currentTarget.style.transform = 'translateY(-1px)'; }}
      onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.transform = 'none'; }}>
      <div style={{ fontSize: '20px' }}>{icon}</div>
      <div style={{ fontWeight: 700, color: 'var(--text-primary)', fontSize: '13px' }}>{title}</div>
      <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>{desc}</div>
    </button>
  );
}

// ── Client form/view ──────────────────────────────────────────────────────────
function ClientView({ client, setClient, catalog, quotes, reload, setView, showToast, setSelectedQuote }) {
  const [form, setForm] = useState(client || {
    name: '', client_type: 'pme', contact_name: '', contact_email: '', contact_phone: '',
    address: '', siret: '', notes: '', previous_provider: '', previous_amount: '',
  });

  useEffect(() => { if (client) setForm(client); else setForm({
    name: '', client_type: 'pme', contact_name: '', contact_email: '', contact_phone: '',
    address: '', siret: '', notes: '', previous_provider: '', previous_amount: '',
  }); }, [client]);

  const save = async () => {
    if (!form.name?.trim()) { showToast('Nom requis', 'error'); return; }
    try {
      const body = { ...form, previous_amount: parseFloat(form.previous_amount) || 0 };
      if (client?.id) {
        const updated = await api(`/api/billing/clients/${client.id}`, {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        setClient(updated);
        showToast('Client mis à jour', 'success');
      } else {
        const created = await api('/api/billing/clients', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        setClient(created);
        showToast('Client créé', 'success');
      }
      reload();
    } catch (e) {
      showToast('Erreur : ' + e.message, 'error');
    }
  };

  const remove = async () => {
    if (!client?.id) return;
    if (!confirm(`Supprimer le client "${client.name}" et tous ses devis ?`)) return;
    try {
      await api(`/api/billing/clients/${client.id}`, { method: 'DELETE' });
      showToast('Client supprimé', 'success');
      setClient(null); setView('list'); reload();
    } catch (e) { showToast('Erreur : ' + e.message, 'error'); }
  };

  return (
    <div>
      <h2 style={{ fontSize: '1.3rem', fontWeight: 800, marginBottom: '20px' }}>
        {client?.id ? '✏️ ' + client.name : '➕ Nouveau client'}
      </h2>

      <div style={{ ...card, marginBottom: '16px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '14px', marginBottom: '14px' }}>
          <Field label="Type de client" required>
            <select value={form.client_type} onChange={e => setForm(f => ({ ...f, client_type: e.target.value }))} style={input}>
              {CLIENT_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </Field>
          <Field label="Nom / Raison sociale" required>
            <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} style={input} placeholder="ex: Mairie de Saint-Étienne" />
          </Field>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '14px', marginBottom: '14px' }}>
          <Field label="Contact (nom)">
            <input value={form.contact_name} onChange={e => setForm(f => ({ ...f, contact_name: e.target.value }))} style={input} placeholder="ex: M. Dupont" />
          </Field>
          <Field label="Email">
            <input type="email" value={form.contact_email} onChange={e => setForm(f => ({ ...f, contact_email: e.target.value }))} style={input} placeholder="contact@..." />
          </Field>
          <Field label="Téléphone">
            <input value={form.contact_phone} onChange={e => setForm(f => ({ ...f, contact_phone: e.target.value }))} style={input} placeholder="01 23 45 67 89" />
          </Field>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '14px', marginBottom: '14px' }}>
          <Field label="Adresse">
            <input value={form.address} onChange={e => setForm(f => ({ ...f, address: e.target.value }))} style={input} />
          </Field>
          <Field label="SIRET">
            <input value={form.siret} onChange={e => setForm(f => ({ ...f, siret: e.target.value }))} style={input} />
          </Field>
        </div>
        <div style={{ background: 'rgba(255,165,0,0.05)', border: '1px solid rgba(255,165,0,0.15)', padding: '12px', borderRadius: '6px', marginBottom: '14px' }}>
          <div style={{ fontSize: '11px', color: '#f59e0b', fontWeight: 700, marginBottom: '8px' }}>🔄 PRESTATAIRE ACTUEL (pour comparaison)</div>
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '10px' }}>
            <Field label="Nom du prestataire">
              <input value={form.previous_provider} onChange={e => setForm(f => ({ ...f, previous_provider: e.target.value }))} style={input} placeholder="ex: ITPrev SARL" />
            </Field>
            <Field label="Montant annuel (€)">
              <input type="number" value={form.previous_amount} onChange={e => setForm(f => ({ ...f, previous_amount: e.target.value }))} style={input} placeholder="8000" />
            </Field>
          </div>
        </div>
        <Field label="Notes">
          <textarea value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} style={{ ...input, minHeight: '60px', resize: 'vertical' }} />
        </Field>
        <div style={{ display: 'flex', gap: '10px', marginTop: '16px' }}>
          <button onClick={save} style={btn('primary')}>{client?.id ? '💾 Mettre à jour' : '➕ Créer le client'}</button>
          {client?.id && <button onClick={remove} style={btn('danger')}>🗑️ Supprimer</button>}
        </div>
      </div>

      {client?.id && (
        <div style={card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <h3 style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)' }}>📄 Devis de ce client ({quotes.length})</h3>
            <button onClick={() => { setSelectedQuote({ client_id: client.id, items: [], tier: 'standard', tva_rate: 20, status: 'draft' }); setView('quote'); }}
              style={btn('primary')}>➕ Nouveau devis</button>
          </div>
          {quotes.length === 0 ? (
            <div style={{ fontSize: '13px', color: 'var(--text-muted)', padding: '12px' }}>Aucun devis pour ce client.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {quotes.map(q => (
                <div key={q.id} onClick={() => { setSelectedQuote(q); setView('quote'); }}
                  style={{ padding: '10px 14px', background: 'rgba(255,255,255,0.03)', borderRadius: '6px', cursor: 'pointer',
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center', border: '1px solid var(--border)' }}>
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: 600 }}>{q.number} — {q.title}</div>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                      {q.items?.length || 0} prestations · marge {q.margin_pct}%
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: '14px', fontWeight: 700, color: '#4f8cff' }}>{q.total_ttc?.toFixed(2)}€ TTC</div>
                    <span style={{ fontSize: '10px', padding: '2px 8px', borderRadius: '10px',
                        background: STATUS_INFO[q.status]?.color + '22', color: STATUS_INFO[q.status]?.color }}>
                      {STATUS_INFO[q.status]?.label}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Field({ label, required, children }) {
  return (
    <div>
      <label style={{ display: 'block', fontSize: '11px', color: 'var(--text-muted)', marginBottom: '5px', fontWeight: 600 }}>
        {label} {required && <span style={{ color: '#ef4444' }}>*</span>}
      </label>
      {children}
    </div>
  );
}

// ── Analyze need (AI-assisted) ────────────────────────────────────────────────
function AnalyzeView({ catalog, clients, setView, setSelectedClient, reload, showToast }) {
  const [description, setDescription] = useState('');
  const [clientType, setClientType] = useState('pme');
  const [analyzing, setAnalyzing] = useState(false);
  const [result, setResult] = useState(null);
  const [selectedIds, setSelectedIds] = useState(new Set());

  const analyze = async () => {
    if (!description.trim()) { showToast('Décrivez le besoin', 'error'); return; }
    setAnalyzing(true);
    setResult(null);
    try {
      const r = await tool('billing_analyze_need', { description, client_type: clientType });
      if (r.error) { showToast(r.error, 'error'); return; }
      setResult(r);
      // Pre-select all suggested services
      setSelectedIds(new Set(r.suggested_services.map(s => s.id)));
    } catch (e) {
      showToast('Erreur : ' + e.message, 'error');
    } finally {
      setAnalyzing(false);
    }
  };

  const toggleService = (id) => {
    setSelectedIds(prev => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id); else n.add(id);
      return n;
    });
  };

  // Compute totals per tier from selected
  const computeTotals = (tier) => {
    if (!result) return 0;
    return result.suggested_services
      .filter(s => selectedIds.has(s.id))
      .reduce((sum, s) => sum + s[`price_${tier}`], 0);
  };

  return (
    <div>
      <h2 style={{ fontSize: '1.3rem', fontWeight: 800, marginBottom: '20px' }}>🔍 Analyse du besoin client</h2>

      <div style={{ ...card, marginBottom: '16px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 200px', gap: '14px', marginBottom: '14px' }}>
          <Field label="Décrivez le besoin du client en quelques phrases" required>
            <textarea value={description} onChange={e => setDescription(e.target.value)}
              placeholder="Ex: La mairie de Saint-X veut moderniser son IT : migrer 20 postes vers Office 365, mettre en place une sauvegarde cloud, audit sécurité, et formation des agents..."
              style={{ ...input, minHeight: '110px', resize: 'vertical' }} />
          </Field>
          <Field label="Type de client">
            <select value={clientType} onChange={e => setClientType(e.target.value)} style={input}>
              {CLIENT_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </Field>
        </div>
        <button onClick={analyze} disabled={analyzing} style={{ ...btn('primary'), opacity: analyzing ? 0.5 : 1 }}>
          {analyzing ? '⏳ Analyse en cours…' : '🚀 Analyser le besoin'}
        </button>
      </div>

      {result && (
        <>
          <div style={{ ...card, marginBottom: '16px', background: 'rgba(34,197,94,0.05)', border: '1px solid rgba(34,197,94,0.2)' }}>
            <div style={{ fontSize: '12px', color: '#4ade80', fontWeight: 700, marginBottom: '8px' }}>
              ✅ {result.suggested_count} prestations suggérées · catégories : {result.matched_categories.join(', ')}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '10px' }}>
              {['basic', 'standard', 'premium'].map(tier => (
                <div key={tier} style={{
                  padding: '10px', background: '#0d1117', borderRadius: '6px',
                  border: `1px solid ${TIER_INFO[tier].color}40`,
                }}>
                  <div style={{ fontSize: '11px', color: TIER_INFO[tier].color, fontWeight: 700 }}>{TIER_INFO[tier].label}</div>
                  <div style={{ fontSize: '18px', fontWeight: 800, color: 'var(--text-primary)', marginTop: '4px' }}>
                    {computeTotals(tier).toFixed(0)}€
                  </div>
                  <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>HT, sélection</div>
                </div>
              ))}
            </div>
          </div>

          <div style={card}>
            <h3 style={{ fontSize: '14px', fontWeight: 700, marginBottom: '12px' }}>📋 Prestations suggérées (cochez celles à inclure)</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxHeight: '450px', overflowY: 'auto' }}>
              {result.suggested_services.map(s => (
                <label key={s.id} style={{
                  display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 12px',
                  background: selectedIds.has(s.id) ? 'rgba(79, 140, 255,0.08)' : 'rgba(255,255,255,0.02)',
                  border: '1px solid ' + (selectedIds.has(s.id) ? 'rgba(79, 140, 255,0.3)' : 'var(--border)'),
                  borderRadius: '6px', cursor: 'pointer',
                }}>
                  <input type="checkbox" checked={selectedIds.has(s.id)} onChange={() => toggleService(s.id)} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: '12px', fontWeight: 600 }}>{s.name}</div>
                    <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{s.category} · {s.description.slice(0, 80)}</div>
                  </div>
                  <div style={{ display: 'flex', gap: '8px', fontSize: '11px', fontFamily: 'monospace' }}>
                    <span style={{ color: TIER_INFO.basic.color }}>{s.price_basic}€</span>
                    <span style={{ color: TIER_INFO.standard.color }}>{s.price_standard}€</span>
                    <span style={{ color: TIER_INFO.premium.color }}>{s.price_premium}€</span>
                  </div>
                </label>
              ))}
            </div>
            <div style={{ marginTop: '16px', display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
              {['basic', 'standard', 'premium'].map(tier => (
                <CreateQuoteBtn key={tier} tier={tier} result={result} selectedIds={selectedIds}
                  clients={clients} setView={setView} showToast={showToast} reload={reload} />
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function CreateQuoteBtn({ tier, result, selectedIds, clients, setView, showToast, reload }) {
  const [open, setOpen] = useState(false);
  const [clientId, setClientId] = useState(clients[0]?.id || '');

  const create = async () => {
    if (!clientId) { showToast('Choisissez un client', 'error'); return; }
    const services = result.suggested_services.filter(s => selectedIds.has(s.id));
    const items = services.map(s => {
      const price = s[`price_${tier}`];
      return {
        label: s.name,
        description: s.description,
        unit: s.unit,
        qty: 1,
        unit_price: price,
        total: price,
        cost: 0,  // user can edit later
      };
    });
    try {
      const r = await api('/api/billing/quotes', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          client_id: clientId,
          tier, items,
          title: `Proposition ${TIER_INFO[tier].label}`,
          need_analysis: result.description,
        }),
      });
      showToast(`Devis ${r.number} créé (${TIER_INFO[tier].label})`, 'success');
      setOpen(false);
      reload();
      setView('list');
    } catch (e) { showToast('Erreur : ' + e.message, 'error'); }
  };

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} style={{
        ...btn(), background: TIER_INFO[tier].color + '22',
        color: TIER_INFO[tier].color, border: `1px solid ${TIER_INFO[tier].color}40`,
      }}>
        📄 Créer devis {TIER_INFO[tier].label}
      </button>
    );
  }

  return (
    <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
      <select value={clientId} onChange={e => setClientId(e.target.value)} style={{ ...input, width: '200px' }}>
        <option value="">— Choisir client —</option>
        {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select>
      <button onClick={create} style={btn('primary')}>✓ {TIER_INFO[tier].label}</button>
      <button onClick={() => setOpen(false)} style={btn()}>×</button>
    </div>
  );
}

// ── Quote view & edit ─────────────────────────────────────────────────────────
function QuoteView({ quote, client, catalog, reload, showToast, setView }) {
  const [q, setQ] = useState(quote);
  const [showCatalog, setShowCatalog] = useState(false);
  const [emailDraft, setEmailDraft] = useState(null);
  const [comparison, setComparison] = useState(null);
  const [proposal, setProposal] = useState(null);
  const [genProp, setGenProp] = useState(false);

  useEffect(() => setQ(quote), [quote]);

  if (!q) return <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>Aucun devis sélectionné.</div>;

  const updateField = (k, v) => setQ(prev => ({ ...prev, [k]: v }));
  const updateItem = (i, key, val) => setQ(prev => {
    const items = [...(prev.items || [])];
    items[i] = { ...items[i], [key]: val };
    if (key === 'qty' || key === 'unit_price') {
      items[i].total = (parseFloat(items[i].qty) || 0) * (parseFloat(items[i].unit_price) || 0);
    }
    return { ...prev, items };
  });
  const addItem = () => setQ(prev => ({
    ...prev,
    items: [...(prev.items || []), { label: '', qty: 1, unit_price: 0, total: 0, cost: 0, unit: 'forfait' }],
  }));
  const removeItem = (i) => setQ(prev => ({ ...prev, items: prev.items.filter((_, idx) => idx !== i) }));
  const addFromCatalog = (s, tier = 'standard') => {
    const price = s[`price_${tier}`];
    setQ(prev => ({
      ...prev,
      items: [...(prev.items || []), {
        label: s.name, description: s.description, unit: s.unit,
        qty: 1, unit_price: price, total: price, cost: s.cost || 0,
      }],
    }));
  };

  const total_ht = (q.items || []).reduce((s, it) => s + (parseFloat(it.total) || 0), 0);
  const cost_total = (q.items || []).reduce((s, it) => s + (parseFloat(it.cost) || 0) * (parseFloat(it.qty) || 0), 0);
  const tva = total_ht * ((q.tva_rate || 20) / 100);
  const total_ttc = total_ht + tva;
  const margin = total_ht - cost_total;
  const margin_pct = total_ht > 0 ? (margin / total_ht * 100) : 0;

  const save = async () => {
    try {
      if (q.id) {
        await api(`/api/billing/quotes/${q.id}`, {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(q),
        });
      } else {
        const r = await api('/api/billing/quotes', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(q),
        });
        setQ(r);
      }
      showToast('Devis enregistré', 'success');
      reload();
    } catch (e) { showToast('Erreur : ' + e.message, 'error'); }
  };

  const generatePdf = async () => {
    if (!q.id) { showToast('Enregistrez le devis d\'abord', 'error'); return; }
    const r = await tool('billing_quote_pdf', { quote_id: q.id });
    if (r.error) showToast(r.error, 'error');
    else showToast('PDF généré : ' + r.path.split('\\').pop(), 'success');
  };

  const generateEmail = async () => {
    if (!q.id) { showToast('Enregistrez d\'abord', 'error'); return; }
    const r = await tool('billing_quote_email', { quote_id: q.id });
    if (r.error) showToast(r.error, 'error');
    else setEmailDraft(r);
  };

  const compare = async () => {
    if (!q.id) { showToast('Enregistrez d\'abord', 'error'); return; }
    const r = await tool('billing_quote_compare', { quote_id: q.id });
    if (r.error) showToast(r.error, 'error');
    else setComparison(r);
  };

  const generateProposal = async () => {
    if (!q.id) { showToast('Enregistrez le devis d\'abord', 'error'); return; }
    setGenProp(true);
    try {
      const r = await tool('billing_generate_proposal', { quote_id: q.id });
      if (r.error) showToast(r.error, 'error'); else setProposal(r);
    } finally { setGenProp(false); }
  };
  const copyProposal = () => {
    if (proposal?.proposal_markdown) {
      navigator.clipboard?.writeText(proposal.proposal_markdown);
      showToast('Proposition copiée', 'success');
    }
  };

  const remove = async () => {
    if (!q.id || !confirm('Supprimer ce devis ?')) return;
    try {
      await api(`/api/billing/quotes/${q.id}`, { method: 'DELETE' });
      showToast('Supprimé', 'success'); setView('list'); reload();
    } catch (e) { showToast('Erreur : ' + e.message, 'error'); }
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', flexWrap: 'wrap', gap: '10px' }}>
        <h2 style={{ fontSize: '1.3rem', fontWeight: 800 }}>
          📄 {q.number || 'Nouveau devis'} {client && <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>· {client.name}</span>}
        </h2>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <button onClick={save} style={btn('primary')}>💾 Enregistrer</button>
          {q.id && <button onClick={generateProposal} style={btn()}>{genProp ? '📑 …' : '📑 Proposition pro'}</button>}
          {q.id && <button onClick={generatePdf} style={btn()}>📕 Générer PDF</button>}
          {q.id && <button onClick={generateEmail} style={btn()}>✉️ Email d'envoi</button>}
          {q.id && client?.previous_amount > 0 && <button onClick={compare} style={btn()}>🔄 Comparer</button>}
          {q.id && <button onClick={remove} style={btn('danger')}>🗑️</button>}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: '16px', marginBottom: '16px' }}>
        <div style={card}>
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: '12px', marginBottom: '14px' }}>
            <Field label="Titre"><input value={q.title || ''} onChange={e => updateField('title', e.target.value)} style={input} /></Field>
            <Field label="Niveau">
              <select value={q.tier || 'standard'} onChange={e => updateField('tier', e.target.value)} style={input}>
                {Object.entries(TIER_INFO).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
              </select>
            </Field>
            <Field label="Statut">
              <select value={q.status || 'draft'} onChange={e => updateField('status', e.target.value)} style={input}>
                {Object.entries(STATUS_INFO).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
              </select>
            </Field>
          </div>
          <Field label="Notes / Analyse du besoin">
            <textarea value={q.need_analysis || ''} onChange={e => updateField('need_analysis', e.target.value)}
              style={{ ...input, minHeight: '60px', resize: 'vertical' }} placeholder="Description du contexte client, contraintes…" />
          </Field>
        </div>
        <div style={card}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '13px' }}>
            <Row label="Total HT" value={`${total_ht.toFixed(2)} €`} bold />
            <Row label={`TVA ${q.tva_rate || 20}%`} value={`${tva.toFixed(2)} €`} muted />
            <Row label="Total TTC" value={`${total_ttc.toFixed(2)} €`} bold big color="#4f8cff" />
            <div style={{ borderTop: '1px solid var(--border)', margin: '6px 0' }} />
            <Row label="Coût" value={`${cost_total.toFixed(2)} €`} muted />
            <Row label="Marge" value={`${margin.toFixed(2)} €`} color={margin >= 0 ? '#22c55e' : '#ef4444'} />
            <Row label="Marge %" value={`${margin_pct.toFixed(1)} %`} color={margin_pct >= 30 ? '#22c55e' : margin_pct >= 0 ? '#f59e0b' : '#ef4444'} />
          </div>
        </div>
      </div>

      <div style={card}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
          <h3 style={{ fontSize: '14px', fontWeight: 700 }}>📋 Lignes du devis</h3>
          <div style={{ display: 'flex', gap: '6px' }}>
            <button onClick={() => setShowCatalog(!showCatalog)} style={btn()}>📚 {showCatalog ? 'Masquer' : 'Ajouter du catalogue'}</button>
            <button onClick={addItem} style={btn('primary')}>➕ Ligne vide</button>
          </div>
        </div>

        {showCatalog && (
          <div style={{
            maxHeight: '240px', overflowY: 'auto', marginBottom: '14px', padding: '8px',
            background: 'rgba(255,255,255,0.02)', borderRadius: '6px', border: '1px solid var(--border)',
          }}>
            {catalog.map(s => (
              <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '4px 6px',
                  fontSize: '11px', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                <div style={{ flex: 1 }}>
                  <strong>{s.name}</strong> <span style={{ color: 'var(--text-muted)' }}>· {s.category}</span>
                </div>
                {['basic','standard','premium'].map(t => (
                  <button key={t} onClick={() => addFromCatalog(s, t)}
                    title={`Ajouter au tarif ${TIER_INFO[t].label}`}
                    style={{ ...btn(), padding: '3px 8px', fontSize: '10px',
                      color: TIER_INFO[t].color, border: `1px solid ${TIER_INFO[t].color}40` }}>
                    + {s[`price_${t}`]}€
                  </button>
                ))}
              </div>
            ))}
          </div>
        )}

        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--text-muted)', fontSize: '11px' }}>
              <th style={{ textAlign: 'left', padding: '6px' }}>Désignation</th>
              <th style={{ textAlign: 'right', padding: '6px', width: '80px' }}>Qté</th>
              <th style={{ textAlign: 'right', padding: '6px', width: '100px' }}>P.U. HT</th>
              <th style={{ textAlign: 'right', padding: '6px', width: '100px' }}>Coût/u</th>
              <th style={{ textAlign: 'right', padding: '6px', width: '100px' }}>Total HT</th>
              <th style={{ width: '30px' }}></th>
            </tr>
          </thead>
          <tbody>
            {(q.items || []).map((it, i) => (
              <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                <td style={{ padding: '4px 6px' }}>
                  <input value={it.label || ''} onChange={e => updateItem(i, 'label', e.target.value)} style={{ ...input, padding: '4px 6px', fontSize: '12px' }} placeholder="Désignation" />
                </td>
                <td style={{ padding: '4px 6px' }}>
                  <input type="number" value={it.qty || 1} onChange={e => updateItem(i, 'qty', e.target.value)} style={{ ...input, padding: '4px 6px', fontSize: '12px', textAlign: 'right' }} />
                </td>
                <td style={{ padding: '4px 6px' }}>
                  <input type="number" value={it.unit_price || 0} onChange={e => updateItem(i, 'unit_price', e.target.value)} style={{ ...input, padding: '4px 6px', fontSize: '12px', textAlign: 'right' }} />
                </td>
                <td style={{ padding: '4px 6px' }}>
                  <input type="number" value={it.cost || 0} onChange={e => updateItem(i, 'cost', e.target.value)} style={{ ...input, padding: '4px 6px', fontSize: '12px', textAlign: 'right' }} />
                </td>
                <td style={{ padding: '4px 6px', textAlign: 'right', fontWeight: 700, color: '#4f8cff' }}>
                  {(it.total || 0).toFixed(2)} €
                </td>
                <td>
                  <button onClick={() => removeItem(i)} style={{ ...btn('danger'), padding: '2px 8px' }}>×</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {(!q.items || q.items.length === 0) && (
          <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>
            Aucune ligne. Cliquez "Ajouter du catalogue" ou "Ligne vide" ci-dessus.
          </div>
        )}
      </div>

      {comparison && (
        <div style={{ ...card, marginTop: '16px', background: 'rgba(59,130,246,0.05)', border: '1px solid rgba(59,130,246,0.2)' }}>
          <h3 style={{ fontSize: '14px', fontWeight: 700, marginBottom: '10px', color: '#60a5fa' }}>🔄 Comparaison prestataire précédent</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '12px', fontSize: '12px' }}>
            <div><div style={{ color: 'var(--text-muted)' }}>Précédent ({comparison.previous_provider})</div><div style={{ fontSize: '18px', fontWeight: 700 }}>{comparison.previous_amount}€</div></div>
            <div><div style={{ color: 'var(--text-muted)' }}>Notre proposition</div><div style={{ fontSize: '18px', fontWeight: 700 }}>{comparison.new_amount}€</div></div>
            <div><div style={{ color: 'var(--text-muted)' }}>Différence</div><div style={{ fontSize: '18px', fontWeight: 700, color: comparison.difference >= 0 ? '#22c55e' : '#ef4444' }}>
              {comparison.difference >= 0 ? '+' : ''}{comparison.difference}€ ({comparison.savings_percent}%)
            </div></div>
          </div>
          <div style={{ marginTop: '10px', padding: '8px 12px', background: '#0d1117', borderRadius: '6px', fontSize: '13px', fontWeight: 600 }}>
            ⭐ {comparison.verdict}
          </div>
        </div>
      )}

      {emailDraft && (
        <div style={{ ...card, marginTop: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
            <h3 style={{ fontSize: '14px', fontWeight: 700 }}>✉️ Email d'accompagnement (généré)</h3>
            <button onClick={() => navigator.clipboard.writeText(emailDraft.body)} style={btn()}>📋 Copier le corps</button>
          </div>
          <div style={{ marginBottom: '8px', fontSize: '12px', color: 'var(--text-muted)' }}>
            <strong>À:</strong> {emailDraft.to || '(email non renseigné dans le client)'}<br />
            <strong>Sujet:</strong> {emailDraft.subject}
          </div>
          <pre style={{ background: '#0d1117', padding: '12px', borderRadius: '6px', fontSize: '12px', whiteSpace: 'pre-wrap', color: '#c9d1d9', maxHeight: '300px', overflowY: 'auto' }}>
            {emailDraft.body}
          </pre>
        </div>
      )}

      {proposal && (
        <div style={{ ...card, marginTop: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
            <h3 style={{ fontSize: '14px', fontWeight: 700 }}>📑 Proposition commerciale ({proposal.word_count} mots)</h3>
            <button onClick={copyProposal} style={btn()}>📋 Copier (Markdown)</button>
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: 8 }}>
            Structure best-practice : contexte → solution → bénéfices → investissement → garanties → appel à l'action.
          </div>
          <pre style={{ background: '#0d1117', padding: '14px', borderRadius: '6px', fontSize: '12px', whiteSpace: 'pre-wrap', color: '#c9d1d9', maxHeight: '420px', overflowY: 'auto', lineHeight: 1.6 }}>
            {proposal.proposal_markdown}
          </pre>
        </div>
      )}
    </div>
  );
}

function Row({ label, value, bold, big, muted, color }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
      <span style={{ color: 'var(--text-muted)', fontSize: muted ? '11px' : '12px' }}>{label}</span>
      <span style={{
        fontWeight: bold ? 800 : 400,
        fontSize: big ? '20px' : '13px',
        color: color || 'var(--text-primary)',
        fontFamily: 'monospace',
      }}>{value}</span>
    </div>
  );
}

// ── Comparateur de prix web ─────────────────────────────────────────────────────
function CompareView({ showToast }) {
  const [mode, setMode] = useState('compare');   // compare | budget
  const [query, setQuery] = useState('');
  const [margin, setMargin] = useState(30);
  const [loading, setLoading] = useState(false);
  const [res, setRes] = useState(null);
  // budget mode
  const [bQuery, setBQuery] = useState('');
  const [bMax, setBMax] = useState('');
  const [bMin, setBMin] = useState('');
  const [bLoading, setBLoading] = useState(false);
  const [bRes, setBRes] = useState(null);

  const run = async () => {
    if (!query.trim()) return;
    setLoading(true); setRes(null);
    try {
      const r = await tool('billing_market_research', { query: query.trim(), target_margin_pct: Number(margin) });
      if (r.error) showToast(r.error, 'error');
      setRes(r);
    } catch (e) { showToast('Erreur : ' + e.message, 'error'); }
    finally { setLoading(false); }
  };

  const runBudget = async () => {
    if (!bQuery.trim()) return;
    setBLoading(true); setBRes(null);
    try {
      const args = { query: bQuery.trim() };
      if (bMax) args.max_budget = Number(bMax);
      if (bMin) args.min_budget = Number(bMin);
      const r = await tool('billing_find_products', args);
      if (r.error) showToast(r.error, 'error');
      setBRes(r);
    } catch (e) { showToast('Erreur : ' + e.message, 'error'); }
    finally { setBLoading(false); }
  };

  const tab = (id, label) => (
    <button onClick={() => setMode(id)} style={{
      ...btn(mode === id ? 'primary' : 'default'), padding: '8px 16px',
    }}>{label}</button>
  );

  return (
    <div style={{ maxWidth: 880 }}>
      <h1 style={{ fontSize: '22px', fontWeight: 800, color: 'var(--text-primary)', margin: '0 0 6px' }}>🔎 Comparateur de prix web</h1>
      <p style={{ color: 'var(--text-muted)', fontSize: '13px', margin: '0 0 16px' }}>
        Compare les prix d'un produit précis, ou trouve du matériel selon un budget — en direct sur le web.
      </p>

      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {tab('compare', '⚖️ Comparer un produit')}
        {tab('budget', '🛒 Trouver selon un budget')}
      </div>

      {mode === 'budget' && (
        <div style={{ ...card, marginBottom: 20 }}>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <div style={{ flex: 3, minWidth: 240 }}>
              <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Type de matériel / besoin</label>
              <input value={bQuery} onChange={e => setBQuery(e.target.value)} onKeyDown={e => e.key === 'Enter' && runBudget()}
                placeholder="ex: PC portable bureautique · écran 27 pouces · serveur NAS · imprimante laser" style={input} />
            </div>
            <div style={{ flex: 1, minWidth: 100 }}>
              <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Budget max €</label>
              <input type="number" value={bMax} onChange={e => setBMax(e.target.value)} placeholder="500" style={input} />
            </div>
            <div style={{ flex: 1, minWidth: 90 }}>
              <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Min € (opt.)</label>
              <input type="number" value={bMin} onChange={e => setBMin(e.target.value)} placeholder="0" style={input} />
            </div>
            <button onClick={runBudget} disabled={bLoading || !bQuery.trim()} style={{ ...btn('primary'), opacity: (bLoading || !bQuery.trim()) ? 0.5 : 1 }}>
              {bLoading ? '🌐 Recherche…' : 'Trouver'}
            </button>
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>
            💡 Marvin cherche les offres dans votre budget, les trie par prix et signale le meilleur rapport qualité/prix.
          </div>
        </div>
      )}

      {mode === 'budget' && bRes && (
        bRes.count > 0 ? (
          <div style={{ ...card }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 4 }}>
              🛒 {bRes.count} offre(s){bRes.max_budget ? ` sous ${bRes.max_budget}€` : ''}
              {bRes.price_range_in_budget && <span style={{ color: 'var(--text-muted)', fontWeight: 400, fontSize: 12 }}> · de {bRes.price_range_in_budget.min}€ à {bRes.price_range_in_budget.max}€</span>}
            </div>
            {bRes.best_value && (
              <div style={{ fontSize: 12, color: '#22c55e', marginBottom: 10 }}>
                🏆 Meilleur rapport qualité/prix : <strong>{bRes.best_value.title}</strong> — {bRes.best_value.price_eur}€ {bRes.best_value.rating ? `(⭐${bRes.best_value.rating}/5)` : ''}
              </div>
            )}
            {bRes.offers.map((o, i) => (
              <div key={i} style={{ padding: '10px 0', borderBottom: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 10 }}>
                  <a href={o.url} target="_blank" rel="noreferrer" style={{ fontSize: 13, color: '#60a5fa', textDecoration: 'none', fontWeight: 600 }}>
                    {i === 0 ? '💰 ' : ''}{o.title}
                  </a>
                  <span style={{ fontSize: 15, fontWeight: 800, color: '#4f8cff', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>{o.price_eur} €</span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 3 }}>
                  {o.rating && <span style={{ color: '#f59e0b' }}>⭐ {o.rating}/5{o.reviews ? ` (${o.reviews})` : ''} · </span>}
                  {o.snippet}
                </div>
              </div>
            ))}
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 10, fontStyle: 'italic' }}>{bRes.disclaimer}</div>
          </div>
        ) : (
          <div style={{ ...card, color: 'var(--text-muted)', fontSize: 13 }}>{bRes.message || 'Aucune offre trouvée dans ce budget.'}</div>
        )
      )}

      {mode === 'compare' && <div style={{ ...card, marginBottom: 20 }}>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div style={{ flex: 3, minWidth: 260 }}>
            <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Produit / prestation</label>
            <input value={query} onChange={e => setQuery(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && run()}
              placeholder="ex: Dell Latitude 5550 i5 16Go 512Go · Microsoft 365 Business Premium · pare-feu Fortinet 60F"
              style={input} />
          </div>
          <div style={{ flex: 1, minWidth: 110 }}>
            <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Marge cible %</label>
            <input type="number" value={margin} onChange={e => setMargin(e.target.value)} style={input} />
          </div>
          <button onClick={run} disabled={loading || !query.trim()} style={{ ...btn('primary'), opacity: (loading || !query.trim()) ? 0.5 : 1 }}>
            {loading ? '🌐 Recherche…' : 'Comparer'}
          </button>
        </div>
      </div>}

      {mode === 'compare' && res && res.prices_analyzed > 0 && (
        <>
          {res.confidence && (() => {
            const ci = { 'élevée': { c: '#22c55e', t: 'Fiabilité élevée' }, 'moyenne': { c: '#f59e0b', t: 'Fiabilité moyenne' }, 'faible': { c: '#ef4444', t: 'Fiabilité faible' } }[res.confidence] || { c: '#888', t: res.confidence };
            return (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12, padding: '8px 12px',
                background: ci.c + '12', border: `1px solid ${ci.c}40`, borderRadius: 8, fontSize: 12 }}>
                <span style={{ color: ci.c, fontWeight: 700 }}>● {ci.t}</span>
                <span style={{ color: 'var(--text-muted)' }}>
                  {res.prices_analyzed} prix retenus · {res.outliers_removed} écarté(s) · {res.found_prices} détecté(s)
                </span>
                {res.confidence === 'faible' && <span style={{ color: '#ef4444' }}>— vérifiez les sources avant de chiffrer</span>}
              </div>
            );
          })()}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 12, marginBottom: 16 }}>
            <StatBox label="Prix le plus bas" value={`${res.market.min_eur} €`} color="#22c55e" />
            <StatBox label="Prix médian marché" value={`${res.market.median_eur} €`} color="#4f8cff" />
            <StatBox label="Prix le plus haut" value={`${res.market.max_eur} €`} color="#ef4444" />
            <StatBox label="Prix d'achat conseillé" value={`${res.recommended_cost_basis_eur} €`} color="#3b82f6" />
          </div>

          {res.reviews && (
            <div style={{ ...card, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 14 }}>
              <span style={{ fontSize: 26 }}>⭐</span>
              <div>
                <div style={{ fontSize: 18, fontWeight: 800, color: '#f59e0b' }}>
                  {res.reviews.average_rating}/5
                  <span style={{ fontSize: 12, color: 'var(--text-muted)', fontWeight: 400, marginLeft: 8 }}>
                    sur {res.reviews.total_reviews || '?'} avis · {res.reviews.rated_sources} source(s)
                  </span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Avis agrégés du web (note pondérée)</div>
              </div>
            </div>
          )}

          <div style={{ ...card, marginBottom: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 12 }}>💰 Prix de vente conseillé (3 paliers)</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 10 }}>
              {['basic', 'standard', 'premium'].map(t => {
                const s = res.recommended_sell[t]; const ti = TIER_INFO[t];
                return (
                  <div key={t} style={{ padding: 12, borderRadius: 8, border: `1px solid ${ti.color}40`,
                    background: t === 'standard' ? `${ti.color}10` : 'transparent', textAlign: 'center' }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: ti.color }}>{ti.label}{t === 'standard' ? ' ⭐' : ''}</div>
                    <div style={{ fontSize: 20, fontWeight: 800, color: 'var(--text-primary)', margin: '6px 0', fontFamily: 'monospace' }}>{s.sell_price_ht} €</div>
                    <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>marge {s.margin_pct}% · +{s.profit}€</div>
                  </div>
                );
              })}
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 12, padding: '8px 12px', background: 'rgba(79, 140, 255,0.07)', borderRadius: 6 }}>
              💡 {res.advice}
            </div>
          </div>

          <div style={{ ...card }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 10 }}>
              📋 Sources ({res.sources?.length || 0}) · {res.found_prices} prix détectés
            </div>
            {(res.sources || []).map((s, i) => (
              <div key={i} style={{ padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
                <a href={s.url} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: '#60a5fa', textDecoration: 'none' }}>{s.title || s.url}</a>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                  {(s.prices_eur || []).length > 0 && <>Prix : {(s.prices_eur || []).map(p => `${p}€`).join(' · ')}</>}
                  {s.rating != null && <span style={{ color: '#f59e0b', marginLeft: (s.prices_eur||[]).length ? 8 : 0 }}>⭐ {s.rating}/5{s.reviews ? ` (${s.reviews} avis)` : ''}</span>}
                </div>
              </div>
            ))}
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 10, fontStyle: 'italic' }}>{res.disclaimer}</div>
          </div>
        </>
      )}
      {mode === 'compare' && res && !res.prices_analyzed && (
        <div style={{ ...card, color: 'var(--text-muted)', fontSize: 13 }}>
          {res.message || 'Aucun prix fiable détecté.'} Affinez la requête avec une référence précise (modèle exact).
        </div>
      )}
    </div>
  );
}

function StatBox({ label, value, color }) {
  return (
    <div style={{ ...card, textAlign: 'center', padding: '14px 12px' }}>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 800, color: color || 'var(--text-primary)', marginTop: 6, fontFamily: 'monospace' }}>{value}</div>
    </div>
  );
}

// ── Base de connaissances IT (consultable) ──────────────────────────────────────
