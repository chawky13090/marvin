'use client';

import { useRouter } from 'next/navigation';
import { BookOpen, Code2, FileText, Presentation, Search, Users } from 'lucide-react';
import LivingAvatar from '@/components/avatar/LivingAvatar';
import ChatInput from '@/components/chat/ChatInput';
import styles from './QuietWelcome.module.css';

const INTENTS = [
  { id: 'research', label: 'Recherche approfondie', icon: Search, prompt: 'Effectue une recherche approfondie et vérifiable sur ' },
  { id: 'council', label: 'Council', icon: Users, prompt: 'Utilise le Council pour analyser ce problème complexe : ' },
  { id: 'code', label: 'Produire du code', icon: Code2, href: '/code' },
  { id: 'document', label: 'Créer un document', icon: FileText, href: '/documents' },
  { id: 'slides', label: 'Créer une présentation', icon: Presentation, prompt: 'Crée une présentation professionnelle sur ' },
  { id: 'knowledge', label: 'Documentation technique', icon: BookOpen, href: '/docs' },
];

export default function QuietWelcome(props) {
  const router = useRouter();

  function chooseIntent(intent) {
    if (intent.href) {
      router.push(intent.href);
      return;
    }
    props.setInput(intent.prompt);
    requestAnimationFrame(() => {
      document.querySelector('[data-marvin-composer] textarea')?.focus();
    });
  }

  return (
    <section className={styles.stage} aria-label="Nouvelle conversation">
      <div className={styles.content}>
        <div className={styles.avatar}>
          <LivingAvatar size={108} thinking={props.isLoading} />
        </div>
        <p className={styles.eyebrow}>Votre espace de travail</p>
        <h2 className={styles.title}>{props.greeting}.</h2>
        <p className={styles.subtitle}>Sur quoi travaillons-nous aujourd’hui&nbsp;?</p>
        <div className={styles.composer} data-marvin-composer>
          <ChatInput variant="welcome" {...props} />
        </div>
        <nav className={styles.intentBar} aria-label="Modes de travail suggérés">
          {INTENTS.map((intent) => {
            const Icon = intent.icon;
            return (
              <button key={intent.id} type="button" className={styles.intent} onClick={() => chooseIntent(intent)}>
                <Icon size={15} aria-hidden="true" />
                {intent.label}
              </button>
            );
          })}
        </nav>
        <p className={styles.hint}>Tapez / pour les commandes et compétences · Ctrl+K pour tout rechercher</p>
      </div>
    </section>
  );
}
