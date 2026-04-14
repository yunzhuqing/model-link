/**
 * Shared provider form fields used by both ProviderList and GroupDetail pages.
 *
 * Props
 * ─────
 * data          – current provider state (new or editing)
 * onChange      – called whenever a field changes; receives the full updated object
 * groups        – if provided, renders a "Group" selector (used by ProviderList)
 */
import { useState } from 'react';

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

// ---------------------------------------------------------------------------
// Gemini image model size reference table (shown inside TencentVOD config)
// ---------------------------------------------------------------------------

const GG25_SIZES = [
  { ar: '1:1',  wh: '1024x1024' },
  { ar: '2:3',  wh: '832x1248'  },
  { ar: '3:2',  wh: '1248x832'  },
  { ar: '3:4',  wh: '864x1184'  },
  { ar: '4:3',  wh: '1184x864'  },
  { ar: '4:5',  wh: '896x1152'  },
  { ar: '5:4',  wh: '1152x896'  },
  { ar: '9:16', wh: '768x1344'  },
  { ar: '16:9', wh: '1344x768'  },
  { ar: '21:9', wh: '1536x672'  },
];

const GG30_SIZES = [
  { ar: '1:1',  k1: '1024x1024', k2: '2048x2048', k4: '4096x4096' },
  { ar: '2:3',  k1: '848x1264',  k2: '1696x2528', k4: '3392x5056' },
  { ar: '3:2',  k1: '1264x848',  k2: '2528x1696', k4: '5056x3392' },
  { ar: '3:4',  k1: '896x1200',  k2: '1792x2400', k4: '3584x4800' },
  { ar: '4:3',  k1: '1200x896',  k2: '2400x1792', k4: '4800x3584' },
  { ar: '4:5',  k1: '928x1152',  k2: '1856x2304', k4: '3712x4608' },
  { ar: '5:4',  k1: '1152x928',  k2: '2304x1856', k4: '4608x3712' },
  { ar: '9:16', k1: '768x1376',  k2: '1536x2752', k4: '3072x5504' },
  { ar: '16:9', k1: '1376x768',  k2: '2752x1536', k4: '5504x3072' },
  { ar: '21:9', k1: '1584x672',  k2: '3168x1344', k4: '6336x2688' },
];

const GG31_SIZES = [
  { ar: '1:1',  s512: '512x512',   k1: '1024x1024',  k2: '2048x2048',  k4: '4096x4096'  },
  { ar: '1:4',  s512: '256x1024',  k1: '512x2048',   k2: '1024x4096',  k4: '2048x8192'  },
  { ar: '1:8',  s512: '192x1536',  k1: '384x3072',   k2: '768x6144',   k4: '1536x12288' },
  { ar: '2:3',  s512: '424x632',   k1: '848x1264',   k2: '1696x2528',  k4: '3392x5056'  },
  { ar: '3:2',  s512: '632x424',   k1: '1264x848',   k2: '2528x1696',  k4: '5056x3392'  },
  { ar: '3:4',  s512: '448x600',   k1: '896x1200',   k2: '1792x2400',  k4: '3584x4800'  },
  { ar: '4:1',  s512: '1024x256',  k1: '2048x512',   k2: '4096x1024',  k4: '8192x2048'  },
  { ar: '4:3',  s512: '600x448',   k1: '1200x896',   k2: '2400x1792',  k4: '4800x3584'  },
  { ar: '4:5',  s512: '464x576',   k1: '928x1152',   k2: '1856x2304',  k4: '3712x4608'  },
  { ar: '5:4',  s512: '576x464',   k1: '1152x928',   k2: '2304x1856',  k4: '4608x3712'  },
  { ar: '8:1',  s512: '1536x192',  k1: '3072x384',   k2: '6144x768',   k4: '12288x1536' },
  { ar: '9:16', s512: '384x688',   k1: '768x1376',   k2: '1536x2752',  k4: '3072x5504'  },
  { ar: '16:9', s512: '688x384',   k1: '1376x768',   k2: '2752x1536',  k4: '5504x3072'  },
  { ar: '21:9', s512: '792x168',   k1: '1584x672',   k2: '3168x1344',  k4: '6336x2688'  },
];

const GEMINI_IMAGE_MODELS = [
  {
    id: 'gemini-2.5-flash-image',
    label: 'Gemini 2.5 Flash Image',
    description: 'Single resolution per aspect ratio. Pass size as "WxH" (e.g. "1024x1024") or aspect ratio (e.g. "16:9").',
    tier: 'none' as const,
  },
  {
    id: 'gemini-3-pro-image-preview',
    label: 'Gemini 3 Pro Image Preview',
    description: 'Three quality tiers: 1K / 2K / 4K. Pass size as "WxH", aspect ratio, or tier label (e.g. "2K").',
    tier: '3tier' as const,
  },
  {
    id: 'gemini-3.1-flash-image-preview',
    label: 'Gemini 3.1 Flash Image Preview',
    description: 'Four quality tiers: 512 / 1K / 2K / 4K. Pass size as "WxH", aspect ratio, or tier label.',
    tier: '4tier' as const,
  },
];

