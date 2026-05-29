import api from './axiosInstance';
import { tokenStorage } from '../utils/token';
import { WS_BASE_URL } from '../config';

// Builds the battle WebSocket URL. When `inviteCode` is set, both sides
// of a battle-a-friend session connect with the same code and the
// backend matchmaker pairs them privately (bypassing the public queue).
function buildWsUrl(inviteCode) {
  const token = tokenStorage.getAccessToken();
  let url = `${WS_BASE_URL}/battle/ws?token=${encodeURIComponent(token || '')}`;
  if (inviteCode) {
    url += `&invite_code=${encodeURIComponent(inviteCode)}`;
  }
  return url;
}

// The shareable invite URL the inviter copies into WhatsApp / chat /
// wherever. Frontend-only — the backend just returns the code; the URL
// is composed here so the backend stays decoupled from the deploy origin.
export function inviteUrlFor(code) {
  if (typeof window === 'undefined') return '';
  return `${window.location.origin}/battle/join/${encodeURIComponent(code)}`;
}

export const battleService = {
  openSocket(inviteCode) {
    return new WebSocket(buildWsUrl(inviteCode));
  },

  async fetchHistory() {
    const { data } = await api.get('/battle/history');
    return data;
  },

  async fetchBattle(battleId) {
    const { data } = await api.get(`/battle/${battleId}`);
    return data;
  },

  // ---- Battle-a-friend invites ----

  async createInvite() {
    const { data } = await api.post('/battle/invites');
    return data; // { code, expires_at }
  },

  async getInvite(code) {
    const { data } = await api.get(`/battle/invites/${encodeURIComponent(code)}`);
    return data; // { code, inviter_username, status, expires_at, is_own_invite }
  },

  async precheckInvite(code) {
    const { data } = await api.post(`/battle/invites/${encodeURIComponent(code)}/precheck`);
    return data; // { code, ready }
  },

  async cancelInvite(code) {
    await api.delete(`/battle/invites/${encodeURIComponent(code)}`);
  },
};
