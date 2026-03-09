import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { groupsApi } from '../api/client';
import type { Group, GroupCreate } from '../api/client';

export default function GroupList() {
  const queryClient = useQueryClient();
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [selectedGroup, setSelectedGroup] = useState<Group | null>(null);
  const [formData, setFormData] = useState<GroupCreate>({ name: '', description: '' });

  const { data: groups, isLoading } = useQuery({
    queryKey: ['groups'],
    queryFn: async () => {
      const res = await groupsApi.list();
      return res.data;
    },
  });

  const createMutation = useMutation({
    mutationFn: groupsApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['groups'] });
      setIsCreateModalOpen(false);
      setFormData({ name: '', description: '' });
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Parameters<typeof groupsApi.update>[1] }) =>
      groupsApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['groups'] });
      setIsEditModalOpen(false);
      setSelectedGroup(null);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: groupsApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['groups'] });
    },
  });

  const handleCreate = () => {
    if (!formData.name.trim()) return;
    createMutation.mutate(formData);
  };

  const handleUpdate = () => {
    if (!selectedGroup || !formData.name.trim()) return;
    updateMutation.mutate({
      id: selectedGroup.id,
      data: {
        name: formData.name,
        description: formData.description,
      },
    });
  };

  const handleDelete = (id: number) => {
    if (window.confirm('确定要删除此分组吗？分组内的 API Key 将解除关联。')) {
      deleteMutation.mutate(id);
    }
  };

  const openEditModal = (group: Group) => {
    setSelectedGroup(group);
    setFormData({
      name: group.name,
      description: group.description || '',
    });
    setIsEditModalOpen(true);
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString('zh-CN');
  };

  if (isLoading) {
    return <div className="text-center py-10">加载中...</div>;
  }

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold text-gray-900">分组管理</h1>
        <button
          onClick={() => {
            setFormData({ name: '', description: '' });
            setIsCreateModalOpen(true);
          }}
          className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
        >
          创建分组
        </button>
      </div>

      {/* Groups Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {groups?.map((group) => (
          <div key={group.id} className="bg-white shadow rounded-lg p-6">
            <div className="flex justify-between items-start mb-4">
              <h3 className="text-lg font-semibold text-gray-900">{group.name}</h3>
              <div className="flex gap-2">
                <button
                  onClick={() => openEditModal(group)}
                  className="text-blue-600 hover:text-blue-800 text-sm"
                >
                  编辑
                </button>
                <button
                  onClick={() => handleDelete(group.id)}
                  className="text-red-600 hover:text-red-800 text-sm"
                >
                  删除
                </button>
              </div>
            </div>
            <p className="text-gray-500 text-sm mb-4">
              {group.description || '暂无描述'}
            </p>
            <div className="flex justify-between text-sm text-gray-400">
              <span>创建于 {formatDate(group.created_at)}</span>
            </div>
            <div className="mt-4 pt-4 border-t flex gap-4 text-sm">
              <span className="text-gray-600">
                <span className="font-medium text-gray-900">{group.user_count || 0}</span> 用户
              </span>
              <span className="text-gray-600">
                <span className="font-medium text-gray-900">{group.api_key_count || 0}</span> API Key
              </span>
            </div>
          </div>
        ))}
        {groups?.length === 0 && (
          <div className="col-span-full bg-white shadow rounded-lg p-10 text-center text-gray-500">
            暂无分组，点击上方按钮创建
          </div>
        )}
      </div>

      {/* Create Modal */}
      {isCreateModalOpen && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-full max-w-md">
            <h2 className="text-xl font-bold mb-4">创建分组</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">名称</label>
                <input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full px-3 py-2 border rounded-md"
                  placeholder="例如：开发团队"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">描述（可选）</label>
                <textarea
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  className="w-full px-3 py-2 border rounded-md"
                  rows={3}
                  placeholder="分组描述"
                />
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => {
                  setIsCreateModalOpen(false);
                  setFormData({ name: '', description: '' });
                }}
                className="px-4 py-2 text-gray-600 hover:text-gray-800"
              >
                取消
              </button>
              <button
                onClick={handleCreate}
                disabled={!formData.name.trim() || createMutation.isPending}
                className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
              >
                {createMutation.isPending ? '创建中...' : '创建'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Modal */}
      {isEditModalOpen && selectedGroup && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-full max-w-md">
            <h2 className="text-xl font-bold mb-4">编辑分组</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">名称</label>
                <input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full px-3 py-2 border rounded-md"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">描述</label>
                <textarea
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  className="w-full px-3 py-2 border rounded-md"
                  rows={3}
                />
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => {
                  setIsEditModalOpen(false);
                  setSelectedGroup(null);
                }}
                className="px-4 py-2 text-gray-600 hover:text-gray-800"
              >
                取消
              </button>
              <button
                onClick={handleUpdate}
                disabled={!formData.name.trim() || updateMutation.isPending}
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