import { api } from './api';
import type { ChatPreset, ChatRequest, ChatResponse } from '@/types';

export const chatService = {
  presets: () => api.get<ChatPreset[]>('/api/chat/presets').then((r) => r.data),
  ask: (req: ChatRequest) => api.post<ChatResponse>('/api/chat', req).then((r) => r.data),
};
