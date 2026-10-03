import { NKZClient, useAuth } from '@nekazari/sdk';

const API_BASE = (import.meta as any).env?.VITE_API_URL || 'https://your-api-domain';

export interface EmailChannel {
  enabled: boolean;
  to?: string;
}

export interface PushChannel {
  enabled: boolean;
}

export interface ZulipChannel {
  enabled: boolean;
  stream?: string;
  topic?: string;
}

export interface WebhookChannel {
  enabled: boolean;
  targets?: unknown[];
}

export interface TelegramChannel {
  enabled: boolean;
}

export interface Channels {
  email: EmailChannel;
  push: PushChannel;
  zulip: ZulipChannel;
  webhook: WebhookChannel;
  telegram: TelegramChannel;
}

export function useModuleApi() {
  const { getToken, getTenantId } = useAuth();

  const client = new NKZClient({
    baseUrl: `${API_BASE}/api/notifications`,
    getToken,
    getTenantId,
  });

  return {
    getChannels: () => client.get<Channels>('/channels'),
    putChannels: (d: Partial<Channels>) => client.put<Channels>('/channels', d),
  };
}
