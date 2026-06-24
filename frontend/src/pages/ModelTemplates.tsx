import { useState, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import client from '../api/client';
import { Plus, Edit2, Trash2, Save, LayoutTemplate, Search, X, RefreshCw } from 'lucide-react';
import NumberInput, { fmtNumber } from '../components/NumberInput';

function currencySymbol(currency: string): string {
  if (currency === 'CNY') return '¥';
  if (currency === 'EUR') return '€';
  if (currency === 'GBP') return '£';
  if (currency === 'JPY') return '¥';
  return '$';
}

interface PricingTier {
  label: string;
  context_size: number;
  input_size: number;
  output_size: number;
  input_price: number;
  output_price: number;
  cache_creation_price: number;
  cache_5m_creation_price: number;
  cache_1h_creation_price: number;
  cache_hit_price: number;
}

interface OutputPricingTier {
  resolution: string;
  quality?: string;
  audio?: boolean;
  reference_video?: boolean;
  price: number;
}

interface OutputPricingCategory {
  type: string;
  price: number;
  tiers?: OutputPricingTier[];
  credits?: Record<string, any>;
}

interface OutputPricing {
  image?: OutputPricingCategory;
  video?: OutputPricingCategory;
  audio?: OutputPricingCategory;
  '3d'?: OutputPricingCategory;
}

interface ModelTemplate {
  id: number;
  label: string;
  provider: string;
  name: string;
  alias: string | null;
  context_size: number;
  input_size: number;
  output_size: number;
  reasoning_effort: string | null;
  supported_image_formats: string | null;
  pricing_tiers: PricingTier[] | null;
  output_pricing: OutputPricing | null;
  input_price: number;
  output_price: number;
  cache_creation_price: number;
  cache_5m_creation_price: number;
  cache_1h_creation_price: number;
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
  api_type: string | null;
}

const emptyTemplate = (): Omit<ModelTemplate, 'id'> => ({
  label: '',
  provider: '',
  name: '',
  alias: '',
  context_size: 4096,
  input_size: 4096,
  output_size: 4096,
  reasoning_effort: '',
  supported_image_formats: '',
  pricing_tiers: null,
  output_pricing: null,
  input_price: 0,
  output_price: 0,
  cache_creation_price: 0,
  cache_5m_creation_price: 0,
  cache_1h_creation_price: 0,
  cache_hit_price: 0,
  currency: 'USD',
  retirement_time: null,
  is_retired: false,
  rpm: null,
  tpm: null,
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
  api_type: '',
});

const FEATURES_KEYS = [
  'support_kvcache',
  'support_image',
  'support_audio',
  'support_video',
  'support_file',
  'support_web_search',
  'support_tool_search',
  'support_thinking',
  'support_online_image',
  'support_online_video',
  'support_embedding',
] as const;

const FEATURE_I18N_MAP: Record<string, string> = {
  support_kvcache: 'kvcache',
  support_image: 'image',
  support_audio: 'audio',
  support_video: 'video',
  support_file: 'file',
  support_web_search: 'webSearch',
  support_tool_search: 'toolSearch',
  support_thinking: 'thinking',
  support_online_image: 'onlineImage',
  support_online_video: 'onlineVideo',
  support_embedding: 'embedding',
};

const ALL_TAB = '__ALL__';

/* ─── Derive model family from template label ─── */
function getModelFamilies(label: string): string[] {
  const families: string[] = [];
  const lower = label.toLowerCase();

  // Embedding models also belong to their provider family
  if (lower.includes('embedding')) {
    families.push('Embedding');
  }

  // Image generation models
  if (
    lower.includes('seedream') ||
    lower.includes('qwen-image') ||
    (lower.startsWith('gemini') && lower.includes('image')) ||
    lower.includes('z-image')
  ) {
    families.push('Image');
  }

  // 3D generation models
  if (
    lower.includes('hunyuan-3d') ||
    lower.includes('seed3d') ||
    lower.includes('hunyuan-3d')
  ) {
    families.push('3D');
  }

  // Video generation models
  if (
    lower.includes('seedance') ||
    lower.includes('kling') ||
    lower.includes('veo') ||
    lower.includes('viduq') ||
    lower.includes('pixverse') ||
    lower.includes('happyhorse')
  ) {
    families.push('Video');
  }

  // Provider-based classification
  if (lower.startsWith('gpt-') || lower.startsWith('gpt ')) families.push('GPT');
  else if (lower.startsWith('claude')) families.push('Claude');
  else if (lower.startsWith('gemini')) families.push('Gemini');
  else if (lower.startsWith('deepseek') || lower.includes('deepseek')) families.push('DeepSeek');
  else if (lower.startsWith('kimi')) families.push('Kimi');
  else if (lower.startsWith('glm')) families.push('GLM');
  else if (lower.startsWith('qwen')) families.push('Qwen');
  else if (lower.startsWith('minimax')) families.push('MiniMax');
  else if (lower.startsWith('doubao')) families.push('Doubao');

  // Fallback
  if (families.length === 0) {
    families.push(label.split(/[\s\-]/)[0]);
  }

  return families;
}

/* ─── Template form (shared by add & edit) ─── */
const TemplateForm = ({
  value,
  onChange,
  onSave,
  onCancel,
  isSaving,
}: {
  value: Omit<ModelTemplate, 'id'>;
  onChange: (v: Omit<ModelTemplate, 'id'>) => void;
  onSave: () => void;
  onCancel: () => void;
  isSaving: boolean;
}) => {
  const { t } = useTranslation();
  const set = (patch: Partial<Omit<ModelTemplate, 'id'>>) => onChange({ ...value, ...patch });

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6 space-y-5">
      {/* Basic identity */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">{t('modelTemplates.form.labelLabel')}</label>
          <input
            placeholder={t('modelTemplates.form.labelPlaceholder')}
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
            value={value.label}
            onChange={(e) => set({ label: e.target.value })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">{t('modelTemplates.form.providerLabel')}</label>
          <input
            placeholder={t('modelTemplates.form.providerPlaceholder')}
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
            value={value.provider}
            onChange={(e) => set({ provider: e.target.value })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">{t('modelTemplates.form.modelNameLabel')}</label>
          <input
            placeholder={t('modelTemplates.form.modelNamePlaceholder')}
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
            value={value.name}
            onChange={(e) => set({ name: e.target.value })}
          />
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">{t('modelTemplates.form.aliasLabel')}</label>
          <input
            placeholder={t('modelTemplates.form.aliasPlaceholder')}
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
            value={value.alias || ''}
            onChange={(e) => set({ alias: e.target.value || null })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">{t('modelTemplates.form.contextSizeLabel')}</label>
          <NumberInput value={value.context_size} onChange={(v) => set({ context_size: v ?? 0 })} />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">{t('modelTemplates.form.inputSizeLabel')}</label>
          <NumberInput value={value.input_size} onChange={(v) => set({ input_size: v ?? 0 })} />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">{t('modelTemplates.form.outputSizeLabel')}</label>
          <NumberInput value={value.output_size ?? 4096} onChange={(v) => set({ output_size: v ?? 0 })} />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">{t('modelTemplates.form.reasoningEffortLabel')}</label>
          <input
            placeholder={t('modelTemplates.form.reasoningEffortPlaceholder')}
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
            value={value.reasoning_effort || ''}
            onChange={(e) => set({ reasoning_effort: e.target.value || null })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">{t('modelTemplates.form.imageFormatsLabel')}</label>
          <input
            placeholder={t('modelTemplates.form.imageFormatsPlaceholder')}
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
            value={value.supported_image_formats || ''}
            onChange={(e) => set({ supported_image_formats: e.target.value || null })}
          />
        </div>
      </div>

      {/* Pricing Tiers */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold text-slate-700">{t('modelTemplates.form.pricingTiersTitle')} <span className="text-slate-400 font-normal text-xs">{t('modelTemplates.form.pricingTiersOptional')}</span></h3>
          <button
            type="button"
            onClick={() => set({ pricing_tiers: [...(value.pricing_tiers ?? []), { label: '', context_size: value.context_size, input_size: value.input_size, output_size: value.output_size, input_price: value.input_price, output_price: value.output_price, cache_creation_price: value.cache_creation_price, cache_5m_creation_price: value.cache_5m_creation_price ?? 0, cache_1h_creation_price: value.cache_1h_creation_price ?? 0, cache_hit_price: value.cache_hit_price }] })}
            className="text-xs bg-blue-50 text-blue-600 px-2 py-1 rounded-lg hover:bg-blue-100 transition-colors"
          >
            {t('modelTemplates.form.addTier')}
          </button>
        </div>
        {value.pricing_tiers && value.pricing_tiers.length > 0 ? (
          <div className="space-y-3">
            {value.pricing_tiers.map((tier, idx) => (
              <div key={idx} className="bg-slate-50 p-3 rounded-xl border border-slate-200">
                <div className="flex items-center justify-between mb-2">
                  <input
                    placeholder={t('modelTemplates.form.tierLabelPlaceholder')}
                    className="flex-1 p-2 bg-white border border-slate-200 rounded-lg text-sm mr-2 focus:border-blue-500 focus:ring-1 focus:ring-blue-500/20"
                    value={tier.label}
                    onChange={(e) => {
                      const tiers = [...value.pricing_tiers!];
                      tiers[idx] = { ...tiers[idx], label: e.target.value };
                      set({ pricing_tiers: tiers });
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => {
                      const tiers = value.pricing_tiers!.filter((_, i) => i !== idx);
                      set({ pricing_tiers: tiers.length > 0 ? tiers : null });
                    }}
                    className="text-slate-400 hover:text-red-500 text-xs px-2 py-1 hover:bg-red-50 rounded-lg"
                  >
                    {t('modelTemplates.form.removeTier')}
                  </button>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                  {[
                    { k: 'context_size', label: t('modelTemplates.form.tierContextSize'), type: 'int' },
                    { k: 'input_size', label: t('modelTemplates.form.tierInputSize'), type: 'int' },
                    { k: 'output_size', label: t('modelTemplates.form.tierOutputSize'), type: 'int' },
                    { k: 'input_price', label: t('modelTemplates.form.tierInputPrice'), type: 'float' },
                    { k: 'output_price', label: t('modelTemplates.form.tierOutputPrice'), type: 'float' },
                    { k: 'cache_creation_price', label: t('modelTemplates.form.tierCacheCreationPrice'), type: 'float' },
                    { k: 'cache_5m_creation_price', label: t('modelTemplates.form.tierCache5mCreationPrice'), type: 'float' },
                    { k: 'cache_1h_creation_price', label: t('modelTemplates.form.tierCache1hCreationPrice'), type: 'float' },
                    { k: 'cache_hit_price', label: t('modelTemplates.form.tierCacheHitPrice'), type: 'float' },
                  ].map(({ k, label, type }) => (
                    <div key={k}>
                      <label className="block text-xs text-slate-500 mb-1">{label}</label>
                      <input
                        type="number"
                        step={type === 'float' ? '0.01' : '1'}
                        className="w-full p-2 bg-white border border-slate-200 rounded-lg text-xs focus:border-blue-500 focus:ring-1 focus:ring-blue-500/20"
                        value={fmtNumber((tier as any)[k])}
                        onWheel={(e) => (e.currentTarget as HTMLInputElement).blur()}
                        onChange={(e) => {
                          const raw = e.target.value;
                          const tiers = [...value.pricing_tiers!];
                          if (raw === '' || raw.trim() === '') {
                            tiers[idx] = { ...tiers[idx], [k]: 0 };
                          } else {
                            const num = type === 'float' ? parseFloat(raw) : parseInt(raw);
                            if (!isNaN(num)) tiers[idx] = { ...tiers[idx], [k]: num };
                          }
                          set({ pricing_tiers: tiers });
                        }}
                      />
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-slate-400 italic">{t('modelTemplates.form.noTiers')}</p>
        )}
      </div>

      {/* Pricing */}
      <div>
        <h3 className="text-sm font-semibold text-slate-700 mb-2">{t('modelTemplates.form.pricingTitle')}</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">{t('modelTemplates.form.currencyLabel')}</label>
            <select
              className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
              value={value.currency || 'USD'}
              onChange={(e) => set({ currency: e.target.value })}
            >
              <option value="USD">USD ($)</option>
              <option value="CNY">CNY (¥)</option>
              <option value="EUR">EUR (€)</option>
              <option value="GBP">GBP (£)</option>
              <option value="JPY">JPY (¥)</option>
            </select>
          </div>
          {[
            { key: 'input_price', label: t('modelTemplates.form.inputPriceLabel') },
            { key: 'output_price', label: t('modelTemplates.form.outputPriceLabel') },
            { key: 'cache_creation_price', label: t('modelTemplates.form.cacheCreatePriceLabel') },
            { key: 'cache_5m_creation_price', label: t('modelTemplates.form.cache5mCreatePriceLabel') },
            { key: 'cache_1h_creation_price', label: t('modelTemplates.form.cache1hCreatePriceLabel') },
            { key: 'cache_hit_price', label: t('modelTemplates.form.cacheHitPriceLabel') },
          ].map(({ key, label }) => (
            <div key={key}>
              <label className="block text-sm font-medium text-slate-700 mb-1">{label}</label>
              <input
                type="number"
                step="0.01"
                className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                value={fmtNumber((value as any)[key])}
                onWheel={(e) => (e.currentTarget as HTMLInputElement).blur()}
                onChange={(e) => {
                  const raw = e.target.value;
                  if (raw === '' || raw.trim() === '') {
                    set({ [key]: 0 } as any);
                  } else {
                    const num = parseFloat(raw);
                    if (!isNaN(num)) set({ [key]: num } as any);
                  }
                }}
              />
            </div>
          ))}
        </div>
      </div>

      {/* Rate limits & discount */}
      <div>
        <h3 className="text-sm font-semibold text-slate-700 mb-2">{t('modelTemplates.form.rateLimitsTitle')}</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              {t('modelTemplates.form.rpmLabel')}
              <span className="text-slate-400 font-normal ml-1 text-xs">{t('modelTemplates.form.rpmHint')}</span>
            </label>
            <NumberInput min={0} placeholder={t('modelTemplates.form.rpmPlaceholder')} value={value.rpm} onChange={(v) => set({ rpm: v })} />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              {t('modelTemplates.form.tpmLabel')}
              <span className="text-slate-400 font-normal ml-1 text-xs">{t('modelTemplates.form.tpmHint')}</span>
            </label>
            <NumberInput min={0} placeholder={t('modelTemplates.form.tpmPlaceholder')} value={value.tpm} onChange={(v) => set({ tpm: v })} />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              {t('modelTemplates.form.discountLabel')}
              <span className="text-slate-400 font-normal ml-1 text-xs">{t('modelTemplates.form.discountHint')}</span>
            </label>
            <NumberInput step="0.01" min={0} max={1} value={value.discount ?? 1.0} onChange={(v) => set({ discount: v ?? 1.0 })} />
          </div>
        </div>
      </div>

      {/* Retirement */}
      <div>
        <h3 className="text-sm font-semibold text-slate-700 mb-2">{t('modelTemplates.form.retirementTitle')}</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              {t('modelTemplates.form.retirementDateLabel')}
              <span className="text-slate-400 font-normal ml-1 text-xs">{t('modelTemplates.form.retirementDateHint')}</span>
            </label>
            <input
              type="datetime-local"
              className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
              value={value.retirement_time ? value.retirement_time.slice(0, 16) : ''}
              onChange={(e) => set({ retirement_time: e.target.value ? e.target.value + ':00' : null })}
            />
          </div>
        </div>
      </div>

      {/* Features */}
      <div>
        <h3 className="text-sm font-semibold text-slate-700 mb-2">{t('modelTemplates.form.featuresTitle')}</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {FEATURES_KEYS.map((key) => (
            <label key={key} className="flex items-center space-x-2 cursor-pointer p-2 rounded-lg hover:bg-slate-50 transition-colors">
              <input
                type="checkbox"
                checked={!!(value as any)[key]}
                onChange={(e) => set({ [key]: e.target.checked } as any)}
                className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
              />
              <span className="text-sm text-slate-600">{t(`modelTemplates.features.${FEATURE_I18N_MAP[key]}`)}</span>
            </label>
          ))}
        </div>
      </div>

      {/* API Access Types */}
      <div>
        <h3 className="text-sm font-semibold text-slate-700 mb-2">API Access Types <span className="text-slate-400 font-normal text-xs">(empty = all allowed)</span></h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {[
            { key: 'chat_completions', label: 'Chat Completions (/v1/chat/completions)' },
            { key: 'responses', label: 'Responses API (/v1/responses)' },
            { key: 'messages', label: 'Messages (/v1/messages, Anthropic)' },
          ].map((apiType) => {
            const selected = (value.api_type || '').split(',').map((s: string) => s.trim()).includes(apiType.key);
            return (
              <label key={apiType.key} className="flex items-center space-x-2 cursor-pointer p-2 rounded-lg hover:bg-slate-50 transition-colors">
                <input
                  type="checkbox"
                  checked={selected}
                  onChange={(e) => {
                    const current = (value.api_type || '').split(',').map((s: string) => s.trim()).filter(Boolean);
                    if (e.target.checked) {
                      current.push(apiType.key);
                    } else {
                      const idx = current.indexOf(apiType.key);
                      if (idx !== -1) current.splice(idx, 1);
                    }
                    set({ api_type: current.join(',') || '' } as any);
                  }}
                  className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                />
                <span className="text-sm text-slate-600">{apiType.label}</span>
              </label>
            );
          })}
        </div>
      </div>

      {/* Output Pricing editor */}
      <div>
        <h3 className="text-sm font-semibold text-slate-700 mb-2">
          Output Pricing <span className="text-slate-400 font-normal text-xs">(optional — for image / video / audio / 3D models)</span>
        </h3>
        {(['image', 'video', 'audio', '3d'] as const).map((category) => {
          const typeOptions: Record<string, { value: string; label: string }[]> = {
            image: [
              { value: 'per_token', label: 'Per Token ($/M)' },
              { value: 'per_image', label: 'Per Image ($)' },
            ],
            video: [
              { value: 'per_token', label: 'Per Token ($/M)' },
              { value: 'per_second', label: 'Per Second ($)' },
            ],
            audio: [
              { value: 'per_token', label: 'Per Token ($/M)' },
              { value: 'per_second', label: 'Per Second ($)' },
            ],
            '3d': [
              { value: 'per_token', label: 'Per Token ($/M)' },
              { value: 'per_credit', label: 'Per Credit ($)' },
            ],
          };
          const tierResolutionHints: Record<string, string[]> = {
            image: ['512', '1K', '2K', '3K', '4K'],
            video: ['720p', '1080p', '2K', '4K'],
            audio: ['low', 'standard', 'high'],
            '3d': [],
          };
          const op: OutputPricing = value.output_pricing ?? {};
          const cat: OutputPricingCategory | undefined = op[category];
          const enabled = !!cat;

          const updateCategory = (patch: Partial<OutputPricingCategory> | null) => {
            const newOp = { ...op };
            if (patch === null) {
              delete newOp[category];
            } else {
              newOp[category] = { ...(cat ?? { type: typeOptions[category][0].value, price: 0 }), ...patch };
            }
            const hasAny = newOp.image || newOp.video || newOp.audio || newOp['3d'];
            set({ output_pricing: hasAny ? newOp : null });
          };

          return (
            <div key={category} className="bg-slate-50 p-3 rounded-xl border border-slate-200 mb-2">
              <div className="flex items-center justify-between">
                <label className="flex items-center space-x-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={enabled}
                    onChange={(e) => {
                      if (e.target.checked) {
                        updateCategory({ type: typeOptions[category][0].value, price: 0 });
                      } else {
                        updateCategory(null);
                      }
                    }}
                    className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                  />
                  <span className="text-sm font-medium text-slate-700">{category === '3d' ? '3D' : category.charAt(0).toUpperCase() + category.slice(1)} Output Pricing</span>
                </label>
              </div>
              {enabled && cat && (
                <div className="mt-3 space-y-3">
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs text-slate-500 mb-1">Pricing Type</label>
                      <select
                        className="w-full p-2 bg-white border border-slate-200 rounded-lg text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500/20"
                        value={cat.type}
                        onChange={(e) => updateCategory({ type: e.target.value })}
                      >
                        {typeOptions[category].map((opt) => (
                          <option key={opt.value} value={opt.value}>{opt.label}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs text-slate-500 mb-1">
                        Base Price {cat.type === 'per_token' ? '($/M tokens)' : cat.type === 'per_image' ? '($ per image)' : cat.type === 'per_second' ? '($ per second)' : '($ per credit)'}
                      </label>
                      <input
                        type="number"
                        step="0.0001"
                        className="w-full p-2 bg-white border border-slate-200 rounded-lg text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500/20"
                        value={fmtNumber(cat.price)}
                        onWheel={(e) => (e.currentTarget as HTMLInputElement).blur()}
                        onChange={(e) => {
                          const raw = e.target.value;
                          if (raw === '' || raw.trim() === '') {
                            updateCategory({ price: 0 });
                          } else {
                            const num = parseFloat(raw);
                            if (!isNaN(num)) updateCategory({ price: num });
                          }
                        }}
                      />
                    </div>
                  </div>
                  {/* Resolution tiers */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className="text-xs font-medium text-slate-600">
                        Resolution Tiers <span className="text-slate-400 font-normal">(override base price by resolution)</span>
                      </label>
                      <button
                        type="button"
                        onClick={() => {
                          const newTier: OutputPricingTier = {
                            resolution: tierResolutionHints[category][0] || '',
                            price: cat.price,
                            ...(category === 'image' ? { quality: '' } : {}),
                            ...(category === 'video' ? { audio: false } : {}),
                          };
                          updateCategory({ tiers: [...(cat.tiers ?? []), newTier] });
                        }}
                        className="text-xs bg-blue-50 text-blue-600 px-2 py-0.5 rounded-lg hover:bg-blue-100 transition-colors"
                      >
                        + Add Tier
                      </button>
                    </div>
                    {cat.tiers && cat.tiers.length > 0 ? (
                      <div className="space-y-2">
                        {cat.tiers.map((tier, idx) => (
                          <div key={idx} className="flex items-center gap-2 bg-white p-2 rounded-lg border border-slate-200">
                            <div className="flex-1">
                              <label className="block text-xs text-slate-400 mb-0.5">Resolution</label>
                              <input
                                type="text"
                                placeholder={tierResolutionHints[category].join(', ')}
                                className="w-full p-1.5 bg-slate-50 border border-slate-200 rounded text-xs focus:border-blue-500 focus:ring-1 focus:ring-blue-500/20"
                                value={tier.resolution}
                                onChange={(e) => {
                                  const tiers = [...(cat.tiers ?? [])];
                                  tiers[idx] = { ...tiers[idx], resolution: e.target.value };
                                  updateCategory({ tiers });
                                }}
                              />
                            </div>
                            {category === 'image' && (
                              <div className="flex-1">
                                <label className="block text-xs text-slate-400 mb-0.5">Quality</label>
                                <input
                                  type="text"
                                  placeholder="low, medium, high"
                                  className="w-full p-1.5 bg-slate-50 border border-slate-200 rounded text-xs focus:border-blue-500 focus:ring-1 focus:ring-blue-500/20"
                                  value={tier.quality || ''}
                                  onChange={(e) => {
                                    const tiers = [...(cat.tiers ?? [])];
                                    tiers[idx] = { ...tiers[idx], quality: e.target.value || undefined };
                                    updateCategory({ tiers });
                                  }}
                                />
                              </div>
                            )}
                            {category === 'video' && (
                              <div className="flex-shrink-0">
                                <label className="block text-xs text-slate-400 mb-0.5">Audio</label>
                                <label className="flex items-center space-x-1 cursor-pointer p-1.5">
                                  <input
                                    type="checkbox"
                                    checked={!!tier.audio}
                                    onChange={(e) => {
                                      const tiers = [...(cat.tiers ?? [])];
                                      tiers[idx] = { ...tiers[idx], audio: e.target.checked };
                                      updateCategory({ tiers });
                                    }}
                                    className="w-3 h-3 rounded border-slate-300 text-blue-600"
                                  />
                                  <span className="text-xs text-slate-600">Yes</span>
                                </label>
                              </div>
                            )}
                            {category === 'video' && (
                              <div className="flex-shrink-0">
                                <label className="block text-xs text-slate-400 mb-0.5">Ref Video</label>
                                <label className="flex items-center space-x-1 cursor-pointer p-1.5">
                                  <input
                                    type="checkbox"
                                    checked={!!tier.reference_video}
                                    onChange={(e) => {
                                      const tiers = [...(cat.tiers ?? [])];
                                      tiers[idx] = { ...tiers[idx], reference_video: e.target.checked };
                                      updateCategory({ tiers });
                                    }}
                                    className="w-3 h-3 rounded border-slate-300 text-blue-600"
                                  />
                                  <span className="text-xs text-slate-600">Yes</span>
                                </label>
                              </div>
                            )}
                            <div className="flex-1">
                              <label className="block text-xs text-slate-400 mb-0.5">
                                Price {cat.type === 'per_token' ? '($/M)' : cat.type === 'per_image' ? '($)' : '($/s)'}
                              </label>
                              <input
                                type="number"
                                step="0.0001"
                                className="w-full p-1.5 bg-slate-50 border border-slate-200 rounded text-xs focus:border-blue-500 focus:ring-1 focus:ring-blue-500/20"
                                value={fmtNumber(tier.price)}
                                onWheel={(e) => (e.currentTarget as HTMLInputElement).blur()}
                                onChange={(e) => {
                                  const raw = e.target.value;
                                  const tiers = [...(cat.tiers ?? [])];
                                  if (raw === '' || raw.trim() === '') {
                                    tiers[idx] = { ...tiers[idx], price: 0 };
                                  } else {
                                    const num = parseFloat(raw);
                                    if (!isNaN(num)) tiers[idx] = { ...tiers[idx], price: num };
                                  }
                                  updateCategory({ tiers });
                                }}
                              />
                            </div>
                            <button
                              type="button"
                              onClick={() => {
                                const tiers = (cat.tiers ?? []).filter((_, i) => i !== idx);
                                updateCategory({ tiers: tiers.length > 0 ? tiers : undefined });
                              }}
                              className="text-slate-400 hover:text-red-500 text-xs mt-4 px-1 py-0.5 hover:bg-red-50 rounded"
                            >
                              ✕
                            </button>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-xs text-slate-400 italic">No tiers — base price applies to all resolutions.</p>
                    )}
                  </div>
                  {/* 3D credit rules editor */}
                  {category === '3d' && (
                    <div className="mt-3 pt-3 border-t border-slate-200">
                      <div className="flex items-center justify-between mb-2">
                        <label className="text-xs font-medium text-slate-600">
                          Credit Rules <span className="text-slate-400 font-normal">(cost per operation in credits)</span>
                        </label>
                        <button
                          type="button"
                          onClick={() => {
                            const newCredits = { ...(cat.credits ?? {}), new_rule: 0 };
                            updateCategory({ credits: newCredits });
                          }}
                          className="text-xs bg-blue-50 text-blue-600 px-2 py-0.5 rounded-lg hover:bg-blue-100 transition-colors"
                        >
                          + Add Rule
                        </button>
                      </div>
                      {cat.credits && Object.keys(cat.credits).length > 0 ? (
                        <div className="space-y-2">
                          {Object.entries(cat.credits).map(([key, val], idx) => {
                            const isObject = typeof val === 'object' && !Array.isArray(val);
                            return (
                              <div key={idx} className="bg-white p-2 rounded-lg border border-slate-200">
                                <div className="flex items-center gap-2 mb-2">
                                  <input
                                    type="text"
                                    placeholder="Rule name"
                                    className="flex-1 p-1.5 bg-slate-50 border border-slate-200 rounded text-xs focus:border-blue-500 focus:ring-1 focus:ring-blue-500/20"
                                    value={key}
                                    onChange={(e) => {
                                      const newCredits = { ...(cat.credits ?? {}) };
                                      delete newCredits[key];
                                      newCredits[e.target.value || `rule_${idx}`] = val;
                                      updateCategory({ credits: newCredits });
                                    }}
                                  />
                                  <button
                                    type="button"
                                    onClick={() => {
                                      const newCredits = { ...(cat.credits ?? {}) };
                                      delete newCredits[key];
                                      updateCategory({ credits: Object.keys(newCredits).length > 0 ? newCredits : undefined });
                                    }}
                                    className="text-slate-400 hover:text-red-500 text-xs px-1 py-0.5 hover:bg-red-50 rounded"
                                  >
                                    ✕
                                  </button>
                                </div>
                                {isObject ? (
                                  <div className="space-y-1 ml-2">
                                    {Object.entries(val as Record<string, number>).map(([subKey, subVal], si) => (
                                      <div key={si} className="flex items-center gap-2">
                                        <input
                                          type="text"
                                          placeholder="Option name"
                                          className="flex-1 p-1.5 bg-slate-50 border border-slate-200 rounded text-xs focus:border-blue-500 focus:ring-1 focus:ring-blue-500/20"
                                          value={subKey}
                                          onChange={(e) => {
                                            const inner = { ...(val as Record<string, number>) };
                                            delete inner[subKey];
                                            inner[e.target.value || `option_${si}`] = subVal;
                                            const newCredits = { ...(cat.credits ?? {}) };
                                            newCredits[key] = inner;
                                            updateCategory({ credits: newCredits });
                                          }}
                                        />
                                        <input
                                          type="number"
                                          className="w-20 p-1.5 bg-slate-50 border border-slate-200 rounded text-xs focus:border-blue-500 focus:ring-1 focus:ring-blue-500/20"
                                          value={fmtNumber(subVal)}
                                          onWheel={(e) => (e.currentTarget as HTMLInputElement).blur()}
                                          onChange={(e) => {
                                            const inner = { ...(val as Record<string, number>) };
                                            const raw = e.target.value;
                                            if (raw === '' || raw.trim() === '') {
                                              inner[subKey] = 0;
                                            } else {
                                              const num = parseInt(raw);
                                              if (!isNaN(num)) inner[subKey] = num;
                                            }
                                            const newCredits = { ...(cat.credits ?? {}) };
                                            newCredits[key] = inner;
                                            updateCategory({ credits: newCredits });
                                          }}
                                        />
                                        <span className="text-xs text-slate-400">credits</span>
                                        <button
                                          type="button"
                                          onClick={() => {
                                            const inner = { ...(val as Record<string, number>) };
                                            delete inner[subKey];
                                            const newCredits = { ...(cat.credits ?? {}) };
                                            if (Object.keys(inner).length > 0) {
                                              newCredits[key] = inner;
                                            } else {
                                              delete newCredits[key];
                                            }
                                            updateCategory({ credits: Object.keys(newCredits).length > 0 ? newCredits : undefined });
                                          }}
                                          className="text-slate-400 hover:text-red-500 text-xs"
                                        >
                                          ✕
                                        </button>
                                      </div>
                                    ))}
                                    <button
                                      type="button"
                                      onClick={() => {
                                        const inner = { ...(val as Record<string, number>), new_option: 0 };
                                        const newCredits = { ...(cat.credits ?? {}) };
                                        newCredits[key] = inner;
                                        updateCategory({ credits: newCredits });
                                      }}
                                      className="text-xs text-blue-500 hover:text-blue-600"
                                    >
                                      + Add option
                                    </button>
                                  </div>
                                ) : (
                                  <div className="flex items-center gap-2 ml-2">
                                    <input
                                      type="number"
                                      className="w-20 p-1.5 bg-slate-50 border border-slate-200 rounded text-xs focus:border-blue-500 focus:ring-1 focus:ring-blue-500/20"
                                      value={fmtNumber(val as number)}
                                      onWheel={(e) => (e.currentTarget as HTMLInputElement).blur()}
                                      onChange={(e) => {
                                        const raw = e.target.value;
                                        const newCredits = { ...(cat.credits ?? {}) };
                                        if (raw === '' || raw.trim() === '') {
                                          newCredits[key] = 0;
                                        } else {
                                          const num = parseInt(raw);
                                          if (!isNaN(num)) newCredits[key] = num;
                                        }
                                        updateCategory({ credits: newCredits });
                                      }}
                                    />
                                    <span className="text-xs text-slate-400">credits</span>
                                    <button
                                      type="button"
                                      onClick={() => {
                                        const inner = { ...(val as Record<string, number>) };
                                        (inner as any).new_option = 0;
                                        const newCredits = { ...(cat.credits ?? {}) };
                                        newCredits[key] = inner;
                                        updateCategory({ credits: newCredits });
                                      }}
                                      className="text-xs text-blue-500 hover:text-blue-600"
                                    >
                                      Convert to options
                                    </button>
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      ) : (
                        <p className="text-xs text-slate-400 italic">No credit rules — fixed price per operation.</p>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Actions */}
      <div className="flex space-x-3 pt-2 border-t border-slate-100">
        <button
          onClick={onSave}
          disabled={isSaving || !value.label || !value.name || !value.provider}
          className="bg-emerald-500 text-white px-5 py-2.5 rounded-xl text-sm flex items-center hover:bg-emerald-600 disabled:bg-slate-300 disabled:cursor-not-allowed transition-colors shadow-sm"
        >
          <Save className="w-4 h-4 mr-2" /> {isSaving ? t('modelTemplates.saving') : t('common.save')}
        </button>
        <button
          onClick={onCancel}
          className="bg-slate-100 text-slate-600 px-5 py-2.5 rounded-xl text-sm hover:bg-slate-200 transition-colors"
        >
          {t('common.cancel')}
        </button>
      </div>
    </div>
  );
};

/* ─── Template card (read-only row) ─── */
const TemplateCard = ({
  tpl,
  onEdit,
  onDelete,
}: {
  tpl: ModelTemplate;
  onEdit: () => void;
  onDelete: () => void;
}) => {
  const { t, i18n } = useTranslation();
  const isZh = i18n.language?.startsWith('zh');

  return (
    <div
      className={`bg-white rounded-2xl shadow-sm border p-5 hover:shadow-md transition-shadow ${tpl.is_retired ? 'border-red-200 opacity-70' : 'border-slate-200'}`}
    >
      <div className="flex justify-between items-start">
        <div className="flex-1 min-w-0">
          {/* Title row */}
          <div className="flex items-center space-x-3 flex-wrap gap-y-1">
            <h3 className="font-semibold text-slate-800">{tpl.label}</h3>
            <span className="bg-slate-100 text-slate-600 px-2 py-0.5 rounded text-xs font-mono">
              {tpl.name}
            </span>
            {tpl.alias && (
              <span className="bg-cyan-100 text-cyan-700 px-2 py-0.5 rounded text-xs">
                @{tpl.alias}
              </span>
            )}
            {tpl.currency && tpl.currency !== 'USD' && (
              <span className="bg-violet-100 text-violet-700 px-2 py-0.5 rounded text-xs font-medium">
                {tpl.currency}
              </span>
            )}
            {tpl.pricing_tiers && tpl.pricing_tiers.length > 0 && (
              <span className="bg-amber-100 text-amber-700 px-2 py-0.5 rounded text-xs font-medium">
                {t('modelTemplates.tiers', { count: tpl.pricing_tiers.length })}
              </span>
            )}
            {tpl.is_retired && (
              <span className="bg-red-100 text-red-700 px-2 py-0.5 rounded text-xs font-medium">
                {t('modelTemplates.retired')}
              </span>
            )}
            {!tpl.is_retired && tpl.retirement_time && (
              <span className="bg-orange-100 text-orange-700 px-2 py-0.5 rounded text-xs font-medium">
                {t('modelTemplates.retires', { date: new Date(tpl.retirement_time).toLocaleDateString() })}
              </span>
            )}
            {tpl.discount != null && tpl.discount < 1 && (
              <span className="bg-green-100 text-green-700 px-2 py-0.5 rounded text-xs font-medium">
                {t('modelTemplates.discountBadge', {
                  percent: isZh ? parseFloat((tpl.discount * 10).toFixed(1)) : Math.round((1 - tpl.discount) * 100),
                })}
              </span>
            )}
          </div>

          {/* Pricing row */}
          {tpl.pricing_tiers && tpl.pricing_tiers.length > 0 ? (
            <div className="mt-3 space-y-1">
              {tpl.pricing_tiers.map((tier, i) => (
                <div key={i} className="flex flex-wrap gap-3 text-sm text-slate-600">
                  <span className="text-slate-500 text-xs font-medium w-20">{tier.label}</span>
                  <span><span className="text-slate-400 text-xs mr-1">{t('modelTemplates.card.ctx')}</span>{tier.context_size.toLocaleString()}</span>
                  <span><span className="text-slate-400 text-xs mr-1">{t('modelTemplates.card.in')}</span>{currencySymbol(tpl.currency)}{tier.input_price}/M</span>
                  <span><span className="text-slate-400 text-xs mr-1">{t('modelTemplates.card.out')}</span>{currencySymbol(tpl.currency)}{tier.output_price}/M</span>
                  {tier.cache_hit_price > 0 && <span><span className="text-slate-400 text-xs mr-1">{t('modelTemplates.card.cacheDown')}</span>{currencySymbol(tpl.currency)}{tier.cache_hit_price}/M</span>}
                </div>
              ))}
            </div>
          ) : (
            <div className="flex flex-wrap gap-4 mt-3 text-sm text-slate-600">
              <span>
                <span className="text-slate-400 text-xs mr-1">{t('modelTemplates.card.ctx')}</span>
                {tpl.context_size.toLocaleString()}
              </span>
              <span>
                <span className="text-slate-400 text-xs mr-1">{t('modelTemplates.card.in')}</span>
                {currencySymbol(tpl.currency)}{tpl.input_price}/M
              </span>
              <span>
                <span className="text-slate-400 text-xs mr-1">{t('modelTemplates.card.out')}</span>
                {currencySymbol(tpl.currency)}{tpl.output_price}/M
              </span>
              {tpl.cache_creation_price > 0 && (
                <span>
                  <span className="text-slate-400 text-xs mr-1">{t('modelTemplates.card.cacheUp')}</span>
                  {currencySymbol(tpl.currency)}{tpl.cache_creation_price}/M
                </span>
              )}
              {tpl.cache_5m_creation_price > 0 && (
                <span>
                  <span className="text-slate-400 text-xs mr-1">{t('modelTemplates.card.cacheUp5m')}</span>
                  {currencySymbol(tpl.currency)}{tpl.cache_5m_creation_price}/M
                </span>
              )}
              {tpl.cache_1h_creation_price > 0 && (
                <span>
                  <span className="text-slate-400 text-xs mr-1">{t('modelTemplates.card.cacheUp1h')}</span>
                  {currencySymbol(tpl.currency)}{tpl.cache_1h_creation_price}/M
                </span>
              )}
              {tpl.cache_hit_price > 0 && (
                <span>
                  <span className="text-slate-400 text-xs mr-1">{t('modelTemplates.card.cacheDown')}</span>
                  {currencySymbol(tpl.currency)}{tpl.cache_hit_price}/M
                </span>
              )}
            </div>
          )}

          {/* Output Pricing display */}
          {tpl.output_pricing && (
            <div className="mt-3">
              {(['image', 'video', 'audio', '3d'] as const).map((cat) => {
                const catConfig = tpl.output_pricing?.[cat];
                if (!catConfig) return null;
                const catLabel = cat === '3d' ? '3D' : cat.charAt(0).toUpperCase() + cat.slice(1);
                const typeLabel = catConfig.type === 'per_image' ? '/image'
                  : catConfig.type === 'per_second' ? '/s'
                  : catConfig.type === 'per_credit' ? '/credit'
                  : '/M tokens';
                return (
                  <div key={cat} className="bg-blue-50 border border-blue-200 rounded-lg p-2 mb-1.5">
                    <span className="text-blue-600 text-xs font-semibold block mb-1">
                      {catLabel} Output — {catConfig.type === 'per_token' ? 'Per Token' : catConfig.type === 'per_image' ? 'Per Image' : catConfig.type === 'per_second' ? 'Per Second' : 'Per Credit'} ({tpl.currency || 'USD'})
                    </span>
                    {catConfig.tiers && catConfig.tiers.length > 0 ? (
                      <div className="space-y-0.5">
                        {catConfig.tiers.map((tier, i) => (
                          <div key={i} className="flex items-center gap-2 text-xs text-slate-600">
                            <span className="text-slate-500 min-w-[40px]">{tier.resolution}</span>
                            {tier.quality && <span className="text-purple-500">{tier.quality}</span>}
                            <span>{currencySymbol(tpl.currency)}{tier.price}{typeLabel}</span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <span className="text-xs text-slate-600">{currencySymbol(tpl.currency)}{catConfig.price}{typeLabel}</span>
                    )}
                    {cat === '3d' && catConfig.credits && (
                      <div className="mt-1.5 pt-1.5 border-t border-blue-200">
                        <span className="text-xs font-medium text-slate-500 block mb-0.5">Credit Rules</span>
                        <div className="space-y-0.5">
                          {Object.entries(catConfig.credits).map(([key, val]) => {
                            if (typeof val === 'object' && !Array.isArray(val)) {
                              return (
                                <div key={key} className="flex items-center gap-2 text-xs text-slate-600">
                                  <span className="text-slate-500 min-w-[80px]">{key}:</span>
                                  <span>{JSON.stringify(val)}</span>
                                </div>
                              );
                            }
                            return (
                              <div key={key} className="flex items-center gap-2 text-xs text-slate-600">
                                <span className="text-slate-500 min-w-[80px]">{key}:</span>
                                <span className="font-medium">{val} credits</span>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* Feature badges */}
          <div className="flex flex-wrap gap-1.5 mt-3">
            {FEATURES_KEYS.filter((key) => !!(tpl as any)[key]).map((key) => (
              <span
                key={key}
                className="bg-blue-50 text-blue-700 px-2 py-0.5 rounded text-xs font-medium"
              >
                {t(`modelTemplates.features.${FEATURE_I18N_MAP[key]}`)}
              </span>
            ))}
          </div>
        </div>

        {/* Actions */}
        <div className="flex space-x-1 ml-4 shrink-0">
          <button
            onClick={onEdit}
            className="text-slate-400 hover:text-blue-600 p-2 hover:bg-blue-50 rounded-lg transition-colors"
            title={t('common.edit')}
          >
            <Edit2 className="w-4 h-4" />
          </button>
          <button
            onClick={onDelete}
            className="text-slate-400 hover:text-red-600 p-2 hover:bg-red-50 rounded-lg transition-colors"
            title={t('common.delete')}
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
};

/* ─── Main page ─── */
export default function ModelTemplates() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [showAdd, setShowAdd] = useState(false);
  const [newTpl, setNewTpl] = useState<Omit<ModelTemplate, 'id'>>(emptyTemplate());
  const [editingTpl, setEditingTpl] = useState<ModelTemplate | null>(null);
  const [activeTab, setActiveTab] = useState<string>(ALL_TAB);
  const [searchQuery, setSearchQuery] = useState('');

  const { data: templates = [], isLoading } = useQuery({
    queryKey: ['model-templates'],
    queryFn: async () => {
      const res = await client.get('/api/model-templates/');
      return res.data as ModelTemplate[];
    },
  });

  const createMutation = useMutation({
    mutationFn: (data: Omit<ModelTemplate, 'id'>) => client.post('/api/model-templates/', data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['model-templates'] });
      setShowAdd(false);
      setNewTpl(emptyTemplate());
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Omit<ModelTemplate, 'id'> }) =>
      client.put(`/api/model-templates/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['model-templates'] });
      setEditingTpl(null);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => client.delete(`/api/model-templates/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['model-templates'] }),
  });

  const seedMutation = useMutation({
    mutationFn: () => client.post('/api/model-templates/seed'),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['model-templates'] });
      const { added, updated } = res.data as { added: number; updated: number };
      alert(t('modelTemplates.syncComplete', { added, updated }));
    },
    onError: () => {
      alert(t('modelTemplates.syncFailed'));
    },
  });

  // Derive unique model families & counts
  const familyTabs = useMemo(() => {
    const countMap = new Map<string, number>();
    for (const tpl of templates) {
      for (const family of getModelFamilies(tpl.label)) {
        countMap.set(family, (countMap.get(family) || 0) + 1);
      }
    }
    // Sort families alphabetically
    const sorted = Array.from(countMap.entries()).sort((a, b) => a[0].localeCompare(b[0]));
    return sorted;
  }, [templates]);

  // Filter templates by active tab (model family) + search query
  const filteredTemplates = useMemo(() => {
    let list = templates;
    if (activeTab !== ALL_TAB) {
      list = list.filter((tpl) => getModelFamilies(tpl.label).includes(activeTab));
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      list = list.filter(
        (tpl) =>
          tpl.label.toLowerCase().includes(q) ||
          tpl.name.toLowerCase().includes(q) ||
          (tpl.alias && tpl.alias.toLowerCase().includes(q)) ||
          tpl.provider.toLowerCase().includes(q)
      );
    }
    return list;
  }, [templates, activeTab, searchQuery]);

  // Group filtered templates by provider for display within a family tab
  const groupedByProvider = useMemo(() => {
    const groups = new Map<string, ModelTemplate[]>();
    for (const tpl of filteredTemplates) {
      if (!groups.has(tpl.provider)) groups.set(tpl.provider, []);
      groups.get(tpl.provider)!.push(tpl);
    }
    return Array.from(groups.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [filteredTemplates]);

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="text-slate-500">{t('modelTemplates.loading')}</div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">{t('modelTemplates.title')}</h1>
          <p className="text-slate-500 mt-1">
            {t('modelTemplates.subtitle')}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => seedMutation.mutate()}
            disabled={seedMutation.isPending}
            className="bg-amber-500 text-white px-5 py-2.5 rounded-xl flex items-center hover:bg-amber-600 disabled:bg-slate-300 disabled:cursor-not-allowed transition-all shadow-lg shadow-amber-500/25"
          >
            <RefreshCw className={`w-4 h-4 mr-2 ${seedMutation.isPending ? 'animate-spin' : ''}`} />
            {seedMutation.isPending ? t('modelTemplates.syncing') : t('modelTemplates.syncTemplates')}
          </button>
          <button
            onClick={() => { setShowAdd(true); setEditingTpl(null); }}
            className="bg-gradient-to-r from-blue-500 to-indigo-600 text-white px-5 py-2.5 rounded-xl flex items-center hover:from-blue-600 hover:to-indigo-700 transition-all shadow-lg shadow-blue-500/25"
          >
            <Plus className="w-4 h-4 mr-2" /> {t('modelTemplates.addTemplate')}
          </button>
        </div>
      </div>

      {/* Provider tabs + search bar */}
      {templates.length > 0 && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-4 space-y-3">
          {/* Tabs */}
          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={() => setActiveTab(ALL_TAB)}
              className={`px-4 py-2 rounded-xl text-sm font-medium transition-all ${
                activeTab === ALL_TAB
                  ? 'bg-blue-500 text-white shadow-md shadow-blue-500/25'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
              }`}
            >
              {t('modelTemplates.all')}
              <span className={`ml-1.5 text-xs px-1.5 py-0.5 rounded-full ${
                activeTab === ALL_TAB ? 'bg-blue-400/30 text-white' : 'bg-slate-200 text-slate-500'
              }`}>
                {templates.length}
              </span>
            </button>
            {familyTabs.map(([family, count]) => (
              <button
                key={family}
                onClick={() => setActiveTab(family)}
                className={`px-4 py-2 rounded-xl text-sm font-medium transition-all ${
                  activeTab === family
                    ? 'bg-blue-500 text-white shadow-md shadow-blue-500/25'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                }`}
              >
                {family}
                <span className={`ml-1.5 text-xs px-1.5 py-0.5 rounded-full ${
                  activeTab === family ? 'bg-blue-400/30 text-white' : 'bg-slate-200 text-slate-500'
                }`}>
                  {count}
                </span>
              </button>
            ))}
          </div>

          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              type="text"
              placeholder={t('modelTemplates.searchPlaceholder')}
              className="w-full pl-10 pr-10 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>
      )}

      {/* Add form */}
      {showAdd && (
        <TemplateForm
          value={newTpl}
          onChange={setNewTpl}
          onSave={() => createMutation.mutate(newTpl)}
          onCancel={() => { setShowAdd(false); setNewTpl(emptyTemplate()); }}
          isSaving={createMutation.isPending}
        />
      )}

      {/* Template list */}
      {templates.length === 0 && !showAdd ? (
        <div className="text-center py-16 bg-white rounded-2xl border border-slate-200 text-slate-500">
          <LayoutTemplate className="w-16 h-16 mx-auto mb-4 text-slate-300" />
          <p className="text-lg font-medium text-slate-700">{t('modelTemplates.noTemplates')}</p>
          <p className="text-sm mt-2">{t('modelTemplates.noTemplatesHint')}</p>
        </div>
      ) : filteredTemplates.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-2xl border border-slate-200 text-slate-500">
          <Search className="w-12 h-12 mx-auto mb-3 text-slate-300" />
          <p className="text-lg font-medium text-slate-700">{t('modelTemplates.noMatchingTemplates')}</p>
          <p className="text-sm mt-1">
            {searchQuery
              ? t('modelTemplates.noTemplatesMatch', { query: searchQuery, tabSuffix: activeTab !== ALL_TAB ? ` in ${activeTab}` : '' })
              : t('modelTemplates.noTemplatesForTab', { tab: activeTab })}
          </p>
          <button
            onClick={() => { setSearchQuery(''); setActiveTab(ALL_TAB); }}
            className="mt-3 text-sm text-blue-600 hover:text-blue-700 font-medium"
          >
            {t('modelTemplates.clearFilters')}
          </button>
        </div>
      ) : (
        groupedByProvider.map(([providerName, providerTemplates]) => (
          <div key={providerName} className="space-y-3">
            <div className="flex items-center justify-between px-1">
              <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wider">
                {providerName}
              </h2>
              <span className="text-xs text-slate-400">
                {t('modelTemplates.modelsCount', { count: providerTemplates.length })}
              </span>
            </div>
            {providerTemplates.map((tpl: ModelTemplate) =>
              editingTpl?.id === tpl.id ? (
                <TemplateForm
                  key={tpl.id}
                  value={editingTpl!}
                  onChange={(v) => setEditingTpl({ ...editingTpl!, ...v })}
                  onSave={() => {
                    const { id, ...data } = editingTpl!;
                    updateMutation.mutate({ id, data });
                  }}
                  onCancel={() => setEditingTpl(null)}
                  isSaving={updateMutation.isPending}
                />
              ) : (
                <TemplateCard
                  key={tpl.id}
                  tpl={tpl}
                  onEdit={() => { setEditingTpl(tpl); setShowAdd(false); }}
                  onDelete={() => {
                    if (confirm(t('modelTemplates.deleteConfirm', { label: tpl.label }))) {
                      deleteMutation.mutate(tpl.id);
                    }
                  }}
                />
              )
            )}
          </div>
        ))
      )}
    </div>
  );
}