import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import client from '../api/client';
import type {
  ApiKeyDetailData, TimeSeries, TimeSeriesByModel,
} from '../api/types';
import {
  Key, ArrowLeft, Copy, Check, Cpu, DollarSign, TrendingUp, Zap,
  Clock, Users, Shield, Gauge, List, BarChart3,
} from 'lucide-react';
import { useState } from 'react';
import UsageRecordsTable from '../components/UsageRecordsTable';
import DailyCostByModelChart from './ApiKeyDetail/DailyCostByModelChart';
import BudgetBars from './ApiKeyDetail/BudgetBars';
import BudgetEditModal from './ApiKeyDetail/BudgetEditModal';
import CompressionSettingsModal from './ApiKeyDetail/CompressionSettingsModal';
import { fmtNum, fmtCost, fmtDate, fmtPrice } from './ApiKeyDetail/utils';
import { Search } from 'lucide-react';
import { fuzzyMatchTokens } from '../utils/fuzzyMatch';

/** Fuzzy match: every whitespace-separated token must appear in at least one
 *  of name / alias / provider (case-insensitive, ignoring symbols). */
function fuzzyMatchModel(query: string, model: { name: string; alias?: string | null; provider_name?: string | null }): boolean {
  return fuzzyMatchTokens(query, [model.name, model.alias, model.provider_name]);
}

/* ── Component ─────────────────────────────────────────────────────────── */

function currencySymbol(currency: string): string {
  if (currency === 'CNY') return '¥';
  if (currency === 'EUR') return '€';
  if (currency === 'GBP') return '£';
  if (currency === 'JPY') return '¥';
  return '$';
}

