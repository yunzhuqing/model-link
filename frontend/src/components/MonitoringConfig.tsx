import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Save, Activity, Plus, Trash2 } from 'lucide-react';
import client from '../api/client';
import type { MonitoringConfig as MonitoringConfigType } from '../api/client';

interface Props {
  groupId: number;
  monitoringConfigs: MonitoringConfigType[] | null | undefined;
}

interface ConfigEntry {
  id: number;
  type: string;
  region: string;
  endpoint: string;
  publicKey: string;
  secretKey: string;
  hasExistingSecret: boolean;
}

const TRACER_TYPES: { value: string; label: string }[] = [
  { value: 'langfuse', label: 'Langfuse' },
];

const REGIONS: { value: string; label: string; endpoint: string }[] = [
  { value: 'cn', label: '中国', endpoint: 'https://cloud.langfuse.com.cn' },
  { value: 'us', label: 'US', endpoint: 'https://cloud.langfuse.com' },
  { value: 'eu', label: 'EU', endpoint: 'https://cloud.langfuse.eu' },
  { value: 'custom', label: '自定义', endpoint: '' },
];

const DEFAULT_LANGFUSE_ENDPOINT = 'https://cloud.langfuse.com.cn';

let _nextId = 0;

function makeEntry(overrides: Partial<ConfigEntry> = {}): ConfigEntry {
  return {
    id: ++_nextId,
    type: 'langfuse',
    region: 'cn',
    endpoint: DEFAULT_LANGFUSE_ENDPOINT,
    publicKey: '',
    secretKey: '',
    hasExistingSecret: false,
    ...overrides,
  };
}

function entriesFromConfigs(configs: MonitoringConfigType[] | null | undefined): ConfigEntry[] {
  if (!configs || configs.length === 0) {
    return [makeEntry()];
  }
  return configs.map((mc) =>
    makeEntry({
      type: mc.type || 'langfuse',
      region: mc.region || 'cn',
      endpoint: mc.endpoint || DEFAULT_LANGFUSE_ENDPOINT,
      publicKey: mc.public_key || '',
      hasExistingSecret: !!mc.secret_key,
    })
  );
}

