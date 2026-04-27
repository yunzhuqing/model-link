import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import client from '../api/client';
import {
  Key, ArrowLeft, Copy, Check, Cpu, DollarSign, TrendingUp, Zap,
  Clock, Users, Shield, Gauge, List, BarChart3, Pencil, X, Save,
} from 'lucide-react';
import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import UsageRecordsTable from '../components/UsageRecordsTable';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface AvailableModel {
  name: string;
  alias: string | null;
  provider_name: string | null;
  rpm: number | null;
  tpm: number | null;
  input_price: number;
  output_price: number;
  currency: string;
}

interface ModelUsage {
  model_name: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  estimated_cost: number;
}

interface BudgetInfo {
  unlimited_budget: boolean;
  budget: number | null;
  used: number;
  remaining: number | null;
}

interface BudgetRecord {
  id: number;
  api_key_id: number;
  amount: number;
  remaining: number;
  created_at: string | null;
  updated_at: string | null;
}

interface TimeSeries {
  period: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  total_cost: number;
  total_cost_usd?: number;
}

interface ApiKeyDetailData {
  id: number;
  key: string;
  name: string;
  group_id: number;
  user_id: number | null;
  user_name: string | null;
  is_active: boolean;
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  request_count: number;
  token_count: number;
  allowed_models: string[];
  budget: number | null;
  api_key_hash?: string;
  group: { id: number; name: string; description: string | null; created_at: string | null } | null;
  usage: {
    requests: number;
    input_tokens: number;
    output_tokens: number;
    reasoning_tokens: number;
    estimated_cost: number;
    total_image_count?: number;
    total_video_count?: number;
    total_audio_seconds?: number;
  };
  by_model: ModelUsage[];
  available_models: AvailableModel[];
  budget_info: BudgetInfo;
  budgets?: BudgetRecord[];
  total_budget_remaining?: number;
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

function fmtDate(s: string | null): string {
  if (!s) return '-';
  const d = s.includes('T') && !s.endsWith('Z') && !s.includes('+') ? s + 'Z' : s;
  return new Date(d).toLocaleString('zh-CN');
}

/* ── Colors ─────────────────────────────────────────────────────────────── */

const PIE_COLORS = [
  '#6366f1', '#06b6d4', '#f59e0b', '#ef4444', '#10b981',
  '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#3b82f6',
];

/* ── TimeSeriesByModel interface ─────────────────────────────────────── */

interface TimeSeriesByModel {
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

/* ── Stacked Cost-by-Model Chart ──────────────────────────────────────── */

const DailyCostByModelChart = ({ data }: { data: TimeSeriesByModel[] }) => {
  const [hovered, setHovered] = useState<{ bar: number; segment: string } | null>(null);
  if (!data || data.length === 0) return <div className="text-center py-10 text-slate-400 text-sm">暂无模型消费数据</div>;

  // Build a map of period → { model_name → cost }
  const periodMap: Record<string, Record<string, number>> = {};
  const modelSet = new Set<string>();
  for (const d of data) {
    const p = String(d.period);
    if (!periodMap[p]) periodMap[p] = {};
    periodMap[p][d.model_name || 'unknown'] = d.total_cost_usd || 0;
    modelSet.add(d.model_name || 'unknown');
  }

  // Sort models by total cost descending
  const modelTotalCost: Record<string, number> = {};
  for (const m of modelSet) {
    modelTotalCost[m] = Object.values(periodMap).reduce((s, pm) => s + (pm[m] || 0), 0);
  }
  const models = Array.from(modelSet).sort((a, b) => (modelTotalCost[b] || 0) - (modelTotalCost[a] || 0));
  const periods = Object.keys(periodMap).sort();

  const maxCost = Math.max(...periods.map(p => Object.values(periodMap[p]).reduce((s, v) => s + v, 0)), 0.001);

  return (
    <div>
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
                    <div>消耗: {fmtCost(Object.values(dayModels).reduce((s, v) => s + v, 0))}</div>
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
  );
};

/* ── Component ─────────────────────────────────────────────────────────── */

/* ── Budget Stacked Bar Component ────────────────────────────────────── */

const BUDGET_COLORS = ['#6366f1', '#06b6d4', '#f59e0b', '#10b981', '#8b5cf6', '#ec4899', '#f97316', '#3b82f6'];

const BudgetBars = ({
  budgets,
  totalRemaining,
  isUnlimited,
  used,
  onEdit,
}: {
  budgets: BudgetRecord[];
  totalRemaining: number;
  isUnlimited: boolean;
  used: number;
  onEdit: () => void;
}) => {
  // Filter budgets: only show those with remaining > 0 (not exhausted)
  const activeBudgets = budgets.filter(b => b.remaining > 0);
  const totalActive = activeBudgets.reduce((s, b) => s + b.amount, 0);

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center space-x-2">
          <DollarSign className="w-5 h-5 text-amber-500" />
          <h3 className="text-sm font-bold text-slate-800">预算</h3>
        </div>
        <button
          onClick={onEdit}
          className="flex items-center space-x-1 text-xs text-slate-400 hover:text-blue-500 hover:bg-blue-50 px-2 py-1 rounded-lg transition-colors"
          title="编辑预算"
        >
          <Pencil className="w-3.5 h-3.5" />
          <span>管理</span>
        </button>
      </div>

      {!isUnlimited && activeBudgets.length > 0 ? (
        <div className="space-y-3">
          {/* Available quota */}
          <div className="flex justify-between items-baseline">
            <span className="text-xs text-slate-500">可用额度</span>
            <span className="text-2xl font-bold text-emerald-600">{fmtCost(totalRemaining)}</span>
          </div>

          {/* Stacked bar — each segment represents a budget record */}
          <div className="flex rounded-lg overflow-hidden h-6" title={`共 ${activeBudgets.length} 笔预算`}>
            {activeBudgets.map((b, i) => {
              const widthPct = totalActive > 0 ? (b.amount / totalActive) * 100 : 0;
              const usedPct = b.amount > 0 ? ((b.amount - b.remaining) / b.amount) * 100 : 0;
              const color = BUDGET_COLORS[i % BUDGET_COLORS.length];
              return (
                <div
                  key={b.id}
                  className="relative group cursor-default"
                  style={{ width: `${Math.max(widthPct, 2)}%` }}
                >
                  {/* Background (total amount) */}
                  <div className="absolute inset-0" style={{ backgroundColor: color, opacity: 0.2 }} />
                  {/* Remaining fill (from bottom) */}
                  <div
                    className="absolute bottom-0 left-0 right-0 transition-all"
                    style={{
                      height: `${100 - usedPct}%`,
                      backgroundColor: color,
                      opacity: 0.7,
                    }}
                  />
                  {/* First budget indicator (currently being consumed) */}
                  {i === 0 && (
                    <div className="absolute top-0 left-0 w-full h-full border-2 rounded-l-lg" style={{ borderColor: color }} />
                  )}
                  {/* Tooltip */}
                  <div className="absolute -top-16 left-1/2 -translate-x-1/2 bg-slate-800 text-white text-xs px-2.5 py-1.5 rounded-lg whitespace-nowrap z-20 shadow-xl hidden group-hover:block">
                    <div className="font-semibold">预算 #{i + 1}</div>
                    <div>总额: {fmtCost(b.amount)} · 剩余: {fmtCost(b.remaining)}</div>
                    <div className="absolute bottom-0 left-1/2 -translate-x-1/2 translate-y-1/2 w-2 h-2 bg-slate-800 rotate-45" />
                  </div>
                </div>
              );
            })}
          </div>

          {/* Legend for active budgets */}
          <div className="space-y-1">
            {activeBudgets.map((b, i) => {
              const color = BUDGET_COLORS[i % BUDGET_COLORS.length];
              return (
                <div key={b.id} className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ backgroundColor: color }} />
                    <span className="text-slate-500">
                      {i === 0 ? '🔥 当前' : `预算 #${i + 1}`}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-slate-400">{fmtCost(b.amount)}</span>
                    <span className="font-semibold" style={{ color }}>
                      剩余 {fmtCost(b.remaining)}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Exhausted budgets count */}
          {budgets.length > activeBudgets.length && (
            <p className="text-xs text-slate-400">
              已耗尽 {budgets.length - activeBudgets.length} 笔预算
            </p>
          )}
        </div>
      ) : !isUnlimited && budgets.length === 0 ? (
        <div className="text-center py-4">
          <p className="text-slate-500 text-sm">暂无预算</p>
          <p className="text-xs text-slate-400 mt-1">点击"管理"追加预算</p>
          <p className="text-xs text-slate-400 mt-0.5">已消费 {fmtCost(used)}</p>
        </div>
      ) : (
        <div className="text-center py-4">
          <div className="text-3xl mb-1">∞</div>
          <p className="text-slate-500 text-sm">无预算限制</p>
          <p className="text-xs text-slate-400 mt-1">已消费 {fmtCost(used)}</p>
        </div>
      )}
    </div>
  );
};

/* ── Budget Edit Modal ────────────────────────────────────────────────── */

const BudgetEditModal = ({
  apiKeyId,
  isUnlimitedBudget,
  currentRemaining,
  budgets: existingBudgets,
  onClose,
}: {
  apiKeyId: number;
  isUnlimitedBudget: boolean;
  currentRemaining: number | null;
  budgets: BudgetRecord[];
  onClose: () => void;
}) => {
  const [addAmount, setAddAmount] = useState('');
  const [isUnlimited, setIsUnlimited] = useState(isUnlimitedBudget);
  const queryClient = useQueryClient();

  // Toggle unlimited mutation
  const toggleMutation = useMutation({
    mutationFn: async (params: { unlimited_budget: boolean }) => {
      await client.put(`/api/apikeys/${apiKeyId}`, params);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['apiKeyDetail', String(apiKeyId)] });
      onClose();
    },
  });

