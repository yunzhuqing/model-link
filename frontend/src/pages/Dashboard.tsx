import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import client from '../api/client';
import {
  Key, Cpu, TrendingUp, Zap, Copy, Check, DollarSign,
  Users, ChevronRight, PieChart, MessageCircle, Sparkles, MessagesSquare,
} from 'lucide-react';
import { useState, useMemo } from 'react';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface GroupItem {
  id: number;
  name: string;
  description: string;
  created_at: string;
}

interface ApiKeyItem {
  id: number;
  key: string;
  name: string;
  group_id: number | null;
  user_id: number | null;
  is_active: boolean;
  created_at: string;
  group?: { id: number; name: string; description: string | null };
}

interface UsageTotals {
  requests: number;
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_tokens: number;
  reasoning_tokens: number;
  total_cost: number;
}

interface UsageByModel {
  model_name: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  total_cost: number;
  total_cost_usd: number;
}

interface CurrencyCost {
  currency: string;
  total_cost_native: number;
  total_cost_usd: number;
}

interface UsageByCurrency {
  currencies: CurrencyCost[];
  total_cost_usd: number;
}

/* ── Helpers ────────────────────────────────────────────────────────────── */

function fmtNum(n: number): string {
  if (n >= 1_000_000_000) return (n / 1_000_000_000).toFixed(1) + 'B';
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return n.toLocaleString();
}

function fmtCost(n: number | string | null | undefined): string {
  const v = Number(n) || 0;
  if (v >= 1000) return '$' + (v / 1000).toFixed(1) + 'K';
  if (v >= 1) return '$' + v.toFixed(2);
  if (v >= 0.01) return '$' + v.toFixed(3);
  if (v > 0) return '$' + v.toFixed(4);
  return '$0.00';
}

function fmtCostWithSymbol(n: number | string | null | undefined, currency: string): string {
  const v = Number(n) || 0;
  const sym = currency === 'CNY' ? '¥' : currency === 'USD' ? '$' : currency + ' ';
  if (v >= 1000) return sym + (v / 1000).toFixed(1) + 'K';
  if (v >= 1) return sym + v.toFixed(2);
  if (v >= 0.01) return sym + v.toFixed(3);
  if (v > 0) return sym + v.toFixed(4);
  return sym + '0.00';
}

/* ── Colors ─────────────────────────────────────────────────────────────── */

const PIE_COLORS = [
  '#6366f1', '#06b6d4', '#f59e0b', '#ef4444', '#10b981',
  '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#3b82f6',
  '#84cc16', '#a855f7',
];

/* ── Donut Chart ───────────────────────────────────────────────────────── */

interface DonutSlice { label: string; value: number; color: string; }

const DonutChart = ({ slices, size = 140, strokeWidth = 24, centerValue, centerLabel }: {
  slices: DonutSlice[];
  size?: number;
  strokeWidth?: number;
  centerValue?: string;
  centerLabel?: string;
}) => {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const total = slices.reduce((s, d) => s + d.value, 0) || 1;
  const c = size / 2;
  let cum = 0;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <circle cx={c} cy={c} r={radius} fill="none" stroke="#f1f5f9" strokeWidth={strokeWidth} />
      {slices.map((sl, i) => {
        const pct = sl.value / total;
        const offset = circumference * (1 - pct);
        const rot = cum * 360 - 90;
        cum += pct;
        return (
          <circle key={i} cx={c} cy={c} r={radius} fill="none" stroke={sl.color}
            strokeWidth={strokeWidth} strokeDasharray={`${circumference}`}
            strokeDashoffset={offset} strokeLinecap="round"
            transform={`rotate(${rot} ${c} ${c})`}
            className="transition-all duration-700"
          />
        );
      })}
      {centerValue && (
        <>
          <text x={c} y={c - 4} textAnchor="middle" style={{ fontSize: '15px', fontWeight: 700 }} className="fill-slate-800">{centerValue}</text>
          {centerLabel && <text x={c} y={c + 12} textAnchor="middle" style={{ fontSize: '10px' }} className="fill-slate-400">{centerLabel}</text>}
        </>
      )}
    </svg>
  );
};