const ApiKeyDetail = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [copiedKey, setCopiedKey] = useState(false);
  const [activeTab, setActiveTab] = useState<'overview' | 'models' | 'model_usage' | 'usage'>('overview');
  const [costDays, setCostDays] = useState(7);
  const [showBudgetModal, setShowBudgetModal] = useState(false);
  const [showCompressModal, setShowCompressModal] = useState(false);
  const [modelSearch, setModelSearch] = useState('');

  const { data, isLoading, error } = useQuery({
    queryKey: ['apiKeyDetail', id],
    queryFn: async () => {
      const res = await client.get<ApiKeyDetailData>(`/api/apikeys/${id}/detail`);
      return res.data;
    },
    enabled: !!id,
  });

  // Fetch user's role and permissions for this key's group
  const { data: myRoleData } = useQuery<{ permissions: Record<string, boolean>; role: string }>({
    queryKey: ['my-role', data?.group_id],
    queryFn: async () => {
      const res = await client.get(`/api/permissions/groups/${data!.group_id}/my-role`);
      return res.data;
    },
    enabled: !!data?.group_id,
  });

  const permissions = myRoleData?.permissions || {};
  const canManageBudget = useMemo(
    () => permissions['apikey.unlimited_budget'] === true || permissions['apikey.add_budget'] === true,
    [permissions],
  );

  // Fetch hourly time series for the last 24 hours (scoped by api_key_hash)
  const now = new Date();
  const oneDayAgo = new Date(now.getTime() - 24 * 60 * 60 * 1000);
  const tsParams = {
    start: oneDayAgo.toISOString(),
    end: now.toISOString(),
    granularity: 'hour',
    ...(data?.api_key_hash ? { api_key_hash: data.api_key_hash } : {}),
  };
  const { data: timeSeries } = useQuery<TimeSeries[]>({
    queryKey: ['apikey-time-series', id, data?.api_key_hash],
    queryFn: async () => {
      const res = await client.get('/api/usage/summary/time_series', { params: tsParams });
      return res.data;
    },
    enabled: !!data?.api_key_hash && activeTab === 'overview',
  });

  // Fetch hourly cost-by-model time series for the last 24 hours (scoped by api_key_hash)
  const { data: hourlyCostByModel } = useQuery<TimeSeriesByModel[]>({
    queryKey: ['apikey-hourly-cost-by-model', id, data?.api_key_hash],
    queryFn: async () => {
      const res = await client.get('/api/usage/summary/time_series_by_model', { params: tsParams });
      return res.data;
    },
    enabled: !!data?.api_key_hash && activeTab === 'overview',
  });

  // Fetch daily cost-by-model time series (scoped by api_key_hash)
  const costStart = new Date(Date.now() - costDays * 86400000);
  const costByModelParams = {
    start: costStart.toISOString(),
    end: new Date().toISOString(),
    granularity: 'day',
    ...(data?.api_key_hash ? { api_key_hash: data.api_key_hash } : {}),
  };
  const { data: costByModel } = useQuery<TimeSeriesByModel[]>({
    queryKey: ['apikey-cost-by-model', id, data?.api_key_hash, costDays],
    queryFn: async () => {
      const res = await client.get('/api/usage/summary/time_series_by_model', { params: costByModelParams });
      return res.data;
    },
    enabled: !!data?.api_key_hash && activeTab === 'overview',
  });

  const handleCopyKey = async () => {
    if (!data) return;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(data.key);
      } else {
        const ta = document.createElement('textarea');
        ta.value = data.key;
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      }
      setCopiedKey(true);
      setTimeout(() => setCopiedKey(false), 2000);
    } catch { /* ignore */ }
  };

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="text-slate-400">加载中...</div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="text-center py-16">
        <Key className="w-12 h-12 mx-auto mb-3 text-slate-300" />
        <p className="text-slate-500">API Key 不存在或无权访问</p>
        <button onClick={() => navigate('/')} className="mt-4 text-blue-500 hover:text-blue-600 text-sm">
          返回首页
        </button>
      </div>
    );
  }

  const budget = data.budget_info;
  const usage = data.usage;
  const ytdTotalTokens = (usage.ytd_input_tokens || 0) + (usage.ytd_output_tokens || 0) + (usage.ytd_reasoning_tokens || 0);
  const mtdTotalTokens = (usage.mtd_input_tokens || 0) + (usage.mtd_output_tokens || 0) + (usage.mtd_reasoning_tokens || 0);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center space-x-4">
        <button
          onClick={() => navigate(-1)}
          className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-xl transition-colors"
          title="返回"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>
        <div className="flex-1">
          <div className="flex items-center space-x-3">
            <h1 className="text-xl font-bold text-slate-800">{data.name}</h1>
            <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
              data.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'
            }`}>
              {data.is_active ? '启用' : '禁用'}
            </span>
            {data.group?.name && (
              <span className="flex items-center text-xs text-slate-400 bg-slate-100 px-2 py-0.5 rounded-full">
                <Users className="w-3 h-3 mr-1" />
                {data.group.name}
              </span>
            )}
          </div>
          <div className="flex items-center space-x-2 mt-1.5">
            <code className="text-xs text-slate-400 font-mono bg-slate-50 px-2.5 py-1 rounded-lg">
              {data.key.substring(0, 12)}...{data.key.slice(-4)}
            </code>
            <button onClick={handleCopyKey} className="text-slate-300 hover:text-blue-500 transition-colors" title="复制">
              {copiedKey ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
            </button>
            <span className="text-xs text-slate-400 ml-2">
              <Clock className="w-3 h-3 inline mr-1" />
              创建于 {fmtDate(data.created_at)}
            </span>
            {data.expires_at && (
              <span className="text-xs text-slate-400">· 过期 {fmtDate(data.expires_at)}</span>
            )}
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-slate-200">
        <nav className="flex space-x-8">
          {[
            { key: 'overview', label: '概览', icon: Zap, color: 'blue' },
            { key: 'models', label: '可用模型', icon: Shield, count: data.available_models.length, color: 'emerald' },
            { key: 'model_usage', label: '模型消耗', icon: Cpu, count: data.by_model.length, color: 'violet' },
            { key: 'usage', label: '消耗明细', icon: List, color: 'rose' },
          ].map(({ key, label, icon: Icon, color, count }) => {
            const active = activeTab === key;
            return (
              <button
                key={key}
                onClick={() => setActiveTab(key as typeof activeTab)}
                className={`py-4 px-1 border-b-2 font-medium text-sm flex items-center space-x-2 transition-colors ${
                  active
                    ? `border-${color}-500 text-${color}-600`
                    : 'border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300'
                }`}
              >
                <Icon className="w-4 h-4" />
                <span>{label}</span>
                {count != null && (
                  <span className={`px-2 py-0.5 rounded-full text-xs ${active ? `bg-${color}-100 text-${color}-700` : 'bg-slate-100 text-slate-600'}`}>
                    {count}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </div>

      {/* ── Overview Tab ────────────────────────────────────────────────── */}
      {activeTab === 'overview' && (
        <>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Budget Bars Card */}
          <BudgetBars
            budgets={data.budgets || []}
            remaining={data.total_budget_remaining || 0}
            unlimitedBudget={budget.unlimited_budget}
            onEdit={() => setShowBudgetModal(true)}
            canManageBudget={canManageBudget}
          />

          {/* Compression Settings Card */}
          {(() => {
            const compressPolicy = data.policies?.find(p => p.policy_type === 'compress') || null;
            return (
              <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-4">
                <div className="flex items-center space-x-2 mb-2.5">
                  <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-cyan-400 to-cyan-600 flex items-center justify-center shadow-md shadow-cyan-200/50">
                    <Gauge className="w-3.5 h-3.5 text-white" />
                  </div>
                  <h3 className="text-sm font-bold text-slate-800">记录压缩</h3>
                </div>
                {compressPolicy ? (
                  <div className="text-sm">
                    <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${compressPolicy.enabled ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-500'}`}>
                      {compressPolicy.enabled ? '已启用' : '已禁用'}
                    </span>
                    {compressPolicy.enabled && (
                      <div className="mt-2 text-xs text-slate-500 space-y-0.5">
                        <div>每分钟: {compressPolicy.config?.per_minute ?? '-'}</div>
                        <div>每小时: {compressPolicy.config?.per_hour ?? '-'}</div>
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="text-sm text-slate-400">未配置</p>
                )}
                <button
                  onClick={() => setShowCompressModal(true)}
                  className="mt-2.5 text-xs font-medium text-indigo-500 hover:text-indigo-700 transition-colors"
                >
                  设置 →
                </button>
              </div>
            );
          })()}

          {/* Token Stats */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-4 relative overflow-hidden">
            {/* Decorative gradient overlay */}
            <div className="absolute -top-6 -right-6 w-20 h-20 bg-linear-to-br from-emerald-200/20 to-transparent rounded-full blur-xl" />
            <div className="relative z-10">
              <div className="flex items-center space-x-2 mb-2.5">
                <div className="w-7 h-7 rounded-lg bg-linear-to-br from-emerald-400 to-emerald-600 flex items-center justify-center shadow-md shadow-emerald-200/50">
                  <TrendingUp className="w-3.5 h-3.5 text-white" />
                </div>
                <h3 className="text-sm font-bold text-slate-800">Token 消耗</h3>
              </div>
              <div className="grid grid-cols-2 gap-1.5 mb-2">
                <div className="bg-linear-to-br from-blue-50 to-blue-100/50 rounded-lg p-2 border border-blue-200/50">
                  <p className="text-[11px] text-blue-500 font-medium mb-0.5">今年</p>
                  <p className="text-base font-bold text-blue-700 leading-tight">
                    {fmtNum(ytdTotalTokens)}
                  </p>
                </div>
                <div className="bg-linear-to-br from-emerald-50 to-emerald-100/50 rounded-lg p-2 border border-emerald-200/50">
                  <p className="text-[11px] text-emerald-500 font-medium mb-0.5">当月</p>
                  <p className="text-base font-bold text-emerald-700 leading-tight">
                    {fmtNum(mtdTotalTokens)}
                  </p>
                </div>
              </div>
              <div className="space-y-0.5 text-xs">
                <div className="flex justify-between py-0.5 px-2">
                  <span className="text-slate-500">输入(年/月)</span>
                  <span className="font-medium text-slate-700">
                    {fmtNum(usage.ytd_input_tokens || 0)} / {fmtNum(usage.mtd_input_tokens || 0)}
                  </span>
                </div>
                <div className="flex justify-between py-0.5 px-2">
                  <span className="text-slate-500">输出(年/月)</span>
                  <span className="font-medium text-slate-700">
                    {fmtNum(usage.ytd_output_tokens || 0)} / {fmtNum(usage.mtd_output_tokens || 0)}
                  </span>
                </div>
                {(usage.ytd_reasoning_tokens || 0) > 0 || (usage.mtd_reasoning_tokens || 0) > 0 ? (
                  <div className="flex justify-between py-0.5 px-2">
                    <span className="text-slate-500">推理(年/月)</span>
                    <span className="font-medium text-violet-700">
                      {fmtNum(usage.ytd_reasoning_tokens || 0)} / {fmtNum(usage.mtd_reasoning_tokens || 0)}
                    </span>
                  </div>
                ) : null}
              </div>
            </div>
          </div>

          {/* Request & Generation Stats */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-4 relative overflow-hidden">
            {/* Decorative gradient overlay */}
            <div className="absolute -top-6 -right-6 w-20 h-20 bg-gradient-to-br from-amber-200/20 to-transparent rounded-full blur-xl" />
            <div className="relative z-10">
              <div className="flex items-center space-x-2 mb-2.5">
                <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-amber-400 to-orange-600 flex items-center justify-center shadow-md shadow-amber-200/50">
                  <Zap className="w-3.5 h-3.5 text-white" />
                </div>
                <h3 className="text-sm font-bold text-slate-800">消费总览</h3>
              </div>
              <div className="grid grid-cols-2 gap-1.5 mb-2">
                <div className="bg-gradient-to-br from-blue-50 to-blue-100/50 rounded-lg p-2 border border-blue-200/50">
                  <p className="text-[11px] text-blue-500 font-medium mb-0.5">今年</p>
                  <p className="text-base font-bold text-blue-700 leading-tight">
                    {fmtCost(usage.ytd_cost || 0)}
                  </p>
                </div>
                <div className="bg-gradient-to-br from-emerald-50 to-emerald-100/50 rounded-lg p-2 border border-emerald-200/50">
                  <p className="text-[11px] text-emerald-500 font-medium mb-0.5">当月</p>
                  <p className="text-base font-bold text-emerald-700 leading-tight">
                    {fmtCost(usage.mtd_cost || 0)}
                  </p>
                </div>
              </div>
              <div className="space-y-0.5">
                {[
                  { label: '请求数', value: usage.requests.toLocaleString(), color: 'text-slate-700' },
                  ...((usage.total_image_count || 0) > 0 ? [{ label: '🖼️ 图片', value: `${(usage.total_image_count || 0).toLocaleString()}`, color: 'text-pink-600' }] : []),
                  ...((usage.total_video_count || 0) > 0 ? [{ label: '🎬 视频', value: `${(usage.total_video_count || 0).toLocaleString()}`, color: 'text-purple-600' }] : []),
                  ...((usage.total_audio_seconds || 0) > 0 ? [{ label: '🔊 音频', value: `${(usage.total_audio_seconds || 0).toFixed(1)}s`, color: 'text-cyan-600' }] : []),
                  { label: '最近使用', value: fmtDate(data.last_used_at), color: 'text-slate-600' },
                ].map((item, i) => (
                  <div key={i} className="flex justify-between text-xs py-1 px-2 rounded hover:bg-slate-50/80 transition-colors">
                    <span className="text-slate-500">{item.label}</span>
                    <span className={`font-semibold ${item.color}`}>{item.value}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Hourly Charts — Token consumption & Cost by Model */}
        {timeSeries && timeSeries.length > 0 && (() => {
          const d = timeSeries;
          const TOP_PAD = 28, LEFT_PAD = 55, BAR_H = 150, BOTTOM = TOP_PAD + BAR_H;
          const X_LABEL_H = 50, TOTAL_H = BOTTOM + X_LABEL_H;
          const GROUP_W = Math.max(16, Math.min(40, Math.floor(800 / d.length)));
          const BAR_W = Math.max(8, GROUP_W - 6);
          const CHART_W = Math.max(700, d.length * GROUP_W + LEFT_PAD + 30);
          const labelEvery = d.length > 96 ? Math.ceil(d.length / 16) : d.length > 48 ? Math.ceil(d.length / 16) : d.length > 24 ? 4 : 2;

          const HourlyBarChart = ({ title, icon, values, color, fmtY, legendLabel }: {
            title: string; icon: React.ReactNode; values: number[];
            color: string; fmtY: (n: number) => string; legendLabel: string;
          }) => {
            const [hovered, setHovered] = useState<number | null>(null);
            const maxVal = Math.max(...values, 1);
            const yTicks = [0, 0.25, 0.5, 0.75, 1].map(f => ({
              val: maxVal * f, y: BOTTOM - Math.round(f * BAR_H),
            }));
            return (
              <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
                <h2 className="font-bold text-slate-800 mb-4 flex items-center gap-2 text-sm">
                  {icon}
                  {title} <span className="text-xs text-slate-400 font-normal">（近 24 小时）</span>
                </h2>
                <div className="overflow-x-auto">
                  <div className="relative rounded-xl bg-gradient-to-b from-slate-50/50 to-transparent p-1">
                    <div className="flex items-center gap-4 mb-3 px-2 text-xs">
                      <span className="text-slate-500">
                        峰值 <span className="font-semibold text-slate-700">{fmtY(Math.max(...values))}</span>
                      </span>
                      <span className="text-slate-300">|</span>
                      <span className="text-slate-500">
                        平均 <span className="font-semibold text-slate-700">{fmtY(Math.round(values.reduce((a, b) => a + b, 0) / values.length))}</span>
                      </span>
                      <span className="text-slate-300">|</span>
                      <span className="text-slate-500">
                        总计 <span className="font-semibold text-slate-700">{fmtY(values.reduce((a, b) => a + b, 0))}</span>
                      </span>
                    </div>
                    <svg width={CHART_W} height={TOTAL_H} className="w-full" style={{ minHeight: TOTAL_H }}>
                      <defs>
                        <linearGradient id={`bar-grad-${title}`} x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor={color} stopOpacity="1" />
                          <stop offset="100%" stopColor={color} stopOpacity="0.6" />
                        </linearGradient>
                      </defs>
                      {yTicks.map((t, i) => (
                        <g key={`y-${i}`}>
                          <line x1={LEFT_PAD} y1={t.y} x2={CHART_W - 10} y2={t.y} stroke="#e2e8f0" strokeWidth={1} strokeDasharray={i === 0 ? undefined : '4 2'} />
                          <text x={LEFT_PAD - 6} y={t.y + 4} textAnchor="end" fontSize={10} fill="#94a3b8">{fmtY(t.val)}</text>
                        </g>
                      ))}
                      {d.map((item, i) => {
                        const gx = LEFT_PAD + i * GROUP_W;
                        const bx = gx + (GROUP_W - BAR_W) / 2;
                        const h = Math.max(2, Math.round((values[i] / maxVal) * BAR_H));
                        const isHov = hovered === i;
                        const periodStr = item.period.includes('T') && !item.period.endsWith('Z') && !item.period.includes('+') ? item.period + 'Z' : item.period;
                        const periodDate = new Date(periodStr);
                        const label = `${String(periodDate.getMonth() + 1).padStart(2, '0')}-${String(periodDate.getDate()).padStart(2, '0')} ${String(periodDate.getHours()).padStart(2, '0')}:00`;
                        return (
                          <g key={i}
                            onMouseEnter={() => setHovered(i)}
                            onMouseLeave={() => setHovered(null)}
                            style={{ cursor: 'pointer' }}
                          >
                            {isHov && <rect x={gx} y={TOP_PAD} width={GROUP_W} height={BAR_H} fill="#eef2ff" rx={4} />}
                            <rect
                              x={bx} y={BOTTOM - h} width={BAR_W} height={h}
                              fill={`url(#bar-grad-${title})`}
                              opacity={isHov ? 1 : 0.75}
                              rx={Math.min(3, h / 2)}
                              ry={Math.min(3, h / 2)}
                              className="transition-all duration-200"
                              filter={isHov ? 'brightness(1.1)' : 'none'}
                            />
                            {isHov && (
                              <line x1={gx + GROUP_W / 2} y1={TOP_PAD} x2={gx + GROUP_W / 2} y2={BOTTOM + 4} stroke={color} strokeWidth={1} strokeDasharray="2 2" opacity={0.3} />
                            )}
                            {i % labelEvery === 0 && (
                              <text x={gx + GROUP_W / 2} y={BOTTOM + 8} textAnchor="end" fontSize={9}
                                fill={isHov ? '#334155' : '#94a3b8'} fontWeight={isHov ? '600' : '400'}
                                transform={`rotate(-45, ${gx + GROUP_W / 2}, ${BOTTOM + 8})`}>{label}</text>
                            )}
                          </g>
                        );
                      })}
                      {hovered !== null && (() => {
                        const cx = LEFT_PAD + hovered * GROUP_W + GROUP_W / 2;
                        const tipW = 150;
                        const tipX = Math.min(Math.max(cx - tipW / 2, 4), CHART_W - tipW - 4);
                        const hPeriodStr = d[hovered].period.includes('T') && !d[hovered].period.endsWith('Z') && !d[hovered].period.includes('+') ? d[hovered].period + 'Z' : d[hovered].period;
                        const hDate = new Date(hPeriodStr);
                        const timeLabel = `${String(hDate.getMonth() + 1).padStart(2, '0')}-${String(hDate.getDate()).padStart(2, '0')} ${String(hDate.getHours()).padStart(2, '0')}:00`;
                        return (
                          <g>
                            <rect x={tipX} y={1} width={tipW} height={28} rx={8} fill="#1e293b" opacity={0.95} />
                            <text x={tipX + tipW / 2} y={16} textAnchor="middle" fontSize={10} fill="white" fontWeight="500">
                              {timeLabel}
                            </text>
                            <text x={tipX + tipW / 2} y={24} textAnchor="middle" fontSize={9} fill="#94a3b8">
                              {legendLabel}: <tspan fill={color} fontWeight="600">{fmtY(values[hovered])}</tspan>
                            </text>
                          </g>
                        );
                      })()}
                    </svg>
                  </div>
                </div>
              </div>
            );
          };

          return (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <HourlyBarChart
                title="Token 消耗趋势"
                icon={<TrendingUp className="w-5 h-5 text-indigo-500" />}
                values={d.map(x => x.input_tokens + x.output_tokens)}
                color="#6366f1"
                fmtY={fmtNum}
                legendLabel="Input + Output Tokens"
              />
              {/* Hourly Cost by Model Stacked Bar Chart */}
              <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
                <h2 className="font-bold text-slate-800 mb-4 flex items-center gap-2 text-sm">
                  <DollarSign className="w-5 h-5 text-amber-500" />
                  金额消耗趋势 <span className="text-xs text-slate-400 font-normal">（近 24 小时，按模型分组）</span>
                </h2>
                <DailyCostByModelChart data={hourlyCostByModel || []} />
              </div>
            </div>
          );
        })()}

        {/* ── Daily Cost by Model Stacked Bar Chart ───────────────────── */}
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-bold text-slate-800 flex items-center space-x-2">
              <BarChart3 className="w-4 h-4 text-indigo-500" />
              <span>每日模型消费统计</span>
            </h3>
            <select value={costDays} onChange={(e) => setCostDays(Number(e.target.value))}
              className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 bg-white">
              <option value={7}>近 7 天</option>
              <option value={14}>近 14 天</option>
              <option value={30}>近 30 天</option>
            </select>
          </div>
          <DailyCostByModelChart data={costByModel || []} />
        </div>
        </>
      )}

      {/* ── Available Models Tab ─────────────────────────────────────────── */}
      {activeTab === 'models' && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center space-x-2">
              <Shield className="w-5 h-5 text-blue-500" />
              <h2 className="text-base font-bold text-slate-800">可用模型</h2>
              <span className="text-xs text-slate-400 ml-2">
                {data.allowed_models.length > 0 ? `限制 ${data.allowed_models.length} 个模型` : '不限制'}
                 · 共 {data.available_models.length} 个可用
              </span>
            </div>
            <div className="relative">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={modelSearch}
                onChange={(e) => setModelSearch(e.target.value)}
                placeholder="搜索模型名称、别名、供应商..."
                className="pl-9 pr-4 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm text-slate-700 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all w-64"
              />
            </div>
          </div>
          {(() => {
            const filtered = data.available_models.filter(m => fuzzyMatchModel(modelSearch, m));
            return filtered.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200">
                    <th className="text-left py-2.5 px-3 font-medium text-slate-500 text-xs uppercase">模型</th>
                    <th className="text-left py-2.5 px-3 font-medium text-slate-500 text-xs uppercase">别名</th>
                    <th className="text-left py-2.5 px-3 font-medium text-slate-500 text-xs uppercase">供应商</th>
                    <th className="text-center py-2.5 px-3 font-medium text-slate-500 text-xs uppercase">
                      <div className="flex items-center justify-center space-x-1">
                        <Gauge className="w-3 h-3" />
                        <span>RPM</span>
                      </div>
                    </th>
                    <th className="text-center py-2.5 px-3 font-medium text-slate-500 text-xs uppercase">
                      <div className="flex items-center justify-center space-x-1">
                        <Gauge className="w-3 h-3" />
                        <span>TPM</span>
                      </div>
                    </th>
                    <th className="text-right py-2.5 px-3 font-medium text-slate-500 text-xs uppercase">输入价格</th>
                    <th className="text-right py-2.5 px-3 font-medium text-slate-500 text-xs uppercase">输出价格</th>
                    <th className="text-right py-2.5 px-3 font-medium text-slate-500 text-xs uppercase">折扣</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((m, idx) => (
                    <tr key={idx} className="border-b border-slate-50 hover:bg-slate-100 transition-colors">
                      <td className="py-2.5 px-3 font-medium text-slate-800">{m.name}</td>
                      <td className="py-2.5 px-3 text-slate-500">{m.alias || '-'}</td>
                      <td className="py-2.5 px-3 text-slate-500">{m.provider_name || '-'}</td>
                      <td className="py-2.5 px-3 text-center">
                        <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                          m.rpm ? 'bg-blue-50 text-blue-600' : 'bg-slate-50 text-slate-400'
                        }`}>
                          {m.rpm ? m.rpm.toLocaleString() : '∞'}
                        </span>
                      </td>
                      <td className="py-2.5 px-3 text-center">
                        <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                          m.tpm ? 'bg-emerald-50 text-emerald-600' : 'bg-slate-50 text-slate-400'
                        }`}>
                          {m.tpm ? fmtNum(m.tpm) : '∞'}
                        </span>
                      </td>
                      <td className="py-2.5 px-3 text-right text-slate-600">
                        {currencySymbol(m.currency)}{fmtPrice(m.input_price)}/1M
                      </td>
                      <td className="py-2.5 px-3 text-right text-slate-600">
                        {currencySymbol(m.currency)}{fmtPrice(m.output_price)}/1M
                      </td>
                      <td className="py-2.5 px-3 text-right">
                        {m.discount < 1 ? (
                          <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-amber-50 text-amber-600">
                            {(m.discount * 10).toFixed(1)}折
                          </span>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-8 text-slate-400 text-sm">
              {modelSearch ? '没有匹配的模型' : '暂无可用模型'}
            </div>
          );
          })()}
        </div>
      )}

      {/* ── Model Usage Breakdown Tab ────────────────────────────────────── */}
      {activeTab === 'model_usage' && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
          <div className="flex items-center space-x-2 mb-4">
            <Cpu className="w-5 h-5 text-violet-500" />
            <h2 className="text-base font-bold text-slate-800">模型消耗统计</h2>
            <span className="text-xs text-slate-400 ml-2">全部历史</span>
          </div>
          {data.by_model.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200">
                    <th className="text-left py-2.5 px-3 font-medium text-slate-500 text-xs uppercase">#</th>
                    <th className="text-left py-2.5 px-3 font-medium text-slate-500 text-xs uppercase">模型</th>
                    <th className="text-right py-2.5 px-3 font-medium text-slate-500 text-xs uppercase">请求数</th>
                    <th className="text-right py-2.5 px-3 font-medium text-slate-500 text-xs uppercase">输入</th>
                    <th className="text-right py-2.5 px-3 font-medium text-slate-500 text-xs uppercase">输出</th>
                    <th className="text-right py-2.5 px-3 font-medium text-slate-500 text-xs uppercase">总 Tokens</th>
                    <th className="text-right py-2.5 px-3 font-medium text-slate-500 text-xs uppercase">费用</th>
                    <th className="text-left py-2.5 px-3 font-medium text-slate-500 text-xs uppercase w-28">占比</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_model.map((m, idx) => {
                    const total = m.input_tokens + m.output_tokens;
                    const totalCost = data.by_model.reduce((s, x) => s + (x.estimated_cost || 0), 0) || 1;
                    const pct = ((m.estimated_cost || 0) / totalCost) * 100;
                    const colors = [
                      'bg-blue-400', 'bg-emerald-400', 'bg-amber-400', 'bg-violet-400',
                      'bg-rose-400', 'bg-cyan-400', 'bg-orange-400', 'bg-indigo-400',
                    ];
                    return (
                      <tr key={idx} className="border-b border-slate-50 hover:bg-slate-100 transition-colors">
                        <td className="py-2.5 px-3">
                          <span className="w-5 h-5 bg-slate-100 rounded flex items-center justify-center text-xs font-bold text-slate-500">
                            {idx + 1}
                          </span>
                        </td>
                        <td className="py-2.5 px-3 font-medium text-slate-800">{m.model_name}</td>
                        <td className="py-2.5 px-3 text-right text-slate-600">{m.requests.toLocaleString()}</td>
                        <td className="py-2.5 px-3 text-right text-slate-500">{fmtNum(m.input_tokens)}</td>
                        <td className="py-2.5 px-3 text-right text-slate-500">{fmtNum(m.output_tokens)}</td>
                        <td className="py-2.5 px-3 text-right font-medium text-slate-700">{fmtNum(total)}</td>
                        <td className="py-2.5 px-3 text-right font-semibold text-amber-600">{fmtCost(m.estimated_cost)}</td>
                        <td className="py-2.5 px-3">
                          <div className="flex items-center space-x-2">
                            <div className="flex-1 bg-slate-100 rounded-full h-1.5">
                              <div
                                className={`h-1.5 rounded-full ${colors[idx % colors.length]} transition-all`}
                                style={{ width: `${Math.max(pct, 1)}%` }}
                              />
                            </div>
                            <span className="text-xs text-slate-400 w-9 text-right">{pct.toFixed(1)}%</span>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr className="border-t border-slate-200 bg-slate-50/50">
                    <td className="py-2.5 px-3" colSpan={2}>
                      <span className="font-bold text-slate-700 text-xs uppercase">合计</span>
                    </td>
                    <td className="py-2.5 px-3 text-right font-bold text-slate-700">{usage.requests.toLocaleString()}</td>
                    <td className="py-2.5 px-3 text-right font-medium text-slate-600">{fmtNum(usage.input_tokens)}</td>
                    <td className="py-2.5 px-3 text-right font-medium text-slate-600">{fmtNum(usage.output_tokens)}</td>
                    <td className="py-2.5 px-3 text-right font-bold text-slate-700">{fmtNum(usage.input_tokens + usage.output_tokens + usage.reasoning_tokens)}</td>
                    <td className="py-2.5 px-3 text-right font-bold text-amber-600">{fmtCost(usage.estimated_cost)}</td>
                    <td className="py-2.5 px-3"></td>
                  </tr>
                </tfoot>
              </table>
            </div>
          ) : (
            <div className="text-center py-8">
              <Cpu className="w-10 h-10 mx-auto mb-2 text-slate-200" />
              <p className="text-slate-400 text-sm">暂无使用记录</p>
            </div>
          )}
        </div>
      )}

      {/* ── Usage Records Tab ────────────────────────────────────────────── */}
      {activeTab === 'usage' && data.api_key_hash && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
          <div className="flex items-center space-x-2 mb-4">
            <List className="w-5 h-5 text-rose-500" />
            <h2 className="text-base font-bold text-slate-800">消耗明细</h2>
            <span className="text-xs text-slate-400 ml-2">每次请求的详细记录</span>
          </div>
          <UsageRecordsTable apiKeyHash={data.api_key_hash} />
        </div>
      )}

      {/* ── Budget Edit Modal ─────────────────────────────────────────────── */}
      {showBudgetModal && (
        <BudgetEditModal
          apiKeyId={data.id}
          isUnlimitedBudget={budget.unlimited_budget}
          currentRemaining={data.total_budget_remaining || budget.remaining || 0}
          budgets={data.budgets || []}
          onClose={() => setShowBudgetModal(false)}
          permissions={permissions}
        />
      )}

      {/* ── Compression Settings Modal ───────────────────────────────────── */}
      {showCompressModal && (
        <CompressionSettingsModal
          apiKeyId={data.id}
          policy={data.policies?.find(p => p.policy_type === 'compress') || null}
          onClose={() => setShowCompressModal(false)}
        />
      )}
    </div>
  );
};

export default ApiKeyDetail;