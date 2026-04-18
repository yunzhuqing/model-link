/**
 * GroupStatistics — 分组消耗统计组件
 *
 * 展示分组的消耗总金额、Token 消耗趋势、模型/API Key 费用分布等可视化图表。
 * 从 GroupDetail.tsx 拆分出来作为独立组件。
 */
import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import client from '../api/client';
import { BarChart3, TrendingUp, DollarSign, Cpu } from 'lucide-react';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface StatTotals {
  requests: number;
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_tokens: number;
  reasoning_tokens: number;
  total_cost: number;
}

interface StatByModel {
  model_name: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  total_cost: number;
}

interface StatByApiKey {
  api_key_hash: string;
  api_key_preview: string;
  api_key_name: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  total_cost: number;
}

interface StatTimeSeries {
  period: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  total_cost: number;
}

/* ── Helpers ────────────────────────────────────────────────────────────── */

function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return String(n);
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
];

/* ── Donut Chart ───────────────────────────────────────────────────────── */

const StatDonut = ({ slices, size = 130, strokeWidth = 22, centerValue, centerLabel }: {
  slices: { label: string; value: number; color: string }[];
  size?: number; strokeWidth?: number; centerValue?: string; centerLabel?: string;
}) => {
  const r = (size - strokeWidth) / 2;
  const circ = 2 * Math.PI * r;
  const total = slices.reduce((s, d) => s + d.value, 0) || 1;
  const c = size / 2;
  let cum = 0;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <circle cx={c} cy={c} r={r} fill="none" stroke="#f1f5f9" strokeWidth={strokeWidth} />
      {slices.map((sl, i) => {
        const pct = sl.value / total;
        const offset = circ * (1 - pct);
        const rot = cum * 360 - 90;
        cum += pct;
        return <circle key={i} cx={c} cy={c} r={r} fill="none" stroke={sl.color}
          strokeWidth={strokeWidth} strokeDasharray={`${circ}`} strokeDashoffset={offset}
          strokeLinecap="round" transform={`rotate(${rot} ${c} ${c})`} className="transition-all duration-700" />;
      })}
      {centerValue && (
        <>
          <text x={c} y={c - 4} textAnchor="middle" style={{ fontSize: '14px', fontWeight: 700 }} className="fill-slate-800">{centerValue}</text>
          {centerLabel && <text x={c} y={c + 12} textAnchor="middle" style={{ fontSize: '10px' }} className="fill-slate-400">{centerLabel}</text>}
        </>
      )}
    </svg>
  );
};

/* ── Daily Cost Bar Chart ──────────────────────────────────────────────── */

