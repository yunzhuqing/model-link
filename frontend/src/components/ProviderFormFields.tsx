/**
 * Shared provider form fields used by both ProviderList and GroupDetail pages.
 *
 * Props
 * ─────
 * data          – current provider state (new or editing)
 * onChange      – called whenever a field changes; receives the full updated object
 * groups        – if provided, renders a "Group" selector (used by ProviderList)
 */

interface Group {
  id: number;
  name: string;
  description: string;
}

export interface ProviderFormData {
  name: string;
  type: string;
  description: string;
  base_url: string;
  api_key: string;
  group_id?: number;
  authorization: string;
  tags: string[];
  extra_config: Record<string, any>;
}

interface Props {
  data: ProviderFormData;
  onChange: (updated: ProviderFormData) => void;
  groups?: Group[];
}

export default function ProviderFormFields({ data, onChange, groups }: Props) {
  const set = (partial: Partial<ProviderFormData>) => onChange({ ...data, ...partial });
  const setExtra = (partial: Record<string, any>) =>
    set({ extra_config: { ...data.extra_config, ...partial } });

  return (
    <>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Name */}
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">Name *</label>
          <input
            placeholder="Provider name"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            value={data.name}
            onChange={(e) => set({ name: e.target.value })}
          />
        </div>

        {/* Type */}
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">Provider Type *</label>
          <select
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            value={data.type}
            onChange={(e) => set({ type: e.target.value })}
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

        {/* Base URL */}
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">Base URL</label>
          <input
            placeholder={
              data.type === 'vertexai'
                ? 'https://{REGION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{REGION}'
                : data.type === 'azure'
                ? 'https://your-resource.openai.azure.com'
                : 'https://api.example.com'
            }
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            value={data.base_url}
            onChange={(e) => set({ base_url: e.target.value })}
          />
          {data.type === 'vertexai' && (
            <p className="text-xs text-slate-400 mt-1">
              Format: https://REGION-aiplatform.googleapis.com/v1/projects/PROJECT_ID/locations/REGION
            </p>
          )}
          {data.type === 'azure' && (
            <p className="text-xs text-slate-400 mt-1">
              Format: https://&#123;resource-name&#125;.openai.azure.com
            </p>
          )}
          {data.type === 'tencentvod' && (
            <p className="text-xs text-slate-400 mt-1">
              Default: https://text-aigc.vod-qcloud.com/v1 (leave blank to use default)
            </p>
          )}
        </div>

        {/* API Key — hidden for tencentvod (uses AK/SK instead) */}
        {data.type !== 'tencentvod' && (
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-2">
              {data.type === 'vertexai' ? 'Service Account JSON' : 'API Key'}
            </label>
            {data.type === 'vertexai' ? (
              <textarea
                placeholder="Paste the full JSON content of your Google Cloud service account key file, or leave empty to use Application Default Credentials (ADC)"
                rows={4}
                className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all font-mono text-sm"
                value={data.api_key}
                onChange={(e) => set({ api_key: e.target.value })}
              />
            ) : (
              <input
                type="password"
                placeholder="sk-..."
                className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                value={data.api_key}
                onChange={(e) => set({ api_key: e.target.value })}
              />
            )}
          </div>
        )}

        {/* Description */}
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">Description</label>
          <input
            placeholder="Description"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            value={data.description}
            onChange={(e) => set({ description: e.target.value })}
          />
        </div>

        {/* Group selector — only shown when groups are provided (ProviderList page) */}
        {groups !== undefined && (
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-2">Group *</label>
            <select
              className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
              value={data.group_id ?? 0}
              onChange={(e) => set({ group_id: parseInt(e.target.value) })}
            >
              <option value={0}>Select a group</option>
              {groups.map((g) => (
                <option key={g.id} value={g.id}>{g.name}</option>
              ))}
            </select>
            {groups.length === 0 && (
              <p className="text-amber-600 text-sm mt-1">No groups available. Please create a group first.</p>
            )}
          </div>
        )}

        {/* Authorization Header */}
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">
            Authorization Header
            <span className="text-slate-400 font-normal ml-1 text-xs">(custom header name for API key)</span>
          </label>
          <input
            placeholder="Authorization (default) or x-goog-api-key for Gemini"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            value={data.authorization || 'Authorization'}
            onChange={(e) => set({ authorization: e.target.value })}
          />
          <p className="text-xs text-slate-400 mt-1">
            Use "Authorization" for Bearer token (default), or "x-goog-api-key" for Gemini API.
          </p>
        </div>

        {/* Tags */}
        <div className="md:col-span-2">
          <label className="block text-sm font-medium text-slate-700 mb-2">
            Tags
            <span className="text-slate-400 font-normal ml-1 text-xs">(comma-separated, for billing usage binding)</span>
          </label>
          <input
            placeholder="Comma-separated tags (e.g. production, team-a)"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            value={(data.tags || []).join(', ')}
            onChange={(e) => {
              const tags = e.target.value.split(',').map((t) => t.trim()).filter(Boolean);
              set({ tags });
            }}
            onBlur={(e) => {
              const tags = e.target.value.split(',').map((t) => t.trim()).filter(Boolean);
              set({ tags });
            }}
          />
          <p className="text-xs text-slate-400 mt-1">
            Comma-separated tags for billing usage binding (e.g. production, team-a, internal)
          </p>
        </div>
      </div>

      {/* Azure-specific fields */}
      {data.type === 'azure' && (
        <div className="mt-4 p-4 bg-blue-50 border border-blue-200 rounded-xl">
          <h3 className="text-sm font-semibold text-blue-800 mb-3">Azure OpenAI Configuration</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-2">API Version</label>
              <input
                placeholder="2025-01-01-preview"
                className="w-full p-3 bg-white border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                value={data.extra_config?.api_version || ''}
                onChange={(e) => setExtra({ api_version: e.target.value })}
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
                value={data.extra_config?.region || ''}
                onChange={(e) => setExtra({ region: e.target.value })}
              />
              <p className="text-xs text-slate-400 mt-1">
                The Azure region where your resource is deployed (e.g., eastus, westeurope).
              </p>
            </div>
          </div>
        </div>
      )}

      {/* TencentVOD-specific fields */}
      {data.type === 'tencentvod' && (
        <div className="mt-4 p-4 bg-teal-50 border border-teal-200 rounded-xl">
          <h3 className="text-sm font-semibold text-teal-800 mb-1">Tencent VOD Credentials</h3>
          <p className="text-xs text-teal-600 mb-3">
            Enter your Tencent Cloud SecretId &amp; SecretKey. An AI API Token will be created automatically
            and used for chat requests. For image generation the SecretId/SecretKey are used directly.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-2">
                Secret ID (AK) <span className="text-red-500">*</span>
              </label>
              <input
                placeholder="AKIDxxxxxxxxxxxxxxxx"
                className="w-full p-3 bg-white border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20 transition-all"
                value={data.extra_config?.secret_id || ''}
                onChange={(e) => setExtra({ secret_id: e.target.value })}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-2">
                Secret Key (SK) <span className="text-red-500">*</span>
              </label>
              <input
                type="password"
                placeholder="Your Tencent Cloud SecretKey"
                className="w-full p-3 bg-white border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20 transition-all"
                value={data.extra_config?.secret_key || ''}
                onChange={(e) => setExtra({ secret_key: e.target.value })}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-2">
                App ID (Sub-App)
                <span className="text-slate-400 font-normal ml-1 text-xs">(optional)</span>
              </label>
              <input
                placeholder="VOD sub-application ID"
                className="w-full p-3 bg-white border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20 transition-all"
                value={data.extra_config?.app_id || ''}
                onChange={(e) => setExtra({ app_id: e.target.value })}
              />
              <p className="text-xs text-slate-400 mt-1">Leave blank to use the main application.</p>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
