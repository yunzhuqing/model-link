import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Save, Activity } from 'lucide-react';
import client from '../api/client';
import type { MonitoringConfig as MonitoringConfigType } from '../api/client';

interface Props {
  groupId: number;
  monitoringConfig: MonitoringConfigType | null | undefined;
}

const TRACER_TYPES: { value: string; label: string }[] = [
  { value: 'langfuse', label: 'Langfuse' },
];

const DEFAULT_LANGFUSE_ENDPOINT = 'https://cloud.langfuse.com';

export default function MonitoringConfig({ groupId, monitoringConfig }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const [enabled, setEnabled] = useState(false);
  const [type, setType] = useState('langfuse');
  const [endpoint, setEndpoint] = useState(DEFAULT_LANGFUSE_ENDPOINT);
  const [publicKey, setPublicKey] = useState('');
  const [secretKey, setSecretKey] = useState('');

  useEffect(() => {
    if (monitoringConfig) {
      setEnabled(true);
      setType(monitoringConfig.type || 'langfuse');
      setEndpoint(monitoringConfig.endpoint || DEFAULT_LANGFUSE_ENDPOINT);
      setPublicKey(monitoringConfig.public_key || '');
      setSecretKey('');
    } else {
      setEnabled(false);
      setType('langfuse');
      setEndpoint(DEFAULT_LANGFUSE_ENDPOINT);
      setPublicKey('');
      setSecretKey('');
    }
  }, [monitoringConfig]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!enabled) {
        const resp = await client.put(`/api/groups/${groupId}`, {
          monitoring_config: null,
        });
        return resp.data;
      }

      const config: Record<string, string> = {
        type,
        endpoint: endpoint || DEFAULT_LANGFUSE_ENDPOINT,
        public_key: publicKey,
      };
      if (secretKey) {
        config.secret_key = secretKey;
      }

      const resp = await client.put(`/api/groups/${groupId}`, {
        monitoring_config: config,
      });
      return resp.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['group', groupId.toString()] });
    },
  });

  const hasExistingSecret = !!(monitoringConfig && monitoringConfig.secret_key);

  return (
    <div className="max-w-2xl">
      <div className="flex items-center gap-3 mb-6">
        <Activity className="w-5 h-5 text-cyan-600" />
        <h2 className="text-lg font-semibold text-slate-800">
          {t('monitoring.title', '监控配置')}
        </h2>
      </div>

      <div className="bg-white rounded-2xl border border-slate-200 p-6 space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-medium text-slate-700">
              {t('monitoring.enable', '启用监控')}
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              {t('monitoring.enableHint', '启用后每次 API 调用都会记录到监控平台')}
            </p>
          </div>
          <button
            type="button"
            onClick={() => setEnabled(!enabled)}
            className={`relative w-11 h-6 rounded-full transition-colors ${
              enabled ? 'bg-cyan-600' : 'bg-slate-300'
            }`}
          >
            <span
              className={`absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${
                enabled ? 'translate-x-[22px]' : 'translate-x-0.5'
              }`}
            />
          </button>
        </div>

        {enabled && (
          <>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-2">
                {t('monitoring.type', '监控类型')}
              </label>
              <select
                className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 focus:bg-white focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/20 transition-all"
                value={type}
                onChange={(e) => setType(e.target.value)}
              >
                {TRACER_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>

            {type === 'langfuse' && (
              <>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">
                    {t('monitoring.endpoint', 'Endpoint')}
                  </label>
                  <input
                    type="url"
                    placeholder={DEFAULT_LANGFUSE_ENDPOINT}
                    className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/20 transition-all"
                    value={endpoint}
                    onChange={(e) => setEndpoint(e.target.value)}
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">
                    {t('monitoring.publicKey', 'Public Key')}
                  </label>
                  <input
                    type="password"
                    placeholder="pk-lf-..."
                    className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/20 transition-all"
                    value={publicKey}
                    onChange={(e) => setPublicKey(e.target.value)}
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">
                    {t('monitoring.secretKey', 'Secret Key')}
                  </label>
                  <input
                    type="password"
                    placeholder={
                      hasExistingSecret
                        ? t('monitoring.secretKeyPlaceholder', '留空则保持不变')
                        : 'sk-lf-...'
                    }
                    className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/20 transition-all"
                    value={secretKey}
                    onChange={(e) => setSecretKey(e.target.value)}
                  />
                  {hasExistingSecret && (
                    <p className="text-xs text-slate-400 mt-1">
                      {t('monitoring.secretKeyHint', '留空则保留已有密钥')}
                    </p>
                  )}
                </div>
              </>
            )}

            <div className="pt-2">
              <button
                onClick={() => saveMutation.mutate()}
                disabled={saveMutation.isPending}
                className="flex items-center gap-2 px-6 py-2.5 bg-cyan-600 text-white rounded-xl hover:bg-cyan-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-sm font-medium"
              >
                <Save className="w-4 h-4" />
                {saveMutation.isPending
                  ? t('monitoring.saving', '保存中...')
                  : t('monitoring.save', '保存配置')}
              </button>
              {saveMutation.isSuccess && (
                <span className="ml-3 text-sm text-green-600">
                  {t('monitoring.saved', '已保存')}
                </span>
              )}
              {saveMutation.isError && (
                <span className="ml-3 text-sm text-red-600">
                  {t('monitoring.saveError', '保存失败')}
                </span>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
