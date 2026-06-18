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
import { useTranslation } from 'react-i18next';
import { Eye, EyeOff, Loader2 } from 'lucide-react';
import { providersApi } from '../api/client';
import TagSelector from './TagSelector';

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
  tags: { name: string; value: string }[];
  extra_config: Record<string, any>;
}

interface Props {
  data: ProviderFormData;
  onChange: (updated: ProviderFormData) => void;
  groups?: Group[];
  providerId?: number;
}

export default function ProviderFormFields({ data, onChange, groups, providerId }: Props) {
  const { t } = useTranslation();
  const set = (partial: Partial<ProviderFormData>) => onChange({ ...data, ...partial });
  const setExtra = (partial: Record<string, any>) =>
    set({ extra_config: { ...data.extra_config, ...partial } });

  const [revealed, setRevealed] = useState(false);
  const [revealing, setRevealing] = useState(false);
  const [revealError, setRevealError] = useState<string | null>(null);

  const handleToggleReveal = async () => {
    if (revealed) {
      setRevealed(false);
      return;
    }
    if (providerId === undefined) return;
    setRevealError(null);
    setRevealing(true);
    try {
      const res = await providersApi.revealKey(providerId);
      set({ api_key: res.data.api_key });
      setRevealed(true);
    } catch (e: any) {
      setRevealError(e?.response?.data?.detail || e?.message || 'Failed to reveal');
    } finally {
      setRevealing(false);
    }
  };

  return (
    <>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Name */}
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">{t('provider.nameLabel')}</label>
          <input
            placeholder={t('provider.namePlaceholder')}
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            value={data.name}
            onChange={(e) => set({ name: e.target.value })}
          />
        </div>

        {/* Type */}
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">{t('provider.providerTypeLabel')}</label>
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
            <option value="byteplus">BytePlus (ByteDance Global)</option>
            <option value="gemini">Gemini (Google AI)</option>
            <option value="vertexai">Vertex AI (Google Cloud)</option>
            <option value="tencentvod">Tencent VOD</option>
            <option value="hunyuan">Hunyuan 3D (Tencent)</option>
            <option value="vllm">vLLM (self-hosted)</option>
            <option value="mulerun">Mulerun</option>
            <option value="openai_chatcompletions_compt">OpenAI ChatCompletions Compatible</option>
            <option value="openai_responses_compt">OpenAI Responses API Compatible</option>
          </select>
        </div>

        {/* Base URL */}
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">{t('provider.baseUrlLabel')}</label>
          <input
            placeholder={
              data.type === 'vertexai'
                ? 'https://{REGION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{REGION}'
                : data.type === 'azure'
                ? 'https://your-resource.openai.azure.com'
                : data.type === 'vllm'
                ? 'http://localhost:8000/v1'
                : data.type === 'mulerun'
                ? 'https://api.mulerun.com/vendors/openai/v1'
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
          {data.type === 'mulerun' && (
            <p className="text-xs text-slate-400 mt-1">
              Default: https://api.mulerun.com/vendors/openai/v1 — leave blank to use default.
            </p>
          )}
        </div>

        {/* API Key — hidden for tencentvod and hunyuan (uses AK/SK instead) */}
        {data.type !== 'tencentvod' && data.type !== 'hunyuan' && (
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-2">
              {data.type === 'vertexai' ? t('provider.serviceAccountJson') : t('provider.apiKeyLabel')}
            </label>
            {data.type === 'vertexai' ? (
              <textarea
                placeholder={t('provider.serviceAccountPlaceholder')}
                rows={4}
                className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all font-mono text-sm"
                value={data.api_key}
                onChange={(e) => set({ api_key: e.target.value })}
              />
            ) : (
              <div className="relative">
                <input
                  type={revealed ? 'text' : 'password'}
                  placeholder="sk-..."
                  className="w-full p-3 pr-12 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                  value={data.api_key}
                  onChange={(e) => set({ api_key: e.target.value })}
                />
                {providerId !== undefined && (
                  <button
                    type="button"
                    onClick={handleToggleReveal}
                    disabled={revealing}
                    title={revealed ? 'Hide' : 'Reveal full API key'}
                    className="absolute right-2 top-1/2 -translate-y-1/2 p-2 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-lg transition-colors disabled:opacity-50"
                  >
                    {revealing ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : revealed ? (
                      <EyeOff className="w-4 h-4" />
                    ) : (
                      <Eye className="w-4 h-4" />
                    )}
                  </button>
                )}
              </div>
            )}
            {revealError && (
              <p className="text-xs text-red-500 mt-1">{revealError}</p>
            )}
          </div>
        )}

        {/* Description */}
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">{t('provider.descriptionLabel')}</label>
          <input
            placeholder={t('provider.descriptionPlaceholder')}
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            value={data.description}
            onChange={(e) => set({ description: e.target.value })}
          />
        </div>

        {/* Group selector — only shown when groups are provided (ProviderList page) */}
        {groups !== undefined && (
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-2">{t('provider.groupLabel')}</label>
            <select
              className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
              value={data.group_id ?? 0}
              onChange={(e) => set({ group_id: parseInt(e.target.value) })}
            >
              <option value={0}>{t('provider.selectGroup')}</option>
              {groups.map((g) => (
                <option key={g.id} value={g.id}>{g.name}</option>
              ))}
            </select>
            {groups.length === 0 && (
              <p className="text-amber-600 text-sm mt-1">{t('provider.noGroupsAvailable')}</p>
            )}
          </div>
        )}

        {/* Authorization Header */}
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">
            {t('provider.authorizationHeader')}
            <span className="text-slate-400 font-normal ml-1 text-xs">{t('provider.authorizationHint')}</span>
          </label>
          <input
            placeholder={t('provider.authorizationPlaceholder')}
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            value={data.authorization || 'Authorization'}
            onChange={(e) => set({ authorization: e.target.value })}
          />
          <p className="text-xs text-slate-400 mt-1">
            {t('provider.authorizationHelp')}
          </p>
        </div>

        {/* Tags */}
        <div className="md:col-span-2">
          <label className="block text-sm font-medium text-slate-700 mb-2">
            {t('provider.tagsLabel')}
            <span className="text-slate-400 font-normal ml-1 text-xs">{t('provider.tagsHint')}</span>
          </label>
          <TagSelector
            value={data.tags || []}
            onChange={(tags) => set({ tags })}
          />
        </div>
      </div>

      {/* Azure-specific fields */}
      {data.type === 'azure' && (
        <div className="mt-4 p-4 bg-blue-50 border border-blue-200 rounded-xl">
          <h3 className="text-sm font-semibold text-blue-800 mb-3">{t('provider.azureConfig')}</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-2">{t('provider.azureApiVersion')}</label>
              <input
                placeholder="2025-01-01-preview"
                className="w-full p-3 bg-white border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                value={data.extra_config?.api_version || ''}
                onChange={(e) => setExtra({ api_version: e.target.value })}
              />
              <p className="text-xs text-slate-400 mt-1">
                {t('provider.azureApiVersionHelp')}
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-2">{t('provider.azureRegion')}</label>
              <input
                placeholder="eastus, westeurope, etc."
                className="w-full p-3 bg-white border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                value={data.extra_config?.region || ''}
                onChange={(e) => setExtra({ region: e.target.value })}
              />
              <p className="text-xs text-slate-400 mt-1">
                {t('provider.azureRegionHelp')}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* vLLM-specific info panel */}
      {data.type === 'vllm' && (
        <div className="mt-4 p-4 bg-violet-50 border border-violet-200 rounded-xl">
          <h3 className="text-sm font-semibold text-violet-800 mb-1">{t('provider.vllmConfig')}</h3>
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
                {t('provider.secretIdLabel')} <span className="text-red-500">*</span>
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
                {t('provider.secretKeyLabel')} <span className="text-red-500">*</span>
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
                {t('provider.regionLabel')}
                <span className="text-slate-400 font-normal ml-1 text-xs">{t('provider.regionOptional')}</span>
              </label>
              <input
                placeholder="ap-guangzhou"
                className="w-full p-3 bg-white border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 transition-all"
                value={data.extra_config?.region || ''}
                onChange={(e) => setExtra({ region: e.target.value })}
              />
              <p className="text-xs text-slate-400 mt-1">{t('provider.defaultApGuangzhou')}</p>
            </div>
          </div>
        </div>
      )}


      {/* Volcengine ARK Asset-specific fields */}
      {data.type === 'volcengine' && (
        <div className="mt-4 space-y-4">
          <div className="p-4 bg-purple-50 border border-purple-200 rounded-xl">
            <h3 className="text-sm font-semibold text-purple-800 mb-1">{t('provider.volcengineArkConfig')}</h3>
            <p className="text-xs text-purple-600 mb-3">{t('provider.volcengineArkDesc')}</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">
                  {t('provider.arkAccessKeyLabel')} <span className="text-red-500">*</span>
                </label>
                <input
                  placeholder={t('provider.arkAccessKeyPlaceholder')}
                  className="w-full p-3 bg-white border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 transition-all"
                  value={data.extra_config?.ark_access_key || ''}
                  onChange={(e) => setExtra({ ark_access_key: e.target.value })}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">
                  {t('provider.arkSecretKeyLabel')} <span className="text-red-500">*</span>
                </label>
                <input
                  type="password"
                  placeholder={t('provider.arkSecretKeyPlaceholder')}
                  className="w-full p-3 bg-white border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 transition-all"
                  value={data.extra_config?.ark_secret_key || ''}
                  onChange={(e) => setExtra({ ark_secret_key: e.target.value })}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">
                  {t('provider.arkRegionLabel')}
                  <span className="text-slate-400 font-normal ml-1 text-xs">{t('provider.regionOptional')}</span>
                </label>
                <input
                  placeholder="cn-beijing"
                  className="w-full p-3 bg-white border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 transition-all"
                  value={data.extra_config?.ark_region || ''}
                  onChange={(e) => setExtra({ ark_region: e.target.value })}
                />
                <p className="text-xs text-slate-400 mt-1">{t('provider.arkRegionHelp')}</p>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">
                  {t('provider.arkGroupIdLabel')}
                </label>
                <input
                  placeholder={t('provider.arkGroupIdPlaceholder')}
                  className="w-full p-3 bg-white border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 transition-all"
                  value={data.extra_config?.ark_group_id || ''}
                  onChange={(e) => setExtra({ ark_group_id: e.target.value })}
                />
                <p className="text-xs text-slate-400 mt-1">{t('provider.arkGroupIdHelp')}</p>
              </div>
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
                  {t('provider.secretIdLabel')} <span className="text-red-500">*</span>
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
                  {t('provider.secretKeyLabel')} <span className="text-red-500">*</span>
                </label>
                <input
                  type="password"
                  placeholder={t('provider.secretKeyPlaceholder')}
                  className="w-full p-3 bg-white border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20 transition-all"
                  value={data.extra_config?.secret_key || ''}
                  onChange={(e) => setExtra({ secret_key: e.target.value })}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">
                  {t('provider.appIdLabel')}
                  <span className="text-slate-400 font-normal ml-1 text-xs">{t('provider.regionOptional')}</span>
                </label>
                <input
                  placeholder={t('provider.appIdPlaceholder')}
                  className="w-full p-3 bg-white border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20 transition-all"
                  value={data.extra_config?.app_id || ''}
                  onChange={(e) => setExtra({ app_id: e.target.value })}
                />
                <p className="text-xs text-slate-400 mt-1">{t('provider.appIdHelp')}</p>
              </div>
            </div>
          </div>

        </div>
      )}
    </>
  );
}
