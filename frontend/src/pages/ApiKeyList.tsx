import { useState, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiKeysApi, groupsApi } from '../api/client';
import client from '../api/client';
import type { ApiKey } from '../api/client';
import { Key, Plus, Edit2, Trash2, Copy, RefreshCw, Check, X, Calendar, Hash, Users, User, Eye, EyeOff, Tag, Search } from 'lucide-react';
import TagSelector from '../components/TagSelector';
import { useAuth } from '../contexts/AuthContext';
import { fuzzyMatchTokens } from '../utils/fuzzyMatch';

interface ModelOption {
  name: string;
  alias?: string | null;
  providerName: string;
  sharedFromGroup?: string;
  groupId?: number;
}

/** Fuzzy match model name / alias / provider / sharedFromGroup by query. */
function fuzzyMatchOption(query: string, m: ModelOption): boolean {
  return fuzzyMatchTokens(query, [m.name, m.alias, m.providerName, m.sharedFromGroup]);
}

/* ── ModelTagSelector ─────────────────────────────────────────────────────
 * Module-level so React keeps the same component identity across parent
 * renders — otherwise the search <input> remounts on every keystroke and
 * loses focus. */
interface ModelTagSelectorProps {
  selected: string[];
  onAdd: (name: string) => void;
  onRemove: (name: string) => void;
  searchInput: string;
  onSearchChange: (v: string) => void;
  allModels: ModelOption[];
  providers?: any[];
  groupId?: number;
  disabled?: boolean;
  groupFilter?: number;
}

