export interface AvailableModel {
  name: string;
  alias: string | null;
  provider_name: string | null;
  rpm: number | null;
  tpm: number | null;
  input_price: number;
  output_price: number;
  currency: string;
  discount: number;
}

export interface ModelUsage {
  model_name: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  estimated_cost: number;
}

export interface BudgetInfo {
  unlimited_budget: boolean;
  budget: number | null;
  used: number;
  remaining: number | null;
}

export interface MyRoleResponse {
  group_id: number;
  user_id: number;
  role: string;
  permissions: Record<string, boolean>;
}

export interface BudgetRecord {
  id: number;
  api_key_id: number;
  amount: number;
  remaining: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface TimeSeries {
  period: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  total_cost: number;
  total_cost_usd?: number;
}

export interface TimeSeriesByModel {
  period: string;
  model_name: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  cache_creation_tokens: number;
  total_cost: number;
  total_cost_usd: number;
}

export interface ApiKeyPolicy {
  id: number;
  api_key_id: number;
  policy_type: string;
  enabled: boolean;
  config: Record<string, any>;
  created_at: string | null;
  updated_at: string | null;
}

export interface ApiKeyDetailData {
  id: number;
  key: string;
  name: string;
  group_id: number;
  user_id: number | null;
  user_name: string | null;
  is_active: boolean;
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  request_count: number;
  token_count: number;
  allowed_models: string[];
  budget: number | null;
  api_key_hash?: string;
  group: { id: number; name: string; description: string | null; created_at: string | null } | null;
  usage: {
    requests: number;
    input_tokens: number;
    output_tokens: number;
    reasoning_tokens: number;
    estimated_cost: number;
    ytd_cost?: number;
    mtd_cost?: number;
    ytd_input_tokens?: number;
    ytd_output_tokens?: number;
    ytd_reasoning_tokens?: number;
    mtd_input_tokens?: number;
    mtd_output_tokens?: number;
    mtd_reasoning_tokens?: number;
    total_image_count?: number;
    total_video_count?: number;
    total_audio_seconds?: number;
  };
  by_model: ModelUsage[];
  available_models: AvailableModel[];
  budget_info: BudgetInfo;
  budgets?: BudgetRecord[];
  total_budget_remaining?: number;
  policies?: ApiKeyPolicy[];
}