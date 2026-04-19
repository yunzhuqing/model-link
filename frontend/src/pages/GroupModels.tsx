/**
 * GroupModels — 分组可用模型列表
 *
 * 聚合该分组下所有供应商的模型，按模型名称/别名分组展示，
 * 一个模型可能由多个供应商提供。
 */
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import client from '../api/client';
import {
  Cpu, Database, Search, Check, X,
  Image, Video, Mic, FileText, Globe, Brain, Layers
} from 'lucide-react';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface ModelItem {
  id: number;
  provider_id: number;
  name: string;
  alias: string | null;
  context_size: number;
  input_size: number;
  output_size: number;
  input_price: number;
  output_price: number;
  currency: string;
  discount: number;
  is_active: boolean;
  is_retired: boolean;
  support_image: boolean;
  support_audio: boolean;
  support_video: boolean;
  support_file: boolean;
  support_web_search: boolean;
  support_thinking: boolean;
  support_embedding: boolean;
}

interface ProviderData {
  id: number;
  name: string;
  type: string;
  is_active: boolean;
  models: ModelItem[];
}

/** Aggregated model: one logical model that may have multiple provider instances */
interface AggregatedModel {
  /** Display name: alias or name */
  displayName: string;
  /** All provider instances providing this model */
  instances: {
    model: ModelItem;
    providerName: string;
    providerType: string;
    providerActive: boolean;
  }[];
}

/* ── Helpers ────────────────────────────────────────────────────────────── */

function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(0) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(0) + 'K';
  return String(n);
}

function fmtPrice(n: number, currency: string): string {
  const sym = currency?.toUpperCase() === 'CNY' ? '¥' : '$';
  if (n === 0) return `${sym}0`;
  if (n < 0.01) return `${sym}${n.toFixed(4)}`;
  return `${sym}${n.toFixed(2)}`;
}

const FeatureBadge = ({ active, icon: Icon, label }: { active: boolean; icon: React.ElementType; label: string }) => {
  if (!active) return null;
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs bg-slate-100 text-slate-600" title={label}>
      <Icon className="w-3 h-3" />
    </span>
  );
};

/* ── Component ─────────────────────────────────────────────────────────── */

