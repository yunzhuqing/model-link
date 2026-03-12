import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import client from '../api/client';
import { Plus, Edit2, Trash2, ChevronDown, ChevronUp, X, Save, Database, Cpu, Link as LinkIcon } from 'lucide-react';

interface Model {
  id: number;
  provider_id: number;
  name: string;
  alias: string | null;
  context_size: number;
  input_size: number;
  input_price: number;
  output_price: number;
  cache_creation_price: number;
  cache_hit_price: number;
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

interface Group {
  id: number;
  name: string;
  description: string;
}

const defaultModelState = {
  name: '',
  alias: '',
  context_size: 4096,
  input_size: 4096,
  input_price: 0,
  output_price: 0,
  cache_creation_price: 0,
  cache_hit_price: 0,
  support_kvcache: false,
  support_image: false,
  support_audio: false,
  support_video: false,
  support_file: false,
  support_web_search: false,
  support_tool_search: false,
};

const ProviderList = () => {
  const queryClient = useQueryClient();
  const [showAddProvider, setShowAddProvider] = useState(false);
  const [editingProvider, setEditingProvider] = useState<Provider | null>(null);
  const [newProvider, setNewProvider] = useState({ name: '', type: 'openai', description: '', base_url: '', api_key: '', group_id: 0 });
  const [expandedProvider, setExpandedProvider] = useState<number | null>(null);
  const [showAddModel, setShowAddModel] = useState<number | null>(null);
  const [editingModel, setEditingModel] = useState<Model | null>(null);
  const [newModel, setNewModel] = useState(defaultModelState);

  const { data: providers, isLoading } = useQuery({
    queryKey: ['providers'],
    queryFn: async () => {
      const response = await client.get('/api/providers/');
      return response.data as Provider[];
    },
  });

  const { data: groups } = useQuery({
    queryKey: ['groups'],
    queryFn: async () => {
      const response = await client.get('/api/groups/');
      return response.data as Group[];
    },
  });

  const createProviderMutation = useMutation({
    mutationFn: (provider: any) => client.post('/api/providers/', provider),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['providers'] });
      setShowAddProvider(false);
      setNewProvider({ name: '', type: 'openai', description: '', base_url: '', api_key: '', group_id: 0 });
    },
  });

  const updateProviderMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: any }) => client.put(`/api/providers/${id}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['providers'] });
      setEditingProvider(null);
    },
  });

  const deleteProviderMutation = useMutation({
    mutationFn: (id: number) => client.delete(`/api/providers/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['providers'] });
    },
  });

  const createModelMutation = useMutation({
    mutationFn: (model: any) => client.post('/api/models/', model),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['providers'] });
      setShowAddModel(null);
      setNewModel(defaultModelState);
    },
  });

  const updateModelMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: any }) => client.put(`/api/models/${id}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['providers'] });
      setEditingModel(null);
    },
  });

  const deleteModelMutation = useMutation({
    mutationFn: (id: number) => client.delete(`/api/models/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['providers'] });
    },
  });

  const handleEditProvider = (provider: Provider) => {
    setEditingProvider(provider);
    setShowAddProvider(false);
  };

  const handleEditModel = (model: Model) => {
    setEditingModel(model);
    setShowAddModel(null);
  };

  if (isLoading) return (
    <div className="flex justify-center items-center h-64">
      <div className="text-slate-500">Loading...</div>
    </div>
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Providers & Models</h1>
          <p className="text-slate-500 mt-1">Manage your AI providers and their models</p>
        </div>
        <button
          onClick={() => { setShowAddProvider(true); setEditingProvider(null); }}
          className="bg-gradient-to-r from-blue-500 to-indigo-600 text-white px-5 py-2.5 rounded-xl flex items-center hover:from-blue-600 hover:to-indigo-700 transition-all shadow-lg shadow-blue-500/25"
        >
          <Plus className="w-4 h-4 mr-2" /> Add Provider
        </button>
      </div>

      {/* Add/Edit Provider Form */}
      {(showAddProvider || editingProvider) && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
          <div className="flex justify-between items-center mb-6">
            <h2 className="text-lg font-bold text-slate-800">
              {editingProvider ? 'Edit Provider' : 'New Provider'}
            </h2>
            <button 
              onClick={() => { setShowAddProvider(false); setEditingProvider(null); }} 
              className="text-slate-400 hover:text-slate-600 p-1 hover:bg-slate-100 rounded-lg transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-2">Name *</label>
              <input
                placeholder="Provider name"
                className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                value={editingProvider ? editingProvider.name : newProvider.name}
                onChange={(e) => editingProvider 
                  ? setEditingProvider({ ...editingProvider, name: e.target.value })
                  : setNewProvider({ ...newProvider, name: e.target.value })
                }
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-2">Provider Type *</label>
              <select
                className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
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
                <option value="volcengine">Volcengine (ByteDance)</option>
                <option value="tencent">Tencent</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-2">Base URL</label>
              <input
                placeholder="https://api.example.com"
                className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
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
                className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
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
                className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                value={editingProvider ? editingProvider.description : newProvider.description}
                onChange={(e) => editingProvider 
                  ? setEditingProvider({ ...editingProvider, description: e.target.value })
                  : setNewProvider({ ...newProvider, description: e.target.value })
                }
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-2">Group *</label>
              <select
                className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                value={editingProvider ? editingProvider.group_id : newProvider.group_id}
                onChange={(e) => editingProvider 
                  ? setEditingProvider({ ...editingProvider, group_id: parseInt(e.target.value) })
                  : setNewProvider({ ...newProvider, group_id: parseInt(e.target.value) })
                }
              >
                <option value={0}>Select a group</option>
                {groups?.map((group) => (
                  <option key={group.id} value={group.id}>{group.name}</option>
                ))}
              </select>
              {groups?.length === 0 && (
                <p className="text-amber-600 text-sm mt-1">No groups available. Please create a group first.</p>
              )}
            </div>
          </div>
          <div className="mt-6 flex space-x-3">
            <button
              onClick={() => {
                if (editingProvider) {
                  updateProviderMutation.mutate({ id: editingProvider.id, data: editingProvider });
                } else {
                  createProviderMutation.mutate(newProvider);
                }
              }}
              className="bg-emerald-500 text-white px-5 py-2.5 rounded-xl flex items-center hover:bg-emerald-600 transition-colors shadow-sm"
            >
              <Save className="w-4 h-4 mr-2" /> Save
            </button>
            <button
              onClick={() => { setShowAddProvider(false); setEditingProvider(null); }}
              className="bg-slate-100 text-slate-600 px-5 py-2.5 rounded-xl hover:bg-slate-200 transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Provider List */}
      <div className="space-y-4">
        {providers?.map((provider) => (
          <div key={provider.id} className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
            <div
              className="p-5 flex justify-between items-center cursor-pointer hover:bg-slate-50 transition-colors"
              onClick={() => setExpandedProvider(expandedProvider === provider.id ? null : provider.id)}
            >
              <div className="flex items-center space-x-4">
                <div className="w-12 h-12 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-xl flex items-center justify-center shadow-lg shadow-blue-500/25">
                  <Database className="w-6 h-6 text-white" />
                </div>
                <div>
                  <div className="flex items-center space-x-2">
                    <h3 className="text-lg font-bold text-slate-800">{provider.name}</h3>
                    <span className="bg-slate-100 text-slate-600 px-2 py-0.5 rounded text-xs font-semibold uppercase">
                      {provider.type}
                    </span>
                  </div>
                  <p className="text-sm text-slate-500 flex items-center">
                    {provider.base_url ? (
                      <>
                        <LinkIcon className="w-3 h-3 mr-1" />
                        {provider.base_url}
                      </>
                    ) : 'No base URL configured'}
                  </p>
                </div>
              </div>
              <div className="flex items-center space-x-2" onClick={(e) => e.stopPropagation()}>
                <span className="bg-blue-100 text-blue-700 px-3 py-1 rounded-lg text-sm font-medium mr-2">
                  {provider.models.length} models
                </span>
                <button
                  onClick={() => handleEditProvider(provider)}
                  className="text-slate-400 hover:text-blue-600 p-2 hover:bg-blue-50 rounded-lg transition-colors"
                  title="Edit Provider"
                >
                  <Edit2 className="w-4 h-4" />
                </button>
                <button
                  onClick={() => {
                    if (confirm('Are you sure you want to delete this provider?')) {
                      deleteProviderMutation.mutate(provider.id);
                    }
                  }}
                  className="text-slate-400 hover:text-red-600 p-2 hover:bg-red-50 rounded-lg transition-colors"
                  title="Delete Provider"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
                {expandedProvider === provider.id ? (
                  <ChevronUp className="w-5 h-5 text-slate-400 ml-2" />
                ) : (
                  <ChevronDown className="w-5 h-5 text-slate-400 ml-2" />
                )}
              </div>
            </div>

            {expandedProvider === provider.id && (
              <div className="p-5 bg-slate-50 border-t border-slate-200">
                <div className="flex justify-between items-center mb-4">
                  <h4 className="font-bold text-slate-700">Models ({provider.models.length})</h4>
                  <button
                    onClick={() => { setShowAddModel(provider.id); setEditingModel(null); }}
                    className="bg-blue-500 text-white px-4 py-2 rounded-xl flex items-center hover:bg-blue-600 transition-colors shadow-sm"
                  >
                    <Plus className="w-4 h-4 mr-2" /> Add Model
                  </button>
                </div>

                {/* Add Model Form */}
                {showAddModel === provider.id && (
                  <ModelForm
                    model={newModel}
                    setModel={setNewModel}
                    onSave={() => createModelMutation.mutate({ ...newModel, provider_id: provider.id })}
                    onCancel={() => { setShowAddModel(null); setNewModel(defaultModelState); }}
                    isLoading={createModelMutation.isPending}
                  />
                )}

                {/* Model List */}
                <div className="space-y-3">
                  {provider.models.map((model) => (
                    <div key={model.id}>
                      {editingModel?.id === model.id ? (
                        <ModelForm
                          model={editingModel}
                          setModel={setEditingModel}
                          onSave={() => updateModelMutation.mutate({ id: model.id, data: editingModel })}
                          onCancel={() => setEditingModel(null)}
                          isLoading={updateModelMutation.isPending}
                        />
                      ) : (
                        <div className="bg-white p-5 rounded-xl border border-slate-200 hover:shadow-md transition-shadow">
                          <div className="flex justify-between items-start">
                            <div className="flex-1">
                              <div className="flex items-center space-x-3">
                                <div className="w-10 h-10 bg-slate-100 rounded-lg flex items-center justify-center">
                                  <Cpu className="w-5 h-5 text-slate-600" />
                                </div>
                                <h5 className="font-semibold text-slate-800">{model.name}</h5>
                                {model.alias && (
                                  <span className="bg-cyan-100 text-cyan-700 px-2 py-0.5 rounded text-xs font-medium">
                                    @{model.alias}
                                  </span>
                                )}
                              </div>
                              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4 text-sm">
                                <div className="bg-slate-50 p-3 rounded-lg">
                                  <span className="text-slate-400 block text-xs mb-1">Context</span>
                                  <span className="text-slate-700 font-medium">{model.context_size?.toLocaleString()}</span>
                                </div>
                                <div className="bg-slate-50 p-3 rounded-lg">
                                  <span className="text-slate-400 block text-xs mb-1">Input Size</span>
                                  <span className="text-slate-700 font-medium">{model.input_size?.toLocaleString()}</span>
                                </div>
                                <div className="bg-slate-50 p-3 rounded-lg">
                                  <span className="text-slate-400 block text-xs mb-1">Input Price</span>
                                  <span className="text-slate-700 font-medium">${model.input_price}/M</span>
                                </div>
                                <div className="bg-slate-50 p-3 rounded-lg">
                                  <span className="text-slate-400 block text-xs mb-1">Output Price</span>
                                  <span className="text-slate-700 font-medium">${model.output_price}/M</span>
                                </div>
                              </div>
                              <div className="flex flex-wrap gap-2 mt-4">
                                {model.support_kvcache && <FeatureBadge label="KV Cache" color="violet" />}
                                {model.support_image && <FeatureBadge label="Image" color="blue" />}
                                {model.support_audio && <FeatureBadge label="Audio" color="emerald" />}
                                {model.support_video && <FeatureBadge label="Video" color="rose" />}
                                {model.support_file && <FeatureBadge label="File" color="amber" />}
                                {model.support_web_search && <FeatureBadge label="Web Search" color="indigo" />}
                                {model.support_tool_search && <FeatureBadge label="Tool Search" color="pink" />}
                              </div>
                            </div>
                            <div className="flex space-x-1 ml-4">
                              <button
                                onClick={() => handleEditModel(model)}
                                className="text-slate-400 hover:text-blue-600 p-2 hover:bg-blue-50 rounded-lg transition-colors"
                                title="Edit Model"
                              >
                                <Edit2 className="w-4 h-4" />
                              </button>
                              <button
                                onClick={() => {
                                  if (confirm('Are you sure you want to delete this model?')) {
                                    deleteModelMutation.mutate(model.id);
                                  }
                                }}
                                className="text-slate-400 hover:text-red-600 p-2 hover:bg-red-50 rounded-lg transition-colors"
                                title="Delete Model"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                  {provider.models.length === 0 && !showAddModel && (
                    <div className="text-center py-8 text-slate-500">
                      <Cpu className="w-12 h-12 mx-auto mb-3 text-slate-300" />
                      <p>No models added yet.</p>
                      <p className="text-sm mt-1">Click "Add Model" to get started.</p>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        ))}
        {providers?.length === 0 && !showAddProvider && (
          <div className="text-center py-12 text-slate-500 bg-white rounded-2xl border border-slate-200">
            <Database className="w-16 h-16 mx-auto mb-4 text-slate-300" />
            <p className="text-lg font-medium text-slate-700">No providers configured yet.</p>
            <p className="text-sm mt-2">Click "Add Provider" to add your first AI provider.</p>
          </div>
        )}
      </div>
    </div>
  );
};

// Feature Badge Component
const FeatureBadge = ({ label, color }: { label: string; color: string }) => {
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
    <span className={`px-2.5 py-1 rounded-lg text-xs font-medium ${colors[color]}`}>
      {label}
    </span>
  );
};

// Model Form Component
const ModelForm = ({ 
  model, 
  setModel, 
  onSave, 
  onCancel, 
  isLoading 
}: { 
  model: any; 
  setModel: (m: any) => void; 
  onSave: () => void; 
  onCancel: () => void;
  isLoading: boolean;
}) => {
  return (
    <div className="bg-white p-5 rounded-xl border border-slate-200 mb-3">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">Model Name *</label>
          <input
            placeholder="gpt-4, claude-3, etc."
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            value={model.name}
            onChange={(e) => setModel({ ...model, name: e.target.value })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">
            Alias
            <span className="text-slate-400 font-normal ml-1">(for API access)</span>
          </label>
          <input
            placeholder="my-gpt4, smart-model, etc."
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            value={model.alias || ''}
            onChange={(e) => setModel({ ...model, alias: e.target.value || null })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">Context Size</label>
          <input
            type="number"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            value={model.context_size}
            onChange={(e) => setModel({ ...model, context_size: parseInt(e.target.value) || 0 })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">Input Size</label>
          <input
            type="number"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            value={model.input_size}
            onChange={(e) => setModel({ ...model, input_size: parseInt(e.target.value) || 0 })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">Input Price ($/M)</label>
          <input
            type="number"
            step="0.01"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            value={model.input_price}
            onChange={(e) => setModel({ ...model, input_price: parseFloat(e.target.value) || 0 })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">Output Price ($/M)</label>
          <input
            type="number"
            step="0.01"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            value={model.output_price}
            onChange={(e) => setModel({ ...model, output_price: parseFloat(e.target.value) || 0 })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">Cache Create ($/M)</label>
          <input
            type="number"
            step="0.01"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            value={model.cache_creation_price}
            onChange={(e) => setModel({ ...model, cache_creation_price: parseFloat(e.target.value) || 0 })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">Cache Hit ($/M)</label>
          <input
            type="number"
            step="0.01"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            value={model.cache_hit_price}
            onChange={(e) => setModel({ ...model, cache_hit_price: parseFloat(e.target.value) || 0 })}
          />
        </div>
      </div>
      
      <div className="mb-4">
        <label className="block text-sm font-medium text-slate-700 mb-2">Supported Features</label>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { key: 'support_kvcache', label: 'KV Cache' },
            { key: 'support_image', label: 'Image Input' },
            { key: 'support_audio', label: 'Audio Input' },
            { key: 'support_video', label: 'Video Input' },
            { key: 'support_file', label: 'File Input' },
            { key: 'support_web_search', label: 'Web Search' },
            { key: 'support_tool_search', label: 'Tool Search' },
          ].map((feature) => (
            <label key={feature.key} className="flex items-center space-x-2 cursor-pointer p-2 rounded-lg hover:bg-slate-50 transition-colors">
              <input
                type="checkbox"
                checked={model[feature.key]}
                onChange={(e) => setModel({ ...model, [feature.key]: e.target.checked })}
                className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
              />
              <span className="text-sm text-slate-600">{feature.label}</span>
            </label>
          ))}
        </div>
      </div>

      <div className="flex space-x-3">
        <button
          onClick={onSave}
          disabled={isLoading || !model.name}
          className="bg-emerald-500 text-white px-5 py-2.5 rounded-xl text-sm flex items-center hover:bg-emerald-600 disabled:bg-slate-300 disabled:cursor-not-allowed transition-colors shadow-sm"
        >
          <Save className="w-4 h-4 mr-2" /> {isLoading ? 'Saving...' : 'Save'}
        </button>
        <button
          onClick={onCancel}
          className="bg-slate-100 text-slate-600 px-5 py-2.5 rounded-xl text-sm hover:bg-slate-200 transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  );
};

export default ProviderList;