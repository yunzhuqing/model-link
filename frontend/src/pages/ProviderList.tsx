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
  output_size: number;
  reasoning_effort: string | null;
  supported_image_formats: string | null;
  pricing_tiers: PricingTier[] | null;
  input_price: number;
  output_price: number;
  cache_creation_price: number;
  cache_hit_price: number;
  currency: string;
  retirement_time: string | null;
  is_retired: boolean;
  rpm: number | null;
  tpm: number | null;
  discount: number;
  support_kvcache: boolean;
  support_image: boolean;
  support_audio: boolean;
  support_video: boolean;
  support_file: boolean;
  support_web_search: boolean;
  support_tool_search: boolean;
  support_thinking: boolean;
  support_online_image: boolean;
  support_online_video: boolean;
  support_embedding: boolean;
}

interface Provider {
  id: number;
  name: string;
  type: string;
  description: string;
  base_url: string;
  api_key: string;
  group_id: number;
  extra_config: Record<string, any>;
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
  output_size: 4096,
  reasoning_effort: '',
  supported_image_formats: '',
  input_price: 0,
  output_price: 0,
  cache_creation_price: 0,
  cache_hit_price: 0,
  currency: 'USD',
  retirement_time: null as string | null,
  rpm: null as number | null,
  tpm: null as number | null,
  discount: 1.0,
  support_kvcache: false,
  support_image: false,
  support_audio: false,
  support_video: false,
  support_file: false,
  support_web_search: false,
  support_tool_search: false,
  support_thinking: false,
  support_online_image: false,
  support_online_video: false,
  support_embedding: false,
};

