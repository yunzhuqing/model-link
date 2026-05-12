import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { groupsApi, permissionsApi } from '../api/client';
import type { Group, GroupCreate } from '../api/client';
import TagSelector from '../components/TagSelector';
import { useWorkspace } from '../contexts/WorkspaceContext';
import { Users, Plus, Edit2, Trash2, X, Key, User, Calendar, ChevronRight, Database, Tag, AlertTriangle } from 'lucide-react';

export default function GroupList() {
  const { t } = useTranslation();
  const { selectedWorkspace } = useWorkspace();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [selectedGroup, setSelectedGroup] = useState<Group | null>(null);
  const [formData, setFormData] = useState<GroupCreate & { tags?: { name: string; value: string }[] }>({ name: '', description: '', tags: [] });
  const [createError, setCreateError] = useState<string | null>(null);
  const [editError, setEditError] = useState<string | null>(null);

  const extractError = (err: unknown): string => {
    if (err && typeof err === 'object' && 'response' in err) {
      const axiosErr = err as { response?: { data?: { detail?: string } } };
      return axiosErr.response?.data?.detail || String(err);
    }
    return String(err);
  };

  const { data: groups, isLoading } = useQuery({
    queryKey: ['groups'],
    queryFn: async () => {
      const res = await groupsApi.list();
      return res.data;
    },
  });

  const { data: myPermissionsData } = useQuery({
    queryKey: ['my-permissions'],
    queryFn: async () => {
      const res = await permissionsApi.myPermissions();
      return res.data;
    },
  });

  const createMutation = useMutation({
    mutationFn: groupsApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['groups'] });
      setIsCreateModalOpen(false);
      setFormData({ name: '', description: '' });
      setCreateError(null);
    },
    onError: (err: unknown) => {
      setCreateError(extractError(err));
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Parameters<typeof groupsApi.update>[1] }) =>
      groupsApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['groups'] });
      setIsEditModalOpen(false);
      setSelectedGroup(null);
      setEditError(null);
    },
    onError: (err: unknown) => {
      setEditError(extractError(err));
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
    createMutation.mutate({
      ...formData,
      workspace_id: selectedWorkspace?.id ?? undefined,
    });
  };

  const handleUpdate = () => {
    if (!selectedGroup || !formData.name.trim()) return;
    updateMutation.mutate({
      id: selectedGroup.id,
      data: {
        name: formData.name,
        description: formData.description,
        tags: formData.tags,
      },
    });
  };

  const handleDelete = (id: number) => {
    if (window.confirm(t('group.deleteConfirm'))) {
      deleteMutation.mutate(id);
    }
  };

  const openEditModal = (group: Group) => {
    setSelectedGroup(group);
    setFormData({
      name: group.name,
      description: group.description || '',
      tags: group.tags || [],
    });
    setIsEditModalOpen(true);
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString();
  };

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="text-slate-500">{t('common.loading')}</div>
      </div>
    );
  }

  const canManageGroups = myPermissionsData?.permissions?.['group.manage'] === true;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">{t('group.title')}</h1>
          <p className="text-slate-500 mt-1">{t('group.subtitle')}</p>
        </div>
        {canManageGroups && (
        <button
          onClick={() => {
            setFormData({ name: '', description: '' });
            setCreateError(null);
            setIsCreateModalOpen(true);
          }}
          className="bg-gradient-to-r from-blue-500 to-indigo-600 text-white px-5 py-2.5 rounded-xl flex items-center hover:from-blue-600 hover:to-indigo-700 transition-all shadow-lg shadow-blue-500/25"
        >
          <Plus className="w-4 h-4 mr-2" /> {t('group.createGroup')}
        </button>
        )}
      </div>

      {/* Groups Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {groups?.map((group) => (
          <div
            key={group.id}
            className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6 hover:shadow-md hover:border-blue-200 transition-all cursor-pointer group"
            onClick={() => navigate(`/groups/${group.id}`)}
          >
            <div className="flex items-start justify-between mb-4">
              <div className="flex items-center space-x-3">
                <div className="w-12 h-12 bg-gradient-to-br from-violet-500 to-purple-600 rounded-xl flex items-center justify-center shadow-lg shadow-violet-500/25">
                  <Users className="w-6 h-6 text-white" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-slate-800 group-hover:text-blue-600 transition-colors">{group.name}</h3>
                </div>
              </div>
              <div className="flex space-x-1" onClick={(e) => e.stopPropagation()}>
                <button
                  onClick={() => openEditModal(group)}
                  className="text-slate-400 hover:text-blue-600 p-1.5 hover:bg-blue-50 rounded-lg transition-colors"
                  title={t('common.edit')}
                >
                  <Edit2 className="w-4 h-4" />
                </button>
                <button
                  onClick={() => handleDelete(group.id)}
                  className="text-slate-400 hover:text-red-600 p-1.5 hover:bg-red-50 rounded-lg transition-colors"
                  title={t('common.delete')}
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>

            <p className="text-slate-500 text-sm mb-4 min-h-[40px]">
              {group.description || t('group.noDescription')}
            </p>

            {/* Stats */}
            <div className="grid grid-cols-3 gap-3 mb-4">
              <div className="bg-slate-50 rounded-xl p-3">
                <div className="flex items-center text-slate-400 mb-1">
                  <User className="w-3 h-3 mr-1" />
                  <span className="text-xs font-medium">{t('group.users')}</span>
                </div>
                <span className="text-xl font-bold text-slate-800">{group.users?.length || 0}</span>
              </div>
              <div className="bg-slate-50 rounded-xl p-3">
                <div className="flex items-center text-slate-400 mb-1">
                  <Key className="w-3 h-3 mr-1" />
                  <span className="text-xs font-medium">{t('group.keys')}</span>
                </div>
                <span className="text-xl font-bold text-slate-800">{group.api_keys?.length || 0}</span>
              </div>
              <div className="bg-slate-50 rounded-xl p-3">
                <div className="flex items-center text-slate-400 mb-1">
                  <Database className="w-3 h-3 mr-1" />
                  <span className="text-xs font-medium">{t('group.providers')}</span>
                </div>
                <span className="text-xl font-bold text-slate-800">{group.providers?.length || 0}</span>
              </div>
            </div>

            {/* Tags */}
            {group.tags && group.tags.length > 0 && (
              <div className="mb-4">
                <div className="flex items-center text-slate-400 mb-1.5">
                  <Tag className="w-3 h-3 mr-1" />
                  <span className="text-xs font-medium">{t('group.tags')}</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {group.tags.map((tag, idx) => (
                    <span key={idx} className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium bg-indigo-50 text-indigo-700 border border-indigo-100">
                      {tag.name}: {tag.value}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Footer */}
            <div className="pt-4 border-t border-slate-100 flex items-center justify-between">
              <div className="flex items-center text-xs text-slate-500">
                <Calendar className="w-3 h-3 mr-2" />
                <span>{formatDate(group.created_at)}</span>
              </div>
              <ChevronRight className="w-5 h-5 text-slate-300 group-hover:text-blue-500 transition-colors" />
            </div>
          </div>
        ))}
        {groups?.length === 0 && (
          <div className="col-span-full bg-white rounded-2xl border border-slate-200 p-12 text-center">
            <Users className="w-16 h-16 mx-auto mb-4 text-slate-300" />
            <p className="text-lg font-medium text-slate-700">{t('group.noGroups')}</p>
            <p className="text-sm text-slate-500 mt-2">{t('group.noGroupsHint')}</p>
          </div>
        )}
      </div>

      {/* Create Modal */}
      {isCreateModalOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">
            <div className="p-6 border-b border-slate-200">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-bold text-slate-800">{t('group.createGroup')}</h2>
                <button
                  onClick={() => { setIsCreateModalOpen(false); setCreateError(null); }}
                  className="text-slate-400 hover:text-slate-600 p-1 hover:bg-slate-100 rounded-lg transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>
            {createError && (
              <div className="mx-6 mt-4 p-3 bg-red-50 border border-red-200 rounded-xl flex items-start gap-2">
                <AlertTriangle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
                <p className="text-sm text-red-700">{createError}</p>
              </div>
            )}
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">{t('group.name')}</label>
                <input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                  placeholder={t('group.namePlaceholder')}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">{t('group.descriptionOptional')}</label>
                <textarea
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all resize-none"
                  rows={3}
                  placeholder={t('group.descriptionPlaceholder')}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">{t('group.tags')}</label>
                <TagSelector
                  value={formData.tags || []}
                  onChange={(tags) => setFormData({ ...formData, tags })}
                />
              </div>
            </div>
            <div className="p-6 border-t border-slate-200 flex justify-end space-x-3">
              <button
                onClick={() => {
                  setIsCreateModalOpen(false);
                  setFormData({ name: '', description: '', tags: [] });
                  setCreateError(null);
                }}
                className="px-5 py-2.5 text-slate-600 bg-slate-100 rounded-xl hover:bg-slate-200 transition-colors"
              >
                {t('common.cancel')}
              </button>
              <button
                onClick={handleCreate}
                disabled={!formData.name.trim() || createMutation.isPending}
                className="px-5 py-2.5 bg-blue-500 text-white rounded-xl hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-sm"
              >
                {createMutation.isPending ? t('group.creating') : t('common.create')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Modal */}
      {isEditModalOpen && selectedGroup && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">
            <div className="p-6 border-b border-slate-200">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-bold text-slate-800">{t('group.editGroup')}</h2>
                <button
                  onClick={() => {
                    setIsEditModalOpen(false);
                    setSelectedGroup(null);
                    setEditError(null);
                  }}
                  className="text-slate-400 hover:text-slate-600 p-1 hover:bg-slate-100 rounded-lg transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>
            {editError && (
              <div className="mx-6 mt-4 p-3 bg-red-50 border border-red-200 rounded-xl flex items-start gap-2">
                <AlertTriangle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
                <p className="text-sm text-red-700">{editError}</p>
              </div>
            )}
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">{t('group.name')}</label>
                <input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">{t('group.description')}</label>
                <textarea
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all resize-none"
                  rows={3}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">{t('group.tags')}</label>
                <TagSelector
                  value={formData.tags || []}
                  onChange={(tags) => setFormData({ ...formData, tags })}
                />
              </div>
            </div>
            <div className="p-6 border-t border-slate-200 flex justify-end space-x-3">
              <button
                onClick={() => {
                  setIsEditModalOpen(false);
                  setSelectedGroup(null);
                  setEditError(null);
                }}
                className="px-5 py-2.5 text-slate-600 bg-slate-100 rounded-xl hover:bg-slate-200 transition-colors"
              >
                {t('common.cancel')}
              </button>
              <button
                onClick={handleUpdate}
                disabled={!formData.name.trim() || updateMutation.isPending}
                className="px-5 py-2.5 bg-blue-500 text-white rounded-xl hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-sm"
              >
                {updateMutation.isPending ? t('group.saving') : t('common.save')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}