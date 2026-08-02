'use client';

const isCloudModelName = model => (
  model.endsWith(':cloud')
  || model.endsWith('-cloud')
  || /^gemma4:e\d+b$/i.test(model)
);

export function ModelSettingsPanel({
  activeTab,
  status,
  models,
  recommendedModels,
  selectedModel,
  handleSetModel,
  pullModelName,
  setPullModelName,
  isPulling,
  handlePullModel,
  ollamaUrl,
  autoConfig,
  portfolioPolicy,
  savePortfolioPolicy,
  portfolioSaving,
  cloudEnabled,
  localOnlyLockdown,
  ultraUnrestricted,
  privacyPreset,
  presetApplying,
  applyPreset,
  cloudOverrides,
  setCloudModelForProfile,
  cloudSaving,
}) {
  return (
    <>
{/* ═══════════════════════════════════════════════════════════════════
              ONGLET : MODÈLE IA
              ═══════════════════════════════════════════════════════════════════ */}
          {activeTab === 'model' && (
            <div className="card" style={{ borderLeft: '4px solid var(--accent-primary)' }}>
              <div className="card-title" style={{ fontSize: 'var(--font-lg)' }}>🧠 Modèle IA — Ollama</div>

              <div style={{
                display: 'flex', alignItems: 'center', gap: '12px',
                padding: '12px 16px', background: 'var(--bg-secondary)',
                borderRadius: 'var(--radius-md)', marginBottom: '16px',
              }}>
                <span className={`badge-dot ${status?.ollama?.connected ? 'connected' : 'disconnected'}`}
                  style={{ width: '12px', height: '12px' }} />
                <div>
                  <div style={{ fontWeight: 600, color: status?.ollama?.connected ? 'var(--success)' : 'var(--danger)' }}>
                    {status?.ollama?.connected ? '🟢 Ollama est connecté et prêt' : '🔴 Ollama est déconnecté'}
                  </div>
                  {!status?.ollama?.connected && (
                    <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginTop: '4px' }}>
                      Lancez Ollama sur votre PC pour continuer. Téléchargez-le sur{' '}
                      <a href="https://ollama.com" target="_blank" rel="noreferrer" style={{ color: 'var(--accent-secondary)' }}>ollama.com</a>
                    </div>
                  )}
                </div>
              </div>

              <div style={{
                display: 'flex', alignItems: 'center', gap: '12px',
                padding: '12px 16px', background: 'var(--bg-secondary)',
                borderRadius: 'var(--radius-md)', marginBottom: '16px',
              }}>
                <span style={{ fontSize: '1.4rem' }}>🎯</span>
                <div>
                  <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)' }}>Modèle actuellement actif :</div>
                  <div style={{
                    fontWeight: 700, fontSize: 'var(--font-md)',
                    background: 'var(--accent-gradient)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
                  }}>
                    {status?.ollama?.model || 'Aucun modèle détecté'}
                  </div>
                </div>
              </div>

              <div style={{ marginBottom: '16px' }}>
                <label style={{ display: 'block', fontSize: 'var(--font-sm)', color: 'var(--text-secondary)', marginBottom: '8px', fontWeight: 600 }}>
                  📋 Changer de modèle actif :
                </label>
                {models.length > 0 ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {models.map(m => {
                      const isActive = m === selectedModel || m === status?.ollama?.model;
                      const recInfo = recommendedModels.find(r => m === r.name);
                      return (
                        <button key={m} onClick={() => handleSetModel(m)} style={{
                          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                          padding: '10px 16px', border: `2px solid ${isActive ? 'var(--accent-primary)' : 'var(--border)'}`,
                          borderRadius: 'var(--radius-md)', cursor: 'pointer',
                          background: isActive ? 'rgba(139, 92, 246, 0.08)' : 'var(--bg-secondary)',
                          color: 'var(--text-primary)', transition: 'all 0.2s', textAlign: 'left',
                        }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                            <span style={{ fontSize: '1.2rem' }}>{isActive ? '✅' : '⚪'}</span>
                            <div>
                              <div style={{ fontWeight: isActive ? 700 : 500, fontSize: 'var(--font-sm)' }}>{m}</div>
                              {recInfo && <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{recInfo.speed} • {recInfo.size}</div>}
                            </div>
                          </div>
                          {isActive && <span className="badge badge-success" style={{ fontSize: '10px' }}>ACTIF</span>}
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <div style={{
                    padding: '16px', background: 'var(--warning-bg)', borderRadius: 'var(--radius-md)',
                    border: '1px solid var(--warning)', color: 'var(--warning)', fontSize: 'var(--font-sm)',
                  }}>
                    ⚠️ Aucun modèle détecté. {status?.ollama?.connected ? 'Téléchargez-en un ci-dessous.' : 'Lancez d\'abord Ollama.'}
                  </div>
                )}
                <button onClick={fetchStatus} style={{
                  marginTop: '8px', padding: '6px 12px',
                  background: 'transparent', border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-md)', color: 'var(--text-secondary)',
                  cursor: 'pointer', fontSize: 'var(--font-xs)',
                }}>
                  🔄 Rafraîchir la liste des modèles
                </button>
              </div>

              <div style={{
                background: 'var(--bg-tertiary)', padding: '16px',
                borderRadius: 'var(--radius-md)', border: '1px solid var(--border)',
              }}>
                {portfolioPolicy?.policy && (
                  <div style={{
                    marginBottom: 14, padding: 14, borderRadius: 'var(--radius-md)',
                    background: 'var(--bg-secondary)', border: '1px solid var(--border)',
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'center' }}>
                      <div>
                        <div style={{ fontWeight: 700, color: 'var(--text-primary)' }}>Portefeuille local autonome</div>
                        <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginTop: 4, lineHeight: 1.5 }}>
                          Maintient les rôles conversation, outils, analyse, vision, code, OCR et mémoire.
                          Aucun modèle n’est supprimé automatiquement.
                        </div>
                      </div>
                      <button
                        type="button"
                        disabled={portfolioSaving}
                        onClick={() => savePortfolioPolicy({
                          ...portfolioPolicy.policy,
                          auto_download: !portfolioPolicy.policy.auto_download,
                        })}
                        style={{
                          padding: '8px 14px', borderRadius: 'var(--radius-full)', cursor: 'pointer',
                          border: '1px solid var(--border)', fontWeight: 700,
                          background: portfolioPolicy.policy.auto_download ? 'var(--success-bg)' : 'var(--bg-tertiary)',
                          color: portfolioPolicy.policy.auto_download ? 'var(--success)' : 'var(--text-secondary)',
                        }}
                      >
                        {portfolioPolicy.policy.auto_download ? 'Automatique actif' : 'Activer'}
                      </button>
                    </div>
                    <div style={{ marginTop: 10, fontSize: 'var(--font-xs)', color: 'var(--text-secondary)' }}>
                      Réseau : <strong>{portfolioPolicy.network_cost || 'inconnu'}</strong>
                      {' · '}Budget disque : <strong>{portfolioPolicy.policy.max_disk_gb} Go</strong>
                      {' · '}À installer : <strong>{(portfolioPolicy.auto_download_queue || []).join(', ') || 'rien'}</strong>
                    </div>
                    {(portfolioPolicy.missing_roles || []).length > 0 && (
                      <div style={{ color: 'var(--warning)', marginTop: 6, fontSize: 'var(--font-xs)' }}>
                        Couverture manquante : {portfolioPolicy.missing_roles.join(', ')}
                      </div>
                    )}
                  </div>
                )}
                {autoConfig && (
                  <div style={{
                    marginBottom: 14, padding: 12, borderRadius: 'var(--radius-md)',
                    background: 'var(--bg-secondary)', color: 'var(--text-secondary)',
                    fontSize: 'var(--font-xs)', lineHeight: 1.6,
                  }}>
                    Budget local sûr : <strong>{autoConfig.model_memory_budget_gb} Go</strong>
                    {' '}— {autoConfig.hardware?.gpu || 'CPU détecté'}.
                    {(autoConfig.rejected_overrides || []).length > 0 && (
                      <div style={{ color: 'var(--warning)', marginTop: 4 }}>
                        {(autoConfig.rejected_overrides || []).length} préférence obsolète ignorée
                        pour éviter un modèle trop lourd ou incompatible.
                      </div>
                    )}
                  </div>
                )}
                <div style={{ fontWeight: 700, fontSize: 'var(--font-sm)', marginBottom: '12px', color: 'var(--text-primary)' }}>
                  📥 Télécharger un nouveau modèle
                </div>
                <div style={{ display: 'flex', gap: '12px', marginBottom: '12px' }}>
                  <input className="input" value={pullModelName} onChange={e => setPullModelName(e.target.value)}
                    placeholder="ex: llama3.2:3b" style={{ flex: 1 }} />
                  <button onClick={handlePullModel} disabled={isPulling} style={{
                    padding: '10px 20px', background: 'var(--accent-gradient)',
                    border: 'none', borderRadius: 'var(--radius-md)',
                    color: 'white', fontWeight: 700, cursor: 'pointer',
                    boxShadow: 'var(--accent-glow)', opacity: isPulling ? 0.7 : 1, whiteSpace: 'nowrap',
                  }}>
                    {isPulling ? '⏳ Téléchargement...' : '📥 Télécharger'}
                  </button>
                </div>
                <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '8px', fontWeight: 600 }}>
                  💡 Suggestions rapides :
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                  {recommendedModels.map(r => (
                    <button key={r.name} onClick={() => setPullModelName(r.name)} style={{
                      padding: '6px 10px', border: '1px solid var(--border)',
                      borderRadius: 'var(--radius-full)', cursor: 'pointer',
                      background: pullModelName === r.name ? 'var(--accent-gradient)' : 'var(--bg-secondary)',
                      color: pullModelName === r.name ? 'white' : 'var(--text-secondary)',
                      fontSize: '11px', fontWeight: 500, transition: 'all 0.2s',
                    }}>
                      {r.name} ({r.size})
                    </button>
                  ))}
                </div>
              </div>

              <div style={{ marginTop: '16px' }}>
                <label style={{ display: 'block', fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '6px' }}>
                  🔗 URL Ollama (avancé)
                </label>
                <input className="input" value={ollamaUrl} onChange={e => setOllamaUrl(e.target.value)} placeholder="http://localhost:11434" />
              </div>
            </div>
          )}

          {/* ═══════════════════════════════════════════════════════════════════
              ONGLET : MODÈLE IA — Ollama Cloud (v2.119)
              ═══════════════════════════════════════════════════════════════════ */}
          {activeTab === 'model' && (() => {
            const activePreset = localOnlyLockdown ? 'hyper'
              : (ultraUnrestricted && cloudEnabled) ? 'ultra'
              : privacyPreset;
            const PRESETS = [
              { id: 'normal', icon: '🛡️', label: 'Normal', tagline: 'Sécurisé — vous choisissez', color: '#f59e0b' },
              { id: 'hyper', icon: '🔒', label: 'Hyper sécurisé', tagline: '100% local, verrouillé', color: '#10b981' },
              { id: 'cloud_max', icon: '☁️', label: 'Tout cloud', tagline: 'Vitesse maximale', color: '#06b6d4' },
              { id: 'ultra', icon: '☠️', label: 'Ultra débridé', tagline: 'Aucune exception', color: '#ef4444' },
            ];
            return (
            <div className="card" style={{ borderLeft: '4px solid #06b6d4', marginTop: '16px' }}>
              <div className="card-title" style={{ fontSize: 'var(--font-lg)' }}>☁️ Ollama Cloud</div>

              {/* v2.120-121 — 4 préréglages globaux : un clic pour appliquer un setup complet */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '10px', marginBottom: '16px' }}>
                {PRESETS.map(p => {
                  const isActive = activePreset === p.id;
                  return (
                    <button key={p.id} onClick={() => applyPreset(p.id)} disabled={presetApplying} style={{
                      padding: '14px 12px', borderRadius: 'var(--radius-md)', cursor: presetApplying ? 'default' : 'pointer',
                      border: `2px solid ${isActive ? p.color : 'var(--border)'}`,
                      background: isActive ? `${p.color}18` : 'var(--bg-secondary)',
                      textAlign: 'center', transition: 'all 0.2s', opacity: presetApplying ? 0.6 : 1,
                    }}>
                      <div style={{ fontSize: '1.5rem', marginBottom: '4px' }}>{p.icon}</div>
                      <div style={{ fontWeight: 700, fontSize: 'var(--font-sm)', color: isActive ? p.color : 'var(--text-primary)' }}>{p.label}</div>
                      <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '2px' }}>{p.tagline}</div>
                      {isActive && <div style={{ marginTop: '6px', fontSize: '10px', fontWeight: 700, color: p.color }}>● ACTIF</div>}
                    </button>
                  );
                })}
              </div>

              {localOnlyLockdown && (
                <div style={{
                  padding: '12px 16px', background: 'rgba(16,185,129,0.08)', border: '1px solid rgba(16,185,129,0.3)',
                  borderRadius: 'var(--radius-md)', marginBottom: '16px', fontSize: 'var(--font-xs)', color: 'var(--text-secondary)', lineHeight: 1.6,
                }}>
                  🔒 <strong>Mode Hyper sécurisé actif</strong> : aucun modèle cloud ne peut être utilisé, même sélectionné manuellement — coupe-circuit total. Repassez en Normal pour reconfigurer le cloud.
                </div>
              )}

              {activePreset === 'ultra' && (
                <div style={{
                  padding: '12px 16px', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.35)',
                  borderRadius: 'var(--radius-md)', marginBottom: '16px', fontSize: 'var(--font-xs)', color: 'var(--text-secondary)', lineHeight: 1.6,
                }}>
                  ☠️ <strong>Mode Ultra débridé actif — cloud strict</strong> : tous les appels LLM génératifs, y compris vision, compétences et replis, restent dans Ollama Cloud. Si le cloud est indisponible, Marvin échoue explicitement au lieu de basculer sur un modèle local. Emails, SSH, mots de passe et factures peuvent partir au cloud. Le garde-fou système contre les commandes destructrices reste actif.
                </div>
              )}

              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px',
                padding: '12px 16px', background: 'var(--bg-secondary)',
                borderRadius: 'var(--radius-md)', marginBottom: '14px', opacity: localOnlyLockdown ? 0.5 : 1,
              }}>
                <div>
                  <div style={{ fontWeight: 600 }}>Activer les modèles cloud</div>
                  <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginTop: '2px' }}>
                    Utilise votre abonnement Ollama Cloud pour les tâches lourdes — plus rapide, sans limite de VRAM.
                  </div>
                </div>
                <label style={{ position: 'relative', display: 'inline-block', width: '44px', height: '24px', flexShrink: 0 }}>
                  <input type="checkbox" checked={cloudEnabled} onChange={e => saveCloudEnabled(e.target.checked)}
                    disabled={cloudSaving || localOnlyLockdown} style={{ opacity: 0, width: 0, height: 0 }} />
                  <span onClick={() => !cloudSaving && !localOnlyLockdown && saveCloudEnabled(!cloudEnabled)} style={{
                    position: 'absolute', inset: 0, borderRadius: '999px', cursor: localOnlyLockdown ? 'not-allowed' : 'pointer', transition: 'background 0.2s',
                    background: cloudEnabled ? '#06b6d4' : 'var(--border)',
                  }}>
                    <span style={{
                      position: 'absolute', top: '3px', left: cloudEnabled ? '23px' : '3px',
                      width: '18px', height: '18px', borderRadius: '50%', background: 'white', transition: 'left 0.2s',
                    }} />
                  </span>
                </label>
              </div>

              {activePreset !== 'ultra' && <div style={{
                padding: '12px 16px', background: 'rgba(6,182,212,0.08)', border: '1px solid rgba(6,182,212,0.25)',
                borderRadius: 'var(--radius-md)', marginBottom: '16px', fontSize: 'var(--font-xs)', color: 'var(--text-secondary)', lineHeight: 1.6,
              }}>
                🔒 <strong>Garde-fou intégré, non désactivable</strong> : toute demande touchant des données sensibles
                (emails, SSH, mots de passe/identifiants, clés API, factures/devis clients) reste <strong>toujours en local</strong>,
                même si le cloud est activé ci-dessus — Marvin bascule automatiquement, y compris en cours de conversation
                si un outil sensible est appelé de façon inattendue.
              </div>}

              {cloudEnabled && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  {['agent', 'chat', 'analysis'].map(profile => {
                    const cloudModels = models.filter(isCloudModelName);
                    return (
                      <div key={profile} style={{
                        display: 'flex', alignItems: 'center', gap: '12px',
                        padding: '10px 14px', background: 'var(--bg-secondary)', borderRadius: 'var(--radius-md)',
                      }}>
                        <div style={{ width: '90px', fontSize: 'var(--font-sm)', fontWeight: 600, textTransform: 'capitalize' }}>
                          {profile === 'agent' ? '🤖 Agent' : profile === 'chat' ? '💬 Chat' : '🔍 Analyse'}
                        </div>
                        <select
                          className="input"
                          value={cloudOverrides[profile] || ''}
                          onChange={e => setCloudModelForProfile(profile, e.target.value)}
                          disabled={cloudSaving}
                          style={{ flex: 1 }}
                        >
                          <option value="">— Rester en local —</option>
                          {cloudModels.map(m => <option key={m} value={m}>{m}</option>)}
                        </select>
                      </div>
                    );
                  })}
                  {models.filter(isCloudModelName).length === 0 && (
                    <div style={{
                      padding: '12px 16px', background: 'var(--warning-bg)', borderRadius: 'var(--radius-md)',
                      border: '1px solid var(--warning)', color: 'var(--warning)', fontSize: 'var(--font-xs)',
                    }}>
                      ⚠️ Aucun modèle cloud détecté. Téléchargez-en un via <code>ollama pull deepseek-v3.1:cloud</code>
                      {' '}(ou glm/kimi) puis rafraîchissez la liste des modèles ci-dessus.
                    </div>
                  )}
                </div>
              )}
            </div>
            ); })()}
    </>
  );
}
