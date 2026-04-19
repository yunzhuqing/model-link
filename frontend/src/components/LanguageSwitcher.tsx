import { useTranslation } from 'react-i18next';
import { Globe } from 'lucide-react';

const LanguageSwitcher = () => {
  const { i18n, t } = useTranslation();

  const toggleLanguage = () => {
    const newLang = i18n.language === 'zh' ? 'en' : 'zh';
    i18n.changeLanguage(newLang);
    localStorage.setItem('i18nextLng', newLang);
  };

  return (
    <button
      onClick={toggleLanguage}
      className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg transition-colors flex items-center space-x-1"
      title={t('lang.switch')}
    >
      <Globe className="w-5 h-5" />
      <span className="text-xs font-medium">{i18n.language === 'zh' ? 'EN' : '中'}</span>
    </button>
  );
};

export default LanguageSwitcher;