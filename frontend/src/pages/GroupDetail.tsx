import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import client from '../api/client';
import { 
  ArrowLeft, Plus, Edit2, Trash2, X, Save, Key, Database, Cpu, 
  Eye, EyeOff, Copy, Check, Link as LinkIcon, Users, UserPlus, Mail
} from 'lucide-react';

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

interface ApiKey {
  id: number;
  key: string;
  name: string;
  group_id: number;
  is_active: boolean;
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  request_count: number;
}

interface Model {
  id: number;
  provider_id: number;
  name: string;
  alias: string | null;
  context_size: number;
  input_size: number;
  input_price: number;
  output_price: number;
  support_kvcache: boolean;
  support_image: boolean;
  support_audio: boolean;
  support_video: boolean;
  support_file: boolean;
  support_web_search: boolean;
  support_tool_search: boolean;
}

interface Provider {
  id: number;
  name: string;
  type: string;
  description: string;
  base_url: string;
  api_key: string;
  group_id: number;
  models: Model[];
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
  const [showAddApiKey, setShowAddApiKey] = useState(false);
  const [editingApiKey, setEditingApiKey] = useState<ApiKey | null>(null);
  const [newApiKey, setNewApiKey] = useState({ name: '', expires_at: '' });
  
  const [showAddProvider, setShowAddProvider] = useState(false);
  const [editingProvider, setEditingProvider] = useState<Provider | null>(null);
  const [newProvider, setNewProvider] = useState({ 
    name: '', type: 'openai', description: '', base_url: '', api_key: '' 
  });
  
  const [expandedProvider, setExpandedProvider] = useState<number | null>(null);
  const [showAddModel, setShowAddModel] = useState<number | null>(null);
  const [editingModel, setEditingModel] = useState<Model | null>(null);
  const [viewingModel, setViewingModel] = useState<Model | null>(null);
  const [newModel, setNewModel] = useState({
    name: '', alias: '', context_size: 4096, input_size: 4096,
    input_price: 0, output_price: 0, cache_creation_price: 0, cache_hit_price: 0,
    support_kvcache: false, support_image: false, support_audio: false,
    support_video: false, support_file: false, support_web_search: false, support_tool_search: false
  });
  
  const [visibleKeys, setVisibleKeys] = useState<Set<number>>(new Set());
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  // Fetch group details
  const { data: group, isLoading: groupLoading } = useQuery({
    queryKey: ['group', id],
    queryFn: async () => {
      const response = await client.get(`/api/groups/${id}`);
      return response.data as Group;
    },
  });

  // Fetch API keys for this group
  const { data: apiKeys, isLoading: apiKeysLoading } = useQuery({
    queryKey: ['api-keys', 'group', id],
    queryFn: async () => {
      const response = await client.get(`/api/apikeys/group/${id}`);
      return response.data as ApiKey[];
    },
  });

  // Fetch providers for this group
  const { data: providers, isLoading: providersLoading } = useQuery({
    queryKey: ['providers', 'group', id],
    queryFn: async () => {
      const response = await client.get(`/api/providers/`, { params: { group_id: id } });
      return response.data as Provider[];
    },
  });

