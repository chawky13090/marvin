import { Inter } from 'next/font/google';
import './globals.css';
import AppFrame from '@/components/layout/AppFrame';
import TopLoadingBar from '@/components/ui/TopLoadingBar';
import CommandPalette from '@/components/ui/CommandPalette';
import { ToastProvider } from '@/components/ui/Toast';
import { ChatProvider } from '@/lib/contexts/ChatContext';
import { NavigationProvider } from '@/lib/contexts/NavigationContext';
import LanAccessGate from '@/components/security/LanAccessGate';

// Forcer le rendu dynamique pour éviter les erreurs SSR avec les composants client
export const dynamic = 'force-dynamic';

const inter = Inter({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-inter',
});

export const metadata = {
  title: 'Marvin — Assistance Informatique',
  description: 'Marvin, votre assistant IA. Plus de 25 ans d\'expérience en assistance informatique. Propulsé par Ollama.',
  keywords: 'Marvin, assistant IA, assistance informatique, fichiers, tâches, Ollama',
};

// Indispensable pour le rendu mobile (sinon le téléphone affiche en « mode bureau »).
export const viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 5,
  themeColor: '#0a0a0d',
};

export default function RootLayout({ children }) {
  return (
    <html lang="fr" className={inter.variable}>
      <body>
        <LanAccessGate>
        {/* ChatProvider lives at the layout level → chat state survives page navigation.
            User can start a conversation, navigate to /outils or /files, and the
            stream keeps running in the background. */}
        <ToastProvider>
          <ChatProvider>
            <NavigationProvider>
              <TopLoadingBar />
              <CommandPalette />
              <AppFrame>{children}</AppFrame>
            </NavigationProvider>
          </ChatProvider>
        </ToastProvider>
        </LanAccessGate>
      </body>
    </html>
  );
}