  // Add budget record mutation (new API)
  const addBudgetMutation = useMutation({
    mutationFn: async (amount: number) => {
      await client.post(`/api/apikeys/${apiKeyId}/budgets`, { amount });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['apiKeyDetail', String(apiKeyId)] });
      setAddAmount('');
    },
  });

  // Delete budget record mutation
  const deleteBudgetMutation = useMutation({
    mutationFn: async (budgetId: number) => {
      await client.delete(`/api/apikeys/${apiKeyId}/budgets/${budgetId}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['apiKeyDetail', String(apiKeyId)] });
    },
  });

  const handleAddBudget = () => {
    const val = parseFloat(addAmount);
    if (!isNaN(val) && val > 0) {
      // First ensure unlimited is off
      if (isUnlimited) {
        // Switch to limited mode, then add budget
        toggleMutation.mutate({ unlimited_budget: false }, {
          onSuccess: () => {
            addBudgetMutation.mutate(val);
          },
        });
      } else {
        addBudgetMutation.mutate(val);
      }
    }
  };

  const handleToggleUnlimited = () => {
    toggleMutation.mutate({ unlimited_budget: !isUnlimited });
  };

  const isPending = toggleMutation.isPending || addBudgetMutation.isPending || deleteBudgetMutation.isPending;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl border border-slate-200 w-full max-w-lg mx-4 p-6 max-h-[85vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-lg font-bold text-slate-800 flex items-center gap-2">
            <DollarSign className="w-5 h-5 text-amber-500" />
            预算管理
          </h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 p-1 rounded-lg hover:bg-slate-100 transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="space-y-4">
          {/* Toggle unlimited */}
          <div className="flex items-center justify-between">
            <label className="flex items-center space-x-3 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={isUnlimited}
                onChange={(e) => setIsUnlimited(e.target.checked)}
                className="w-4 h-4 text-blue-600 rounded border-slate-300 focus:ring-blue-500"
              />
              <span className="text-sm text-slate-700">无预算限制</span>
            </label>
            {isUnlimited !== isUnlimitedBudget && (
              <button
                onClick={handleToggleUnlimited}
                disabled={isPending}
                className="text-xs text-blue-600 hover:text-blue-700 font-medium"
              >
                {isPending ? '保存中...' : '应用'}
              </button>
            )}
          </div>

          {/* Existing budget records */}
          {!isUnlimited && existingBudgets.length > 0 && (
            <div>
              <p className="text-xs text-slate-500 mb-2">预算记录</p>
              <div className="space-y-1.5">
                {existingBudgets.map((b, i) => {
                  const isExhausted = b.remaining <= 0;
                  const color = BUDGET_COLORS[i % BUDGET_COLORS.length];
                  return (
                    <div key={b.id} className={`flex items-center justify-between text-xs px-3 py-2 rounded-lg ${isExhausted ? 'bg-slate-50 opacity-50' : 'bg-slate-50'}`}>
                      <div className="flex items-center gap-2">
                        <span className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ backgroundColor: isExhausted ? '#cbd5e1' : color }} />
                        <span className="text-slate-600">
                          {fmtCost(b.amount)}
                        </span>
                        <span className="text-slate-400">→</span>
                        <span className={isExhausted ? 'text-slate-400' : 'text-emerald-600 font-semibold'}>
                          {isExhausted ? '已耗尽' : `剩余 ${fmtCost(b.remaining)}`}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-slate-400">{b.created_at ? fmtDate(b.created_at).slice(0, 10) : ''}</span>
                        {b.remaining > 0 && (
                          <button
                            onClick={() => {
                              if (window.confirm(`确定要删除这笔预算 (${fmtCost(b.amount)}) 吗？剩余 ${fmtCost(b.remaining)} 将被退回。`)) {
                                deleteBudgetMutation.mutate(b.id);
                              }
                            }}
                            className="text-slate-300 hover:text-red-500 transition-colors"
                            title="删除预算"
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="flex justify-between text-xs mt-2 px-1">
                <span className="text-slate-400">共 {existingBudgets.length} 笔</span>
                <span className="text-emerald-600 font-semibold">
                  可用: {fmtCost(currentRemaining || 0)}
                </span>
              </div>
            </div>
          )}

          {/* Add budget input */}
          {!isUnlimited && (
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1.5">
                追加预算 (USD)
              </label>
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm">+$</span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={addAmount}
                    onChange={(e) => setAddAmount(e.target.value)}
                    placeholder="金额，例如: 100.00"
                    className="w-full pl-10 pr-4 py-2.5 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-colors"
                    autoFocus
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleAddBudget();
                    }}
                  />
                </div>
                <button
                  onClick={handleAddBudget}
                  disabled={isPending || !addAmount || parseFloat(addAmount) <= 0}
                  className="flex items-center space-x-1.5 px-4 py-2.5 text-sm text-white bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 rounded-xl transition-colors flex-shrink-0"
                >
                  <Save className="w-4 h-4" />
                  <span>{addBudgetMutation.isPending ? '追加中...' : '追加'}</span>
                </button>
              </div>
              {addAmount && parseFloat(addAmount) > 0 && (
                <p className="text-xs text-emerald-600 mt-1.5">
                  追加后可用: {fmtCost((currentRemaining || 0) + parseFloat(addAmount))}
                </p>
              )}
            </div>
          )}

          {/* Quick presets */}
          {!isUnlimited && (
            <div>
              <p className="text-xs text-slate-500 mb-2">快速追加</p>
              <div className="flex flex-wrap gap-2">
                {[1, 5, 10, 50, 100, 500, 1000].map(v => (
                  <button
                    key={v}
                    onClick={() => setAddAmount(String(v))}
                    className={`px-3 py-1.5 text-xs rounded-lg border transition-colors ${
                      addAmount === String(v)
                        ? 'bg-blue-50 border-blue-300 text-blue-700 font-medium'
                        : 'bg-white border-slate-200 text-slate-600 hover:bg-slate-50'
                    }`}
                  >
                    +${v}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Close */}
        <div className="flex justify-end mt-6 pt-4 border-t border-slate-100">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-slate-600 hover:text-slate-800 hover:bg-slate-100 rounded-xl transition-colors"
          >
            关闭
          </button>
        </div>

        {(toggleMutation.isError || addBudgetMutation.isError || deleteBudgetMutation.isError) && (
          <p className="text-xs text-red-500 mt-2">操作失败，请重试</p>
        )}
      </div>
    </div>
  );
};

/* ── Component ─────────────────────────────────────────────────────────── */

const ApiKeyDetail = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [copiedKey, setCopiedKey] = useState(false);
  const [activeTab, setActiveTab] = useState<'overview' | 'models' | 'model_usage' | 'usage'>('overview');
  const [costDays, setCostDays] = useState(7);
  const [showBudgetModal, setShowBudgetModal] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ['apiKeyDetail', id],
    queryFn: async () => {
      const res = await client.get<ApiKeyDetailData>(`/api/apikeys/${id}/detail`);
      return res.data;
    },
    enabled: !!id,
  });

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
  const totalTokens = usage.input_tokens + usage.output_tokens;

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
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Budget Bars Card */}
          <BudgetBars
            budgets={data.budgets || []}
            totalRemaining={data.total_budget_remaining || 0}
            isUnlimited={budget.unlimited_budget}
            used={budget.used}
            onEdit={() => setShowBudgetModal(true)}
          />

          {/* Token Stats */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-5">
            <div className="flex items-center space-x-2 mb-3">
              <TrendingUp className="w-5 h-5 text-emerald-500" />
              <h3 className="text-sm font-bold text-slate-800">Token 消耗</h3>
            </div>
            <div className="text-2xl font-bold text-slate-800 mb-1">{fmtNum(totalTokens)}</div>
            <div className="grid grid-cols-2 gap-2 mt-3">
              <div className="bg-blue-50 rounded-lg p-2.5">
                <p className="text-xs text-blue-500">输入</p>
                <p className="text-sm font-bold text-blue-700">{fmtNum(usage.input_tokens)}</p>
              </div>
              <div className="bg-emerald-50 rounded-lg p-2.5">
                <p className="text-xs text-emerald-500">输出</p>
                <p className="text-sm font-bold text-emerald-700">{fmtNum(usage.output_tokens)}</p>
              </div>
            </div>
            {usage.reasoning_tokens > 0 && (
              <div className="mt-2 bg-violet-50 rounded-lg p-2.5">
                <p className="text-xs text-violet-500">推理</p>
                <p className="text-sm font-bold text-violet-700">{fmtNum(usage.reasoning_tokens)}</p>
              </div>
            )}
          </div>

          {/* Request & Generation Stats */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-5">
            <div className="flex items-center space-x-2 mb-3">
              <Zap className="w-5 h-5 text-blue-500" />
              <h3 className="text-sm font-bold text-slate-800">消费总览</h3>
            </div>
            <div className="text-2xl font-bold text-amber-600 mb-1">{fmtCost(usage.estimated_cost)}</div>
            <p className="text-xs text-slate-400">历史总消费 (USD)</p>
            <div className="mt-3 space-y-1.5">
              <div className="flex justify-between text-sm">
                <span className="text-slate-500">请求次数</span>
                <span className="font-semibold text-slate-700">{usage.requests.toLocaleString()}</span>
              </div>
              {(usage.total_image_count || 0) > 0 && (
                <div className="flex justify-between text-sm">
                  <span className="text-slate-500">🖼️ 图片生成</span>
                  <span className="font-semibold text-pink-600">{(usage.total_image_count || 0).toLocaleString()} 张</span>
                </div>
              )}
              {(usage.total_video_count || 0) > 0 && (
                <div className="flex justify-between text-sm">
                  <span className="text-slate-500">🎬 视频生成</span>
                  <span className="font-semibold text-purple-600">{(usage.total_video_count || 0).toLocaleString()} 个</span>
                </div>
              )}
              {(usage.total_audio_seconds || 0) > 0 && (
                <div className="flex justify-between text-sm">
                  <span className="text-slate-500">🔊 音频生成</span>
                  <span className="font-semibold text-cyan-600">{(usage.total_audio_seconds || 0).toFixed(1)}s</span>
                </div>
              )}
              <div className="flex justify-between text-sm">
                <span className="text-slate-500">最近使用</span>
                <span className="text-slate-600">{fmtDate(data.last_used_at)}</span>
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
                  <svg width={CHART_W} height={TOTAL_H} className="w-full" style={{ minHeight: TOTAL_H }}>
                    {yTicks.map((t, i) => (
                      <g key={`y-${i}`}>
                        <line x1={LEFT_PAD} y1={t.y} x2={CHART_W - 10} y2={t.y} stroke="#e2e8f0" strokeWidth={1} strokeDasharray={i === 0 ? undefined : '4 2'} />
                        <text x={LEFT_PAD - 6} y={t.y + 4} textAnchor="end" fontSize={10} fill="#94a3b8">{fmtY(t.val)}</text>
                      </g>
                    ))}
                    {d.map((item, i) => {
                      const gx = LEFT_PAD + i * GROUP_W;
                      const bx = gx + (GROUP_W - BAR_W) / 2;
                      const h = Math.max(1, Math.round((values[i] / maxVal) * BAR_H));
                      const isHov = hovered === i;
                      // Parse period as UTC and format in local timezone
                      const periodStr = item.period.includes('T') && !item.period.endsWith('Z') && !item.period.includes('+') ? item.period + 'Z' : item.period;
                      const periodDate = new Date(periodStr);
                      const label = `${String(periodDate.getMonth() + 1).padStart(2, '0')}-${String(periodDate.getDate()).padStart(2, '0')} ${String(periodDate.getHours()).padStart(2, '0')}:00`;
                      return (
                        <g key={i}
                          onMouseEnter={() => setHovered(i)}
                          onMouseLeave={() => setHovered(null)}
                          style={{ cursor: 'default' }}
                        >
                          {isHov && <rect x={gx} y={TOP_PAD} width={GROUP_W} height={BAR_H} fill="#f1f5f9" rx={3} />}
                          <rect x={bx} y={BOTTOM - h} width={BAR_W} height={h} fill={color} opacity={isHov ? 1 : 0.7} rx={2} />
                          {i % labelEvery === 0 && (
                            <text x={gx + GROUP_W / 2} y={BOTTOM + 8} textAnchor="end" fontSize={9}
                              fill={isHov ? '#334155' : '#94a3b8'} fontWeight={isHov ? '600' : '400'}
                              transform={`rotate(-45, ${gx + GROUP_W / 2}, ${BOTTOM + 8})`}>{label}</text>
                          )}
                        </g>
                      );
                    })}
                    {/* Hover tooltip */}
                    {hovered !== null && (() => {
                      const cx = LEFT_PAD + hovered * GROUP_W + GROUP_W / 2;
                      const tipW = 130;
                      const tipX = Math.min(Math.max(cx - tipW / 2, 4), CHART_W - tipW - 4);
                      const hPeriodStr = d[hovered].period.includes('T') && !d[hovered].period.endsWith('Z') && !d[hovered].period.includes('+') ? d[hovered].period + 'Z' : d[hovered].period;
                      const hDate = new Date(hPeriodStr);
                      const timeLabel = `${String(hDate.getMonth() + 1).padStart(2, '0')}-${String(hDate.getDate()).padStart(2, '0')} ${String(hDate.getHours()).padStart(2, '0')}:00`;
                      return (
                        <g>
                          <rect x={tipX} y={1} width={tipW} height={24} rx={6} fill="#1e293b" opacity={0.92} />
                          <text x={tipX + tipW / 2} y={15} textAnchor="middle" fontSize={10} fill="white" fontWeight="500">
                            {timeLabel} {fmtY(values[hovered])}
                          </text>
                        </g>
                      );
                    })()}
                  </svg>
                  <div className="flex items-center gap-4 mt-2 text-xs text-slate-500">
                    <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm inline-block" style={{ backgroundColor: color }} /> {legendLabel}</span>
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
          <div className="flex items-center space-x-2 mb-4">
            <Shield className="w-5 h-5 text-blue-500" />
            <h2 className="text-base font-bold text-slate-800">可用模型</h2>
            <span className="text-xs text-slate-400 ml-2">
              {data.allowed_models.length > 0 ? `限制 ${data.allowed_models.length} 个模型` : '不限制'}
               · 共 {data.available_models.length} 个可用
            </span>
          </div>
          {data.available_models.length > 0 ? (
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
                  </tr>
                </thead>
                <tbody>
                  {data.available_models.map((m, idx) => (
                    <tr key={idx} className="border-b border-slate-50 hover:bg-slate-50/60 transition-colors">
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
                        ${m.input_price}/{m.currency === 'CNY' ? '¥' : ''}1M
                      </td>
                      <td className="py-2.5 px-3 text-right text-slate-600">
                        ${m.output_price}/{m.currency === 'CNY' ? '¥' : ''}1M
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-8 text-slate-400 text-sm">暂无可用模型</div>
          )}
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
                      <tr key={idx} className="border-b border-slate-50 hover:bg-slate-50/60 transition-colors">
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
                    <td className="py-2.5 px-3 text-right font-bold text-slate-700">{fmtNum(totalTokens)}</td>
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
        />
      )}
    </div>
  );
};

export default ApiKeyDetail;