const ModelTagSelector = ({
  selected,
  onAdd,
  onRemove,
  searchInput,
  onSearchChange,
  allModels,
  providers,
  groupId,
  disabled = false,
  groupFilter,
}: ModelTagSelectorProps) => {
  const [isFocused, setIsFocused] = useState(false);
  const blurTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  let availableModels = allModels.length > 0 ? allModels : (providers ? (() => {
    // Fallback: build from providers only when allModels is empty (standalone mode)
    const seen = new Set<string>();
    const result: ModelOption[] = [];
    for (const p of providers) {
      if (p.models) {
        for (const m of p.models) {
          if (!seen.has(m.name)) {
            seen.add(m.name);
            result.push({ name: m.name, alias: m.alias, providerName: p.name });
          }
        }
      }
    }
    return result.sort((a, b) => a.name.localeCompare(b.name));
  })() : []);

  // In standalone mode, filter by the key's group when groupFilter is provided
  if (groupFilter && !groupId) {
    availableModels = availableModels.filter(
      m => m.groupId === groupFilter || m.sharedFromGroup != null
    );
  }

  // Flatten each model into separate dropdown rows for its name and alias.
  // The row's `identifier` is what gets stored in `selected` (and ultimately
  // in api_key.allowed_models) — the backend's _check_allowed_models compares
  // the request payload's `model` field verbatim against this string, so
  // storing the alias lets callers invoke by alias.
  type Row = { identifier: string; kind: 'name' | 'alias'; option: ModelOption };
  const rows: Row[] = [];
  for (const m of availableModels) {
    rows.push({ identifier: m.name, kind: 'name', option: m });
    if (m.alias) {
      rows.push({ identifier: m.alias, kind: 'alias', option: m });
    }
  }

  const filtered = rows.filter(
    r => !selected.includes(r.identifier) && fuzzyMatchOption(searchInput, r.option)
  );

  const showDropdown = (isFocused || !!searchInput) && filtered.length > 0;

  return (
    <div className={disabled ? 'opacity-50 pointer-events-none' : ''}>
      <label className="block text-sm font-medium text-slate-700 mb-2">
        可用模型限制（留空表示不限制）
      </label>
      {/* Selected tags */}
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {selected.map(id => {
            // `id` may be either a model name or an alias (whichever the user
            // picked). Look up which one it is, so we can label the chip.
            const opt = availableModels.find(m => m.name === id || m.alias === id);
            const isAlias = !!(opt && opt.alias === id);
            const tooltip = opt
              ? `${opt.providerName}${isAlias ? ` · 别名指向 ${opt.name}` : opt.alias ? ` · 别名 ${opt.alias}` : ''}${opt.sharedFromGroup ? ` · 共享自 ${opt.sharedFromGroup}` : ''}`
              : id;
            return (
              <span
                key={id}
                className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium ${
                  isAlias ? 'bg-emerald-50 text-emerald-700' : 'bg-blue-50 text-blue-700'
                }`}
                title={tooltip}
              >
                {isAlias && (
                  <span className="text-emerald-400 font-normal text-[10px]">别名</span>
                )}
                {id}
                <button
                  onClick={() => onRemove(id)}
                  className={isAlias ? 'text-emerald-400 hover:text-emerald-600 ml-0.5' : 'text-blue-400 hover:text-blue-600 ml-0.5'}
                >
                  <X className="w-3 h-3" />
                </button>
              </span>
            );
          })}
        </div>
      )}
      {/* Search input */}
      <div className="relative">
        <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
        <input
          type="text"
          value={searchInput}
          onChange={(e) => onSearchChange(e.target.value)}
          onFocus={() => {
            if (blurTimer.current) {
              clearTimeout(blurTimer.current);
              blurTimer.current = null;
            }
            setIsFocused(true);
          }}
          onBlur={() => {
            // Delay so clicks on dropdown items register before the list collapses.
            blurTimer.current = setTimeout(() => setIsFocused(false), 150);
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && searchInput.trim()) {
              e.preventDefault();
              const q = searchInput.toLowerCase();
              const exactMatch = filtered.find(r => r.identifier.toLowerCase() === q);
              if (exactMatch) {
                onAdd(exactMatch.identifier);
              } else if (filtered.length === 1) {
                // Only one candidate left — pick it (typical narrowing behavior).
                onAdd(filtered[0].identifier);
              } else if (searchInput.trim() && !selected.includes(searchInput.trim())) {
                onAdd(searchInput.trim());
              }
              onSearchChange('');
            }
          }}
          className="w-full pl-9 p-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-800 placeholder-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
          placeholder="搜索模型名称、别名、供应商（支持空格分词，如 gpt 4o）"
        />
      </div>
      {/* Dropdown suggestions */}
      {showDropdown && (
        <div className="mt-1 max-h-64 overflow-y-auto bg-white border border-slate-200 rounded-xl shadow-lg z-10 relative">
          {filtered.map(r => (
            <button
              key={`${r.kind}:${r.identifier}`}
              onMouseDown={(e) => {
                // mouseDown fires before blur — prevents the input's onBlur from
                // collapsing the list before the click is registered.
                e.preventDefault();
                onAdd(r.identifier);
                onSearchChange('');
              }}
              className="w-full text-left px-3 py-2 hover:bg-blue-50 hover:text-blue-700 transition-colors first:rounded-t-xl last:rounded-b-xl"
            >
              <div className="text-sm font-medium text-slate-800 flex items-center gap-2">
                <span>{r.identifier}</span>
                {r.kind === 'alias' ? (
                  <span className="px-1.5 py-0.5 bg-emerald-50 text-emerald-600 rounded text-[10px] font-medium">
                    别名 → {r.option.name}
                  </span>
                ) : (
                  <span className="px-1.5 py-0.5 bg-slate-100 text-slate-500 rounded text-[10px] font-medium">
                    模型名
                  </span>
                )}
              </div>
              <div className="text-xs text-slate-400 flex items-center gap-1.5 mt-0.5">
                <span>{r.option.providerName}</span>
                {r.option.sharedFromGroup && (
                  <span className="px-1 py-0.5 bg-amber-50 text-amber-600 rounded text-[10px] font-medium">
                    共享自 {r.option.sharedFromGroup}
                  </span>
                )}
              </div>
            </button>
          ))}
        </div>
      )}
      {selected.length > 0 && (
        <p className="text-xs text-slate-400 mt-1.5">
          已选择 {selected.length} 个模型 · 共 {availableModels.length} 个可用
        </p>
      )}
      {disabled && (
        <p className="text-xs text-amber-500 mt-1">您没有编辑可用模型的权限</p>
      )}
    </div>
  );
};

/** When groupId is provided the component acts as an embedded panel (GroupDetail).
 *  When omitted it acts as a standalone page showing all API keys. */
const ApiKeyList = ({ groupId, currentRole, permissions }: { groupId?: number; currentRole?: string; permissions?: Record<string, boolean> } = {}) => {
  const { userId } = useAuth();
  const isMember = currentRole === 'member';
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isModelsModalOpen, setIsModelsModalOpen] = useState(false);
  const [selectedKey, setSelectedKey] = useState<ApiKey | null>(null);
  const [modelsKeyId, setModelsKeyId] = useState<number | null>(null);
  const [modelsKeyName, setModelsKeyName] = useState('');
  const [newKeyName, setNewKeyName] = useState('');
  const [newKeyDescription, setNewKeyDescription] = useState('');
  const [newKeyGroupId, setNewKeyGroupId] = useState<number | undefined>(groupId);
  const [newKeyExpires, setNewKeyExpires] = useState('');
  const [newKeyAllowedModels, setNewKeyAllowedModels] = useState<string[]>([]);
  const [newKeyTags, setNewKeyTags] = useState<{ name: string; value: string }[]>([]);
  const [newKeyRpm, setNewKeyRpm] = useState('');
  const [newKeyTpm, setNewKeyTpm] = useState('');
  const [modelSearchInput, setModelSearchInput] = useState('');
  const [editAllowedModels, setEditAllowedModels] = useState<string[]>([]);
  const [editModelSearchInput, setEditModelSearchInput] = useState('');
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [modelsSearchFilter, setModelsSearchFilter] = useState('');
  const [visibleKeys, setVisibleKeys] = useState<Set<number>>(new Set());
  const [createError, setCreateError] = useState<string | null>(null);

  // Edit key state (for embedded mode)
  const [editKeyName, setEditKeyName] = useState('');
  const [editKeyDescription, setEditKeyDescription] = useState('');
  const [editKeyExpires, setEditKeyExpires] = useState('');
  const [editKeyTags, setEditKeyTags] = useState<{ name: string; value: string }[]>([]);
  const [editKeyRpm, setEditKeyRpm] = useState('');
  const [editKeyTpm, setEditKeyTpm] = useState('');

  const apiKeysQueryKey = groupId ? ['api-keys', 'group', String(groupId)] : ['apiKeys'];

  const { data: apiKeys, isLoading } = useQuery({
    queryKey: apiKeysQueryKey,
    queryFn: async () => {
      if (groupId) {
        const res = await client.get(`/api/apikeys/group/${groupId}`);
        return res.data as ApiKey[];
      }
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
    enabled: !groupId,
  });

  const { data: providers } = useQuery({
    queryKey: groupId ? ['providers', 'group', groupId] : ['providers'],
    queryFn: async () => {
      const params = groupId ? { group_id: groupId } : undefined;
      const res = await client.get('/api/providers/', { params });
      return res.data as any[];
    },
  });

  // Fetch shared models from other groups (embedded mode only)
  const { data: sharesData } = useQuery({
    queryKey: ['model-shares', groupId],
    queryFn: async () => {
      const res = await client.get(`/api/groups/${groupId}/model-shares`);
      return res.data as { shares: any[] };
    },
    enabled: !!groupId,
  });

  // Standalone mode: fetch shared models for the create group when group is selected
  const effectiveGroupId = newKeyGroupId || selectedKey?.group?.id;
  const { data: standaloneShares } = useQuery({
    queryKey: ['model-shares', effectiveGroupId],
    queryFn: async () => {
      const res = await client.get(`/api/groups/${effectiveGroupId}/model-shares`);
      return res.data as { shares: any[] };
    },
    enabled: !groupId && !!effectiveGroupId,
  });

  const { data: modelsData, isLoading: isModelsLoading } = useQuery({
    queryKey: ['apiKeyModels', modelsKeyId],
    queryFn: async () => {
      if (!modelsKeyId) return null;
      const res = await apiKeysApi.getModels(modelsKeyId);
      return res.data;
    },
    enabled: !!modelsKeyId,
  });

  // Build available model list from providers + shared models (embedded mode)
  const allModels = useMemo<ModelOption[]>(() => {
    const seen = new Set<string>();
    const result: ModelOption[] = [];

    // Own provider models
    if (providers) {
      for (const p of providers) {
        if (p.models) {
          for (const m of p.models) {
            if (!seen.has(m.name)) {
              seen.add(m.name);
              result.push({ name: m.name, alias: m.alias, providerName: p.name, groupId: p.group_id });
            }
          }
        }
      }
    }

    // Shared models from other groups (embedded mode)
    const allShares = sharesData?.shares || standaloneShares?.shares;
    if (allShares) {
      for (const share of allShares) {
        if (!seen.has(share.model_name)) {
          seen.add(share.model_name);
          result.push({
            name: share.model_name,
            alias: share.model_alias,
            providerName: share.provider_name,
            sharedFromGroup: share.source_group_name,
          });
        }
      }
    }

    return result.sort((a, b) => a.name.localeCompare(b.name));
  }, [providers, sharesData, standaloneShares]);

  const createMutation = useMutation({
    mutationFn: (data: any) => {
      if (groupId) {
        return client.post('/api/apikeys/', { ...data, group_id: groupId });
      }
      return apiKeysApi.create(data);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: apiKeysQueryKey });
      setIsCreateModalOpen(false);
      setNewKeyName('');
      setNewKeyGroupId(groupId);
      setNewKeyExpires('');
      setNewKeyAllowedModels([]);
      setNewKeyTags([]);
      setNewKeyRpm('');
      setNewKeyTpm('');
      setModelSearchInput('');
      setCreateError(null);
    },
    onError: (err: any) => {
      setCreateError(err.response?.data?.detail || '创建 API Key 失败');
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: any }) =>
      client.put(`/api/apikeys/${id}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: apiKeysQueryKey });
      setIsEditModalOpen(false);
      setSelectedKey(null);
      setEditAllowedModels([]);
      setEditModelSearchInput('');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: apiKeysApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: apiKeysQueryKey });
    },
  });

  const regenerateMutation = useMutation({
    mutationFn: apiKeysApi.regenerate,
    onSuccess: (res: { data: ApiKey }) => {
      queryClient.invalidateQueries({ queryKey: apiKeysQueryKey });
      setSelectedKey(res.data);
    },
  });

  const handleCopyKey = async (key: string) => {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(key);
      } else {
        const textArea = document.createElement('textarea');
        textArea.value = key;
        textArea.style.position = 'fixed';
        textArea.style.left = '-9999px';
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
      }
      setCopiedKey(key);
      setTimeout(() => setCopiedKey(null), 2000);
    } catch (err) {
      console.error('Failed to copy to clipboard:', err);
    }
  };

  const handleCreate = () => {
    if (!newKeyName.trim()) return;
    createMutation.mutate({
      name: newKeyName,
      description: newKeyDescription,
      group_id: groupId || newKeyGroupId,
      expires_at: newKeyExpires || undefined,
      allowed_models: newKeyAllowedModels.length > 0 ? newKeyAllowedModels : undefined,
      tags: newKeyTags.length > 0 ? newKeyTags : undefined,
      rpm: newKeyRpm ? Number(newKeyRpm) : null,
      tpm: newKeyTpm ? Number(newKeyTpm) : null,
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

  const handleViewModels = (apiKey: ApiKey) => {
    setModelsKeyId(apiKey.id);
    setModelsKeyName(apiKey.name);
    setModelsSearchFilter('');
    setIsModelsModalOpen(true);
  };

  const handleEdit = (apiKey: ApiKey) => {
    setSelectedKey(apiKey);
    setEditKeyName(apiKey.name);
    setEditKeyDescription(apiKey.description || '');
    setEditKeyExpires(apiKey.expires_at ? apiKey.expires_at.slice(0, 16) : '');
    setEditAllowedModels(apiKey.allowed_models || []);
    setEditKeyTags((apiKey as any).tags || []);
    setEditKeyRpm(apiKey.rpm != null ? String(apiKey.rpm) : '');
    setEditKeyTpm(apiKey.tpm != null ? String(apiKey.tpm) : '');
    setEditModelSearchInput('');
    setIsEditModalOpen(true);
  };

  const toggleKeyVisibility = (keyId: number) => {
    const s = new Set(visibleKeys);
    s.has(keyId) ? s.delete(keyId) : s.add(keyId);
    setVisibleKeys(s);
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleString('zh-CN');
  };

  const formatTokenCount = (count: number): string => {
    if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`;
    if (count >= 1_000) return `${(count / 1_000).toFixed(1)}K`;
    return count.toString();
  };

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="text-slate-500">Loading...</div>
      </div>
    );
  }

  // ── Embedded mode (inside GroupDetail) ──────────────────────────────────────
  if (groupId !== undefined) {
    // Check if member can create keys (permission may be disabled by root)
    // permissions is undefined → no restrictions (loading or standalone)
    const canCreate = permissions ? permissions['apikey.create'] === true : true;
    const canCopyOthers = permissions ? permissions['apikey.copy_others'] === true : !isMember;
    const canEditOwn = permissions ? permissions['apikey.edit_own'] === true : true;
    const canManage = permissions ? permissions['apikey.manage'] === true : !isMember;
    const canEditModels = permissions ? permissions['apikey.edit_models'] === true : !isMember;

    return (
      <>
        {/* Header */}
        <div className="flex justify-between items-center mb-6">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 bg-emerald-100 rounded-lg flex items-center justify-center">
              <Key className="w-5 h-5 text-emerald-600" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-slate-800">API Keys</h2>
              <p className="text-sm text-slate-500">{apiKeys?.length || 0} keys</p>
            </div>
          </div>
          {canCreate && (
            <button
              onClick={() => setIsCreateModalOpen(true)}
              className="bg-emerald-500 text-white px-4 py-2 rounded-xl flex items-center hover:bg-emerald-600 transition-colors shadow-sm"
            >
              <Plus className="w-4 h-4 mr-2" /> New Key
            </button>
          )}
        </div>

        {/* API Key List */}
        <div className="space-y-3">
          {apiKeys?.map((apiKey) => (
            <div key={apiKey.id} className="bg-slate-50 p-4 rounded-xl">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-4 min-w-0 flex-1">
                  <div className={`w-3 h-3 rounded-full flex-shrink-0 ${apiKey.is_active ? 'bg-emerald-500' : 'bg-slate-400'}`} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center space-x-2">
                      <h4
                        className="font-medium text-slate-800 hover:text-blue-600 cursor-pointer transition-colors"
                        onClick={() => navigate(`/apikeys/${apiKey.id}`)}
                        title="查看详情"
                      >
                        {apiKey.name}
                      </h4>
                      {(apiKey as any).user_name && (
                        <span className="text-xs text-slate-400">by {(apiKey as any).user_name}</span>
                      )}
                    </div>
                    {apiKey.description && (
                      <p className="text-sm text-slate-500 mt-0.5 truncate">{apiKey.description}</p>
                    )}
                    <div className="flex items-center space-x-2 mt-1">
                      <code className="text-sm text-slate-600 bg-white px-2 py-0.5 rounded">
                        {visibleKeys.has(apiKey.id) ? apiKey.key : `${apiKey.key.slice(0, 8)}...${apiKey.key.slice(-4)}`}
                      </code>
                      <button onClick={() => toggleKeyVisibility(apiKey.id)} className="text-slate-400 hover:text-slate-600">
                        {visibleKeys.has(apiKey.id) ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </button>
                  {/* Copy: for members, only allow copying own keys unless copy_others is enabled */}
                  {(apiKey.user_id === userId || canCopyOthers) && (
                    <button onClick={() => handleCopyKey(apiKey.key)} className="text-slate-400 hover:text-slate-600">
                      {copiedKey === apiKey.key ? <Check className="w-4 h-4 text-emerald-500" /> : <Copy className="w-4 h-4" />}
                    </button>
                  )}
                </div>
              </div>
            </div>
            <div className="flex items-center space-x-3 text-sm text-slate-500 flex-shrink-0">
              <span className="flex items-center">
                <Hash className="w-3 h-3 mr-1" />
                {apiKey.request_count}
              </span>
              <span className="hidden lg:inline">Last: {formatDate(apiKey.last_used_at)}</span>
              <button
                onClick={() => handleViewModels(apiKey)}
                className="text-slate-400 hover:text-purple-600 p-1.5 hover:bg-purple-50 rounded-lg transition-colors"
                title="查看模型"
              >
                <Eye className="w-4 h-4" />
              </button>
              {/* Edit/Delete: for members, only allow editing/deleting own keys if edit_own is enabled */}
              {(apiKey.user_id === userId ? canEditOwn : canManage) && (
                <>
                  <button
                    onClick={() => handleEdit(apiKey)}
                    className="text-slate-400 hover:text-blue-600 p-1.5 hover:bg-blue-50 rounded-lg transition-colors"
                    title="编辑"
                  >
                    <Edit2 className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => handleDelete(apiKey.id)}
                    className="text-slate-400 hover:text-red-600 p-1.5 hover:bg-red-50 rounded-lg transition-colors"
                    title="删除"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </>
              )}
                </div>
              </div>

              {/* Allowed Models Tags */}
              {apiKey.allowed_models && apiKey.allowed_models.length > 0 && (
                <div className="mt-3 pt-3 border-t border-slate-200">
                  <div className="flex items-center gap-2 flex-wrap">
                    <div className="flex items-center text-slate-400">
                      <Tag className="w-3 h-3 mr-1" />
                      <span className="text-xs">可用模型:</span>
                    </div>
                    {apiKey.allowed_models.slice(0, 5).map(name => (
                      <span key={name} className="inline-block px-2 py-0.5 bg-purple-50 text-purple-600 rounded-md text-xs font-medium">
                        {name}
                      </span>
                    ))}
                    {apiKey.allowed_models.length > 5 && (
                      <span className="inline-block px-2 py-0.5 bg-slate-100 text-slate-500 rounded-md text-xs font-medium">
                        +{apiKey.allowed_models.length - 5}
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}
          {(!apiKeys || apiKeys.length === 0) && (
            <div className="text-center py-8 text-slate-500">
              <Key className="w-12 h-12 mx-auto mb-3 text-slate-300" />
              <p>No API keys yet.</p>
            </div>
          )}
        </div>

        {/* Create Modal */}
        {isCreateModalOpen && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
            <div className="bg-white rounded-2xl shadow-xl w-full max-w-md max-h-[90vh] flex flex-col">
              <div className="p-6 border-b border-slate-200 flex-shrink-0">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-bold text-slate-800">创建 API Key</h2>
                  <button
                    onClick={() => { setIsCreateModalOpen(false); setNewKeyName(''); setNewKeyDescription(''); setNewKeyExpires(''); setNewKeyAllowedModels([]); setModelSearchInput(''); }}
                    className="text-slate-400 hover:text-slate-600 p-1 hover:bg-slate-100 rounded-lg transition-colors"
                  >
                    <X className="w-5 h-5" />
                  </button>
                </div>
              </div>
              <div className="p-6 space-y-4 overflow-y-auto flex-1">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">名称 *</label>
                  <input
                    type="text"
                    value={newKeyName}
                    onChange={(e) => setNewKeyName(e.target.value)}
                    className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                    placeholder="例如：生产环境 Key"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">描述 *</label>
                  <input
                    type="text"
                    value={newKeyDescription}
                    onChange={(e) => setNewKeyDescription(e.target.value)}
                    className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                    placeholder="例如：用于生产环境调用 GPT-4"
                  />
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
                <ModelTagSelector
                  selected={newKeyAllowedModels}
                  onAdd={(name) => setNewKeyAllowedModels(prev => [...prev, name])}
                  onRemove={(name) => setNewKeyAllowedModels(prev => prev.filter(n => n !== name))}
                  searchInput={modelSearchInput}
                  onSearchChange={setModelSearchInput}
                  allModels={allModels}
                  providers={providers}
                  groupId={groupId}
                  disabled={!canEditModels}
                  groupFilter={newKeyGroupId}
                />
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2 mt-4">标签</label>
                  <TagSelector value={newKeyTags} onChange={setNewKeyTags} />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-2">RPM 限制（可选）</label>
                    <input
                      type="number"
                      value={newKeyRpm}
                      onChange={(e) => setNewKeyRpm(e.target.value)}
                      className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                      placeholder="不限制"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-2">TPM 限制（可选）</label>
                    <input
                      type="number"
                      value={newKeyTpm}
                      onChange={(e) => setNewKeyTpm(e.target.value)}
                      className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                      placeholder="不限制"
                    />
                  </div>
                </div>
              </div>
              {createError && (
                <div className="px-6 pb-2">
                  <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-600">
                    {createError}
                  </div>
                </div>
              )}
              <div className="p-6 border-t border-slate-200 flex justify-end space-x-3 flex-shrink-0">
                <button
                  onClick={() => { setIsCreateModalOpen(false); setNewKeyName(''); setNewKeyDescription(''); setNewKeyExpires(''); setNewKeyAllowedModels([]); setNewKeyTags([]); setNewKeyRpm(''); setNewKeyTpm(''); setModelSearchInput(''); setCreateError(null); }}
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
            <div className="bg-white rounded-2xl shadow-xl w-full max-w-md max-h-[90vh] flex flex-col">
              <div className="p-6 border-b border-slate-200 flex-shrink-0">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-bold text-slate-800">编辑 API Key</h2>
                  <button
                    onClick={() => { setIsEditModalOpen(false); setSelectedKey(null); }}
                    className="text-slate-400 hover:text-slate-600 p-1 hover:bg-slate-100 rounded-lg transition-colors"
                  >
                    <X className="w-5 h-5" />
                  </button>
                </div>
              </div>
              <div className="p-6 space-y-4 overflow-y-auto flex-1">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">名称</label>
                  <input
                    type="text"
                    value={editKeyName}
                    onChange={(e) => setEditKeyName(e.target.value)}
                    className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">描述</label>
                  <input
                    type="text"
                    value={editKeyDescription}
                    onChange={(e) => setEditKeyDescription(e.target.value)}
                    className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                    placeholder="例如：用于生产环境调用 GPT-4"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">过期时间</label>
                  <input
                    type="datetime-local"
                    value={editKeyExpires}
                    onChange={(e) => setEditKeyExpires(e.target.value)}
                    className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                  />
                </div>
                <ModelTagSelector
                  selected={editAllowedModels}
                  onAdd={(name) => setEditAllowedModels(prev => [...prev, name])}
                  onRemove={(name) => setEditAllowedModels(prev => prev.filter(n => n !== name))}
                  searchInput={editModelSearchInput}
                  onSearchChange={setEditModelSearchInput}
                  allModels={allModels}
                  providers={providers}
                  groupId={groupId}
                  disabled={!canEditModels}
                  groupFilter={selectedKey?.group?.id}
                />
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2 mt-4">标签</label>
                  <TagSelector value={editKeyTags} onChange={setEditKeyTags} />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-2">RPM 限制（可选）</label>
                    <input
                      type="number"
                      value={editKeyRpm}
                      onChange={(e) => setEditKeyRpm(e.target.value)}
                      className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                      placeholder="不限制"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-2">TPM 限制（可选）</label>
                    <input
                      type="number"
                      value={editKeyTpm}
                      onChange={(e) => setEditKeyTpm(e.target.value)}
                      className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                      placeholder="不限制"
                    />
                  </div>
                </div>
              </div>
              <div className="p-6 border-t border-slate-200 flex justify-end space-x-3 flex-shrink-0">
                <button
                  onClick={() => { setIsEditModalOpen(false); setSelectedKey(null); }}
                  className="px-5 py-2.5 text-slate-600 bg-slate-100 rounded-xl hover:bg-slate-200 transition-colors"
                >
                  取消
                </button>
                <button
                  onClick={() => {
                    const editData: any = {
                      name: editKeyName,
                      description: editKeyDescription || undefined,
                      expires_at: editKeyExpires || undefined,
                      tags: editKeyTags.length > 0 ? editKeyTags : undefined,
                      rpm: editKeyRpm ? Number(editKeyRpm) : null,
                      tpm: editKeyTpm ? Number(editKeyTpm) : null,
                    };
                    if (canEditModels) {
                      editData.allowed_models = editAllowedModels;
                    }
                    updateMutation.mutate({
                      id: selectedKey.id,
                      data: editData,
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

        {/* Models Viewer Modal */}
        {renderModelsModal()}
      </>
    );
  }

  // ── Standalone mode (standalone page) ─────────────────────────────────────

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
                  <h3
                    className="font-semibold text-slate-800 hover:text-blue-600 cursor-pointer transition-colors"
                    onClick={() => navigate(`/apikeys/${apiKey.id}`)}
                    title="查看详情"
                  >
                    {apiKey.name}
                  </h3>
                  {apiKey.description && (
                    <p className="text-sm text-slate-500 mt-0.5">{apiKey.description}</p>
                  )}
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
                  onClick={() => handleViewModels(apiKey)}
                  className="text-slate-400 hover:text-purple-600 p-1.5 hover:bg-purple-50 rounded-lg transition-colors"
                  title="查看模型"
                >
                  <Eye className="w-4 h-4" />
                </button>
                <button
                  onClick={() => handleEdit(apiKey)}
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

            {/* Allowed Models Tags */}
            {apiKey.allowed_models && apiKey.allowed_models.length > 0 && (
              <div className="mb-4">
                <div className="flex items-center text-slate-400 mb-1.5">
                  <Tag className="w-3 h-3 mr-1" />
                  <span className="text-xs">可用模型</span>
                </div>
                <div className="flex flex-wrap gap-1">
                  {apiKey.allowed_models.slice(0, 3).map(name => (
                    <span key={name} className="inline-block px-2 py-0.5 bg-purple-50 text-purple-600 rounded-md text-xs font-medium truncate max-w-[120px]">
                      {name}
                    </span>
                  ))}
                  {apiKey.allowed_models.length > 3 && (
                    <span className="inline-block px-2 py-0.5 bg-slate-100 text-slate-500 rounded-md text-xs font-medium">
                      +{apiKey.allowed_models.length - 3}
                    </span>
                  )}
                </div>
              </div>
            )}

            {/* Stats */}
            <div className="grid grid-cols-3 gap-3 text-sm">
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
                <span className="font-medium text-slate-700">{apiKey.group?.name || (apiKey as any).group_name || groups?.find(g => g.id === apiKey.group_id)?.name || '-'}</span>
              </div>
              <div className="bg-slate-50 rounded-lg p-3">
                <div className="flex items-center text-slate-400 mb-1">
                  <User className="w-3 h-3 mr-1" />
                  <span className="text-xs">所属用户</span>
                </div>
                <span className="font-medium text-slate-700">{apiKey.user_name || '-'}</span>
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
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md max-h-[90vh] flex flex-col">
            <div className="p-6 border-b border-slate-200 flex-shrink-0">
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
            <div className="p-6 space-y-4 overflow-y-auto flex-1">
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
                <label className="block text-sm font-medium text-slate-700 mb-2">描述 *</label>
                <input
                  type="text"
                  value={newKeyDescription}
                  onChange={(e) => setNewKeyDescription(e.target.value)}
                  className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                  placeholder="例如：用于生产环境调用 GPT-4"
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
              <ModelTagSelector
                selected={newKeyAllowedModels}
                onAdd={(name) => setNewKeyAllowedModels(prev => [...prev, name])}
                onRemove={(name) => setNewKeyAllowedModels(prev => prev.filter(n => n !== name))}
                searchInput={modelSearchInput}
                onSearchChange={setModelSearchInput}
                allModels={allModels}
                providers={providers}
                groupId={groupId}
                groupFilter={newKeyGroupId}
              />
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2 mt-4">标签</label>
                <TagSelector value={newKeyTags} onChange={setNewKeyTags} />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">RPM 限制（可选）</label>
                  <input
                    type="number"
                    value={newKeyRpm}
                    onChange={(e) => setNewKeyRpm(e.target.value)}
                    className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                    placeholder="不限制"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">TPM 限制（可选）</label>
                  <input
                    type="number"
                    value={newKeyTpm}
                    onChange={(e) => setNewKeyTpm(e.target.value)}
                    className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                    placeholder="不限制"
                  />
                </div>
              </div>
            </div>
            {createError && (
              <div className="px-6 pb-2">
                <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-600">
                  {createError}
                </div>
              </div>
            )}
            <div className="p-6 border-t border-slate-200 flex justify-end space-x-3 flex-shrink-0">
              <button
                onClick={() => {
                  setIsCreateModalOpen(false);
                  setNewKeyName('');
                  setNewKeyDescription('');
                  setNewKeyGroupId(groupId);
                  setNewKeyExpires('');
                  setNewKeyAllowedModels([]);
                  setNewKeyTags([]);
                  setNewKeyRpm('');
                  setNewKeyTpm('');
                  setModelSearchInput('');
                  setCreateError(null);
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
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md max-h-[90vh] flex flex-col">
            <div className="p-6 border-b border-slate-200 flex-shrink-0">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-bold text-slate-800">编辑 API Key</h2>
                <button
                  onClick={() => { setIsEditModalOpen(false); setSelectedKey(null); }}
                  className="text-slate-400 hover:text-slate-600 p-1 hover:bg-slate-100 rounded-lg transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>
            <div className="p-6 space-y-4 overflow-y-auto flex-1">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">名称</label>
                <input
                  type="text"
                  value={editKeyName}
                  onChange={(e) => setEditKeyName(e.target.value)}
                  className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">描述</label>
                <input
                  type="text"
                  value={editKeyDescription}
                  onChange={(e) => setEditKeyDescription(e.target.value)}
                  className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                  placeholder="例如：用于生产环境调用 GPT-4"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">过期时间</label>
                <input
                  type="datetime-local"
                  value={editKeyExpires}
                  onChange={(e) => setEditKeyExpires(e.target.value)}
                  className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                />
              </div>
              <ModelTagSelector
                selected={editAllowedModels}
                onAdd={(name) => setEditAllowedModels(prev => [...prev, name])}
                onRemove={(name) => setEditAllowedModels(prev => prev.filter(n => n !== name))}
                searchInput={editModelSearchInput}
                onSearchChange={setEditModelSearchInput}
                allModels={allModels}
                providers={providers}
                groupId={groupId}
                groupFilter={selectedKey?.group?.id}
              />
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2 mt-4">标签</label>
                <TagSelector value={editKeyTags} onChange={setEditKeyTags} />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">RPM 限制（可选）</label>
                  <input
                    type="number"
                    value={editKeyRpm}
                    onChange={(e) => setEditKeyRpm(e.target.value)}
                    className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                    placeholder="不限制"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">TPM 限制（可选）</label>
                  <input
                    type="number"
                    value={editKeyTpm}
                    onChange={(e) => setEditKeyTpm(e.target.value)}
                    className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                    placeholder="不限制"
                  />
                </div>
              </div>
            </div>
            <div className="p-6 border-t border-slate-200 flex justify-end space-x-3 flex-shrink-0">
              <button
                onClick={() => { setIsEditModalOpen(false); setSelectedKey(null); }}
                className="px-5 py-2.5 text-slate-600 bg-slate-100 rounded-xl hover:bg-slate-200 transition-colors"
              >
                取消
              </button>
              <button
                onClick={() => {
                  updateMutation.mutate({
                    id: selectedKey.id,
                    data: {
                      name: editKeyName,
                      description: editKeyDescription || undefined,
                      expires_at: editKeyExpires || undefined,
                      allowed_models: editAllowedModels,
                      tags: editKeyTags.length > 0 ? editKeyTags : undefined,
                      rpm: editKeyRpm ? Number(editKeyRpm) : null,
                      tpm: editKeyTpm ? Number(editKeyTpm) : null,
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

      {/* Models Modal */}
      {renderModelsModal()}
    </div>
  );

  // ── Shared Models Modal ─────────────────────────────────────────────────────
  function renderModelsModal() {
    if (!isModelsModalOpen || !modelsKeyId) return null;
    return (
      <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
        <div className="bg-white rounded-2xl shadow-xl w-full max-w-2xl max-h-[85vh] flex flex-col">
          <div className="p-6 border-b border-slate-200 flex-shrink-0">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-bold text-slate-800">可用模型列表</h2>
                <p className="text-sm text-slate-500 mt-0.5">
                  {modelsKeyName}
                  {modelsData?.allowed_models && modelsData.allowed_models.length > 0
                    ? ` · 已限制 ${modelsData.allowed_models.length} 个模型`
                    : ' · 未限制（可访问所有模型）'}
                </p>
              </div>
              <button
                onClick={() => {
                  setIsModelsModalOpen(false);
                  setModelsKeyId(null);
                  setModelsKeyName('');
                  setModelsSearchFilter('');
                }}
                className="text-slate-400 hover:text-slate-600 p-1 hover:bg-slate-100 rounded-lg transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            {/* Search */}
            <div className="relative mt-4">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={modelsSearchFilter}
                onChange={(e) => setModelsSearchFilter(e.target.value)}
                className="w-full pl-9 p-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                placeholder="搜索模型..."
              />
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-6">
            {isModelsLoading ? (
              <div className="flex justify-center items-center h-32">
                <div className="text-slate-500">加载中...</div>
              </div>
            ) : modelsData?.models && modelsData.models.length > 0 ? (
              <div className="space-y-2">
                {/* Header row */}
                <div className="grid grid-cols-12 gap-2 px-3 py-2 text-xs font-medium text-slate-400 uppercase tracking-wider">
                  <div className="col-span-4">模型</div>
                  <div className="col-span-2">供应商</div>
                  <div className="col-span-1 text-right">请求</div>
                  <div className="col-span-2 text-right">输入 Tokens</div>
                  <div className="col-span-2 text-right">输出 Tokens</div>
                  <div className="col-span-1 text-right">推理</div>
                </div>
                {modelsData.models
                  .filter(m => fuzzyMatchTokens(modelsSearchFilter, [m.name, m.alias, m.provider_name]))
                  .map((model) => (
                    <div
                      key={model.name}
                      className="grid grid-cols-12 gap-2 px-3 py-3 bg-slate-50 rounded-xl hover:bg-slate-100 transition-colors items-center"
                    >
                      <div className="col-span-4 min-w-0">
                        <p className="text-sm font-medium text-slate-800 truncate" title={model.name}>
                          {model.name}
                        </p>
                        {model.alias && (
                          <p className="text-xs text-slate-400 truncate" title={model.alias}>
                            别名: {model.alias}
                          </p>
                        )}
                      </div>
                      <div className="col-span-2 min-w-0">
                        <span className="text-xs text-slate-500 truncate block" title={model.provider_name || ''}>
                          {model.provider_name || '-'}
                        </span>
                      </div>
                      <div className="col-span-1 text-right">
                        <span className="text-sm font-semibold text-slate-700">
                          {model.requests.toLocaleString()}
                        </span>
                      </div>
                      <div className="col-span-2 text-right">
                        <span className="text-sm text-slate-600">
                          {formatTokenCount(model.input_tokens)}
                        </span>
                      </div>
                      <div className="col-span-2 text-right">
                        <span className="text-sm text-slate-600">
                          {formatTokenCount(model.output_tokens)}
                        </span>
                      </div>
                      <div className="col-span-1 text-right">
                        <span className="text-sm text-slate-500">
                          {model.reasoning_tokens > 0 ? formatTokenCount(model.reasoning_tokens) : '-'}
                        </span>
                      </div>
                    </div>
                  ))}
              </div>
            ) : (
              <div className="text-center py-12">
                <Eye className="w-12 h-12 mx-auto mb-3 text-slate-300" />
                <p className="text-slate-500">暂无可用模型</p>
                <p className="text-sm text-slate-400 mt-1">请确保分组下有已启用的供应商和模型</p>
              </div>
            )}
          </div>
          {/* Footer summary */}
          {modelsData?.models && modelsData.models.length > 0 && (
            <div className="p-4 border-t border-slate-200 flex-shrink-0">
              <div className="flex justify-between text-xs text-slate-500">
                <span>共 {modelsData.models.length} 个模型</span>
                <span>
                  总请求: {modelsData.models.reduce((s, m) => s + m.requests, 0).toLocaleString()} · 
                  总输入: {formatTokenCount(modelsData.models.reduce((s, m) => s + m.input_tokens, 0))} · 
                  总输出: {formatTokenCount(modelsData.models.reduce((s, m) => s + m.output_tokens, 0))}
                </span>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }
};

export default ApiKeyList;