  // API Key mutations
  const createApiKeyMutation = useMutation({
    mutationFn: (data: any) => client.post('/api/apikeys/', { ...data, group_id: parseInt(id!) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-keys', 'group', id] });
      setShowAddApiKey(false);
      setNewApiKey({ name: '', expires_at: '' });
    },
  });

  const deleteApiKeyMutation = useMutation({
    mutationFn: (keyId: number) => client.delete(`/api/apikeys/${keyId}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['api-keys', 'group', id] }),
  });

  // Provider mutations
  const createProviderMutation = useMutation({
    mutationFn: (data: any) => client.post('/api/providers/', { ...data, group_id: parseInt(id!) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['providers', 'group', id] });
      setShowAddProvider(false);
      setNewProvider({ name: '', type: 'openai', description: '', base_url: '', api_key: '' });
    },
  });

  const updateProviderMutation = useMutation({
    mutationFn: ({ providerId, data }: { providerId: number; data: any }) => 
      client.put(`/api/providers/${providerId}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['providers', 'group', id] });
      setEditingProvider(null);
    },
  });

  const deleteProviderMutation = useMutation({
    mutationFn: (providerId: number) => client.delete(`/api/providers/${providerId}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['providers', 'group', id] }),
  });

  // Model mutations
  const createModelMutation = useMutation({
    mutationFn: (data: any) => client.post('/api/models/', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['providers', 'group', id] });
      setShowAddModel(null);
      setNewModel({
        name: '', alias: '', context_size: 4096, input_size: 4096,
        input_price: 0, output_price: 0, cache_creation_price: 0, cache_hit_price: 0,
        support_kvcache: false, support_image: false, support_audio: false,
        support_video: false, support_file: false, support_web_search: false, support_tool_search: false
      });
    },
  });

  const updateModelMutation = useMutation({
    mutationFn: ({ modelId, data }: { modelId: number; data: any }) => 
      client.put(`/api/models/${modelId}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['providers', 'group', id] });
      setEditingModel(null);
      setViewingModel(null);
    },
  });

  const deleteModelMutation = useMutation({
    mutationFn: (modelId: number) => client.delete(`/api/models/${modelId}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['providers', 'group', id] }),
  });

  // Member mutations
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

  const getRoleBadgeColor = (role: string) => {
    switch (role) {
      case 'root': return 'bg-rose-100 text-rose-700 border-rose-200';
      case 'admin': return 'bg-amber-100 text-amber-700 border-amber-200';
      default: return 'bg-slate-100 text-slate-600 border-slate-200';
    }
  };

  const toggleKeyVisibility = (keyId: number) => {
    const newSet = new Set(visibleKeys);
    if (newSet.has(keyId)) {
      newSet.delete(keyId);
    } else {
      newSet.add(keyId);
    }
    setVisibleKeys(newSet);
  };

  const copyToClipboard = async (text: string) => {
    await navigator.clipboard.writeText(text);
    setCopiedKey(text);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return 'Never';
    return new Date(dateStr).toLocaleString();
  };

  const isLoading = groupLoading || apiKeysLoading || providersLoading;

  if (isLoading) {
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

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center space-x-4">
        <button
          onClick={() => navigate('/groups')}
          className="p-2 hover:bg-slate-100 rounded-lg transition-colors"
        >
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
          <button
            onClick={() => setActiveTab('members')}
            className={`py-4 px-1 border-b-2 font-medium text-sm flex items-center space-x-2 transition-colors ${
              activeTab === 'members'
                ? 'border-violet-500 text-violet-600'
                : 'border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300'
            }`}
          >
            <Users className="w-4 h-4" />
            <span>Members</span>
            <span className={`px-2 py-0.5 rounded-full text-xs ${
              activeTab === 'members' ? 'bg-violet-100 text-violet-700' : 'bg-slate-100 text-slate-600'
            }`}>
              {group?.users?.length || 0}
            </span>
          </button>
          <button
            onClick={() => setActiveTab('apikeys')}
            className={`py-4 px-1 border-b-2 font-medium text-sm flex items-center space-x-2 transition-colors ${
              activeTab === 'apikeys'
                ? 'border-emerald-500 text-emerald-600'
                : 'border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300'
            }`}
          >
            <Key className="w-4 h-4" />
            <span>API Keys</span>
            <span className={`px-2 py-0.5 rounded-full text-xs ${
              activeTab === 'apikeys' ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-600'
            }`}>
              {apiKeys?.length || 0}
            </span>
          </button>
          <button
            onClick={() => setActiveTab('providers')}
            className={`py-4 px-1 border-b-2 font-medium text-sm flex items-center space-x-2 transition-colors ${
              activeTab === 'providers'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300'
            }`}
          >
            <Database className="w-4 h-4" />
            <span>Providers</span>
            <span className={`px-2 py-0.5 rounded-full text-xs ${
              activeTab === 'providers' ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-slate-600'
            }`}>
              {providers?.length || 0}
            </span>
          </button>
        </nav>
      </div>

      {/* Members Tab Content */}
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

        {/* Invite Member Form */}
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
                onChange={(e) => setInviteRole(e.target.value as 'root' | 'admin' | 'member')}
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

        {/* Members List */}
        <div className="space-y-3">
          {group?.users?.map((member) => (
            <div key={member.id} className="bg-slate-50 p-4 rounded-xl flex items-center justify-between">
              <div className="flex items-center space-x-4">
                <div className="w-10 h-10 bg-gradient-to-br from-violet-500 to-purple-600 rounded-full flex items-center justify-center">
                  <span className="text-white font-semibold text-sm">
                    {member.username?.charAt(0).toUpperCase() || member.email?.charAt(0).toUpperCase()}
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
                    onChange={(e) => {
                      updateRoleMutation.mutate({ userId: member.id, role: e.target.value });
                    }}
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
                  onClick={() => {
                    if (confirm(`Remove ${member.username || member.email} from this group?`)) {
                      removeMemberMutation.mutate(member.id);
                    }
                  }}
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

      {/* API Keys Tab Content */}
      {activeTab === 'apikeys' && (
      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
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
          <button
            onClick={() => setShowAddApiKey(true)}
            className="bg-emerald-500 text-white px-4 py-2 rounded-xl flex items-center hover:bg-emerald-600 transition-colors shadow-sm"
          >
            <Plus className="w-4 h-4 mr-2" /> New Key
          </button>
        </div>

        {/* Add API Key Form */}
        {showAddApiKey && (
          <div className="bg-slate-50 p-4 rounded-xl mb-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">Name *</label>
                <input
                  placeholder="Key name"
                  className="w-full p-3 bg-white border border-slate-200 rounded-xl text-sm"
                  value={newApiKey.name}
                  onChange={(e) => setNewApiKey({ ...newApiKey, name: e.target.value })}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">Expires At (optional)</label>
                <input
                  type="datetime-local"
                  className="w-full p-3 bg-white border border-slate-200 rounded-xl text-sm"
                  value={newApiKey.expires_at}
                  onChange={(e) => setNewApiKey({ ...newApiKey, expires_at: e.target.value })}
                />
              </div>
            </div>
            <div className="flex space-x-3 mt-4">
              <button
                onClick={() => createApiKeyMutation.mutate(newApiKey)}
                disabled={!newApiKey.name}
                className="bg-emerald-500 text-white px-4 py-2 rounded-xl text-sm hover:bg-emerald-600 disabled:bg-slate-300"
              >
                Create
              </button>
              <button
                onClick={() => { setShowAddApiKey(false); setNewApiKey({ name: '', expires_at: '' }); }}
                className="bg-slate-200 text-slate-600 px-4 py-2 rounded-xl text-sm hover:bg-slate-300"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* API Keys List */}
        <div className="space-y-3">
          {apiKeys?.map((apiKey) => (
            <div key={apiKey.id} className="bg-slate-50 p-4 rounded-xl flex items-center justify-between">
              <div className="flex items-center space-x-4">
                <div className={`w-3 h-3 rounded-full ${apiKey.is_active ? 'bg-emerald-500' : 'bg-slate-400'}`} />
                <div>
                  <h4 className="font-medium text-slate-800">{apiKey.name}</h4>
                  <div className="flex items-center space-x-2 mt-1">
                    <code className="text-sm text-slate-600 bg-white px-2 py-0.5 rounded">
                      {visibleKeys.has(apiKey.id) ? apiKey.key : `${apiKey.key.slice(0, 8)}...${apiKey.key.slice(-4)}`}
                    </code>
                    <button
                      onClick={() => toggleKeyVisibility(apiKey.id)}
                      className="text-slate-400 hover:text-slate-600"
                    >
                      {visibleKeys.has(apiKey.id) ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                    <button
                      onClick={() => copyToClipboard(apiKey.key)}
                      className="text-slate-400 hover:text-slate-600"
                    >
                      {copiedKey === apiKey.key ? <Check className="w-4 h-4 text-emerald-500" /> : <Copy className="w-4 h-4" />}
                    </button>
                  </div>
                </div>
              </div>
              <div className="flex items-center space-x-4 text-sm text-slate-500">
                <span>{apiKey.request_count} requests</span>
                <span>Last used: {formatDate(apiKey.last_used_at)}</span>
                <button
                  onClick={() => {
                    if (confirm('Delete this API key?')) {
                      deleteApiKeyMutation.mutate(apiKey.id);
                    }
                  }}
                  className="text-slate-400 hover:text-red-600 p-1 hover:bg-red-50 rounded"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>
          ))}
          {(!apiKeys || apiKeys.length === 0) && !showAddApiKey && (
            <div className="text-center py-8 text-slate-500">
              <Key className="w-12 h-12 mx-auto mb-3 text-slate-300" />
              <p>No API keys yet.</p>
            </div>
          )}
        </div>
      </div>
      )}

      {/* Model Detail/Edit Modal */}
      {(viewingModel || editingModel) && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
            <div className="p-6 border-b border-slate-200 sticky top-0 bg-white">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-3">
                  <div className="w-10 h-10 bg-gradient-to-br from-cyan-500 to-blue-600 rounded-lg flex items-center justify-center">
                    <Cpu className="w-5 h-5 text-white" />
                  </div>
                  <div>
                    <h2 className="text-lg font-bold text-slate-800">
                      {editingModel ? 'Edit Model' : 'Model Details'}
                    </h2>
                    <p className="text-sm text-slate-500">{viewingModel?.name || editingModel?.name}</p>
                  </div>
                </div>
                <button
                  onClick={() => { setViewingModel(null); setEditingModel(null); }}
                  className="text-slate-400 hover:text-slate-600 p-1 hover:bg-slate-100 rounded-lg transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            {editingModel ? (
              /* Edit Form */
              <div className="p-6 space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-2">Name *</label>
                    <input
                      className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm"
                      value={editingModel.name}
                      onChange={(e) => setEditingModel({ ...editingModel, name: e.target.value })}
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-2">Alias</label>
                    <input
                      className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm"
                      value={editingModel.alias || ''}
                      onChange={(e) => setEditingModel({ ...editingModel, alias: e.target.value || null })}
                      placeholder="Custom alias for API access"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-4 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-2">Context Size</label>
                    <input
                      type="number"
                      className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm"
                      value={editingModel.context_size}
                      onChange={(e) => setEditingModel({ ...editingModel, context_size: parseInt(e.target.value) })}
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-2">Input Size</label>
                    <input
                      type="number"
                      className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm"
                      value={editingModel.input_size}
                      onChange={(e) => setEditingModel({ ...editingModel, input_size: parseInt(e.target.value) })}
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-2">Input Price ($/M)</label>
                    <input
                      type="number"
                      step="0.01"
                      className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm"
                      value={editingModel.input_price}
                      onChange={(e) => setEditingModel({ ...editingModel, input_price: parseFloat(e.target.value) })}
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-2">Output Price ($/M)</label>
                    <input
                      type="number"
                      step="0.01"
                      className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm"
                      value={editingModel.output_price}
                      onChange={(e) => setEditingModel({ ...editingModel, output_price: parseFloat(e.target.value) })}
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">Supported Features</label>
                  <div className="grid grid-cols-4 gap-3">
                    {[
                      { key: 'support_kvcache', label: 'KV Cache' },
                      { key: 'support_image', label: 'Image' },
                      { key: 'support_audio', label: 'Audio' },
                      { key: 'support_video', label: 'Video' },
                      { key: 'support_file', label: 'File' },
                      { key: 'support_web_search', label: 'Web Search' },
                      { key: 'support_tool_search', label: 'Tool Search' },
                    ].map((feature) => (
                      <label key={feature.key} className="flex items-center space-x-2 cursor-pointer p-2 rounded-lg hover:bg-slate-50">
                        <input
                          type="checkbox"
                          checked={editingModel[feature.key as keyof Model] as boolean}
                          onChange={(e) => setEditingModel({ ...editingModel, [feature.key]: e.target.checked })}
                          className="w-4 h-4 rounded border-slate-300 text-blue-600"
                        />
                        <span className="text-sm text-slate-600">{feature.label}</span>
                      </label>
                    ))}
                  </div>
                </div>

                <div className="flex space-x-3 pt-4 border-t border-slate-200">
                  <button
                    onClick={() => updateModelMutation.mutate({ modelId: editingModel.id, data: editingModel })}
                    disabled={!editingModel.name || updateModelMutation.isPending}
                    className="bg-blue-500 text-white px-4 py-2 rounded-xl text-sm hover:bg-blue-600 disabled:bg-slate-300"
                  >
                    <Save className="w-4 h-4 mr-2 inline" /> {updateModelMutation.isPending ? 'Saving...' : 'Save Changes'}
                  </button>
                  <button
                    onClick={() => setEditingModel(null)}
                    className="bg-slate-200 text-slate-600 px-4 py-2 rounded-xl text-sm hover:bg-slate-300"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : viewingModel ? (
              /* View Details */
              <div className="p-6 space-y-6">
                {/* Basic Info */}
                <div className="grid grid-cols-2 gap-4">
                  <div className="bg-slate-50 p-4 rounded-xl">
                    <span className="text-sm text-slate-500">Model Name</span>
                    <p className="text-lg font-semibold text-slate-800">{viewingModel.name}</p>
                  </div>
                  <div className="bg-slate-50 p-4 rounded-xl">
                    <span className="text-sm text-slate-500">Alias</span>
                    <p className="text-lg font-semibold text-slate-800">
                      {viewingModel.alias ? `@${viewingModel.alias}` : <span className="text-slate-400">Not set</span>}
                    </p>
                  </div>
                </div>

                {/* Pricing */}
                <div>
                  <h3 className="text-sm font-medium text-slate-700 mb-3">Pricing</h3>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="bg-emerald-50 p-4 rounded-xl">
                      <span className="text-sm text-emerald-600">Input Price</span>
                      <p className="text-2xl font-bold text-emerald-700">${viewingModel.input_price}/M</p>
                    </div>
                    <div className="bg-blue-50 p-4 rounded-xl">
                      <span className="text-sm text-blue-600">Output Price</span>
                      <p className="text-2xl font-bold text-blue-700">${viewingModel.output_price}/M</p>
                    </div>
                  </div>
                </div>

                {/* Context & Size */}
                <div>
                  <h3 className="text-sm font-medium text-slate-700 mb-3">Context & Size</h3>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="bg-slate-50 p-4 rounded-xl">
                      <span className="text-sm text-slate-500">Context Size</span>
                      <p className="text-lg font-semibold text-slate-800">{viewingModel.context_size?.toLocaleString()}</p>
                    </div>
                    <div className="bg-slate-50 p-4 rounded-xl">
                      <span className="text-sm text-slate-500">Input Size</span>
                      <p className="text-lg font-semibold text-slate-800">{viewingModel.input_size?.toLocaleString()}</p>
                    </div>
                  </div>
                </div>

                {/* Features */}
                <div>
                  <h3 className="text-sm font-medium text-slate-700 mb-3">Supported Features</h3>
                  <div className="flex flex-wrap gap-2">
                    {[
                      { key: 'support_kvcache', label: 'KV Cache', color: 'violet' },
                      { key: 'support_image', label: 'Image', color: 'blue' },
                      { key: 'support_audio', label: 'Audio', color: 'emerald' },
                      { key: 'support_video', label: 'Video', color: 'rose' },
                      { key: 'support_file', label: 'File', color: 'amber' },
                      { key: 'support_web_search', label: 'Web Search', color: 'indigo' },
                      { key: 'support_tool_search', label: 'Tool Search', color: 'pink' },
                    ].map((feature) => {
                      const enabled = viewingModel[feature.key as keyof Model] as boolean;
                      const colors: Record<string, string> = {
                        violet: 'bg-violet-100 text-violet-700',
                        blue: 'bg-blue-100 text-blue-700',
                        emerald: 'bg-emerald-100 text-emerald-700',
                        rose: 'bg-rose-100 text-rose-700',
                        amber: 'bg-amber-100 text-amber-700',
                        indigo: 'bg-indigo-100 text-indigo-700',
                        pink: 'bg-pink-100 text-pink-700',
                      };
                      return (
                        <span
                          key={feature.key}
                          className={`px-3 py-1.5 rounded-lg text-sm font-medium ${
                            enabled ? colors[feature.color] : 'bg-slate-100 text-slate-400'
                          }`}
                        >
                          {feature.label}
                        </span>
                      );
                    })}
                  </div>
                </div>

                {/* Actions */}
                <div className="flex space-x-3 pt-4 border-t border-slate-200">
                  <button
                    onClick={() => setEditingModel(viewingModel)}
                    className="bg-blue-500 text-white px-4 py-2 rounded-xl text-sm hover:bg-blue-600"
                  >
                    <Edit2 className="w-4 h-4 mr-2 inline" /> Edit Model
                  </button>
                  <button
                    onClick={() => setViewingModel(null)}
                    className="bg-slate-200 text-slate-600 px-4 py-2 rounded-xl text-sm hover:bg-slate-300"
                  >
                    Close
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      )}

      {/* Providers Tab Content */}
      {activeTab === 'providers' && (
      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
        <div className="flex justify-between items-center mb-6">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center">
              <Database className="w-5 h-5 text-blue-600" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-slate-800">Providers</h2>
              <p className="text-sm text-slate-500">{providers?.length || 0} providers</p>
            </div>
          </div>
          <button
            onClick={() => setShowAddProvider(true)}
            className="bg-blue-500 text-white px-4 py-2 rounded-xl flex items-center hover:bg-blue-600 transition-colors shadow-sm"
          >
            <Plus className="w-4 h-4 mr-2" /> Add Provider
          </button>
        </div>

        {/* Add/Edit Provider Form */}
        {(showAddProvider || editingProvider) && (
          <div className="bg-slate-50 p-4 rounded-xl mb-4">
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">Name *</label>
                <input
                  placeholder="Provider name"
                  className="w-full p-3 bg-white border border-slate-200 rounded-xl text-sm"
                  value={editingProvider ? editingProvider.name : newProvider.name}
                  onChange={(e) => editingProvider 
                    ? setEditingProvider({ ...editingProvider, name: e.target.value })
                    : setNewProvider({ ...newProvider, name: e.target.value })
                  }
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">Type *</label>
                <select
                  className="w-full p-3 bg-white border border-slate-200 rounded-xl text-sm"
                  value={editingProvider ? editingProvider.type : newProvider.type}
                  onChange={(e) => editingProvider 
                    ? setEditingProvider({ ...editingProvider, type: e.target.value })
                    : setNewProvider({ ...newProvider, type: e.target.value })
                  }
                >
                  <option value="openai">OpenAI</option>
                  <option value="anthropic">Anthropic</option>
                  <option value="deepseek">DeepSeek</option>
                  <option value="kimi">Kimi</option>
                  <option value="glm">GLM (Zhipu AI)</option>
                  <option value="minimax">MiniMax</option>
                  <option value="bailian">Bailian (Alibaba)</option>
                  <option value="volcengine">Volcengine</option>
                  <option value="tencent">Tencent</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">Base URL</label>
                <input
                  placeholder="https://api.example.com"
                  className="w-full p-3 bg-white border border-slate-200 rounded-xl text-sm"
                  value={editingProvider ? editingProvider.base_url : newProvider.base_url}
                  onChange={(e) => editingProvider 
                    ? setEditingProvider({ ...editingProvider, base_url: e.target.value })
                    : setNewProvider({ ...newProvider, base_url: e.target.value })
                  }
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">API Key</label>
                <input
                  type="password"
                  placeholder="sk-..."
                  className="w-full p-3 bg-white border border-slate-200 rounded-xl text-sm"
                  value={editingProvider ? editingProvider.api_key : newProvider.api_key}
                  onChange={(e) => editingProvider 
                    ? setEditingProvider({ ...editingProvider, api_key: e.target.value })
                    : setNewProvider({ ...newProvider, api_key: e.target.value })
                  }
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">Description</label>
                <input
                  placeholder="Description"
                  className="w-full p-3 bg-white border border-slate-200 rounded-xl text-sm"
                  value={editingProvider ? editingProvider.description : newProvider.description}
                  onChange={(e) => editingProvider 
                    ? setEditingProvider({ ...editingProvider, description: e.target.value })
                    : setNewProvider({ ...newProvider, description: e.target.value })
                  }
                />
              </div>
            </div>
            <div className="flex space-x-3 mt-4">
              <button
                onClick={() => {
                  if (editingProvider) {
                    updateProviderMutation.mutate({ providerId: editingProvider.id, data: editingProvider });
                  } else {
                    createProviderMutation.mutate(newProvider);
                  }
                }}
                disabled={editingProvider ? !editingProvider.name : !newProvider.name}
                className="bg-blue-500 text-white px-4 py-2 rounded-xl text-sm hover:bg-blue-600 disabled:bg-slate-300"
              >
                <Save className="w-4 h-4 mr-2 inline" /> Save
              </button>
              <button
                onClick={() => { setShowAddProvider(false); setEditingProvider(null); }}
                className="bg-slate-200 text-slate-600 px-4 py-2 rounded-xl text-sm hover:bg-slate-300"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Providers List */}
        <div className="space-y-4">
          {providers?.map((provider) => (
            <div key={provider.id} className="border border-slate-200 rounded-xl overflow-hidden">
              <div
                className="p-4 flex justify-between items-center cursor-pointer hover:bg-slate-50"
                onClick={() => setExpandedProvider(expandedProvider === provider.id ? null : provider.id)}
              >
                <div className="flex items-center space-x-3">
                  <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-lg flex items-center justify-center">
                    <Database className="w-5 h-5 text-white" />
                  </div>
                  <div>
                    <div className="flex items-center space-x-2">
                      <h4 className="font-semibold text-slate-800">{provider.name}</h4>
                      <span className="bg-slate-100 text-slate-600 px-2 py-0.5 rounded text-xs font-medium uppercase">
                        {provider.type}
                      </span>
                    </div>
                    <p className="text-sm text-slate-500">
                      {provider.base_url ? (
                        <span className="flex items-center"><LinkIcon className="w-3 h-3 mr-1" />{provider.base_url}</span>
                      ) : 'No base URL'}
                    </p>
                  </div>
                </div>
                <div className="flex items-center space-x-2" onClick={(e) => e.stopPropagation()}>
                  <span className="bg-blue-100 text-blue-700 px-3 py-1 rounded-lg text-sm font-medium">
                    {provider.models.length} models
                  </span>
                  <button
                    onClick={() => setEditingProvider(provider)}
                    className="text-slate-400 hover:text-blue-600 p-1 hover:bg-blue-50 rounded"
                  >
                    <Edit2 className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => {
                      if (confirm('Delete this provider?')) {
                        deleteProviderMutation.mutate(provider.id);
                      }
                    }}
                    className="text-slate-400 hover:text-red-600 p-1 hover:bg-red-50 rounded"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>

              {/* Expanded Provider - Models */}
              {expandedProvider === provider.id && (
                <div className="p-4 bg-slate-50 border-t border-slate-200">
                  <div className="flex justify-between items-center mb-4">
                    <h5 className="font-medium text-slate-700">Models</h5>
                    <button
                      onClick={() => setShowAddModel(provider.id)}
                      className="bg-blue-500 text-white px-3 py-1.5 rounded-lg text-sm flex items-center hover:bg-blue-600"
                    >
                      <Plus className="w-3 h-3 mr-1" /> Add Model
                    </button>
                  </div>

                  {/* Add Model Form */}
                  {showAddModel === provider.id && (
                    <div className="bg-white p-4 rounded-xl border border-slate-200 mb-3">
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        <div>
                          <label className="block text-xs font-medium text-slate-700 mb-1">Name *</label>
                          <input
                            placeholder="gpt-4"
                            className="w-full p-2 bg-slate-50 border border-slate-200 rounded-lg text-sm"
                            value={newModel.name}
                            onChange={(e) => setNewModel({ ...newModel, name: e.target.value })}
                          />
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-slate-700 mb-1">Alias</label>
                          <input
                            placeholder="my-gpt4"
                            className="w-full p-2 bg-slate-50 border border-slate-200 rounded-lg text-sm"
                            value={newModel.alias}
                            onChange={(e) => setNewModel({ ...newModel, alias: e.target.value })}
                          />
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-slate-700 mb-1">Context</label>
                          <input
                            type="number"
                            className="w-full p-2 bg-slate-50 border border-slate-200 rounded-lg text-sm"
                            value={newModel.context_size}
                            onChange={(e) => setNewModel({ ...newModel, context_size: parseInt(e.target.value) })}
                          />
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-slate-700 mb-1">Input Price ($/M)</label>
                          <input
                            type="number"
                            step="0.01"
                            className="w-full p-2 bg-slate-50 border border-slate-200 rounded-lg text-sm"
                            value={newModel.input_price}
                            onChange={(e) => setNewModel({ ...newModel, input_price: parseFloat(e.target.value) })}
                          />
                        </div>
                      </div>
                      <div className="flex space-x-2 mt-3">
                        <button
                          onClick={() => createModelMutation.mutate({ ...newModel, provider_id: provider.id })}
                          disabled={!newModel.name}
                          className="bg-emerald-500 text-white px-3 py-1.5 rounded-lg text-sm hover:bg-emerald-600 disabled:bg-slate-300"
                        >
                          Add
                        </button>
                        <button
                          onClick={() => setShowAddModel(null)}
                          className="bg-slate-200 text-slate-600 px-3 py-1.5 rounded-lg text-sm hover:bg-slate-300"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Models List */}
                  <div className="space-y-2">
                    {provider.models.map((model) => (
                      <div 
                        key={model.id} 
                        className="bg-white p-3 rounded-lg border border-slate-200 flex items-center justify-between cursor-pointer hover:border-blue-300 transition-colors"
                        onClick={() => setViewingModel(model)}
                      >
                        <div className="flex items-center space-x-3">
                          <Cpu className="w-4 h-4 text-slate-400" />
                          <span className="font-medium text-slate-800">{model.name}</span>
                          {model.alias && (
                            <span className="bg-cyan-100 text-cyan-700 px-2 py-0.5 rounded text-xs">@{model.alias}</span>
                          )}
                          <span className="text-xs text-slate-500">{model.context_size?.toLocaleString()} ctx</span>
                          <span className="text-xs text-slate-500">${model.input_price}/${model.output_price} per M</span>
                        </div>
                        <div className="flex items-center space-x-1" onClick={(e) => e.stopPropagation()}>
                          <button
                            onClick={() => setEditingModel(model)}
                            className="text-slate-400 hover:text-blue-600 p-1 hover:bg-blue-50 rounded"
                            title="Edit"
                          >
                            <Edit2 className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => {
                              if (confirm('Delete this model?')) {
                                deleteModelMutation.mutate(model.id);
                              }
                            }}
                            className="text-slate-400 hover:text-red-600 p-1 hover:bg-red-50 rounded"
                            title="Delete"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </div>
                    ))}
                    {provider.models.length === 0 && !showAddModel && (
                      <p className="text-center text-slate-500 py-4 text-sm">No models added.</p>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}
          {(!providers || providers.length === 0) && !showAddProvider && (
            <div className="text-center py-8 text-slate-500">
              <Database className="w-12 h-12 mx-auto mb-3 text-slate-300" />
              <p>No providers yet.</p>
            </div>
          )}
        </div>
      </div>
      )}
    </div>
  );
}
