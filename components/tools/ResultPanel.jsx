'use client';
import { useState } from 'react';
import PrettyResult from '@/components/chat/PrettyResult';
import FileAction from '@/components/tools/FileAction';
import { callBackendTool } from '@/lib/tools/api';

function ResultPanel({ result, error, accentColor }) {
  const [collapsed, setCollapsed] = useState(false);
  const [showJson, setShowJson] = useState(false);

  if (error) return (
    <div style={{
      marginTop: '12px', padding: '12px 14px',
      background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)',
      borderRadius: 'var(--radius-md)', color: '#f87171', fontSize: 'var(--font-xs)',
    }}>
      ⚠️ {error}
    </div>
  );

  if (!result) return null;

  // Image (screenshot, infographie)
  const img = result.image || result.path?.match(/\.(png|jpg|jpeg|gif|webp)$/i)?.[0];
  const isImage = result.image?.startsWith('data:image') || false;

  // Fichiers listés
  const fileList = result.entries || result.files || result.results || result.items;
  const isFileList = Array.isArray(fileList);

  // Résultats web
  const webResults = result.results && Array.isArray(result.results) && result.results[0]?.url;

  return (
    <div style={{ marginTop: '12px' }}>
      {/* Header résultat */}
      <div
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '8px 12px',
          background: `${accentColor}10`, borderRadius: collapsed ? 'var(--radius-md)' : 'var(--radius-md) var(--radius-md) 0 0',
          border: `1px solid ${accentColor}25`,
        }}
      >
        <span
          onClick={() => setCollapsed(c => !c)}
          style={{ fontSize: 'var(--font-xs)', fontWeight: 700, color: accentColor, cursor: 'pointer', flex: 1 }}
        >
          ✅ Résultat {collapsed ? '▼' : '▲'}
        </span>
        <div style={{ display: 'flex', gap: '6px' }}>
          <button
            onClick={() => setShowJson(j => !j)}
            title={showJson ? 'Affichage lisible' : 'Voir le JSON brut'}
            style={{
              padding: '2px 8px', borderRadius: '4px',
              border: `1px solid ${showJson ? accentColor + '66' : 'rgba(255,255,255,0.1)'}`,
              background: showJson ? `${accentColor}22` : 'rgba(255,255,255,0.05)',
              color: showJson ? accentColor : 'var(--text-muted)', fontSize: '10px', cursor: 'pointer',
            }}
          >
            {showJson ? '✨ Lisible' : '{ } JSON'}
          </button>
          <button
            onClick={() => {
              const text = typeof result === 'object' ? JSON.stringify(result, null, 2) : String(result);
              navigator.clipboard.writeText(text).catch(() => {});
            }}
            title="Copier en JSON"
            style={{
              padding: '2px 8px', borderRadius: '4px', border: '1px solid rgba(255,255,255,0.1)',
              background: 'rgba(255,255,255,0.05)', color: 'var(--text-muted)',
              fontSize: '10px', cursor: 'pointer',
            }}
          >
            📋 Copier
          </button>
          {result?.text && (
            <button
              onClick={() => navigator.clipboard.writeText(result.text).catch(() => {})}
              title="Copier le texte"
              style={{
                padding: '2px 8px', borderRadius: '4px', border: '1px solid rgba(255,255,255,0.1)',
                background: 'rgba(255,255,255,0.05)', color: 'var(--text-muted)',
                fontSize: '10px', cursor: 'pointer',
              }}
            >
              📝 Texte
            </button>
          )}
          {result?.path && (
            <button
              onClick={() => navigator.clipboard.writeText(result.path).catch(() => {})}
              title="Copier le chemin"
              style={{
                padding: '2px 8px', borderRadius: '4px', border: '1px solid rgba(255,255,255,0.1)',
                background: 'rgba(255,255,255,0.05)', color: 'var(--text-muted)',
                fontSize: '10px', cursor: 'pointer',
              }}
            >
              📂 Chemin
            </button>
          )}
        </div>
      </div>

      {!collapsed && showJson && (
        <pre style={{
          margin: 0, padding: '12px 14px', background: 'var(--bg-primary)',
          borderRadius: '0 0 var(--radius-md) var(--radius-md)',
          border: `1px solid ${accentColor}20`, borderTop: 'none',
          maxHeight: '420px', overflowY: 'auto', fontSize: '11px',
          color: 'var(--text-secondary)', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
        }}>
          {typeof result === 'object' ? JSON.stringify(result, null, 2) : String(result)}
        </pre>
      )}

      {!collapsed && !showJson && (
        <div style={{
          padding: '12px 14px',
          background: 'var(--bg-primary)',
          borderRadius: '0 0 var(--radius-md) var(--radius-md)',
          border: `1px solid ${accentColor}20`,
          borderTop: 'none',
          maxHeight: '380px', overflowY: 'auto',
        }}>
          {/* Succès simple */}
          {result.success && result.message && (
            <div style={{ color: '#4ade80', fontSize: 'var(--font-xs)', marginBottom: isFileList || isImage ? '10px' : 0 }}>
              ✓ {result.message}
              {result.path && !isImage && (
                <div style={{ color: 'var(--text-muted)', fontFamily: 'monospace', fontSize: '10px', marginTop: '4px' }}>
                  📍 {result.path}
                </div>
              )}
            </div>
          )}

          {/* Image inline */}
          {isImage && (
            <img src={result.image} alt="Résultat"
              style={{ maxWidth: '100%', borderRadius: '6px', marginTop: '8px', cursor: 'pointer' }}
              onClick={() => window.open(result.image, '_blank')}
            />
          )}

          {/* Résultats de recherche web */}
          {webResults && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {result.results.map((r, i) => (
                <div key={i} style={{
                  padding: '8px 10px', borderRadius: '6px',
                  background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)',
                }}>
                  <a href={r.url} target="_blank" rel="noopener noreferrer"
                    style={{ color: accentColor, fontWeight: 600, fontSize: 'var(--font-xs)', textDecoration: 'none' }}>
                    {r.title || r.url}
                  </a>
                  <div style={{ color: 'var(--text-muted)', fontSize: '10px', marginTop: '2px', fontFamily: 'monospace' }}>{r.url}</div>
                  {r.snippet && <div style={{ color: 'var(--text-secondary)', fontSize: '11px', marginTop: '4px', lineHeight: 1.4 }}>{r.snippet}</div>}
                </div>
              ))}
            </div>
          )}

          {/* Liste de fichiers */}
          {isFileList && !webResults && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              {fileList.slice(0, 40).map((f, i) => {
                const fpath = (typeof f === 'object') ? (f.path || f.full_path || f.filepath || f.location) : null;
                return (
                  <div key={i} className="file-row" style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    gap: 8, padding: '5px 8px', borderRadius: '4px',
                    background: 'rgba(255,255,255,0.02)', fontSize: '11px',
                  }}>
                    <span style={{ color: 'var(--text-primary)', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}
                      title={fpath || ''}>
                      {f.is_dir ? '📁 ' : '📄 '}{f.name || (typeof f === 'string' ? f : fpath) || '—'}
                    </span>
                    {f.size_human && <span style={{ color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{f.size_human}</span>}
                    {fpath && (
                      <span style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                        <FileAction icon="📂" title="Ouvrir" onClick={() => callBackendTool('pc_open_file', { path: fpath })} />
                        <FileAction icon="🔎" title="Révéler dans l'Explorateur" onClick={() => callBackendTool('pc_reveal', { path: fpath })} />
                        <FileAction icon="📋" title="Copier le chemin" onClick={() => navigator.clipboard.writeText(fpath).catch(() => {})} />
                      </span>
                    )}
                  </div>
                );
              })}
              {fileList.length > 40 && (
                <div style={{ color: 'var(--text-muted)', fontSize: '10px', textAlign: 'center', marginTop: '4px' }}>
                  +{fileList.length - 40} éléments supplémentaires
                </div>
              )}
            </div>
          )}

          {/* Texte brut (read, system_info, etc.) */}
          {result.content && (
            <pre style={{
              fontSize: '11px', color: 'var(--text-secondary)', lineHeight: 1.5,
              whiteSpace: 'pre-wrap', fontFamily: 'monospace', margin: 0,
            }}>
              {String(result.content).slice(0, 3000)}
              {String(result.content).length > 3000 && '\n…(tronqué)'}
            </pre>
          )}

          {/* OCR — texte extrait */}
          {result.text && !result.content && (
            <div>
              {result.model && (
                <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '8px', fontFamily: 'monospace' }}>
                  Modèle : {result.model} — {result.char_count} caractères extraits
                </div>
              )}
              <pre style={{
                fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.6,
                whiteSpace: 'pre-wrap', fontFamily: 'monospace', margin: 0,
                padding: '10px', background: 'rgba(255,255,255,0.03)',
                borderRadius: '6px', border: '1px solid rgba(255,255,255,0.06)',
              }}>
                {result.text}
              </pre>
            </div>
          )}

          {/* Réseau — output texte (ping, traceroute) */}
          {result.output && (
            <div>
              {result.summary && (
                <div style={{ marginBottom: '8px', padding: '6px 10px', background: `${accentColor}12`, borderRadius: '6px',
                  fontSize: '12px', color: accentColor, fontFamily: 'monospace' }}>
                  ⚡ {result.summary.trim()}
                </div>
              )}
              <pre style={{
                fontSize: '11px', color: 'var(--text-secondary)', lineHeight: 1.5,
                whiteSpace: 'pre-wrap', fontFamily: 'monospace', margin: 0,
                maxHeight: '260px', overflowY: 'auto',
              }}>
                {result.output}
              </pre>
            </div>
          )}

          {/* Réseau — ports ouverts */}
          {result.open_ports !== undefined && (
            <div>
              <div style={{ fontSize: '12px', color: accentColor, marginBottom: '8px', fontFamily: 'monospace' }}>
                {result.summary}
              </div>
              {result.open_ports.length > 0 ? (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                  {result.open_ports.map(p => (
                    <span key={p} style={{
                      padding: '3px 10px', borderRadius: '12px', fontSize: '12px',
                      background: '#22c55e22', border: '1px solid #22c55e44', color: '#4ade80',
                      fontFamily: 'monospace',
                    }}>
                      :{p}
                    </span>
                  ))}
                </div>
              ) : (
                <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Aucun port ouvert trouvé.</div>
              )}
            </div>
          )}

          {/* Réseau — appareils ARP */}
          {result.devices !== undefined && Array.isArray(result.devices) && (
            <div>
              <div style={{ fontSize: '12px', color: accentColor, marginBottom: '10px', fontFamily: 'monospace' }}>
                {result.count} appareil{result.count > 1 ? 's' : ''} détecté{result.count > 1 ? 's' : ''}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                {result.devices.map((d, i) => (
                  <div key={i} style={{
                    display: 'grid', gridTemplateColumns: '140px 160px 1fr',
                    gap: '8px', padding: '5px 8px', borderRadius: '5px',
                    background: 'rgba(255,255,255,0.02)', fontSize: '11px', fontFamily: 'monospace',
                  }}>
                    <span style={{ color: accentColor }}>{d.ip}</span>
                    <span style={{ color: 'var(--text-muted)' }}>{d.mac}</span>
                    <span style={{ color: 'var(--text-muted)', fontSize: '10px' }}>{d.type}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Réseau — DNS */}
          {result.addresses && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '4px' }}>ADRESSES IP</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                  {result.addresses.map((a, i) => (
                    <span key={i} style={{
                      padding: '3px 10px', borderRadius: '12px',
                      background: `${accentColor}15`, border: `1px solid ${accentColor}30`,
                      color: accentColor, fontFamily: 'monospace', fontSize: '12px',
                    }}>{a}</span>
                  ))}
                </div>
              </div>
              {result.hostname && (
                <div style={{ fontSize: '12px', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>
                  ↩ {result.hostname}
                </div>
              )}
              {result.nslookup && (
                <pre style={{ fontSize: '10px', color: 'var(--text-muted)', whiteSpace: 'pre-wrap', margin: 0, maxHeight: '160px', overflowY: 'auto' }}>
                  {result.nslookup}
                </pre>
              )}
            </div>
          )}

          {/* Réseau — WHOIS */}
          {result.whois && (
            <pre style={{
              fontSize: '10px', color: 'var(--text-secondary)', whiteSpace: 'pre-wrap',
              fontFamily: 'monospace', margin: 0, maxHeight: '260px', overflowY: 'auto',
              lineHeight: 1.5,
            }}>
              {result.whois}
            </pre>
          )}

          {/* Couleur (color_tool) */}
          {result.hex && result.rgb && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                <div style={{
                  width: '60px', height: '60px', borderRadius: '10px',
                  background: result.hex, border: '2px solid rgba(255,255,255,0.1)',
                  flexShrink: 0,
                }} />
                <div style={{ flex: 1 }}>
                  {[
                    ['HEX', result.hex],
                    ['RGB', result.rgb_str],
                    ['HSL', result.hsl_str],
                    ['Luminance', result.luminance],
                    ['Clarté', result.brightness],
                  ].map(([k, v]) => (
                    <div key={k} style={{ display: 'flex', gap: '8px', fontSize: '12px', marginBottom: '2px' }}>
                      <span style={{ color: 'var(--text-muted)', minWidth: '80px' }}>{k}</span>
                      <code style={{ color: accentColor }}>{v}</code>
                    </div>
                  ))}
                </div>
                {result.complementary && (
                  <div style={{ textAlign: 'center' }}>
                    <div style={{
                      width: '40px', height: '40px', borderRadius: '8px',
                      background: result.complementary, border: '2px solid rgba(255,255,255,0.1)',
                    }} />
                    <div style={{ fontSize: '9px', color: 'var(--text-muted)', marginTop: '4px' }}>Comp.</div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* IP Info */}
          {result.country && result.city && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '12px' }}>
              {[
                ['IP', result.ip], ['Pays', `${result.country_code} ${result.country}`],
                ['Ville', result.city], ['Région', result.region],
                ['Fuseau', result.timezone], ['ISP', result.isp],
                ['ASN', result.asn], ['Lat/Lon', `${result.latitude}, ${result.longitude}`],
              ].filter(([, v]) => v).map(([k, v]) => (
                <div key={k} style={{ display: 'flex', flexDirection: 'column' }}>
                  <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{k}</span>
                  <span style={{ color: 'var(--text-primary)', fontFamily: 'monospace', fontSize: '11px' }}>{v}</span>
                </div>
              ))}
            </div>
          )}

          {/* Hash */}
          {result.hash && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{result.algorithm} ({result.source})</div>
              <code style={{
                wordBreak: 'break-all', padding: '8px 10px', background: 'rgba(255,255,255,0.04)',
                borderRadius: '6px', fontSize: '12px', color: accentColor, fontFamily: 'monospace',
                border: '1px solid rgba(255,255,255,0.06)',
              }}>
                {result.hash}
              </code>
            </div>
          )}

          {/* URL Analyze */}
          {result.status && result.url && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '12px' }}>
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                <span style={{
                  padding: '2px 10px', borderRadius: '12px', fontWeight: 700,
                  background: result.status < 400 ? '#22c55e22' : '#ef444422',
                  color: result.status < 400 ? '#4ade80' : '#f87171',
                  border: `1px solid ${result.status < 400 ? '#22c55e44' : '#ef444444'}`,
                }}>
                  HTTP {result.status}
                </span>
                <span style={{ color: 'var(--text-muted)' }}>{result.response_time_ms}ms</span>
                {result.server && <span style={{ color: 'var(--text-muted)' }}>🖥️ {result.server}</span>}
              </div>
              {result.title && <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{result.title}</div>}
              {result.description && <div style={{ color: 'var(--text-secondary)', lineHeight: 1.4 }}>{result.description}</div>}
              <a href={result.url} target="_blank" rel="noopener noreferrer" style={{ color: accentColor, fontSize: '11px', wordBreak: 'break-all' }}>{result.url}</a>
            </div>
          )}

          {/* PDF Info */}
          {result.pages !== undefined && result.file && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '12px' }}>
              {[
                ['Fichier', result.file?.split('\\').pop()],
                ['Pages', result.pages],
                ['Taille', `${result.size_kb} Ko`],
                ['Chiffré', result.encrypted ? 'Oui' : 'Non'],
                ['Titre', result.title],
                ['Auteur', result.author],
                ['Créateur', result.creator],
              ].filter(([, v]) => v).map(([k, v]) => (
                <div key={k} style={{ display: 'flex', flexDirection: 'column' }}>
                  <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{k}</span>
                  <span style={{ color: 'var(--text-primary)', fontFamily: 'monospace', fontSize: '11px', wordBreak: 'break-all' }}>{v}</span>
                </div>
              ))}
            </div>
          )}

          {/* XLSX / CSV data table */}
          {result.headers && result.data && Array.isArray(result.data) && (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '11px' }}>
                <thead>
                  <tr>
                    {result.headers.map(h => (
                      <th key={h} style={{
                        padding: '5px 8px', textAlign: 'left', borderBottom: `1px solid ${accentColor}30`,
                        color: accentColor, fontWeight: 700, whiteSpace: 'nowrap',
                      }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.data.slice(0, 20).map((row, i) => (
                    <tr key={i} style={{ background: i % 2 === 0 ? 'rgba(255,255,255,0.02)' : 'transparent' }}>
                      {result.headers.map(h => (
                        <td key={h} style={{
                          padding: '4px 8px', color: 'var(--text-secondary)',
                          borderBottom: '1px solid rgba(255,255,255,0.04)',
                          maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                        }}>
                          {row[h] ?? ''}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              {result.data.length > 20 && (
                <div style={{ fontSize: '10px', color: 'var(--text-muted)', textAlign: 'center', marginTop: '6px' }}>
                  +{result.data.length - 20} lignes supplémentaires
                </div>
              )}
            </div>
          )}

          {/* QR Code image */}
          {result.output && result.size_px && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', alignItems: 'flex-start' }}>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                💾 Sauvegardé : <code style={{ color: accentColor }}>{result.output?.split('\\').pop()}</code>
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                {result.size_px?.[0]}×{result.size_px?.[1]} px · {result.size_kb} Ko
              </div>
            </div>
          )}

          {/* Base64 result */}
          {result.action === 'encode' && result.result && !result.hex && (
            <code style={{
              wordBreak: 'break-all', padding: '8px 10px', background: 'rgba(255,255,255,0.04)',
              borderRadius: '6px', fontSize: '12px', color: accentColor, fontFamily: 'monospace',
              border: '1px solid rgba(255,255,255,0.06)', display: 'block',
            }}>
              {result.result}
            </code>
          )}

          {/* Translation result */}
          {result.translated && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '13px' }}>
              <div style={{ color: 'var(--text-muted)', fontSize: '11px' }}>
                {result.source_lang?.toUpperCase()} → {result.target_lang?.toUpperCase()}
              </div>
              <div style={{ padding: '10px 14px', background: 'rgba(255,255,255,0.04)', borderRadius: '8px', lineHeight: 1.6, color: 'var(--text-primary)' }}>
                {result.translated}
              </div>
            </div>
          )}

          {/* Password result */}
          {result.password && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <code style={{
                padding: '10px 14px', background: 'rgba(255,255,255,0.04)', borderRadius: '8px',
                fontSize: '16px', color: accentColor, fontFamily: 'monospace', letterSpacing: '0.05em',
                border: `1px solid ${accentColor}30`,
              }}>
                {result.password}
              </code>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                Entropie : {result.entropy_bits} bits · Force : {result.strength}
              </div>
            </div>
          )}

          {/* Code Python result */}
          {result.stdout !== undefined && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {result.stdout && result.stdout !== '(aucune sortie)' && (
                <div>
                  <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '4px' }}>STDOUT</div>
                  <pre style={{
                    padding: '8px 12px', background: '#0d1117', borderRadius: '6px',
                    fontSize: '12px', color: '#c9d1d9', fontFamily: 'monospace',
                    whiteSpace: 'pre-wrap', margin: 0, maxHeight: '200px', overflowY: 'auto',
                    border: '1px solid rgba(228, 228, 231,0.08)',
                  }}>
                    {result.stdout}
                  </pre>
                </div>
              )}
              {result.stderr && (
                <div>
                  <div style={{ fontSize: '10px', color: '#f87171', marginBottom: '4px' }}>STDERR</div>
                  <pre style={{ padding: '8px 12px', background: '#1a0808', borderRadius: '6px', fontSize: '11px', color: '#f87171', fontFamily: 'monospace', whiteSpace: 'pre-wrap', margin: 0 }}>
                    {result.stderr}
                  </pre>
                </div>
              )}
              {result.result !== null && result.result !== undefined && (
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center', fontSize: '12px' }}>
                  <span style={{ color: 'var(--text-muted)' }}>result =</span>
                  <code style={{ color: accentColor, fontFamily: 'monospace' }}>{String(result.result)}</code>
                </div>
              )}
              {result.vars && Object.keys(result.vars).length > 0 && (
                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                  Variables: {Object.entries(result.vars).map(([k,v]) => `${k}=${v}`).join(', ')}
                </div>
              )}
            </div>
          )}

          {/* JSON brut fallback — pour tout le reste */}
          {!result.content && !result.text && !result.output && result.open_ports === undefined
           && !result.devices && !result.addresses && !result.whois
           && !result.hex && !result.country && !result.hash && !result.status
           && !result.pages && !result.headers && !result.translated && !result.password
           && result.stdout === undefined
           && !(result.success && result.message) && !isFileList && !webResults && !isImage && (
            <PrettyResult result={result} />
          )}
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════

export default ResultPanel;
