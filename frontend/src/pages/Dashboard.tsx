import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import client from '../api/client';
import {
  Key, Activity, Cpu, TrendingUp, Zap, Copy, Check, DollarSign,
  Clock, Users, ChevronRight, PieChart, Shield,
  ChevronDown, AlertCircle,
} from 'lucide-react';
import { useState, useMemo } from 'react';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface ApiKeyItem {
  id: number;
  key: string;
  name: string;
  group_id: number | null;
  user_id?: number | null;
  user_name?: string | null;
  is_active: boolean;
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  request_count: number;
  token_count: number;
  group?: { id: number; name: string; description: string | null; created_at: string | null };
}

interface UsageSummary {
  totals: {
    requests: number;
    input_tokens: number;
    output_tokens: number;
    cache_creation_tokens: number;
    cache_tokens: number;
    reasoning_tokens: number;
    output_image_number: number;
    output_video_number: number;
    output_audio_seconds: number;
    web_search_requests: number;
    estimated_cost: number;
  };
  by_model: Array<{
    model_name: string;
    requests: number;
    input_tokens: number;
    output_tokens: number;
    reasoning_tokens: number;
    estimated_cost: number;
  }>;
  by_api_key: Array<{
    api_key_hash: string;
    api_key_preview: string;
    api_key_name: string;
    requests: number;
    input_tokens: number;
    output_tokens: number;
    estimated_cost: number;
  }>;
  by_group: Array<{
    group_id: number;
    group_name: string;
    requests: number;
    input_tokens: number;
    output_tokens: number;
  }>;
  time_series: Array<{
    period: string;
    requests: number;
    input_tokens: number;
    output_tokens: number;
  }>;
}

/* ── Helpers ────────────────────────────────────────────────────────────── */

function fmtNum(n: number): string {
  if (n >= 1_000_000_000) return (n / 1_000_000_000).toFixed(1) + 'B';
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return n.toLocaleString();
}

function fmtCost(n: number): string {
  if (n >= 1000) return '$' + (n / 1000).toFixed(1) + 'K';
  if (n >= 1) return '$' + n.toFixed(2);
  if (n >= 0.01) return '$' + n.toFixed(3);
  if (n > 0) return '$' + n.toFixed(4);
  return '$0.00';
}


/* ── Colors ─────────────────────────────────────────────────────────────── */

const PIE_COLORS = [
  '#6366f1', '#06b6d4', '#f59e0b', '#ef4444', '#10b981',
  '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#3b82f6',
  '#84cc16', '#a855f7',
];

/* ── Sparkline SVG ─────────────────────────────────────────────────────── */

const Sparkline = ({ data, width = 100, height = 32, color = 'rgba(255,255,255,0.6)', fillColor = 'rgba(255,255,255,0.15)' }: {
  data: number[];
  width?: number;
  height?: number;
  color?: string;
  fillColor?: string;
}) => {
  if (data.length < 2) return null;
  const max = Math.max(...data, 1);
  const min = Math.min(...data, 0);
  const range = max - min || 1;
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - ((v - min) / range) * (height * 0.85) - height * 0.05;
    return `${x},${y}`;
  });
  const line = pts.join(' ');
  const area = `0,${height} ${line} ${width},${height}`;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="flex-shrink-0">
      <polyline fill={fillColor} points={area} />
      <polyline fill="none" stroke={color} strokeWidth="1.5" points={line} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
};

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

/* ── Mini bar chart for API key ────────────────────────────────────────── */

const MiniBarChart = ({ values, color = '#6366f1' }: { values: number[]; color?: string }) => {
  const max = Math.max(...values, 1);
  return (
    <div className="flex items-end space-x-[2px] h-6">
      {values.slice(-7).map((v, i) => (
        <div key={i} className="w-[4px] rounded-t-sm transition-all duration-300"
          style={{ height: `${Math.max((v / max) * 100, 8)}%`, backgroundColor: color, opacity: 0.5 + (i / 10) }}
        />
      ))}
    </div>
  );
};

/* ══════════════════════════════════════════════════════════════════════════
   Dashboard
   ══════════════════════════════════════════════════════════════════════════ */

