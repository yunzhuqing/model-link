import { useQuery } from '@tanstack/react-query';
import client from '../api/client';
import { Key, Activity, Cpu, BarChart3, TrendingUp, Zap, Copy, Check, Users, Database } from 'lucide-react';
import { useState } from 'react';

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
  };
  by_model: Array<{
    model_name: string;
    requests: number;
    input_tokens: number;
    output_tokens: number;
    reasoning_tokens: number;
  }>;
  by_api_key: Array<{
    api_key_hash: string;
    api_key_preview: string;
    api_key_name: string;
    requests: number;
    input_tokens: number;
    output_tokens: number;
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

function fmtDate(s: string | null): string {
  if (!s) return '-';
  const d = s.includes('T') && !s.endsWith('Z') && !s.includes('+') ? s + 'Z' : s;
  return new Date(d).toLocaleString('zh-CN');
}

/* ── Dashboard ─────────────────────────────────────────────────────────── */

const Dashboard = () => {
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  // Fetch current user's API keys
  const { data: apiKeys, isLoading: keysLoading } = useQuery({
    queryKey: ['apiKeys'],
    queryFn: async () => {
      const res = await client.get<ApiKeyItem[]>('/api/apikeys/');
      return res.data;
    },
  });

  // Fetch usage summary (last 30 days by default)
  const { data: usage, isLoading: usageLoading } = useQuery({
    queryKey: ['usage-summary'],
    queryFn: async () => {
      const now = new Date();
      const start = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
      const res = await client.get<UsageSummary>('/api/usage/summary', {
        params: {
          start: start.toISOString(),
          end: now.toISOString(),
          granularity: 'day',
        },
      });
      return res.data;
    },
  });

  const handleCopyKey = async (key: string) => {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(key);
      } else {
        const ta = document.createElement('textarea');
        ta.value = key;
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      }
      setCopiedKey(key);
      setTimeout(() => setCopiedKey(null), 2000);
    } catch { /* ignore */ }
  };

  const totals = usage?.totals;
  const totalTokens = (totals?.input_tokens || 0) + (totals?.output_tokens || 0);

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">控制台</h1>
          <p className="text-slate-500 mt-1">查看 API Key 和使用统计概览</p>
        </div>
        <div className="flex items-center space-x-2 px-4 py-2 bg-green-50 border border-green-200 rounded-xl">
          <Activity className="w-4 h-4 text-green-500" />
          <span className="text-sm font-medium text-green-700">系统正常</span>
        </div>
      </div>

      {/* ── Overview Stats ─────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatCard
          icon={<Key className="w-6 h-6 text-blue-600" />}
          label="我的 API Keys"
          value={apiKeys?.length ?? 0}
          color="blue"
        />
        <StatCard
          icon={<Zap className="w-6 h-6 text-amber-600" />}
          label="总请求次数"
          value={fmtNum(totals?.requests || 0)}
          color="amber"
          sub="近 30 天"
        />
        <StatCard
          icon={<TrendingUp className="w-6 h-6 text-emerald-600" />}
          label="总 Token 消耗"
          value={fmtNum(totalTokens)}
          color="emerald"
          sub="输入 + 输出"
        />
        <StatCard
          icon={<Cpu className="w-6 h-6 text-violet-600" />}
          label="使用模型数"
          value={usage?.by_model?.length ?? 0}
          color="violet"
          sub="近 30 天"
        />
      </div>

      {/* ── My API Keys ────────────────────────────────────────────────── */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
        <div className="flex items-center justify-between mb-5">
          <div>
            <h2 className="text-lg font-bold text-slate-800">我的 API Key</h2>
            <p className="text-sm text-slate-500">当前用户可见的所有 API Key</p>
          </div>
          <Key className="w-5 h-5 text-slate-400" />
        </div>
        {keysLoading ? (
          <div className="text-center py-8 text-slate-500">加载中...</div>
        ) : apiKeys && apiKeys.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200">
                  <th className="text-left py-3 px-4 font-semibold text-slate-600">名称</th>
                  <th className="text-left py-3 px-4 font-semibold text-slate-600">Key</th>
                  <th className="text-center py-3 px-4 font-semibold text-slate-600">状态</th>
                  <th className="text-left py-3 px-4 font-semibold text-slate-600">分组</th>
                  <th className="text-left py-3 px-4 font-semibold text-slate-600">所属用户</th>
                  <th className="text-center py-3 px-4 font-semibold text-slate-600">请求数</th>
                  <th className="text-left py-3 px-4 font-semibold text-slate-600">创建时间</th>
                </tr>
              </thead>
              <tbody>
                {apiKeys.map((k) => (
                  <tr key={k.id} className="border-b border-slate-100 hover:bg-slate-50 transition-colors">
                    <td className="py-3 px-4 font-medium text-slate-800">{k.name}</td>
                    <td className="py-3 px-4">
                      <div className="flex items-center space-x-2">
                        <code className="text-xs text-slate-500 font-mono bg-slate-100 px-2 py-1 rounded">
                          {k.key.substring(0, 12)}...
                        </code>
                        <button
                          onClick={() => handleCopyKey(k.key)}
                          className="text-slate-400 hover:text-blue-600 transition-colors"
                          title="复制"
                        >
                          {copiedKey === k.key
                            ? <Check className="w-3.5 h-3.5 text-emerald-500" />
                            : <Copy className="w-3.5 h-3.5" />}
                        </button>
                      </div>
                    </td>
                    <td className="py-3 px-4 text-center">
                      <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
                        k.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'
                      }`}>
                        {k.is_active ? '启用' : '禁用'}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-slate-600">{k.group?.name || '-'}</td>
                    <td className="py-3 px-4 text-slate-600">{k.user_name || '-'}</td>
                    <td className="py-3 px-4 text-center text-slate-700 font-medium">{k.request_count.toLocaleString()}</td>
                    <td className="py-3 px-4 text-slate-500 text-xs">{fmtDate(k.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-center py-8 text-slate-500">
            <Key className="w-12 h-12 mx-auto mb-3 text-slate-300" />
            <p>暂无 API Key，请前往 API Key 管理页面创建</p>
          </div>
        )}
      </div>

      {/* ── Per API Key Token Usage ────────────────────────────────────── */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
        <div className="flex items-center justify-between mb-5">
          <div>
            <h2 className="text-lg font-bold text-slate-800">API Key 用量统计</h2>
            <p className="text-sm text-slate-500">近 30 天各 API Key 的 Token 使用情况</p>
          </div>
          <BarChart3 className="w-5 h-5 text-slate-400" />
        </div>
        {usageLoading ? (
          <div className="text-center py-8 text-slate-500">加载中...</div>
        ) : usage?.by_api_key && usage.by_api_key.length > 0 ? (
          <div className="space-y-3">
            {usage.by_api_key.map((item, idx) => {
              const total = item.input_tokens + item.output_tokens;
              const maxTotal = Math.max(...usage.by_api_key.map(i => i.input_tokens + i.output_tokens), 1);
              const pct = (total / maxTotal) * 100;
              return (
                <div key={idx} className="p-4 bg-slate-50 rounded-xl hover:bg-slate-100 transition-colors">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center space-x-3">
                      <div className="w-8 h-8 bg-blue-100 rounded-lg flex items-center justify-center">
                        <Key className="w-4 h-4 text-blue-600" />
                      </div>
                      <div>
                        <p className="font-medium text-slate-800">{item.api_key_name || '未命名'}</p>
                        <p className="text-xs text-slate-500 font-mono">{item.api_key_preview}</p>
                      </div>
                    </div>
                    <div className="text-right">
                      <p className="text-sm font-bold text-slate-800">{fmtNum(total)} tokens</p>
                      <p className="text-xs text-slate-500">{item.requests.toLocaleString()} 次请求</p>
                    </div>
                  </div>
                  {/* Bar */}
                  <div className="w-full bg-slate-200 rounded-full h-2">
                    <div
                      className="h-2 rounded-full bg-gradient-to-r from-blue-400 to-indigo-500 transition-all"
                      style={{ width: `${Math.max(pct, 2)}%` }}
                    />
                  </div>
                  <div className="flex justify-between mt-1 text-xs text-slate-500">
                    <span>输入: {fmtNum(item.input_tokens)}</span>
                    <span>输出: {fmtNum(item.output_tokens)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="text-center py-8 text-slate-500">
            <BarChart3 className="w-12 h-12 mx-auto mb-3 text-slate-300" />
            <p>暂无使用记录</p>
          </div>
        )}
      </div>

      {/* ── Model Usage Stats ──────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* By Model */}
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
          <div className="flex items-center justify-between mb-5">
            <div>
              <h2 className="text-lg font-bold text-slate-800">模型使用统计</h2>
              <p className="text-sm text-slate-500">近 30 天各模型请求 & Token 分布</p>
            </div>
            <Cpu className="w-5 h-5 text-slate-400" />
          </div>
          {usageLoading ? (
            <div className="text-center py-8 text-slate-500">加载中...</div>
          ) : usage?.by_model && usage.by_model.length > 0 ? (
            <div className="space-y-3">
              {usage.by_model.map((m, idx) => {
                const total = m.input_tokens + m.output_tokens;
                const maxTotal = Math.max(...usage.by_model.map(i => i.input_tokens + i.output_tokens), 1);
                const pct = (total / maxTotal) * 100;
                const colors = [
                  'from-blue-400 to-indigo-500',
                  'from-emerald-400 to-green-500',
                  'from-amber-400 to-orange-500',
                  'from-violet-400 to-purple-500',
                  'from-rose-400 to-pink-500',
                  'from-cyan-400 to-teal-500',
                ];
                return (
                  <div key={idx} className="p-4 bg-slate-50 rounded-xl hover:bg-slate-100 transition-colors">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center space-x-3">
                        <span className="w-7 h-7 bg-slate-200 rounded-lg flex items-center justify-center text-xs font-bold text-slate-600">
                          {idx + 1}
                        </span>
                        <div>
                          <p className="font-medium text-slate-800 text-sm">{m.model_name}</p>
                          <p className="text-xs text-slate-500">{m.requests.toLocaleString()} 次请求</p>
                        </div>
                      </div>
                      <span className="text-sm font-bold text-slate-800">{fmtNum(total)}</span>
                    </div>
                    <div className="w-full bg-slate-200 rounded-full h-1.5">
                      <div
                        className={`h-1.5 rounded-full bg-gradient-to-r ${colors[idx % colors.length]} transition-all`}
                        style={{ width: `${Math.max(pct, 2)}%` }}
                      />
                    </div>
                    <div className="flex justify-between mt-1 text-xs text-slate-400">
                      <span>输入 {fmtNum(m.input_tokens)} · 输出 {fmtNum(m.output_tokens)}</span>
                      {m.reasoning_tokens > 0 && <span>推理 {fmtNum(m.reasoning_tokens)}</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="text-center py-8 text-slate-500">
              <Cpu className="w-12 h-12 mx-auto mb-3 text-slate-300" />
              <p>暂无模型使用记录</p>
            </div>
          )}
        </div>

        {/* By Group + Daily Trend */}
        <div className="space-y-6">
          {/* By Group */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
            <div className="flex items-center justify-between mb-5">
              <div>
                <h2 className="text-lg font-bold text-slate-800">分组用量</h2>
                <p className="text-sm text-slate-500">近 30 天各分组 Token 消耗</p>
              </div>
              <Users className="w-5 h-5 text-slate-400" />
            </div>
            {usageLoading ? (
              <div className="text-center py-8 text-slate-500">加载中...</div>
            ) : usage?.by_group && usage.by_group.length > 0 ? (
              <div className="space-y-3">
                {usage.by_group.map((g, idx) => {
                  const total = g.input_tokens + g.output_tokens;
                  return (
                    <div key={idx} className="flex items-center justify-between p-3 bg-slate-50 rounded-xl hover:bg-slate-100 transition-colors">
                      <div className="flex items-center space-x-3">
                        <div className="w-8 h-8 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-lg flex items-center justify-center">
                          <Database className="w-4 h-4 text-white" />
                        </div>
                        <div>
                          <p className="font-medium text-slate-800 text-sm">{g.group_name || `Group #${g.group_id}`}</p>
                          <p className="text-xs text-slate-500">{g.requests.toLocaleString()} 次请求</p>
                        </div>
                      </div>
                      <span className="bg-blue-100 text-blue-700 px-3 py-1 rounded-lg text-sm font-medium">
                        {fmtNum(total)} tokens
                      </span>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="text-center py-6 text-slate-500 text-sm">暂无数据</div>
            )}
          </div>

          {/* Daily Trend */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
            <div className="flex items-center justify-between mb-5">
              <div>
                <h2 className="text-lg font-bold text-slate-800">每日请求趋势</h2>
                <p className="text-sm text-slate-500">近 30 天请求数量变化</p>
              </div>
              <TrendingUp className="w-5 h-5 text-slate-400" />
            </div>
            {usageLoading ? (
              <div className="text-center py-8 text-slate-500">加载中...</div>
            ) : usage?.time_series && usage.time_series.length > 0 ? (
              <div>
                {/* Simple bar chart */}
                <div className="flex items-end space-x-1 h-32">
                  {usage.time_series.map((ts, idx) => {
                    const maxReqs = Math.max(...usage.time_series.map(t => t.requests), 1);
                    const h = (ts.requests / maxReqs) * 100;
                    return (
                      <div key={idx} className="flex-1 flex flex-col items-center group relative" title={`${ts.period.slice(0, 10)}: ${ts.requests} 次`}>
                        <div
                          className="w-full bg-gradient-to-t from-blue-400 to-indigo-400 rounded-t transition-all hover:from-blue-500 hover:to-indigo-500"
                          style={{ height: `${Math.max(h, 2)}%`, minHeight: '2px' }}
                        />
                        {/* Tooltip on hover */}
                        <div className="absolute -top-10 left-1/2 -translate-x-1/2 bg-slate-800 text-white text-xs px-2 py-1 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none z-10">
                          {ts.period.slice(5, 10)}: {ts.requests}
                        </div>
                      </div>
                    );
                  })}
                </div>
                <div className="flex justify-between text-xs text-slate-400 mt-2">
                  <span>{usage.time_series[0]?.period.slice(5, 10)}</span>
                  <span>{usage.time_series[usage.time_series.length - 1]?.period.slice(5, 10)}</span>
                </div>
              </div>
            ) : (
              <div className="text-center py-6 text-slate-500 text-sm">暂无趋势数据</div>
            )}
          </div>
        </div>
      </div>

      {/* ── Token Summary ──────────────────────────────────────────────── */}
      {totals && (totals.requests > 0) && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
          <h2 className="text-lg font-bold text-slate-800 mb-4">Token 使用明细 (近 30 天)</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-4">
            <MiniStat label="输入 Tokens" value={fmtNum(totals.input_tokens)} color="blue" />
            <MiniStat label="输出 Tokens" value={fmtNum(totals.output_tokens)} color="emerald" />
            <MiniStat label="缓存创建 Tokens" value={fmtNum(totals.cache_creation_tokens)} color="amber" />
            <MiniStat label="缓存命中 Tokens" value={fmtNum(totals.cache_tokens)} color="violet" />
            <MiniStat label="推理 Tokens" value={fmtNum(totals.reasoning_tokens)} color="rose" />
            {totals.output_image_number > 0 && (
              <MiniStat label="生成图片" value={totals.output_image_number.toString()} color="cyan" />
            )}
            {totals.output_video_number > 0 && (
              <MiniStat label="生成视频" value={totals.output_video_number.toString()} color="pink" />
            )}
            {totals.web_search_requests > 0 && (
              <MiniStat label="联网搜索" value={totals.web_search_requests.toString()} color="indigo" />
            )}
          </div>
        </div>
      )}
    </div>
  );
};

