'use client';

import { usePathname } from 'next/navigation';
import Sidebar from '@/components/sidebar/Sidebar';
import NavigationModeControl from '@/components/layout/NavigationModeControl';
import { useNavigationLayout } from '@/lib/contexts/NavigationContext';

export default function AppFrame({ children }) {
  const pathname = usePathname();
  const avatarMode = pathname === '/avatar';
  const navigation = useNavigationLayout();

  if (avatarMode) return <main className="avatar-main-content">{children}</main>;

  return (
    <div className={`app-layout app-layout--nav-${navigation.mode}`}>
      {navigation.mode !== 'focus' && (
        <Sidebar
          displayMode={navigation.mode}
          onRequestFull={() => navigation.openOverlay()}
        />
      )}
      {navigation.overlayOpen && (
        <Sidebar
          displayMode="overlay"
          onRequestClose={navigation.closeOverlay}
        />
      )}
      {(navigation.mode === 'focus' || navigation.mode === 'classic') && <NavigationModeControl />}
      <main className={`main-content main-content--nav-${navigation.mode}`}>{children}</main>
    </div>
  );
}
