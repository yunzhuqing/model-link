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

// Response interceptor: on 401, clear token and redirect to login
client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token');
      // Only redirect if we're not already on the login page
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

// Types
export interface ApiKey {
  id: number;
  key: string;
  name: string;
  description: string | null;
  group_id: number | null;
  group_name?: string;
  user_id?: number | null;
  user_name?: string | null;
  is_active: boolean;
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  request_count: number;
  token_count: number;
  allowed_models: string[];
  tags?: { name: string; value: string }[];
  group?: { id: number; name: string; description: string | null; created_at: string | null };
}

export interface ApiKeyCreate {
  name: string;
  description: string;
  group_id?: number;
  expires_at?: string;
  allowed_models?: string[];
  tags?: { name: string; value: string }[];
}

export interface ApiKeyUpdate {
  name?: string;
  description?: string;
  is_active?: boolean;
  expires_at?: string;
  allowed_models?: string[];
  tags?: { name: string; value: string }[];
}

export interface ApiKeyModelsResponse {
  allowed_models: string[];
  models: Array<{
    name: string;
    alias: string | null;
    provider_name: string | null;
    requests: number;
    input_tokens: number;
    output_tokens: number;
    reasoning_tokens: number;
  }>;
}

export interface MonitoringConfig {
  type: string;
  endpoint?: string;
  region?: string;
  public_key?: string;
  secret_key?: string;
}

export interface Group {
  id: number;
  name: string;
  description: string | null;
  workspace_id?: number | null;
  monitoring_config?: MonitoringConfig[] | null;
  created_at: string;
  user_count?: number;
  api_key_count?: number;
  users?: Array<{ id: number; username: string; email: string }>;
  tags?: { name: string; value: string }[];
  api_keys?: Array<{ id: number; name: string; is_active: boolean }>;
  providers?: Array<{ id: number; name: string; type: string }>;
}

export interface GroupCreate {
  name: string;
  description?: string;
  workspace_id?: number | null;
}

export interface GroupUpdate {
  name?: string;
  description?: string;
  workspace_id?: number | null;
  monitoring_config?: MonitoringConfig[] | null;
  tags?: { name: string; value: string }[];
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
  cache_5m_creation_price: number | null;
  cache_1h_creation_price: number | null;
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
  tags?: { name: string; value: string }[];
}

export interface Tag {
  id: number;
  name: string;
  value: string;
  description: string;
  created_at: string | null;
  updated_at: string | null;
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
  cache_5m_creation_price?: number;
  cache_1h_creation_price?: number;
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
  list: () => client.get<ApiKey[]>('/api/apikeys/'),
  get: (id: number) => client.get<ApiKey>(`/api/apikeys/${id}`),
  create: (data: ApiKeyCreate) => client.post<ApiKey>('/api/apikeys/', data),
  update: (id: number, data: ApiKeyUpdate) => client.put<ApiKey>(`/api/apikeys/${id}`, data),
  delete: (id: number) => client.delete(`/api/apikeys/${id}`),
  regenerate: (id: number) => client.post<ApiKey>(`/api/apikeys/${id}/regenerate`),
  getModels: (id: number) => client.get<ApiKeyModelsResponse>(`/api/apikeys/${id}/models`),
  // Policy endpoints
  listPolicies: (apiKeyId: number) => client.get(`/api/apikeys/${apiKeyId}/policies`),
  upsertPolicy: (apiKeyId: number, policyType: string, data: { enabled?: boolean; config?: Record<string, any> }) =>
    client.put(`/api/apikeys/${apiKeyId}/policies/${policyType}`, data),
  deletePolicy: (apiKeyId: number, policyType: string) =>
    client.delete(`/api/apikeys/${apiKeyId}/policies/${policyType}`),
};

// Group endpoints
export const groupsApi = {
  list: (search?: string) => client.get<Group[]>('/api/groups/', { params: search ? { search } : undefined }),
  get: (id: number) => client.get<Group>(`/api/groups/${id}`),
  create: (data: GroupCreate) => client.post<Group>('/api/groups/', data),
  update: (id: number, data: GroupUpdate) => client.put<Group>(`/api/groups/${id}`, data),
  delete: (id: number) => client.delete(`/api/groups/${id}`),
  addUser: (groupId: number, userId: number) =>
    client.post(`/api/groups/${groupId}/users/${userId}`),
  removeUser: (groupId: number, userId: number) =>
    client.delete(`/api/groups/${groupId}/users/${userId}`),
};

export interface MyPermissions {
  role: string | null;
  permissions: Record<string, boolean>;
}

// Permission endpoints
export const permissionsApi = {
  myPermissions: () => client.get<MyPermissions>('/api/permissions/my-permissions'),
};