/* ── Stat Card ─────────────────────────────────────────────────────────── */

const StatCard = ({
  icon, label, value, color, sub,
}: {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  color: string;
  sub?: string;
}) => {
  const colors: Record<string, { bg: string; border: string }> = {
    blue: { bg: 'bg-blue-50', border: 'border-blue-100' },
    emerald: { bg: 'bg-emerald-50', border: 'border-emerald-100' },
    amber: { bg: 'bg-amber-50', border: 'border-amber-100' },
    violet: { bg: 'bg-violet-50', border: 'border-violet-100' },
  };
  return (
    <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between">
        <div className={`p-3 rounded-xl ${colors[color]?.bg || 'bg-slate-50'} border ${colors[color]?.border || 'border-slate-100'}`}>
          {icon}
        </div>
        {sub && (
          <span className="text-xs font-medium text-slate-500 bg-slate-100 px-2 py-1 rounded-full">
            {sub}
          </span>
        )}
      </div>
      <div className="mt-4">
        <p className="text-sm font-medium text-slate-500">{label}</p>
        <p className="text-2xl font-bold text-slate-800 mt-1">{value}</p>
      </div>
    </div>
  );
};

/* ── Mini Stat ─────────────────────────────────────────────────────────── */

const MiniStat = ({ label, value, color }: { label: string; value: string; color: string }) => {
  const bgColors: Record<string, string> = {
    blue: 'bg-blue-50 border-blue-100',
    emerald: 'bg-emerald-50 border-emerald-100',
    amber: 'bg-amber-50 border-amber-100',
    violet: 'bg-violet-50 border-violet-100',
    rose: 'bg-rose-50 border-rose-100',
    cyan: 'bg-cyan-50 border-cyan-100',
    pink: 'bg-pink-50 border-pink-100',
    indigo: 'bg-indigo-50 border-indigo-100',
  };
  const textColors: Record<string, string> = {
    blue: 'text-blue-700',
    emerald: 'text-emerald-700',
    amber: 'text-amber-700',
    violet: 'text-violet-700',
    rose: 'text-rose-700',
    cyan: 'text-cyan-700',
    pink: 'text-pink-700',
    indigo: 'text-indigo-700',
  };
  return (
    <div className={`rounded-xl p-4 border ${bgColors[color] || 'bg-slate-50 border-slate-100'}`}>
      <p className="text-xs font-medium text-slate-500 mb-1">{label}</p>
      <p className={`text-xl font-bold ${textColors[color] || 'text-slate-800'}`}>{value}</p>
    </div>
  );
};

export default Dashboard;
