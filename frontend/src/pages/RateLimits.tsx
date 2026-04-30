import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { rateLimitsApi, providersApi } from '../api/client';
import type { WorkspaceRateLimitStatus, RateLimitApiKeyUsage, WorkspaceProviderBreakdown } from '../api/client';
import { Gauge, Activity, Key, AlertCircle, ChevronDown, ChevronUp, Globe, Plus, Pencil, Trash2, X, Save, Layers, Clock, Server, Search } from 'lucide-react';
import { Fragment, useState, useRef, useEffect, useMemo } from 'react';
import { useWorkspace } from '../contexts/WorkspaceContext';


function fmtNum(n: number): string {
  if (n >= 1_000_000_000) return (n / 1_000_000_000).toFixed(1) + 'B';
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return n.toLocaleString();
}
function pctColor(pct: number): string {
  if (pct >= 90) return 'text-red-600';
  if (pct >= 75) return 'text-amber-600';
  if (pct >= 50) return 'text-yellow-600';
  return 'text-emerald-600';
}
function barColor(pct: number): string {
  if (pct >= 90) return 'bg-red-500';
  if (pct >= 75) return 'bg-amber-500';
  if (pct >= 50) return 'bg-yellow-500';
  return 'bg-emerald-500';
}
function cardBg(pct: number): string {
  if (pct >= 90) return 'bg-red-50 border-red-200';
  if (pct >= 75) return 'bg-amber-50 border-amber-200';
  return 'bg-white border-slate-200';
}

function ProgressBar({ pct, used, total, label }: { pct: number; used: number; total: number | null; label: string }) {
  const { t } = useTranslation();
  if (!total) return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs"><span className="text-slate-500">{label}</span><span className="text-slate-400">{t('rateLimits.unlimited')}</span></div>
      <div className="h-2 bg-slate-100 rounded-full" />
    </div>
  );
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-slate-500">{label}</span>
        <span className={pctColor(pct) + ' font-mono font-medium'}>{fmtNum(used)} / {fmtNum(total)} ({pct}%)</span>
      </div>
      <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
        <div className={barColor(pct) + ' h-full rounded-full transition-all duration-500'} style={{ width: Math.min(pct, 100) + '%' }} />
      </div>
    </div>
  );
}

