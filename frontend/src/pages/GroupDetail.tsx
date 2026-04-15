import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import client from '../api/client';
import {
  ArrowLeft, Edit2, Trash2, Key, Database,
  Users, UserPlus, Mail
} from 'lucide-react';
import ProviderList from './ProviderList';
import ApiKeyList from './ApiKeyList';

interface Group {
  id: number;
  name: string;
  description: string;
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
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [activeTab, setActiveTab] = useState<'members' | 'apikeys' | 'providers'>('members');
  const [showInviteMember, setShowInviteMember] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState<'root' | 'admin' | 'member'>('member');
  const [editingMemberRole, setEditingMemberRole] = useState<number | null>(null);

  // ── Queries ─────────────────────────────────────────────────────────────────

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
      setInviteEmail('');
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

  // ── Loading / Not Found ──────────────────────────────────────────────────────

  if (groupLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="text-slate-500">Loading...</div>
      </div>
    );
  }

  if (!group) {
    return (
      <div className="text-center py-12">
        <Users className="w-16 h-16 mx-auto mb-4 text-slate-300" />
        <p className="text-lg font-medium text-slate-700">Group not found</p>
        <button onClick={() => navigate('/groups')} className="mt-4 text-blue-600 hover:underline">
          Back to Groups
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
          <p className="text-slate-500">{group.description || 'No description'}</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-slate-200">
        <nav className="flex space-x-8">
          {[
            { key: 'members', label: 'Members', icon: Users, color: 'violet', count: group?.users?.length || 0 },
            { key: 'apikeys', label: 'API Keys', icon: Key, color: 'emerald', count: apiKeys?.length || 0 },
            { key: 'providers', label: 'Providers', icon: Database, color: 'blue', count: providers?.length || 0 },
          ].map(({ key, label, icon: Icon, color, count }) => {
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
                <span className={`px-2 py-0.5 rounded-full text-xs ${active ? `bg-${color}-100 text-${color}-700` : 'bg-slate-100 text-slate-600'}`}>
                  {count}
                </span>
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
                <h2 className="text-lg font-bold text-slate-800">Members</h2>
                <p className="text-sm text-slate-500">{group?.users?.length || 0} members</p>
              </div>
            </div>
            <button
              onClick={() => setShowInviteMember(true)}
              className="bg-violet-500 text-white px-4 py-2 rounded-xl flex items-center hover:bg-violet-600 transition-colors shadow-sm"
            >
              <UserPlus className="w-4 h-4 mr-2" /> Invite Member
            </button>
          </div>

          {showInviteMember && (
            <div className="bg-slate-50 p-4 rounded-xl mb-4">
              <div className="flex gap-4">
                <div className="flex-1">
                  <label className="block text-sm font-medium text-slate-700 mb-2">Email Address *</label>
                  <div className="relative">
                    <Mail className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                    <input
                      type="email"
                      placeholder="user@example.com"
                      className="w-full pl-10 p-3 bg-white border border-slate-200 rounded-xl text-sm"
                      value={inviteEmail}
                      onChange={(e) => setInviteEmail(e.target.value)}
                    />
                  </div>
                </div>
              </div>
              <div className="mt-4">
                <label className="block text-sm font-medium text-slate-700 mb-2">Role</label>
                <select
                  className="w-full p-3 bg-white border border-slate-200 rounded-xl text-sm mb-4"
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value as typeof inviteRole)}
                >
                  <option value="member">Member</option>
                  <option value="admin">Admin</option>
                  <option value="root">Root</option>
                </select>
              </div>
              <div className="flex space-x-3">
                <button
                  onClick={() => inviteMemberMutation.mutate({ email: inviteEmail, role: inviteRole })}
                  disabled={!inviteEmail || inviteMemberMutation.isPending}
                  className="bg-violet-500 text-white px-4 py-2 rounded-xl text-sm hover:bg-violet-600 disabled:bg-slate-300"
                >
                  {inviteMemberMutation.isPending ? 'Inviting...' : 'Send Invite'}
                </button>
                <button
                  onClick={() => { setShowInviteMember(false); setInviteEmail(''); setInviteRole('member'); }}
                  className="bg-slate-200 text-slate-600 px-4 py-2 rounded-xl text-sm hover:bg-slate-300"
                >
                  Cancel
                </button>
              </div>
              {inviteMemberMutation.isError && (
                <p className="text-red-500 text-sm mt-2">Failed to invite member. Please check the email address.</p>
              )}
            </div>
          )}

          <div className="space-y-3">
            {group?.users?.map((member) => (
              <div key={member.id} className="bg-slate-50 p-4 rounded-xl flex items-center justify-between">
                <div className="flex items-center space-x-4">
                  <div className="w-10 h-10 bg-gradient-to-br from-violet-500 to-purple-600 rounded-full flex items-center justify-center">
                    <span className="text-white font-semibold text-sm">
                      {(member.username || member.email).charAt(0).toUpperCase()}
                    </span>
                  </div>
                  <div>
                    <div className="flex items-center space-x-2">
                      <h4 className="font-medium text-slate-800">{member.username || 'Unknown'}</h4>
                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium border ${getRoleBadgeColor(member.role)}`}>
                        {member.role}
                      </span>
                    </div>
                    <p className="text-sm text-slate-500">{member.email}</p>
                  </div>
                </div>
                <div className="flex items-center space-x-2">
                  {editingMemberRole === member.id ? (
                    <select
                      className="p-2 bg-white border border-slate-200 rounded-lg text-sm"
                      value={member.role}
                      onChange={(e) => updateRoleMutation.mutate({ userId: member.id, role: e.target.value })}
                      onBlur={() => setEditingMemberRole(null)}
                    >
                      <option value="member">Member</option>
                      <option value="admin">Admin</option>
                      <option value="root">Root</option>
                    </select>
                  ) : (
                    <button
                      onClick={() => setEditingMemberRole(member.id)}
                      className="text-slate-400 hover:text-blue-600 p-2 hover:bg-blue-50 rounded-lg transition-colors"
                      title="Change role"
                    >
                      <Edit2 className="w-4 h-4" />
                    </button>
                  )}
                  <button
                    onClick={() => { if (confirm(`Remove ${member.username || member.email} from this group?`)) removeMemberMutation.mutate(member.id); }}
                    className="text-slate-400 hover:text-red-600 p-2 hover:bg-red-50 rounded-lg transition-colors"
                    title="Remove member"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            ))}
            {(!group?.users || group.users.length === 0) && !showInviteMember && (
              <div className="text-center py-8 text-slate-500">
                <Users className="w-12 h-12 mx-auto mb-3 text-slate-300" />
                <p>No members yet.</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── API Keys Tab ─────────────────────────────────────────────────────── */}
      {activeTab === 'apikeys' && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
          {/* ApiKeyList handles all API key CRUD internally */}
          <ApiKeyList groupId={parseInt(id!)} />
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
              <h2 className="text-lg font-bold text-slate-800">Providers</h2>
              <p className="text-sm text-slate-500">Manage AI providers and models for this group</p>
            </div>
          </div>
          {/* ProviderList handles all provider + model CRUD internally */}
          <ProviderList groupId={parseInt(id!)} />
        </div>
      )}
    </div>
  );
}
