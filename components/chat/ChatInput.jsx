'use client';
import { useState, useRef, useEffect, useCallback } from 'react';
import { useOptionalChat } from '@/lib/contexts/ChatContext';
import { openMicStream, createRecorder, startVAD as startVADShared } from '@/lib/voice/voiceRecorder';
import { BACKEND_URL } from '@/lib/backend';
import AutonomyControl from '@/components/chat/AutonomyControl';
import CortexControl from '@/components/chat/CortexControl';

export default function ChatInput({ input = '', setInput, handleInputChange, handleSubmit, isLoading, onStop, onImageAttach, messages = [], variant = 'dock' }) {
  // Voice context (TTS + voice mode)
  const chatCtx = useOptionalChat();
  const voiceCtx = chatCtx?.voice;
  const voiceMode = voiceCtx?.voiceMode || false;
  const isSpeaking = voiceCtx?.isSpeaking || false;
  const activeAssistant = [...messages].reverse().find(message => message?.role === 'assistant');
  const activeInvocations = activeAssistant?.toolInvocations || [];
  const completedInvocations = activeInvocations.filter(invocation => (
    invocation?.state === 'result'
    || invocation?.state === 'error'
    || invocation?.result !== undefined
  )).length;
  const textareaRef = useRef(null);
  const fileInputRef = useRef(null);
  const [attachedImages, setAttachedImages] = useState([]);
  const [uploading, setUploading] = useState(false);

  // ── Joindre un ou plusieurs documents (PDF/Word/Excel/texte) — Marvin lit leur contenu ─────
  // v2.140 — pièces jointes MULTIPLES (glisser-déposer demandé explicitement) : était limité à
  // un seul document (`attachedFile` objet unique) ; converti en tableau `attachedFiles`.
  const docInputRef = useRef(null);
  const [attachedFiles, setAttachedFiles] = useState([]);   // [{name, content, chars, truncated}]
  const [fileBusy, setFileBusy] = useState(false);
  async function uploadDocFile(file) {
    try {
      const fd = new FormData(); fd.append('file', file);
      const r = await fetch(`${BACKEND_URL}/api/chat/attach`, { method: 'POST', body: fd }).then(r => r.json());
      if (r.success && r.kind === 'text' && r.content) {
        return { name: r.name, content: r.content, chars: r.chars, truncated: r.truncated };
      }
      return { name: file.name, content: '', error: r.message || r.error || 'Type non lisible' };
    } catch {
      return { name: file.name, content: '', error: 'Échec du chargement' };
    }
  }
  async function handleDocSelect(e) {
    const files = Array.from(e.target?.files || []);
    if (files.length === 0) return;
    setFileBusy(true);
    const results = await Promise.all(files.map(uploadDocFile));
    setAttachedFiles(prev => [...prev, ...results]);
    setFileBusy(false);
    if (docInputRef.current) docInputRef.current.value = '';
  }
  function removeAttachedFile(idx) {
    setAttachedFiles(prev => prev.filter((_, i) => i !== idx));
  }

  // ── Menu "+" groupé (image/document/compétence) — v2.167 ────────────────────
  // Décongestionne la barre de saisie (5 icônes en dur → 1 bouton "+" qui ouvre
  // un petit menu), pattern Claude/ChatGPT. Micro et mode vocal restent visibles
  // en direct (actions fréquentes, un seul clic).
  const [attachMenu, setAttachMenu] = useState(false);

  // ── Menu compétences (insérer une skill dans le chat) ───────────────────────
  const [skillMenu, setSkillMenu] = useState(false);
  const [skills, setSkills] = useState([]);
  const [skillFilter, setSkillFilter] = useState('');
  useEffect(() => {
    if (skillMenu && skills.length === 0) {
      fetch(`${BACKEND_URL}/api/skills`).then(r => r.json()).then(d => setSkills(d.skills || [])).catch(() => {});
    }
  }, [skillMenu, skills.length]);
  const applyInput = useCallback((text) => {
    if (setInput) setInput(text);
    else if (handleInputChange) handleInputChange({ target: { value: text } });
  }, [setInput, handleInputChange]);
  const insertSkill = useCallback((s) => {
    const phrase = (s.triggers && s.triggers[0]) || s.name.replace(/-/g, ' ');
    applyInput((input ? input.trim() + ' ' : '') + phrase + ' ');
    setSkillMenu(false);
    setSkillFilter('');
    setTimeout(() => textareaRef.current?.focus(), 50);
  }, [input, applyInput]);

  // Création de compétence depuis le chat
  const [createMode, setCreateMode] = useState(null);   // null | 'prompt'
  const [createDesc, setCreateDesc] = useState('');
  const [skillBusy, setSkillBusy] = useState(false);
  const [skillMsg, setSkillMsg] = useState('');
  const genFromPrompt = useCallback(async () => {
    if (!createDesc.trim()) return;
    setSkillBusy(true); setSkillMsg('🤖 Marvin rédige la compétence…');
    try {
      const r = await fetch(`${BACKEND_URL}/api/skills/generate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ description: createDesc.trim() }) }).then(r => r.json());
      if (r.success) { setSkillMsg(`✅ Compétence « ${r.skill?.name} » créée`); setCreateDesc(''); setCreateMode(null); setSkills([]); }
      else setSkillMsg('⚠️ ' + (r.error || 'Échec'));
    } catch { setSkillMsg('❌ Backend injoignable'); }
    setSkillBusy(false);
  }, [createDesc]);
  const genFromConversation = useCallback(async () => {
    if (!messages || messages.length < 2) { setSkillMsg('⚠️ Échange trop court pour en faire une compétence.'); return; }
    setSkillBusy(true); setSkillMsg('🧠 Marvin analyse la conversation…');
    try {
      const r = await fetch(`${BACKEND_URL}/api/skills/from-conversation`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ messages: messages.map(m => ({ role: m.role, content: m.content })) }) }).then(r => r.json());
      if (r.success) { setSkillMsg(`✅ Compétence « ${r.skill?.name} » créée depuis la conversation`); setSkills([]); }
      else setSkillMsg('⚠️ ' + (r.error || 'Échec'));
    } catch { setSkillMsg('❌ Backend injoignable'); }
    setSkillBusy(false);
  }, [messages]);

  // ── Enregistrement vocal (module voiceRecorder partagé — voir son en-tête pour le
  //    détail des correctifs : choix de périphérique + repli robuste, MIME adaptatif,
  //    VAD sensible. Auparavant dupliqué ici ET dans useVoice.js avec les mêmes défauts.)
  const mediaRecorderRef = useRef(null);
  const vadRef = useRef(null);          // { stop } pour la détection de silence
  const [voiceState, setVoiceState] = useState('idle'); // 'idle' | 'recording' | 'transcribing'
  const [micError, setMicError] = useState('');
  const [showMicMenu, setShowMicMenu] = useState(false);
  // v2.186 — le sélecteur de voix n'était visible que DANS le bandeau "Mode vocal actif"
  // (ChatContainer.jsx), donc invisible dès qu'on n'active pas le mode mains-libres. Signalé
  // directement ("je ne vois plus l'option pour changer la voix") — ajouté ici en permanence,
  // à côté du bouton haut-parleur, même pattern que le choix du micro juste au-dessus.
  const [showVoiceMenu, setShowVoiceMenu] = useState(false);

  const startRecording = useCallback(async () => {
    setMicError('');
    try {
      // If Marvin is speaking, stop the audio so the mic doesn't pick it up
      if (voiceCtx?.isSpeaking) voiceCtx.stopSpeaking();

      const { stream, fellBack } = await openMicStream(voiceCtx?.micDeviceId, (m) => setMicError(m));
      if (fellBack) setMicError('Micro choisi indisponible — micro par défaut utilisé.');
      const { mr, chunks, mime } = createRecorder(stream);
      mr.onstop = async () => {
        if (vadRef.current) { try { vadRef.current.stop(); } catch {} vadRef.current = null; }
        stream.getTracks().forEach(t => t.stop());
        const blob = new Blob(chunks, { type: mime });
        if (blob.size < 1200) { setVoiceState('idle'); return; }   // trop court → on ignore
        setVoiceState('transcribing');
        try {
          const fd = new FormData();
          fd.append('file', blob, 'recording.webm');
          const res = await fetch(`${BACKEND_URL}/api/voice/transcribe`, { method: 'POST', body: fd });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const data = await res.json();
          if (data.text) {
            const transcribed = data.text.trim();
            // ── Voice mode : auto-send the transcription as a new message ─────
            if (voiceMode) {
              // Clear input first then send the transcription directly
              if (setInput) setInput('');
              // Use a synthetic submit with the transcribed text
              if (handleSubmit) {
                // Pass an object the parent's handleSend can read as override
                handleSubmit({ preventDefault: () => {}, voiceText: transcribed });
              }
            } else {
              // ── Normal mode : append to the input field ─────────────────────
              const merged = (input ? input.trimEnd() + ' ' : '') + transcribed;
              if (setInput) setInput(merged);
              else if (handleInputChange) handleInputChange({ target: { value: merged } });
            }
          }
        } catch (err) {
          console.error('Transcription error:', err);
          setMicError('Transcription impossible (réseau ou serveur).');
        } finally {
          setVoiceState('idle');
        }
      };
      mr.start();
      mediaRecorderRef.current = mr;
      setVoiceState('recording');
      // Auto-stop quand l'utilisateur se tait (mains libres)
      vadRef.current = startVADShared(stream, {
        onSilence: () => {
          if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
            mediaRecorderRef.current.stop();
          }
        },
      });
    } catch (err) {
      console.error('Microphone error:', err);
      setMicError(err?.name === 'NotAllowedError' ? 'Accès au micro refusé (autorisation navigateur).' : 'Impossible d\'accéder au microphone.');
      setVoiceState('idle');
    }
  }, [input, setInput, handleInputChange, voiceCtx, voiceMode, handleSubmit]);

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
  }, []);

  // Quitter le mode mains libres ferme immédiatement un micro encore ouvert.
  useEffect(() => {
    if (!voiceMode && voiceState === 'recording') stopRecording();
  }, [voiceMode, voiceState, stopRecording]);

  const toggleVoice = useCallback(() => {
    if (voiceState === 'idle') startRecording();
    else if (voiceState === 'recording') stopRecording();
  }, [voiceState, startRecording, stopRecording]);

  // ── Mains libres : en mode vocal, ré-écoute automatiquement quand Marvin a fini
  //    de parler (front montant→descendant de isSpeaking), si on est au repos.
  const prevSpeakingRef = useRef(false);
  useEffect(() => {
    const speaking = !!voiceCtx?.isSpeaking;
    const wasSpeaking = prevSpeakingRef.current;
    prevSpeakingRef.current = speaking;
    if (voiceMode && wasSpeaking && !speaking && voiceState === 'idle' && !isLoading) {
      const t = setTimeout(() => {
        if (voiceState === 'idle' && !voiceCtx?.isSpeaking) startRecording();
      }, 500);
      return () => clearTimeout(t);
    }
  }, [voiceCtx?.isSpeaking, voiceMode, voiceState, isLoading, startRecording]);

  // Échap ferme le menu de sélection du micro s'il est ouvert
  useEffect(() => {
    if (!showMicMenu) return;
    const onEsc = (e) => { if (e.key === 'Escape') setShowMicMenu(false); };
    window.addEventListener('keydown', onEsc);
    return () => window.removeEventListener('keydown', onEsc);
  }, [showMicMenu]);

  // Échap ferme le menu de sélection de la voix s'il est ouvert
  useEffect(() => {
    if (!showVoiceMenu) return;
    const onEsc = (e) => { if (e.key === 'Escape') setShowVoiceMenu(false); };
    window.addEventListener('keydown', onEsc);
    return () => window.removeEventListener('keydown', onEsc);
  }, [showVoiceMenu]);

  // Auto-resize du textarea
  useEffect(() => {
    const ta = textareaRef.current;
    if (ta) {
      ta.style.height = 'auto';
      ta.style.height = Math.min(ta.scrollHeight, 140) + 'px';
    }
  }, [input]);

  function onKeyDown(e) {
    if (e.key === '/' && !input && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      window.dispatchEvent(new Event('marvin:open-command-palette'));
      return;
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!isLoading && (input.trim() || attachedImages.length > 0 || attachedFiles.length > 0)) {
        doSubmit(e);
      }
    }
  }

  async function handleFileSelect(e) {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;
    setUploading(true);
    const newImages = [];
    for (const file of files) {
      try {
        const formData = new FormData();
        formData.append('file', file);
        const res = await fetch(`${BACKEND_URL}/api/upload-image`, { method: 'POST', body: formData });
        const data = await res.json();
        if (data.success) {
          newImages.push({ filename: data.filename, data: data.data, content_type: data.content_type });
        }
      } catch (err) {
        console.error('Upload failed:', err);
      }
    }
    setAttachedImages(prev => [...prev, ...newImages]);
    setUploading(false);
    // Reset file input
    if (fileInputRef.current) fileInputRef.current.value = '';
  }

  function removeImage(idx) {
    setAttachedImages(prev => prev.filter((_, i) => i !== idx));
  }

  function doSubmit(e) {
    if (attachedImages.length > 0 && onImageAttach) {
      onImageAttach(attachedImages);
    }
    setAttachedImages([]);
    // Documents joints → on injecte leur contenu dans le message (Marvin les lit directement).
    // v2.140 — plusieurs documents possibles, chacun dans son propre bloc identifié par nom.
    const readableFiles = attachedFiles.filter(f => f.content);
    if (readableFiles.length > 0) {
      if (e?.preventDefault) e.preventDefault();
      const q = (input || '').trim() || (
        readableFiles.length > 1
          ? 'Analyse ces documents et fais-m\'en un résumé clair.'
          : 'Analyse ce document et fais-m\'en un résumé clair.'
      );
      const blocks = readableFiles.map(f => {
        const trunc = f.truncated ? '\n[…document tronqué…]' : '';
        return `📎 Document joint « ${f.name} » :\n"""\n${f.content}${trunc}\n"""`;
      }).join('\n\n');
      const combined = `${blocks}\n\n${q}`;
      handleSubmit({ preventDefault: () => {}, voiceText: combined });
      setAttachedFiles([]);
      applyInput('');
      return;
    }
    handleSubmit(e);
  }

  // ── Glisser-déposer (v2.140) ────────────────────────────────────────────────
  // Classe chaque fichier déposé par type MIME : images → même chemin que le bouton 🖼️
  // (upload-image), tout le reste → même chemin que le bouton 📎 (chat/attach, lu comme texte).
  const [dragActive, setDragActive] = useState(false);
  const dragCounter = useRef(0);
  function onDragEnter(e) {
    e.preventDefault(); e.stopPropagation();
    dragCounter.current += 1;
    if (e.dataTransfer?.types?.includes('Files')) setDragActive(true);
  }
  function onDragLeave(e) {
    e.preventDefault(); e.stopPropagation();
    dragCounter.current -= 1;
    if (dragCounter.current <= 0) { dragCounter.current = 0; setDragActive(false); }
  }
  function onDragOver(e) {
    e.preventDefault(); e.stopPropagation();
  }
  async function onDrop(e) {
    e.preventDefault(); e.stopPropagation();
    dragCounter.current = 0;
    setDragActive(false);
    const files = Array.from(e.dataTransfer?.files || []);
    if (files.length === 0) return;
    const images = files.filter(f => f.type.startsWith('image/'));
    const docs = files.filter(f => !f.type.startsWith('image/'));
    if (images.length > 0) {
      handleFileSelect({ target: { files: images } });
    }
    if (docs.length > 0) {
      handleDocSelect({ target: { files: docs } });
    }
  }

  // Paste image support
  function handlePaste(e) {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        const file = item.getAsFile();
        if (file) {
          const fakeEvent = { target: { files: [file] } };
          handleFileSelect(fakeEvent);
        }
      }
    }
  }

  return (
    <form
      className={`marvin-chat-input-shell${variant === 'welcome' ? ' marvin-chat-input-shell--welcome' : ''}`}
      onSubmit={doSubmit}
      onDragEnter={onDragEnter}
      onDragLeave={onDragLeave}
      onDragOver={onDragOver}
      onDrop={onDrop}
      style={{
        padding: variant === 'welcome' ? '0' : '16px 24px 20px',
        borderTop: variant === 'welcome' ? 'none' : '1px solid var(--border)',
        background: variant === 'welcome' ? 'transparent' : 'var(--bg-secondary)',
        position: 'relative',
      }}
    >
      {/* Overlay glisser-déposer (v2.140) */}
      {dragActive && (
        <div style={{
          position: 'absolute', inset: 0, zIndex: 10,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: 'rgba(255, 255, 255, 0.055)', backdropFilter: 'blur(2px)',
          border: '2px dashed var(--accent-primary)', borderRadius: '16px', margin: '8px',
          pointerEvents: 'none',
        }}>
          <div style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--accent-primary)' }}>
            📥 Dépose ton/tes fichier(s) ici — images ou documents
          </div>
        </div>
      )}

      {/* Documents joints (v2.140 — plusieurs possibles) */}
      {attachedFiles.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 10 }}>
          {attachedFiles.map((f, idx) => (
            <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', borderRadius: 10, background: 'rgba(255,255,255,0.04)', border: '1px solid var(--border-hover)' }}>
              <span style={{ fontSize: '1.1rem' }}>📎</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.name}</div>
                <div style={{ fontSize: 11, color: f.error ? '#f87171' : 'var(--text-muted)' }}>
                  {f.error ? f.error : `${(f.chars || 0).toLocaleString('fr-FR')} caractères lus${f.truncated ? ' (tronqué)' : ''} — Marvin le lira`}
                </div>
              </div>
              <button type="button" onClick={() => removeAttachedFile(idx)} title="Retirer"
                style={{ background: 'none', border: 'none', color: '#f87171', cursor: 'pointer', fontSize: '1.1rem', lineHeight: 1 }}>×</button>
            </div>
          ))}
        </div>
      )}

      {/* Prévisualisation des images attachées */}
      {attachedImages.length > 0 && (
        <div style={{ display: 'flex', gap: '8px', marginBottom: '10px', flexWrap: 'wrap' }}>
          {attachedImages.map((img, idx) => (
            <div key={idx} style={{ position: 'relative', display: 'inline-block' }}>
              <img
                src={img.data}
                alt={img.filename}
                style={{ width: '64px', height: '64px', objectFit: 'cover', borderRadius: '8px', border: '1px solid var(--border)' }}
              />
              <button
                type="button"
                onClick={() => removeImage(idx)}
                style={{
                  position: 'absolute', top: '-6px', right: '-6px',
                  width: '18px', height: '18px', borderRadius: '50%',
                  background: '#ef4444', border: 'none', color: 'white',
                  fontSize: '11px', cursor: 'pointer', display: 'flex',
                  alignItems: 'center', justifyContent: 'center', lineHeight: 1,
                }}
              >×</button>
            </div>
          ))}
        </div>
      )}

      {(voiceMode || isSpeaking || voiceCtx?.voiceError) && (
        <div
          role="status"
          aria-live="polite"
          style={{
            display: 'flex', alignItems: 'center', gap: 8, minHeight: 34,
            marginBottom: 8, padding: '5px 8px 5px 10px',
            border: '1px solid var(--border-hover)', borderRadius: 10,
            background: 'rgba(255,255,255,.028)', color: 'var(--text-secondary)',
            fontSize: 11,
          }}
        >
          <span aria-hidden="true" style={{
            width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
            background: voiceCtx?.voiceError ? 'var(--warning)' : 'var(--accent-primary)',
            boxShadow: voiceMode ? '0 0 0 3px rgba(255,255,255,.07)' : 'none',
          }} />
          <strong style={{ color: 'var(--text-primary)', whiteSpace: 'nowrap' }}>
            {isSpeaking ? 'Marvin parle' : voiceState === 'recording' ? 'Écoute en cours' : voiceCtx?.voiceError ? 'Voix indisponible' : 'Conversation vocale'}
          </strong>
          <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {voiceCtx?.voiceError || (voiceMode ? 'Mains libres actives pour cette session' : 'Lecture en cours')}
          </span>
          {isSpeaking && (
            <button type="button" onClick={voiceCtx.stopSpeaking} style={{
              marginLeft: 'auto', border: 0, background: 'transparent',
              color: 'var(--warning)', cursor: 'pointer', fontSize: 11,
            }}>Couper</button>
          )}
          {voiceMode && (
            <button type="button" onClick={voiceCtx.toggleVoiceMode} style={{
              marginLeft: isSpeaking ? 0 : 'auto', padding: '4px 8px',
              border: '1px solid var(--border)', borderRadius: 7,
              background: 'rgba(255,255,255,.025)', color: 'var(--text-primary)',
              cursor: 'pointer', fontSize: 11,
            }}>Quitter</button>
          )}
        </div>
      )}

      <div className="marvin-chat-composer" style={{
        display: 'flex',
        alignItems: 'flex-end',
        gap: '8px',
        background: variant === 'welcome' ? 'rgba(24, 24, 29, .92)' : 'var(--bg-glass)',
        backdropFilter: 'blur(20px)',
        border: `1px solid ${variant === 'welcome' ? 'rgba(228, 228, 231, .14)' : 'var(--border)'}`,
        borderRadius: variant === 'welcome' ? '21px' : '16px',
        padding: variant === 'welcome' ? '13px 13px 13px 16px' : '8px 8px 8px 12px',
        minHeight: variant === 'welcome' ? '112px' : undefined,
        boxShadow: variant === 'welcome' ? '0 18px 55px rgba(0, 0, 0, .28)' : 'none',
        transition: 'border-color 0.2s, box-shadow 0.2s',
      }}
      onFocus={(e) => {
        e.currentTarget.style.borderColor = 'var(--border-focus)';
        e.currentTarget.style.boxShadow = '0 0 0 3px rgba(255, 255, 255, 0.055)';
      }}
      onBlur={(e) => {
        e.currentTarget.style.borderColor = 'var(--border)';
        e.currentTarget.style.boxShadow = 'none';
      }}
      >
        {/* Entrées fichier cachées — inchangées, juste déclenchées depuis le menu "+" */}
        <input
          ref={fileInputRef}
          type="file"
          accept="image/jpeg,image/png,image/gif,image/webp"
          multiple
          style={{ display: 'none' }}
          onChange={handleFileSelect}
        />
        <input ref={docInputRef} type="file" multiple accept=".pdf,.docx,.doc,.txt,.md,.markdown,.csv,.tsv,.xlsx,.xls,.pptx,.json,.log,.xml,.html,.htm,.rtf" style={{ display: 'none' }} onChange={handleDocSelect} />

        {/* Bouton "+" groupé — image / document / compétence (v2.167) */}
        <div style={{ position: 'relative', flexShrink: 0 }}>
          <button
            type="button"
            onClick={() => setAttachMenu(v => !v)}
            title="Joindre ou insérer (image, document, compétence)"
            style={{
              width: '34px', height: '34px', borderRadius: '8px',
              background: (attachMenu || attachedImages.length > 0 || attachedFiles.length > 0) ? 'rgba(255,255,255,0.075)' : 'transparent',
              border: `1px solid ${(attachMenu || attachedImages.length > 0 || attachedFiles.length > 0) ? 'var(--border-hover)' : 'transparent'}`,
              color: (attachMenu || attachedImages.length > 0 || attachedFiles.length > 0) ? 'var(--accent-primary)' : 'var(--text-muted)',
              fontSize: '1.25rem', lineHeight: 1, cursor: (uploading || fileBusy) ? 'wait' : 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              transition: 'all 0.2s', position: 'relative',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--accent-primary)'; }}
            onMouseLeave={(e) => { if (!attachMenu && !attachedImages.length && !attachedFiles.length) e.currentTarget.style.color = 'var(--text-muted)'; }}
          >
            {(uploading || fileBusy) ? '⏳' : '+'}
            {(attachedImages.length + attachedFiles.length) > 0 && (
              <span style={{
                position: 'absolute', top: '-3px', right: '-3px', minWidth: '14px', height: '14px',
                padding: '0 3px', borderRadius: '999px', background: 'var(--accent-primary)',
                color: '#0a0a0d', fontSize: '9px', fontWeight: 700, lineHeight: '14px', textAlign: 'center',
              }}>{attachedImages.length + attachedFiles.length}</span>
            )}
          </button>

          {attachMenu && (
            <>
              <div onClick={() => setAttachMenu(false)} style={{ position: 'fixed', inset: 0, zIndex: 90 }} />
              <div style={{
                position: 'absolute', bottom: '42px', left: 0, zIndex: 100,
                width: '220px', display: 'flex', flexDirection: 'column', gap: 2, padding: 6,
                background: 'var(--bg-secondary)', border: '1px solid var(--border)',
                borderRadius: '12px', boxShadow: 'var(--shadow-lg)',
              }}>
                <button type="button" onClick={() => { fileInputRef.current?.click(); setAttachMenu(false); }}
                  style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', textAlign: 'left', padding: '8px 10px', background: 'none', border: 'none', cursor: 'pointer', borderRadius: 8, color: 'var(--text-primary)', fontSize: 13 }}
                  onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-glass)'}
                  onMouseLeave={e => e.currentTarget.style.background = 'none'}>
                  🖼️ Image{attachedImages.length > 0 ? ` (${attachedImages.length})` : ''}
                </button>
                <button type="button" onClick={() => { docInputRef.current?.click(); setAttachMenu(false); }}
                  style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', textAlign: 'left', padding: '8px 10px', background: 'none', border: 'none', cursor: 'pointer', borderRadius: 8, color: 'var(--text-primary)', fontSize: 13 }}
                  onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-glass)'}
                  onMouseLeave={e => e.currentTarget.style.background = 'none'}>
                  📎 Document{attachedFiles.length > 0 ? ` (${attachedFiles.length})` : ''}
                </button>
                <button type="button" onClick={() => { setAttachMenu(false); setSkillMenu(true); }}
                  style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', textAlign: 'left', padding: '8px 10px', background: 'none', border: 'none', cursor: 'pointer', borderRadius: 8, color: 'var(--text-primary)', fontSize: 13 }}
                  onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-glass)'}
                  onMouseLeave={e => e.currentTarget.style.background = 'none'}>
                  🧩 Compétence
                </button>
              </div>
            </>
          )}

          {skillMenu && (
            <>
              <div onClick={() => setSkillMenu(false)} style={{ position: 'fixed', inset: 0, zIndex: 90 }} />
              <div style={{
                position: 'absolute', bottom: '42px', left: 0, zIndex: 100,
                width: '320px', maxHeight: '340px', display: 'flex', flexDirection: 'column',
                background: 'var(--bg-secondary)', border: '1px solid var(--border)',
                borderRadius: '12px', boxShadow: 'var(--shadow-lg)', overflow: 'hidden',
              }}>
                <div style={{ padding: '8px 10px', borderBottom: '1px solid var(--border)' }}>
                  <input value={skillFilter} onChange={e => setSkillFilter(e.target.value)}
                    placeholder="🧩 Chercher une compétence…"
                    style={{ width: '100%', padding: '6px 9px', borderRadius: 8, border: '1px solid var(--border)', background: 'rgba(255,255,255,0.04)', color: 'var(--text-primary)', fontSize: 13, boxSizing: 'border-box' }} />
                </div>

                {/* Créer une compétence */}
                <div style={{ padding: '8px 10px', borderBottom: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {createMode !== 'prompt' ? (
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button type="button" onClick={() => { setCreateMode('prompt'); setSkillMsg(''); }} disabled={skillBusy}
                        style={{ flex: 1, padding: '6px 8px', borderRadius: 8, border: '1px solid rgba(45,212,191,0.4)', background: 'rgba(45,212,191,0.1)', color: '#2dd4bf', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>✨ Créer une compétence</button>
                      <button type="button" onClick={genFromConversation} disabled={skillBusy}
                        title="Transformer cette conversation en compétence réutilisable"
                        style={{ flex: 1, padding: '6px 8px', borderRadius: 8, border: '1px solid rgba(45,212,191,0.4)', background: 'rgba(45,212,191,0.1)', color: '#2dd4bf', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>🧠 Depuis la conversation</button>
                    </div>
                  ) : (
                    <div style={{ display: 'flex', gap: 6 }}>
                      <input autoFocus value={createDesc} onChange={e => setCreateDesc(e.target.value)}
                        onKeyDown={e => { if (e.key === 'Enter') genFromPrompt(); if (e.key === 'Escape') setCreateMode(null); }}
                        placeholder="Décris la compétence (ex : préparer un devis)"
                        style={{ flex: 1, padding: '6px 9px', borderRadius: 8, border: '1px solid var(--border)', background: 'rgba(255,255,255,0.04)', color: 'var(--text-primary)', fontSize: 12, boxSizing: 'border-box' }} />
                      <button type="button" onClick={genFromPrompt} disabled={skillBusy || !createDesc.trim()}
                        style={{ padding: '6px 12px', borderRadius: 8, border: 'none', background: '#2dd4bf', color: '#06251f', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>{skillBusy ? '⏳' : 'OK'}</button>
                    </div>
                  )}
                  {skillMsg && <div style={{ fontSize: 11, color: skillMsg.startsWith('✅') ? '#34d399' : skillMsg.startsWith('⚠️') || skillMsg.startsWith('❌') ? '#f87171' : 'var(--text-muted)' }}>{skillMsg}</div>}
                </div>
                <div style={{ overflowY: 'auto', padding: 6 }}>
                  {skills.length === 0 && <div style={{ padding: 12, fontSize: 12, color: 'var(--text-muted)' }}>Aucune compétence.</div>}
                  {skills.filter(s => s.enabled !== false && (s.name + ' ' + (s.description || '')).toLowerCase().includes(skillFilter.toLowerCase())).map(s => (
                    <button key={s.name} type="button" onClick={() => insertSkill(s)} style={{
                      display: 'block', width: '100%', textAlign: 'left', padding: '7px 10px',
                      background: 'none', border: 'none', cursor: 'pointer', borderRadius: 8, color: 'var(--text-primary)',
                    }}
                    onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-glass)'}
                    onMouseLeave={e => e.currentTarget.style.background = 'none'}>
                      <div style={{ fontSize: 13, fontWeight: 600 }}>🧩 {s.name}</div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.description}</div>
                    </button>
                  ))}
                </div>
                <div style={{ padding: '6px 10px', borderTop: '1px solid var(--border)', fontSize: 10, color: 'var(--text-muted)' }}>
                  Clique pour insérer — Marvin appliquera la méthode.
                </div>
              </div>
            </>
          )}
        </div>

        <CortexControl
          contract={chatCtx?.cortexContract}
          onChange={chatCtx?.setCortexContract}
          disabled={isLoading}
          compact
        />

        <AutonomyControl disabled={isLoading} />

        {isLoading && (
          <div
            role="status"
            aria-live="polite"
            title={activeInvocations.length
              ? `${completedInvocations}/${activeInvocations.length} action(s) terminée(s)`
              : 'Marvin analyse la demande'}
            style={{
              minHeight: 34,
              maxWidth: 170,
              padding: '0 8px',
              borderRadius: 999,
              border: '1px solid var(--border-hover)',
              background: 'rgba(255,255,255,.045)',
              color: 'var(--text-secondary)',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              flexShrink: 1,
              overflow: 'hidden',
              fontSize: 10.5,
              whiteSpace: 'nowrap',
            }}
          >
            <span className="context-bar__status-dot" aria-hidden="true" style={{ background: 'var(--accent-primary)' }} />
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {activeInvocations.length
                ? `Travail · ${completedInvocations}/${activeInvocations.length}`
                : 'Marvin travaille'}
            </span>
          </div>
        )}

        {/* Bouton microphone — enregistrement vocal + sélecteur de périphérique */}
        <div style={{ position: 'relative', display: 'flex' }}>
          <button
            type="button"
            onClick={toggleVoice}
            disabled={voiceState === 'transcribing' || isLoading}
            title={voiceState === 'recording' ? 'Arrêter l\'enregistrement' : voiceState === 'transcribing' ? 'Transcription en cours…' : 'Dicter un message (Whisper)'}
            style={{
              width: '34px', height: '34px', borderRadius: '8px 0 0 8px',
              background: voiceState === 'recording'
                ? 'rgba(239,68,68,0.15)'
                : voiceState === 'transcribing'
                  ? 'rgba(255,255,255,0.065)'
                  : 'transparent',
              borderStyle: 'solid',
              borderWidth: '1px 0 1px 1px',
              borderColor: voiceState === 'recording' ? 'rgba(239,68,68,0.5)' : 'transparent',
              color: voiceState === 'recording' ? '#ef4444'
                : voiceState === 'transcribing' ? 'var(--accent-primary)'
                : 'var(--text-muted)',
              fontSize: '1rem', cursor: voiceState === 'transcribing' || isLoading ? 'not-allowed' : 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              transition: 'all 0.2s', flexShrink: 0,
              animation: voiceState === 'recording' ? 'pulse 1.2s ease-in-out infinite' : 'none',
            }}
            onMouseEnter={(e) => { if (voiceState === 'idle') e.currentTarget.style.color = 'var(--accent-primary)'; }}
            onMouseLeave={(e) => { if (voiceState === 'idle') e.currentTarget.style.color = 'var(--text-muted)'; }}
          >
            {voiceState === 'transcribing' ? (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <circle cx="12" cy="12" r="10"/>
                <path d="M12 6v6l4 2"/>
              </svg>
            ) : voiceState === 'recording' ? (
              /* carré stop */
              <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
                <rect x="2" y="2" width="10" height="10" rx="2"/>
              </svg>
            ) : (
              /* icône micro */
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="9" y="2" width="6" height="11" rx="3"/>
                <path d="M5 10a7 7 0 0 0 14 0"/>
                <line x1="12" y1="17" x2="12" y2="21"/>
                <line x1="9" y1="21" x2="15" y2="21"/>
              </svg>
            )}
          </button>

          {/* Choix du micro (casque Bluetooth, micro externe…) */}
          <button
            type="button"
            onClick={() => setShowMicMenu(s => !s)}
            title="Choisir le micro"
            style={{
              width: '16px', height: '34px', borderRadius: '0 8px 8px 0',
              background: 'transparent', border: 'none', color: 'var(--text-muted)',
              cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: '9px', flexShrink: 0,
            }}
          >▾</button>

          {showMicMenu && (
            <>
              <div onClick={() => setShowMicMenu(false)} style={{ position: 'fixed', inset: 0, zIndex: 40 }} />
              <div style={{
                position: 'absolute', bottom: '100%', left: 0, marginBottom: 8,
                background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 10,
                minWidth: 220, maxWidth: 300, zIndex: 41, boxShadow: 'var(--shadow-lg)', padding: 6,
              }}>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', padding: '4px 8px', fontWeight: 600, textTransform: 'uppercase' }}>Microphone</div>
                <button type="button" onClick={() => { voiceCtx?.setMicDevice?.(''); setShowMicMenu(false); }}
                  style={{ display: 'block', width: '100%', textAlign: 'left', padding: '7px 8px', borderRadius: 6, border: 'none',
                    background: !voiceCtx?.micDeviceId ? 'rgba(255,255,255,0.07)' : 'transparent',
                    color: !voiceCtx?.micDeviceId ? 'var(--accent-primary)' : 'var(--text-primary)', cursor: 'pointer', fontSize: 12.5 }}>
                  {!voiceCtx?.micDeviceId ? '✓ ' : ''}🎙️ Micro par défaut du système
                </button>
                {(voiceCtx?.micDevices || []).map((d) => (
                  <button key={d.deviceId} type="button" onClick={() => { voiceCtx?.setMicDevice?.(d.deviceId); setShowMicMenu(false); }}
                    style={{ display: 'block', width: '100%', textAlign: 'left', padding: '7px 8px', borderRadius: 6, border: 'none',
                      background: voiceCtx?.micDeviceId === d.deviceId ? 'rgba(255,255,255,0.07)' : 'transparent',
                      color: voiceCtx?.micDeviceId === d.deviceId ? 'var(--accent-primary)' : 'var(--text-primary)', cursor: 'pointer', fontSize: 12.5,
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {voiceCtx?.micDeviceId === d.deviceId ? '✓ ' : ''}🎙️ {d.label}
                  </button>
                ))}
                {(!voiceCtx?.micDevices || voiceCtx.micDevices.length === 0) && (
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: '4px 8px' }}>Autorise le micro une fois pour voir la liste.</div>
                )}
              </div>
            </>
          )}
        </div>

        {(micError || voiceCtx?.voiceError) && (
          <div title={micError || voiceCtx?.voiceError} style={{
            fontSize: 10.5, color: '#f0a85a', maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis',
            whiteSpace: 'nowrap', flexShrink: 1, alignSelf: 'center',
          }}>⚠️ {micError || voiceCtx?.voiceError}</div>
        )}

        {/* Mode vocal — toggle pour faire répondre Marvin à voix haute automatiquement */}
        {voiceCtx && (
          <button
            type="button"
            onClick={voiceCtx.toggleVoiceMode}
            title={voiceMode
              ? 'Mode vocal ACTIF — Marvin parle ses réponses. Cliquez pour désactiver.'
              : 'Activer le mode vocal — Marvin parlera ses réponses à voix haute.'}
            style={{
              width: '34px', height: '34px', borderRadius: '8px',
              background: voiceMode ? 'rgba(255,255,255,0.085)' : 'transparent',
              border: `1px solid ${voiceMode ? 'var(--border-hover)' : 'transparent'}`,
              color: voiceMode ? 'var(--accent-primary)' : 'var(--text-muted)',
              fontSize: '1rem', cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              transition: 'all 0.2s', flexShrink: 0,
              boxShadow: voiceMode ? '0 0 0 3px rgba(255,255,255,0.055)' : 'none',
            }}
            onMouseEnter={(e) => { if (!voiceMode) e.currentTarget.style.color = 'var(--accent-primary)'; }}
            onMouseLeave={(e) => { if (!voiceMode) e.currentTarget.style.color = 'var(--text-muted)'; }}
          >
            {isSpeaking ? (
              /* speaker waves animé */
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ animation: 'pulse 1s ease-in-out infinite' }}>
                <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                <path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/>
              </svg>
            ) : voiceMode ? (
              /* speaker on */
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                <path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>
              </svg>
            ) : (
              /* speaker off */
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                <line x1="23" y1="9" x2="17" y2="15"/>
                <line x1="17" y1="9" x2="23" y2="15"/>
              </svg>
            )}
          </button>
        )}

        {/* Choix de la voix — toujours visible, pas seulement en mode vocal mains-libres */}
        {voiceCtx && voiceCtx.voiceList?.length > 0 && (
          <div style={{ position: 'relative', flexShrink: 0 }}>
            <button
              type="button"
              onClick={() => setShowVoiceMenu(s => !s)}
              title={`Voix : ${voiceCtx.voiceList.find(v => v.key === voiceCtx.currentVoice)?.label?.split('(')[0]?.trim() || voiceCtx.currentVoice}`}
              style={{
                width: '20px', height: '34px', borderRadius: '8px',
                background: 'transparent', border: 'none', color: 'var(--text-muted)',
                cursor: 'pointer', fontSize: '9px', flexShrink: 0,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}
            >▾</button>

            {showVoiceMenu && (
              <>
                <div onClick={() => setShowVoiceMenu(false)} style={{ position: 'fixed', inset: 0, zIndex: 40 }} />
                <div style={{
                  position: 'absolute', bottom: '100%', left: 0, marginBottom: 8,
                  background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 10,
                  minWidth: 200, maxWidth: 280, zIndex: 41, boxShadow: 'var(--shadow-lg)', padding: 6,
                }}>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', padding: '4px 8px', fontWeight: 600, textTransform: 'uppercase' }}>Voix de Marvin</div>
                  {voiceCtx.voiceList.map(v => (
                    <button key={v.key} type="button" onClick={() => { voiceCtx.setVoice(v.key); setShowVoiceMenu(false); }}
                      style={{ display: 'block', width: '100%', textAlign: 'left', padding: '7px 8px', borderRadius: 6, border: 'none',
                        background: voiceCtx.currentVoice === v.key ? 'rgba(255,255,255,0.07)' : 'transparent',
                        color: voiceCtx.currentVoice === v.key ? 'var(--accent-primary)' : 'var(--text-primary)', cursor: 'pointer', fontSize: 12.5,
                        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {voiceCtx.currentVoice === v.key ? '✓ ' : ''}🔊 {v.label?.split('(')[0]?.trim() || v.key}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        )}

        <textarea
          className="marvin-chat-composer__input"
          ref={textareaRef}
          value={input}
          onChange={(e) => {
            if (setInput) {
              setInput(e.target.value);
            } else if (handleInputChange) {
              handleInputChange(e);
            }
          }}
          onKeyDown={onKeyDown}
          onPaste={handlePaste}
          placeholder={variant === 'welcome'
            ? 'Décrivez votre objectif, ou tapez / pour choisir une capacité…'
            : 'Demandez quelque chose… (Entrée pour envoyer, Maj+Entrée pour nouvelle ligne)'}
          disabled={isLoading}
          rows={1}
          style={{
            flex: 1,
            minWidth: 0,
            background: 'transparent',
            border: 'none',
            outline: 'none',
            color: 'var(--text-primary)',
            fontFamily: 'var(--font-family)',
            fontSize: 'var(--font-base)',
            lineHeight: '1.5',
            resize: 'none',
            maxHeight: variant === 'welcome' ? '180px' : '140px',
            minHeight: variant === 'welcome' ? '72px' : undefined,
            padding: '6px 0',
          }}
        />
        {isLoading ? (
          <button
            type="button"
            onClick={onStop}
            title="Arrêter la génération"
            style={{
              width: '42px', height: '42px', borderRadius: '12px',
              background: 'var(--danger-bg)', border: '1px solid var(--danger)',
              color: 'var(--danger)', fontSize: '1rem', cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              transition: 'all 0.2s ease', flexShrink: 0,
            }}
            onMouseEnter={(e) => { e.currentTarget.style.transform = 'scale(1.05)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
          >
            ⏹
          </button>
        ) : (
          <button
            type="submit"
            disabled={!input.trim() && attachedImages.length === 0 && attachedFiles.length === 0}
            style={{
              width: '42px', height: '42px', borderRadius: '12px',
              background: (input.trim() || attachedImages.length > 0 || attachedFiles.length > 0) ? 'var(--accent-gradient)' : 'var(--bg-tertiary)',
              border: 'none', color: 'white', fontSize: '1.1rem',
              cursor: (input.trim() || attachedImages.length > 0 || attachedFiles.length > 0) ? 'pointer' : 'not-allowed',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              transition: 'all 0.2s ease', flexShrink: 0,
              boxShadow: (input.trim() || attachedImages.length > 0 || attachedFiles.length > 0) ? 'var(--accent-glow)' : 'none',
            }}
            onMouseEnter={(e) => { if (input.trim() || attachedImages.length > 0 || attachedFiles.length > 0) e.currentTarget.style.transform = 'scale(1.05)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="22" y1="2" x2="11" y2="13" />
              <polygon points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
          </button>
        )}
      </div>
      <p style={{ textAlign: 'center', fontSize: '11px', color: 'var(--text-muted)', marginTop: '8px' }}>
        Marvin agit sur votre PC. Vérifiez toujours les actions sensibles avant de les confirmer.
      </p>
    </form>
  );
}
