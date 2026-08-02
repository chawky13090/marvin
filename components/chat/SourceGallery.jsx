'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { BACKEND_URL } from '@/lib/backend';
import styles from './SourceGallery.module.css';


const EVIDENCE = {
  page_read: { label: 'Page lue', className: 'verified' },
  snippet_only: { label: 'Aperçu moteur', className: 'preview' },
  access_restricted: { label: 'Connexion requise', className: 'restricted' },
  rejected: { label: 'Source écartée', className: 'rejected' },
};

function domainOf(url) {
  try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return ''; }
}

function displayText(value) {
  return String(value || '').replace(/\uFFFD+/g, '…').replace(/\s+/g, ' ').trim();
}

function normalizeSource(source, index) {
  const url = String(source?.url || source?.requested_url || '');
  const rawEvidence = source?.evidence_level || source?.evidence;
  const evidence = EVIDENCE[rawEvidence] ? rawEvidence : 'snippet_only';
  return {
    id: source?.id || source?.citation || `${url}-${index}`,
    title: displayText(source?.title || url || 'Source Web'),
    url,
    domain: String(source?.domain || domainOf(url)),
    publisher: displayText(source?.publisher || source?.domain || domainOf(url)),
    publishedAt: String(source?.published_at || source?.publishedAt || ''),
    imageUrl: String(source?.image_url || source?.thumbnail || source?.imageUrl || ''),
    faviconUrl: String(source?.favicon_url || source?.faviconUrl || ''),
    evidence,
  };
}

function previewUrl(url) {
  return url ? `${BACKEND_URL}/api/web/source-preview?url=${encodeURIComponent(url)}` : '';
}

function formatDate(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' });
}

function SourcePreview({ source, index }) {
  const [state, setState] = useState('loading');
  const label = (source.publisher || source.domain || 'Web').slice(0, 1).toUpperCase();
  const sourceUrl = previewUrl(source.imageUrl || source.url);

  return (
    <>
      <span className={styles.visualFallback} aria-hidden="true">{label}</span>
      {state === 'loading' && <span className={styles.visualLoading} aria-hidden="true" />}
      {state === 'failed' && (
        <span className={styles.visualUnavailable}>Aperçu indisponible</span>
      )}
      <img
        className={state === 'loaded' ? styles.visualImageLoaded : styles.visualImagePending}
        src={sourceUrl}
        alt=""
        loading={index < 4 ? 'eager' : 'lazy'}
        fetchPriority={index < 2 ? 'high' : 'auto'}
        decoding="async"
        onLoad={() => setState('loaded')}
        onError={() => setState('failed')}
      />
    </>
  );
}

