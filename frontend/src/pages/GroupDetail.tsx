import { useState, useRef, useMemo } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import client from '../api/client';
import {
  ArrowLeft, Edit2, Trash2, Key, Database,
  Users, UserPlus, Search, BarChart3, Cpu, List, Gauge, Activity,
} from 'lucide-react';
import ProviderList from './ProviderList';
import ApiKeyList from './ApiKeyList';
import GroupStatistics from './GroupStatistics';
import GroupModels from './GroupModels';
import UsageRecordsTable from '../components/UsageRecordsTable';
import MonitoringConfig from '../components/MonitoringConfig';
import type { MonitoringConfig as MonitoringConfigType } from '../api/client';

interface Group {
  id: number;
  name: string;
  description: string;
  workspace_id?: number;
  monitoring_config?: MonitoringConfigType[] | null;
  created_at: string;
  users?: Member[];
}

interface Member {
  id: number;
  username: string;
  email: string;
  role: 'root' | 'admin' | 'member';
}

export default function GroupDetail() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();

  const validTabs = ['statistics', 'models', 'apikeys', 'members', 'providers', 'usage', 'rateLimits', 'monitoring'] as const;
  type TabKey = typeof validTabs[number];
  const tabParam = searchParams.get('tab');
  const activeTab: TabKey = validTabs.includes(tabParam as TabKey) ? (tabParam as TabKey) : 'statistics';
  const setActiveTab = (tab: TabKey) => {
    if (tab === 'statistics') {
      setSearchParams({}, { replace: true });
    } else {
      setSearchParams({ tab }, { replace: true });
    }
  };
  const [showInviteMember, setShowInviteMember] = useState(false);
  const [inviteSearch, setInviteSearch] = useState('');
  const [searchResults, setSearchResults] = useState<Member[]>([]);
  const [searching, setSearching] = useState(false);
  const [inviteRole, setInviteRole] = useState<'root' | 'admin' | 'member'>('member');
  const [editingMemberRole, setEditingMemberRole] = useState<number | null>(null);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Queries ─────────────────────────────────────────────────────────────────

  // Fetch current user's role and permissions in this group
  const { data: myRoleData } = useQuery({
    queryKey: ['my-role', id],
    queryFn: async () => {
      try {
        const r = await client.get(`/api/permissions/groups/${id}/my-role`);
        return r.data as { role: string; permissions: Record<string, boolean> };
      } catch {
        return null;
      }
    },
    enabled: !!id,
  });

  const currentRole = myRoleData?.role || 'member';
  const myPermissions = myRoleData?.permissions || {};
  const isRoot = currentRole === 'root';
  const isAtLeastAdmin = isRoot || currentRole === 'admin';
  const canInvite = isAtLeastAdmin && myPermissions['member.invite'] !== false;

  const ROLE_RANK: Record<string, number> = { root: 3, admin: 2, member: 1 };

  const getAvailableRoles = (): string[] => {
    if (currentRole === 'root') return ['root', 'admin', 'member'];
    if (currentRole === 'admin') return ['admin', 'member'];
    return ['member'];
  };

  const canModifyMember = (memberRole: string) =>
    ROLE_RANK[memberRole] <= ROLE_RANK[currentRole];

  const { data: group, isLoading: groupLoading } = useQuery({
    queryKey: ['group', id],
    queryFn: async () => {
      const response = await client.get(`/api/groups/${id}`);
      return response.data as Group;
    },
  });

  const { data: apiKeys } = useQuery({
    queryKey: ['api-keys', 'group', id],
    queryFn: async () => {
      const response = await client.get(`/api/apikeys/group/${id}`);
      return response.data as { id: number }[];
    },
  });

  // providers count for tab badge
  const { data: providers } = useQuery({
    queryKey: ['providers', 'group', id],
    queryFn: async () => {
      const response = await client.get('/api/providers/', { params: { group_id: id } });
      return response.data as { id: number }[];
    },
  });

  // ── Mutations ────────────────────────────────────────────────────────────────

  const inviteMemberMutation = useMutation({
    mutationFn: ({ email, role }: { email: string; role: string }) =>
      client.post(`/api/groups/${id}/invite`, { email, role }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['group', id] });
      setShowInviteMember(false);
      setInviteSearch('');
      setSearchResults([]);
      setInviteRole('member');
    },
  });

  const removeMemberMutation = useMutation({
    mutationFn: (userId: number) => client.delete(`/api/groups/${id}/users/${userId}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['group', id] }),
  });

  const updateRoleMutation = useMutation({
    mutationFn: ({ userId, role }: { userId: number; role: string }) =>
      client.put(`/api/groups/${id}/users/${userId}/role`, { role }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['group', id] });
      setEditingMemberRole(null);
    },
  });

  // ── Helpers ──────────────────────────────────────────────────────────────────

  const getRoleBadgeColor = (role: string) => {
    switch (role) {
      case 'root': return 'bg-rose-100 text-rose-700 border-rose-200';
      case 'admin': return 'bg-amber-100 text-amber-700 border-amber-200';
      default: return 'bg-slate-100 text-slate-600 border-slate-200';
    }
  };

  const handleInviteSearch = (value: string) => {
    setInviteSearch(value);
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);

    if (!value.trim()) {
      setSearchResults([]);
      return;
    }

    if (!group?.workspace_id) return;

    searchTimerRef.current = setTimeout(async () => {
      setSearching(true);
      try {
        const res = await client.get(`/api/workspaces/${group.workspace_id}/users`, {
          params: { search: value.trim() },
        });
        const memberIds = (group.users || []).map((m) => m.id);
        setSearchResults((res.data as Member[]).filter((u) => !memberIds.includes(u.id)));
      } catch {
        setSearchResults([]);
      } finally {
        setSearching(false);
      }
    }, 300);
  };

  const selectUser = (user: Member) => {
    setInviteSearch(user.email);
    setSearchResults([]);
  };

  const sortedUsers = useMemo(() => {
    return [...(group?.users || [])].sort((a, b) => ROLE_RANK[b.role] - ROLE_RANK[a.role]);
  }, [group?.users]);

  // ── Loading / Not Found ──────────────────────────────────────────────────────

  if (groupLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="text-slate-500">{t('common.loading')}</div>
      </div>
    );
  }

  if (!group) {
    return (
      <div className="text-center py-12">
        <Users className="w-16 h-16 mx-auto mb-4 text-slate-300" />
        <p className="text-lg font-medium text-slate-700">{t('group.groupNotFound')}</p>
        <button onClick={() => navigate('/groups')} className="mt-4 text-blue-600 hover:underline">
          {t('group.backToGroups')}
        </button>
      </div>
    );
  }

  // ── Render ───────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center space-x-4">
        <button onClick={() => navigate('/groups')} className="p-2 hover:bg-slate-100 rounded-lg transition-colors">
          <ArrowLeft className="w-5 h-5 text-slate-600" />
        </button>
        <div>
          <h1 className="text-2xl font-bold text-slate-800">{group.name}</h1>
          <p className="text-slate-500">{group.description || t('group.noDescription')}</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-slate-200">
        <nav className="flex space-x-8">
          {(isRoot
            ? [
                { key: 'statistics', label: t('group.tabStatistics'), icon: BarChart3, color: 'amber' },
                { key: 'models', label: t('group.tabModels'), icon: Cpu, color: 'indigo' },
                { key: 'apikeys', label: t('group.tabApiKeys'), icon: Key, color: 'emerald', count: apiKeys?.length || 0 },
                { key: 'members', label: t('group.tabMembers'), icon: Users, color: 'violet', count: group?.users?.length || 0 },
                { key: 'providers', label: t('group.tabProviders'), icon: Database, color: 'blue', count: providers?.length || 0 },
                { key: 'usage', label: t('group.tabUsage'), icon: List, color: 'rose' },
                { key: 'rateLimits', label: t('group.tabRateLimits'), icon: Gauge, color: 'teal' },
                { key: 'monitoring', label: t('group.tabMonitoring'), icon: Activity, color: 'cyan' },
              ]
            : [
                { key: 'statistics', label: t('group.tabStatistics'), icon: BarChart3, color: 'amber' },
                { key: 'models', label: t('group.tabModels'), icon: Cpu, color: 'indigo' },
                { key: 'apikeys', label: t('group.tabApiKeys'), icon: Key, color: 'emerald', count: apiKeys?.length || 0 },
                { key: 'members', label: t('group.tabMembers'), icon: Users, color: 'violet', count: group?.users?.length || 0 },
                { key: 'providers', label: t('group.tabProviders'), icon: Database, color: 'blue', count: providers?.length || 0 },
                { key: 'usage', label: t('group.tabUsage'), icon: List, color: 'rose' },
                { key: 'rateLimits', label: t('group.tabRateLimits'), icon: Gauge, color: 'teal' },
                { key: 'monitoring', label: t('group.tabMonitoring'), icon: Activity, color: 'cyan' },
              ]
          ).map(({ key, label, icon: Icon, color, count }) => {
            const active = activeTab === key;
            return (
              <button
                key={key}
                onClick={() => setActiveTab(key as typeof activeTab)}
                className={`py-4 px-1 border-b-2 font-medium text-sm flex items-center space-x-2 transition-colors ${
                  active
                    ? `border-${color}-500 text-${color}-600`
                    : 'border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300'
                }`}
              >
                <Icon className="w-4 h-4" />
                <span>{label}</span>
                {count != null && (
                  <span className={`px-2 py-0.5 rounded-full text-xs ${active ? `bg-${color}-100 text-${color}-700` : 'bg-slate-100 text-slate-600'}`}>
                    {count}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </div>

      {/* ── Members Tab ─────────────────────────────────────────────────────── */}
      {activeTab === 'members' && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
          <div className="flex justify-between items-center mb-6">
            <div className="flex items-center space-x-3">
              <div className="w-10 h-10 bg-violet-100 rounded-lg flex items-center justify-center">
                <Users className="w-5 h-5 text-violet-600" />
              </div>
              <div>
                <h2 className="text-lg font-bold text-slate-800">{t('group.tabMembers')}</h2>
                <p className="text-sm text-slate-500">{t('group.memberCount', { count: group?.users?.length || 0 })}</p>
              </div>
            </div>
            {canInvite && (
              <button
                onClick={() => setShowInviteMember(true)}
                className="bg-violet-500 text-white px-4 py-2 rounded-xl flex items-center hover:bg-violet-600 transition-colors shadow-sm"
              >
                <UserPlus className="w-4 h-4 mr-2" /> {t('group.inviteMember')}
              </button>
            )}
          </div>

          {showInviteMember && (
            <div className="bg-slate-50 p-4 rounded-xl mb-4">
              <div className="flex gap-4">
                <div className="flex-1 relative">
                  <label className="block text-sm font-medium text-slate-700 mb-2">{t('group.searchMember')}</label>
                  <div className="relative">
                    <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                    <input
                      type="text"
                      placeholder={t('group.searchMemberPlaceholder')}
                      className="w-full pl-10 p-3 bg-white border border-slate-200 rounded-xl text-sm"
                      value={inviteSearch}
                      onChange={(e) => handleInviteSearch(e.target.value)}
                      autoFocus
                    />
                  </div>
                  {/* Search results dropdown */}
                  {(searchResults.length > 0 || searching) && (
                    <div className="absolute z-10 w-full mt-1 bg-white border border-slate-200 rounded-xl shadow-lg max-h-48 overflow-y-auto">
                      {searching ? (
                        <div className="p-3 text-sm text-slate-400">{t('common.searching')}</div>
                      ) : (
                        searchResults.map((user) => (
                          <button
                            key={user.id}
                            type="button"
                            className="w-full px-4 py-3 text-left hover:bg-slate-50 flex items-center space-x-3 border-b border-slate-100 last:border-b-0"
                            onClick={() => selectUser(user)}
                          >
                            <div className="w-8 h-8 bg-gradient-to-br from-violet-500 to-purple-600 rounded-full flex items-center justify-center flex-shrink-0">
                              <span className="text-white font-semibold text-xs">
                                {(user.username || user.email).charAt(0).toUpperCase()}
                              </span>
                            </div>
                            <div className="min-w-0">
                              <div className="text-sm font-medium text-slate-700 truncate">{user.username}</div>
                              <div className="text-xs text-slate-400 truncate">{user.email}</div>
                            </div>
                          </button>
                        ))
                      )}
                    </div>
                  )}
                </div>
              </div>
              <div className="mt-4">
                <label className="block text-sm font-medium text-slate-700 mb-2">{t('group.role')}</label>
                <select
                  className="w-full p-3 bg-white border border-slate-200 rounded-xl text-sm mb-4"
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value as typeof inviteRole)}
                >
                  {getAvailableRoles().map((r) => (
                    <option key={r} value={r}>{t(`group.role${r.charAt(0).toUpperCase() + r.slice(1)}`)}</option>
                  ))}
                </select>
              </div>
              <div className="flex space-x-3">
                <button
                  onClick={() => inviteMemberMutation.mutate({ email: inviteSearch, role: inviteRole })}
                  disabled={!inviteSearch || inviteMemberMutation.isPending}
                  className="bg-violet-500 text-white px-4 py-2 rounded-xl text-sm hover:bg-violet-600 disabled:bg-slate-300"
                >
                  {inviteMemberMutation.isPending ? t('group.inviting') : t('group.sendInvite')}
                </button>
                <button
                  onClick={() => { setShowInviteMember(false); setInviteSearch(''); setSearchResults([]); setInviteRole('member'); }}
                  className="bg-slate-200 text-slate-600 px-4 py-2 rounded-xl text-sm hover:bg-slate-300"
                >
                  {t('common.cancel')}
                </button>
              </div>
              {inviteMemberMutation.isError && (
                <p className="text-red-500 text-sm mt-2">{t('group.inviteFailed')}</p>
              )}
            </div>
          )}

          <div className="space-y-3">
            {sortedUsers.map((member) => (
              <div key={member.id} className="bg-slate-50 p-4 rounded-xl flex items-center justify-between">
                <div className="flex items-center space-x-4">
                  <div className="w-10 h-10 bg-gradient-to-br from-violet-500 to-purple-600 rounded-full flex items-center justify-center">
                    <span className="text-white font-semibold text-sm">
                      {(member.username || member.email).charAt(0).toUpperCase()}
                    </span>
                  </div>
                  <div>
                    <div className="flex items-center space-x-2">
                      <h4 className="font-medium text-slate-800">{member.username || t('common.noData')}</h4>
                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium border ${getRoleBadgeColor(member.role)}`}>
                        {member.role}
                      </span>
                    </div>
                    <p className="text-sm text-slate-500">{member.email}</p>
                  </div>
                </div>
                <div className="flex items-center space-x-2">
                  {isAtLeastAdmin && canModifyMember(member.role) && (
                    <>
                      {editingMemberRole === member.id ? (
                        <select
                          className="p-2 bg-white border border-slate-200 rounded-lg text-sm"
                          value={member.role}
                          onChange={(e) => updateRoleMutation.mutate({ userId: member.id, role: e.target.value })}
                          onBlur={() => setEditingMemberRole(null)}
                        >
                          {getAvailableRoles().map((r) => (
                            <option key={r} value={r}>{t(`group.role${r.charAt(0).toUpperCase() + r.slice(1)}`)}</option>
                          ))}
                        </select>
                      ) : (
                        <button
                          onClick={() => setEditingMemberRole(member.id)}
                          className="text-slate-400 hover:text-blue-600 p-2 hover:bg-blue-50 rounded-lg transition-colors"
                          title={t('group.changeRole')}
                        >
                          <Edit2 className="w-4 h-4" />
                        </button>
                      )}
                      <button
                        onClick={() => { if (confirm(t('group.removeMemberConfirm', { name: member.username || member.email }))) removeMemberMutation.mutate(member.id); }}
                        className="text-slate-400 hover:text-red-600 p-2 hover:bg-red-50 rounded-lg transition-colors"
                        title={t('group.removeMember')}
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </>
                  )}
                </div>
              </div>
            ))}
            {(!group?.users || group.users.length === 0) && !showInviteMember && (
              <div className="text-center py-8 text-slate-500">
                <Users className="w-12 h-12 mx-auto mb-3 text-slate-300" />
                <p>{t('group.noMembers')}</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── API Keys Tab ─────────────────────────────────────────────────────── */}
      {activeTab === 'apikeys' && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
          <ApiKeyList groupId={parseInt(id!)} currentRole={currentRole} permissions={myPermissions} />
        </div>
      )}

      {/* ── Providers Tab ────────────────────────────────────────────────────── */}
      {activeTab === 'providers' && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
          <div className="flex items-center space-x-3 mb-6">
            <div className="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center">
              <Database className="w-5 h-5 text-blue-600" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-slate-800">{t('group.tabProviders')}</h2>
              <p className="text-sm text-slate-500">{t('group.manageProviders')}</p>
            </div>
          </div>
          {/* ProviderList handles all provider + model CRUD internally */}
          <ProviderList groupId={parseInt(id!)} currentRole={currentRole} permissions={myPermissions} />
        </div>
      )}

      {/* ── Statistics Tab ───────────────────────────────────────────────────── */}
      {activeTab === 'statistics' && (
        <GroupStatistics groupId={parseInt(id!)} />
      )}

      {/* ── Models Tab ───────────────────────────────────────────────────────── */}
      {activeTab === 'models' && (
        <GroupModels groupId={parseInt(id!)} currentRole={currentRole} myPermissions={myPermissions} />
      )}

      {/* ── Usage Records Tab ────────────────────────────────────────────────── */}
      {activeTab === 'usage' && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
          <div className="flex items-center space-x-3 mb-6">
            <div className="w-10 h-10 bg-rose-100 rounded-lg flex items-center justify-center">
              <List className="w-5 h-5 text-rose-600" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-slate-800">{t('group.tabUsage')}</h2>
              <p className="text-sm text-slate-500">{t('group.usageDesc')}</p>
            </div>
          </div>
          <UsageRecordsTable groupId={parseInt(id!)} />
        </div>
      )}

      {/* ── Rate Limits Tab ──────────────────────────────────────────────────── */}
      {activeTab === 'rateLimits' && (
        <GroupRateLimits groupId={parseInt(id!)} />
      )}

      {/* ── Monitoring Tab ───────────────────────────────────────────────────── */}
      {activeTab === 'monitoring' && (
        <MonitoringConfig
          groupId={parseInt(id!)}
          monitoringConfigs={group?.monitoring_config}
        />
      )}
    </div>
  );
}

