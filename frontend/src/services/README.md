# services/

API 클라이언트를 feature별로 분리. `lib/api.ts`보다 도메인 명확.

## 패턴

```typescript
// services/userService.ts
import api from "./api";

export interface User { id: string; name: string; }

export const userService = {
  async list(): Promise<User[]> {
    const { data } = await api.get("/api/users");
    return data;
  },

  async get(id: string): Promise<User> {
    const { data } = await api.get(`/api/users/${id}`);
    return data;
  },
};
```

페이지/컴포넌트에서:

```tsx
import { userService } from "@/services/userService";

const users = await userService.list();
```

## Files

- `api.ts` — axios base instance (JWT, interceptors)
- `<feature>Service.ts` — 각 도메인별 API call

## 왜 lib/api.ts 가 아니라 services/?

- `lib/`은 generic 유틸 (axios 클라이언트, formatter 등)
- `services/`는 도메인 logic이 들어가는 API call 모음
- 큰 프로젝트일수록 services/ 분리가 유지보수에 좋음
