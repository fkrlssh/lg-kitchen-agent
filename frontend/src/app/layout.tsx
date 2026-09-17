import type { Metadata } from 'next';
import localFont from 'next/font/local';
import './globals.css';
import Sidebar from '@/components/layout/Sidebar';
import GlobalAssistant from '@/components/chat/GlobalAssistant';

// Pretendard 셀프호스팅 (내부망 전용 — 외부 CDN 도달 불가) + FOUT 제거
const pretendard = localFont({
  src: './fonts/PretendardVariable.woff2',
  display: 'swap',
  weight: '45 920',
  variable: '--font-pretendard',
});

export const metadata: Metadata = {
  title: '키친솔루션 한계돌파 플랫폼',
  description: '키친솔루션 한계돌파 플랫폼 — 경영 성과 금액 실시간 모니터링.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko" className={pretendard.variable}>
      <body>
        <div className="min-h-screen flex">
          <Sidebar />
          <main className="flex-1 ml-60 min-h-screen min-w-0">
            {children}
          </main>
        </div>
        <GlobalAssistant />
      </body>
    </html>
  );
}
