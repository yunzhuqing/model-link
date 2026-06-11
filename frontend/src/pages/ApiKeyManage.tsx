import { useState, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import client, { apiKeysApi, groupsApi } from '../api/client';
import type { ApiKeyManageItem } from '../api/client';
import {
  Search,
  Key,
  Users,
  Calendar,
  Infinity,
  Edit2,
  Plus,
  ChevronLeft,
  ChevronRight,
  Loader2,
  X,
  Check,
  Filter,
} from 'lucide-react';

interface GroupOption {
  id: number;
  name: string;
  users: Array<{ id: number; username: string }>;
}

interface EditModalState {
  open: boolean;
  apiKey: ApiKeyManageItem | null;
  newUserId: number | null;
  newGroupId: number | null;
  newRpm: string;
  newTpm: string;
}

interface CreateFormState {
  name: string;
  description: string;
  groupId: number | null;
  userId: number | null;
  rpm: string;
  tpm: string;
}

const PER_PAGE = 20;

export default function ApiKeyManage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const [page, setPage] = useState(1);
  const [groupFilter, setGroupFilter] = useState<number | undefined>(undefined);
  const [searchInput, setSearchInput] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');

  const [editModal, setEditModal] = useState<EditModalState>({
    open: false,
    apiKey: null,
    newUserId: null,
    newGroupId: null,
    newRpm: '',
    newTpm: '',
  });

  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [createForm, setCreateForm] = useState<CreateFormState>({
    name: '',
    description: '',
    groupId: null,
    userId: null,
    rpm: '',
    tpm: '',
  });

  // Debounced search
  const handleSearchChange = useCallback((value: string) => {
    setSearchInput(value);
    setTimeout(() => {
      setDebouncedSearch(value);
      setPage(1);
    }, 300);
  }, []);

  // Fetch manageable groups
  const { data: groups } = useQuery<GroupOption[]>({
    queryKey: ['manageable-groups'],
    queryFn: async () => {
      const grpsRes = await groupsApi.list();
      return grpsRes.data as unknown as GroupOption[];
    },
  });

  // Fetch API keys
  const { data, isLoading, error } = useQuery({
    queryKey: ['api-keys-manage', debouncedSearch, page, groupFilter],
    queryFn: async () => {
      const r = await apiKeysApi.manage({
        page,
        per_page: PER_PAGE,
        search: debouncedSearch || undefined,
        group_id: groupFilter,
      });
      return r.data;
    },
  });

  const totalPages = data ? Math.ceil(data.total / PER_PAGE) : 1;

  // Create mutation
  const createMutation = useMutation({
    mutationFn: (payload: { name: string; description: string; group_id: number; rpm?: number | null; tpm?: number | null }) =>
      apiKeysApi.create(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-keys-manage'] });
      setCreateModalOpen(false);
      setCreateForm({ name: '', description: '', groupId: null, userId: null, rpm: '', tpm: '' });
    },
  });

  // Edit mutation
  const assignMutation = useMutation({
    mutationFn: ({ id, userId, groupId, rpm, tpm }: { id: number; userId?: number | null; groupId?: number | null; rpm?: number | null; tpm?: number | null }) =>
      apiKeysApi.assign(id, { user_id: userId, group_id: groupId, rpm, tpm }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-keys-manage'] });
      closeEditModal();
    },
  });

  // ── Create handlers ──

  const handleCreateGroupChange = (groupId: number) => {
    const newGroup = groups?.find(g => g.id === groupId);
    const usersInGroup = newGroup?.users ?? [];
    setCreateForm(prev => ({
      ...prev,
      groupId,
      userId: usersInGroup.length > 0 ? usersInGroup[0].id : null,
    }));
  };

  const handleCreateSubmit = () => {
    if (!createForm.name.trim() || !createForm.groupId) return;
    const rpmVal = createForm.rpm.trim() ? Number(createForm.rpm.trim()) : undefined;
    const tpmVal = createForm.tpm.trim() ? Number(createForm.tpm.trim()) : undefined;
    createMutation.mutate({
      name: createForm.name.trim(),
      description: createForm.description.trim(),
      group_id: createForm.groupId,
      rpm: rpmVal,
      tpm: tpmVal,
    });
  };

  const createGroupUsers = groups?.find(g => g.id === createForm.groupId)?.users ?? [];

  // ── Edit handlers ──

  const openEditModal = (apiKey: ApiKeyManageItem) => {
    setEditModal({
      open: true,
      apiKey,
      newUserId: apiKey.user_id ?? null,
      newGroupId: apiKey.group_id,
      newRpm: apiKey.rpm != null ? String(apiKey.rpm) : '',
      newTpm: apiKey.tpm != null ? String(apiKey.tpm) : '',
    });
  };

  const closeEditModal = () => {
    setEditModal({ open: false, apiKey: null, newUserId: null, newGroupId: null, newRpm: '', newTpm: '' });
  };

  const selectedGroupUsers = groups?.find(g => g.id === editModal.newGroupId)?.users ?? [];

  const handleGroupChange = (groupId: number) => {
    const newGroup = groups?.find(g => g.id === groupId);
    setEditModal(prev => {
      const usersInGroup = newGroup?.users ?? [];
      const currentUserInGroup = usersInGroup.some(u => u.id === prev.newUserId);
      return {
        ...prev,
        newGroupId: groupId,
        newUserId: currentUserInGroup ? prev.newUserId : (usersInGroup.length > 0 ? usersInGroup[0].id : null),
      };
    });
  };

  const handleSave = () => {
    if (!editModal.apiKey) return;
    const hasUserChange = editModal.newUserId !== editModal.apiKey.user_id;
    const hasGroupChange = editModal.newGroupId !== editModal.apiKey.group_id;
    const rpmVal = editModal.newRpm.trim() ? Number(editModal.newRpm.trim()) : undefined;
    const tpmVal = editModal.newTpm.trim() ? Number(editModal.newTpm.trim()) : undefined;
    const origRpm = editModal.apiKey.rpm;
    const origTpm = editModal.apiKey.tpm;
    const hasRpmChange = rpmVal !== undefined ? rpmVal !== origRpm : origRpm != null;
    const hasTpmChange = tpmVal !== undefined ? tpmVal !== origTpm : origTpm != null;
    if (!hasUserChange && !hasGroupChange && !hasRpmChange && !hasTpmChange) {
      closeEditModal();
      return;
    }
    assignMutation.mutate({
      id: editModal.apiKey.id,
      userId: hasUserChange ? editModal.newUserId : undefined,
      groupId: hasGroupChange ? editModal.newGroupId : undefined,
      rpm: hasRpmChange ? (rpmVal ?? null) : undefined,
      tpm: hasTpmChange ? (tpmVal ?? null) : undefined,
    });
  };

  // ── Helpers ──

  const maskKey = (key: string) => {
    if (key.length <= 12) return key;
    return key.slice(0, 7) + '...' + key.slice(-4);
  };

  const formatBudget = (item: ApiKeyManageItem) => {
    if (item.unlimited_budget) {
      return (
        <span className="inline-flex items-center gap-1 text-xs font-medium text-purple-600 bg-purple-50 px-2 py-0.5 rounded-full">
          <Infinity className="w-3 h-3" />
          无限
        </span>
      );
    }
    const remaining = item.remaining_budget ?? 0;
    return (
      <span className={`text-sm font-mono ${remaining <= 0 ? 'text-red-500' : 'text-slate-700'}`}>
        ${remaining.toFixed(4)}
      </span>
    );
  };

  const statusBadge = (active: boolean) => (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
      active ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-600'
    }`}>
      {active ? '启用' : '禁用'}
    </span>
  );

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">API Key 管理</h1>
          <p className="text-sm text-slate-500 mt-1">管理当前工作区内所有 API Key</p>
        </div>
        <button
          onClick={() => setCreateModalOpen(true)}
          className="inline-flex items-center gap-2 px-4 py-2.5 bg-blue-500 hover:bg-blue-600 text-white text-sm font-medium rounded-xl transition-colors shadow-sm"
        >
          <Plus className="w-4 h-4" />
          创建 API Key
        </button>
      </div>

      {/* Search and filter bar */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => handleSearchChange(e.target.value)}
            placeholder="搜索 API Key 名称或用户名..."
            className="w-full pl-10 pr-4 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-all"
          />
          {searchInput && (
            <button
              onClick={() => { setSearchInput(''); setDebouncedSearch(''); setPage(1); }}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-slate-400 hover:text-slate-600"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
        <div className="relative">
          <Filter className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <select
            value={groupFilter ?? ''}
            onChange={(e) => { setGroupFilter(e.target.value ? Number(e.target.value) : undefined); setPage(1); }}
            className="pl-10 pr-8 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-all appearance-none"
          >
            <option value="">全部分组</option>
            {groups?.map(g => (
              <option key={g.id} value={g.id}>{g.name}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Table */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center py-20 text-slate-500">
            <p className="text-red-500">加载失败，请稍后重试</p>
          </div>
        ) : !data || data.data.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-slate-400">
            <Key className="w-12 h-12 mb-3 text-slate-300" />
            <p className="text-slate-500">暂无 API Key</p>
            <p className="text-sm mt-1">该工作区下没有可管理的 API Key</p>
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-slate-100 bg-slate-50/50">
                    <th className="text-left px-6 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">名称</th>
                    <th className="text-left px-6 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">Key</th>
                    <th className="text-left px-6 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">分组</th>
                    <th className="text-left px-6 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">所属用户</th>
                    <th className="text-left px-6 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">创建时间</th>
                    <th className="text-right px-6 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">剩余额度</th>
                    <th className="text-center px-6 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">状态</th>
                    <th className="text-center px-6 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50">
                  {data.data.map((item) => (
                    <tr key={item.id} className="hover:bg-slate-50/50 transition-colors">
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-2">
                          <Key className="w-4 h-4 text-blue-400 flex-shrink-0" />
                          <span className="text-sm font-medium text-slate-800 truncate max-w-[180px]" title={item.name}>
                            {item.name}
                          </span>
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <code className="text-xs text-slate-500 bg-slate-100 px-2 py-1 rounded font-mono">
                          {maskKey(item.key)}
                        </code>
                      </td>
                      <td className="px-6 py-4">
                        <span className="inline-flex items-center gap-1.5 text-sm text-slate-600">
                          <Users className="w-3.5 h-3.5 text-indigo-400" />
                          {item.group_name || `ID: ${item.group_id}`}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <span className="text-sm text-slate-600">
                          {item.user_name || (item.user_id ? `ID: ${item.user_id}` : '-')}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-1.5 text-sm text-slate-500">
                          <Calendar className="w-3.5 h-3.5 text-slate-400" />
                          {item.created_at ? new Date(item.created_at).toLocaleDateString('zh-CN') : '-'}
                        </div>
                      </td>
                      <td className="px-6 py-4 text-right">
                        {formatBudget(item)}
                      </td>
                      <td className="px-6 py-4 text-center">
                        {statusBadge(item.is_active)}
                      </td>
                      <td className="px-6 py-4 text-center">
                        <button
                          onClick={() => openEditModal(item)}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-blue-600 bg-blue-50 hover:bg-blue-100 rounded-lg transition-colors"
                          title="编辑分配"
                        >
                          <Edit2 className="w-3 h-3" />
                          编辑
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <div className="flex items-center justify-between px-6 py-3.5 border-t border-slate-100 bg-slate-50/30">
              <span className="text-sm text-slate-500">
                共 {data.total} 条记录，第 {data.page}/{totalPages} 页
              </span>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="p-2 rounded-lg text-slate-500 hover:bg-slate-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
                  let pageNum: number;
                  if (totalPages <= 7) {
                    pageNum = i + 1;
                  } else if (page <= 4) {
                    pageNum = i + 1;
                  } else if (page >= totalPages - 3) {
                    pageNum = totalPages - 6 + i;
                  } else {
                    pageNum = page - 3 + i;
                  }
                  return (
                    <button
                      key={pageNum}
                      onClick={() => setPage(pageNum)}
                      className={`w-9 h-9 rounded-lg text-sm font-medium transition-colors ${
                        pageNum === page
                          ? 'bg-blue-500 text-white shadow-sm'
                          : 'text-slate-600 hover:bg-slate-100'
                      }`}
                    >
                      {pageNum}
                    </button>
                  );
                })}
                <button
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className="p-2 rounded-lg text-slate-500 hover:bg-slate-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Edit Modal */}
      {editModal.open && editModal.apiKey && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={closeEditModal} />
          <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
              <h3 className="text-lg font-semibold text-slate-800">编辑 API Key 分配</h3>
              <button onClick={closeEditModal} className="p-1 text-slate-400 hover:text-slate-600 transition-colors">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="px-6 py-4 space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5">API Key</label>
                <div className="flex items-center gap-2 p-2.5 bg-slate-50 rounded-xl">
                  <Key className="w-4 h-4 text-blue-400" />
                  <span className="text-sm font-medium text-slate-700">{editModal.apiKey.name}</span>
                  <code className="text-xs text-slate-400 font-mono ml-auto">{maskKey(editModal.apiKey.key)}</code>
                </div>
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5">所属分组</label>
                <select
                  value={editModal.newGroupId ?? ''}
                  onChange={(e) => handleGroupChange(Number(e.target.value))}
                  className="w-full px-4 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-all"
                >
                  <option value="" disabled>选择分组</option>
                  {groups?.map(g => (
                    <option key={g.id} value={g.id}>{g.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5">所属用户</label>
                <select
                  value={editModal.newUserId ?? ''}
                  onChange={(e) => setEditModal(prev => ({ ...prev, newUserId: e.target.value ? Number(e.target.value) : null }))}
                  className="w-full px-4 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-all"
                >
                  <option value="">未分配</option>
                  {selectedGroupUsers.map(u => (
                    <option key={u.id} value={u.id}>{u.username}</option>
                  ))}
                </select>
                {selectedGroupUsers.length === 0 && editModal.newGroupId && (
                  <p className="text-xs text-amber-600 mt-1">该分组下暂无成员</p>
                )}
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5">RPM 限制</label>
                  <input
                    type="number"
                    value={editModal.newRpm}
                    onChange={(e) => setEditModal(prev => ({ ...prev, newRpm: e.target.value }))}
                    placeholder="不限"
                    min="0"
                    className="w-full px-4 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-all"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5">TPM 限制</label>
                  <input
                    type="number"
                    value={editModal.newTpm}
                    onChange={(e) => setEditModal(prev => ({ ...prev, newTpm: e.target.value }))}
                    placeholder="不限"
                    min="0"
                    className="w-full px-4 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-all"
                  />
                </div>
              </div>
              <div className="p-3 bg-slate-50 rounded-xl text-xs text-slate-500 space-y-1">
                <p>当前分组: <span className="font-medium text-slate-700">{editModal.apiKey.group_name || `ID: ${editModal.apiKey.group_id}`}</span></p>
                <p>当前用户: <span className="font-medium text-slate-700">{editModal.apiKey.user_name || '未分配'}</span></p>
              </div>
              {assignMutation.isError && (
                <div className="p-3 bg-red-50 rounded-xl text-sm text-red-600">
                  {(assignMutation.error as any)?.response?.data?.detail || '操作失败，请稍后重试'}
                </div>
              )}
            </div>
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-slate-100 bg-slate-50/50">
              <button onClick={closeEditModal} className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-800 hover:bg-slate-100 rounded-xl transition-colors">
                取消
              </button>
              <button
                onClick={handleSave}
                disabled={assignMutation.isPending}
                className="inline-flex items-center gap-2 px-5 py-2 bg-blue-500 hover:bg-blue-600 text-white text-sm font-medium rounded-xl transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
              >
                {assignMutation.isPending ? (
                  <><Loader2 className="w-4 h-4 animate-spin" />保存中...</>
                ) : (
                  <><Check className="w-4 h-4" />保存</>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create Modal */}
      {createModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setCreateModalOpen(false)} />
          <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
              <h3 className="text-lg font-semibold text-slate-800">创建 API Key</h3>
              <button onClick={() => setCreateModalOpen(false)} className="p-1 text-slate-400 hover:text-slate-600 transition-colors">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="px-6 py-4 space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5">
                  名称 <span className="text-red-400">*</span>
                </label>
                <input
                  type="text"
                  value={createForm.name}
                  onChange={(e) => setCreateForm(prev => ({ ...prev, name: e.target.value }))}
                  placeholder="输入 API Key 名称"
                  className="w-full px-4 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-all"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5">描述</label>
                <textarea
                  value={createForm.description}
                  onChange={(e) => setCreateForm(prev => ({ ...prev, description: e.target.value }))}
                  placeholder="可选描述信息"
                  rows={2}
                  className="w-full px-4 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-all resize-none"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5">
                  所属分组 <span className="text-red-400">*</span>
                </label>
                <select
                  value={createForm.groupId ?? ''}
                  onChange={(e) => handleCreateGroupChange(Number(e.target.value))}
                  className="w-full px-4 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-all"
                >
                  <option value="" disabled>选择分组</option>
                  {groups?.map(g => (
                    <option key={g.id} value={g.id}>{g.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5">所属用户</label>
                <select
                  value={createForm.userId ?? ''}
                  onChange={(e) => setCreateForm(prev => ({ ...prev, userId: e.target.value ? Number(e.target.value) : null }))}
                  className="w-full px-4 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-all"
                >
                  <option value="">未分配</option>
                  {createGroupUsers.map(u => (
                    <option key={u.id} value={u.id}>{u.username}</option>
                  ))}
                </select>
                {createForm.groupId && createGroupUsers.length === 0 && (
                  <p className="text-xs text-amber-600 mt-1">该分组下暂无成员</p>
                )}
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5">RPM 限制</label>
                  <input
                    type="number"
                    value={createForm.rpm}
                    onChange={(e) => setCreateForm(prev => ({ ...prev, rpm: e.target.value }))}
                    placeholder="不限"
                    min="0"
                    className="w-full px-4 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-all"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5">TPM 限制</label>
                  <input
                    type="number"
                    value={createForm.tpm}
                    onChange={(e) => setCreateForm(prev => ({ ...prev, tpm: e.target.value }))}
                    placeholder="不限"
                    min="0"
                    className="w-full px-4 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-all"
                  />
                </div>
              </div>
              {createMutation.isError && (
                <div className="p-3 bg-red-50 rounded-xl text-sm text-red-600">
                  {(createMutation.error as any)?.response?.data?.detail || '创建失败，请稍后重试'}
                </div>
              )}
            </div>
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-slate-100 bg-slate-50/50">
              <button
                onClick={() => setCreateModalOpen(false)}
                className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-800 hover:bg-slate-100 rounded-xl transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleCreateSubmit}
                disabled={!createForm.name.trim() || !createForm.groupId || createMutation.isPending}
                className="inline-flex items-center gap-2 px-5 py-2 bg-blue-500 hover:bg-blue-600 text-white text-sm font-medium rounded-xl transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
              >
                {createMutation.isPending ? (
                  <><Loader2 className="w-4 h-4 animate-spin" />创建中...</>
                ) : (
                  <><Check className="w-4 h-4" />创建</>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
