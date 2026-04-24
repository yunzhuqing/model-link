/**
 * GroupStatistics — Group usage statistics component
 *
 * Displays group consumption totals, Token trends, model/API Key cost distribution charts.
 * Split from GroupDetail.tsx as an independent component.
 */
import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
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
  total_cost_usd: number;
}

interface StatByApiKey {
  api_key_hash: string;
  api_key_preview: string;
  api_key_name: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  total_cost: number;
  total_cost_usd: number;
}

interface StatTimeSeries {
  period: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  cache_creation_tokens: number;
  total_cost: number;
}

interface StatTimeSeriesByModel {
  period: string;
  model_name: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  cache_creation_tokens: number;
  total_cost: number;
  total_cost_usd: number;
}

interface CurrencyCost {
  currency: string;
  total_cost_native: number;
  total_cost_usd: number;
}

interface StatByCurrency {
  currencies: CurrencyCost[];
  total_cost_usd: number;
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

function fmtCostWithSymbol(n: number, currency: string): string {
  const sym = currency === 'CNY' ? '¥' : currency === 'USD' ? '$' : currency + ' ';
  if (n >= 1000) return sym + (n / 1000).toFixed(1) + 'K';
  if (n >= 1) return sym + n.toFixed(2);
  if (n >= 0.01) return sym + n.toFixed(3);
  if (n > 0) return sym + n.toFixed(4);
  return sym + '0.00';
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

/* ── Stacked Bar Chart for daily token trend ───────────────────────────── */

const DailyBarChart = ({ data, t }: { data: StatTimeSeries[]; t: (key: string, opts?: Record<string, unknown>) => string }) => {
  const [hovered, setHovered] = useState<number | null>(null);
  if (!data || data.length === 0) return <div className="text-center py-10 text-slate-400 text-sm">{t('group.statistics.noTrendData')}</div>;

  // input_tokens from the API already includes cache_creation_tokens (both
  // are billed at input_price_unit).  To avoid double-counting in the
  // stacked bar chart we compute "pure input" = input_tokens - cache_creation.
  const pureInput = (d: StatTimeSeries) => Math.max(d.input_tokens - (d.cache_creation_tokens || 0), 0);

  const maxVal = Math.max(...data.map(d => d.input_tokens + d.output_tokens + (d.reasoning_tokens || 0)), 1);

  // Generate Y-axis ticks for tokens
  const yTicks = [0, maxVal * 0.25, maxVal * 0.5, maxVal * 0.75, maxVal];

  return (
    <div className="flex">
      {/* Y-axis */}
      <div className="flex flex-col justify-between text-xs text-slate-400 pr-2 h-44 text-right w-14 flex-shrink-0">
        {yTicks.map((tick, i) => (
          <span key={i}>{fmtNum(Math.round(tick))}</span>
        )).reverse()}
      </div>
      <div className="flex-1">
        <div className="flex items-end space-x-[3px] h-44">
            {data.map((d, i) => {
              const inH = (pureInput(d) / maxVal) * 160;
              const cacheH = ((d.cache_creation_tokens || 0) / maxVal) * 160;
              const outH = (d.output_tokens / maxVal) * 160;
              const reasonH = ((d.reasoning_tokens || 0) / maxVal) * 160;
              const totalH = Math.max(inH + cacheH + outH + reasonH, 1);
              const isH = hovered === i;
              return (
                <div key={i} className="flex-1 flex flex-col items-center relative"
                  onMouseEnter={() => setHovered(i)} onMouseLeave={() => setHovered(null)}>
                  <div className="w-full rounded-t-sm overflow-hidden transition-all" style={{ height: `${totalH}px`, opacity: isH ? 1 : 0.7 }}>
                    {/* Top→bottom visual: reasoning, output, cache, input */}
                    {reasonH > 0 && <div className="w-full bg-amber-400" style={{ height: `${reasonH}px` }} />}
                    {outH > 0 && <div className="w-full bg-emerald-400" style={{ height: `${outH}px` }} />}
                    {cacheH > 0 && <div className="w-full bg-purple-400" style={{ height: `${cacheH}px` }} />}
                    {inH > 0 && <div className="w-full bg-blue-400" style={{ height: `${inH}px` }} />}
                  </div>
                  {isH && (
                    <div className="absolute -top-[70px] left-1/2 -translate-x-1/2 bg-slate-800 text-white text-xs px-3 py-2 rounded-lg whitespace-nowrap z-20 shadow-xl">
                      <div className="font-semibold mb-0.5">{String(d.period).slice(5, 10)}</div>
                      <div>{t('group.statistics.inOut', { in: fmtNum(pureInput(d)), out: fmtNum(d.output_tokens) })}</div>
                      {(d.cache_creation_tokens || 0) > 0 && <div>Cache Creation: {fmtNum(d.cache_creation_tokens)}</div>}
                      {(d.reasoning_tokens || 0) > 0 && <div>Reasoning: {fmtNum(d.reasoning_tokens)}</div>}
                      <div>{t('group.statistics.requests', { value: String(d.requests) })}</div>
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
          <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 bg-blue-400 rounded-sm" /> {t('group.statistics.inputTokensLegend')}</span>
          <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 bg-purple-400 rounded-sm" /> {t('group.statistics.cache')}</span>
          <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 bg-emerald-400 rounded-sm" /> {t('group.statistics.outputTokensLegend')}</span>
          <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 bg-amber-400 rounded-sm" /> {t('group.statistics.reasoning')}</span>
        </div>
      </div>
    </div>
  );
};

/* ── Stacked Cost-by-Model Chart ──────────────────────────────────────── */

const DailyCostByModelChart = ({ data, t }: { data: StatTimeSeriesByModel[]; t: (key: string, opts?: Record<string, unknown>) => string }) => {
  const [hovered, setHovered] = useState<{ bar: number; segment: string } | null>(null);
  if (!data || data.length === 0) return <div className="text-center py-10 text-slate-400 text-sm">{t('group.statistics.noCostData')}</div>;

  // Build a map of period → { model_name → cost } and collect all unique periods & models
  const periodMap: Record<string, Record<string, number>> = {};
  const modelSet = new Set<string>();
  for (const d of data) {
    const p = String(d.period);
    if (!periodMap[p]) periodMap[p] = {};
    periodMap[p][d.model_name || 'unknown'] = d.total_cost_usd || 0;
    modelSet.add(d.model_name || 'unknown');
  }

  // Sort models by total cost descending for color assignment
  const modelTotalCost: Record<string, number> = {};
  for (const m of modelSet) {
    modelTotalCost[m] = Object.values(periodMap).reduce((s, pm) => s + (pm[m] || 0), 0);
  }
  const models = Array.from(modelSet).sort((a, b) => (modelTotalCost[b] || 0) - (modelTotalCost[a] || 0));
  const periods = Object.keys(periodMap).sort();

  const maxCost = Math.max(...periods.map(p => Object.values(periodMap[p]).reduce((s, v) => s + v, 0)), 0.001);

  // Generate Y-axis ticks for cost
  const yTicks = [0, maxCost * 0.25, maxCost * 0.5, maxCost * 0.75, maxCost];

  return (
    <div className="flex">
      {/* Y-axis */}
      <div className="flex flex-col justify-between text-xs text-slate-400 pr-2 h-44 text-right w-14 flex-shrink-0">
        {yTicks.map((tick, i) => (
          <span key={i}>{fmtCost(tick)}</span>
        )).reverse()}
      </div>
      <div className="flex-1">
        <div className="flex items-end space-x-[3px] h-44">
          {periods.map((p, i) => {
          const dayModels = periodMap[p];
          const segments = models.filter(m => (dayModels[m] || 0) > 0);
          const isH = hovered?.bar === i;
          return (
            <div key={i} className="flex-1 flex flex-col items-center relative"
              onMouseEnter={() => setHovered({ bar: i, segment: '' })}
              onMouseLeave={() => setHovered(null)}>
              <div className="w-full rounded-t-sm overflow-hidden transition-all" style={{ height: `${Math.max(Object.values(dayModels).reduce((s, v) => s + v, 0) / maxCost * 160, 1)}px`, opacity: isH ? 1 : 0.7 }}>
                {segments.map((m, si) => {
                  const cost = dayModels[m] || 0;
                  const segH = (cost / maxCost) * 160;
                  const color = PIE_COLORS[models.indexOf(m) % PIE_COLORS.length];
                  return (
                    <div key={si} className="w-full transition-all cursor-default"
                      style={{ height: `${segH}px`, backgroundColor: color }}
                      onMouseEnter={() => setHovered({ bar: i, segment: m })} />
                  );
                })}
              </div>
              {isH && (
                <div className="absolute -top-[60px] left-1/2 -translate-x-1/2 bg-slate-800 text-white text-xs px-3 py-1.5 rounded-lg whitespace-nowrap z-20 shadow-xl max-w-[200px]">
                  <div className="font-semibold">{p.slice(5, 10)}</div>
                  {hovered?.segment && (
                    <div className="flex items-center space-x-1">
                      <span className="w-2 h-2 rounded-sm inline-block" style={{ backgroundColor: PIE_COLORS[models.indexOf(hovered.segment) % PIE_COLORS.length] }} />
                      <span>{hovered.segment}: {fmtCost(dayModels[hovered.segment] || 0)}</span>
                    </div>
                  )}
                  {!hovered?.segment && (
                    <div>{t('group.statistics.cost', { value: fmtCost(Object.values(dayModels).reduce((s, v) => s + v, 0)) })}</div>
                  )}
                  <div className="absolute bottom-0 left-1/2 -translate-x-1/2 translate-y-1/2 w-2 h-2 bg-slate-800 rotate-45" />
                </div>
              )}
            </div>
          );
        })}
        </div>
        <div className="flex justify-between text-xs text-slate-400 mt-2">
          {periods.map((p, i) => (
            i % Math.max(1, Math.ceil(periods.length / 7)) === 0 || i === periods.length - 1
              ? <span key={i}>{p.slice(5, 10)}</span>
              : <span key={i} />
          ))}
        </div>
        <div className="flex items-center gap-3 mt-3 text-xs text-slate-500 flex-wrap">
          {models.slice(0, 8).map((m, i) => (
            <span key={i} className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: PIE_COLORS[i % PIE_COLORS.length] }} />
              <span className="truncate max-w-[120px]">{m}</span>
            </span>
          ))}
          {models.length > 8 && <span className="text-slate-400">+{models.length - 8}</span>}
        </div>
      </div>
    </div>
  );
};

/* ══════════════════════════════════════════════════════════════════════════
   Main Component
   ══════════════════════════════════════════════════════════════════════════ */

export default function GroupStatistics({ groupId }: { groupId: number }) {
  const { t } = useTranslation();
  const [days, setDays] = useState(7);

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
  const { data: byCurrency, isLoading: byCurrencyLoading } = useQuery<StatByCurrency>({
    queryKey: ['grp-stat-by-currency', groupId, days],
    queryFn: async () => (await client.get('/api/usage/summary/by_currency', { params })).data,
  });
  const { data: timeSeriesByModel, isLoading: tsByModelLoading } = useQuery<StatTimeSeriesByModel[]>({
    queryKey: ['grp-stat-ts-by-model', groupId, days],
    queryFn: async () => (await client.get('/api/usage/summary/time_series_by_model', { params: { ...params, granularity: 'day' } })).data,
  });

  const loading = totalsLoading || byModelLoading || byApiKeyLoading || tsLoading || byCurrencyLoading || tsByModelLoading;

  // Token distribution: input, output, reasoning, cache hit
  const totalTokens = (totals?.input_tokens || 0) + (totals?.output_tokens || 0) + (totals?.reasoning_tokens || 0) + (totals?.cache_tokens || 0);

  // Donut slices — use total_cost_usd for proper cross-currency comparison
  const modelCostSlices = (byModel || [])
    .sort((a, b) => (b.total_cost_usd || 0) - (a.total_cost_usd || 0))
    .map((m, i) => ({ label: m.model_name, value: m.total_cost_usd || 0, color: PIE_COLORS[i % PIE_COLORS.length] }));

  const apiKeyCostSlices = (byApiKey || [])
    .sort((a, b) => (b.total_cost_usd || 0) - (a.total_cost_usd || 0))
    .map((k, i) => ({ label: k.api_key_name || k.api_key_preview || '—', value: k.total_cost_usd || 0, color: PIE_COLORS[i % PIE_COLORS.length] }));

  const tokenSlices = totals ? [
    { label: t('group.statistics.input'), value: totals.input_tokens, color: '#3b82f6' },
    { label: t('group.statistics.output'), value: totals.output_tokens, color: '#10b981' },
    { label: t('group.statistics.reasoning'), value: totals.reasoning_tokens || 0, color: '#f59e0b' },
    { label: t('group.statistics.cacheHit'), value: totals.cache_tokens || 0, color: '#8b5cf6' },
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
            <h2 className="text-lg font-bold text-slate-800">{t('group.statistics.title')}</h2>
            <p className="text-sm text-slate-500">{t('group.statistics.subtitle', { days })}</p>
          </div>
        </div>
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}
          className="text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white">
          <option value={7}>{t('group.statistics.last7Days')}</option>
          <option value={14}>{t('group.statistics.last14Days')}</option>
          <option value={30}>{t('group.statistics.last30Days')}</option>
        </select>
      </div>

      {loading ? (
        <div className="text-center py-16 text-slate-400">{t('group.statistics.loading')}</div>
      ) : (!totals || totals.requests === 0) ? (
        <div className="text-center py-16 text-slate-400">
          <BarChart3 className="w-12 h-12 mx-auto mb-3 text-slate-200" />
          <p>{t('group.statistics.noData')}</p>
        </div>
      ) : (
        <>
          {/* ── KPI Cards ──────────────────────────────────────────────────── */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-gradient-to-br from-emerald-500 to-emerald-600 rounded-2xl p-4 text-white shadow">
              <div className="flex items-center space-x-2 mb-1"><DollarSign className="w-4 h-4" /><span className="text-xs text-white/80">{t('group.statistics.totalCostUSD')}</span></div>
              <p className="text-2xl font-bold">{fmtCost(byCurrency?.total_cost_usd || 0)}</p>
              {(byCurrency?.currencies?.length ?? 0) >= 1 && (
                <div className="mt-1.5 space-y-0.5">
                  {byCurrency!.currencies.map((c) => (
                    <div key={c.currency} className="flex items-center justify-between text-xs text-white/70">
                      <span>{c.currency}</span>
                      <span className="tabular-nums">{fmtCostWithSymbol(c.total_cost_native, c.currency)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="bg-gradient-to-br from-blue-500 to-blue-600 rounded-2xl p-4 text-white shadow">
              <div className="flex items-center space-x-2 mb-1"><TrendingUp className="w-4 h-4" /><span className="text-xs text-white/80">{t('group.statistics.totalTokens')}</span></div>
              <p className="text-2xl font-bold">{fmtNum(totalTokens)}</p>
            </div>
            <div className="bg-gradient-to-br from-indigo-500 to-indigo-600 rounded-2xl p-4 text-white shadow">
              <div className="flex items-center space-x-2 mb-1"><BarChart3 className="w-4 h-4" /><span className="text-xs text-white/80">{t('group.statistics.totalRequests')}</span></div>
              <p className="text-2xl font-bold">{fmtNum(totals.requests)}</p>
            </div>
            <div className="bg-gradient-to-br from-violet-500 to-violet-600 rounded-2xl p-4 text-white shadow">
              <div className="flex items-center space-x-2 mb-1"><Cpu className="w-4 h-4" /><span className="text-xs text-white/80">{t('group.statistics.usedModels')}</span></div>
              <p className="text-2xl font-bold">{byModel?.length ?? 0}</p>
            </div>
          </div>

          {/* ── Two charts side by side: Token trend + Cost trend ─────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
              <h3 className="text-sm font-bold text-slate-800 mb-4 flex items-center space-x-2">
                <TrendingUp className="w-4 h-4 text-blue-500" />
                <span>{t('group.statistics.dailyTokenTrend')}</span>
              </h3>
              <DailyBarChart data={timeSeries || []} t={t} />
            </div>
            <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
              <h3 className="text-sm font-bold text-slate-800 mb-4 flex items-center space-x-2">
                <DollarSign className="w-4 h-4 text-amber-500" />
                <span>{t('group.statistics.dailyCostByModel')}</span>
              </h3>
              <DailyCostByModelChart data={timeSeriesByModel || []} t={t} />
            </div>
          </div>

          {/* ── Donut Charts Row: Token Distribution + Model Cost + API Key Cost */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Token Distribution */}
            <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
              <h3 className="text-xs font-bold text-slate-600 mb-4">{t('group.statistics.tokenDistribution')}</h3>
              <div className="flex flex-col items-center">
                <StatDonut slices={tokenSlices} centerValue={fmtNum(totalTokens)} centerLabel={t('group.statistics.totalLabel')} />
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
              <h3 className="text-xs font-bold text-slate-600 mb-4">{t('group.statistics.modelCostDistribution')}</h3>
              <div className="flex flex-col items-center">
                <StatDonut slices={modelCostSlices} centerValue={fmtCost(byCurrency?.total_cost_usd || 0)} centerLabel={t('group.statistics.totalCostLabel')} />
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
              <h3 className="text-xs font-bold text-slate-600 mb-4">{t('group.statistics.apiKeyCostDistribution')}</h3>
              <div className="flex flex-col items-center">
                <StatDonut slices={apiKeyCostSlices} centerValue={fmtCost(byCurrency?.total_cost_usd || 0)} centerLabel={t('group.statistics.totalCostLabel')} />
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