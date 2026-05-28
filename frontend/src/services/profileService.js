import api from './axiosInstance';

export const profileService = {
  async createProfile(payload) {
    const { data } = await api.post('/profile/create', payload);
    return data;
  },

  async getMyProfile() {
    const { data } = await api.get('/profile/me');
    return data;
  },

  async updateProfile(partial) {
    const { data } = await api.put('/profile/update', partial);
    return data;
  },

  async completeTour(slug) {
    const { data } = await api.post(
      `/profile/tours/${encodeURIComponent(slug)}/complete`
    );
    return data;
  },
};
