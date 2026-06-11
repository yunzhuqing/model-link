import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { usersApi, permissionsApi } from '../api/client';
import type { UserCreateRequest, UserUpdateRequest } from '../api/client';
import { Plus, Edit2, Trash2, X, Search, AlertTriangle, User, Mail, Lock, ChevronLeft, ChevronRight, Shield } from 'lucide-react';

function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

const PER_PAGE = 20;

export default function UserManagement() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const { data: permData } = useQuery({
    queryKey: ['my-permissions'],
    queryFn: async () => {
      const res = await permissionsApi.myPermissions();
      return res.data;
    },
  });
  const canManageUsers = permData?.permissions?.['user.manage'] === true;
  const [searchText, setSearchText] = useState('');
  const debouncedSearch = useDebounce(searchText.trim(), 300);
  const [page, setPage] = useState(1);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState<{ id: number; username: string; email: string | null } | null>(null);
  const [createForm, setCreateForm] = useState<UserCreateRequest>({ username: '', email: '', password: '' });
  const [editForm, setEditForm] = useState<UserUpdateRequest & { password?: string }>({ username: '', email: '', password: '' });
  const [createError, setCreateError] = useState<string | null>(null);
  const [editError, setEditError] = useState<string | null>(null);

  // Reset to page 1 when search changes
  useEffect(() => {
    setPage(1);
  }, [debouncedSearch]);

  const extractError = (err: unknown): string => {
    if (err && typeof err === 'object' && 'response' in err) {
      const axiosErr = err as { response?: { data?: { detail?: string } } };
      return axiosErr.response?.data?.detail || String(err);
    }
    return String(err);
  };

  const { data: userResponse, isLoading } = useQuery({
    queryKey: ['users', page, debouncedSearch],
    queryFn: async () => {
      const res = await usersApi.list({
        page,
        per_page: PER_PAGE,
        search: debouncedSearch || undefined,
      });
      return res.data;
    },
  });

  const users = userResponse?.data ?? [];
  const total = userResponse?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));

  const createMutation = useMutation({
    mutationFn: usersApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
      setIsCreateModalOpen(false);
      setCreateForm({ username: '', email: '', password: '' });
      setCreateError(null);
    },
    onError: (err: unknown) => setCreateError(extractError(err)),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: UserUpdateRequest }) => usersApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
      setIsEditModalOpen(false);
      setSelectedUser(null);
      setEditError(null);
    },
    onError: (err: unknown) => setEditError(extractError(err)),
  });

  const deleteMutation = useMutation({
    mutationFn: usersApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
    },
  });

  const handleCreate = () => {
    if (!createForm.username.trim() || !createForm.password) return;
    createMutation.mutate(createForm);
  };

  const handleUpdate = () => {
    if (!selectedUser) return;
    const data: UserUpdateRequest = {};
    if (editForm.username !== selectedUser.username) data.username = editForm.username;
    if (editForm.email !== selectedUser.email) data.email = editForm.email || undefined;
    if (editForm.password) data.password = editForm.password;
    updateMutation.mutate({ id: selectedUser.id, data });
  };

  const openEdit = (user: { id: number; username: string; email: string | null }) => {
    setSelectedUser(user);
    setEditForm({ username: user.username, email: user.email || '', password: '' });
    setEditError(null);
    setIsEditModalOpen(true);
  };

  const handleDelete = (user: { id: number; username: string }) => {
    if (window.confirm(t('userManagement.confirmDelete', { name: user.username }))) {
      deleteMutation.mutate(user.id);
    }
  };

  if (!permData) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
      </div>
    );
  }

  if (!canManageUsers) {
    return (
      <div className="flex flex-col items-center justify-center py-32 text-center">
        <div className="w-16 h-16 bg-slate-100 rounded-2xl flex items-center justify-center mb-4">
          <Shield className="w-8 h-8 text-slate-400" />
        </div>
        <h2 className="text-lg font-semibold text-slate-700 mb-1">{t('userManagement.noPermission')}</h2>
        <p className="text-sm text-slate-500">{t('userManagement.noPermissionDesc')}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-slate-500 mt-1">
            {t('userManagement.userCount', { count: total })}
          </p>
        </div>
        <button
          onClick={() => {
            setCreateForm({ username: '', email: '', password: '' });
            setCreateError(null);
            setIsCreateModalOpen(true);
          }}
          className="flex items-center gap-2 px-5 py-2.5 bg-blue-500 text-white rounded-xl hover:bg-blue-600 transition-colors shadow-sm"
        >
          <Plus className="w-4 h-4" />
          {t('userManagement.createUser')}
        </button>
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
        <input
          type="text"
          placeholder={t('userManagement.searchPlaceholder')}
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          className="w-full pl-12 pr-4 py-3 bg-white border border-slate-200 rounded-xl text-slate-800 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
        />
      </div>

      {/* User List */}
      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
        </div>
      ) : users.length === 0 ? (
        <div className="text-center py-20">
          <User className="w-12 h-12 text-slate-300 mx-auto mb-4" />
          <p className="text-slate-500">{t('userManagement.noUsers')}</p>
        </div>
      ) : (
        <div className="bg-white rounded-2xl border border-slate-200 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50/50">
                <th className="text-left px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">ID</th>
                <th className="text-left px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">{t('userManagement.username')}</th>
                <th className="text-left px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">{t('userManagement.email')}</th>
                <th className="text-right px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {users.map((user) => (
                <tr key={user.id} className="hover:bg-slate-50/50 transition-colors">
                  <td className="px-6 py-4 text-sm text-slate-500 font-mono">{user.id}</td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-400 to-indigo-500 flex items-center justify-center text-white text-sm font-medium flex-shrink-0">
                        {user.username.charAt(0).toUpperCase()}
                      </div>
                      <span className="text-sm font-medium text-slate-800">{user.username}</span>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2 text-sm text-slate-600">
                      <Mail className="w-3.5 h-3.5 text-slate-400" />
                      {user.email || '-'}
                    </div>
                  </td>
                  <td className="px-6 py-4 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        onClick={() => openEdit(user)}
                        className="p-2 text-slate-400 hover:text-blue-500 hover:bg-blue-50 rounded-lg transition-colors"
                        title={t('common.edit')}
                      >
                        <Edit2 className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleDelete(user)}
                        disabled={deleteMutation.isPending}
                        className="p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors disabled:opacity-50"
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
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between px-2">
          <p className="text-sm text-slate-500">
            {page} / {totalPages}
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="flex items-center gap-1 px-3 py-2 text-sm text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="flex items-center gap-1 px-3 py-2 text-sm text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* Create Modal */}
      {isCreateModalOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">
            <div className="p-6 border-b border-slate-200">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-bold text-slate-800">{t('userManagement.createUser')}</h2>
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
                <label className="block text-sm font-medium text-slate-700 mb-2">{t('userManagement.username')}</label>
                <div className="relative">
                  <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                  <input
                    type="text"
                    value={createForm.username}
                    onChange={(e) => setCreateForm({ ...createForm, username: e.target.value })}
                    className="w-full pl-10 p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">{t('userManagement.email')}</label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                  <input
                    type="email"
                    value={createForm.email}
                    onChange={(e) => setCreateForm({ ...createForm, email: e.target.value })}
                    className="w-full pl-10 p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">{t('userManagement.password')}</label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                  <input
                    type="password"
                    value={createForm.password}
                    onChange={(e) => setCreateForm({ ...createForm, password: e.target.value })}
                    className="w-full pl-10 p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                  />
                </div>
              </div>
            </div>
            <div className="p-6 border-t border-slate-200 flex justify-end space-x-3">
              <button
                onClick={() => { setIsCreateModalOpen(false); setCreateError(null); }}
                className="px-5 py-2.5 text-slate-600 bg-slate-100 rounded-xl hover:bg-slate-200 transition-colors"
              >
                {t('common.cancel')}
              </button>
              <button
                onClick={handleCreate}
                disabled={!createForm.username.trim() || !createForm.password || createMutation.isPending}
                className="px-5 py-2.5 bg-blue-500 text-white rounded-xl hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-sm"
              >
                {createMutation.isPending ? t('userManagement.creating') : t('common.create')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Modal */}
      {isEditModalOpen && selectedUser && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">
            <div className="p-6 border-b border-slate-200">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-bold text-slate-800">{t('userManagement.editUser')}</h2>
                <button
                  onClick={() => { setIsEditModalOpen(false); setSelectedUser(null); setEditError(null); }}
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
                <label className="block text-sm font-medium text-slate-700 mb-2">{t('userManagement.username')}</label>
                <div className="relative">
                  <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                  <input
                    type="text"
                    value={editForm.username}
                    onChange={(e) => setEditForm({ ...editForm, username: e.target.value })}
                    className="w-full pl-10 p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">{t('userManagement.email')}</label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                  <input
                    type="email"
                    value={editForm.email}
                    onChange={(e) => setEditForm({ ...editForm, email: e.target.value })}
                    className="w-full pl-10 p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">{t('userManagement.newPassword')}</label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                  <input
                    type="password"
                    value={editForm.password}
                    onChange={(e) => setEditForm({ ...editForm, password: e.target.value })}
                    placeholder={t('userManagement.newPassword')}
                    className="w-full pl-10 p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                  />
                </div>
              </div>
            </div>
            <div className="p-6 border-t border-slate-200 flex justify-end space-x-3">
              <button
                onClick={() => { setIsEditModalOpen(false); setSelectedUser(null); setEditError(null); }}
                className="px-5 py-2.5 text-slate-600 bg-slate-100 rounded-xl hover:bg-slate-200 transition-colors"
              >
                {t('common.cancel')}
              </button>
              <button
                onClick={handleUpdate}
                disabled={!editForm.username?.trim() || updateMutation.isPending}
                className="px-5 py-2.5 bg-blue-500 text-white rounded-xl hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-sm"
              >
                {updateMutation.isPending ? t('userManagement.saving') : t('common.save')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
