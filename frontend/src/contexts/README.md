# contexts/

전역 상태 (React Context). 필요할 때만 사용 (대부분 props로 충분).

## 사용 시기

- **JWT 인증 상태** (모든 페이지에서 user 정보 필요)
- **WebSocket 연결** (chat / realtime)
- **테마 / 언어 / global UI 상태**

## 패턴

```tsx
// contexts/AuthContext.tsx
"use client";
import { createContext, useContext, useState, ReactNode } from "react";

interface AuthState {
  user: User | null;
  login: (token: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  // ...
  return <AuthContext.Provider value={{ user, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
```

`app/layout.tsx`에서 wrap:

```tsx
<AuthProvider>
  {children}
</AuthProvider>
```

## 주의

- Context가 많아지면 provider hell 됨 — `app/providers.tsx`로 묶기
- 큰 전역 상태 필요하면 zustand/jotai 고려
