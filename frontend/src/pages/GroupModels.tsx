/**
 * GroupModels — 分组可用模型列表
 *
 * 聚合该分组下所有供应商的模型，按模型名称/别名分组展示，
 * 一个模型可能由多个供应商提供。支持模型共享到其他分组。
 */
import { useMemo, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import client from '../api/client';
import {
  Cpu, Database, Search, Check, X,
  Image, Video, Mic, FileText, Globe, Brain, Layers, Share2
} from 'lucide-react';
import ShareModelModal from '../components/ShareModelModal';

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
  api_type: string | null;
  rpm: number | null;
  tpm: number | null;
  priority: number;
  traffic_ratio: number;
}

interface ProviderData {
  id: number;
  name: string;
  type: string;
  is_active: boolean;
  models: ModelItem[];
}

interface ModelShareEntry {
  id: number;
  model_id: number;
  model_name: string;
  model_alias: string | null;
  provider_name: string;
  provider_type: string;
  source_group_id: number;
  source_group_name: string;
  context_size: number;
  input_price: number;
  output_price: number;
  currency: string;
  is_active: boolean;
  support_image: boolean;
  support_audio: boolean;
  support_video: boolean;
  support_file: boolean;
  support_web_search: boolean;
  support_thinking: boolean;
  support_embedding: boolean;
  api_type: string | null;
  rpm: number | null;
  tpm: number | null;
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
    /** If this instance comes from a shared model, the source group name */
    sharedFromGroup?: string;
  }[];
}

/* ── Helpers ────────────────────────────────────────────────────────────── */

function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(0) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(0) + 'K';
  return String(n);
}

function fmtPrice(n: number | string | null | undefined, currency: string): string {
  const v = Number(n) || 0;
  const sym = currency?.toUpperCase() === 'CNY' ? '¥' : '$';
  if (v === 0) return `${sym}0`;
  if (v < 0.01) return `${sym}${v.toFixed(4)}`;
  return `${sym}${v.toFixed(2)}`;
}

function fmtDiscount(d: number): string {
  if (d >= 1 || d == null) return '-';
  return (d * 10).toFixed(1).replace(/\.0$/, '') + '折';
}

const FeatureBadge = ({ active, icon: Icon, label }: { active: boolean; icon: React.ElementType; label: string }) => {
  if (!active) return null;
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs bg-slate-100 text-slate-600" title={label}>
      <Icon className="w-3 h-3" />
    </span>
  );
};

/* ── InlineEditableCell ─────────────────────────────────────────────────── */

const InlineEditableCell = ({ value, onSave, readonly, min = 0, max = 100 }: {
  value: number;
  onSave: (v: number) => void;
  readonly?: boolean;
  min?: number;
  max?: number;
}) => {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(String(value));

  if (readonly) {
    return <span className="text-xs font-mono text-slate-500 px-2 py-0.5">{value}</span>;
  }

  const startEdit = () => { setDraft(String(value)); setEditing(true); };
  const commit = () => {
    const n = Number(draft);
    if (!isNaN(n)) onSave(Math.max(min, Math.min(max, n)));
    setEditing(false);
  };
  const cancel = () => setEditing(false);
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') commit();
    else if (e.key === 'Escape') cancel();
  };

  if (editing) {
    return (
      <input
        type="number" min={min} max={max} value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit} onKeyDown={onKeyDown}
        className="w-16 px-1.5 py-0.5 text-xs font-mono text-center border border-indigo-300 rounded focus:outline-none focus:ring-1 focus:ring-indigo-400"
        autoFocus
      />
    );
  }
  return (
    <button
      onClick={startEdit}
      className="text-xs font-mono text-slate-600 hover:text-indigo-600 hover:bg-indigo-50 px-2 py-0.5 rounded cursor-pointer transition-colors"
      title="点击编辑"
    >{value}</button>
  );
};

/* ── Component ─────────────────────────────────────────────────────────── */

