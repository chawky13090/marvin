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
  const themeBootstrap = `(function(){try{var allowed=['dark','light','manga','medieval','cyberpunk'];var colors={dark:'#0a0a0d',light:'#f4f6fb',manga:'#fff8fc',medieval:'#17130d',cyberpunk:'#070713'};var value=localStorage.getItem('marvin_theme');var theme=allowed.indexOf(value)>=0?value:'dark';document.documentElement.dataset.theme=theme;document.documentElement.style.colorScheme=(theme==='dark'||theme==='cyberpunk'||theme==='medieval')?'dark':'light';var meta=document.querySelector('meta[name="theme-color"]');if(meta)meta.setAttribute('content',colors[theme]);}catch(e){document.documentElement.dataset.theme='dark';}})();`;
  return (
    <html lang="fr" className={inter.variable} data-theme="dark" data-scroll-behavior="smooth" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: themeBootstrap }} /></head>
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
