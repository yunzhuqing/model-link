import { useState, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import client from '../api/client';
import {
  BarChart3,
  TrendingUp,
  Zap,
  Search,
  ChevronLeft,
  ChevronRight,
  Filter,
  RefreshCw,
  Image,
  Video,
  Mic,
  Globe,
  Brain,
  Key,
  Users,
  Cpu,
} from 'lucide-react';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface Totals {
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
}

interface ByModel {
  model_name: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
}

interface ByGroup {
  group_id: number;
  group_name: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
}

interface ByApiKey {
  api_key_hash: string;
  api_key_preview: string;
  api_key_name: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
}

interface TimeSeries {
  period: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
}

interface SummaryData {
  totals: Totals;
  by_model: ByModel[];
  by_group: ByGroup[];
  by_api_key: ByApiKey[];
  time_series: TimeSeries[];
}

interface UsageRecord {
  id: number;
  user_name: string | null;
  group_id: number | null;
  group_name: string | null;
  api_key_preview: string | null;
  api_key_name: string | null;
  model_name: string | null;
  provider_name: string | null;
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_tokens: number;
  reasoning_tokens: number;
  output_image_number: number;
  output_video_number: number;
  output_audio_seconds: number;
  web_search_requests: number;
  created_at: string;
}

interface RecordsData {
  total: number;
  page: number;
  page_size: number;
  pages: number;
  records: UsageRecord[];
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return String(n);
}

function fmtDate(iso: string): string {
  try {
    // Backend returns UTC timestamps without 'Z' suffix — ensure correct parsing
    let utcStr = iso;
    if (!utcStr.endsWith('Z') && !utcStr.includes('+') && !/[-]\d{2}:\d{2}$/.test(utcStr)) {
      utcStr += 'Z';
    }
    return new Date(utcStr).toLocaleString(undefined, {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return iso;
  }
}

// Format a Date as a local datetime string for <input type="datetime-local">
// e.g. "2026-04-14T13:48"  (using the browser's local timezone, not UTC)
function toLocalDateTimeString(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

// Default date range: last 30 days (in local time)
function defaultStart(): string {
  const d = new Date();
  d.setDate(d.getDate() - 30);
  return toLocalDateTimeString(d);
}
function defaultEnd(): string {
  return toLocalDateTimeString(new Date());
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────────────────────────

const StatCard = ({
  icon,
  label,
  value,
  sub,
  color,
}: {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  sub?: string;
  color: string;
}) => {
  const colors: Record<string, { bg: string; border: string; icon: string }> = {
    blue:   { bg: 'bg-blue-50',   border: 'border-blue-100',   icon: 'text-blue-600' },
    emerald:{ bg: 'bg-emerald-50',border: 'border-emerald-100',icon: 'text-emerald-600' },
    violet: { bg: 'bg-violet-50', border: 'border-violet-100', icon: 'text-violet-600' },
    amber:  { bg: 'bg-amber-50',  border: 'border-amber-100',  icon: 'text-amber-600' },
    rose:   { bg: 'bg-rose-50',   border: 'border-rose-100',   icon: 'text-rose-600' },
    indigo: { bg: 'bg-indigo-50', border: 'border-indigo-100', icon: 'text-indigo-600' },
    cyan:   { bg: 'bg-cyan-50',   border: 'border-cyan-100',   icon: 'text-cyan-600' },
    pink:   { bg: 'bg-pink-50',   border: 'border-pink-100',   icon: 'text-pink-600' },
  };
  const c = colors[color] || colors.blue;
  return (
    <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-5 hover:shadow-md transition-shadow">
      <div className={`inline-flex p-2.5 rounded-xl ${c.bg} border ${c.border} mb-3`}>
        <span className={c.icon}>{icon}</span>
      </div>
      <p className="text-sm font-medium text-slate-500">{label}</p>
      <p className="text-2xl font-bold text-slate-800 mt-0.5">{value}</p>
      {sub && <p className="text-xs text-slate-400 mt-1">{sub}</p>}
    </div>
  );
};

/** Simple bar chart rendered with CSS/SVG (no external chart lib needed). */
const SimpleBarChart = ({ data }: { data: TimeSeries[] }) => {
  if (!data || data.length === 0) {
    return (
      <div className="flex items-center justify-center h-40 text-slate-400 text-sm">
        暂无时序数据
      </div>
    );
  }

  const maxIn = Math.max(...data.map((d) => d.input_tokens), 1);
  const maxOut = Math.max(...data.map((d) => d.output_tokens), 1);
  const maxVal = Math.max(maxIn, maxOut);

  const BAR_W = Math.max(6, Math.min(32, Math.floor(560 / data.length) - 4));

  return (
    <div className="overflow-x-auto">
      <svg width={Math.max(600, data.length * (BAR_W + 4) + 60)} height={180} className="w-full">
        {data.map((d, i) => {
          const x = 30 + i * (BAR_W + 4);
          const hIn = Math.round((d.input_tokens / maxVal) * 130);
          const hOut = Math.round((d.output_tokens / maxVal) * 130);
          const label = d.period.slice(5, 10); // MM-DD or HH:00
          return (
            <g key={i}>
              {/* Input bar */}
              <rect x={x} y={160 - hIn} width={BAR_W / 2} height={hIn} fill="#6366f1" opacity={0.8} rx={2} />
              {/* Output bar */}
              <rect x={x + BAR_W / 2} y={160 - hOut} width={BAR_W / 2} height={hOut} fill="#10b981" opacity={0.8} rx={2} />
              {/* Label */}
              {data.length <= 31 && (
                <text x={x + BAR_W / 2} y={175} textAnchor="middle" fontSize={9} fill="#94a3b8">
                  {label}
                </text>
              )}
            </g>
          );
        })}
        {/* Y-axis label */}
        <text x={0} y={10} fontSize={9} fill="#94a3b8">tokens</text>
      </svg>
      <div className="flex items-center gap-4 mt-2 text-xs text-slate-500">
        <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-sm bg-indigo-500 inline-block" /> Input</span>
        <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-sm bg-emerald-500 inline-block" /> Output</span>
      </div>
    </div>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// Main page
// ─────────────────────────────────────────────────────────────────────────────

const UsagePage = () => {
  // ── Filters ───────────────────────────────────────────────────────────────
  const [start, setStart] = useState(defaultStart());
  const [end, setEnd] = useState(defaultEnd());
  const [granularity, setGranularity] = useState<'hour' | 'day' | 'month'>('day');
  const [groupId, setGroupId] = useState('');
  const [modelName, setModelName] = useState('');
  const [activeTab, setActiveTab] = useState<'summary' | 'records'>('summary');

  // ── Records pagination ────────────────────────────────────────────────────
  const [page, setPage] = useState(1);

  // ── Build query params ────────────────────────────────────────────────────
  const summaryParams = new URLSearchParams({
    start: start ? new Date(start).toISOString() : '',
    end: end ? new Date(end).toISOString() : '',
    granularity,
    ...(groupId ? { group_id: groupId } : {}),
    ...(modelName ? { model_name: modelName } : {}),
  });

  const recordsParams = new URLSearchParams({
    start: start ? new Date(start).toISOString() : '',
    end: end ? new Date(end).toISOString() : '',
    page: String(page),
    page_size: '20',
    ...(groupId ? { group_id: groupId } : {}),
    ...(modelName ? { model_name: modelName } : {}),
  });

  // ── Queries ───────────────────────────────────────────────────────────────
  const { data: summary, isLoading: summaryLoading, refetch: refetchSummary } = useQuery<SummaryData>({
    queryKey: ['usage-summary', summaryParams.toString()],
    queryFn: async () => {
      const res = await client.get(`/api/usage/summary?${summaryParams}`);
      return res.data;
    },
    enabled: activeTab === 'summary',
  });

  const { data: records, isLoading: recordsLoading, refetch: refetchRecords } = useQuery<RecordsData>({
    queryKey: ['usage-records', recordsParams.toString()],
    queryFn: async () => {
      const res = await client.get(`/api/usage/records?${recordsParams}`);
      return res.data;
    },
    enabled: activeTab === 'records',
  });

  const refetch = useCallback(() => {
    if (activeTab === 'summary') refetchSummary();
    else refetchRecords();
  }, [activeTab, refetchSummary, refetchRecords]);

  const totals = summary?.totals;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Usage Analytics</h1>
          <p className="text-slate-500 mt-1 text-sm">查看 API 请求消耗明细与统计概要</p>
        </div>
        <button
          onClick={refetch}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-xl hover:bg-slate-50 transition-colors shadow-sm"
        >
          <RefreshCw className="w-4 h-4" />
          刷新
        </button>
      </div>

      {/* Filters */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-5">
        <div className="flex items-center gap-2 mb-4 text-slate-600">
          <Filter className="w-4 h-4" />
          <span className="font-medium text-sm">筛选条件</span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
          <div>
            <label className="block text-xs text-slate-500 mb-1">开始时间</label>
            <input
              type="datetime-local"
              value={start}
              onChange={(e) => { setStart(e.target.value); setPage(1); }}
              className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-300"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">结束时间</label>
            <input
              type="datetime-local"
              value={end}
              onChange={(e) => { setEnd(e.target.value); setPage(1); }}
              className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-300"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">时间粒度</label>
            <select
              value={granularity}
              onChange={(e) => setGranularity(e.target.value as 'hour' | 'day' | 'month')}
              className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-300 bg-white"
            >
              <option value="hour">按小时</option>
              <option value="day">按天</option>
              <option value="month">按月</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">Group ID</label>
            <input
              type="text"
              placeholder="全部"
              value={groupId}
              onChange={(e) => { setGroupId(e.target.value); setPage(1); }}
              className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-300"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">模型名称</label>
            <input
              type="text"
              placeholder="模糊匹配"
              value={modelName}
              onChange={(e) => { setModelName(e.target.value); setPage(1); }}
              className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-300"
            />
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2">
        {(['summary', 'records'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-5 py-2.5 rounded-xl text-sm font-medium transition-all ${
              activeTab === tab
                ? 'bg-blue-600 text-white shadow-sm'
                : 'bg-white text-slate-600 border border-slate-200 hover:bg-slate-50'
            }`}
          >
            {tab === 'summary' ? '统计概要' : '消耗明细'}
          </button>
        ))}
      </div>

      {/* ── Summary tab ─────────────────────────────────────────────────── */}
      {activeTab === 'summary' && (
        <>
          {summaryLoading ? (
            <div className="text-center py-16 text-slate-400">加载中...</div>
          ) : (
            <>
              {/* KPI Cards */}
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
                <StatCard icon={<BarChart3 className="w-5 h-5" />} label="总请求数" value={fmtNum(totals?.requests ?? 0)} color="blue" />
                <StatCard icon={<TrendingUp className="w-5 h-5" />} label="输入 Tokens" value={fmtNum(totals?.input_tokens ?? 0)} color="indigo" />
                <StatCard icon={<Zap className="w-5 h-5" />} label="输出 Tokens" value={fmtNum(totals?.output_tokens ?? 0)} color="emerald" />
                <StatCard icon={<Brain className="w-5 h-5" />} label="推理 Tokens" value={fmtNum(totals?.reasoning_tokens ?? 0)} color="violet" />
                <StatCard icon={<Cpu className="w-5 h-5" />} label="缓存命中 Tokens" value={fmtNum(totals?.cache_tokens ?? 0)} color="cyan" />
                <StatCard icon={<Image className="w-5 h-5" />} label="生成图片" value={totals?.output_image_number ?? 0} sub="张" color="amber" />
                <StatCard icon={<Video className="w-5 h-5" />} label="生成视频" value={totals?.output_video_number ?? 0} sub="个" color="rose" />
                <StatCard icon={<Mic className="w-5 h-5" />} label="音频时长" value={(totals?.output_audio_seconds ?? 0).toFixed(1)} sub="秒" color="pink" />
                <StatCard icon={<Globe className="w-5 h-5" />} label="Web 搜索" value={totals?.web_search_requests ?? 0} sub="次" color="indigo" />
                <StatCard icon={<Cpu className="w-5 h-5" />} label="缓存写入 Tokens" value={fmtNum(totals?.cache_creation_tokens ?? 0)} color="amber" />
              </div>

              {/* Time Series Chart */}
              <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
                <h2 className="font-bold text-slate-800 mb-4 flex items-center gap-2">
                  <TrendingUp className="w-5 h-5 text-indigo-500" />
                  Token 消耗趋势
                </h2>
                <SimpleBarChart data={summary?.time_series ?? []} />
              </div>

              {/* By Model / By Group / By API Key */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* By Model */}
                <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
                  <h2 className="font-bold text-slate-800 mb-4 flex items-center gap-2">
                    <Cpu className="w-4 h-4 text-blue-500" />
                    按模型统计
                  </h2>
                  <div className="space-y-3">
                    {(summary?.by_model ?? []).slice(0, 8).map((m, i) => (
                      <div key={i} className="flex items-center justify-between p-3 bg-slate-50 rounded-xl hover:bg-slate-100 transition-colors">
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-medium text-slate-800 truncate">{m.model_name || '—'}</p>
                          <p className="text-xs text-slate-500">
                            In: {fmtNum(m.input_tokens)} / Out: {fmtNum(m.output_tokens)}
                          </p>
                        </div>
                        <span className="ml-2 bg-blue-100 text-blue-700 text-xs font-medium px-2.5 py-1 rounded-lg whitespace-nowrap">
                          {fmtNum(m.requests)} 次
                        </span>
                      </div>
                    ))}
                    {(summary?.by_model ?? []).length === 0 && (
                      <p className="text-center text-slate-400 text-sm py-6">暂无数据</p>
                    )}
                  </div>
                </div>

                {/* By Group */}
                <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
                  <h2 className="font-bold text-slate-800 mb-4 flex items-center gap-2">
                    <Users className="w-4 h-4 text-emerald-500" />
                    按分组统计
                  </h2>
                  <div className="space-y-3">
                    {(summary?.by_group ?? []).slice(0, 8).map((g, i) => (
                      <div key={i} className="flex items-center justify-between p-3 bg-slate-50 rounded-xl hover:bg-slate-100 transition-colors">
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-medium text-slate-800 truncate">{g.group_name || `Group #${g.group_id}`}</p>
                          <p className="text-xs text-slate-500">
                            In: {fmtNum(g.input_tokens)} / Out: {fmtNum(g.output_tokens)}
                          </p>
                        </div>
                        <span className="ml-2 bg-emerald-100 text-emerald-700 text-xs font-medium px-2.5 py-1 rounded-lg whitespace-nowrap">
                          {fmtNum(g.requests)} 次
                        </span>
                      </div>
                    ))}
                    {(summary?.by_group ?? []).length === 0 && (
                      <p className="text-center text-slate-400 text-sm py-6">暂无数据</p>
                    )}
                  </div>
                </div>

                {/* By API Key */}
                <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
                  <h2 className="font-bold text-slate-800 mb-4 flex items-center gap-2">
                    <Key className="w-4 h-4 text-violet-500" />
                    按 API Key 统计
                  </h2>
                  <div className="space-y-3">
                    {(summary?.by_api_key ?? []).slice(0, 8).map((k, i) => (
                      <div key={i} className="flex items-center justify-between p-3 bg-slate-50 rounded-xl hover:bg-slate-100 transition-colors">
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-medium text-slate-800 truncate">{k.api_key_name || '—'}</p>
                          <p className="text-xs text-slate-400 font-mono truncate">{k.api_key_preview}</p>
                        </div>
                        <span className="ml-2 bg-violet-100 text-violet-700 text-xs font-medium px-2.5 py-1 rounded-lg whitespace-nowrap">
                          {fmtNum(k.requests)} 次
                        </span>
                      </div>
                    ))}
                    {(summary?.by_api_key ?? []).length === 0 && (
                      <p className="text-center text-slate-400 text-sm py-6">暂无数据</p>
                    )}
                  </div>
                </div>
              </div>
            </>
          )}
        </>
      )}

      {/* ── Records tab ─────────────────────────────────────────────────── */}
      {activeTab === 'records' && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
          {recordsLoading ? (
            <div className="text-center py-16 text-slate-400">加载中...</div>
          ) : (
            <>
              {/* Table */}
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-slate-50 border-b border-slate-200">
                      {[
                        { label: '时间', align: 'text-left' },
                        { label: '模型', align: 'text-left' },
                        { label: '分组', align: 'text-left' },
                        { label: 'API Key', align: 'text-left' },
                        { label: '输入 Tokens', align: 'text-center' },
                        { label: '输出 Tokens', align: 'text-center' },
                        { label: '推理 Tokens', align: 'text-center' },
                        { label: '缓存命中', align: 'text-center' },
                        { label: '图片', align: 'text-center' },
                        { label: '视频', align: 'text-center' },
                        { label: '搜索', align: 'text-center' },
                      ].map((h) => (
                        <th key={h.label} className={`px-4 py-3 ${h.align} text-xs font-semibold text-slate-500 whitespace-nowrap`}>
                          {h.label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {(records?.records ?? []).map((r) => (
                      <tr key={r.id} className="hover:bg-slate-50 transition-colors">
                        <td className="px-4 py-3 text-slate-500 whitespace-nowrap text-xs">{fmtDate(r.created_at)}</td>
                        <td className="px-4 py-3 text-slate-800 font-medium max-w-[140px] truncate">{r.model_name || '—'}</td>
                        <td className="px-4 py-3 text-slate-600 whitespace-nowrap">{r.group_name || '—'}</td>
                        <td className="px-4 py-3">
                          <div>
                            <p className="text-slate-700 font-medium text-xs">{r.api_key_name || '—'}</p>
                            <p className="text-slate-400 font-mono text-xs">{r.api_key_preview || ''}</p>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-indigo-700 font-mono text-center whitespace-nowrap">
                          {fmtNum(r.input_tokens)}
                        </td>
                        <td className="px-4 py-3 text-emerald-700 font-mono text-center whitespace-nowrap">
                          {fmtNum(r.output_tokens)}
                        </td>
                        <td className="px-4 py-3 text-violet-700 font-mono text-center whitespace-nowrap">
                          {r.reasoning_tokens > 0 ? fmtNum(r.reasoning_tokens) : '—'}
                        </td>
                        <td className="px-4 py-3 text-cyan-700 font-mono text-center whitespace-nowrap">
                          {r.cache_tokens > 0 ? fmtNum(r.cache_tokens) : '—'}
                        </td>
                        <td className="px-4 py-3 text-amber-700 text-center whitespace-nowrap">
                          {r.output_image_number > 0 ? r.output_image_number : '—'}
                        </td>
                        <td className="px-4 py-3 text-rose-700 text-center whitespace-nowrap">
                          {r.output_video_number > 0 ? r.output_video_number : '—'}
                        </td>
                        <td className="px-4 py-3 text-blue-700 text-center whitespace-nowrap">
                          {r.web_search_requests > 0 ? r.web_search_requests : '—'}
                        </td>
                      </tr>
                    ))}
                    {(records?.records ?? []).length === 0 && (
                      <tr>
                        <td colSpan={11} className="text-center py-16 text-slate-400">
                          <Search className="w-10 h-10 mx-auto mb-2 text-slate-200" />
                          暂无消耗记录
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {(records?.pages ?? 0) > 1 && (
                <div className="flex items-center justify-between px-6 py-4 border-t border-slate-100">
                  <p className="text-sm text-slate-500">
                    共 {records?.total} 条，第 {page} / {records?.pages} 页
                  </p>
                  <div className="flex gap-2">
                    <button
                      disabled={page <= 1}
                      onClick={() => setPage((p) => p - 1)}
                      className="p-2 rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                    >
                      <ChevronLeft className="w-4 h-4" />
                    </button>
                    <button
                      disabled={page >= (records?.pages ?? 1)}
                      onClick={() => setPage((p) => p + 1)}
                      className="p-2 rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                    >
                      <ChevronRight className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
};

export default UsagePage;
