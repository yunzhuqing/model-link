import axios from 'axios';

// In production (Docker), use relative URL (same origin).
// In development, set VITE_API_URL in frontend/.env.development
const API_URL = import.meta.env.VITE_API_URL || '';

const client = axios.create({
  baseURL: API_URL,
});

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Types
export interface ApiKey {
  id: number;
  key: string;
  name: string;
  group_id: number | null;
  group_name?: string;
  is_active: boolean;
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  request_count: number;
  token_count: number;
}

export interface ApiKeyCreate {
  name: string;
  group_id?: number;
  expires_at?: string;
}

export interface ApiKeyUpdate {
  name?: string;
  is_active?: boolean;
  expires_at?: string;
}

export interface Group {
  id: number;
  name: string;
  description: string | null;
  created_at: string;
  user_count?: number;
  api_key_count?: number;
  users?: Array<{ id: number; username: string; email: string }>;
  api_keys?: Array<{ id: number; name: string; is_active: boolean }>;
  providers?: Array<{ id: number; name: string; type: string }>;
}

export interface GroupCreate {
  name: string;
  description?: string;
}

export interface GroupUpdate {
  name?: string;
  description?: string;
}

export interface Provider {
  id: number;
  name: string;
  provider_type: string;
  base_url: string | null;
  api_key: string | null;
  is_active: boolean;
  created_at: string;
  models: Model[];
}

export interface Model {
  id: number;
  name: string;
  display_name: string | null;
  context_size: number;
  max_input_tokens: number | null;
  max_output_tokens: number | null;
  input_price: number;
  output_price: number;
  cache_creation_price: number | null;
  cache_read_price: number | null;
  supports_kv_cache: boolean;
  supports_vision: boolean;
  supports_audio: boolean;
  supports_video: boolean;
  supports_file: boolean;
  supports_web_search: boolean;
  supports_tool_call: boolean;
  provider_id: number;
}

export interface ProviderCreate {
  name: string;
  provider_type: string;
  base_url?: string;
  api_key?: string;
}

export interface ModelCreate {
  name: string;
  display_name?: string;
  context_size: number;
  max_input_tokens?: number;
  max_output_tokens?: number;
  input_price: number;
  output_price: number;
  cache_creation_price?: number;
  cache_read_price?: number;
  supports_kv_cache?: boolean;
  supports_vision?: boolean;
  supports_audio?: boolean;
  supports_video?: boolean;
  supports_file?: boolean;
  supports_web_search?: boolean;
  supports_tool_call?: boolean;
}

// API Key endpoints
export const apiKeysApi = {
  list: () => client.get<ApiKey[]>('/api/api-keys/'),
  get: (id: number) => client.get<ApiKey>(`/api/api-keys/${id}`),
  create: (data: ApiKeyCreate) => client.post<ApiKey>('/api/api-keys/', data),
  update: (id: number, data: ApiKeyUpdate) => client.put<ApiKey>(`/api/api-keys/${id}`, data),
  delete: (id: number) => client.delete(`/api/api-keys/${id}`),
  regenerate: (id: number) => client.post<ApiKey>(`/api/api-keys/${id}/regenerate`),
};

// Group endpoints
export const groupsApi = {
  list: () => client.get<Group[]>('/api/groups/'),
  get: (id: number) => client.get<Group>(`/api/groups/${id}`),
  create: (data: GroupCreate) => client.post<Group>('/api/groups/', data),
  update: (id: number, data: GroupUpdate) => client.put<Group>(`/api/groups/${id}`, data),
  delete: (id: number) => client.delete(`/api/groups/${id}`),
  addUser: (groupId: number, userId: number) =>
    client.post(`/api/groups/${groupId}/users/${userId}`),
  removeUser: (groupId: number, userId: number) =>
    client.delete(`/api/groups/${groupId}/users/${userId}`),
};

// Provider endpoints
export const providersApi = {
  list: () => client.get<Provider[]>('/api/providers/'),
  get: (id: number) => client.get<Provider>(`/api/providers/${id}`),
  create: (data: ProviderCreate) => client.post<Provider>('/api/providers/', data),
  update: (id: number, data: Partial<ProviderCreate>) =>
    client.put<Provider>(`/api/providers/${id}`, data),
  delete: (id: number) => client.delete(`/api/providers/${id}`),
  addModel: (providerId: number, data: ModelCreate) =>
    client.post<Model>(`/api/providers/${providerId}/models`, data),
  updateModel: (providerId: number, modelId: number, data: Partial<ModelCreate>) =>
    client.put<Model>(`/api/providers/${providerId}/models/${modelId}`, data),
  deleteModel: (providerId: number, modelId: number) =>
    client.delete(`/api/providers/${providerId}/models/${modelId}`),
};

export default client;