import { useState, useMemo, useRef, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useWorkspace } from '../contexts/WorkspaceContext';
import { rateLimitsApi, providersApi, type WorkspaceRateLimitStatus, type WorkspaceProviderBreakdown, type RateLimitApiKeyUsage } from '../api/client';
import BubbleView from '../components/BubbleView';
import {
  Globe, Activity, Gauge, Layers, AlertCircle, Plus, Pencil, Trash2,
  Server, X, Search, Save, List, LayoutGrid, Key, Users,
} from 'lucide-react';

/* ─── helpers ─── */

function fmtNum(n: number): string {
  if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e4) return (n / 1e3).toFixed(1) + 'K';
  return n.toLocaleString();
}

function pctColor(pct: number): string {
  if (pct >= 90) return 'text-red-600';
  if (pct >= 75) return 'text-amber-600';
  if (pct >= 50) return 'text-yellow-600';
  if (pct >= 25) return 'text-emerald-600';
  return 'text-cyan-600';
}

function barColor(pct: number): string {
  if (pct >= 90) return 'bg-red-500';
  if (pct >= 75) return 'bg-amber-500';
  if (pct >= 50) return 'bg-yellow-500';
  if (pct >= 25) return 'bg-emerald-500';
  return 'bg-cyan-500';
}

function cardBg(pct: number): string {
  if (pct >= 90) return 'border-red-200 bg-red-50/30';
  if (pct >= 75) return 'border-amber-200 bg-amber-50/30';
  return 'border-slate-200 bg-white';
}

/* ─── API Key usage sub-table ─── */

