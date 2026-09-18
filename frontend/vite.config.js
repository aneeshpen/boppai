import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// The Tailwind Vite plugin is the v4 install path
// (https://tailwindcss.com/docs/installation/using-vite).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    allowedHosts: ['sublime-harmonica-untagged.ngrok-free.dev'],
  },
});
