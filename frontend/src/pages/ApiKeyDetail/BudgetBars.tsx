import { DollarSign } from 'lucide-react';
import type { BudgetRecord } from '../../api/types';
import { fmtCost, BUDGET_COLORS } from './utils';

interface Props {
  budgets: BudgetRecord[];
  remaining: number;
  unlimitedBudget: boolean;
  onEdit: () => void;
}

const BudgetBars = ({ budgets, remaining, unlimitedBudget, onEdit }: Props) => {
  const budgetsWithRemaining = budgets.filter(b => b.remaining > 0);

  // Total budget: only sum amounts of budgets that still have remaining > 0
  const totalBudget = budgetsWithRemaining.reduce((sum, b) => sum + b.amount, 0);

  // Calculate the percentage of each budget relative to the total
  const availableWidth = 100;

  // Sum of remaining amounts from active budgets
  const remainingSum = budgetsWithRemaining.reduce((s, b) => s + b.remaining, 0);

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-5 transition-all hover:shadow-md duration-300">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center space-x-2.5">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-slate-600 to-slate-900 flex items-center justify-center shadow-lg">
            <DollarSign className="w-4.5 h-4.5 text-white" />
          </div>
          <div>
            <h3 className="font-bold text-slate-800 text-sm">预算管理</h3>
            <p className="text-[11px] text-slate-400">{unlimitedBudget ? '不限制' : `已使用 ${fmtCost(totalBudget - remainingSum)} / ${fmtCost(totalBudget)}`}</p>
          </div>
        </div>
        <button onClick={onEdit}
          className="text-xs font-medium text-indigo-600 hover:text-indigo-700 bg-indigo-50 hover:bg-indigo-100 px-3 py-1.5 rounded-lg transition-all duration-200">
          管理预算
        </button>
      </div>

      {!unlimitedBudget && totalBudget > 0 && (
        <>
          {/* Progress bars */}
          <div className="relative mt-2">
            {/* Background track */}
            <div className="h-[18px] bg-slate-100 rounded-full overflow-hidden flex">
              {budgetsWithRemaining.length > 0 ? (
                budgetsWithRemaining.map((b, i) => {
                  const pct = totalBudget > 0 ? (b.remaining / totalBudget) * availableWidth : 0;
                  const color = BUDGET_COLORS[i % BUDGET_COLORS.length];
                  // Calculate offset: sum of previous segments' percentages
                  const offset = budgetsWithRemaining.slice(0, i).reduce((s, pb) => s + (totalBudget > 0 ? (pb.remaining / totalBudget) * availableWidth : 0), 0);
                  return (
                    <div
                      key={b.id}
                      className="h-full transition-all duration-500 relative group"
                      style={{
                        width: `${pct}%`,
                        marginLeft: i === 0 ? 0 : `${-offset + offset}px`,
                        background: `linear-gradient(135deg, ${color}, ${color}cc)`,
                        borderRadius: i === 0 ? '999px 0 0 999px' : i === budgetsWithRemaining.length - 1 ? '0 999px 999px 0' : '0',
                        boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.2)',
                      }}
                    >
                      {/* Tooltip on hover */}
                      <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 hidden group-hover:block z-20">
                        <div className="bg-slate-900 text-white text-[10px] px-2 py-1 rounded-lg whitespace-nowrap shadow-xl">
                          {fmtCost(b.remaining)} 剩余
                        </div>
                      </div>
                    </div>
                  );
                })
              ) : (
                <div className="h-full w-full bg-gradient-to-r from-slate-300 to-slate-400 rounded-full" />
              )}
            </div>
            {/* Used marker */}
            <div className="absolute top-0 left-0 h-[18px] flex items-center">
              {budgetsWithRemaining.length === 0 && (
                <span className="text-[10px] text-white font-medium ml-2">已用完</span>
              )}
            </div>
          </div>

          {/* Budget segments */}
          {budgetsWithRemaining.length > 0 && (
            <div className="mt-2.5 space-y-1">
              {budgetsWithRemaining.slice(0, 5).map((b, i) => {
                const pct = totalBudget > 0 ? (b.remaining / totalBudget) * 100 : 0;
                const color = BUDGET_COLORS[i % BUDGET_COLORS.length];
                return (
                  <div key={b.id} className="flex items-center justify-between text-xs py-1 px-1.5 rounded-md hover:bg-slate-50 transition-colors">
                    <div className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
                      <span className="text-slate-400">
                        {(() => {
                          try {
                            return new Date(b.created_at || '').toLocaleDateString('zh-CN');
                          } catch {
                            return '-';
                          }
                        })()} 追加
                      </span>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-slate-600">{fmtCost(b.remaining)}</span>
                      <span className="text-slate-300 w-12 text-right">{pct.toFixed(1)}%</span>
                    </div>
                  </div>
                );
              })}
              {budgetsWithRemaining.length > 5 && (
                <div className="text-xs text-slate-400 text-center pt-1">还有 {budgetsWithRemaining.length - 5} 笔预算</div>
              )}
            </div>
          )}
        </>
      )}

      {/* State card */}
      <div className="mt-3 flex items-center justify-between p-3 bg-gradient-to-r from-slate-50 to-slate-50/50 rounded-xl border border-slate-100">
        <div>
          <p className="text-[11px] text-slate-400 font-medium uppercase">当前状态</p>
          <p className="text-sm font-bold mt-0.5" style={{
            color: unlimitedBudget ? '#059669' : (remaining > 0 ? '#2563eb' : '#dc2626'),
          }}>
            {unlimitedBudget ? '不限制' : (remaining > 0 ? `剩余 ¥${Number(remaining).toFixed(2)}` : '已耗尽')}
          </p>
        </div>
        <div className="text-right">
          <p className="text-[11px] text-slate-400">预算总额</p>
          <p className="text-sm font-bold text-slate-700 mt-0.5">{fmtCost(totalBudget)}</p>
        </div>
      </div>
    </div>
  );
};

export default BudgetBars;