const DailyCostChart = ({ data }: { data: StatTimeSeries[] }) => {
  const [hovered, setHovered] = useState<number | null>(null);
  if (!data || data.length === 0) return <div className="text-center py-10 text-slate-400 text-sm">暂无金额数据</div>;

  const maxCost = Math.max(...data.map(d => d.total_cost || 0), 0.001);

  return (
    <div>
      <div className="flex items-end space-x-[3px] h-36">
        {data.map((d, i) => {
          const h = Math.max(((d.total_cost || 0) / maxCost) * 130, 1);
          const isH = hovered === i;
          return (
            <div key={i} className="flex-1 flex flex-col items-center relative"
              onMouseEnter={() => setHovered(i)} onMouseLeave={() => setHovered(null)}>
              <div className="w-full bg-amber-400 rounded-t-sm transition-all"
                style={{ height: `${h}px`, opacity: isH ? 1 : 0.7 }} />
              {isH && (
                <div className="absolute -top-[50px] left-1/2 -translate-x-1/2 bg-slate-800 text-white text-xs px-3 py-1.5 rounded-lg whitespace-nowrap z-20 shadow-xl">
                  <div className="font-semibold">{String(d.period).slice(5, 10)}</div>
                  <div>消耗: {fmtCost(d.total_cost || 0)}</div>
                  <div className="absolute bottom-0 left-1/2 -translate-x-1/2 translate-y-1/2 w-2 h-2 bg-slate-800 rotate-45" />
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="flex justify-between text-xs text-slate-400 mt-2">
        {data.map((d, i) => (
          i % Math.max(1, Math.ceil(data.length / 7)) === 0 || i === data.length - 1
            ? <span key={i}>{String(d.period).slice(5, 10)}</span>
            : <span key={i} />
        ))}
      </div>
    </div>
  );
};

/* ── Stacked Bar Chart for daily token trend ───────────────────────────── */

const DailyBarChart = ({ data }: { data: StatTimeSeries[] }) => {
  const [hovered, setHovered] = useState<number | null>(null);
  if (!data || data.length === 0) return <div className="text-center py-10 text-slate-400 text-sm">暂无趋势数据</div>;

  const maxVal = Math.max(...data.map(d => d.input_tokens + d.output_tokens), 1);

  return (
    <div>
      <div className="flex items-end space-x-[3px] h-44">
        {data.map((d, i) => {
          const inH = Math.max((d.input_tokens / maxVal) * 160, 1);
          const outH = Math.max((d.output_tokens / maxVal) * 160, 1);
          const isH = hovered === i;
          return (
            <div key={i} className="flex-1 flex flex-col items-center relative"
              onMouseEnter={() => setHovered(i)} onMouseLeave={() => setHovered(null)}>
              <div className="w-full flex flex-col-reverse">
                <div className="w-full bg-indigo-400 rounded-t-sm transition-all" style={{ height: `${inH}px`, opacity: isH ? 1 : 0.7 }} />
                <div className="w-full bg-emerald-400 rounded-t-sm transition-all" style={{ height: `${outH}px`, opacity: isH ? 1 : 0.7 }} />
              </div>
              {isH && (
                <div className="absolute -top-[70px] left-1/2 -translate-x-1/2 bg-slate-800 text-white text-xs px-3 py-2 rounded-lg whitespace-nowrap z-20 shadow-xl">
                  <div className="font-semibold mb-0.5">{String(d.period).slice(5, 10)}</div>
                  <div>In: {fmtNum(d.input_tokens)} · Out: {fmtNum(d.output_tokens)}</div>
                  <div>请求: {d.requests}</div>
                  <div className="absolute bottom-0 left-1/2 -translate-x-1/2 translate-y-1/2 w-2 h-2 bg-slate-800 rotate-45" />
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="flex justify-between text-xs text-slate-400 mt-2">
        {data.map((d, i) => (
          i % Math.max(1, Math.ceil(data.length / 7)) === 0 || i === data.length - 1
            ? <span key={i}>{String(d.period).slice(5, 10)}</span>
            : <span key={i} />
        ))}
      </div>
      <div className="flex items-center gap-4 mt-3 text-xs text-slate-500">
        <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 bg-indigo-400 rounded-sm" /> 输入 Tokens</span>
        <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 bg-emerald-400 rounded-sm" /> 输出 Tokens</span>
      </div>
    </div>
  );
};

/* ══════════════════════════════════════════════════════════════════════════
   Main Component
   ══════════════════════════════════════════════════════════════════════════ */

export default function GroupStatistics({ groupId }: { groupId: number }) {
  const [days, setDays] = useState(14);

  const params = useMemo(() => {
    const now = new Date();
    const start = new Date(now.getTime() - days * 86400000);
    return { start: start.toISOString(), end: now.toISOString(), group_id: String(groupId) };
  }, [groupId, days]);

  const { data: totals, isLoading: totalsLoading } = useQuery<StatTotals>({
    queryKey: ['grp-stat-totals', groupId, days],
    queryFn: async () => (await client.get('/api/usage/summary/totals', { params })).data,
  });
  const { data: byModel, isLoading: byModelLoading } = useQuery<StatByModel[]>({
    queryKey: ['grp-stat-by-model', groupId, days],
    queryFn: async () => (await client.get('/api/usage/summary/by_model', { params })).data,
  });
  const { data: byApiKey, isLoading: byApiKeyLoading } = useQuery<StatByApiKey[]>({
    queryKey: ['grp-stat-by-api-key', groupId, days],
    queryFn: async () => (await client.get('/api/usage/summary/by_api_key', { params })).data,
  });
  const { data: timeSeries, isLoading: tsLoading } = useQuery<StatTimeSeries[]>({
    queryKey: ['grp-stat-ts', groupId, days],
    queryFn: async () => (await client.get('/api/usage/summary/time_series', { params: { ...params, granularity: 'day' } })).data,
  });

  const loading = totalsLoading || byModelLoading || byApiKeyLoading || tsLoading;
  const totalTokens = (totals?.input_tokens || 0) + (totals?.output_tokens || 0);

  // Donut slices
  const modelCostSlices = (byModel || [])
    .sort((a, b) => (b.total_cost || 0) - (a.total_cost || 0))
    .map((m, i) => ({ label: m.model_name, value: m.total_cost || 0, color: PIE_COLORS[i % PIE_COLORS.length] }));

  const apiKeyCostSlices = (byApiKey || [])
    .sort((a, b) => (b.total_cost || 0) - (a.total_cost || 0))
    .map((k, i) => ({ label: k.api_key_name || k.api_key_preview || '—', value: k.total_cost || 0, color: PIE_COLORS[i % PIE_COLORS.length] }));

  const tokenSlices = totals ? [
    { label: '输入', value: totals.input_tokens, color: '#3b82f6' },
    { label: '输出', value: totals.output_tokens, color: '#10b981' },
    { label: '推理', value: totals.reasoning_tokens || 0, color: '#f59e0b' },
    { label: '缓存', value: (totals.cache_tokens || 0) + (totals.cache_creation_tokens || 0), color: '#8b5cf6' },
  ].filter(s => s.value > 0) : [];

  return (
    <div className="space-y-6">
      {/* Header + Range */}
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="w-10 h-10 bg-amber-100 rounded-lg flex items-center justify-center">
            <BarChart3 className="w-5 h-5 text-amber-600" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-slate-800">消耗统计</h2>
            <p className="text-sm text-slate-500">近 {days} 天分组用量概览</p>
          </div>
        </div>
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}
          className="text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white">
          <option value={7}>近 7 天</option>
          <option value={14}>近 14 天</option>
          <option value={30}>近 30 天</option>
        </select>
      </div>

      {loading ? (
        <div className="text-center py-16 text-slate-400">加载中...</div>
      ) : (!totals || totals.requests === 0) ? (
        <div className="text-center py-16 text-slate-400">
          <BarChart3 className="w-12 h-12 mx-auto mb-3 text-slate-200" />
          <p>该分组暂无消耗数据</p>
        </div>
      ) : (
        <>
          {/* ── KPI Cards ──────────────────────────────────────────────────── */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-gradient-to-br from-emerald-500 to-emerald-600 rounded-2xl p-4 text-white shadow">
              <div className="flex items-center space-x-2 mb-1"><DollarSign className="w-4 h-4" /><span className="text-xs text-white/80">消耗总金额</span></div>
              <p className="text-2xl font-bold">{fmtCost(totals.total_cost || 0)}</p>
            </div>
            <div className="bg-gradient-to-br from-blue-500 to-blue-600 rounded-2xl p-4 text-white shadow">
              <div className="flex items-center space-x-2 mb-1"><TrendingUp className="w-4 h-4" /><span className="text-xs text-white/80">消耗总 Token</span></div>
              <p className="text-2xl font-bold">{fmtNum(totalTokens)}</p>
            </div>
            <div className="bg-gradient-to-br from-indigo-500 to-indigo-600 rounded-2xl p-4 text-white shadow">
              <div className="flex items-center space-x-2 mb-1"><BarChart3 className="w-4 h-4" /><span className="text-xs text-white/80">请求总数</span></div>
              <p className="text-2xl font-bold">{fmtNum(totals.requests)}</p>
            </div>
            <div className="bg-gradient-to-br from-violet-500 to-violet-600 rounded-2xl p-4 text-white shadow">
              <div className="flex items-center space-x-2 mb-1"><Cpu className="w-4 h-4" /><span className="text-xs text-white/80">使用模型数</span></div>
              <p className="text-2xl font-bold">{byModel?.length ?? 0}</p>
            </div>
          </div>

          {/* ── Two charts side by side: Token trend + Cost trend ─────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
              <h3 className="text-sm font-bold text-slate-800 mb-4 flex items-center space-x-2">
                <TrendingUp className="w-4 h-4 text-blue-500" />
                <span>每日 Token 消耗趋势</span>
              </h3>
              <DailyBarChart data={timeSeries || []} />
            </div>
            <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
              <h3 className="text-sm font-bold text-slate-800 mb-4 flex items-center space-x-2">
                <DollarSign className="w-4 h-4 text-amber-500" />
                <span>每日金额消耗趋势</span>
              </h3>
              <DailyCostChart data={timeSeries || []} />
            </div>
          </div>

          {/* ── Donut Charts Row: Token Distribution + Model Cost + API Key Cost */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Token Distribution */}
            <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
              <h3 className="text-xs font-bold text-slate-600 mb-4">Token 分布</h3>
              <div className="flex flex-col items-center">
                <StatDonut slices={tokenSlices} centerValue={fmtNum(totalTokens)} centerLabel="总计" />
                <div className="mt-4 space-y-2 w-full">
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
            <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
              <h3 className="text-xs font-bold text-slate-600 mb-4">模型费用分布</h3>
              <div className="flex flex-col items-center">
                <StatDonut slices={modelCostSlices} centerValue={fmtCost(totals.total_cost || 0)} centerLabel="总费用" />
                <div className="mt-4 space-y-2 w-full max-h-[140px] overflow-y-auto">
                  {modelCostSlices.map((s, i) => {
                    const total = modelCostSlices.reduce((a, sl) => a + sl.value, 0) || 1;
                    return (
                      <div key={i} className="flex items-center justify-between text-xs">
                        <div className="flex items-center space-x-1.5 min-w-0">
                          <div className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ backgroundColor: s.color }} />
                          <span className="text-slate-600 truncate">{s.label}</span>
                        </div>
                        <div className="flex items-center space-x-2 flex-shrink-0 ml-2">
                          <span className="font-semibold text-amber-600 tabular-nums">{fmtCost(s.value)}</span>
                          <span className="text-slate-400 tabular-nums">{((s.value / total) * 100).toFixed(1)}%</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* API Key Cost Distribution */}
            <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
              <h3 className="text-xs font-bold text-slate-600 mb-4">API Key 费用分布</h3>
              <div className="flex flex-col items-center">
                <StatDonut slices={apiKeyCostSlices} centerValue={fmtCost(totals.total_cost || 0)} centerLabel="总费用" />
                <div className="mt-4 space-y-2 w-full max-h-[140px] overflow-y-auto">
                  {apiKeyCostSlices.map((s, i) => {
                    const total = apiKeyCostSlices.reduce((a, sl) => a + sl.value, 0) || 1;
                    return (
                      <div key={i} className="flex items-center justify-between text-xs">
                        <div className="flex items-center space-x-1.5 min-w-0">
                          <div className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ backgroundColor: s.color }} />
                          <span className="text-slate-600 truncate">{s.label}</span>
                        </div>
                        <div className="flex items-center space-x-2 flex-shrink-0 ml-2">
                          <span className="font-semibold text-amber-600 tabular-nums">{fmtCost(s.value)}</span>
                          <span className="text-slate-400 tabular-nums">{((s.value / total) * 100).toFixed(1)}%</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
