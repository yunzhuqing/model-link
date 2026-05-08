import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { tagsApi, type Tag } from '../api/client';
import client from '../api/client';
import { Tag as TagIcon, Plus, Edit2, Trash2, X, AlertCircle, Loader2, Check } from 'lucide-react';

export default function TagManager() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [editingTag, setEditingTag] = useState<Tag | null>(null);
  const [form, setForm] = useState({ name: '', value: '', description: '' });
  const [error, setError] = useState('');

  const { data: tagData, isLoading } = useQuery<{ tags: Tag[]; is_root: boolean }>({
    queryKey: ['tags-manager'],
    queryFn: async () => {
      const [tagsRes, permRes] = await Promise.all([
        tagsApi.list(),
        client.get('/api/permissions/groups/0/my-role').catch(() => ({ data: { permissions: {} } })),
      ]);
      // Check is_root via permissions endpoint
      let isRoot = false;
      try {
        const permCheck = await client.get('/api/permissions');
        isRoot = (permCheck.data as any)?.is_root ?? false;
      } catch {
        // fallback: check if any group has root role
      }
      return { tags: tagsRes.data, is_root: isRoot };
    },
  });

  const tags = tagData?.tags ?? [];
  const isRoot = tagData?.is_root ?? false;

  const createMutation = useMutation({
    mutationFn: tagsApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tags-manager'] });
      setIsCreateOpen(false);
      resetForm();
    },
    onError: (err: any) => {
      setError(err.response?.data?.detail || t('tagManager.createFailed'));
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: { name: string; value: string; description?: string } }) =>
      tagsApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tags-manager'] });
      setEditingTag(null);
      resetForm();
    },
    onError: (err: any) => {
      setError(err.response?.data?.detail || t('tagManager.updateFailed'));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: tagsApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tags-manager'] });
    },
  });

  function resetForm() {
    setForm({ name: '', value: '', description: '' });
    setError('');
  }

  function openEdit(tag: Tag) {
    setEditingTag(tag);
    setForm({ name: tag.name, value: tag.value, description: tag.description || '' });
    setError('');
  }

  function handleSave() {
    const name = form.name.trim();
    const value = form.value.trim();
    if (!name || !value) {
      setError(t('tagManager.nameValueRequired'));
      return;
    }
    if (editingTag) {
      updateMutation.mutate({ id: editingTag.id, data: { name, value, description: form.description.trim() } });
    } else {
      createMutation.mutate({ name, value, description: form.description.trim() });
    }
  }

  function handleDelete(id: number) {
    if (window.confirm(t('tagManager.deleteConfirm'))) {
      deleteMutation.mutate(id);
    }
  }

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <Loader2 className="w-6 h-6 text-slate-400 animate-spin" />
        <span className="ml-2 text-slate-500">{t('common.loading')}</span>
      </div>
    );
  }

  if (!isRoot) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">{t('tagManager.pageTitle')}</h1>
          <p className="text-slate-500 mt-1">{t('tagManager.pageSubtitle')}</p>
        </div>
        <div className="bg-amber-50 border border-amber-200 rounded-2xl p-6 flex items-start space-x-3">
          <AlertCircle className="w-5 h-5 text-amber-500 mt-0.5 flex-shrink-0" />
          <div>
            <h4 className="text-sm font-medium text-amber-800">{t('tagManager.rootOnly')}</h4>
            <p className="text-sm text-amber-600 mt-1">{t('tagManager.rootOnlyDesc')}</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">{t('tagManager.pageTitle')}</h1>
          <p className="text-slate-500 mt-1">{t('tagManager.pageSubtitle')}</p>
        </div>
        <button
          onClick={() => setIsCreateOpen(true)}
          className="bg-gradient-to-r from-blue-500 to-indigo-600 text-white px-5 py-2.5 rounded-xl flex items-center hover:from-blue-600 hover:to-indigo-700 transition-all shadow-lg shadow-blue-500/25"
        >
          <Plus className="w-4 h-4 mr-2" /> {t('tagManager.createTag')}
        </button>
      </div>

      {/* Modal: Create / Edit */}
      {(isCreateOpen || editingTag) && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">
            <div className="p-6 border-b border-slate-200">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-bold text-slate-800">
                  {editingTag ? t('tagManager.editTag') : t('tagManager.createTag')}
                </h2>
                <button
                  onClick={() => { setIsCreateOpen(false); setEditingTag(null); resetForm(); }}
                  className="text-slate-400 hover:text-slate-600 p-1 hover:bg-slate-100 rounded-lg transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>
            <div className="p-6 space-y-4">
              {error && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-600">{error}</div>
              )}
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">{t('tagManager.tagName')}</label>
                <input
                  type="text"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                  placeholder={t('tagManager.tagNamePlaceholder')}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">{t('tagManager.tagValue')}</label>
                <input
                  type="text"
                  value={form.value}
                  onChange={(e) => setForm({ ...form, value: e.target.value })}
                  className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                  placeholder={t('tagManager.tagValuePlaceholder')}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">{t('tagManager.descriptionOptional')}</label>
                <textarea
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all resize-none"
                  rows={3}
                  placeholder={t('tagManager.descriptionPlaceholder')}
                />
              </div>
            </div>
            <div className="p-6 border-t border-slate-200 flex justify-end space-x-3">
              <button
                onClick={() => { setIsCreateOpen(false); setEditingTag(null); resetForm(); }}
                className="px-5 py-2.5 text-slate-600 bg-slate-100 rounded-xl hover:bg-slate-200 transition-colors"
              >
                {t('common.cancel')}
              </button>
              <button
                onClick={handleSave}
                disabled={!form.name.trim() || !form.value.trim() || createMutation.isPending || updateMutation.isPending}
                className="px-5 py-2.5 bg-blue-500 text-white rounded-xl hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-sm"
              >
                {(createMutation.isPending || updateMutation.isPending) ? t('tagManager.saving') : t('common.save')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Tags Table */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
        {tags.length === 0 ? (
          <div className="p-12 text-center">
            <TagIcon className="w-12 h-12 text-slate-300 mx-auto mb-3" />
            <h3 className="text-lg font-semibold text-slate-600">{t('tagManager.noTags')}</h3>
            <p className="text-sm text-slate-400 mt-1">{t('tagManager.noTagsHint')}</p>
          </div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50">
                <th className="text-left px-6 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wider">{t('tagManager.tagName')}</th>
                <th className="text-left px-6 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wider">{t('tagManager.tagValue')}</th>
                <th className="text-left px-6 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wider">{t('tagManager.description')}</th>
                <th className="text-right px-6 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wider">{t('tagManager.actions')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {tags.map((tag) => (
                <tr key={tag.id} className="hover:bg-slate-50/50 transition-colors">
                  <td className="px-6 py-3">
                    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-indigo-100 text-indigo-800">
                      {tag.name}
                    </span>
                  </td>
                  <td className="px-6 py-3 text-sm text-slate-700">{tag.value}</td>
                  <td className="px-6 py-3 text-sm text-slate-500">{tag.description || '-'}</td>
                  <td className="px-6 py-3 text-right">
                    <div className="flex justify-end space-x-1">
                      <button
                        onClick={() => openEdit(tag)}
                        className="text-slate-400 hover:text-blue-600 p-1.5 hover:bg-blue-50 rounded-lg transition-colors"
                        title={t('common.edit')}
                      >
                        <Edit2 className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleDelete(tag.id)}
                        className="text-slate-400 hover:text-red-600 p-1.5 hover:bg-red-50 rounded-lg transition-colors"
                        title={t('common.delete')}
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
