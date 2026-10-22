import { defineConfig } from 'vite';
import { nkzModulePreset } from '@nekazari/module-builder';
import path from 'path';

const MODULE_ID = 'notifications';

export default defineConfig(nkzModulePreset({
  moduleId: MODULE_ID,
  viteConfig: {
    resolve: {
      alias: { '@': path.resolve(__dirname, './src') },
    },
    server: {
      port: 5010,
      proxy: {
        '/api': {
          target: process.env.VITE_PROXY_TARGET || 'http://localhost:8000',
          changeOrigin: true,
          secure: process.env.VITE_PROXY_TARGET?.startsWith('https') ?? false,
        },
      },
    },
  },
}));
