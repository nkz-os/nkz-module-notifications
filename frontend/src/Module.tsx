import { defineModule } from '@nekazari/module-kit';
import { lazy } from 'react';
import './i18n';
import pkg from '../package.json';

const ChannelsPage = lazy(() => import('./pages/ChannelsPage'));

export default defineModule({
  id: 'notifications',
  displayName: 'Notifications',
  version: pkg.version,
  hostApiVersion: '^2.0.0',
  description: 'Notifications — Nekazari Platform Module',
  accent: { base: '#3B82F6', soft: '#DBEAFE', strong: '#1D4ED8' },
  icon: 'bell',
  main: ChannelsPage,
  route: '/notifications',
  api: { basePath: '/api/notifications' },
  data: {
    entities: [],
    timeseries: [],
  },
});
