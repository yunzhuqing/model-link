/**
 * ShareModelModal — 将模型共享到其他分组的弹窗
 */
import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { X, Share2, Trash2, Users } from 'lucide-react';
import client from '../api/client';
import type { Group } from '../api/client';

interface ModelInfo {
  id: number;
  name: string;
  alias: string | null;
  providerName: string;
}

interface Props {
  model: ModelInfo;
  currentGroupId: number;
  onClose: () => void;
}

export default function ShareModelModal({ model, currentGroupId, onClose }: Props) {
  const { t } = useTranslation();
  const [groups, setGroups] = useState<Group[]>([]);
  const [loading, setLoading] = useState(true);
  const [sharingId, setSharingId] = useState<number | null>(null);
  const [removingId, setRemovingId] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');
  const modelDisplayName = model.alias || model.name;

  useEffect(() => {
    loadGroups();
    loadShareStates();
  }, []);

  async function loadGroups() {
    try {
      const res = await client.get<Group[]>('/api/groups/');
      setGroups((res.data || []).filter((g) => g.id !== currentGroupId));
    } catch {
      setError('Failed to load groups');
    } finally {
      setLoading(false);
    }
  }

  // Check which groups already have this model shared
  const [sharedGroupIds, setSharedGroupIds] = useState<Set<number>>(new Set());

  async function loadShareStates() {
    try {
      const res = await client.get<Group[]>('/api/groups/');
      const allGroups = (res.data || []).filter((g) => g.id !== currentGroupId);
      // Query each group's shares in parallel to check if model is already shared
      const results = await Promise.all(
        allGroups.map(async (g) => {
          try {
            const sr = await client.get(`/api/groups/${g.id}/model-shares`);
            const shares = sr.data?.shares || [];
            return { groupId: g.id, shared: shares.some((s: any) => s.model_id === model.id) };
          } catch {
            return { groupId: g.id, shared: false };
          }
        })
      );
      const ids = new Set<number>();
      for (const r of results) {
        if (r.shared) ids.add(r.groupId);
      }
      setSharedGroupIds(ids);
    } catch {
      // Silently ignore - the share button will show for all groups
    }
  }

  async function handleShare(targetGroupId: number) {
    setSharingId(targetGroupId);
    setError('');
    setSuccessMsg('');
    try {
      await client.post(`/api/groups/${targetGroupId}/model-shares`, {
        model_id: model.id,
      });
      setSharedGroupIds((prev) => new Set(prev).add(targetGroupId));
      setSuccessMsg(t('group.shareModel.shareSuccess'));
    } catch (e: any) {
      const msg = e?.response?.data?.detail || 'Share failed';
      setError(msg);
    } finally {
      setSharingId(null);
    }
  }

  async function handleRemove(targetGroupId: number) {
    setRemovingId(targetGroupId);
    setError('');
    setSuccessMsg('');
    try {
      const res = await client.get(`/api/groups/${targetGroupId}/model-shares`);
      const shares = res.data?.shares || [];
      const share = shares.find((s: any) => s.model_id === model.id);
      if (share) {
        await client.delete(`/api/groups/${targetGroupId}/model-shares/${share.id}`);
      }
      setSharedGroupIds((prev) => {
        const next = new Set(prev);
        next.delete(targetGroupId);
        return next;
      });
      setSuccessMsg(t('group.shareModel.removeSuccess'));
    } catch (e: any) {
      const msg = e?.response?.data?.detail || 'Remove failed';
      setError(msg);
    } finally {
      setRemovingId(null);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="p-6 border-b border-slate-200 flex items-center justify-between shrink-0">
          <div>
            <h2 className="text-lg font-bold text-slate-800">{t('group.shareModel.title')}</h2>
            <p className="text-sm text-slate-500 mt-0.5">
              {modelDisplayName}
              <span className="mx-1.5 text-slate-300">·</span>
              {model.providerName}
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 p-1 hover:bg-slate-100 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 overflow-y-auto flex-1">
          {loading ? (
            <div className="text-center py-8 text-slate-400">{t('common.loading')}</div>
          ) : groups.length === 0 ? (
            <div className="text-center py-8 text-slate-400">
              <Users className="w-10 h-10 mx-auto mb-3 text-slate-200" />
              <p>{t('group.shareModel.noGroups')}</p>
            </div>
          ) : (
            <div className="space-y-2">
              {groups.map((group) => {
                const isShared = sharedGroupIds.has(group.id);
                const isProcessing = sharingId === group.id || removingId === group.id;
                return (
                  <div
                    key={group.id}
                    className="flex items-center justify-between p-3 rounded-xl border border-slate-200 hover:border-indigo-200 hover:bg-slate-50 transition-colors"
                  >
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-slate-800 text-sm truncate">{group.name}</p>
                      {group.description && (
                        <p className="text-xs text-slate-400 truncate mt-0.5">{group.description}</p>
                      )}
                    </div>
                    {isShared ? (
                      <button
                        onClick={() => handleRemove(group.id)}
                        disabled={isProcessing}
                        className="ml-3 flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-red-600 bg-red-50 hover:bg-red-100 rounded-lg transition-colors disabled:opacity-50"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                        {t('group.shareModel.removeShare')}
                      </button>
                    ) : (
                      <button
                        onClick={() => handleShare(group.id)}
                        disabled={isProcessing}
                        className="ml-3 flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-indigo-600 bg-indigo-50 hover:bg-indigo-100 rounded-lg transition-colors disabled:opacity-50"
                      >
                        <Share2 className="w-3.5 h-3.5" />
                        {isProcessing ? t('group.shareModel.sharing') : t('group.shareModel.share')}
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {successMsg && (
            <p className="mt-3 text-sm text-emerald-500 text-center">{successMsg}</p>
          )}
          {error && (
            <p className="mt-3 text-sm text-red-500 text-center">{error}</p>
          )}
        </div>
      </div>
    </div>
  );
}