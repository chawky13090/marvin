'use client';

import { useCallback, useEffect, useState } from 'react';
import { BACKEND_URL } from '@/lib/backend';


export default function LanAccessGate({ children }) {
  const [state, setState] = useState({ loading: true, required: false, authenticated: false });
  const [code, setCode] = useState('');
  const [accessProfile, setAccessProfile] = useState('full');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch(`${BACKEND_URL}/api/auth/lan/status`, {
        cache: 'no-store',
        signal: AbortSignal.timeout(8000),
      });
      const data = await response.json();
      setState({ loading: false, ...data });
    } catch {
      setState({ loading: false, required: true, authenticated: false });
      setError('Le backend Marvin ne répond pas.');
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function pair(event) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const response = await fetch(`${BACKEND_URL}/api/auth/lan/pair`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          code: code.trim(),
          access_profile: accessProfile,
        }),
        signal: AbortSignal.timeout(10000),
      });
      if (!response.ok) throw new Error('pairing_rejected');
      await refresh();
      setCode('');
    } catch {
      setError('Code refusé. Recopie le code affiché sur le PC qui exécute Marvin.');
    } finally {
      setBusy(false);
    }
  }

  if (state.loading) {
    return (
      <div className="lan-access-shell">
        <div className="lan-access-card">Vérification de l’accès Marvin…</div>
      </div>
    );
  }
  if (state.required && !state.authenticated) {
    return (
      <div className="lan-access-shell">
        <form className="lan-access-card" onSubmit={pair}>
          <div className="lan-access-mark">M</div>
          <h1>Jumeler cet appareil</h1>
          <p>
            Pour protéger les outils, fichiers et e-mails de Marvin sur le réseau local,
            saisis le code temporaire affiché dans la fenêtre Backend du PC principal.
          </p>
          <label htmlFor="marvin-pair-code">Code de jumelage</label>
          <input
            id="marvin-pair-code"
            value={code}
            onChange={(event) => setCode(event.target.value)}
            minLength={12}
            maxLength={128}
            autoComplete="one-time-code"
            autoFocus
          />
          <label htmlFor="marvin-access-profile">Niveau d’accès de cet appareil</label>
          <select
            id="marvin-access-profile"
            value={accessProfile}
            onChange={(event) => setAccessProfile(event.target.value)}
          >
            <option value="full">Complet — toutes les fonctions</option>
            <option value="standard">Standard — sans administration sensible</option>
            <option value="read_only">Lecture seule</option>
          </select>
          {error && <div className="lan-access-error">{error}</div>}
          <button type="submit" disabled={busy || code.trim().length < 12}>
            {busy ? 'Vérification…' : 'Autoriser cet appareil'}
          </button>
          <small>Le code change à chaque redémarrage. La session reste dans un cookie HttpOnly.</small>
        </form>
      </div>
    );
  }
  return children;
}