/* ══════════════════════════════════════════════════════════════════════════
   Dashboard
   ══════════════════════════════════════════════════════════════════════════ */

const Dashboard = () => {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [copiedUrl, setCopiedUrl] = useState<string | null>(null);
  const origin = useMemo(() => window.location.origin, []);

  // ── Data queries ──────────────────────────────────────────────────────────
  const { data: groups, isLoading: groupsLoading } = useQuery<GroupItem[]>({
    queryKey: ['groups'],
    queryFn: async () => (await client.get('/api/groups/')).data,
  });

  const { data: apiKeys, isLoading: keysLoading } = useQuery<ApiKeyItem[]>({
    queryKey: ['apiKeys'],
    queryFn: async () => (await client.get('/api/apikeys/')).data,
  });

  // Usage data: last 14 days
  const _now = useMemo(() => new Date(), []);
  const _start14d = useMemo(() => new Date(_now.getTime() - 14 * 86400000), [_now]);
  const _dashParams = useMemo(() => ({
    start: _start14d.toISOString(),
    end: _now.toISOString(),
  }), [_start14d, _now]);

  // Get current user info to filter usage by user_id
  const { data: userInfo } = useQuery<{ id: number; username: string }>({
    queryKey: ['currentUser'],
    queryFn: async () => (await client.get('/users/me')).data,
  });

  // Usage queries filtered by current user's user_id
  const _userParams = useMemo(() => ({
    ..._dashParams,
    ...(userInfo?.id ? { user_id: String(userInfo.id) } : {}),
  }), [_dashParams, userInfo]);

  const { data: totals, isLoading: totalsLoading } = useQuery<UsageTotals>({
    queryKey: ['dash-totals', _userParams],
    queryFn: async () => (await client.get('/api/usage/summary/totals', { params: _userParams })).data,
    enabled: !!userInfo,
  });

  const { data: byModel, isLoading: byModelLoading } = useQuery<UsageByModel[]>({
    queryKey: ['dash-by-model', _userParams],
    queryFn: async () => (await client.get('/api/usage/summary/by_model', { params: _userParams })).data,
    enabled: !!userInfo,
  });

  const { data: byCurrency, isLoading: byCurrencyLoading } = useQuery<UsageByCurrency>({
    queryKey: ['dash-by-currency', _userParams],
    queryFn: async () => (await client.get('/api/usage/summary/by_currency', { params: _userParams })).data,
    enabled: !!userInfo,
  });

  // ── Handlers ──────────────────────────────────────────────────────────────
  const handleCopy = async (key: string) => {
    try {
      if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(key); }
      else { const t = document.createElement('textarea'); t.value = key; t.style.cssText = 'position:fixed;left:-9999px'; document.body.appendChild(t); t.select(); document.execCommand('copy'); document.body.removeChild(t); }
      setCopiedKey(key); setTimeout(() => setCopiedKey(null), 2000);
    } catch { /* */ }
  };


  // ── Derived data ──────────────────────────────────────────────────────────
  // Filter API keys to show only the current user's keys
  const myApiKeys = useMemo(() => {
    if (!apiKeys || !userInfo) return [];
    return apiKeys.filter(k => k.user_id === userInfo.id);
  }, [apiKeys, userInfo]);

  const totalTokens = (totals?.input_tokens || 0) + (totals?.output_tokens || 0);

  const modelCostSlices: DonutSlice[] = (byModel || [])
    .sort((a, b) => (b.total_cost_usd || 0) - (a.total_cost_usd || 0))
    .map((m, i) => ({ label: m.model_name, value: m.total_cost_usd || 0, color: PIE_COLORS[i % PIE_COLORS.length] }));

  const tokenSlices: DonutSlice[] = totals ? [
    { label: '输入 Tokens', value: totals.input_tokens, color: '#3b82f6' },
    { label: '输出 Tokens', value: totals.output_tokens, color: '#10b981' },
    { label: '推理 Tokens', value: totals.reasoning_tokens, color: '#f59e0b' },
    { label: '缓存 Tokens', value: (totals.cache_tokens || 0) + (totals.cache_creation_tokens || 0), color: '#8b5cf6' },
  ].filter(s => s.value > 0) : [];

  const loading = groupsLoading || keysLoading || totalsLoading || byModelLoading || byCurrencyLoading;

  /* ── Render ───────────────────────────────────────────────────────────── */

  return (
    <div className="space-y-5 pb-6">

      {/* ━━ Header ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">{t('dashboard.title')}</h1>
          <p className="text-sm text-slate-400 mt-0.5">{t('dashboard.subtitle')}</p>
        </div>
        <div className="flex items-center space-x-2 px-4 py-2 bg-emerald-50 border border-emerald-200 rounded-xl">
          <div className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse" />
          <span className="text-sm font-medium text-emerald-700">{t('common.systemNormal')}</span>
        </div>
      </div>

      {/* ━━ KPI Cards ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {/* 1. 参与的分组数 */}
        <div
          onClick={() => navigate('/groups')}
          className="relative overflow-hidden bg-gradient-to-br from-violet-500 to-violet-600 rounded-2xl p-5 text-white shadow-lg cursor-pointer hover:shadow-xl transition-shadow"
        >
          <div className="flex items-center space-x-2 mb-1">
            <div className="w-7 h-7 bg-white/20 rounded-lg flex items-center justify-center">
              <Users className="w-3.5 h-3.5" />
            </div>
            <span className="text-xs font-medium text-white/80">{t('dashboard.groupCount')}</span>
          </div>
          <p className="text-2xl font-bold">{groups?.length ?? 0}</p>
          <ChevronRight className="absolute right-3 top-1/2 -translate-y-1/2 w-5 h-5 text-white/40" />
        </div>

        {/* 2. 消耗总金额 (USD) */}
        <div className="relative overflow-hidden bg-gradient-to-br from-emerald-500 to-emerald-600 rounded-2xl p-5 text-white shadow-lg">
          <div className="flex items-center space-x-2 mb-1">
            <div className="w-7 h-7 bg-white/20 rounded-lg flex items-center justify-center">
              <DollarSign className="w-3.5 h-3.5" />
            </div>
            <span className="text-xs font-medium text-white/80">{t('dashboard.totalCost')}</span>
          </div>
          <p className="text-2xl font-bold">{fmtCost(byCurrency?.total_cost_usd || 0)}</p>
          {(byCurrency?.currencies?.length ?? 0) >= 1 && (
            <div className="mt-2 space-y-0.5">
              {byCurrency!.currencies.map((c) => (
                <div key={c.currency} className="flex items-center justify-between text-xs text-white/70">
                  <span>{c.currency}</span>
                  <span className="tabular-nums">{fmtCostWithSymbol(c.total_cost_native, c.currency)}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 3. Token 消耗 */}
        <div className="relative overflow-hidden bg-gradient-to-br from-blue-500 to-blue-600 rounded-2xl p-5 text-white shadow-lg">
          <div className="flex items-center space-x-2 mb-1">
            <div className="w-7 h-7 bg-white/20 rounded-lg flex items-center justify-center">
              <TrendingUp className="w-3.5 h-3.5" />
            </div>
            <span className="text-xs font-medium text-white/80">{t('dashboard.tokenTotal')}</span>
          </div>
          <p className="text-2xl font-bold">{fmtNum(totalTokens)}</p>
        </div>

        {/* 4. 请求次数 */}
        <div className="relative overflow-hidden bg-gradient-to-br from-orange-400 to-orange-500 rounded-2xl p-5 text-white shadow-lg">
          <div className="flex items-center space-x-2 mb-1">
            <div className="w-7 h-7 bg-white/20 rounded-lg flex items-center justify-center">
              <Zap className="w-3.5 h-3.5" />
            </div>
            <span className="text-xs font-medium text-white/80">{t('dashboard.requestCount')}</span>
          </div>
          <p className="text-2xl font-bold">{fmtNum(totals?.requests || 0)}</p>
        </div>
      </div>

      {/* ━━ Main 2-column Section ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-5">

        {/* ── Left: Groups + API Keys ─────────────────────────────────────── */}
        <div className="xl:col-span-5 space-y-5">
          {/* My Groups */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200/80 overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
              <div className="flex items-center space-x-2.5">
                <div className="w-8 h-8 bg-violet-50 rounded-lg flex items-center justify-center">
                  <Users className="w-4 h-4 text-violet-600" />
                </div>
                <h2 className="text-sm font-bold text-slate-800">{t('dashboard.myGroups')}</h2>
              </div>
              <button onClick={() => navigate('/groups')}
                className="text-xs text-blue-500 hover:text-blue-700 font-medium flex items-center">
                {t('common.viewAll')} <ChevronRight className="w-3.5 h-3.5 ml-0.5" />
              </button>
            </div>
            <div className="divide-y divide-slate-50" style={{ maxHeight: '200px', overflowY: 'auto' }}>
              {loading ? (
                <div className="flex items-center justify-center py-10">
                  <div className="w-5 h-5 border-2 border-violet-200 border-t-violet-500 rounded-full animate-spin" />
                </div>
              ) : !groups?.length ? (
                <div className="text-center py-8 text-slate-400 text-sm">{t('dashboard.noGroups')}</div>
              ) : groups.map((g) => (
                <div key={g.id}
                  onClick={() => navigate(`/groups/${g.id}`)}
                  className="px-5 py-3 hover:bg-violet-50/50 cursor-pointer group flex items-center justify-between"
                >
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-slate-800 group-hover:text-violet-600 truncate">{g.name}</p>
                    {g.description && <p className="text-xs text-slate-400 truncate">{g.description}</p>}
                  </div>
                  <ChevronRight className="w-4 h-4 text-slate-200 group-hover:text-violet-400 flex-shrink-0" />
                </div>
              ))}
            </div>
          </div>

          {/* My API Keys */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200/80 overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-100 flex items-center space-x-2.5">
              <div className="w-8 h-8 bg-emerald-50 rounded-lg flex items-center justify-center">
                <Key className="w-4 h-4 text-emerald-600" />
              </div>
              <h2 className="text-sm font-bold text-slate-800">{t('dashboard.myApiKeys')}</h2>
            </div>
            <div className="divide-y divide-slate-50" style={{ maxHeight: '300px', overflowY: 'auto' }}>
              {loading ? (
                <div className="flex items-center justify-center py-10">
                  <div className="w-5 h-5 border-2 border-emerald-200 border-t-emerald-500 rounded-full animate-spin" />
                </div>
              ) : !myApiKeys?.length ? (
                <div className="text-center py-8 text-slate-400 text-sm">{t('dashboard.noApiKeys')}</div>
              ) : myApiKeys.map((k) => (
                <div key={k.id}
                  onClick={() => navigate(`/apikeys/${k.id}`)}
                  className="px-5 py-3 hover:bg-emerald-50/50 cursor-pointer group"
                >
                  <div className="flex items-center justify-between">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center space-x-2">
                        <span className="text-sm font-medium text-slate-800 group-hover:text-emerald-600 truncate transition-colors">{k.name}</span>
                        {k.is_active ? (
                          <span className="w-2 h-2 bg-emerald-400 rounded-full flex-shrink-0" />
                        ) : (
                          <span className="w-2 h-2 bg-slate-300 rounded-full flex-shrink-0" />
                        )}
                        {k.group?.name && (
                          <span className="text-xs text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded truncate">{k.group.name}</span>
                        )}
                      </div>
                      <div className="flex items-center space-x-2 mt-1">
                        <code className="text-xs text-slate-400 font-mono">
                          {k.key.substring(0, 8)}···{k.key.slice(-4)}
                        </code>
                        <button
                          onClick={(e) => { e.stopPropagation(); handleCopy(k.key); }}
                          className="text-slate-300 hover:text-blue-500 transition-colors p-0.5"
                          title="复制 API Key"
                        >
                          {copiedKey === k.key ? <Check className="w-3 h-3 text-emerald-500" /> : <Copy className="w-3 h-3" />}
                        </button>
                      </div>
                    </div>
                    <ChevronRight className="w-4 h-4 text-slate-200 group-hover:text-emerald-400 flex-shrink-0" />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Base URLs */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200/80 overflow-hidden">
            <div className="px-5 py-3 border-b border-slate-100 flex items-center space-x-2.5">
              <div className="w-8 h-8 bg-slate-100 rounded-lg flex items-center justify-center">
                <MessageCircle className="w-4 h-4 text-slate-500" />
              </div>
              <h2 className="text-sm font-bold text-slate-800">{t('dashboard.baseUrlTitle')}</h2>
            </div>
            <div className="divide-y divide-slate-50">
              {[
                { icon: MessageCircle, color: 'text-sky-500', label: t('dashboard.openaiChatCompletions'), url: `${origin}/v1` },
                { icon: Sparkles, color: 'text-emerald-500', label: t('dashboard.openaiResponses'), url: `${origin}/v1` },
                { icon: MessagesSquare, color: 'text-amber-500', label: t('dashboard.anthropicMessages'), url: origin },
              ].map((item) => {
                const Icon = item.icon;
                const isCopied = copiedUrl === item.url;
                return (
                  <div key={item.label} className="px-5 py-2.5 flex items-center justify-between hover:bg-slate-50/50 transition-colors">
                    <div className="flex items-center gap-3 min-w-0">
                      <Icon className={`w-4 h-4 ${item.color} shrink-0`} />
                      <span className="text-xs font-medium text-slate-500 w-44 shrink-0">{item.label}</span>
                      <code className="text-sm text-slate-600 font-mono truncate select-all">{item.url}</code>
                    </div>
                    <button
                      onClick={async () => {
                        try {
                          if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(item.url); }
                          else { const el = document.createElement('textarea'); el.value = item.url; el.style.cssText = 'position:fixed;left:-9999px'; document.body.appendChild(el); el.select(); document.execCommand('copy'); document.body.removeChild(el); }
                          setCopiedUrl(item.url); setTimeout(() => setCopiedUrl(null), 2000);
                        } catch { /* */ }
                      }}
                      className={`shrink-0 p-1.5 rounded-md transition-colors ${
                        isCopied
                          ? 'bg-emerald-50 text-emerald-500'
                          : 'text-slate-300 hover:text-blue-500 hover:bg-blue-50'
                      }`}
                    >
                      {isCopied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* ── Right: Charts ───────────────────────────────────────────────── */}
        <div className="xl:col-span-7 space-y-5">
          {/* Donut charts: Token distribution + Model cost */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200/80 p-6">
            <div className="flex items-center space-x-2.5 mb-5">
              <div className="w-8 h-8 bg-indigo-50 rounded-lg flex items-center justify-center">
                <PieChart className="w-4 h-4 text-indigo-600" />
              </div>
              <h2 className="text-sm font-bold text-slate-800">{t('dashboard.tokenDistribution')} & {t('dashboard.modelCostDistribution')}</h2>
            </div>
            {totalsLoading ? (
              <div className="flex items-center justify-center py-16">
                <div className="w-6 h-6 border-2 border-slate-200 border-t-blue-400 rounded-full animate-spin" />
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-8">
                {/* Token Distribution */}
                <div>
                  <h3 className="text-xs font-bold text-slate-600 mb-3">{t('dashboard.tokenDistribution')}</h3>
                  <div className="flex flex-col items-center">
                    <DonutChart slices={tokenSlices} size={130} strokeWidth={22}
                      centerValue={fmtNum(totalTokens)} centerLabel="总计" />
                    <div className="mt-3 space-y-1.5 w-full">
                      {tokenSlices.map((s, i) => (
                        <div key={i} className="flex items-center justify-between text-xs">
                          <div className="flex items-center space-x-1.5">
                            <div className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: s.color }} />
                            <span className="text-slate-600">{s.label}</span>
                          </div>
                          <span className="font-semibold text-slate-700 tabular-nums">{fmtNum(s.value)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Model Cost Distribution */}
                <div>
                  <h3 className="text-xs font-bold text-slate-600 mb-3">{t('dashboard.modelCostDistribution')}</h3>
                  <div className="flex flex-col items-center">
                    <DonutChart slices={modelCostSlices} size={130} strokeWidth={22}
                      centerValue={fmtCost(byCurrency?.total_cost_usd || 0)} centerLabel="总费用(USD)" />
                    <div className="mt-3 space-y-1.5 w-full max-h-[120px] overflow-y-auto">
                      {modelCostSlices.map((s, i) => {
                        const total = modelCostSlices.reduce((a, sl) => a + sl.value, 0) || 1;
                        return (
                          <div key={i} className="flex items-center justify-between text-xs">
                            <div className="flex items-center space-x-1.5 min-w-0">
                              <div className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ backgroundColor: s.color }} />
                              <span className="text-slate-600 truncate">{s.label}</span>
                            </div>
                            <span className="font-semibold text-slate-500 tabular-nums flex-shrink-0 ml-2">
                              {((s.value / total) * 100).toFixed(1)}%
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Model Detail Table: token & cost per model */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200/80 overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-100 flex items-center space-x-2.5">
              <div className="w-8 h-8 bg-blue-50 rounded-lg flex items-center justify-center">
                <Cpu className="w-4 h-4 text-blue-600" />
              </div>
              <h2 className="text-sm font-bold text-slate-800">{t('dashboard.modelUsageDetail')}</h2>
            </div>

            {byModelLoading ? (
              <div className="flex items-center justify-center py-16">
                <div className="w-6 h-6 border-2 border-slate-200 border-t-blue-400 rounded-full animate-spin" />
              </div>
            ) : !byModel?.length ? (
              <div className="text-center py-12 text-slate-400 text-sm">{t('dashboard.noModelUsage')}</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-slate-50/80 border-b border-slate-200">
                      <th className="text-left py-3 px-4 font-semibold text-slate-500 text-xs">{t('dashboard.modelName')}</th>
                      <th className="text-right py-3 px-4 font-semibold text-slate-500 text-xs">{t('dashboard.requests')}</th>
                      <th className="text-right py-3 px-4 font-semibold text-slate-500 text-xs">{t('dashboard.inputTokens')}</th>
                      <th className="text-right py-3 px-4 font-semibold text-slate-500 text-xs">{t('dashboard.outputTokens')}</th>
                      <th className="text-right py-3 px-4 font-semibold text-slate-500 text-xs">{t('dashboard.reasoningTokens')}</th>
                      <th className="text-right py-3 px-4 font-semibold text-slate-500 text-xs">{t('dashboard.cost')}</th>
                      <th className="text-left py-3 px-4 font-semibold text-slate-500 text-xs w-28">{t('dashboard.proportion')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...byModel]
                      .sort((a, b) => (b.total_cost_usd || 0) - (a.total_cost_usd || 0))
                      .map((m, idx) => {
                        const totalCost = byModel.reduce((s, x) => s + (x.total_cost_usd || 0), 0) || 1;
                        const costPct = ((m.total_cost_usd || 0) / totalCost) * 100;
                        const color = PIE_COLORS[idx % PIE_COLORS.length];
                        return (
                          <tr key={idx} className="border-b border-slate-100 hover:bg-slate-50/60">
                            <td className="py-3 px-4">
                              <div className="flex items-center space-x-2">
                                <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: color }} />
                                <span className="font-medium text-slate-800 truncate">{m.model_name}</span>
                              </div>
                            </td>
                            <td className="py-3 px-4 text-right text-slate-600 tabular-nums">{fmtNum(m.requests)}</td>
                            <td className="py-3 px-4 text-right text-indigo-600 tabular-nums font-mono text-xs">{fmtNum(m.input_tokens)}</td>
                            <td className="py-3 px-4 text-right text-emerald-600 tabular-nums font-mono text-xs">{fmtNum(m.output_tokens)}</td>
                            <td className="py-3 px-4 text-right text-violet-600 tabular-nums font-mono text-xs">{m.reasoning_tokens > 0 ? fmtNum(m.reasoning_tokens) : '—'}</td>
                            <td className="py-3 px-4 text-right font-bold text-amber-600 tabular-nums">{fmtCost(m.total_cost_usd || 0)}</td>
                            <td className="py-3 px-4">
                              <div className="flex items-center space-x-2">
                                <div className="flex-1 bg-slate-100 rounded-full h-1.5 overflow-hidden">
                                  <div className="h-1.5 rounded-full" style={{ width: `${Math.max(costPct, 2)}%`, backgroundColor: color }} />
                                </div>
                                <span className="text-xs text-slate-400 w-10 text-right tabular-nums">{costPct.toFixed(1)}%</span>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
