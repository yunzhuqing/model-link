import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiKeysApi, groupsApi } from '../api/client';
import type { ApiKey } from '../api/client';
import { Key, Plus, Edit2, Trash2, Copy, RefreshCw, Check, X, Calendar, Hash, Users } from 'lucide-react';

export default function ApiKeyList() {
  const queryClient = useQueryClient();
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [selectedKey, setSelectedKey] = useState<ApiKey | null>(null);
  const [newKeyName, setNewKeyName] = useState('');
  const [newKeyGroupId, setNewKeyGroupId] = useState<number | undefined>();
  const [newKeyExpires, setNewKeyExpires] = useState('');
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  const { data: apiKeys, isLoading } = useQuery({
    queryKey: ['apiKeys'],
    queryFn: async () => {
      const res = await apiKeysApi.list();
      return res.data;
    },
  });

  const { data: groups } = useQuery({
    queryKey: ['groups'],
    queryFn: async () => {
      const res = await groupsApi.list();
      return res.data;
    },
  });

  const createMutation = useMutation({
    mutationFn: apiKeysApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['apiKeys'] });
      setIsCreateModalOpen(false);
      setNewKeyName('');
      setNewKeyGroupId(undefined);
      setNewKeyExpires('');
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Parameters<typeof apiKeysApi.update>[1] }) =>
      apiKeysApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['apiKeys'] });
      setIsEditModalOpen(false);
      setSelectedKey(null);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: apiKeysApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['apiKeys'] });
    },
  });

  const regenerateMutation = useMutation({
    mutationFn: apiKeysApi.regenerate,
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['apiKeys'] });
      setSelectedKey(res.data);
    },
  });

  const handleCopyKey = async (key: string) => {
    await navigator.clipboard.writeText(key);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  const handleCreate = () => {
    if (!newKeyName.trim()) return;
    createMutation.mutate({
      name: newKeyName,
      group_id: newKeyGroupId,
      expires_at: newKeyExpires || undefined,
    });
  };

  const handleToggleActive = (apiKey: ApiKey) => {
    updateMutation.mutate({
      id: apiKey.id,
      data: { is_active: !apiKey.is_active },
    });
  };

  const handleDelete = (id: number) => {
    if (window.confirm('确定要删除此 API Key 吗？此操作不可撤销。')) {
      deleteMutation.mutate(id);
    }
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleString('zh-CN');
  };

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="text-slate-500">Loading...</div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">API Key 管理</h1>
          <p className="text-slate-500 mt-1">管理您的 API 密钥</p>
        </div>
        <button
          onClick={() => setIsCreateModalOpen(true)}
          className="bg-gradient-to-r from-blue-500 to-indigo-600 text-white px-5 py-2.5 rounded-xl flex items-center hover:from-blue-600 hover:to-indigo-700 transition-all shadow-lg shadow-blue-500/25"
        >
          <Plus className="w-4 h-4 mr-2" /> 创建 API Key
        </button>
      </div>

      {/* API Keys Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {apiKeys?.map((apiKey) => (
          <div key={apiKey.id} className="bg-white rounded-2xl shadow-sm border border-slate-200 p-5 hover:shadow-md transition-shadow">
            <div className="flex items-start justify-between mb-4">
              <div className="flex items-center space-x-3">
                <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${
                  apiKey.is_active ? 'bg-emerald-100' : 'bg-slate-100'
                }`}>
                  <Key className={`w-5 h-5 ${apiKey.is_active ? 'text-emerald-600' : 'text-slate-400'}`} />
                </div>
                <div>
                  <h3 className="font-semibold text-slate-800">{apiKey.name}</h3>
                  <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                    apiKey.is_active 
                      ? 'bg-emerald-100 text-emerald-700' 
                      : 'bg-red-100 text-red-700'
                  }`}>
                    {apiKey.is_active ? '启用' : '禁用'}
                  </span>
                </div>
              </div>
              <div className="flex space-x-1">
                <button
                  onClick={() => handleCopyKey(apiKey.key)}
                  className="text-slate-400 hover:text-blue-600 p-1.5 hover:bg-blue-50 rounded-lg transition-colors"
                  title="复制 Key"
                >
                  {copiedKey === apiKey.key ? (
                    <Check className="w-4 h-4 text-emerald-500" />
                  ) : (
                    <Copy className="w-4 h-4" />
                  )}
                </button>
                <button
                  onClick={() => {
                    setSelectedKey(apiKey);
                    setIsEditModalOpen(true);
                  }}
                  className="text-slate-400 hover:text-blue-600 p-1.5 hover:bg-blue-50 rounded-lg transition-colors"
                  title="编辑"
                >
                  <Edit2 className="w-4 h-4" />
                </button>
                <button
                  onClick={() => {
                    if (window.confirm('确定要重新生成此 API Key 吗？旧 Key 将立即失效。')) {
                      regenerateMutation.mutate(apiKey.id);
                    }
                  }}
                  className="text-slate-400 hover:text-amber-600 p-1.5 hover:bg-amber-50 rounded-lg transition-colors"
                  title="重新生成"
                >
                  <RefreshCw className="w-4 h-4" />
                </button>
                <button
                  onClick={() => handleDelete(apiKey.id)}
                  className="text-slate-400 hover:text-red-600 p-1.5 hover:bg-red-50 rounded-lg transition-colors"
                  title="删除"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* Key Preview */}
            <div className="bg-slate-50 rounded-lg p-3 mb-4">
              <code className="text-sm text-slate-600 font-mono">
                {apiKey.key.substring(0, 16)}...
              </code>
            </div>

            {/* Stats */}
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="bg-slate-50 rounded-lg p-3">
                <div className="flex items-center text-slate-400 mb-1">
                  <Hash className="w-3 h-3 mr-1" />
                  <span className="text-xs">请求次数</span>
                </div>
                <span className="font-semibold text-slate-700">{apiKey.request_count.toLocaleString()}</span>
              </div>
              <div className="bg-slate-50 rounded-lg p-3">
                <div className="flex items-center text-slate-400 mb-1">
                  <Users className="w-3 h-3 mr-1" />
                  <span className="text-xs">分组</span>
                </div>
                <span className="font-medium text-slate-700">{apiKey.group_name || groups?.find(g => g.id === apiKey.group_id)?.name || '-'}</span>
              </div>
            </div>

            {/* Dates */}
            <div className="mt-4 pt-4 border-t border-slate-100 space-y-2 text-xs text-slate-500">
              <div className="flex items-center">
                <Calendar className="w-3 h-3 mr-2" />
                <span>创建: {formatDate(apiKey.created_at)}</span>
              </div>
              <div className="flex items-center">
                <Calendar className="w-3 h-3 mr-2" />
                <span>过期: {formatDate(apiKey.expires_at)}</span>
              </div>
            </div>

            {/* Toggle Active */}
            <div className="mt-4 pt-4 border-t border-slate-100">
              <button
                onClick={() => handleToggleActive(apiKey)}
                className={`w-full py-2 rounded-xl text-sm font-medium transition-colors ${
                  apiKey.is_active
                    ? 'bg-red-50 text-red-600 hover:bg-red-100'
                    : 'bg-emerald-50 text-emerald-600 hover:bg-emerald-100'
                }`}
              >
                {apiKey.is_active ? '禁用 Key' : '启用 Key'}
              </button>
            </div>
          </div>
        ))}
        {apiKeys?.length === 0 && (
          <div className="col-span-full bg-white rounded-2xl border border-slate-200 p-12 text-center">
            <Key className="w-16 h-16 mx-auto mb-4 text-slate-300" />
            <p className="text-lg font-medium text-slate-700">暂无 API Key</p>
            <p className="text-sm text-slate-500 mt-2">点击上方按钮创建您的第一个 API Key</p>
          </div>
        )}
      </div>

      {/* Create Modal */}
      {isCreateModalOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">
            <div className="p-6 border-b border-slate-200">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-bold text-slate-800">创建 API Key</h2>
                <button
                  onClick={() => setIsCreateModalOpen(false)}
                  className="text-slate-400 hover:text-slate-600 p-1 hover:bg-slate-100 rounded-lg transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">名称</label>
                <input
                  type="text"
                  value={newKeyName}
                  onChange={(e) => setNewKeyName(e.target.value)}
                  className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                  placeholder="例如：生产环境 Key"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">分组（可选）</label>
                <select
                  value={newKeyGroupId || ''}
                  onChange={(e) => setNewKeyGroupId(e.target.value ? Number(e.target.value) : undefined)}
                  className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                >
                  <option value="">无分组</option>
                  {groups?.map((group) => (
                    <option key={group.id} value={group.id}>
                      {group.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">过期时间（可选）</label>
                <input
                  type="datetime-local"
                  value={newKeyExpires}
                  onChange={(e) => setNewKeyExpires(e.target.value)}
                  className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                />
              </div>
            </div>
            <div className="p-6 border-t border-slate-200 flex justify-end space-x-3">
              <button
                onClick={() => {
                  setIsCreateModalOpen(false);
                  setNewKeyName('');
                  setNewKeyGroupId(undefined);
                  setNewKeyExpires('');
                }}
                className="px-5 py-2.5 text-slate-600 bg-slate-100 rounded-xl hover:bg-slate-200 transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleCreate}
                disabled={!newKeyName.trim() || createMutation.isPending}
                className="px-5 py-2.5 bg-blue-500 text-white rounded-xl hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-sm"
              >
                {createMutation.isPending ? '创建中...' : '创建'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Modal */}
      {isEditModalOpen && selectedKey && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">
            <div className="p-6 border-b border-slate-200">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-bold text-slate-800">编辑 API Key</h2>
                <button
                  onClick={() => {
                    setIsEditModalOpen(false);
                    setSelectedKey(null);
                  }}
                  className="text-slate-400 hover:text-slate-600 p-1 hover:bg-slate-100 rounded-lg transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">名称</label>
                <input
                  type="text"
                  value={selectedKey.name}
                  onChange={(e) => setSelectedKey({ ...selectedKey, name: e.target.value })}
                  className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">过期时间</label>
                <input
                  type="datetime-local"
                  value={selectedKey.expires_at ? selectedKey.expires_at.slice(0, 16) : ''}
                  onChange={(e) => setSelectedKey({ ...selectedKey, expires_at: e.target.value || null })}
                  className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                />
              </div>
            </div>
            <div className="p-6 border-t border-slate-200 flex justify-end space-x-3">
              <button
                onClick={() => {
                  setIsEditModalOpen(false);
                  setSelectedKey(null);
                }}
                className="px-5 py-2.5 text-slate-600 bg-slate-100 rounded-xl hover:bg-slate-200 transition-colors"
              >
                取消
              </button>
              <button
                onClick={() => {
                  updateMutation.mutate({
                    id: selectedKey.id,
                    data: {
                      name: selectedKey.name,
                      expires_at: selectedKey.expires_at || undefined,
                    },
                  });
                }}
                disabled={updateMutation.isPending}
                className="px-5 py-2.5 bg-blue-500 text-white rounded-xl hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-sm"
              >
                {updateMutation.isPending ? '保存中...' : '保存'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}