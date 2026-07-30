'use client';

import { useRef, useEffect } from 'react';
import MessageBubble from './MessageBubble';
import TypingIndicator from './TypingIndicator';
import LivingAvatar from '@/components/avatar/LivingAvatar';
import styles from './ChatWindow.module.css';

const SUGGESTIONS = [
  'Quelle est la météo à Paris cette semaine ?',
  'Quels sont mes rendez-vous cette semaine ?',
  'Traduis ce texte en anglais : Bonjour le monde',
  'Calcule (12 + 4) * 3 / sqrt(9)',
  'Liste mes fichiers sur le Bureau',
  'Quelle heure est-il à Tokyo ?',
  'Génère un QR code pour https://marvin.ai',
  'Calcule le hash SHA256 de "test"',
  "Donne-moi les infos de l'IP 8.8.8.8",
  'Convertis la couleur #3B82F6 en RGB et HSL',
  'Analyse cette URL : https://example.com',
];

export default function ChatWindow({
  messages,
  isLoading,
  onSuggestionClick,
}) {
  const scrollRef = useRef(null);
  const containerRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isLoading]);

  const hasMessages = messages && messages.length > 0;

  return (
    <div className={styles.container}>
      <div className={styles.messagesArea} ref={containerRef}>
        {!hasMessages ? (
          <div className={styles.welcomeContainer}>
            <div style={{ marginBottom: 4 }}>
              <LivingAvatar size={140} thinking={isLoading} />
            </div>
            <h1 className={`${styles.welcomeTitle} holo-text`}>MARVIN</h1>
            <p className={styles.welcomeText}>
              Bonjour ! Je suis <strong style={{ color: 'var(--accent-primary)' }}>Marvin</strong>, votre assistant informatique.
              Plus de 25 ans d&apos;expérience à votre service.
            </p>
            <div className={styles.welcomeSuggestions}>
              {SUGGESTIONS.map((text) => (
                <button
                  key={text}
                  className={styles.suggestion}
                  onClick={() => onSuggestionClick?.(text)}
                >
                  {text}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {messages.map((message, index) => (
              <MessageBubble
                key={message.id || index}
                message={message}
                index={index}
              />
            ))}
            {isLoading && <TypingIndicator />}
          </>
        )}
        <div ref={scrollRef} className={styles.scrollAnchor} />
      </div>
    </div>
  );
}
