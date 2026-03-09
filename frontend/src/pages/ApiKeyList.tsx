import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiKeysApi, groupsApi } from '../api/client';
import type { ApiKey } from '../api/client';

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
      // Show the new key
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
    return <div className="text-center py-10">加载中...</div>;
  }

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold text-gray-900">API Key 管理</h1>
        <button
          onClick={() => setIsCreateModalOpen(true)}
          className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
        >
          创建 API Key
        </button>
      </div>

      {/* API Keys Table */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">名称</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">API Key</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">分组</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">状态</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">请求次数</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">创建时间</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">过期时间</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">操作</th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {apiKeys?.map((apiKey) => (
              <tr key={apiKey.id} className="hover:bg-gray-50">
                <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                  {apiKey.name}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                  <div className="flex items-center gap-2">
                    <code className="bg-gray-100 px-2 py-1 rounded text-xs">
                      {apiKey.key.substring(0, 12)}...
                    </code>
                    <button
                      onClick={() => handleCopyKey(apiKey.key)}
                      className="text-blue-600 hover:text-blue-800 text-xs"
                    >
                      {copiedKey === apiKey.key ? '已复制!' : '复制'}
                    </button>
                  </div>
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                  {apiKey.group_name || '-'}
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  <button
                    onClick={() => handleToggleActive(apiKey)}
                    className={`px-2 py-1 rounded text-xs ${
                      apiKey.is_active
                        ? 'bg-green-100 text-green-800'
                        : 'bg-red-100 text-red-800'
                    }`}
                  >
                    {apiKey.is_active ? '启用' : '禁用'}
                  </button>
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                  {apiKey.request_count.toLocaleString()}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                  {formatDate(apiKey.created_at)}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                  {formatDate(apiKey.expires_at)}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                  <div className="flex gap-2">
                    <button
                      onClick={() => {
                        setSelectedKey(apiKey);
                        setIsEditModalOpen(true);
                      }}
                      className="text-blue-600 hover:text-blue-800"
                    >
                      编辑
                    </button>
                    <button
                      onClick={() => {
                        if (window.confirm('确定要重新生成此 API Key 吗？旧 Key 将立即失效。')) {
                          regenerateMutation.mutate(apiKey.id);
                        }
                      }}
                      className="text-yellow-600 hover:text-yellow-800"
                    >
                      重新生成
                    </button>
                    <button
                      onClick={() => handleDelete(apiKey.id)}
                      className="text-red-600 hover:text-red-800"
                    >
                      删除
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {apiKeys?.length === 0 && (
              <tr>
                <td colSpan={8} className="px-6 py-4 text-center text-gray-500">
                  暂无 API Key，点击上方按钮创建
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Create Modal */}
      {isCreateModalOpen && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-full max-w-md">
            <h2 className="text-xl font-bold mb-4">创建 API Key</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">名称</label>
                <input
                  type="text"
                  value={newKeyName}
                  onChange={(e) => setNewKeyName(e.target.value)}
                  className="w-full px-3 py-2 border rounded-md"
                  placeholder="例如：生产环境 Key"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">分组（可选）</label>
                <select
                  value={newKeyGroupId || ''}
                  onChange={(e) => setNewKeyGroupId(e.target.value ? Number(e.target.value) : undefined)}
                  className="w-full px-3 py-2 border rounded-md"
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
                <label className="block text-sm font-medium text-gray-700 mb-1">过期时间（可选）</label>
                <input
                  type="datetime-local"
                  value={newKeyExpires}
                  onChange={(e) => setNewKeyExpires(e.target.value)}
                  className="w-full px-3 py-2 border rounded-md"
                />
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => {
                  setIsCreateModalOpen(false);
                  setNewKeyName('');
                  setNewKeyGroupId(undefined);
                  setNewKeyExpires('');
                }}
                className="px-4 py-2 text-gray-600 hover:text-gray-800"
              >
                取消
              </button>
              <button
                onClick={handleCreate}
                disabled={!newKeyName.trim() || createMutation.isPending}
                className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
              >
                {createMutation.isPending ? '创建中...' : '创建'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Modal */}
      {isEditModalOpen && selectedKey && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-full max-w-md">
            <h2 className="text-xl font-bold mb-4">编辑 API Key</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">名称</label>
                <input
                  type="text"
                  value={selectedKey.name}
                  onChange={(e) => setSelectedKey({ ...selectedKey, name: e.target.value })}
                  className="w-full px-3 py-2 border rounded-md"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">过期时间</label>
                <input
                  type="datetime-local"
                  value={selectedKey.expires_at ? selectedKey.expires_at.slice(0, 16) : ''}
                  onChange={(e) => setSelectedKey({ ...selectedKey, expires_at: e.target.value || null })}
                  className="w-full px-3 py-2 border rounded-md"
                />
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => {
                  setIsEditModalOpen(false);
                  setSelectedKey(null);
                }}
                className="px-4 py-2 text-gray-600 hover:text-gray-800"
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
                className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
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