export default function GroupModels({ groupId, currentRole, myPermissions }: { groupId: number; currentRole?: string; myPermissions?: Record<string, boolean> }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const [shareModel, setShareModel] = useState<{ id: number; name: string; alias: string | null; providerName: string } | null>(null);

  // admins and root can edit priority/traffic_ratio when permission is enabled
  const isAtLeastAdmin = currentRole === 'root' || currentRole === 'admin';
  const canEditPriority = isAtLeastAdmin && (myPermissions?.['model.priority'] !== false);
  const canEditTrafficRatio = isAtLeastAdmin && (myPermissions?.['model.priority'] !== false);

  const providersQueryKey = ['providers', 'group', groupId];

  const { data: providers, isLoading } = useQuery<ProviderData[]>({
    queryKey: providersQueryKey,
    queryFn: async () => {
      const res = await client.get('/api/providers/', { params: { group_id: groupId } });
      return res.data;
    },
  });

  // Fetch shared models (incoming shares TO this group)
  const { data: sharesData } = useQuery<{ shares: ModelShareEntry[] }>({
    queryKey: ['model-shares', groupId],
    queryFn: async () => {
      const res = await client.get(`/api/groups/${groupId}/model-shares`);
      return res.data;
    },
  });

  const updateModel = useMutation({
    mutationFn: async ({ id, field, value }: { id: number; field: 'priority' | 'traffic_ratio'; value: number }) => {
      await client.put(`/api/models/${id}`, { [field]: value });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: providersQueryKey }),
  });

  // Aggregate models across providers AND shared models
  const aggregated = useMemo(() => {
    if (!providers) return [];

    const map = new Map<string, AggregatedModel>();

    // Add models from own providers
    for (const prov of providers) {
      for (const model of prov.models) {
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

    // Add shared models as additional provider instances
    const shares: ModelShareEntry[] = sharesData?.shares || [];
    for (const share of shares) {
      const displayName = share.model_alias || share.model_name;
      const key = displayName.toLowerCase();

      if (!map.has(key)) {
        map.set(key, { displayName, instances: [] });
      }
      // Create a synthetic ModelItem from the share data
      const syntheticModel: ModelItem = {
        id: share.model_id,
        provider_id: 0,
        name: share.model_name,
        alias: share.model_alias,
        context_size: share.context_size,
        input_size: share.context_size,
        output_size: share.context_size,
        input_price: share.input_price,
        output_price: share.output_price,
        currency: share.currency,
        discount: 1,
        is_active: share.is_active,
        is_retired: false,
        support_image: share.support_image,
        support_audio: share.support_audio,
        support_video: share.support_video,
        support_file: share.support_file,
        support_web_search: share.support_web_search,
        support_thinking: share.support_thinking,
        support_embedding: share.support_embedding,
        api_type: share.api_type || null,
        rpm: share.rpm,
        tpm: share.tpm,
        priority: 0,
        traffic_ratio: 0,
      };
      map.get(key)!.instances.push({
        model: syntheticModel,
        providerName: share.provider_name,
        providerType: 'shared',
        providerActive: true,
        sharedFromGroup: share.source_group_name,
      });
    }

    return Array.from(map.values()).sort((a, b) => a.displayName.localeCompare(b.displayName));
  }, [providers, sharesData]);

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

  // Determine which model_id to show share button for (use the first non-shared instance's model id)
  function getShareableModel(agg: AggregatedModel): { id: number; name: string; alias: string | null; providerName: string } | null {
    const own = agg.instances.find(i => !i.sharedFromGroup);
    if (!own) return null;
    return {
      id: own.model.id,
      name: own.model.name,
      alias: own.model.alias,
      providerName: own.providerName,
    };
  }

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
                  <th className="px-4 py-3 text-center text-xs font-semibold text-slate-500">{t('group.groupDetail.discount')}</th>
                  <th className="px-4 py-3 text-center text-xs font-semibold text-slate-500">{t('group.groupDetail.rpm')}</th>
                  <th className="px-4 py-3 text-center text-xs font-semibold text-slate-500">{t('group.groupDetail.tpm')}</th>
                  <th className="px-4 py-3 text-center text-xs font-semibold text-slate-500">{t('group.groupDetail.priority')}</th>
                  <th className="px-4 py-3 text-center text-xs font-semibold text-slate-500">{t('group.groupDetail.trafficRatio')}</th>
                  <th className="px-4 py-3 text-center text-xs font-semibold text-slate-500">{t('group.groupDetail.capabilities')}</th>
                  <th className="px-4 py-3 text-center text-xs font-semibold text-slate-500">{t('group.groupDetail.status')}</th>
                  <th className="px-4 py-3 text-center text-xs font-semibold text-slate-500">{t('group.groupDetail.actions')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filtered.map((agg) => {
                  const shareable = getShareableModel(agg);

                  // If only one provider, show as single row
                  if (agg.instances.length === 1) {
                    const inst = agg.instances[0];
                    const m = inst.model;
                    const active = m.is_active && inst.providerActive;
                    const isShared = !!inst.sharedFromGroup;
                    return (
                      <tr key={`${m.id}-${isShared ? 's' : 'o'}`} className={`hover:bg-slate-50 ${!active ? 'opacity-50' : ''}`}>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-slate-800">{agg.displayName}</span>
                            {m.alias && m.alias !== m.name && (
                              <span className="text-xs text-slate-400">{m.name}</span>
                            )}
                            {isShared && (
                              <span className="text-xs text-indigo-600 bg-indigo-50 px-1.5 py-0.5 rounded">
                                {t('group.groupDetail.sharedBadge', { group: inst.sharedFromGroup })}
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <span className="inline-flex items-center gap-1 text-xs text-slate-600">
                            <Database className="w-3 h-3 text-slate-400" />
                            {inst.providerName}
                            {isShared && (
                              <Share2 className="w-3 h-3 text-indigo-400 ml-1" />
                            )}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-center text-xs text-slate-600 font-mono">{isShared ? '-' : fmtNum(m.context_size)}</td>
                        <td className="px-4 py-3 text-right text-xs text-slate-600 font-mono">
                          {isShared ? '-' : fmtPrice(m.input_price, m.currency) + '/M'}
                        </td>
                        <td className="px-4 py-3 text-right text-xs text-slate-600 font-mono">
                          {isShared ? '-' : fmtPrice(m.output_price, m.currency) + '/M'}
                        </td>
                        <td className="px-4 py-3 text-center text-xs text-slate-600 font-mono">
                          {isShared ? '-' : fmtDiscount(m.discount)}
                        </td>
                        <td className="px-4 py-3 text-center text-xs text-slate-600 font-mono">{isShared ? '-' : (m.rpm != null ? m.rpm : '-')}</td>
                        <td className="px-4 py-3 text-center text-xs text-slate-600 font-mono">{isShared ? '-' : (m.tpm != null ? m.tpm : '-')}</td>
                        <td className="px-4 py-3 text-center">
                          {isShared ? <span className="text-xs text-slate-400">-</span> : (
                            <InlineEditableCell readonly={!canEditPriority} value={m.priority ?? 0} onSave={(v) => updateModel.mutate({ id: m.id, field: 'priority', value: v })} />
                          )}
                        </td>
                        <td className="px-4 py-3 text-center">
                          {isShared ? <span className="text-xs text-slate-400">-</span> : (
                            <InlineEditableCell readonly={!canEditTrafficRatio} value={m.traffic_ratio ?? 0} onSave={(v) => updateModel.mutate({ id: m.id, field: 'traffic_ratio', value: v })} />
                          )}
                        </td>
                        <td className="px-4 py-3">
                          {isShared ? <span className="text-xs text-slate-400">-</span> : (
                            <>
                            <div className="flex items-center justify-center gap-1 flex-wrap">
                              <FeatureBadge active={m.support_image} icon={Image} label={t('group.groupDetail.featureImage')} />
                              <FeatureBadge active={m.support_video} icon={Video} label={t('group.groupDetail.featureVideo')} />
                              <FeatureBadge active={m.support_audio} icon={Mic} label={t('group.groupDetail.featureAudio')} />
                              <FeatureBadge active={m.support_file} icon={FileText} label={t('group.groupDetail.featureFile')} />
                              <FeatureBadge active={m.support_web_search} icon={Globe} label={t('group.groupDetail.featureWebSearch')} />
                              <FeatureBadge active={m.support_thinking} icon={Brain} label={t('group.groupDetail.featureThinking')} />
                              <FeatureBadge active={m.support_embedding} icon={Layers} label={t('group.groupDetail.featureEmbedding')} />
                            </div>
                            {m.api_type && <div className="mt-1">
                              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs bg-blue-50 text-blue-600 font-mono" title="API access types">{m.api_type}</span>
                            </div>}
                          </>
                          )}
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
                        <td className="px-4 py-3 text-center">
                          {shareable && (
                            <button
                              onClick={() => setShareModel(shareable)}
                              className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors"
                              title={t('group.groupDetail.shareToGroup')}
                            >
                              <Share2 className="w-3.5 h-3.5" />
                              {t('group.groupDetail.shareToGroup')}
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  }

                  // Multiple providers: show grouped rows
                  return agg.instances.map((inst, idx) => {
                    const m = inst.model;
                    const active = m.is_active && inst.providerActive;
                    const isShared = !!inst.sharedFromGroup;
                    const rowSpan = agg.instances.length;
                    const instShareable = isShared ? null : {
                      id: m.id,
                      name: m.name,
                      alias: m.alias,
                      providerName: inst.providerName,
                    };
                    return (
                      <tr key={`${m.id}-${idx}-${isShared ? 's' : 'o'}`} className={`hover:bg-slate-50 ${!active ? 'opacity-50' : ''} ${idx > 0 ? 'border-t-0' : ''}`}>
                        {idx === 0 ? (
                          <td className="px-4 py-3" rowSpan={rowSpan}>
                            <div className="flex items-center gap-2">
                              <span className="font-medium text-slate-800">{agg.displayName}</span>
                              <span className="text-xs text-indigo-500 bg-indigo-50 px-1.5 py-0.5 rounded">
                                {t('group.groupDetail.providersCount', { count: rowSpan })}
                              </span>
                            </div>
                          </td>
                        ) : null}
                        <td className="px-4 py-3">
                          <span className="inline-flex items-center gap-1 text-xs text-slate-600">
                            <Database className="w-3 h-3 text-slate-400" />
                            {inst.providerName}
                            {isShared && (
                                <>
                                <Share2 className="w-3 h-3 text-indigo-400 ml-1" />
                                <span className="text-xs text-indigo-500 ml-1">
                                  ({t('group.groupDetail.sharedBadge', { group: inst.sharedFromGroup })})
                                </span>
                            </>
                            )}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-center text-xs text-slate-600 font-mono">{isShared ? '-' : fmtNum(m.context_size)}</td>
                        <td className="px-4 py-3 text-right text-xs text-slate-600 font-mono">
                          {isShared ? '-' : fmtPrice(m.input_price, m.currency) + '/M'}
                        </td>
                        <td className="px-4 py-3 text-right text-xs text-slate-600 font-mono">
                          {isShared ? '-' : fmtPrice(m.output_price, m.currency) + '/M'}
                        </td>
                        <td className="px-4 py-3 text-center text-xs text-slate-600 font-mono">
                          {isShared ? '-' : fmtDiscount(m.discount)}
                        </td>
                        <td className="px-4 py-3 text-center text-xs text-slate-600 font-mono">{isShared ? '-' : (m.rpm != null ? m.rpm : '-')}</td>
                        <td className="px-4 py-3 text-center text-xs text-slate-600 font-mono">{isShared ? '-' : (m.tpm != null ? m.tpm : '-')}</td>
                        <td className="px-4 py-3 text-center">
                          {isShared ? <span className="text-xs text-slate-400">-</span> : (
                            <InlineEditableCell readonly={!canEditPriority} value={m.priority ?? 0} onSave={(v) => updateModel.mutate({ id: m.id, field: 'priority', value: v })} />
                          )}
                        </td>
                        <td className="px-4 py-3 text-center">
                          {isShared ? <span className="text-xs text-slate-400">-</span> : (
                            <InlineEditableCell readonly={!canEditTrafficRatio} value={m.traffic_ratio ?? 0} onSave={(v) => updateModel.mutate({ id: m.id, field: 'traffic_ratio', value: v })} />
                          )}
                        </td>
                        <td className="px-4 py-3">
                          {isShared ? <span className="text-xs text-slate-400">-</span> : (
                            <>
                            <div className="flex items-center justify-center gap-1 flex-wrap">
                              <FeatureBadge active={m.support_image} icon={Image} label={t('group.groupDetail.featureImage')} />
                              <FeatureBadge active={m.support_video} icon={Video} label={t('group.groupDetail.featureVideo')} />
                              <FeatureBadge active={m.support_audio} icon={Mic} label={t('group.groupDetail.featureAudio')} />
                              <FeatureBadge active={m.support_file} icon={FileText} label={t('group.groupDetail.featureFile')} />
                              <FeatureBadge active={m.support_web_search} icon={Globe} label={t('group.groupDetail.featureWebSearch')} />
                              <FeatureBadge active={m.support_thinking} icon={Brain} label={t('group.groupDetail.featureThinking')} />
                              <FeatureBadge active={m.support_embedding} icon={Layers} label={t('group.groupDetail.featureEmbedding')} />
                            </div>
                            {m.api_type && <div className="mt-1">
                              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs bg-blue-50 text-blue-600 font-mono" title="API access types">{m.api_type}</span>
                            </div>}
                          </>
                          )}
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
                        <td className="px-4 py-3 text-center">
                          {instShareable && (
                            <button
                              onClick={() => setShareModel(instShareable)}
                              className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors"
                              title={t('group.groupDetail.shareToGroup')}
                            >
                              <Share2 className="w-3.5 h-3.5" />
                              {t('group.groupDetail.shareToGroup')}
                            </button>
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

      {/* Share Model Modal */}
      {shareModel && (
        <ShareModelModal
          model={shareModel}
          currentGroupId={groupId}
          onClose={() => {
            setShareModel(null);
            queryClient.invalidateQueries({ queryKey: ['model-shares'] });
          }}
        />
      )}
    </div>
  );
}