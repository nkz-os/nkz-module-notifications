import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Mail, MessageSquare } from 'lucide-react';
import { Card, Switch, Input, Button, Skeleton } from '@nekazari/ui-kit';
import { useModuleApi, Channels, WeeklyChannels } from '../services/api';

// NKZClient throws `Error("HTTP <status> ...")` (no response object).
const isForbidden = (err: unknown): boolean =>
  err instanceof Error && /^HTTP 403\b/.test(err.message);

export default function ChannelsPanel() {
  const { t } = useTranslation('notifications');
  const api = useModuleApi();

  const [channels, setChannels] = useState<Channels | null>(null);
  const [original, setOriginal] = useState<Channels | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [weekly, setWeekly] = useState<WeeklyChannels | null>(null);
  const [weeklyOriginal, setWeeklyOriginal] = useState<WeeklyChannels | null>(null);
  const [weeklySaving, setWeeklySaving] = useState(false);
  const [banner, setBanner] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const load = async () => {
    try {
      setLoading(true);
      const data = await api.getChannels();
      setChannels(data);
      setOriginal(data);
      try {
        const w = await api.getWeeklyChannels();
        setWeekly(w);
        setWeeklyOriginal(w);
      } catch {
        // The weekly card stays hidden; alert channels remain usable.
        setWeekly(null);
        setWeeklyOriginal(null);
      }
    } catch (err: any) {
      if (isForbidden(err)) {
        setBanner({ type: 'error', message: t('error.forbidden') });
      } else {
        setBanner({ type: 'error', message: t('error.loadFailed') });
      }
    } finally {
      setLoading(false);
    }
  };

  const showBanner = (type: 'success' | 'error', message: string) => {
    setBanner({ type, message });
    if (type === 'success') {
      setTimeout(() => setBanner(null), 3000);
    }
  };

  const saveChannels = async () => {
    if (!channels) return;
    setSaving(true);
    try {
      const saved = await api.putChannels({
        email: channels.email,
        zulip: channels.zulip,
      });
      
      const merged = { ...channels, email: saved.email, zulip: saved.zulip };
      setChannels(merged);
      setOriginal(merged);
      showBanner('success', t('success.saved'));
    } catch (err: any) {
      if (isForbidden(err)) {
        showBanner('error', t('error.forbidden'));
      } else {
        showBanner('error', t('error.saveFailed'));
      }
    } finally {
      setSaving(false);
    }
  };

  const saveWeekly = async () => {
    if (!weekly) return;
    setWeeklySaving(true);
    try {
      const saved = await api.putWeeklyChannels({ email: weekly.email, zulip: weekly.zulip });
      setWeekly(saved);
      setWeeklyOriginal(saved);
      showBanner('success', t('success.saved'));
    } catch (err: any) {
      if (isForbidden(err)) {
        showBanner('error', t('error.forbidden'));
      } else {
        showBanner('error', t('error.saveFailed'));
      }
    } finally {
      setWeeklySaving(false);
    }
  };

  const weeklyChanged =
    !!weekly && !!weeklyOriginal && JSON.stringify(weekly) !== JSON.stringify(weeklyOriginal);

  const hasChanges = () => {
    if (!channels || !original) return false;
    return JSON.stringify(channels) !== JSON.stringify(original);
  };

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton variant="rect" height="120px" className="w-full rounded-xl" />
        <Skeleton variant="rect" height="120px" className="w-full rounded-xl" />
      </div>
    );
  }

  if (!channels) {
    return (
      <div className="p-4 bg-nkz-danger-soft text-nkz-danger-strong border border-nkz-danger/20 rounded-lg">
        {banner?.message || t('error.loadFailed')}
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-2xl">
      {banner && (
        <div
          className={`p-4 rounded-lg border text-sm font-medium ${
            banner.type === 'success'
              ? 'bg-nkz-success-soft text-nkz-success-strong border-nkz-success-soft'
              : 'bg-nkz-danger-soft text-nkz-danger-strong border-nkz-danger/20'
          }`}
        >
          {banner.message}
        </div>
      )}

      {/* Email Card */}
      <Card className="p-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <Mail className="w-5 h-5 text-nkz-text-muted" />
            <div>
              <h3 className="text-base font-semibold text-nkz-text-primary">{t('channels.email.title')}</h3>
              <p className="text-sm text-nkz-text-muted">{t('channels.email.description')}</p>
            </div>
          </div>
          <Switch
            checked={channels.email.enabled}
            onChange={(checked: boolean) => setChannels({ ...channels, email: { ...channels.email, enabled: checked } })}
          />
        </div>
        
        {channels.email.enabled && (
          <div className="mt-4 pt-4 border-t border-nkz-border">
            <label className="block text-sm font-medium text-nkz-text-primary mb-1">
              {t('channels.email.recipients')}
            </label>
            <Input
              value={channels.email.to || ''}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setChannels({ ...channels, email: { ...channels.email, to: e.target.value } })}
              placeholder={t('channels.email.recipientsPlaceholder')}
            />
          </div>
        )}
      </Card>

      {/* Zulip Card */}
      <Card className="p-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <MessageSquare className="w-5 h-5 text-nkz-text-muted" />
            <div>
              <h3 className="text-base font-semibold text-nkz-text-primary">{t('channels.zulip.title')}</h3>
              <p className="text-sm text-nkz-text-muted">{t('channels.zulip.description')}</p>
            </div>
          </div>
          <Switch
            checked={channels.zulip.enabled}
            onChange={(checked: boolean) => setChannels({ ...channels, zulip: { ...channels.zulip, enabled: checked } })}
          />
        </div>

        {channels.zulip.enabled && (
          <div className="mt-4 pt-4 border-t border-nkz-border grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-nkz-text-primary mb-1">
                {t('channels.zulip.stream')}
              </label>
              <Input
                value={channels.zulip.stream || ''}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setChannels({ ...channels, zulip: { ...channels.zulip, stream: e.target.value } })}
                placeholder={t('channels.zulip.streamPlaceholder')}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-nkz-text-primary mb-1">
                {t('channels.zulip.topic')}
              </label>
              <Input
                value={channels.zulip.topic || ''}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setChannels({ ...channels, zulip: { ...channels.zulip, topic: e.target.value } })}
                placeholder={t('channels.zulip.topicPlaceholder')}
              />
            </div>
          </div>
        )}
      </Card>

      {/* Weekly report Card */}
      {weekly && (
        <Card className="p-6">
          <h3 className="text-base font-semibold text-nkz-text-primary">{t('weekly.title')}</h3>
          <p className="text-sm text-nkz-text-muted mb-4">{t('weekly.description')}</p>
          <div className="flex items-center justify-between">
            <span className="text-sm text-nkz-text-primary">{t('weekly.email')}</span>
            <Switch
              checked={weekly.email}
              onChange={(checked: boolean) => setWeekly({ ...weekly, email: checked })}
            />
          </div>
          <div className="flex items-center justify-between mt-3">
            <div>
              <span className="text-sm text-nkz-text-primary">{t('weekly.zulip')}</span>
              {!channels.zulip.enabled && (
                <p className="text-xs text-nkz-text-muted">{t('weekly.zulipOff')}</p>
              )}
            </div>
            <Switch
              checked={weekly.zulip && channels.zulip.enabled}
              disabled={!channels.zulip.enabled}
              onChange={(checked: boolean) => setWeekly({ ...weekly, zulip: checked })}
            />
          </div>
          <div className="flex justify-end mt-4">
            <Button
              variant="primary"
              onClick={saveWeekly}
              disabled={!weeklyChanged || weeklySaving}
            >
              {weeklySaving ? t('saving') : t('weekly.save')}
            </Button>
          </div>
        </Card>
      )}

      <div className="flex items-center justify-between pt-4">
        <span className="text-sm text-nkz-text-muted">{t('moreComingSoon')}</span>
        <Button
          variant="primary"
          onClick={saveChannels}
          disabled={!hasChanges() || saving}
        >
          {saving ? t('saving') : t('save')}
        </Button>
      </div>
    </div>
  );
}
