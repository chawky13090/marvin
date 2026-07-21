'use client';

import { usePathname } from 'next/navigation';
import Sidebar from '@/components/sidebar/Sidebar';

export default function AppFrame({ children }) {
  const pathname = usePathname();
  const avatarMode = pathname === '/avatar';

  if (avatarMode) return <main className="avatar-main-content">{children}</main>;

  return (
    <div className="app-layout">
      <Sidebar />
      <main className="main-content">{children}</main>
    </div>
  );
}