function ApiKeyBreakdown({ apikeys }: { apikeys?: RateLimitApiKeyUsage[] }) {
  const { t } = useTranslation();
  if (!apikeys || apikeys.length === 0) {
    return (
      <div className="text-xs text-slate-400 py-2 pl-10">
        {t('rateLimits.noApiKeyUsage')}
      </div>
    );
  }
  return (
    <div className="pl-10 pr-4 py-2">
      <div className="text-[10px] text-slate-400 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
        <Key className="w-3 h-3" />
        {t('rateLimits.apiKeyUsage')}
      </div>
      <div className="space-y-1">
        {apikeys.map((k, i) => (
          <div
            key={k.api_key_name || k.preview || i}
            className="flex items-center gap-3 bg-slate-50 rounded-lg px-3 py-2 text-xs"
          >
            <div className="min-w-0 flex-1">
              <div className="text-slate-700 truncate font-medium">
                {k.api_key_name || k.preview}
              </div>
              {k.group_name && (
                <div className="text-[10px] text-slate-400 flex items-center gap-1 mt-0.5">
                  <Users className="w-2.5 h-2.5" />
                  {k.group_name}
                </div>
              )}
            </div>
            <div className="text-right flex-shrink-0 flex items-center gap-3">
              <div>
                <span className="font-mono text-slate-600">{fmtNum(k.rpm_used)}</span>
                <span className="text-slate-400 ml-0.5">RPM</span>
              </div>
              <div>
                <span className="font-mono text-slate-600">{fmtNum(k.tpm_used)}</span>
                <span className="text-slate-400 ml-0.5">TPM</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── ComboInput ─── */

interface ComboOption { value: string; label: string; sub?: string; }

function ComboInput({ value, onChange, options, placeholder, disabled, className }: {
  value: string;
  onChange: (v: string) => void;
  options: ComboOption[];
  placeholder?: string;
  disabled?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const filtered = useMemo(() => {
    const q = (search || value).toLowerCase();
    if (!q) return options;
    return options.filter(o =>
      o.value.toLowerCase().includes(q) ||
      o.label.toLowerCase().includes(q) ||
      (o.sub && o.sub.toLowerCase().includes(q))
    );
  }, [options, search, value]);

  return (
    <div ref={ref} className={'relative ' + (className || '')}>
      <div className="relative">
        <input
          className="w-full border rounded-lg px-3 py-2 text-sm pr-8"
          value={open ? search : value}
          onChange={e => { setSearch(e.target.value); onChange(e.target.value); if (!open) setOpen(true); }}
          onFocus={() => { setOpen(true); setSearch(value); }}
          placeholder={placeholder}
          disabled={disabled}
        />
        <Search className="w-3.5 h-3.5 text-slate-400 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
      </div>
      {open && !disabled && filtered.length > 0 && (
        <div className="absolute z-50 mt-1 w-full bg-white border border-slate-200 rounded-lg shadow-lg max-h-48 overflow-y-auto">
          {filtered.map(o => (
            <button
              key={o.value}
              type="button"
              className={`w-full text-left px-3 py-2 text-sm hover:bg-indigo-50 flex items-center justify-between ${o.value === value ? 'bg-indigo-50 text-indigo-700' : 'text-slate-700'}`}
              onClick={() => { onChange(o.value); setSearch(''); setOpen(false); }}
            >
              <span className="truncate">{o.label}</span>
              {o.sub && <span className="text-xs text-slate-400 ml-2 flex-shrink-0">{o.sub}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ─── WsLimitForm ─── */

interface WsFormData { model_name: string; provider_type: string; provider_id: string; rpm: string; tpm: string; }

function WsLimitForm({ wsId, initial, onDone }: {
  wsId: number;
  initial?: { id: number; model_name: string; provider_type: string; provider_id: number | null; rpm: number | null; tpm: number | null };
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const isEdit = !!initial;
  const [form, setForm] = useState<WsFormData>({
    model_name: initial?.model_name ?? '',
    provider_type: initial?.provider_type ?? '',
    provider_id: initial?.provider_id != null ? String(initial.provider_id) : '',
    rpm: initial?.rpm != null ? String(initial.rpm) : '',
    tpm: initial?.tpm != null ? String(initial.tpm) : '',
  });

  const { data: providersData } = useQuery({
    queryKey: ['providers-for-suggestions'],
    queryFn: async () => { const r = await providersApi.list(); return r.data; },
    staleTime: 60000,
  });

  const { modelOptions, providerTypeOptions, providerIdOptions } = useMemo(() => {
    const providers = providersData ?? [];
    const modelSet = new Map<string, string>();
    const typeSet = new Set<string>();
    const providerList: ComboOption[] = [{ value: '', label: t('rateLimits.sharedEmpty'), sub: t('rateLimits.sharedNoSpecific') }];

    for (const p of providers) {
      const pType = (p as any).type || (p as any).provider_type || '';
      typeSet.add(pType);
      providerList.push({ value: String(p.id), label: `${p.name}`, sub: `#${p.id} · ${pType}` });
      const models = (p as any).models || [];
      for (const m of models) {
        const alias = (m as any).alias;
        const name = (m as any).name;
        const displayName = alias || name;
        if (displayName && !modelSet.has(displayName)) {
          modelSet.set(displayName, `${p.name} · ${pType}`);
        }
        if (alias && name && alias !== name && !modelSet.has(name)) {
          modelSet.set(name, `${p.name} · ${pType} (原名)`);
        }
      }
    }

    const modelOptions: ComboOption[] = Array.from(modelSet.entries()).map(([v, sub]) => ({ value: v, label: v, sub }));
    const providerTypeOptions: ComboOption[] = Array.from(typeSet).sort().map(t => ({ value: t, label: t }));

    return { modelOptions, providerTypeOptions, providerIdOptions: providerList };
  }, [providersData, t]);

  const handleModelChange = (v: string) => {
    setForm(prev => {
      const next = { ...prev, model_name: v };
      if (!isEdit && providersData) {
        const matchingTypes = new Set<string>();
        for (const p of providersData) {
          const pType = (p as any).type || (p as any).provider_type || '';
          const models = (p as any).models || [];
          for (const m of models) {
            if ((m as any).alias === v || (m as any).name === v) {
              matchingTypes.add(pType);
            }
          }
        }
        if (matchingTypes.size === 1) {
          next.provider_type = Array.from(matchingTypes)[0];
        }
      }
      return next;
    });
  };

  const filteredProviderIdOptions = useMemo(() => {
    if (!form.provider_type || !providersData) return providerIdOptions;
    return providerIdOptions.filter(o => {
      if (o.value === '') return true;
      const p = providersData.find(p => String(p.id) === o.value);
      if (!p) return false;
      const pType = (p as any).type || (p as any).provider_type || '';
      return pType === form.provider_type;
    });
  }, [form.provider_type, providerIdOptions, providersData]);

  const save = async () => {
    const payload = {
      model_name: form.model_name,
      provider_type: form.provider_type,
      provider_id: form.provider_id ? parseInt(form.provider_id) : null,
      rpm: form.rpm ? parseInt(form.rpm) : null,
      tpm: form.tpm ? parseInt(form.tpm) : null,
    };
    if (isEdit) {
      await rateLimitsApi.updateWorkspaceLimit(wsId, initial!.id, payload);
    } else {
      await rateLimitsApi.createWorkspaceLimit(wsId, payload);
    }
    qc.invalidateQueries({ queryKey: ['workspace-rate-limits', wsId] });
    onDone();
  };

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm space-y-3">
      <h4 className="font-semibold text-slate-700">{isEdit ? t('rateLimits.editLimit') : t('rateLimits.addLimit')}</h4>
      <div className="grid grid-cols-1 sm:grid-cols-5 gap-3">
        <div>
          <label className="text-xs text-slate-500 mb-1 block">{t('rateLimits.modelName')}</label>
          <ComboInput value={form.model_name} onChange={handleModelChange}
            options={modelOptions} placeholder={t('rateLimits.searchOrInputModel')} disabled={isEdit} />
        </div>
        <div>
          <label className="text-xs text-slate-500 mb-1 block">{t('rateLimits.providerType')}</label>
          <ComboInput value={form.provider_type} onChange={v => setForm({ ...form, provider_type: v })}
            options={providerTypeOptions} placeholder={t('rateLimits.searchOrInputType')} disabled={isEdit} />
        </div>
        <div>
          <label className="text-xs text-slate-500 mb-1 block">{t('rateLimits.providerAccount')}</label>
          <ComboInput value={form.provider_id} onChange={v => setForm({ ...form, provider_id: v })}
            options={filteredProviderIdOptions} placeholder={t('rateLimits.sharedPlaceholder')} disabled={isEdit} />
        </div>
        <div>
          <label className="text-xs text-slate-500 mb-1 block">RPM</label>
          <input className="w-full border rounded-lg px-3 py-2 text-sm" type="number" value={form.rpm}
            onChange={e => setForm({ ...form, rpm: e.target.value })} placeholder={t('rateLimits.unlimited')} />
        </div>
        <div>
          <label className="text-xs text-slate-500 mb-1 block">TPM</label>
          <input className="w-full border rounded-lg px-3 py-2 text-sm" type="number" value={form.tpm}
            onChange={e => setForm({ ...form, tpm: e.target.value })} placeholder={t('rateLimits.unlimited')} />
        </div>
      </div>
      <div className="flex gap-2 justify-end">
        <button onClick={onDone} className="px-3 py-1.5 text-sm rounded-lg border hover:bg-slate-50 flex items-center gap-1">
          <X className="w-3.5 h-3.5" />{t('rateLimits.cancel')}
        </button>
        <button onClick={save} disabled={!form.model_name || !form.provider_type}
          className="px-3 py-1.5 text-sm rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 flex items-center gap-1">
          <Save className="w-3.5 h-3.5" />{t('rateLimits.save')}
        </button>
      </div>
    </div>
  );
}

/* ─── Main Page ─── */

type ViewMode = 'table' | 'bubble';

export default function RateLimits() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { selectedWorkspace } = useWorkspace();
  const selectedWsId = selectedWorkspace?.id ?? null;
  const [showForm, setShowForm] = useState(false);
  const [editItem, setEditItem] = useState<{ id: number; model_name: string; provider_type: string; provider_id: number | null; rpm: number | null; tpm: number | null } | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>('bubble');

  const { data: wsData, isLoading: wsLoading } = useQuery({
    queryKey: ['workspace-rate-limits', selectedWsId],
    queryFn: async () => {
      if (!selectedWsId) return null;
      const r = await rateLimitsApi.getWorkspaceLimits(selectedWsId);
      return r.data;
    },
    refetchInterval: 10000,
    enabled: !!selectedWsId,
  });

  const deleteMut = useMutation({
    mutationFn: (limitId: number) => rateLimitsApi.deleteWorkspaceLimit(selectedWsId!, limitId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['workspace-rate-limits', selectedWsId] }),
  });

  if (wsLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full" />
      </div>
    );
  }

  const wsLimits: WorkspaceRateLimitStatus[] = wsData?.rate_limits ?? [];

  // ── Summary ──
  const totalRpmUsed = wsLimits.reduce((sum, rl) => sum + (rl.rpm?.used ?? 0), 0);
  const totalTpmUsed = wsLimits.reduce((sum, rl) => sum + (rl.tpm?.used ?? 0), 0);
  const configuredModels = wsLimits.length;

  const sortedLimits = [...wsLimits].sort((a, b) => {
    const aPct = Math.max(
      a.rpm?.limit ? Math.round(a.rpm.used / a.rpm.limit * 100) : 0,
      a.tpm?.limit ? Math.round(a.tpm.used / a.tpm.limit * 100) : 0,
    );
    const bPct = Math.max(
      b.rpm?.limit ? Math.round(b.rpm.used / b.rpm.limit * 100) : 0,
      b.tpm?.limit ? Math.round(b.tpm.used / b.tpm.limit * 100) : 0,
    );
    return bPct - aPct;
  });

  const bottleneckCount = sortedLimits.filter(rl => {
    const pct = Math.max(
      rl.rpm?.limit ? Math.round(rl.rpm.used / rl.rpm.limit * 100) : 0,
      rl.tpm?.limit ? Math.round(rl.tpm.used / rl.tpm.limit * 100) : 0,
    );
    return pct >= 75;
  }).length;

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {/* ── Header ── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-6 gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">{t('rateLimits.title')}</h1>
          <p className="text-sm text-slate-500">{t('rateLimits.subtitle')}</p>
        </div>
        <div className="flex items-center gap-2">
          {/* View toggle */}
          <div className="flex bg-slate-100 rounded-lg p-0.5">
            <button
              onClick={() => setViewMode('bubble')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                viewMode === 'bubble'
                  ? 'bg-white text-slate-800 shadow-sm'
                  : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              <LayoutGrid className="w-4 h-4" />
              {t('rateLimits.bubbleView')}
            </button>
            <button
              onClick={() => setViewMode('table')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                viewMode === 'table'
                  ? 'bg-white text-slate-800 shadow-sm'
                  : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              <List className="w-4 h-4" />
              {t('rateLimits.tableView')}
            </button>
          </div>
          {selectedWsId && (
            <button
              onClick={() => { setShowForm(true); setEditItem(null); }}
              className="flex items-center gap-1 px-3 py-1.5 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700"
            >
              <Plus className="w-4 h-4" /> {t('rateLimits.addLimit')}
            </button>
          )}
        </div>
      </div>

      {/* ── Summary Cards ── */}
      {selectedWsId && wsLimits.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
            <div className="flex items-center gap-2 mb-2">
              <div className="p-2 bg-blue-50 rounded-lg"><Activity className="w-4 h-4 text-blue-500" /></div>
              <span className="text-sm text-slate-500">{t('rateLimits.totalRpmUsed')}</span>
            </div>
            <div className="text-2xl font-bold text-slate-800 font-mono">{fmtNum(totalRpmUsed)}</div>
          </div>
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
            <div className="flex items-center gap-2 mb-2">
              <div className="p-2 bg-indigo-50 rounded-lg"><Gauge className="w-4 h-4 text-indigo-500" /></div>
              <span className="text-sm text-slate-500">{t('rateLimits.totalTpmUsed')}</span>
            </div>
            <div className="text-2xl font-bold text-slate-800 font-mono">{fmtNum(totalTpmUsed)}</div>
          </div>
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
            <div className="flex items-center gap-2 mb-2">
              <div className="p-2 bg-emerald-50 rounded-lg"><Layers className="w-4 h-4 text-emerald-500" /></div>
              <span className="text-sm text-slate-500">{t('rateLimits.configuredModels')}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-2xl font-bold text-slate-800 font-mono">{configuredModels}</span>
              {bottleneckCount > 0 && (
                <span className="text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded-full font-medium flex items-center gap-1">
                  <AlertCircle className="w-3 h-3" /> {bottleneckCount} bottleneck
                </span>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Add / Edit form ── */}
      {showForm && selectedWsId && (
        <div className="mb-4">
          <WsLimitForm
            wsId={selectedWsId}
            initial={editItem ?? undefined}
            onDone={() => { setShowForm(false); setEditItem(null); }}
          />
        </div>
      )}

      {/* ── Workspace header ── */}
      <div className="flex items-center gap-2 mb-3">
        <Globe className="w-5 h-5 text-indigo-500" />
        <h2 className="text-lg font-semibold text-slate-700">
          {t('rateLimits.workspaceLevel')}
          {selectedWorkspace && (
            <span className="text-sm font-normal text-slate-500"> — {selectedWorkspace.name}</span>
          )}
        </h2>
      </div>

      {/* ── Content by view mode ── */}
      {!selectedWsId ? (
        <div className="text-center py-8 text-slate-400 bg-white border border-slate-200 rounded-xl">
          {t('rateLimits.selectWorkspace')}
        </div>
      ) : wsLimits.length === 0 ? (
        <div className="text-center py-8 text-slate-400 bg-white border border-slate-200 rounded-xl">
          {t('rateLimits.noWsLimits')}
        </div>
      ) : viewMode === 'bubble' ? (
        /* ─── Bubble 3D View ─── */
        <BubbleView wsLimits={wsLimits} />
      ) : (
        /* ─── Table View ─── */
        <div className="space-y-3">
          <p className="text-xs text-slate-400">{t('rateLimits.workspaceSubtitle')}</p>

          {sortedLimits.map((rl, i) => {
            const rpmLim = (rl as any).rpm_limit ?? rl.rpm?.limit;
            const tpmLim = (rl as any).tpm_limit ?? rl.tpm?.limit;
            const rpmUsed = rl.rpm?.used ?? 0;
            const tpmUsed = rl.tpm?.used ?? 0;
            const rpmPct = rpmLim ? Math.round(rpmUsed / rpmLim * 100) : 0;
            const tpmPct = tpmLim ? Math.round(tpmUsed / tpmLim * 100) : 0;
            const maxPct = Math.max(rpmPct, tpmPct);
            const rlId = (rl as any).id;
            const providers: WorkspaceProviderBreakdown[] = rl.providers ?? [];
            const providerMaxPct = providers.reduce((max, p) => {
              const pRpm = p.rpm_limit ? Math.round(p.rpm_used / p.rpm_limit * 100) : 0;
              const pTpm = p.tpm_limit ? Math.round(p.tpm_used / p.tpm_limit * 100) : 0;
              return Math.max(max, pRpm, pTpm);
            }, 0);
            const effectiveMaxPct = Math.max(maxPct, providerMaxPct);

            const isHighLoad = effectiveMaxPct >= 90;
            const isMediumLoad = effectiveMaxPct >= 75 && effectiveMaxPct < 90;

            return (
              <div
                key={rl.model_name + '-' + i}
                className={`rounded-xl border overflow-hidden shadow-sm ${cardBg(effectiveMaxPct)}`}
              >
                {/* Model row header */}
                <div className="px-4 py-3 flex items-center justify-between">
                  <div className="flex items-center gap-3 min-w-0">
                    {isHighLoad ? (
                      <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0" />
                    ) : isMediumLoad ? (
                      <AlertCircle className="w-5 h-5 text-amber-500 flex-shrink-0" />
                    ) : (
                      <Server className="w-5 h-5 text-slate-400 flex-shrink-0" />
                    )}
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-slate-800 truncate">{rl.model_name}</span>
                        <span className="text-xs text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded flex-shrink-0">
                          {rl.provider_type}
                          {rl.provider_name ? ` · ${rl.provider_name}` : rl.provider_id == null ? ` · ${t('rateLimits.shared')}` : ''}
                        </span>
                        {providers.length > 0 && (
                          <span className="text-xs text-slate-400 flex-shrink-0">({providers.length} providers)</span>
                        )}
                      </div>
                      <div className="flex items-center gap-1 mt-0.5">
                        {isHighLoad && (
                          <span className="text-[10px] bg-red-100 text-red-700 px-1.5 py-0.5 rounded-full font-medium">
                            {t('rateLimits.usageHigh')} {effectiveMaxPct}%
                          </span>
                        )}
                        {isMediumLoad && (
                          <span className="text-[10px] bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded-full font-medium">
                            {t('rateLimits.usageMedium')} {effectiveMaxPct}%
                          </span>
                        )}
                        {!isHighLoad && !isMediumLoad && effectiveMaxPct > 0 && (
                          <span className="text-[10px] text-slate-400">{effectiveMaxPct}%</span>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    {/* RPM / TPM summary */}
                    <div className="hidden sm:flex gap-4 text-right">
                      <div>
                        <div className="text-xs text-slate-400">RPM</div>
                        <div className={`text-sm font-mono font-semibold ${pctColor(rpmPct)}`}>
                          {rpmLim ? `${rpmUsed}/${rpmLim}` : '∞'}
                        </div>
                        {rpmLim && (
                          <div className="mt-0.5 h-1 w-full bg-slate-100 rounded-full">
                            <div
                              className={`h-full rounded-full ${barColor(rpmPct)}`}
                              style={{ width: Math.min(rpmPct, 100) + '%' }}
                            />
                          </div>
                        )}
                      </div>
                      <div>
                        <div className="text-xs text-slate-400">TPM</div>
                        <div className={`text-sm font-mono font-semibold ${pctColor(tpmPct)}`}>
                          {tpmLim ? `${fmtNum(tpmUsed)}/${fmtNum(tpmLim)}` : '∞'}
                        </div>
                        {tpmLim && (
                          <div className="mt-0.5 h-1 w-full bg-slate-100 rounded-full">
                            <div
                              className={`h-full rounded-full ${barColor(tpmPct)}`}
                              style={{ width: Math.min(tpmPct, 100) + '%' }}
                            />
                          </div>
                        )}
                      </div>
                    </div>
                    {/* Actions */}
                    <div className="flex gap-1">
                      <button
                        onClick={() => {
                          setEditItem({
                            id: rlId,
                            model_name: rl.model_name,
                            provider_type: rl.provider_type || '',
                            provider_id: rl.provider_id ?? null,
                            rpm: rpmLim,
                            tpm: tpmLim,
                          });
                          setShowForm(true);
                        }}
                        className="p-1.5 rounded hover:bg-slate-100"
                        title={t('rateLimits.edit')}
                      >
                        <Pencil className="w-3.5 h-3.5 text-slate-500" />
                      </button>
                      <button
                        onClick={() => {
                          if (confirm(t('rateLimits.confirmDelete'))) deleteMut.mutate(rlId);
                        }}
                        className="p-1.5 rounded hover:bg-red-50"
                        title={t('rateLimits.delete')}
                      >
                        <Trash2 className="w-3.5 h-3.5 text-red-500" />
                      </button>
                    </div>
                  </div>
                </div>

                {/* Provider sub-rows — each provider is a separate block */}
                {providers.length > 0 && (
                  <div className="border-t border-slate-100">
                    <div className="px-4 py-1.5 text-[10px] text-slate-400 uppercase tracking-wider">
                      {t('rateLimits.providerBreakdown')}
                    </div>
                    {providers.map((p, j) => {
                      const pRpmPct = p.rpm_limit ? Math.round(p.rpm_used / p.rpm_limit * 100) : 0;
                      const pTpmPct = p.tpm_limit ? Math.round(p.tpm_used / p.tpm_limit * 100) : 0;
                      const pMax = Math.max(pRpmPct, pTpmPct);
                      return (
                        <div
                          key={`${rl.model_name}-p-${j}`}
                          className={`px-4 py-2 flex items-center justify-between text-xs ${
                            j < providers.length - 1 ? 'border-b border-slate-50' : ''
                          } ${pMax >= 90 ? 'bg-red-50/30' : pMax >= 75 ? 'bg-amber-50/30' : ''}`}
                        >
                          <div className="flex items-center gap-2 min-w-0 flex-1">
                            <Server className="w-3 h-3 text-slate-400 flex-shrink-0" />
                            <span className="text-slate-700 font-medium">{p.provider_name || '?'}</span>
                            <span className="text-slate-400">·</span>
                            <span className="text-slate-500 flex items-center gap-1">
                              <Users className="w-2.5 h-2.5" />
                              {p.group_name || '?'}
                            </span>
                            {pMax >= 90 && (
                              <span className="text-[10px] bg-red-100 text-red-600 px-1 py-0.5 rounded font-medium">
                                {pMax}%
                              </span>
                            )}
                            {pMax >= 75 && pMax < 90 && (
                              <span className="text-[10px] bg-amber-100 text-amber-600 px-1 py-0.5 rounded font-medium">
                                {pMax}%
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-4 flex-shrink-0">
                            <div className="text-right min-w-[80px]">
                              <span className={`font-mono ${pctColor(pRpmPct)}`}>
                                {p.rpm_limit ? `${p.rpm_used}/${p.rpm_limit}` : '∞'}
                              </span>
                              <span className="text-slate-400 ml-0.5">RPM</span>
                            </div>
                            <div className="text-right min-w-[100px]">
                              <span className={`font-mono ${pctColor(pTpmPct)}`}>
                                {p.tpm_limit ? `${fmtNum(p.tpm_used)}/${fmtNum(p.tpm_limit)}` : '∞'}
                              </span>
                              <span className="text-slate-400 ml-0.5">TPM</span>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* API Key usage section */}
                {rl.apikeys && rl.apikeys.length > 0 && (
                  <div className="border-t border-slate-100">
                    <ApiKeyBreakdown apikeys={rl.apikeys} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}