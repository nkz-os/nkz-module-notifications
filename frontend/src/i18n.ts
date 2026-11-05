import { i18n } from '@nekazari/sdk';
import en from './locales/en.json';
import es from './locales/es.json';
// ASSUMPTION: eu wording is ours — confirm before shipping
import eu from './locales/eu.json';

const NAMESPACE = 'notifications';

export function registerModuleTranslations(): void {
  if (!i18n || typeof (i18n as any).addResourceBundle !== 'function') return;
  i18n.addResourceBundle('en', NAMESPACE, en, true, true);
  i18n.addResourceBundle('es', NAMESPACE, es, true, true);
  i18n.addResourceBundle('eu', NAMESPACE, eu, true, true);
}

registerModuleTranslations();