function ApiKeyTable({ apikeys }: { apikeys: RateLimitApiKeyUsage[] }) {
  const { t } = useTranslation();
  if (!apikeys || apikeys.length === 0) return null;
  return (
    <div>
      <h4 className="text-sm font-medium text-slate-700 mb-2 flex items-center gap-2"><Key className="w-4 h-4" /> {t('rateLimits.apiKeyUsage')}</h4>
      <table className="w-full text-sm">
        <thead><tr className="text-left text-xs text-slate-500 border-b"><th className="pb-1">API Key</th><th className="pb-1 text-right">RPM</th><th className="pb-1 text-right">TPM</th></tr></thead>
        <tbody>{apikeys.map(k => (
          <tr key={k.preview} className="border-b border-slate-50">
            <td className="py-1 font-mono text-xs">{k.preview}</td>
            <td className="py-1 text-right">{k.rpm_used}</td>
            <td className="py-1 text-right">{fmtNum(k.tpm_used)}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function HistoryTable({ history }: { history: WorkspaceRateLimitStatus['history'] }) {
  if (!history) return null;
  return (
    <div>
      <h4 className="text-sm font-medium text-slate-700 mb-2 flex items-center gap-2"><Clock className="w-4 h-4" /> 历史趋势</h4>
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: '1 min', rpm: history.rpm_1m, tpm: history.tpm_1m },
          { label: '5 min', rpm: history.rpm_5m, tpm: history.tpm_5m },
          { label: '10 min', rpm: history.rpm_10m, tpm: history.tpm_10m },
        ].map(({ label, rpm, tpm }) => (
          <div key={label} className="bg-slate-50 rounded-lg p-3 text-center">
            <div className="text-xs text-slate-400 mb-1">{label}</div>
            <div className="text-sm font-mono">
              <span className="text-blue-600">{rpm}</span>
              <span className="text-slate-300 mx-1">|</span>
              <span className="text-indigo-600">{fmtNum(tpm)}</span>
            </div>
            <div className="text-[10px] text-slate-400 mt-0.5">RPM | TPM</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ProviderTable({ providers }: { providers?: WorkspaceProviderBreakdown[] }) {
  if (!providers || providers.length === 0) return null;
  return (
    <div>
      <h4 className="text-sm font-medium text-slate-700 mb-2 flex items-center gap-2"><Server className="w-4 h-4" /> 供应商明细</h4>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-slate-500 border-b">
            <th className="pb-1">供应商</th>
            <th className="pb-1">分组</th>
            <th className="pb-1 text-right">RPM (used/limit)</th>
            <th className="pb-1 text-right">TPM (used/limit)</th>
          </tr>
        </thead>
        <tbody>
          {providers.map((p, i) => {
            const rpmPct = p.rpm_limit ? Math.round(p.rpm_used / p.rpm_limit * 100) : 0;
            const tpmPct = p.tpm_limit ? Math.round(p.tpm_used / p.tpm_limit * 100) : 0;
            return (
              <tr key={`${p.provider_name}-${i}`} className="border-b border-slate-50">
                <td className="py-1.5 font-medium text-xs">{p.provider_name || '-'}</td>
                <td className="py-1.5 text-xs text-slate-500">{p.group_name || '-'}</td>
                <td className="py-1.5 text-right font-mono text-xs">
                  {p.rpm_limit ? (
                    <span className={pctColor(rpmPct)}>{p.rpm_used}/{p.rpm_limit}</span>
                  ) : <span className="text-slate-400">∞</span>}
                </td>
                <td className="py-1.5 text-right font-mono text-xs">
                  {p.tpm_limit ? (
                    <span className={pctColor(tpmPct)}>{fmtNum(p.tpm_used)}/{fmtNum(p.tpm_limit)}</span>
                  ) : <span className="text-slate-400">∞</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function WorkspaceCard({ status: s }: { status: WorkspaceRateLimitStatus }) {
  const [open, setOpen] = useState(false);
  const rpmPct = s.rpm.limit && s.rpm.limit > 0 ? Math.round(s.rpm.used / s.rpm.limit * 100) : 0;
  const tpmPct = s.tpm.limit && s.tpm.limit > 0 ? Math.round(s.tpm.used / s.tpm.limit * 100) : 0;
  const maxPct = Math.max(rpmPct, tpmPct);
  const Icon = maxPct >= 90 ? AlertCircle : maxPct >= 75 ? Activity : Globe;
  return (
    <div className={'rounded-xl border shadow-sm overflow-hidden ' + cardBg(maxPct)}>
      <div className="px-5 py-4 flex items-center justify-between cursor-pointer hover:bg-slate-50/50" onClick={() => setOpen(!open)}>
        <div className="flex items-center gap-3 min-w-0">
          <Icon className={'w-5 h-5 ' + pctColor(maxPct)} />
          <div className="min-w-0">
            <h3 className="font-semibold text-slate-800 truncate">{s.model_name}</h3>
            <p className="text-xs text-slate-500 truncate">
              {s.workspace_name}
              {s.providers && s.providers.length > 0 && (
                <span className="ml-1 text-slate-400">· {s.providers.length} provider{s.providers.length > 1 ? 's' : ''}</span>
              )}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="hidden sm:flex gap-6 text-right">
            <div><div className="text-xs text-slate-400">RPM</div><div className={'text-sm font-mono font-semibold ' + pctColor(rpmPct)}>{s.rpm.limit ? s.rpm.used + '/' + s.rpm.limit : '∞'}</div></div>
            <div><div className="text-xs text-slate-400">TPM</div><div className={'text-sm font-mono font-semibold ' + pctColor(tpmPct)}>{s.tpm.limit ? fmtNum(s.tpm.used) + '/' + fmtNum(s.tpm.limit) : '∞'}</div></div>
          </div>
          {open ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
        </div>
      </div>
      {open && (
        <div className="px-5 pb-4 border-t border-slate-100 pt-4 space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <ProgressBar pct={rpmPct} used={s.rpm.used} total={s.rpm.limit} label="RPM" />
            <ProgressBar pct={tpmPct} used={s.tpm.used} total={s.tpm.limit} label="TPM" />
          </div>
          <HistoryTable history={s.history} />
          <ProviderTable providers={s.providers} />
          <ApiKeyTable apikeys={s.apikeys} />
        </div>
      )}
    </div>
  );
}

/* ── ComboInput: searchable dropdown that also allows free-form input ── */
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

  // Close on outside click
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

  // Fetch all providers to build suggestion lists
  const { data: providersData } = useQuery({
    queryKey: ['providers-for-suggestions'],
    queryFn: async () => { const r = await providersApi.list(); return r.data; },
    staleTime: 60000,
  });

  // Build suggestion options from providers data
  const { modelOptions, providerTypeOptions, providerIdOptions } = useMemo(() => {
    const providers = providersData ?? [];
    // Model names: deduplicated, from all provider models (alias or name)
    const modelSet = new Map<string, string>(); // value -> sub info
    const typeSet = new Set<string>();
    const providerList: ComboOption[] = [{ value: '', label: '空 (共享)', sub: '不指定具体账号' }];

    for (const p of providers) {
      const pType = (p as any).type || (p as any).provider_type || '';
      typeSet.add(pType);
      providerList.push({
        value: String(p.id),
        label: `${p.name}`,
        sub: `#${p.id} · ${pType}`,
      });
      const models = (p as any).models || [];
      for (const m of models) {
        const alias = (m as any).alias;
        const name = (m as any).name;
        const displayName = alias || name;
        if (displayName && !modelSet.has(displayName)) {
          modelSet.set(displayName, `${p.name} · ${pType}`);
        }
        // Also add original name if alias is different
        if (alias && name && alias !== name && !modelSet.has(name)) {
          modelSet.set(name, `${p.name} · ${pType} (原名)`);
        }
      }
    }

    const modelOptions: ComboOption[] = Array.from(modelSet.entries()).map(([v, sub]) => ({
      value: v, label: v, sub,
    }));
    const providerTypeOptions: ComboOption[] = Array.from(typeSet).sort().map(t => ({
      value: t, label: t,
    }));

    return { modelOptions, providerTypeOptions, providerIdOptions: providerList };
  }, [providersData]);

  // When model_name is selected, auto-fill provider_type if unambiguous
  const handleModelChange = (v: string) => {
    setForm(prev => {
      const next = { ...prev, model_name: v };
      // Try to auto-detect provider_type from the selected model
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

  // When provider_type changes, filter providerIdOptions
  const filteredProviderIdOptions = useMemo(() => {
    if (!form.provider_type || !providersData) return providerIdOptions;
    return providerIdOptions.filter(o => {
      if (o.value === '') return true; // always show "shared" option
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
            options={modelOptions} placeholder="搜索或输入模型名" disabled={isEdit} />
        </div>
        <div>
          <label className="text-xs text-slate-500 mb-1 block">供应商类型</label>
          <ComboInput value={form.provider_type} onChange={v => setForm({ ...form, provider_type: v })}
            options={providerTypeOptions} placeholder="搜索或输入类型" disabled={isEdit} />
        </div>
        <div>
          <label className="text-xs text-slate-500 mb-1 block">供应商账号 <span className="text-slate-400">(可选)</span></label>
          <ComboInput value={form.provider_id} onChange={v => setForm({ ...form, provider_id: v })}
            options={filteredProviderIdOptions} placeholder="空=共享" disabled={isEdit} />
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
        <button onClick={onDone} className="px-3 py-1.5 text-sm rounded-lg border hover:bg-slate-50 flex items-center gap-1"><X className="w-3.5 h-3.5" />{t('rateLimits.cancel')}</button>
        <button onClick={save} disabled={!form.model_name || !form.provider_type} className="px-3 py-1.5 text-sm rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 flex items-center gap-1"><Save className="w-3.5 h-3.5" />{t('rateLimits.save')}</button>
      </div>
    </div>
  );
}

export default function RateLimits() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { selectedWorkspace } = useWorkspace();
  const selectedWsId = selectedWorkspace?.id ?? null;
  const [showForm, setShowForm] = useState(false);
  const [editItem, setEditItem] = useState<{ id: number; model_name: string; provider_type: string; provider_id: number | null; rpm: number | null; tpm: number | null } | null>(null);

  // Workspace-level rate limits for globally selected workspace
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

  if (wsLoading) return <div className="flex items-center justify-center h-64"><div className="animate-spin w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full" /></div>;

  const wsLimits = wsData?.rate_limits ?? [];

  // Compute workspace summary
  const totalRpmUsed = wsLimits.reduce((sum, rl) => sum + (rl.rpm?.used ?? 0), 0);
  const totalTpmUsed = wsLimits.reduce((sum, rl) => sum + (rl.tpm?.used ?? 0), 0);
  const configuredModels = wsLimits.length;

  // Sort by bottleneck severity (highest usage % first)
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
      <h1 className="text-2xl font-bold text-slate-800 mb-1">{t('rateLimits.title')}</h1>
      <p className="text-sm text-slate-500 mb-6">{t('rateLimits.subtitle')}</p>

      {/* ── Workspace Summary Cards ── */}
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

      {/* ── Workspace Rate Limits ── */}
      <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-semibold text-slate-700 flex items-center gap-2">
              <Globe className="w-5 h-5 text-indigo-500" />
              {t('rateLimits.workspaceLevel')}
              {selectedWorkspace && (
                <span className="text-sm font-normal text-slate-500">— {selectedWorkspace.name}</span>
              )}
            </h2>
            <div className="flex items-center gap-2">
              {selectedWsId && (
                <button onClick={() => { setShowForm(true); setEditItem(null); }}
                  className="flex items-center gap-1 px-3 py-1.5 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700">
                  <Plus className="w-4 h-4" /> {t('rateLimits.addLimit')}
                </button>
              )}
            </div>
          </div>
          <p className="text-xs text-slate-400 mb-3">{t('rateLimits.workspaceSubtitle')}</p>

          {/* Add / Edit form */}
          {showForm && selectedWsId && (
            <div className="mb-4">
              <WsLimitForm wsId={selectedWsId} initial={editItem ?? undefined}
                onDone={() => { setShowForm(false); setEditItem(null); }} />
            </div>
          )}

          {/* Workspace rate limits table — sorted by bottleneck severity */}
          {sortedLimits.length > 0 ? (
            <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-sm">
              <table className="w-full text-sm">
                <thead className="bg-slate-50">
                  <tr className="text-left text-xs text-slate-500 uppercase tracking-wider">
                    <th className="px-4 py-3">{t('rateLimits.modelName')}</th>
                    <th className="px-4 py-3 w-40">RPM</th>
                    <th className="px-4 py-3 w-40">TPM</th>
                    <th className="px-4 py-3 text-right w-20">{t('rateLimits.actions')}</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedLimits.map((rl, i) => {
                    const rpmLim = (rl as any).rpm_limit ?? rl.rpm?.limit;
                    const tpmLim = (rl as any).tpm_limit ?? rl.tpm?.limit;
                    const rpmUsed = rl.rpm?.used ?? 0;
                    const tpmUsed = rl.tpm?.used ?? 0;
                    const rpmPct = rpmLim ? Math.round(rpmUsed / rpmLim * 100) : 0;
                    const tpmPct = tpmLim ? Math.round(tpmUsed / tpmLim * 100) : 0;
                    const maxPct = Math.max(rpmPct, tpmPct);
                    const rlId = (rl as any).id;
                    const providers = rl.providers ?? [];
                    // Check if any provider is bottlenecked
                    const providerMaxPct = providers.reduce((max, p) => {
                      const pRpm = p.rpm_limit ? Math.round(p.rpm_used / p.rpm_limit * 100) : 0;
                      const pTpm = p.tpm_limit ? Math.round(p.tpm_used / p.tpm_limit * 100) : 0;
                      return Math.max(max, pRpm, pTpm);
                    }, 0);
                    const effectiveMaxPct = Math.max(maxPct, providerMaxPct);
                    return (
                      <Fragment key={rl.model_name + '-' + i}>
                        {/* Model row (workspace-level) */}
                        <tr className={`border-t hover:bg-slate-50 ${effectiveMaxPct >= 90 ? 'bg-red-50/50 border-red-100' : effectiveMaxPct >= 75 ? 'bg-amber-50/50 border-amber-100' : 'border-slate-100'}`}>
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2">
                              {effectiveMaxPct >= 90 ? <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0" /> : effectiveMaxPct >= 75 ? <AlertCircle className="w-4 h-4 text-amber-500 flex-shrink-0" /> : null}
                              <div>
                                <span className="font-medium">{rl.model_name}</span>
                                <span className="text-xs text-slate-400 ml-1.5 bg-slate-100 px-1.5 py-0.5 rounded">{rl.provider_type}{rl.provider_name ? ` · ${rl.provider_name}` : rl.provider_id == null ? ' (共享)' : ''}</span>
                                {providers.length > 0 && <span className="text-xs text-slate-400 ml-1">({providers.length} providers)</span>}
                              </div>
                              {effectiveMaxPct >= 90 && <span className="text-xs bg-red-100 text-red-700 px-1.5 py-0.5 rounded-full font-medium">{effectiveMaxPct}%</span>}
                              {effectiveMaxPct >= 75 && effectiveMaxPct < 90 && <span className="text-xs bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded-full font-medium">{effectiveMaxPct}%</span>}
                            </div>
                          </td>
                          <td className="px-4 py-3">
                            {rpmLim ? (
                              <div className="space-y-1">
                                <div className="flex justify-between text-xs">
                                  <span className={pctColor(rpmPct) + ' font-mono font-medium'}>{rpmUsed}/{rpmLim}</span>
                                  <span className={pctColor(rpmPct) + ' font-medium'}>{rpmPct}%</span>
                                </div>
                                <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
                                  <div className={barColor(rpmPct) + ' h-full rounded-full transition-all'} style={{ width: Math.min(rpmPct, 100) + '%' }} />
                                </div>
                              </div>
                            ) : <span className="text-xs text-slate-400">∞</span>}
                          </td>
                          <td className="px-4 py-3">
                            {tpmLim ? (
                              <div className="space-y-1">
                                <div className="flex justify-between text-xs">
                                  <span className={pctColor(tpmPct) + ' font-mono font-medium'}>{fmtNum(tpmUsed)}/{fmtNum(tpmLim)}</span>
                                  <span className={pctColor(tpmPct) + ' font-medium'}>{tpmPct}%</span>
                                </div>
                                <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
                                  <div className={barColor(tpmPct) + ' h-full rounded-full transition-all'} style={{ width: Math.min(tpmPct, 100) + '%' }} />
                                </div>
                              </div>
                            ) : <span className="text-xs text-slate-400">∞</span>}
                          </td>
                          <td className="px-4 py-3 text-right">
                            <div className="flex justify-end gap-1">
                              <button onClick={() => { setEditItem({ id: rlId, model_name: rl.model_name, provider_type: rl.provider_type || '', provider_id: rl.provider_id ?? null, rpm: rpmLim, tpm: tpmLim }); setShowForm(true); }}
                                className="p-1.5 rounded hover:bg-slate-100" title={t('rateLimits.edit')}><Pencil className="w-3.5 h-3.5 text-slate-500" /></button>
                              <button onClick={() => { if (confirm(t('rateLimits.confirmDelete'))) deleteMut.mutate(rlId); }}
                                className="p-1.5 rounded hover:bg-red-50" title={t('rateLimits.delete')}><Trash2 className="w-3.5 h-3.5 text-red-500" /></button>
                            </div>
                          </td>
                        </tr>
                        {/* Provider sub-rows */}
                        {providers.map((p, j) => {
                          const pRpmPct = p.rpm_limit ? Math.round(p.rpm_used / p.rpm_limit * 100) : 0;
                          const pTpmPct = p.tpm_limit ? Math.round(p.tpm_used / p.tpm_limit * 100) : 0;
                          const pMax = Math.max(pRpmPct, pTpmPct);
                          return (
                            <tr key={`${rl.model_name}-p-${j}`} className={`border-t border-slate-50 ${pMax >= 90 ? 'bg-red-50/30' : pMax >= 75 ? 'bg-amber-50/30' : 'bg-slate-50/50'}`}>
                              <td className="px-4 py-2 pl-10">
                                <div className="flex items-center gap-2 text-xs">
                                  <Server className="w-3 h-3 text-slate-400 flex-shrink-0" />
                                  <span className="text-slate-600">{p.provider_name || '?'}</span>
                                  <span className="text-slate-400">· {p.group_name || '?'}</span>
                                  {pMax >= 90 && <span className="text-[10px] bg-red-100 text-red-600 px-1 py-0.5 rounded font-medium">{pMax}%</span>}
                                  {pMax >= 75 && pMax < 90 && <span className="text-[10px] bg-amber-100 text-amber-600 px-1 py-0.5 rounded font-medium">{pMax}%</span>}
                                </div>
                              </td>
                              <td className="px-4 py-2">
                                {p.rpm_limit ? (
                                  <div className="space-y-0.5">
                                    <div className="flex justify-between text-[11px]">
                                      <span className={pctColor(pRpmPct) + ' font-mono'}>{p.rpm_used}/{p.rpm_limit}</span>
                                      <span className={pctColor(pRpmPct)}>{pRpmPct}%</span>
                                    </div>
                                    <div className="h-1 bg-slate-100 rounded-full overflow-hidden">
                                      <div className={barColor(pRpmPct) + ' h-full rounded-full'} style={{ width: Math.min(pRpmPct, 100) + '%' }} />
                                    </div>
                                  </div>
                                ) : <span className="text-[11px] text-slate-400">∞</span>}
                              </td>
                              <td className="px-4 py-2">
                                {p.tpm_limit ? (
                                  <div className="space-y-0.5">
                                    <div className="flex justify-between text-[11px]">
                                      <span className={pctColor(pTpmPct) + ' font-mono'}>{fmtNum(p.tpm_used)}/{fmtNum(p.tpm_limit)}</span>
                                      <span className={pctColor(pTpmPct)}>{pTpmPct}%</span>
                                    </div>
                                    <div className="h-1 bg-slate-100 rounded-full overflow-hidden">
                                      <div className={barColor(pTpmPct) + ' h-full rounded-full'} style={{ width: Math.min(pTpmPct, 100) + '%' }} />
                                    </div>
                                  </div>
                                ) : <span className="text-[11px] text-slate-400">∞</span>}
                              </td>
                              <td className="px-4 py-2"></td>
                            </tr>
                          );
                        })}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-8 text-slate-400 bg-white border border-slate-200 rounded-xl">
              {selectedWsId ? t('rateLimits.noWsLimits') : t('rateLimits.selectWorkspace')}
            </div>
          )}
        </div>

      {/* ── Workspace Model Detail Cards (with API Key breakdown) ── */}
      {wsLimits.length > 0 && (
        <div className="mt-6 space-y-3">
          {wsLimits.map((rl, i) => (
            <WorkspaceCard key={rl.model_name + '-' + i} status={rl} />
          ))}
        </div>
      )}

    </div>
  );
}