function TencentVODGeminiImageGuide() {
  const [activeModel, setActiveModel] = useState<string>('gemini-2.5-flash-image');

  const thCls = 'px-3 py-2 text-left text-xs font-semibold text-slate-500 bg-slate-50 border-b border-slate-200';
  const tdCls = 'px-3 py-1.5 text-xs text-slate-700 border-b border-slate-100 font-mono';
  const arCls = 'px-3 py-1.5 text-xs font-medium text-slate-600 border-b border-slate-100';

  return (
    <div className="p-4 bg-slate-50 border border-slate-200 rounded-xl">
      <h3 className="text-sm font-semibold text-slate-700 mb-1">Gemini Image Models via TencentVOD</h3>
      <p className="text-xs text-slate-500 mb-3">
        The following Gemini image models are routed through TencentVOD's CreateAigcImageTask API.
        Use the model name below as the model identifier. Specify image size via the{' '}
        <code className="bg-slate-200 px-1 rounded font-mono">size</code> parameter in your request
        (accepts WxH, aspect ratio like "16:9", or a tier label like "2K").
      </p>

      {/* Model tabs */}
      <div className="flex gap-1 mb-3 flex-wrap">
        {GEMINI_IMAGE_MODELS.map((m) => (
          <button
            key={m.id}
            onClick={() => setActiveModel(m.id)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              activeModel === m.id
                ? 'bg-teal-600 text-white'
                : 'bg-white border border-slate-200 text-slate-600 hover:bg-teal-50 hover:border-teal-300'
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>

      {/* Active model info */}
      {(() => {
        const model = GEMINI_IMAGE_MODELS.find((m) => m.id === activeModel)!;
        return (
          <>
            <div className="mb-3 flex items-start gap-2">
              <code className="bg-slate-200 text-slate-800 px-2 py-0.5 rounded font-mono text-xs shrink-0">
                {model.id}
              </code>
              <p className="text-xs text-slate-500">{model.description}</p>
            </div>

            {/* Size table */}
            <div className="overflow-x-auto rounded-lg border border-slate-200">
              {activeModel === 'gemini-2.5-flash-image' && (
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr>
                      <th className={thCls}>Aspect Ratio</th>
                      <th className={thCls}>Resolution (WxH)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {GG25_SIZES.map((r) => (
                      <tr key={r.ar} className="hover:bg-slate-50">
                        <td className={arCls}>{r.ar}</td>
                        <td className={tdCls}>{r.wh}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {activeModel === 'gemini-3-pro-image-preview' && (
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr>
                      <th className={thCls}>Aspect Ratio</th>
                      <th className={thCls}>1K</th>
                      <th className={thCls}>2K</th>
                      <th className={thCls}>4K</th>
                    </tr>
                  </thead>
                  <tbody>
                    {GG30_SIZES.map((r) => (
                      <tr key={r.ar} className="hover:bg-slate-50">
                        <td className={arCls}>{r.ar}</td>
                        <td className={tdCls}>{r.k1}</td>
                        <td className={tdCls}>{r.k2}</td>
                        <td className={tdCls}>{r.k4}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {activeModel === 'gemini-3.1-flash-image-preview' && (
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr>
                      <th className={thCls}>Aspect Ratio</th>
                      <th className={thCls}>512</th>
                      <th className={thCls}>1K</th>
                      <th className={thCls}>2K</th>
                      <th className={thCls}>4K</th>
                    </tr>
                  </thead>
                  <tbody>
                    {GG31_SIZES.map((r) => (
                      <tr key={r.ar} className="hover:bg-slate-50">
                        <td className={arCls}>{r.ar}</td>
                        <td className={tdCls}>{r.s512}</td>
                        <td className={tdCls}>{r.k1}</td>
                        <td className={tdCls}>{r.k2}</td>
                        <td className={tdCls}>{r.k4}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </>
        );
      })()}
    </div>
  );
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
            <option value="hunyuan">Hunyuan 3D (Tencent)</option>
            <option value="vllm">vLLM (self-hosted)</option>
            <option value="openai_chatcompletions_compt">OpenAI ChatCompletions Compatible</option>
            <option value="openai_responses_compt">OpenAI Responses API Compatible</option>
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
                : data.type === 'vllm'
                ? 'http://localhost:8000/v1'
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
          {data.type === 'hunyuan' && (
            <p className="text-xs text-slate-400 mt-1">
              Leave blank to use the default Hunyuan 3D API endpoint.
            </p>
          )}
          {data.type === 'vllm' && (
            <p className="text-xs text-slate-400 mt-1">
              Default: http://localhost:8000/v1 — set to your vLLM server address.
            </p>
          )}
        </div>

        {/* API Key — hidden for tencentvod and hunyuan (uses AK/SK instead) */}
        {data.type !== 'tencentvod' && data.type !== 'hunyuan' && (
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

      {/* vLLM-specific info panel */}
      {data.type === 'vllm' && (
        <div className="mt-4 p-4 bg-violet-50 border border-violet-200 rounded-xl">
          <h3 className="text-sm font-semibold text-violet-800 mb-1">vLLM Configuration</h3>
          <p className="text-xs text-violet-700 mb-0">
            vLLM exposes an OpenAI-compatible <code className="font-mono bg-violet-100 px-1 rounded">/v1/chat/completions</code> endpoint.
            Set <strong>Base URL</strong> to your vLLM server (e.g. <code className="font-mono bg-violet-100 px-1 rounded">http://&lt;host&gt;:8000/v1</code>).
            <br />
            <strong>API Key</strong> is optional — leave it blank if your vLLM deployment does not require authentication.
          </p>
        </div>
      )}

      {/* OpenAI ChatCompletions Compatible info panel */}
      {data.type === 'openai_chatcompletions_compt' && (
        <div className="mt-4 p-4 bg-emerald-50 border border-emerald-200 rounded-xl">
          <h3 className="text-sm font-semibold text-emerald-800 mb-1">OpenAI ChatCompletions Compatible</h3>
          <p className="text-xs text-emerald-700 mb-0">
            Use this provider type for any service that exposes an OpenAI-compatible{' '}
            <code className="font-mono bg-emerald-100 px-1 rounded">/v1/chat/completions</code> endpoint.
            <br />
            Typical examples: FastChat, LiteLLM, text-generation-webui, and most domestic cloud LLM services.
            <br />
            Set <strong>Base URL</strong> to the service address (e.g.{' '}
            <code className="font-mono bg-emerald-100 px-1 rounded">http://192.168.1.100:8080/v1</code>).
            <br />
            <strong>API Key</strong> is optional — leave it blank if authentication is not required.
          </p>
        </div>
      )}

      {/* OpenAI Responses API Compatible info panel */}
      {data.type === 'openai_responses_compt' && (
        <div className="mt-4 p-4 bg-sky-50 border border-sky-200 rounded-xl">
          <h3 className="text-sm font-semibold text-sky-800 mb-1">OpenAI Responses API Compatible</h3>
          <p className="text-xs text-sky-700 mb-0">
            Use this provider type for services that implement the OpenAI{' '}
            <code className="font-mono bg-sky-100 px-1 rounded">/v1/responses</code> API format.
            <br />
            Key differences from Chat Completions: uses <code className="font-mono bg-sky-100 px-1 rounded">input</code> instead of{' '}
            <code className="font-mono bg-sky-100 px-1 rounded">messages</code>,{' '}
            <code className="font-mono bg-sky-100 px-1 rounded">instructions</code> for system prompts,{' '}
            <code className="font-mono bg-sky-100 px-1 rounded">max_output_tokens</code> instead of{' '}
            <code className="font-mono bg-sky-100 px-1 rounded">max_tokens</code>, and{' '}
            <code className="font-mono bg-sky-100 px-1 rounded">output</code> in the response body.
            <br />
            Set <strong>Base URL</strong> to the service address (e.g.{' '}
            <code className="font-mono bg-sky-100 px-1 rounded">https://api.openai.com/v1</code>).
            <br />
            <strong>API Key</strong> is optional — leave it blank if authentication is not required.
          </p>
        </div>
      )}

      {/* Hunyuan 3D-specific fields */}
      {data.type === 'hunyuan' && (
        <div className="mt-4 p-4 bg-purple-50 border border-purple-200 rounded-xl">
          <h3 className="text-sm font-semibold text-purple-800 mb-1">Hunyuan 3D Credentials</h3>
          <p className="text-xs text-purple-600 mb-3">
            Enter your Tencent Cloud SecretId &amp; SecretKey to use the Hunyuan 3D generation API
            (<code className="bg-purple-100 px-1 rounded font-mono">hunyuan-3d-rapid</code> / <code className="bg-purple-100 px-1 rounded font-mono">hunyuan-3d-pro</code>).
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-2">
                Secret ID (AK) <span className="text-red-500">*</span>
              </label>
              <input
                placeholder="AKIDxxxxxxxxxxxxxxxx"
                className="w-full p-3 bg-white border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 transition-all"
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
                className="w-full p-3 bg-white border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 transition-all"
                value={data.extra_config?.secret_key || ''}
                onChange={(e) => setExtra({ secret_key: e.target.value })}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-2">
                Region
                <span className="text-slate-400 font-normal ml-1 text-xs">(optional)</span>
              </label>
              <input
                placeholder="ap-guangzhou"
                className="w-full p-3 bg-white border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 transition-all"
                value={data.extra_config?.region || ''}
                onChange={(e) => setExtra({ region: e.target.value })}
              />
              <p className="text-xs text-slate-400 mt-1">Default: ap-guangzhou</p>
            </div>
          </div>
        </div>
      )}

      {/* TencentVOD-specific fields */}
      {data.type === 'tencentvod' && (
        <div className="mt-4 space-y-4">
          {/* Credentials */}
          <div className="p-4 bg-teal-50 border border-teal-200 rounded-xl">
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

          {/* Gemini Image Models Reference */}
          <TencentVODGeminiImageGuide />
        </div>
      )}
    </>
  );
}
