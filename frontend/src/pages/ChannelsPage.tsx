import React from 'react';
import { useTranslation } from 'react-i18next';
import ChannelsPanel from '../components/ChannelsPanel';

export default function ChannelsPage() {
  const { t } = useTranslation('notifications');

  return (
    <div className="p-6">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-nkz-text-primary">{t('page.title')}</h1>
        <p className="text-nkz-text-muted mt-2">{t('page.description')}</p>
      </div>
      <ChannelsPanel />
    </div>
  );
}