const Dashboard = () => {
  const navigate = useNavigate();
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [expandedModels, setExpandedModels] = useState<Set<string>>(new Set());

  const { data: apiKeys, isLoading: keysLoading } = useQuery({
    queryKey: ['apiKeys'],
    queryFn: async () => (await client.get<ApiKeyItem[]>('/api/apikeys/')).data,
  });

  const { data: usage, isLoading: usageLoading } = useQuery({
    queryKey: ['usage-summary-14d'],
    queryFn: async () => {
      const now = new Date();
      const start = new Date(now.getTime() - 14 * 86400000);
      return (await client.get<UsageSummary>('/api/usage/summary', {
        params: { start: start.toISOString(), end: now.toISOString(), granularity: 'day' },
      })).data;
    },
  });

  const handleCopy = async (key: string) => {
    try {
      if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(key); }
      else { const t = document.createElement('textarea'); t.value = key; t.style.cssText = 'position:fixed;left:-9999px'; document.body.appendChild(t); t.select(); document.execCommand('copy'); document.body.removeChild(t); }
      setCopiedKey(key); setTimeout(() => setCopiedKey(null), 2000);
    } catch { /* */ }
  };

  const toggleModel = (name: string) => {
    setExpandedModels(prev => {
      const next = new Set(prev);
      next.has(name) ? next.delete(name) : next.add(name);
      return next;
    });
  };

  const totals = usage?.totals;
  const totalTokens = (totals?.input_tokens || 0) + (totals?.output_tokens || 0);
  const tsData = usage?.time_series || [];

  const sortedKeys = useMemo(() =>
    apiKeys ? [...apiKeys].sort((a, b) => {
      if (!a.last_used_at && !b.last_used_at) return 0;
      if (!a.last_used_at) return 1;
      if (!b.last_used_at) return -1;
      return new Date(b.last_used_at).getTime() - new Date(a.last_used_at).getTime();
    }) : []
  , [apiKeys]);

  const modelSlices: DonutSlice[] = (usage?.by_model || [])
    .sort((a, b) => (b.estimated_cost || 0) - (a.estimated_cost || 0))
    .map((m, i) => ({ label: m.model_name, value: m.estimated_cost || 0, color: PIE_COLORS[i % PIE_COLORS.length] }));

  const tokenSlices: DonutSlice[] = totals ? [
    { label: '输入 Tokens', value: totals.input_tokens, color: '#3b82f6' },
    { label: '输出 Tokens', value: totals.output_tokens, color: '#10b981' },
    { label: '推理 Tokens', value: totals.reasoning_tokens, color: '#f59e0b' },
    { label: '缓存 Tokens', value: totals.cache_tokens + totals.cache_creation_tokens, color: '#8b5cf6' },
  ].filter(s => s.value > 0) : [];

  const loading = keysLoading || usageLoading;

  /* ── Render ───────────────────────────────────────────────────────────── */

  return (
    <div className="space-y-5 pb-6">

      {/* ━━ Header ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">控制台</h1>
          <p className="text-sm text-slate-400 mt-0.5">近 14 天 · 全部数据概览</p>
        </div>
        <div className="flex items-center space-x-2 px-4 py-2 bg-emerald-50 border border-emerald-200 rounded-xl">
          <div className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse" />
          <span className="text-sm font-medium text-emerald-700">全部系统运行正常</span>
        </div>
      </div>

      {/* ━━ Stat Cards with Sparklines ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {([
          { label: '消费金额', value: fmtCost(totals?.estimated_cost || 0), icon: DollarSign,
            gradient: 'from-emerald-500 to-emerald-600', sparkData: tsData.map(t => t.requests * 0.003), sparkColor: 'rgba(255,255,255,0.7)' },
          { label: 'Token 量额', value: fmtNum(totalTokens), icon: TrendingUp,
            gradient: 'from-blue-500 to-blue-600', sparkData: tsData.map(t => t.input_tokens + t.output_tokens), sparkColor: 'rgba(255,255,255,0.7)' },
          { label: '请求次数', value: fmtNum(totals?.requests || 0), icon: Zap,
            gradient: 'from-orange-400 to-orange-500', sparkData: tsData.map(t => t.requests), sparkColor: 'rgba(255,255,255,0.7)' },
          { label: '模型数', value: String(usage?.by_model?.length ?? 0), icon: Cpu,
            gradient: 'from-violet-500 to-violet-600', sparkData: tsData.map(t => t.requests), sparkColor: 'rgba(255,255,255,0.7)' },
        ] as const).map((c) => (
          <div key={c.label} className={`relative overflow-hidden bg-gradient-to-br ${c.gradient} rounded-2xl p-5 text-white shadow-lg`}>
            <div className="flex items-center justify-between">
              <div className="flex-1 min-w-0">
                <div className="flex items-center space-x-2 mb-1">
                  <div className="w-7 h-7 bg-white/20 rounded-lg flex items-center justify-center">
                    <c.icon className="w-3.5 h-3.5" />
                  </div>
                  <span className="text-xs font-medium text-white/80">{c.label}</span>
                </div>
                <p className="text-2xl font-bold tracking-tight">{c.value}</p>
              </div>
              <div className="flex-shrink-0 ml-2 opacity-90">
                <Sparkline data={c.sparkData} width={80} height={36} color={c.sparkColor} />
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* ━━ Three Column Main Section ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-5">

        {/* ── Left: API Keys ─────────────────────────────────────────── */}
        <div className="xl:col-span-4 bg-white rounded-2xl shadow-sm border border-slate-200/80 overflow-hidden flex flex-col">
          <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between flex-shrink-0">
            <div className="flex items-center space-x-2.5">
              <div className="w-8 h-8 bg-blue-50 rounded-lg flex items-center justify-center">
                <Shield className="w-4 h-4 text-blue-600" />
              </div>
              <div>
                <h2 className="text-sm font-bold text-slate-800">API Keys 使用与安全状态</h2>
              </div>
            </div>
          </div>

          <div className="px-4 py-2 border-b border-slate-50 bg-slate-50/50 flex items-center text-xs text-slate-400 font-medium">
            <span className="flex-1">Key 名称</span>
            <span className="w-20 text-center">近14天活跃</span>
            <span className="w-12 text-right">状态</span>
          </div>

          <div className="flex-1 overflow-y-auto divide-y divide-slate-50" style={{ maxHeight: '420px' }}>
            {loading ? (
              <div className="flex items-center justify-center py-16">
                <div className="w-6 h-6 border-2 border-blue-200 border-t-blue-500 rounded-full animate-spin" />
              </div>
            ) : sortedKeys.length === 0 ? (
              <div className="text-center py-12 text-slate-400">
                <Key className="w-8 h-8 mx-auto mb-2 text-slate-200" />
                <p className="text-sm">暂无 API Key</p>
              </div>
            ) : sortedKeys.slice(0, 8).map((k) => (
              <div
                key={k.id}
                onClick={() => navigate(`/apikeys/${k.id}`)}
                className="px-4 py-3 hover:bg-blue-50/50 cursor-pointer group transition-colors"
              >
                <div className="flex items-center">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center space-x-2">
                      <span className="font-semibold text-sm text-slate-800 truncate group-hover:text-blue-600 transition-colors">
                        {k.name}
                      </span>
                      {k.is_active ? (
                        <span className="w-2 h-2 bg-emerald-400 rounded-full flex-shrink-0" />
                      ) : (
                        <AlertCircle className="w-3.5 h-3.5 text-amber-400 flex-shrink-0" />
                      )}
                    </div>
                    <div className="flex items-center space-x-2 mt-1">
                      <code className="text-xs text-slate-400 font-mono">
                        {k.key.substring(0, 10)}···{k.key.slice(-4)}
                      </code>
                      <button
                        onClick={(e) => { e.stopPropagation(); handleCopy(k.key); }}
                        className="text-slate-300 hover:text-blue-500 transition-colors p-0.5"
                      >
                        {copiedKey === k.key ? <Check className="w-3 h-3 text-emerald-500" /> : <Copy className="w-3 h-3" />}
                      </button>
                      {k.group?.name && (
                        <span className="text-xs text-slate-400 flex items-center">
                          <Users className="w-3 h-3 mr-0.5 text-slate-300" />{k.group.name}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="w-20 flex items-center justify-center flex-shrink-0">
                    <MiniBarChart values={tsData.map(t => t.requests)} color={k.is_active ? '#6366f1' : '#cbd5e1'} />
                  </div>
                  <div className="w-12 flex items-center justify-end flex-shrink-0">
                    <span className="text-xs text-slate-400 flex items-center">
                      <Clock className="w-3 h-3 mr-0.5" />
                    </span>
                    <ChevronRight className="w-3.5 h-3.5 text-slate-200 group-hover:text-blue-400 transition-colors" />
                  </div>
                </div>
              </div>
            ))}
          </div>

          {sortedKeys.length > 8 && (
            <div className="px-4 py-3 border-t border-slate-100 flex-shrink-0">
              <button onClick={() => navigate('/apikeys')}
                className="text-xs text-blue-500 hover:text-blue-700 font-medium flex items-center space-x-1 w-full justify-center">
                <span>查看全部 {sortedKeys.length} 个 Key</span>
                <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
        </div>

        {/* ── Middle: Charts ──────────────────────────────────────────── */}
        <div className="xl:col-span-5 space-y-5">
          {/* Donut Row */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200/80 overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-100 flex items-center space-x-2.5">
              <div className="w-8 h-8 bg-indigo-50 rounded-lg flex items-center justify-center">
                <PieChart className="w-4 h-4 text-indigo-600" />
              </div>
              <h2 className="text-sm font-bold text-slate-800">用量与费用分布对照</h2>
            </div>

            <div className="p-5">
              {usageLoading ? (
                <LoadingPlaceholder />
              ) : (
                <div className="grid grid-cols-2 gap-6">
                  {/* Token Distribution */}
                  <div>
                    <h3 className="text-xs font-bold text-slate-600 mb-3">Token 分布</h3>
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
                    <h3 className="text-xs font-bold text-slate-600 mb-3">模型费用分布</h3>
                    <div className="flex flex-col items-center">
                      <DonutChart slices={modelSlices} size={130} strokeWidth={22}
                        centerValue={fmtCost(totals?.estimated_cost || 0)} centerLabel="总费用" />
                      <div className="mt-3 space-y-1.5 w-full max-h-[120px] overflow-y-auto">
                        {modelSlices.map((s, i) => {
                          const total = modelSlices.reduce((a, sl) => a + sl.value, 0) || 1;
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
          </div>

          {/* Stacked Bar Trend */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200/80 overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
              <div className="flex items-center space-x-2.5">
                <div className="w-8 h-8 bg-blue-50 rounded-lg flex items-center justify-center">
                  <Activity className="w-4 h-4 text-blue-600" />
                </div>
                <h2 className="text-sm font-bold text-slate-800">请求数与 Token 趋势（14 天）</h2>
              </div>
              <div className="flex items-center space-x-3 text-xs">
                <span className="flex items-center space-x-1"><span className="w-2.5 h-2.5 bg-blue-400 rounded-sm" /><span className="text-slate-500">请求数</span></span>
                <span className="flex items-center space-x-1"><span className="w-2.5 h-2.5 bg-emerald-400 rounded-sm" /><span className="text-slate-500">Prompt</span></span>
                <span className="flex items-center space-x-1"><span className="w-2.5 h-2.5 bg-amber-400 rounded-sm" /><span className="text-slate-500">Completion</span></span>
              </div>
            </div>
            <div className="p-5">
              {usageLoading ? <LoadingPlaceholder /> : tsData.length > 0 ? (
                <StackedBarChart data={tsData} />
              ) : (
                <EmptyState text="暂无趋势数据" />
              )}
            </div>
          </div>
        </div>

        {/* ── Right: Rankings & Metrics ───────────────────────────────── */}
        <div className="xl:col-span-3 space-y-5">
          {/* Spending Ranking */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200/80 overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-100 flex items-center space-x-2.5">
              <div className="w-8 h-8 bg-amber-50 rounded-lg flex items-center justify-center">
                <DollarSign className="w-4 h-4 text-amber-600" />
              </div>
              <h2 className="text-sm font-bold text-slate-800">消费排行</h2>
            </div>
            <div className="p-4">
              {usageLoading ? <LoadingPlaceholder /> : usage?.by_api_key && usage.by_api_key.length > 0 ? (
                <div className="space-y-3">
                  {usage.by_api_key
                    .sort((a, b) => (b.estimated_cost || 0) - (a.estimated_cost || 0))
                    .slice(0, 5)
                    .map((item, idx) => {
                      const medals = ['🥇', '🥈', '🥉'];
                      return (
                        <div key={idx} className="flex items-center justify-between">
                          <div className="flex items-center space-x-2 min-w-0">
                            <span className="w-5 text-center flex-shrink-0 text-sm">
                              {idx < 3 ? medals[idx] : <span className="text-xs font-bold text-slate-400">{idx + 1}</span>}
                            </span>
                            <span className="text-sm text-slate-700 truncate font-medium">{item.api_key_name || '未命名'}</span>
                          </div>
                          <span className="text-sm font-bold text-amber-600 flex-shrink-0 ml-2 tabular-nums">
                            {fmtCost(item.estimated_cost || 0)}
                          </span>
                        </div>
                      );
                    })}
                </div>
              ) : <EmptyState text="暂无消费" />}
            </div>
          </div>

          {/* Real-time Performance (simplified) */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200/80 overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-100 flex items-center space-x-2.5">
              <div className="w-8 h-8 bg-emerald-50 rounded-lg flex items-center justify-center">
                <Zap className="w-4 h-4 text-emerald-600" />
              </div>
              <h2 className="text-sm font-bold text-slate-800">实时性能</h2>
            </div>
            <div className="p-4 space-y-4">
              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-slate-500">日均请求量 (Request/day)</span>
                  <span className="text-sm font-bold text-slate-700 tabular-nums">
                    {tsData.length > 0 ? Math.round(tsData.reduce((s, t) => s + t.requests, 0) / tsData.length).toLocaleString() : '0'}
                  </span>
                </div>
                <Sparkline data={tsData.map(t => t.requests)} width={220} height={40}
                  color="#10b981" fillColor="rgba(16,185,129,0.1)" />
              </div>

              <div className="border-t border-slate-100 pt-3">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-slate-500">日均 Token 量</span>
                  <span className="text-sm font-bold text-slate-700 tabular-nums">
                    {tsData.length > 0 ? fmtNum(Math.round(tsData.reduce((s, t) => s + t.input_tokens + t.output_tokens, 0) / tsData.length)) : '0'}
                  </span>
                </div>
                <Sparkline data={tsData.map(t => t.input_tokens + t.output_tokens)} width={220} height={40}
                  color="#6366f1" fillColor="rgba(99,102,241,0.1)" />
              </div>
            </div>
          </div>

          {/* Token breakdown mini cards */}
          {totals && totals.requests > 0 && (
            <div className="bg-white rounded-2xl shadow-sm border border-slate-200/80 p-4">
              <h3 className="text-xs font-bold text-slate-600 mb-3 flex items-center space-x-1.5">
                <Activity className="w-3.5 h-3.5 text-blue-500" />
                <span>Token 明细</span>
              </h3>
              <div className="grid grid-cols-2 gap-2">
                {[
                  { label: '输入', value: fmtNum(totals.input_tokens), color: 'border-l-blue-500' },
                  { label: '输出', value: fmtNum(totals.output_tokens), color: 'border-l-emerald-500' },
                  { label: '推理', value: fmtNum(totals.reasoning_tokens), color: 'border-l-amber-500' },
                  { label: '缓存', value: fmtNum(totals.cache_tokens), color: 'border-l-violet-500' },
                ].map(t => (
                  <div key={t.label} className={`border-l-2 ${t.color} pl-2 py-1`}>
                    <p className="text-xs text-slate-400">{t.label}</p>
                    <p className="text-sm font-bold text-slate-700">{t.value}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ━━ Model Detail Table ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      {usage?.by_model && usage.by_model.length > 0 && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200/80 overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-100 flex items-center space-x-2.5">
            <div className="w-8 h-8 bg-violet-50 rounded-lg flex items-center justify-center">
              <Cpu className="w-4 h-4 text-violet-600" />
            </div>
            <h2 className="text-sm font-bold text-slate-800">模型详细统计与服务利用</h2>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50/80 border-b border-slate-200">
                  <th className="text-left py-3 px-4 font-semibold text-slate-500 text-xs">模型名称</th>
                  <th className="text-right py-3 px-4 font-semibold text-slate-500 text-xs">
                    <span className="inline-flex items-center space-x-1">
                      <span>请求数</span>
                    </span>
                  </th>
                  <th className="text-right py-3 px-4 font-semibold text-slate-500 text-xs">Tokens ↓</th>
                  <th className="text-right py-3 px-4 font-semibold text-slate-500 text-xs">费用 ↑</th>
                  <th className="text-left py-3 px-4 font-semibold text-slate-500 text-xs w-36">用量比比</th>
                </tr>
              </thead>
              <tbody>
                {usage.by_model
                  .sort((a, b) => (b.estimated_cost || 0) - (a.estimated_cost || 0))
                  .map((m, idx) => {
                    const totalCost = usage.by_model.reduce((s, x) => s + (x.estimated_cost || 0), 0) || 1;
                    const costPct = ((m.estimated_cost || 0) / totalCost) * 100;
                    const totalTok = m.input_tokens + m.output_tokens;
                    const color = PIE_COLORS[idx % PIE_COLORS.length];
                    const isExpanded = expandedModels.has(m.model_name);
                    const subRows = [
                      { name: 'Prompt', count: m.requests, tokens: m.input_tokens, cost: (m.estimated_cost || 0) * (m.input_tokens / (totalTok || 1)) },
                      { name: 'Completion', count: m.requests, tokens: m.output_tokens, cost: (m.estimated_cost || 0) * (m.output_tokens / (totalTok || 1)) },
                    ];
                    if (m.reasoning_tokens > 0) {
                      subRows.push({ name: 'Reasoning', count: 0, tokens: m.reasoning_tokens, cost: 0 });
                    }

                    return (
                      <ModelTableRow
                        key={idx}
                        model={m}
                        idx={idx}
                        color={color}
                        costPct={costPct}
                        totalTok={totalTok}
                        isExpanded={isExpanded}
                        onToggle={() => toggleModel(m.model_name)}
                        subRows={subRows}
                        totalCost={totalCost}
                      />
                    );
                  })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};

/* ── Model Table Row (expandable) ──────────────────────────────────────── */

interface ModelRowProps {
  model: { model_name: string; requests: number; input_tokens: number; output_tokens: number; reasoning_tokens: number; estimated_cost: number };
  idx: number;
  color: string;
  costPct: number;
  totalTok: number;
  isExpanded: boolean;
  onToggle: () => void;
  subRows: Array<{ name: string; count: number; tokens: number; cost: number }>;
  totalCost: number;
}

const ModelTableRow = ({ model: m, color, costPct, totalTok, isExpanded, onToggle, subRows, totalCost }: ModelRowProps) => {
  return (
    <>
      <tr className="border-b border-slate-100 hover:bg-slate-50/60 transition-colors cursor-pointer group" onClick={onToggle}>
        <td className="py-3 px-4">
          <div className="flex items-center space-x-2">
            <ChevronDown className={`w-3.5 h-3.5 text-slate-400 transition-transform ${isExpanded ? '' : '-rotate-90'}`} />
            <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: color }} />
            <span className="font-semibold text-slate-800">{m.model_name}</span>
            <span className="text-xs text-slate-400">{m.requests}次</span>
          </div>
        </td>
        <td className="py-3 px-4 text-right text-slate-600 font-medium tabular-nums">{m.requests.toLocaleString()}</td>
        <td className="py-3 px-4 text-right text-slate-500 tabular-nums">{fmtNum(totalTok)}</td>
        <td className="py-3 px-4 text-right font-bold text-amber-600 tabular-nums">{fmtCost(m.estimated_cost || 0)}</td>
        <td className="py-3 px-4">
          <div className="flex items-center space-x-2">
            <div className="flex-1 bg-slate-100 rounded-full h-2 overflow-hidden">
              <div className="h-2 rounded-full transition-all duration-700"
                style={{ width: `${Math.max(costPct, 2)}%`, backgroundColor: color }} />
            </div>
            <span className="text-xs text-slate-400 w-12 text-right tabular-nums">{costPct.toFixed(1)}%</span>
          </div>
        </td>
      </tr>
      {isExpanded && subRows.map((sub, si) => {
        const subPct = (sub.tokens / (totalCost > 0 ? totalTok : 1)) * 100;
        const barColor = si === 0 ? '#3b82f6' : si === 1 ? '#10b981' : '#f59e0b';
        return (
          <tr key={si} className="bg-slate-50/50 border-b border-slate-50">
            <td className="py-2 px-4 pl-14">
              <span className="text-xs font-medium text-slate-500">{sub.name}</span>
              {sub.count > 0 && <span className="text-xs text-slate-400 ml-2">{sub.count}次</span>}
            </td>
            <td className="py-2 px-4 text-right text-slate-400 text-xs tabular-nums">{sub.count > 0 ? sub.count.toLocaleString() : '-'}</td>
            <td className="py-2 px-4 text-right text-slate-400 text-xs tabular-nums">{fmtNum(sub.tokens)}</td>
            <td className="py-2 px-4 text-right text-slate-400 text-xs tabular-nums">{fmtCost(sub.cost)}</td>
            <td className="py-2 px-4">
              <div className="flex-1 bg-slate-100 rounded-full h-1.5 overflow-hidden">
                <div className="h-1.5 rounded-full transition-all duration-500"
                  style={{ width: `${Math.max(subPct, 2)}%`, backgroundColor: barColor }} />
              </div>
            </td>
          </tr>
        );
      })}
    </>
  );
};

/* ── Stacked Bar Chart ─────────────────────────────────────────────────── */

const StackedBarChart = ({ data }: { data: Array<{ period: string; requests: number; input_tokens: number; output_tokens: number }> }) => {
  const maxVal = Math.max(...data.map(d => d.requests + d.input_tokens / 1000 + d.output_tokens / 1000), 1);
  const [hovered, setHovered] = useState<number | null>(null);

  return (
    <div className="relative">
      {/* Y axis labels */}
      <div className="absolute left-0 top-0 h-44 flex flex-col justify-between text-xs text-slate-400 tabular-nums pr-2" style={{ width: '40px' }}>
        <span>{fmtNum(maxVal)}</span>
        <span>{fmtNum(maxVal / 2)}</span>
        <span>0</span>
      </div>

      <div className="ml-11">
        <div className="flex items-end space-x-[3px] h-44 relative">
          {data.map((d, i) => {
            const reqH = (d.requests / maxVal) * 100;
            const promptH = ((d.input_tokens / 1000) / maxVal) * 100;
            const compH = ((d.output_tokens / 1000) / maxVal) * 100;
            return (
              <div key={i} className="flex-1 flex flex-col items-center relative group"
                onMouseEnter={() => setHovered(i)} onMouseLeave={() => setHovered(null)}>
                <div className="w-full flex flex-col-reverse">
                  <div className="w-full bg-blue-400 rounded-t-sm transition-all" style={{ height: `${Math.max(reqH, 1)}px` }} />
                  <div className="w-full bg-emerald-400 transition-all" style={{ height: `${Math.max(promptH, 0)}px` }} />
                  <div className="w-full bg-amber-400 rounded-t-sm transition-all" style={{ height: `${Math.max(compH, 0)}px` }} />
                </div>

                {hovered === i && (
                  <div className="absolute -top-[80px] left-1/2 -translate-x-1/2 bg-slate-800 text-white text-xs px-3 py-2 rounded-lg whitespace-nowrap z-20 shadow-xl">
                    <div className="font-semibold mb-1">{d.period.slice(5, 10)}</div>
                    <div className="flex items-center space-x-1"><span className="w-2 h-2 bg-emerald-400 rounded-sm" /><span>Prompt</span><span className="font-bold ml-1">{fmtNum(d.input_tokens)}</span></div>
                    <div className="flex items-center space-x-1"><span className="w-2 h-2 bg-amber-400 rounded-sm" /><span>Completion</span><span className="font-bold ml-1">{fmtNum(d.output_tokens)}</span></div>
                    <div className="flex items-center space-x-1"><span className="w-2 h-2 bg-blue-400 rounded-sm" /><span>请求</span><span className="font-bold ml-1">{d.requests.toLocaleString()}</span></div>
                    <div className="absolute bottom-0 left-1/2 -translate-x-1/2 translate-y-1/2 w-2 h-2 bg-slate-800 rotate-45" />
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* X axis */}
        <div className="flex justify-between text-xs text-slate-400 mt-2">
          {data.map((d, i) => (
            i % Math.ceil(data.length / 7) === 0 || i === data.length - 1 ? (
              <span key={i} className="tabular-nums">{d.period.slice(8, 10)}日</span>
            ) : <span key={i} />
          ))}
        </div>
      </div>
    </div>
  );
};

/* ── Loading / Empty ───────────────────────────────────────────────────── */

const LoadingPlaceholder = () => (
  <div className="flex items-center justify-center py-10">
    <div className="w-6 h-6 border-2 border-slate-200 border-t-blue-400 rounded-full animate-spin" />
  </div>
);

const EmptyState = ({ text }: { text: string }) => (
  <div className="text-center py-8 text-slate-400 text-sm">{text}</div>
);

export default Dashboard;