// Provider endpoints
export const providersApi = {
  list: () => client.get<Provider[]>('/api/providers/'),
  get: (id: number) => client.get<Provider>(`/api/providers/${id}`),
  create: (data: ProviderCreate) => client.post<Provider>('/api/providers/', data),
  update: (id: number, data: Partial<ProviderCreate>) =>
    client.put<Provider>(`/api/providers/${id}`, data),
  revealKey: (id: number) =>
    client.get<{ api_key: string }>(`/api/providers/${id}/reveal-key`),
  delete: (id: number) => client.delete(`/api/providers/${id}`),
  addModel: (providerId: number, data: ModelCreate) =>
    client.post<Model>(`/api/providers/${providerId}/models`, data),
  updateModel: (providerId: number, modelId: number, data: Partial<ModelCreate>) =>
    client.put<Model>(`/api/providers/${providerId}/models/${modelId}`, data),
  deleteModel: (providerId: number, modelId: number) =>
    client.delete(`/api/providers/${providerId}/models/${modelId}`),
};

// Tag endpoints
export const tagsApi = {
  list: () => client.get<Tag[]>('/api/tags/'),
  create: (data: { name: string; value: string; description?: string }) =>
    client.post<Tag>('/api/tags/', data),
  update: (id: number, data: { name: string; value: string; description?: string }) =>
    client.put<Tag>(`/api/tags/${id}`, data),
  delete: (id: number) => client.delete(`/api/tags/${id}`),
};

// Rate limit status endpoints
export interface RateLimitApiKeyUsage {
  preview: string;
  rpm_used: number;
  tpm_used: number;
  api_key_name?: string | null;
  group_name?: string | null;
}

export interface RateLimitStatus {
  model_id?: number;
  model_name?: string;
  alias?: string;
  provider_id?: number;
  provider_name?: string;
  group_id?: number;
  rpm_limit?: number | null;
  tpm_limit?: number | null;
  rpm_remaining?: number | null;
  tpm_remaining?: number | null;
  rpm_used?: number;
  tpm_used?: number;
  rpm_pct?: number;
  tpm_pct?: number;
  apikeys?: RateLimitApiKeyUsage[];
}

export interface WorkspaceRateLimitConfig {
  id: number;
  workspace_id: number;
  model_name: string;
  provider_type: string;
  provider_id: number | null;
  provider_name: string | null;
  rpm: number | null;
  tpm: number | null;
  created_at?: string;
  updated_at?: string;
}

export interface WorkspaceRateLimitHistory {
  rpm_1m: number;
  rpm_5m: number;
  rpm_10m: number;
  tpm_1m: number;
  tpm_5m: number;
  tpm_10m: number;
}

export interface WorkspaceProviderBreakdown {
  provider_name: string | null;
  provider_type: string | null;
  provider_id: number | null;
  group_name: string | null;
  model_id: number;
  rpm_limit: number | null;
  tpm_limit: number | null;
  rpm_used: number;
  tpm_used: number;
}

export interface WorkspaceRateLimitStatus {
  id?: number;
  workspace_id: number;
  workspace_name: string;
  model_name: string;
  provider_type?: string;
  provider_id?: number | null;
  provider_name?: string | null;
  rpm_limit: number | null;
  tpm_limit: number | null;
  rpm: { limit: number | null; remaining: number | null; used: number };
  tpm: { limit: number | null; remaining: number | null; used: number };
  apikeys: RateLimitApiKeyUsage[];
  history?: WorkspaceRateLimitHistory;
  providers?: WorkspaceProviderBreakdown[];
}

export const rateLimitsApi = {
  // Group-level rate limits
  getAll: () => client.get<{ models: RateLimitStatus[] }>('/api/providers/rate-limits'),
  getModel: (modelId: number) => client.get<RateLimitStatus>(`/api/providers/rate-limits/${modelId}`),

  // Workspace-level rate limits
  getWorkspaceLimits: (workspaceId: number) =>
    client.get<{ workspace: { id: number; name: string }; rate_limits: WorkspaceRateLimitStatus[] }>(
      `/api/workspaces/${workspaceId}/rate-limits`
    ),
  createWorkspaceLimit: (workspaceId: number, data: { model_name: string; provider_type: string; provider_id?: number | null; rpm?: number | null; tpm?: number | null }) =>
    client.post<WorkspaceRateLimitConfig>(`/api/workspaces/${workspaceId}/rate-limits`, data),
  updateWorkspaceLimit: (workspaceId: number, limitId: number, data: { rpm?: number | null; tpm?: number | null; model_name?: string; provider_type?: string; provider_id?: number | null }) =>
    client.put<WorkspaceRateLimitConfig>(`/api/workspaces/${workspaceId}/rate-limits/${limitId}`, data),
  deleteWorkspaceLimit: (workspaceId: number, limitId: number) =>
    client.delete(`/api/workspaces/${workspaceId}/rate-limits/${limitId}`),
  getWorkspaceStatus: (workspaceId: number, modelName: string) =>
    client.get<WorkspaceRateLimitStatus>(`/api/workspaces/${workspaceId}/rate-limits/status?model_name=${encodeURIComponent(modelName)}`),
};

export default client;
