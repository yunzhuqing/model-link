import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import client from '../../api/client';
import type { BudgetRecord } from '../../api/types';
import { fmtCost, BUDGET_COLORS } from './utils';
import { X, Plus, RotateCcw, AlertCircle } from 'lucide-react';

interface Props {
  apiKeyId: number;
  isUnlimitedBudget: boolean;
  currentRemaining: number;
  budgets: BudgetRecord[];
  onClose: () => void;
  permissions?: Record<string, boolean>;
}

const BudgetEditModal = ({ apiKeyId, isUnlimitedBudget, budgets, onClose, permissions = {} }: Props) => {
  const canToggleUnlimited = permissions['apikey.unlimited_budget'] !== false;
  const canAddBudget = permissions['apikey.add_budget'] !== false;
  const queryClient = useQueryClient();
  const [addAmount, setAddAmount] = useState('');
  const [isUnlimited, setIsUnlimited] = useState(isUnlimitedBudget);
  const budgetsWithRemaining = budgets.filter(b => b.remaining > 0);
  const totalRemaining = budgetsWithRemaining.reduce((s, b) => s + b.remaining, 0);
  // Show all active budgets + up to 2 most recently exhausted ones
  const displayBudgets = (() => {
    const active = budgets.filter(b => b.remaining > 0);
    const exhausted = budgets
      .filter(b => b.remaining <= 0)
      .sort((a, b) => new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime())
      .slice(0, 2);
    return [...active, ...exhausted];
  })();

  const toggleMutation = useMutation({
    mutationFn: async (params: { unlimited_budget: boolean }) => {
      await client.put(`/api/apikeys/${apiKeyId}`, params);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['apiKeyDetail', String(apiKeyId)] });
    },
  });

  const addBudgetMutation = useMutation({
    mutationFn: async (amount: number) => {
      await client.post(`/api/apikeys/${apiKeyId}/budgets`, { amount });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['apiKeyDetail', String(apiKeyId)] });
      setAddAmount('');
      onClose();
    },
  });

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
      if (isUnlimited) {
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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-lg mx-auto overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-slate-100">
          <h3 className="text-base font-bold text-slate-800 flex items-center gap-2">
            <Plus className="w-4 h-4 text-indigo-500" />
            预算管理
          </h3>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-100 transition-colors">
            <X className="w-4 h-4 text-slate-400" />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 space-y-4">
          {canToggleUnlimited && (
          <div className="flex items-center justify-between p-3 bg-slate-50 rounded-xl border border-slate-100">
            <div className="flex items-center gap-2">
              <RotateCcw className="w-4 h-4 text-slate-400" />
              <span className="text-sm font-medium text-slate-700">不限制预算</span>
            </div>
            <button
              onClick={() => {
                const newVal = !isUnlimited;
                setIsUnlimited(newVal);
                toggleMutation.mutate({ unlimited_budget: newVal });
              }}
              className={`relative w-11 h-6 rounded-full transition-colors ${isUnlimited ? 'bg-indigo-500' : 'bg-slate-300'}`}
            >
              <span className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${isUnlimited ? 'translate-x-5' : ''}`} />
            </button>
          </div>
          )}

          {/* Add Budget */}
          {!isUnlimited && canAddBudget && (
            <div className="p-4 bg-gradient-to-br from-indigo-50/50 to-transparent border border-indigo-100/50 rounded-xl">
              <label className="text-xs font-medium text-slate-500 mb-2 block">追加预算 (USD)</label>
              <div className="flex items-center gap-2">
                <div className="flex-1 relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm font-bold text-slate-400">$</span>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={addAmount}
                    onChange={(e) => setAddAmount(e.target.value)}
                    placeholder="输入金额"
                    className="w-full pl-7 pr-3 py-2.5 text-sm border border-slate-200 rounded-xl focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400 outline-none transition-all"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleAddBudget();
                    }}
                  />
                </div>
                <button
                  onClick={handleAddBudget}
                  disabled={!addAmount || parseFloat(addAmount) <= 0 || addBudgetMutation.isPending}
                  className="px-4 py-2.5 bg-indigo-500 hover:bg-indigo-600 disabled:bg-slate-300 text-white text-sm font-medium rounded-xl transition-all duration-200 disabled:cursor-not-allowed flex items-center gap-1"
                >
                  {addBudgetMutation.isPending ? (
                    <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  ) : (
                    <>
                      <Plus className="w-3.5 h-3.5" />
                      追加
                    </>
                  )}
                </button>
              </div>
            </div>
          )}

          {/* Budget history */}
          {!isUnlimited && displayBudgets.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold text-slate-500 uppercase mb-2">预算记录</h4>
              <div className="space-y-1 max-h-48 overflow-y-auto">
                {displayBudgets.map((b, i) => {
                  const isExhausted = b.remaining <= 0;
                  const pct = totalRemaining > 0 ? (b.remaining / totalRemaining) * 100 : 0;
                  const color = BUDGET_COLORS[i % BUDGET_COLORS.length];
                  return (
                    <div key={b.id} className="flex items-center justify-between py-2 px-3 rounded-xl hover:bg-slate-50 transition-colors group">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: isExhausted ? '#cbd5e1' : color }} />
                        <span className={`text-xs ${isExhausted ? 'text-slate-300' : 'text-slate-500'}`}>
                          追加 {(() => {
                            try {
                              return new Date(b.created_at || '').toLocaleDateString('zh-CN');
                            } catch {
                              return '-';
                            }
                          })()}
                        </span>
                      </div>
                      <div className="flex items-center gap-3 flex-shrink-0">
                        <span className={`text-sm font-semibold ${isExhausted ? 'text-slate-300' : 'text-slate-700'}`}>{fmtCost(b.remaining)}</span>
                        {!isExhausted && <span className="text-xs text-slate-400 w-10 text-right">{pct.toFixed(0)}%</span>}
                        {canAddBudget && (
                          <button
                            onClick={() => {
                              if (window.confirm('确定删除此预算记录？')) {
                                deleteBudgetMutation.mutate(b.id);
                              }
                            }}
                            className={`p-1 rounded-lg ${isExhausted ? 'opacity-0' : 'opacity-0 group-hover:opacity-100'} hover:bg-red-50 transition-all`}
                          >
                            <X className="w-3.5 h-3.5 text-red-400" />
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Unlimited state info */}
          {isUnlimited && (
            <div className="flex items-start gap-2 p-3 bg-amber-50 rounded-xl border border-amber-100">
              <AlertCircle className="w-4 h-4 text-amber-500 mt-0.5 flex-shrink-0" />
              <p className="text-xs text-amber-700">
                当前为不限制状态，Api Key 可无限制调用。如需设置预算限制，请关闭「不限制预算」开关。
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default BudgetEditModal;