function GroupRateLimits({ groupId }: { groupId: number }) {
  const { t } = useTranslation();

  interface RateLimitModel {
    model_id: number; model_name: string; alias: string | null;
    provider_id: number; provider_name: string | null; group_id: number;
    rpm_limit: number | null; tpm_limit: number | null;
    rpm_used: number; tpm_used: number; rpm_pct: number; tpm_pct: number;
  }

  const { data, isLoading } = useQuery({
    queryKey: ['rate-limits'],
    queryFn: async () => {
      const r = await client.get('/api/providers/rate-limits');
      return r.data.models as RateLimitModel[];
    },
    refetchInterval: 10000,
  });

  if (isLoading) return <div className="text-center py-8 text-slate-400">{t('common.loading')}</div>;

  const models = (data || []).filter(m => m.group_id === groupId);

  if (models.length === 0) {
    return (
      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
        <div className="flex items-center space-x-3 mb-6">
          <div className="w-10 h-10 bg-teal-100 rounded-lg flex items-center justify-center">
            <Gauge className="w-5 h-5 text-teal-600" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-slate-800">{t('group.tabRateLimits')}</h2>
            <p className="text-sm text-slate-500">{t('group.rateLimitsDesc')}</p>
          </div>
        </div>
        <div className="text-center py-8 text-slate-400">{t('rateLimits.noActiveLimits')}</div>
      </div>
    );
  }

  const fmtNum = (n: number) => {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
    if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
    return n.toLocaleString();
  };

  const pctColor = (pct: number) => {
    if (pct >= 90) return 'text-red-600';
    if (pct >= 75) return 'text-amber-600';
    if (pct >= 50) return 'text-yellow-600';
    return 'text-emerald-600';
  };

  const barColor = (pct: number) => {
    if (pct >= 90) return 'bg-red-500';
    if (pct >= 75) return 'bg-amber-500';
    if (pct >= 50) return 'bg-yellow-500';
    return 'bg-emerald-500';
  };

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
      <div className="flex items-center space-x-3 mb-6">
        <div className="w-10 h-10 bg-teal-100 rounded-lg flex items-center justify-center">
          <Gauge className="w-5 h-5 text-teal-600" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-slate-800">{t('group.tabRateLimits')}</h2>
          <p className="text-sm text-slate-500">{t('group.rateLimitsDesc')}</p>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr className="text-left text-xs text-slate-500 uppercase tracking-wider">
              <th className="px-4 py-3">{t('rateLimits.modelName')}</th>
              <th className="px-4 py-3">Provider</th>
              <th className="px-4 py-3 text-right">RPM</th>
              <th className="px-4 py-3 text-right">TPM</th>
              <th className="px-4 py-3 text-center" style={{ minWidth: 200 }}>RPM</th>
              <th className="px-4 py-3 text-center" style={{ minWidth: 200 }}>TPM</th>
            </tr>
          </thead>
          <tbody>
            {models.map(m => (
              <tr key={m.model_id} className="border-t border-slate-100 hover:bg-slate-50">
                <td className="px-4 py-3 font-medium">{m.alias || m.model_name}</td>
                <td className="px-4 py-3 text-slate-500">{m.provider_name}</td>
                <td className="px-4 py-3 text-right font-mono">
                  <span className={pctColor(m.rpm_pct)}>{m.rpm_limit ? `${m.rpm_used}/${m.rpm_limit}` : '∞'}</span>
                </td>
                <td className="px-4 py-3 text-right font-mono">
                  <span className={pctColor(m.tpm_pct)}>{m.tpm_limit ? `${fmtNum(m.tpm_used)}/${fmtNum(m.tpm_limit)}` : '∞'}</span>
                </td>
                <td className="px-4 py-3">
                  {m.rpm_limit ? (
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
                        <div className={`${barColor(m.rpm_pct)} h-full rounded-full transition-all`} style={{ width: Math.min(m.rpm_pct, 100) + '%' }} />
                      </div>
                      <span className={`text-xs font-mono ${pctColor(m.rpm_pct)}`}>{m.rpm_pct}%</span>
                    </div>
                  ) : <span className="text-xs text-slate-400">{t('rateLimits.unlimited')}</span>}
                </td>
                <td className="px-4 py-3">
                  {m.tpm_limit ? (
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
                        <div className={`${barColor(m.tpm_pct)} h-full rounded-full transition-all`} style={{ width: Math.min(m.tpm_pct, 100) + '%' }} />
                      </div>
                      <span className={`text-xs font-mono ${pctColor(m.tpm_pct)}`}>{m.tpm_pct}%</span>
                    </div>
                  ) : <span className="text-xs text-slate-400">{t('rateLimits.unlimited')}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}