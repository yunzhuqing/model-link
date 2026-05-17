import { useState, useEffect } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiKeysApi } from '../../api/client';
import type { ApiKeyPolicy } from '../../api/types';
import { X, Save, ToggleLeft, ToggleRight, Info } from 'lucide-react';

interface Props {
  apiKeyId: number;
  policy: ApiKeyPolicy | null;
  onClose: () => void;
}

const CompressionSettingsModal = ({ apiKeyId, policy, onClose }: Props) => {
  const queryClient = useQueryClient();
  const [enabled, setEnabled] = useState(policy?.enabled ?? false);
  const [perMinute, setPerMinute] = useState(policy?.config?.per_minute ?? 1);
  const [perHour, setPerHour] = useState(policy?.config?.per_hour ?? 60);

  useEffect(() => {
    setEnabled(policy?.enabled ?? false);
    setPerMinute(policy?.config?.per_minute ?? 1);
    setPerHour(policy?.config?.per_hour ?? 60);
  }, [policy]);

  const upsertMutation = useMutation({
    mutationFn: async () => {
      await apiKeysApi.upsertPolicy(apiKeyId, 'compress', {
        enabled,
        config: { per_minute: perMinute, per_hour: perHour },
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['apiKeyDetail', String(apiKeyId)] });
      onClose();
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-md mx-auto overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-slate-100">
          <h3 className="text-base font-bold text-slate-800">
            记录压缩设置
          </h3>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-100 transition-colors">
            <X className="w-4 h-4 text-slate-400" />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 space-y-4">
          {/* Enable toggle */}
          <div className="flex items-center justify-between p-3 bg-slate-50 rounded-xl border border-slate-100">
            <div className="flex items-center gap-2">
              {enabled ? (
                <ToggleRight className="w-4 h-4 text-indigo-500" />
              ) : (
                <ToggleLeft className="w-4 h-4 text-slate-400" />
              )}
              <span className="text-sm font-medium text-slate-700">启用压缩</span>
            </div>
            <button
              onClick={() => setEnabled(!enabled)}
              className={`relative w-11 h-6 rounded-full transition-colors ${enabled ? 'bg-indigo-500' : 'bg-slate-300'}`}
            >
              <span className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${enabled ? 'translate-x-5' : ''}`} />
            </button>
          </div>

          {/* Info */}
          <div className="flex items-start gap-2 p-3 bg-blue-50 rounded-xl border border-blue-100">
            <Info className="w-4 h-4 text-blue-500 mt-0.5 flex-shrink-0" />
            <p className="text-xs text-blue-700">
              压缩会将时间窗口内超出的记录合并为一条汇总记录，按供应商+模型分组，原始记录将归档到存储中。
            </p>
          </div>

          {/* per_minute */}
          <div>
            <label className="text-xs font-medium text-slate-500 mb-1.5 block">
              每分钟最多保留记录数
            </label>
            <input
              type="number"
              min={1}
              value={perMinute}
              onChange={(e) => setPerMinute(Math.max(1, parseInt(e.target.value) || 1))}
              disabled={!enabled}
              className="w-full px-3 py-2.5 text-sm border border-slate-200 rounded-xl focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400 outline-none transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            />
          </div>

          {/* per_hour */}
          <div>
            <label className="text-xs font-medium text-slate-500 mb-1.5 block">
              每小时最多保留记录数
            </label>
            <input
              type="number"
              min={1}
              value={perHour}
              onChange={(e) => setPerHour(Math.max(1, parseInt(e.target.value) || 1))}
              disabled={!enabled}
              className="w-full px-3 py-2.5 text-sm border border-slate-200 rounded-xl focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400 outline-none transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 p-4 border-t border-slate-100 bg-slate-50/50">
          <button
            onClick={onClose}
            className="px-4 py-2.5 text-sm font-medium text-slate-600 hover:text-slate-800 transition-colors"
          >
            取消
          </button>
          <button
            onClick={() => upsertMutation.mutate()}
            disabled={upsertMutation.isPending}
            className="px-4 py-2.5 bg-indigo-500 hover:bg-indigo-600 disabled:bg-slate-300 text-white text-sm font-medium rounded-xl transition-all duration-200 disabled:cursor-not-allowed flex items-center gap-1.5"
          >
            {upsertMutation.isPending ? (
              <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            ) : (
              <>
                <Save className="w-3.5 h-3.5" />
                保存
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};

export default CompressionSettingsModal;