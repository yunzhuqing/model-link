import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import client from '../api/client';
import {
  Key, ArrowLeft, Copy, Check, Cpu, DollarSign, TrendingUp, Zap,
  Clock, Users, Shield, Gauge,
} from 'lucide-react';
import { useState } from 'react';

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
  budget: number | null;
  used: number;
  remaining: number | null;
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
  group: { id: number; name: string; description: string | null; created_at: string | null } | null;
  usage: {
    requests: number;
    input_tokens: number;
    output_tokens: number;
    reasoning_tokens: number;
    estimated_cost: number;
  };
  by_model: ModelUsage[];
  available_models: AvailableModel[];
  budget_info: BudgetInfo;
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

/* ── Component ─────────────────────────────────────────────────────────── */

const ApiKeyDetail = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [copiedKey, setCopiedKey] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ['apiKeyDetail', id],
    queryFn: async () => {
      const res = await client.get<ApiKeyDetailData>(`/api/apikeys/${id}/detail`);
      return res.data;
    },
    enabled: !!id,
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
  const budgetPct = budget.budget && budget.budget > 0 ? Math.min((budget.used / budget.budget) * 100, 100) : 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center space-x-4">
        <button
          onClick={() => navigate('/')}
          className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-xl transition-colors"
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

      {/* ── Budget + Usage Overview ──────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Budget Card */}
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-5">
          <div className="flex items-center space-x-2 mb-3">
            <DollarSign className="w-5 h-5 text-amber-500" />
            <h3 className="text-sm font-bold text-slate-800">预算</h3>
          </div>
          {budget.budget !== null ? (
            <>
              <div className="flex justify-between text-sm mb-2">
                <span className="text-slate-500">总额</span>
                <span className="font-bold text-slate-800">{fmtCost(budget.budget)}</span>
              </div>
              <div className="flex justify-between text-sm mb-2">
                <span className="text-slate-500">已使用</span>
                <span className="font-semibold text-amber-600">{fmtCost(budget.used)}</span>
              </div>
              <div className="flex justify-between text-sm mb-3">
                <span className="text-slate-500">剩余</span>
                <span className={`font-semibold ${(budget.remaining || 0) > 0 ? 'text-emerald-600' : 'text-red-600'}`}>
                  {fmtCost(Math.max(budget.remaining || 0, 0))}
                </span>
              </div>
              <div className="w-full bg-slate-100 rounded-full h-2.5">
                <div
                  className={`h-2.5 rounded-full transition-all ${
                    budgetPct > 90 ? 'bg-red-400' : budgetPct > 70 ? 'bg-amber-400' : 'bg-emerald-400'
                  }`}
                  style={{ width: `${budgetPct}%` }}
                />
              </div>
              <p className="text-xs text-slate-400 mt-1.5 text-right">{budgetPct.toFixed(1)}% 已使用</p>
            </>
          ) : (
            <div className="text-center py-4">
              <p className="text-slate-500 text-sm">无预算限制</p>
              <p className="text-xs text-slate-400 mt-1">已消费 {fmtCost(budget.used)}</p>
            </div>
          )}
        </div>

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

        {/* Request Stats */}
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-5">
          <div className="flex items-center space-x-2 mb-3">
            <Zap className="w-5 h-5 text-blue-500" />
            <h3 className="text-sm font-bold text-slate-800">请求统计</h3>
          </div>
          <div className="text-2xl font-bold text-slate-800 mb-1">{usage.requests.toLocaleString()}</div>
          <p className="text-xs text-slate-400">总请求次数</p>
          <div className="mt-3 space-y-2">
            <div className="flex justify-between text-sm">
              <span className="text-slate-500">消费金额</span>
              <span className="font-semibold text-amber-600">{fmtCost(usage.estimated_cost)}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-slate-500">最近使用</span>
              <span className="text-slate-600">{fmtDate(data.last_used_at)}</span>
            </div>
          </div>
        </div>
      </div>

      {/* ── Available Models ─────────────────────────────────────────── */}
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

      {/* ── Model Usage Breakdown ────────────────────────────────────── */}
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
    </div>
  );
};

export default ApiKeyDetail;
