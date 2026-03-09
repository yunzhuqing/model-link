import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import client from '../api/client';
import { Plus, Edit2, Trash2, ChevronDown, ChevronUp, X, Save } from 'lucide-react';

interface Model {
  id: number;
  provider_id: number;
  name: string;
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
  description: string;
  base_url: string;
  api_key: string;
  models: Model[];
}

const defaultModelState = {
  name: '',
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
  const [newProvider, setNewProvider] = useState({ name: '', description: '', base_url: '', api_key: '' });
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

  const createProviderMutation = useMutation({
    mutationFn: (provider: any) => client.post('/api/providers/', provider),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['providers'] });
      setShowAddProvider(false);
      setNewProvider({ name: '', description: '', base_url: '', api_key: '' });
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

  if (isLoading) return <div className="flex justify-center items-center h-64">Loading...</div>;

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold text-gray-800">Providers & Models</h1>
        <button
          onClick={() => { setShowAddProvider(true); setEditingProvider(null); }}
          className="bg-blue-600 text-white px-4 py-2 rounded flex items-center hover:bg-blue-700 transition"
        >
          <Plus className="w-4 h-4 mr-2" /> Add Provider
        </button>
      </div>

      {/* Add/Edit Provider Form */}
      {(showAddProvider || editingProvider) && (
        <div className="bg-white p-6 rounded-lg shadow-sm border border-blue-200">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-bold">{editingProvider ? 'Edit Provider' : 'New Provider'}</h2>
            <button onClick={() => { setShowAddProvider(false); setEditingProvider(null); }} className="text-gray-500 hover:text-gray-700">
              <X className="w-5 h-5" />
            </button>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Name *</label>
              <input
                placeholder="Provider name"
                className="w-full p-2 border rounded focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                value={editingProvider ? editingProvider.name : newProvider.name}
                onChange={(e) => editingProvider 
                  ? setEditingProvider({ ...editingProvider, name: e.target.value })
                  : setNewProvider({ ...newProvider, name: e.target.value })
                }
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Base URL</label>
              <input
                placeholder="https://api.example.com"
                className="w-full p-2 border rounded focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                value={editingProvider ? editingProvider.base_url : newProvider.base_url}
                onChange={(e) => editingProvider 
                  ? setEditingProvider({ ...editingProvider, base_url: e.target.value })
                  : setNewProvider({ ...newProvider, base_url: e.target.value })
                }
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">API Key</label>
              <input
                type="password"
                placeholder="sk-..."
                className="w-full p-2 border rounded focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                value={editingProvider ? editingProvider.api_key : newProvider.api_key}
                onChange={(e) => editingProvider 
                  ? setEditingProvider({ ...editingProvider, api_key: e.target.value })
                  : setNewProvider({ ...newProvider, api_key: e.target.value })
                }
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
              <input
                placeholder="Description"
                className="w-full p-2 border rounded focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                value={editingProvider ? editingProvider.description : newProvider.description}
                onChange={(e) => editingProvider 
                  ? setEditingProvider({ ...editingProvider, description: e.target.value })
                  : setNewProvider({ ...newProvider, description: e.target.value })
                }
              />
            </div>
          </div>
          <div className="mt-4 flex space-x-2">
            <button
              onClick={() => {
                if (editingProvider) {
                  updateProviderMutation.mutate({ id: editingProvider.id, data: editingProvider });
                } else {
                  createProviderMutation.mutate(newProvider);
                }
              }}
              className="bg-green-600 text-white px-4 py-2 rounded flex items-center hover:bg-green-700 transition"
            >
              <Save className="w-4 h-4 mr-2" /> Save
            </button>
            <button
              onClick={() => { setShowAddProvider(false); setEditingProvider(null); }}
              className="bg-gray-300 px-4 py-2 rounded hover:bg-gray-400 transition"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Provider List */}
      <div className="space-y-4">
        {providers?.map((provider) => (
          <div key={provider.id} className="bg-white rounded-lg shadow-sm overflow-hidden">
            <div
              className="p-4 flex justify-between items-center cursor-pointer hover:bg-gray-50"
              onClick={() => setExpandedProvider(expandedProvider === provider.id ? null : provider.id)}
            >
              <div>
                <h3 className="text-lg font-bold text-gray-800">{provider.name}</h3>
                <p className="text-sm text-gray-500">{provider.base_url || 'No base URL configured'}</p>
              </div>
              <div className="flex items-center space-x-2" onClick={(e) => e.stopPropagation()}>
                <button
                  onClick={() => handleEditProvider(provider)}
                  className="text-blue-500 hover:text-blue-700 p-1"
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
                  className="text-red-500 hover:text-red-700 p-1"
                  title="Delete Provider"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
                {expandedProvider === provider.id ? <ChevronUp className="w-5 h-5 text-gray-400" /> : <ChevronDown className="w-5 h-5 text-gray-400" />}
              </div>
            </div>

            {expandedProvider === provider.id && (
              <div className="p-4 bg-gray-50 border-t">
                <div className="flex justify-between items-center mb-4">
                  <h4 className="font-bold text-gray-700">Models ({provider.models.length})</h4>
                  <button
                    onClick={() => { setShowAddModel(provider.id); setEditingModel(null); }}
                    className="text-sm bg-blue-600 text-white px-3 py-1 rounded flex items-center hover:bg-blue-700 transition"
                  >
                    <Plus className="w-3 h-3 mr-1" /> Add Model
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
                <div className="space-y-2">
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
                        <div className="bg-white p-4 rounded border hover:shadow-sm transition">
                          <div className="flex justify-between items-start">
                            <div className="flex-1">
                              <h5 className="font-semibold text-gray-800">{model.name}</h5>
                              <div className="grid grid-cols-4 gap-4 mt-2 text-sm text-gray-600">
                                <div>
                                  <span className="text-gray-400">Context:</span> {model.context_size?.toLocaleString()}
                                </div>
                                <div>
                                  <span className="text-gray-400">Input Size:</span> {model.input_size?.toLocaleString()}
                                </div>
                                <div>
                                  <span className="text-gray-400">Input Price:</span> ${model.input_price}/M
                                </div>
                                <div>
                                  <span className="text-gray-400">Output Price:</span> ${model.output_price}/M
                                </div>
                              </div>
                              <div className="grid grid-cols-4 gap-4 mt-1 text-sm text-gray-600">
                                <div>
                                  <span className="text-gray-400">Cache Create:</span> ${model.cache_creation_price}/M
                                </div>
                                <div>
                                  <span className="text-gray-400">Cache Hit:</span> ${model.cache_hit_price}/M
                                </div>
                              </div>
                              <div className="flex flex-wrap gap-2 mt-3">
                                {model.support_kvcache && <FeatureBadge label="KV Cache" color="purple" />}
                                {model.support_image && <FeatureBadge label="Image" color="blue" />}
                                {model.support_audio && <FeatureBadge label="Audio" color="green" />}
                                {model.support_video && <FeatureBadge label="Video" color="red" />}
                                {model.support_file && <FeatureBadge label="File" color="yellow" />}
                                {model.support_web_search && <FeatureBadge label="Web Search" color="indigo" />}
                                {model.support_tool_search && <FeatureBadge label="Tool Search" color="pink" />}
                              </div>
                            </div>
                            <div className="flex space-x-2 ml-4">
                              <button
                                onClick={() => handleEditModel(model)}
                                className="text-blue-500 hover:text-blue-700 p-1"
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
                                className="text-red-500 hover:text-red-700 p-1"
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
                    <p className="text-sm text-gray-400 italic text-center py-4">No models added yet. Click "Add Model" to get started.</p>
                  )}
                </div>
              </div>
            )}
          </div>
        ))}
        {providers?.length === 0 && !showAddProvider && (
          <div className="text-center py-12 text-gray-500">
            <p>No providers configured yet.</p>
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
    purple: 'bg-purple-100 text-purple-700',
    blue: 'bg-blue-100 text-blue-700',
    green: 'bg-green-100 text-green-700',
    red: 'bg-red-100 text-red-700',
    yellow: 'bg-yellow-100 text-yellow-700',
    indigo: 'bg-indigo-100 text-indigo-700',
    pink: 'bg-pink-100 text-pink-700',
  };
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[color]}`}>
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
    <div className="bg-white p-4 rounded border mb-2 shadow-sm">
      <div className="grid grid-cols-4 gap-4 mb-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Model Name *</label>
          <input
            placeholder="gpt-4, claude-3, etc."
            className="w-full p-2 border rounded text-sm focus:ring-2 focus:ring-blue-500"
            value={model.name}
            onChange={(e) => setModel({ ...model, name: e.target.value })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Context Size</label>
          <input
            type="number"
            className="w-full p-2 border rounded text-sm focus:ring-2 focus:ring-blue-500"
            value={model.context_size}
            onChange={(e) => setModel({ ...model, context_size: parseInt(e.target.value) || 0 })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Input Size</label>
          <input
            type="number"
            className="w-full p-2 border rounded text-sm focus:ring-2 focus:ring-blue-500"
            value={model.input_size}
            onChange={(e) => setModel({ ...model, input_size: parseInt(e.target.value) || 0 })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Input Price ($/M)</label>
          <input
            type="number"
            step="0.01"
            className="w-full p-2 border rounded text-sm focus:ring-2 focus:ring-blue-500"
            value={model.input_price}
            onChange={(e) => setModel({ ...model, input_price: parseFloat(e.target.value) || 0 })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Output Price ($/M)</label>
          <input
            type="number"
            step="0.01"
            className="w-full p-2 border rounded text-sm focus:ring-2 focus:ring-blue-500"
            value={model.output_price}
            onChange={(e) => setModel({ ...model, output_price: parseFloat(e.target.value) || 0 })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Cache Create Price ($/M)</label>
          <input
            type="number"
            step="0.01"
            className="w-full p-2 border rounded text-sm focus:ring-2 focus:ring-blue-500"
            value={model.cache_creation_price}
            onChange={(e) => setModel({ ...model, cache_creation_price: parseFloat(e.target.value) || 0 })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Cache Hit Price ($/M)</label>
          <input
            type="number"
            step="0.01"
            className="w-full p-2 border rounded text-sm focus:ring-2 focus:ring-blue-500"
            value={model.cache_hit_price}
            onChange={(e) => setModel({ ...model, cache_hit_price: parseFloat(e.target.value) || 0 })}
          />
        </div>
      </div>
      
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700 mb-2">Supported Features</label>
        <div className="grid grid-cols-4 gap-3">
          {[
            { key: 'support_kvcache', label: 'KV Cache' },
            { key: 'support_image', label: 'Image Input' },
            { key: 'support_audio', label: 'Audio Input' },
            { key: 'support_video', label: 'Video Input' },
            { key: 'support_file', label: 'File Input' },
            { key: 'support_web_search', label: 'Web Search' },
            { key: 'support_tool_search', label: 'Tool Search' },
          ].map((feature) => (
            <label key={feature.key} className="flex items-center space-x-2 cursor-pointer">
              <input
                type="checkbox"
                checked={model[feature.key]}
                onChange={(e) => setModel({ ...model, [feature.key]: e.target.checked })}
                className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              <span className="text-sm text-gray-600">{feature.label}</span>
            </label>
          ))}
        </div>
      </div>

      <div className="flex space-x-2">
        <button
          onClick={onSave}
          disabled={isLoading || !model.name}
          className="bg-green-600 text-white px-4 py-2 rounded text-sm flex items-center hover:bg-green-700 disabled:bg-gray-400 transition"
        >
          <Save className="w-4 h-4 mr-2" /> {isLoading ? 'Saving...' : 'Save'}
        </button>
        <button
          onClick={onCancel}
          className="bg-gray-300 px-4 py-2 rounded text-sm hover:bg-gray-400 transition"
        >
          Cancel
        </button>
      </div>
    </div>
  );
};

export default ProviderList;