const ProviderList = () => {
  const queryClient = useQueryClient();
  const [showAddProvider, setShowAddProvider] = useState(false);
  const [editingProvider, setEditingProvider] = useState<Provider | null>(null);
  const [newProvider, setNewProvider] = useState({ name: '', type: 'openai', description: '', base_url: '', api_key: '', group_id: 0, extra_config: {} as Record<string, any> });
  const [expandedProvider, setExpandedProvider] = useState<number | null>(null);
  const [showAddModel, setShowAddModel] = useState<number | null>(null);
  const [editingModel, setEditingModel] = useState<Model | null>(null);
  const [newModel, setNewModel] = useState(defaultModelState);

  const { data: modelTemplates = [] } = useQuery({
    queryKey: ['model-templates'],
    queryFn: async () => {
      const response = await client.get('/api/model-templates/');
      return response.data as ModelTemplate[];
    },
  });

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
      setNewProvider({ name: '', type: 'openai', description: '', base_url: '', api_key: '', group_id: 0, extra_config: {} });
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
                <option value="azure">Azure OpenAI</option>
                <option value="deepseek">DeepSeek</option>
                <option value="moonshot">Moonshot (Kimi)</option>
                <option value="glm">GLM (Zhipu AI)</option>
                <option value="minimax">MiniMax</option>
                <option value="bailian">Bailian (Alibaba)</option>
                <option value="volcengine">Volcengine (ByteDance)</option>
                <option value="gemini">Gemini (Google AI)</option>
                <option value="vertexai">Vertex AI (Google Cloud)</option>
                <option value="tencentvod">Tencent VOD</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-2">Base URL</label>
              <input
                placeholder={
                  (editingProvider?.type || newProvider.type) === 'vertexai'
                    ? 'https://{REGION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{REGION}'
                    : (editingProvider?.type || newProvider.type) === 'azure'
                    ? 'https://your-resource.openai.azure.com'
                    : 'https://api.example.com'
                }
                className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                value={editingProvider ? editingProvider.base_url : newProvider.base_url}
                onChange={(e) => editingProvider 
                  ? setEditingProvider({ ...editingProvider, base_url: e.target.value })
                  : setNewProvider({ ...newProvider, base_url: e.target.value })
                }
              />
              {(editingProvider?.type || newProvider.type) === 'vertexai' && (
                <p className="text-xs text-slate-400 mt-1">
                  Format: https://REGION-aiplatform.googleapis.com/v1/projects/PROJECT_ID/locations/REGION
                </p>
              )}
              {(editingProvider?.type || newProvider.type) === 'azure' && (
                <p className="text-xs text-slate-400 mt-1">
                  Format: https://&#123;resource-name&#125;.openai.azure.com
                </p>
              )}
              {(editingProvider?.type || newProvider.type) === 'tencentvod' && (
                <p className="text-xs text-slate-400 mt-1">
                  Default: https://text-aigc.vod-qcloud.com/v1 (leave blank to use default)
                </p>
              )}
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-2">
                {(editingProvider?.type || newProvider.type) === 'vertexai' ? 'Service Account JSON' : 'API Key'}
              </label>
              {(editingProvider?.type || newProvider.type) === 'vertexai' ? (
                <textarea
                  placeholder='Paste the full JSON content of your Google Cloud service account key file, or leave empty to use Application Default Credentials (ADC)'
                  rows={4}
                  className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all font-mono text-sm"
                  value={editingProvider ? editingProvider.api_key : newProvider.api_key}
                  onChange={(e) => editingProvider 
                    ? setEditingProvider({ ...editingProvider, api_key: e.target.value })
                    : setNewProvider({ ...newProvider, api_key: e.target.value })
                  }
                />
              ) : (
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
              )}
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

          {/* Azure-specific fields */}
          {(editingProvider?.type || newProvider.type) === 'azure' && (
            <div className="mt-4 p-4 bg-blue-50 border border-blue-200 rounded-xl">
              <h3 className="text-sm font-semibold text-blue-800 mb-3">Azure OpenAI Configuration</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">API Version</label>
                  <input
                    placeholder="2025-01-01-preview"
                    className="w-full p-3 bg-white border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                    value={editingProvider 
                      ? (editingProvider.extra_config?.api_version || '') 
                      : (newProvider.extra_config?.api_version || '')
                    }
                    onChange={(e) => {
                      const val = e.target.value;
                      if (editingProvider) {
                        setEditingProvider({ 
                          ...editingProvider, 
                          extra_config: { ...editingProvider.extra_config, api_version: val } 
                        });
                      } else {
                        setNewProvider({ 
                          ...newProvider, 
                          extra_config: { ...newProvider.extra_config, api_version: val } 
                        });
                      }
                    }}
                  />
                  <p className="text-xs text-slate-400 mt-1">
                    Default: 2025-01-01-preview. See Azure docs for available versions.
                  </p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">Region</label>
                  <input
                    placeholder="eastus, westeurope, etc."
                    className="w-full p-3 bg-white border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                    value={editingProvider 
                      ? (editingProvider.extra_config?.region || '') 
                      : (newProvider.extra_config?.region || '')
                    }
                    onChange={(e) => {
                      const val = e.target.value;
                      if (editingProvider) {
                        setEditingProvider({ 
                          ...editingProvider, 
                          extra_config: { ...editingProvider.extra_config, region: val } 
                        });
                      } else {
                        setNewProvider({ 
                          ...newProvider, 
                          extra_config: { ...newProvider.extra_config, region: val } 
                        });
                      }
                    }}
                  />
                  <p className="text-xs text-slate-400 mt-1">
                    The Azure region where your resource is deployed (e.g., eastus, westeurope).
                  </p>
                </div>
              </div>
            </div>
          )}

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
                    templates={modelTemplates}
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
                          templates={modelTemplates}
                        />
                      ) : (
                        <div className="bg-white p-5 rounded-xl border border-slate-200 hover:shadow-md transition-shadow">
                          <div className="flex justify-between items-start">
                            <div className="flex-1">
                              <div className="flex items-center space-x-3 flex-wrap gap-y-1">
                                <div className="w-10 h-10 bg-slate-100 rounded-lg flex items-center justify-center shrink-0">
                                  <Cpu className="w-5 h-5 text-slate-600" />
                                </div>
                                <h5 className="font-semibold text-slate-800">{model.name}</h5>
                                {model.alias && (
                                  <span className="bg-cyan-100 text-cyan-700 px-2 py-0.5 rounded text-xs font-medium">
                                    @{model.alias}
                                  </span>
                                )}
                                {model.currency && model.currency !== 'USD' && (
                                  <span className="bg-violet-100 text-violet-700 px-2 py-0.5 rounded text-xs font-medium">
                                    {model.currency}
                                  </span>
                                )}
                                {model.is_retired && (
                                  <span className="bg-red-100 text-red-700 px-2 py-0.5 rounded text-xs font-medium">
                                    Retired
                                  </span>
                                )}
                                {!model.is_retired && model.retirement_time && (
                                  <span className="bg-orange-100 text-orange-700 px-2 py-0.5 rounded text-xs font-medium">
                                    Retires {new Date(model.retirement_time).toLocaleDateString()}
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
                                  <span className="text-slate-700 font-medium">{model.input_price}/M {model.currency || 'USD'}</span>
                                </div>
                                <div className="bg-slate-50 p-3 rounded-lg">
                                  <span className="text-slate-400 block text-xs mb-1">Output Price</span>
                                  <span className="text-slate-700 font-medium">{model.output_price}/M {model.currency || 'USD'}</span>
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
                                {model.support_thinking && <FeatureBadge label="Thinking" color="cyan" />}
                                {model.support_online_image === false && <FeatureBadge label="Base64 Image Only" color="slate" />}
                                {model.support_online_video === false && <FeatureBadge label="Base64 Video Only" color="slate" />}
                                {model.support_embedding && <FeatureBadge label="Embedding" color="emerald" />}
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
    cyan: 'bg-cyan-100 text-cyan-700',
    slate: 'bg-slate-200 text-slate-700',
  };
  return (
    <span className={`px-2.5 py-1 rounded-lg text-xs font-medium ${colors[color]}`}>
      {label}
    </span>
  );
};

interface PricingTier {
  label: string;
  context_size: number;
  input_size: number;
  output_size: number;
  input_price: number;
  output_price: number;
  cache_creation_price: number;
  cache_hit_price: number;
}

interface ModelTemplate {
  id: number;
  label: string;
  provider: string;
  name: string;
  alias: string | null;
  context_size: number;
  input_size: number;
  output_size?: number;
  pricing_tiers: PricingTier[] | null;
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
  support_thinking: boolean;
  support_online_image: boolean;
  support_online_video: boolean;
  support_embedding: boolean;
}

// Model Form Component
const ModelForm = ({ 
  model, 
  setModel, 
  onSave, 
  onCancel, 
  isLoading,
  templates,
}: { 
  model: any; 
  setModel: (m: any) => void; 
  onSave: () => void; 
  onCancel: () => void;
  isLoading: boolean;
  templates: ModelTemplate[];
}) => {
  const templateProviders = Array.from(new Set(templates.map((t) => t.provider)));
  const [activeTpl, setActiveTpl] = useState<ModelTemplate | null>(null);

  const applyTplOrTier = (tpl: ModelTemplate, tier?: PricingTier) => {
    const src = tier ?? tpl;
    setModel({
      ...model,
      name: tpl.name,
      alias: tpl.alias || '',
      context_size: src.context_size ?? tpl.context_size,
      input_size: src.input_size ?? tpl.input_size,
      output_size: (src as any).output_size ?? tpl.output_size ?? 4096,
      input_price: src.input_price,
      output_price: src.output_price,
      cache_creation_price: src.cache_creation_price,
      cache_hit_price: src.cache_hit_price,
      support_kvcache: tpl.support_kvcache,
      support_image: tpl.support_image,
      support_audio: tpl.support_audio,
      support_video: tpl.support_video,
      support_file: tpl.support_file,
      support_web_search: tpl.support_web_search,
      support_tool_search: tpl.support_tool_search,
      support_thinking: tpl.support_thinking,
      support_online_image: tpl.support_online_image,
      support_online_video: tpl.support_online_video,
      support_embedding: tpl.support_embedding,
    });
  };

  return (
    <div className="bg-white p-5 rounded-xl border border-slate-200 mb-3">
      {/* Template selector */}
      <div className="mb-4 pb-4 border-b border-slate-100">
        <label className="block text-sm font-medium text-slate-700 mb-2">
          Quick Fill from Template
          <span className="text-slate-400 font-normal ml-1">(optional)</span>
        </label>
        <select
          className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
          value={activeTpl?.id ?? ''}
          onChange={(e) => {
            const id = parseInt(e.target.value);
            if (isNaN(id)) { setActiveTpl(null); return; }
            const tpl = templates.find((t) => t.id === id);
            if (!tpl) return;
            setActiveTpl(tpl);
            if (!tpl.pricing_tiers || tpl.pricing_tiers.length === 0) {
              applyTplOrTier(tpl);
            }
          }}
        >
          <option value="">— Select a template —</option>
          {templateProviders.map((providerName) => (
            <optgroup key={providerName} label={providerName}>
              {templates
                .filter((tpl) => tpl.provider === providerName)
                .map((tpl) => (
                  <option key={tpl.id} value={tpl.id}>
                    {tpl.label}
                  </option>
                ))}
            </optgroup>
          ))}
        </select>
        {activeTpl?.pricing_tiers && activeTpl.pricing_tiers.length > 0 && (
          <div className="mt-2">
            <label className="block text-xs font-medium text-slate-600 mb-1">Select Pricing Tier</label>
            <select
              className="w-full p-2 bg-slate-50 border border-blue-300 rounded-lg text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
              defaultValue=""
              onChange={(e) => {
                const idx = parseInt(e.target.value);
                if (isNaN(idx)) return;
                const tier = activeTpl.pricing_tiers![idx];
                applyTplOrTier(activeTpl, tier);
              }}
            >
              <option value="">— Pick a tier —</option>
              {activeTpl.pricing_tiers.map((tier, idx) => (
                <option key={idx} value={idx}>
                  {tier.label} — in ${tier.input_price}/M out ${tier.output_price}/M
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

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
          <label className="block text-sm font-medium text-slate-700 mb-2">Output Size</label>
          <input
            type="number"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            value={model.output_size ?? 4096}
            onChange={(e) => setModel({ ...model, output_size: parseInt(e.target.value) || 0 })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">
            Reasoning Effort
            <span className="text-slate-400 font-normal ml-1">(none/low/medium/high)</span>
          </label>
          <input
            placeholder="none"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            value={model.reasoning_effort || ''}
            onChange={(e) => setModel({ ...model, reasoning_effort: e.target.value || null })}
          />
        </div>
        <div className="md:col-span-2">
          <label className="block text-sm font-medium text-slate-700 mb-2">
            Supported Image Formats
            <span className="text-slate-400 font-normal ml-1">(comma-separated, e.g. png,jpeg,webp)</span>
          </label>
          <input
            placeholder="png,jpeg,webp,gif (leave blank for no restriction)"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            value={model.supported_image_formats || ''}
            onChange={(e) => setModel({ ...model, supported_image_formats: e.target.value || null })}
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
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">Currency</label>
          <select
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            value={model.currency || 'USD'}
            onChange={(e) => setModel({ ...model, currency: e.target.value })}
          >
            <option value="USD">USD ($)</option>
            <option value="CNY">CNY (¥)</option>
            <option value="EUR">EUR (€)</option>
            <option value="GBP">GBP (£)</option>
            <option value="JPY">JPY (¥)</option>
          </select>
        </div>
        <div className="md:col-span-2">
          <label className="block text-sm font-medium text-slate-700 mb-2">
            Retirement Date
            <span className="text-slate-400 font-normal ml-1 text-xs">(optional — model cannot be used after this date)</span>
          </label>
          <input
            type="datetime-local"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            value={model.retirement_time ? model.retirement_time.slice(0, 16) : ''}
            onChange={(e) => setModel({ ...model, retirement_time: e.target.value ? e.target.value + ':00' : null })}
          />
        </div>
      </div>
      
      {/* Rate limits & discount */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-4">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">
            RPM
            <span className="text-slate-400 font-normal ml-1 text-xs">(req/min, blank = ∞)</span>
          </label>
          <input
            type="number"
            min="0"
            placeholder="unlimited"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            value={model.rpm ?? ''}
            onChange={(e) => setModel({ ...model, rpm: e.target.value ? parseInt(e.target.value) : null })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">
            TPM
            <span className="text-slate-400 font-normal ml-1 text-xs">(tok/min, blank = ∞)</span>
          </label>
          <input
            type="number"
            min="0"
            placeholder="unlimited"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            value={model.tpm ?? ''}
            onChange={(e) => setModel({ ...model, tpm: e.target.value ? parseInt(e.target.value) : null })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">
            Discount
            <span className="text-slate-400 font-normal ml-1 text-xs">(1.0 = full, 0.9 = 10% off)</span>
          </label>
          <input
            type="number"
            step="0.01"
            min="0"
            max="1"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            value={model.discount ?? 1.0}
            onChange={(e) => setModel({ ...model, discount: parseFloat(e.target.value) || 1.0 })}
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
            { key: 'support_thinking', label: 'Thinking' },
            { key: 'support_online_image', label: 'Online Image URL' },
            { key: 'support_online_video', label: 'Online Video URL' },
            { key: 'support_embedding', label: 'Embedding' },
          ].map((feature) => (
            <label key={feature.key} className="flex items-center space-x-2 cursor-pointer p-2 rounded-lg hover:bg-slate-50 transition-colors">
              <input
                type="checkbox"
                checked={!!model[feature.key]}
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