export default function MonitoringConfig({ groupId, monitoringConfigs }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const [enabled, setEnabled] = useState(false);
  const [entries, setEntries] = useState<ConfigEntry[]>(() => [makeEntry()]);

  useEffect(() => {
    if (monitoringConfigs && monitoringConfigs.length > 0) {
      setEnabled(true);
      setEntries(entriesFromConfigs(monitoringConfigs));
    } else {
      setEnabled(false);
      setEntries([makeEntry()]);
    }
  }, [monitoringConfigs]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!enabled) {
        const resp = await client.put(`/api/groups/${groupId}`, {
          monitoring_config: null,
        });
        return resp.data;
      }

      const configs = entries.map((e) => {
        const config: Record<string, string> = {
          type: e.type,
          region: e.region,
          endpoint: e.endpoint || DEFAULT_LANGFUSE_ENDPOINT,
          public_key: e.publicKey,
        };
        if (e.secretKey) {
          config.secret_key = e.secretKey;
        }
        return config;
      });

      const resp = await client.put(`/api/groups/${groupId}`, {
        monitoring_config: configs,
      });
      return resp.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['group', groupId.toString()] });
    },
  });

  const updateEntry = (id: number, patch: Partial<ConfigEntry>) => {
    setEntries((prev) => prev.map((e) => (e.id === id ? { ...e, ...patch } : e)));
  };

  const addEntry = () => {
    setEntries((prev) => [...prev, makeEntry()]);
  };

  const removeEntry = (id: number) => {
    setEntries((prev) => {
      if (prev.length <= 1) return prev;
      return prev.filter((e) => e.id !== id);
    });
  };

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
            {entries.map((entry, idx) => (
              <div
                key={entry.id}
                className="border border-slate-200 rounded-xl p-5 space-y-4 bg-slate-50/50"
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-slate-600">
                    {t('monitoring.configNumber', '配置 {{n}}', { n: idx + 1 })}
                  </span>
                  {entries.length > 1 && (
                    <button
                      type="button"
                      onClick={() => removeEntry(entry.id)}
                      className="p-1 text-slate-400 hover:text-red-500 transition-colors"
                      title={t('monitoring.removeRegion', '移除')}
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  )}
                </div>

                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">
                    {t('monitoring.type', '监控类型')}
                  </label>
                  <select
                    className="w-full p-3 bg-white border border-slate-200 rounded-xl text-slate-800 focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/20 transition-all"
                    value={entry.type}
                    onChange={(e) => updateEntry(entry.id, { type: e.target.value })}
                  >
                    {TRACER_TYPES.map((tr) => (
                      <option key={tr.value} value={tr.value}>
                        {tr.label}
                      </option>
                    ))}
                  </select>
                </div>

                {entry.type === 'langfuse' && (
                  <>
                    <div>
                      <label className="block text-sm font-medium text-slate-700 mb-2">
                        {t('monitoring.region', 'Region')}
                      </label>
                      <select
                        className="w-full p-3 bg-white border border-slate-200 rounded-xl text-slate-800 focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/20 transition-all"
                        value={entry.region}
                        onChange={(e) => {
                          const newRegion = e.target.value;
                          const regionConfig = REGIONS.find((r) => r.value === newRegion);
                          updateEntry(entry.id, {
                            region: newRegion,
                            endpoint: regionConfig?.endpoint ?? entry.endpoint,
                          });
                        }}
                      >
                        {REGIONS.map((r) => (
                          <option key={r.value} value={r.value}>
                            {r.label}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-slate-700 mb-2">
                        {t('monitoring.endpoint', 'Endpoint')}
                      </label>
                      <input
                        type="url"
                        placeholder={DEFAULT_LANGFUSE_ENDPOINT}
                        className="w-full p-3 bg-white border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/20 transition-all"
                        value={entry.endpoint}
                        onChange={(e) => updateEntry(entry.id, { endpoint: e.target.value })}
                      />
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-slate-700 mb-2">
                        {t('monitoring.publicKey', 'Public Key')}
                      </label>
                      <input
                        type="password"
                        placeholder="pk-lf-..."
                        className="w-full p-3 bg-white border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/20 transition-all"
                        value={entry.publicKey}
                        onChange={(e) => updateEntry(entry.id, { publicKey: e.target.value })}
                      />
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-slate-700 mb-2">
                        {t('monitoring.secretKey', 'Secret Key')}
                      </label>
                      <input
                        type="password"
                        placeholder={
                          entry.hasExistingSecret
                            ? t('monitoring.secretKeyPlaceholder', '留空则保持不变')
                            : 'sk-lf-...'
                        }
                        className="w-full p-3 bg-white border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/20 transition-all"
                        value={entry.secretKey}
                        onChange={(e) => updateEntry(entry.id, { secretKey: e.target.value })}
                      />
                      {entry.hasExistingSecret && (
                        <p className="text-xs text-slate-400 mt-1">
                          {t('monitoring.secretKeyHint', '留空则保留已有密钥')}
                        </p>
                      )}
                    </div>
                  </>
                )}
              </div>
            ))}

            <button
              type="button"
              onClick={addEntry}
              className="flex items-center gap-2 w-full p-3 border-2 border-dashed border-slate-300 rounded-xl text-slate-500 hover:border-cyan-400 hover:text-cyan-600 transition-colors text-sm"
            >
              <Plus className="w-4 h-4" />
              {t('monitoring.addRegion', '添加区域')}
            </button>

            <div className="pt-2 flex items-center gap-3">
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
                <span className="text-sm text-green-600">
                  {t('monitoring.saved', '已保存')}
                </span>
              )}
              {saveMutation.isError && (
                <span className="text-sm text-red-600">
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