export default function GroupModels({ groupId }: { groupId: number }) {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');

  const { data: providers, isLoading } = useQuery<ProviderData[]>({
    queryKey: ['providers', 'group', groupId],
    queryFn: async () => {
      const res = await client.get('/api/providers/', { params: { group_id: groupId } });
      return res.data;
    },
  });

  // Aggregate models across providers
  const aggregated = useMemo(() => {
    if (!providers) return [];

    const map = new Map<string, AggregatedModel>();

    for (const prov of providers) {
      for (const model of prov.models) {
        // Use alias as the key if available, otherwise name
        const key = (model.alias || model.name).toLowerCase();
        const displayName = model.alias || model.name;

        if (!map.has(key)) {
          map.set(key, { displayName, instances: [] });
        }
        map.get(key)!.instances.push({
          model,
          providerName: prov.name,
          providerType: prov.type,
          providerActive: prov.is_active,
        });
      }
    }

    return Array.from(map.values()).sort((a, b) => a.displayName.localeCompare(b.displayName));
  }, [providers]);

  // Filter by search
  const filtered = useMemo(() => {
    if (!search.trim()) return aggregated;
    const q = search.toLowerCase();
    return aggregated.filter(m =>
      m.displayName.toLowerCase().includes(q) ||
      m.instances.some(inst => inst.model.name.toLowerCase().includes(q) || inst.providerName.toLowerCase().includes(q))
    );
  }, [aggregated, search]);

  const totalModels = aggregated.length;
  const activeModels = aggregated.filter(m => m.instances.some(i => i.model.is_active && i.providerActive)).length;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="w-10 h-10 bg-indigo-100 rounded-lg flex items-center justify-center">
            <Cpu className="w-5 h-5 text-indigo-600" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-slate-800">{t('group.tabModels')}</h2>
            <p className="text-sm text-slate-500">
              {t('group.groupDetail.activeModels', { active: activeModels, total: totalModels })}
            </p>
          </div>
        </div>
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            placeholder={t('group.groupDetail.searchPlaceholder')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 pr-3 py-2 text-sm border border-slate-200 rounded-lg w-64 focus:outline-none focus:ring-2 focus:ring-indigo-300"
          />
        </div>
      </div>

      {isLoading ? (
        <div className="text-center py-16 text-slate-400">{t('group.groupDetail.loading')}</div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-16 text-slate-400">
          <Cpu className="w-12 h-12 mx-auto mb-3 text-slate-200" />
          <p>{search ? t('group.groupDetail.noMatchingModels') : t('group.groupDetail.noModels')}</p>
        </div>
      ) : (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200">
                  <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500">{t('group.groupDetail.modelName')}</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500">{t('group.groupDetail.provider')}</th>
                  <th className="px-4 py-3 text-center text-xs font-semibold text-slate-500">{t('group.groupDetail.context')}</th>
                  <th className="px-4 py-3 text-right text-xs font-semibold text-slate-500">{t('group.groupDetail.inputPrice')}</th>
                  <th className="px-4 py-3 text-right text-xs font-semibold text-slate-500">{t('group.groupDetail.outputPrice')}</th>
                  <th className="px-4 py-3 text-center text-xs font-semibold text-slate-500">{t('group.groupDetail.capabilities')}</th>
                  <th className="px-4 py-3 text-center text-xs font-semibold text-slate-500">{t('group.groupDetail.status')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filtered.map((agg) => {
                  // If only one provider, show as single row
                  if (agg.instances.length === 1) {
                    const inst = agg.instances[0];
                    const m = inst.model;
                    const active = m.is_active && inst.providerActive;
                    return (
                      <tr key={`${m.id}`} className={`hover:bg-slate-50 ${!active ? 'opacity-50' : ''}`}>
                        <td className="px-4 py-3">
                          <div>
                            <span className="font-medium text-slate-800">{agg.displayName}</span>
                            {m.alias && m.alias !== m.name && (
                              <span className="ml-2 text-xs text-slate-400">{m.name}</span>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <span className="inline-flex items-center gap-1 text-xs text-slate-600">
                            <Database className="w-3 h-3 text-slate-400" />
                            {inst.providerName}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-center text-xs text-slate-600 font-mono">{fmtNum(m.context_size)}</td>
                        <td className="px-4 py-3 text-right text-xs text-slate-600 font-mono">
                          {fmtPrice(m.input_price, m.currency)}/M
                        </td>
                        <td className="px-4 py-3 text-right text-xs text-slate-600 font-mono">
                          {fmtPrice(m.output_price, m.currency)}/M
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center justify-center gap-1 flex-wrap">
                            <FeatureBadge active={m.support_image} icon={Image} label={t('group.groupDetail.featureImage')} />
                            <FeatureBadge active={m.support_video} icon={Video} label={t('group.groupDetail.featureVideo')} />
                            <FeatureBadge active={m.support_audio} icon={Mic} label={t('group.groupDetail.featureAudio')} />
                            <FeatureBadge active={m.support_file} icon={FileText} label={t('group.groupDetail.featureFile')} />
                            <FeatureBadge active={m.support_web_search} icon={Globe} label={t('group.groupDetail.featureWebSearch')} />
                            <FeatureBadge active={m.support_thinking} icon={Brain} label={t('group.groupDetail.featureThinking')} />
                            <FeatureBadge active={m.support_embedding} icon={Layers} label={t('group.groupDetail.featureEmbedding')} />
                          </div>
                        </td>
                        <td className="px-4 py-3 text-center">
                          {active ? (
                            <span className="inline-flex items-center gap-1 text-xs text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-full">
                              <Check className="w-3 h-3" /> {t('group.groupDetail.active')}
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-xs text-slate-400 bg-slate-100 px-2 py-0.5 rounded-full">
                              <X className="w-3 h-3" /> {t('group.groupDetail.disabled')}
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  }

                  // Multiple providers: show grouped rows
                  return agg.instances.map((inst, idx) => {
                    const m = inst.model;
                    const active = m.is_active && inst.providerActive;
                    return (
                      <tr key={`${m.id}`} className={`hover:bg-slate-50 ${!active ? 'opacity-50' : ''} ${idx > 0 ? 'border-t-0' : ''}`}>
                        {idx === 0 ? (
                          <td className="px-4 py-3" rowSpan={agg.instances.length}>
                            <div>
                              <span className="font-medium text-slate-800">{agg.displayName}</span>
                              <span className="ml-2 text-xs text-indigo-500 bg-indigo-50 px-1.5 py-0.5 rounded">
                                {t('group.groupDetail.providersCount', { count: agg.instances.length })}
                              </span>
                            </div>
                          </td>
                        ) : null}
                        <td className="px-4 py-3">
                          <span className="inline-flex items-center gap-1 text-xs text-slate-600">
                            <Database className="w-3 h-3 text-slate-400" />
                            {inst.providerName}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-center text-xs text-slate-600 font-mono">{fmtNum(m.context_size)}</td>
                        <td className="px-4 py-3 text-right text-xs text-slate-600 font-mono">
                          {fmtPrice(m.input_price, m.currency)}/M
                        </td>
                        <td className="px-4 py-3 text-right text-xs text-slate-600 font-mono">
                          {fmtPrice(m.output_price, m.currency)}/M
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center justify-center gap-1 flex-wrap">
                            <FeatureBadge active={m.support_image} icon={Image} label={t('group.groupDetail.featureImage')} />
                            <FeatureBadge active={m.support_video} icon={Video} label={t('group.groupDetail.featureVideo')} />
                            <FeatureBadge active={m.support_audio} icon={Mic} label={t('group.groupDetail.featureAudio')} />
                            <FeatureBadge active={m.support_file} icon={FileText} label={t('group.groupDetail.featureFile')} />
                            <FeatureBadge active={m.support_web_search} icon={Globe} label={t('group.groupDetail.featureWebSearch')} />
                            <FeatureBadge active={m.support_thinking} icon={Brain} label={t('group.groupDetail.featureThinking')} />
                            <FeatureBadge active={m.support_embedding} icon={Layers} label={t('group.groupDetail.featureEmbedding')} />
                          </div>
                        </td>
                        <td className="px-4 py-3 text-center">
                          {active ? (
                            <span className="inline-flex items-center gap-1 text-xs text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-full">
                              <Check className="w-3 h-3" /> {t('group.groupDetail.active')}
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-xs text-slate-400 bg-slate-100 px-2 py-0.5 rounded-full">
                              <X className="w-3 h-3" /> {t('group.groupDetail.disabled')}
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  });
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
