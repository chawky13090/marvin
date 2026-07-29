'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import styles from './history.module.css';

function parseDate(conversation) {
  const value = conversation.updated_at || conversation.created_at;
  if (!value) return null;
  const date = new Date(String(value).replace(' ', 'T') + (String(value).includes('Z') ? '' : 'Z'));
  return Number.isNaN(date.getTime()) ? null : date;
}

function bucketFor(date) {
  if (!date) return 'Plus ancien';
  const now = new Date();
  const days = (now - date) / 86400000;
  if (date.toDateString() === now.toDateString()) return "Aujourd'hui";
  if (days < 7) return 'Cette semaine';
  if (date.getMonth() === now.getMonth() && date.getFullYear() === now.getFullYear()) return 'Ce mois';
  if (date.getFullYear() === now.getFullYear()) return 'Cette année';
  return String(date.getFullYear());
}

export default function ConversationHistoryPage() {
  const [conversations, setConversations] = useState([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    fetch(`/api/conversations?t=${Date.now()}`)
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(String(response.status))))
      .then((payload) => setConversations(Array.isArray(payload) ? payload : (payload.conversations || [])))
      .catch(() => setConversations([]))
      .finally(() => setLoading(false));
  }, []);

  const groups = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase('fr');
    const filtered = conversations.filter((conversation) => (
      !needle || String(conversation.title || '').toLocaleLowerCase('fr').includes(needle)
    ));
    const result = new Map();
    filtered.forEach((conversation) => {
      const date = parseDate(conversation);
      const bucket = bucketFor(date);
      if (!result.has(bucket)) result.set(bucket, []);
      result.get(bucket).push({ ...conversation, _date: date });
    });
    return [...result.entries()];
  }, [conversations, query]);

  function openConversation(id) {
    router.push(`/?conversation=${encodeURIComponent(id)}`);
  }

  return (
    <main className={styles.page}>
      <div className={styles.shell}>
        <header className={styles.header}>
          <div>
            <div className={styles.eyebrow}>Espace de travail</div>
            <h1 className={styles.title}>Historique des discussions</h1>
          </div>
          <Link className={styles.back} href="/">Retour au chat</Link>
        </header>
        <input
          className={styles.search}
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value.slice(0, 200))}
          placeholder={`Rechercher dans ${conversations.length} discussion${conversations.length > 1 ? 's' : ''}`}
          aria-label="Rechercher dans l’historique des discussions"
        />
        {loading ? (
          <div className={styles.empty}>Chargement de l’historique…</div>
        ) : groups.length === 0 ? (
          <div className={styles.empty}>Aucune discussion correspondante.</div>
        ) : (
          <div className={styles.groups}>
            {groups.map(([label, items]) => (
              <section key={label}>
                <h2 className={styles.groupTitle}>{label}</h2>
                <div className={styles.list}>
                  {items.map((conversation) => (
                    <button key={conversation.id} type="button" className={styles.item} onClick={() => openConversation(conversation.id)}>
                      <span className={styles.itemTitle}>{conversation.title || 'Conversation sans titre'}</span>
                      <time className={styles.itemDate} dateTime={conversation._date?.toISOString()}>
                        {conversation._date?.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' }) || 'Date inconnue'}
                      </time>
                    </button>
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
