import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      // 'prompt' so the React app decides when the new SW takes over (we
      // show an "Update available" toast). With 'autoUpdate' the SW swaps
      // in the background and the open tab keeps running the old bundle
      // silently — users have to know to hard-reload to see the new code.
      registerType: 'prompt',
      includeAssets: [
        'robots.txt',
        'logo.png',
        'favicon-192.png',
        'maskable_icon_x128.png',
        'maskable_icon_x192.png',
        'maskable_icon_x384.png',
        'maskable_icon_x512.png',
        'dashboard-narrow.png',
        'dashboard-wide.png',
      ],
      manifest: {
        id: '/',
        name: 'Make My Mock',
        short_name: 'MakeMyMock',
        description: 'Smart test series platform — mock, analyse, succeed.',
        lang: 'en',
        dir: 'ltr',
        categories: ['education', 'productivity'],
        theme_color: '#0d9678',
        background_color: '#fbfdf4',
        display: 'standalone',
        // Prefer richer display modes when supported, fall back gracefully.
        display_override: ['standalone', 'minimal-ui'],
        // No native counterpart — tell the OS not to suggest one.
        prefer_related_applications: false,
        orientation: 'portrait',
        start_url: '/',
        scope: '/',
        icons: [
          // Plain logo — used for the browser tab favicon, bookmarks,
          // and the "any" PWA contexts (OSes that don't apply a mask).
          { src: 'logo.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          // Maskable variants for Android adaptive launchers — these
          // PNGs reserve safe-zone padding so the brand survives the
          // circle / squircle / rounded-square crop.
          { src: 'maskable_icon_x128.png', sizes: '128x128', type: 'image/png', purpose: 'maskable' },
          { src: 'maskable_icon_x192.png', sizes: '192x192', type: 'image/png', purpose: 'maskable' },
          { src: 'maskable_icon_x384.png', sizes: '384x384', type: 'image/png', purpose: 'maskable' },
          { src: 'maskable_icon_x512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
        screenshots: [
          {
            src: 'dashboard-narrow.png',
            sizes: '376x813',
            type: 'image/png',
            form_factor: 'narrow',
            label: 'Personalised dashboard with daily progress',
          },
          {
            src: 'dashboard-wide.png',
            sizes: '1905x924',
            type: 'image/png',
            form_factor: 'wide',
            label: 'Personalised dashboard with daily progress',
          },
        ],
        shortcuts: [
          { name: 'Tests',     short_name: 'Tests',     url: '/tests',     icons: [{ src: 'logo.png', sizes: '512x512' }] },
          { name: 'Compete',   short_name: 'Compete',   url: '/compete',   icons: [{ src: 'logo.png', sizes: '512x512' }] },
          { name: 'Analytics', short_name: 'Analytics', url: '/analytics', icons: [{ src: 'logo.png', sizes: '512x512' }] },
          { name: 'SolverX',   short_name: 'SolverX',   url: '/solverx',   icons: [{ src: 'logo.png', sizes: '512x512' }] },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,ico,woff,woff2}'],
        navigateFallbackDenylist: [/^\/api\//],
        runtimeCaching: [
          {
            urlPattern: ({ url }) =>
              url.origin === 'https://fonts.googleapis.com',
            handler: 'StaleWhileRevalidate',
            options: { cacheName: 'google-fonts-stylesheets' },
          },
          {
            urlPattern: ({ url }) =>
              url.origin === 'https://fonts.gstatic.com',
            handler: 'CacheFirst',
            options: {
              cacheName: 'google-fonts-webfonts',
              expiration: {
                maxEntries: 30,
                maxAgeSeconds: 60 * 60 * 24 * 365,
              },
            },
          },
        ],
      },
    }),
  ],

  server: {
    port: 3000,
    open: true,
  },

  preview: {
    host: '0.0.0.0',
    port: Number(process.env.PORT) || 4173,
    allowedHosts: ['makemymock-client.onrender.com'],
  },

  test: {
    globals: true,
    environment: 'jsdom',
  },
});