export function collectWebSources(toolInvocations = []) {
  const candidates = [];
  for (const tool of toolInvocations) {
    if (!String(tool?.toolName || '').startsWith('web_')) continue;
    let result = tool?.result;
    if (result?.type === 'json' && result.value !== undefined) result = result.value;
    if (!result || typeof result !== 'object') continue;
    if (Array.isArray(result.sources)) candidates.push(...result.sources);
    if (Array.isArray(result.results)) {
      candidates.push(...result.results.map(source => ({ ...source, evidence_level: 'snippet_only' })));
    }
    if (result.url || result.requested_url) {
      candidates.push({
        ...result,
        url: result.requested_url || result.url,
        evidence_level: result.access_limited ? 'access_restricted' : 'page_read',
      });
    }
  }
  const ranks = { page_read: 3, access_restricted: 2, snippet_only: 1, rejected: 0 };
  const byUrl = new Map();
  candidates.map(normalizeSource).forEach((source) => {
    if (!/^https?:\/\//i.test(source.url)) return;
    const existing = byUrl.get(source.url);
    if (!existing || ranks[source.evidence] > ranks[existing.evidence]) byUrl.set(source.url, source);
  });
  return [...byUrl.values()].sort((a, b) => ranks[b.evidence] - ranks[a.evidence]).slice(0, 50);
}

export default function SourceGallery({ sources = [] }) {
  const trackRef = useRef(null);
  const closeButtonRef = useRef(null);
  const closeTimerRef = useRef(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [filter, setFilter] = useState('');
  const normalized = useMemo(() => sources.map(normalizeSource), [sources]);
  const visibleSources = useMemo(() => {
    const query = filter.trim().toLocaleLowerCase('fr-FR');
    const indexed = normalized.map((source, index) => ({ ...source, citationIndex: index + 1 }));
    if (!query) return indexed;
    return indexed.filter(source => (
      `${source.title} ${source.publisher} ${source.domain} ${source.url}`
        .toLocaleLowerCase('fr-FR').includes(query)
    ));
  }, [filter, normalized]);
  const closePanel = () => {
    if (closeTimerRef.current !== null) return;
    closeTimerRef.current = window.setTimeout(() => {
      setPanelOpen(false);
      closeTimerRef.current = null;
    }, 120);
  };
  useEffect(() => {
    if (!panelOpen) return undefined;
    closeButtonRef.current?.focus();
    const closeOnEscape = (event) => {
      if (event.key === 'Escape') setPanelOpen(false);
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => {
      window.removeEventListener('keydown', closeOnEscape);
      if (closeTimerRef.current !== null) {
        window.clearTimeout(closeTimerRef.current);
        closeTimerRef.current = null;
      }
    };
  }, [panelOpen]);
  if (normalized.length === 0) return null;

  const readCount = normalized.filter(source => source.evidence === 'page_read').length;
  const scroll = (direction) => trackRef.current?.scrollBy({
    left: direction * Math.max(280, trackRef.current.clientWidth * 0.72),
    behavior: 'smooth',
  });

  return (
    <>
    <section className={styles.gallery} aria-label={`Sources Web (${normalized.length})`}>
      <div className={styles.header}>
        <div>
          <strong>Sources</strong>
          <span>{readCount} page{readCount > 1 ? 's' : ''} réellement lue{readCount > 1 ? 's' : ''}</span>
        </div>
        <div className={styles.controls}>
          <button
            type="button"
            className={styles.sourcesButton}
            onClick={() => setPanelOpen(true)}
            aria-haspopup="dialog"
          >
            Sources ({normalized.length})
          </button>
          <button type="button" onClick={() => scroll(-1)} aria-label="Sources précédentes">←</button>
          <button type="button" onClick={() => scroll(1)} aria-label="Sources suivantes">→</button>
        </div>
      </div>
      <div className={styles.track} ref={trackRef} tabIndex={0}>
        {normalized.map((source, index) => {
          const evidence = EVIDENCE[source.evidence];
          const date = formatDate(source.publishedAt);
          return (
            <a
              className={`${styles.card} ${styles[evidence.className]}`}
              href={source.url}
              target="_blank"
              rel="noopener noreferrer"
              key={source.id}
              aria-label={`Ouvrir la source ${index + 1} : ${source.title}`}
            >
              <div className={styles.visual}>
                {source.evidence !== 'access_restricted' && (
                  <SourcePreview source={source} index={index} />
                )}
                <span className={styles.sourceNumber}>[{index + 1}]</span>
                <span className={styles.evidence}>{evidence.label}</span>
              </div>
              <div className={styles.body}>
                <div className={styles.publisherRow}>
                  {source.faviconUrl && (
                    <img src={previewUrl(source.faviconUrl)} alt="" loading="lazy" onError={(event) => { event.currentTarget.style.display = 'none'; }} />
                  )}
                  <span>{source.publisher || source.domain}</span>
                </div>
                <div className={styles.title}>{source.title}</div>
                <div className={styles.footer}>{date || source.domain}</div>
              </div>
            </a>
          );
        })}
      </div>
    </section>
    {panelOpen && typeof document !== 'undefined' && createPortal(
      <div className={styles.panelBackdrop} onClick={closePanel}>
        <aside
          className={styles.sourcesPanel}
          role="dialog"
          aria-modal="true"
          aria-labelledby="web-sources-title"
          onClick={(event) => event.stopPropagation()}
        >
          <div className={styles.panelHeader}>
            <div>
              <strong id="web-sources-title">Sources de la réponse</strong>
              <span>{readCount} page{readCount > 1 ? 's' : ''} lue{readCount > 1 ? 's' : ''} · {normalized.length} lien{normalized.length > 1 ? 's' : ''}</span>
            </div>
            <button
              ref={closeButtonRef}
              type="button"
              onClick={closePanel}
              aria-label="Fermer les sources"
            >
              ×
            </button>
          </div>
          {normalized.length >= 8 && (
            <label className={styles.sourceFilter}>
              <span className="sr-only">Filtrer les sources</span>
              <input
                type="search"
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                placeholder="Rechercher dans les sources"
              />
            </label>
          )}
          <div className={styles.sourceList}>
            {visibleSources.map((source) => {
              const evidence = EVIDENCE[source.evidence];
              return (
                <a
                  href={source.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={styles.sourceLink}
                  key={`${source.id}-panel`}
                >
                  <span className={styles.sourceIndex}>{source.citationIndex}</span>
                  <span className={styles.sourceLinkBody}>
                    <strong>{source.title}</strong>
                    <span>{source.publisher || source.domain}</span>
                    <small>{source.url}</small>
                  </span>
                  <span className={`${styles.sourceEvidence} ${styles[evidence.className]}`}>{evidence.label}</span>
                  <span className={styles.openSource} aria-hidden="true">↗</span>
                </a>
              );
            })}
            {visibleSources.length === 0 && (
              <p className={styles.noSource}>Aucune source ne correspond à ce filtre.</p>
            )}
          </div>
          <p className={styles.panelNote}>Chaque lien ouvre la page d’origine afin que vous puissiez vérifier directement l’information.</p>
        </aside>
      </div>,
      document.body,
    )}
    </>
  );
}
