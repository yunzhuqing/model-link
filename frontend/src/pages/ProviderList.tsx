import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import client from '../api/client';
import { Plus, Edit2, Trash2, ChevronDown, ChevronUp, X, Save, Database, Cpu, Link as LinkIcon } from 'lucide-react';
import ProviderFormFields, { type ProviderFormData } from '../components/ProviderFormFields';

// ── Interfaces ────────────────────────────────────────────────────────────────

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

interface OutputPricingTier {
  resolution: string;
  audio?: boolean;
  reference_video?: boolean;
  price: number;
}

interface OutputPricingCategory {
  type: string;  // "per_image" | "per_token" | "per_second"
  price: number;
  tiers?: OutputPricingTier[];
}

interface OutputPricing {
  image?: OutputPricingCategory;
  video?: OutputPricingCategory;
  audio?: OutputPricingCategory;
}

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
  output_pricing: OutputPricing | null;
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
  is_active: boolean;
}

interface Provider {
  id: number;
  name: string;
  type: string;
  description: string;
  base_url: string;
  api_key: string;
  group_id: number;
  authorization: string;
  tags: string[];
  extra_config: Record<string, any>;
  is_active: boolean;
  models: Model[];
}

interface Group {
  id: number;
  name: string;
  description: string;
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
  output_pricing?: OutputPricing | null;
  input_price: number;
  output_price: number;
  cache_creation_price: number;
  cache_hit_price: number;
  currency: string;
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

// ── Helpers & small components ────────────────────────────────────────────────

/** Map provider type (from DB / form) to the template `provider` value(s).
 *  Some provider types don't match their template provider name 1:1, e.g.
 *  the "gemini" provider type uses templates labelled "Google". */
const PROVIDER_TYPE_TO_TEMPLATE: Record<string, string[]> = {
  gemini: ['Google'],
  deepseek: ['DeepSeek'],
};

/** Return the subset of model templates that match a given provider type.
 *  For "openai_chatcompletions_compt" and "openai_responses_compt" all
 *  templates are returned so users can pick any model. */
const filterTemplatesByProviderType = (
  templates: ModelTemplate[],
  providerType: string,
): ModelTemplate[] => {
  const pt = providerType.toLowerCase();
  if (['openai_chatcompletions_compt', 'openai_responses_compt'].includes(pt)) {
    return templates;
  }
  const mapped = PROVIDER_TYPE_TO_TEMPLATE[pt];
  if (mapped) {
    return templates.filter((t) => mapped.some((m) => m.toLowerCase() === t.provider.toLowerCase()));
  }
  return templates.filter((t) => t.provider.toLowerCase() === pt);
};

const currencySymbol = (c?: string) =>
  ({ USD: '$', CNY: '¥', EUR: '€', GBP: '£', JPY: '¥' }[c || 'USD'] || '$');

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
  return <span className={`px-2.5 py-1 rounded-lg text-xs font-medium ${colors[color]}`}>{label}</span>;
};

const defaultModelState = {
  name: '',
  alias: '',
  context_size: 4096,
  input_size: 4096,
  output_size: 4096,
  reasoning_effort: '',
  supported_image_formats: '',
  pricing_tiers: null as PricingTier[] | null,
  output_pricing: null as OutputPricing | null,
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

// ── ModelCard ─────────────────────────────────────────────────────────────────

const ModelCard = ({ model, onEdit, onDelete, onToggle }: { model: Model; onEdit: () => void; onDelete: () => void; onToggle: () => void }) => {
  const sym = currencySymbol(model.currency);
  const hasTiers = model.pricing_tiers && model.pricing_tiers.length > 0 && !model.output_pricing;

  return (
    <div className={`bg-white p-5 rounded-xl border border-slate-200 hover:shadow-md transition-all duration-300 ${!model.is_active ? 'opacity-60' : ''}`}>
      <div className="flex justify-between items-start">
        <div className="flex-1">
          <div className="flex items-center space-x-3 flex-wrap gap-y-1">
            <div className="w-10 h-10 bg-slate-100 rounded-lg flex items-center justify-center shrink-0">
              <Cpu className="w-5 h-5 text-slate-600" />
            </div>
            <h5 className="font-semibold text-slate-800">{model.name}</h5>
            {!model.is_active && <span className="bg-red-100 text-red-600 px-2 py-0.5 rounded text-xs font-semibold">Disabled</span>}
            {model.alias && <span className="bg-cyan-100 text-cyan-700 px-2 py-0.5 rounded text-xs font-medium">@{model.alias}</span>}
            {model.currency && model.currency !== 'USD' && <span className="bg-violet-100 text-violet-700 px-2 py-0.5 rounded text-xs font-medium">{model.currency}</span>}
            {hasTiers && <span className="bg-amber-100 text-amber-700 px-2 py-0.5 rounded text-xs font-medium">{model.pricing_tiers!.length} tiers</span>}
            {model.is_retired && <span className="bg-red-100 text-red-700 px-2 py-0.5 rounded text-xs font-medium">Retired</span>}
            {!model.is_retired && model.retirement_time && <span className="bg-orange-100 text-orange-700 px-2 py-0.5 rounded text-xs font-medium">Retires {new Date(model.retirement_time).toLocaleDateString()}</span>}
          </div>

          {hasTiers ? (
            <div className="mt-4">
              <div className="grid grid-cols-2 gap-4 text-sm mb-3">
                <div className="bg-slate-50 p-3 rounded-lg"><span className="text-slate-400 block text-xs mb-1">Context</span><span className="text-slate-700 font-medium">{model.context_size?.toLocaleString()}</span></div>
                <div className="bg-slate-50 p-3 rounded-lg"><span className="text-slate-400 block text-xs mb-1">Input Size</span><span className="text-slate-700 font-medium">{model.input_size?.toLocaleString()}</span></div>
              </div>
              <div className="bg-amber-50 border border-amber-200 rounded-lg p-3">
                <span className="text-amber-600 text-xs font-semibold block mb-2">Tiered Pricing ({model.currency || 'USD'})</span>
                <div className="space-y-1.5">
                  {model.pricing_tiers!.map((tier, i) => (
                    <div key={i} className="flex flex-wrap gap-3 text-sm text-slate-600">
                      <span className="text-slate-500 text-xs font-medium min-w-[80px]">{tier.label || `Tier ${i + 1}`}</span>
                      <span><span className="text-slate-400 text-xs mr-1">ctx</span>{tier.context_size?.toLocaleString()}</span>
                      <span><span className="text-slate-400 text-xs mr-1">in</span>{sym}{tier.input_price}/M</span>
                      <span><span className="text-slate-400 text-xs mr-1">out</span>{sym}{tier.output_price}/M</span>
                      {tier.cache_hit_price > 0 && <span><span className="text-slate-400 text-xs mr-1">cache↓</span>{sym}{tier.cache_hit_price}/M</span>}
                      {tier.cache_creation_price > 0 && <span><span className="text-slate-400 text-xs mr-1">cache↑</span>{sym}{tier.cache_creation_price}/M</span>}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4 text-sm">
              <div className="bg-slate-50 p-3 rounded-lg"><span className="text-slate-400 block text-xs mb-1">Context</span><span className="text-slate-700 font-medium">{model.context_size?.toLocaleString()}</span></div>
              <div className="bg-slate-50 p-3 rounded-lg"><span className="text-slate-400 block text-xs mb-1">Input Size</span><span className="text-slate-700 font-medium">{model.input_size?.toLocaleString()}</span></div>
              <div className="bg-slate-50 p-3 rounded-lg"><span className="text-slate-400 block text-xs mb-1">Input Price</span><span className="text-slate-700 font-medium">{sym}{model.input_price}/M {model.currency || 'USD'}</span></div>
              <div className="bg-slate-50 p-3 rounded-lg"><span className="text-slate-400 block text-xs mb-1">Output Price</span><span className="text-slate-700 font-medium">{sym}{model.output_price}/M {model.currency || 'USD'}</span></div>
            </div>
          )}

          {/* Output Pricing display */}
          {model.output_pricing && (
            <div className="mt-4">
              {(['image', 'video', 'audio'] as const).map((cat) => {
                const catConfig = model.output_pricing?.[cat];
                if (!catConfig) return null;
                const catLabel = cat.charAt(0).toUpperCase() + cat.slice(1);
                const typeLabel = catConfig.type === 'per_image' ? '/image' : catConfig.type === 'per_second' ? '/s' : '/M tokens';
                return (
                  <div key={cat} className="bg-blue-50 border border-blue-200 rounded-lg p-3 mb-2">
                    <span className="text-blue-600 text-xs font-semibold block mb-1">
                      {catLabel} Output — {catConfig.type === 'per_token' ? 'Per Token' : catConfig.type === 'per_image' ? 'Per Image' : 'Per Second'} ({model.currency || 'USD'})
                    </span>
                    {catConfig.tiers && catConfig.tiers.length > 0 ? (
                      <div className="space-y-1">
                        {catConfig.tiers.map((tier, i) => (
                          <div key={i} className="flex items-center gap-3 text-sm text-slate-600">
                            <span className="text-slate-500 text-xs font-medium min-w-[50px]">{tier.resolution}</span>
                            <span>{sym}{tier.price}{typeLabel}</span>
                            {cat === 'video' && tier.audio && <span className="text-xs text-slate-400">+audio</span>}
                            {cat === 'video' && tier.reference_video && <span className="text-xs text-slate-400">+ref_video</span>}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <span className="text-sm text-slate-600">{sym}{catConfig.price}{typeLabel}</span>
                    )}
                  </div>
                );
              })}
            </div>
          )}

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
        <div className="flex items-center space-x-1 ml-4">
          <button
            onClick={onToggle}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-blue-500/20 ${model.is_active ? 'bg-emerald-500' : 'bg-slate-300'}`}
            title={model.is_active ? 'Disable Model' : 'Enable Model'}
          >
            <span
              className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow-sm transition-transform duration-200 ${model.is_active ? 'translate-x-[18px]' : 'translate-x-[3px]'}`}
            />
          </button>
          <button onClick={onEdit} className="text-slate-400 hover:text-blue-600 p-2 hover:bg-blue-50 rounded-lg transition-colors" title="Edit Model"><Edit2 className="w-4 h-4" /></button>
          <button onClick={onDelete} className="text-slate-400 hover:text-red-600 p-2 hover:bg-red-50 rounded-lg transition-colors" title="Delete Model"><Trash2 className="w-4 h-4" /></button>
        </div>
      </div>
    </div>
  );
};

// ── ModelForm ─────────────────────────────────────────────────────────────────

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

  const applyTemplate = (tpl: ModelTemplate) => {
    setModel({
      ...model,
      name: tpl.name,
      alias: tpl.alias || '',
      context_size: tpl.context_size,
      input_size: tpl.input_size,
      output_size: tpl.output_size ?? 4096,
      input_price: tpl.input_price,
      output_price: tpl.output_price,
      cache_creation_price: tpl.cache_creation_price,
      cache_hit_price: tpl.cache_hit_price,
      pricing_tiers: tpl.pricing_tiers,
      output_pricing: tpl.output_pricing ?? null,
      currency: tpl.currency || 'USD',
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

  const pricingTiers: PricingTier[] | null = model.pricing_tiers ?? null;

  return (
    <div className="bg-white p-5 rounded-xl border border-slate-200 mb-3">
      {/* Template selector */}
      <div className="mb-4 pb-4 border-b border-slate-100">
        <label className="block text-sm font-medium text-slate-700 mb-2">
          Quick Fill from Template <span className="text-slate-400 font-normal">(optional)</span>
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
            applyTemplate(tpl);
          }}
        >
          <option value="">— Select a template —</option>
          {templateProviders.map((providerName) => (
            <optgroup key={providerName} label={providerName}>
              {templates
                .filter((tpl) => tpl.provider === providerName)
                .map((tpl) => (
                  <option key={tpl.id} value={tpl.id}>{tpl.label}</option>
                ))}
            </optgroup>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
        {[
          { label: 'Model Name *', key: 'name', type: 'text', placeholder: 'gpt-4, claude-3…' },
          { label: 'Alias (for API access)', key: 'alias', type: 'text', placeholder: 'my-gpt4…' },
          { label: 'Context Size', key: 'context_size', type: 'number' },
          { label: 'Input Size', key: 'input_size', type: 'number' },
          { label: 'Output Size', key: 'output_size', type: 'number' },
          { label: 'Reasoning Effort (none/low/medium/high)', key: 'reasoning_effort', type: 'text', placeholder: 'none' },
          { label: 'Input Price ($/M)', key: 'input_price', type: 'number', step: '0.01' },
          { label: 'Output Price ($/M)', key: 'output_price', type: 'number', step: '0.01' },
          { label: 'Cache Create ($/M)', key: 'cache_creation_price', type: 'number', step: '0.01' },
          { label: 'Cache Hit ($/M)', key: 'cache_hit_price', type: 'number', step: '0.01' },
        ].map(({ label, key, type, placeholder, step }) => (
          <div key={key}>
            <label className="block text-sm font-medium text-slate-700 mb-2">{label}</label>
            <input
              type={type}
              step={step}
              placeholder={placeholder}
              className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
              value={model[key] ?? ''}
              onChange={(e) => {
                const val = type === 'number' ? (parseFloat(e.target.value) || 0) : (e.target.value || null);
                setModel({ ...model, [key]: val });
              }}
            />
          </div>
        ))}
        {/* Supported Image Formats — spans 2 cols */}
        <div className="md:col-span-2">
          <label className="block text-sm font-medium text-slate-700 mb-2">
            Supported Image Formats <span className="text-slate-400 font-normal">(comma-separated)</span>
          </label>
          <input
            placeholder="png,jpeg,webp,gif (leave blank for no restriction)"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            value={model.supported_image_formats || ''}
            onChange={(e) => setModel({ ...model, supported_image_formats: e.target.value || null })}
          />
        </div>
        {/* Currency */}
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
        {/* Retirement date — spans 2 cols */}
        <div className="md:col-span-2">
          <label className="block text-sm font-medium text-slate-700 mb-2">
            Retirement Date <span className="text-slate-400 font-normal text-xs">(optional)</span>
          </label>
          <input
            type="datetime-local"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            value={model.retirement_time ? model.retirement_time.slice(0, 16) : ''}
            onChange={(e) => setModel({ ...model, retirement_time: e.target.value ? e.target.value + ':00' : null })}
          />
        </div>
      </div>

      {/* Pricing Tiers editor */}
      <div className="mb-4">
        <div className="flex items-center justify-between mb-2">
          <label className="block text-sm font-semibold text-slate-700">
            Pricing Tiers <span className="text-slate-400 font-normal text-xs">(optional — for models with context-size-based pricing)</span>
          </label>
          <button
            type="button"
            onClick={() =>
              setModel({
                ...model,
                pricing_tiers: [
                  ...(pricingTiers ?? []),
                  {
                    label: '',
                    context_size: model.context_size || 4096,
                    input_size: model.input_size || 4096,
                    output_size: model.output_size || 4096,
                    input_price: model.input_price || 0,
                    output_price: model.output_price || 0,
                    cache_creation_price: model.cache_creation_price || 0,
                    cache_hit_price: model.cache_hit_price || 0,
                  },
                ],
              })
            }
            className="text-xs bg-blue-50 text-blue-600 px-2 py-1 rounded-lg hover:bg-blue-100 transition-colors"
          >
            + Add Tier
          </button>
        </div>
        {pricingTiers && pricingTiers.length > 0 ? (
          <div className="space-y-3">
            {pricingTiers.map((tier, idx) => (
              <div key={idx} className="bg-slate-50 p-3 rounded-xl border border-slate-200">
                <div className="flex items-center justify-between mb-2">
                  <input
                    placeholder="Tier label, e.g. ≤128k ctx"
                    className="flex-1 p-2 bg-white border border-slate-200 rounded-lg text-sm mr-2 focus:border-blue-500 focus:ring-1 focus:ring-blue-500/20"
                    value={tier.label}
                    onChange={(e) => {
                      const tiers = [...pricingTiers];
                      tiers[idx] = { ...tiers[idx], label: e.target.value };
                      setModel({ ...model, pricing_tiers: tiers });
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => {
                      const tiers = pricingTiers.filter((_, i) => i !== idx);
                      setModel({ ...model, pricing_tiers: tiers.length > 0 ? tiers : null });
                    }}
                    className="text-slate-400 hover:text-red-500 text-xs px-2 py-1 hover:bg-red-50 rounded-lg"
                  >
                    Remove
                  </button>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                  {[
                    { k: 'context_size', label: 'Context Size', type: 'int' },
                    { k: 'input_size', label: 'Input Size', type: 'int' },
                    { k: 'output_size', label: 'Output Size', type: 'int' },
                    { k: 'input_price', label: 'Input $/M', type: 'float' },
                    { k: 'output_price', label: 'Output $/M', type: 'float' },
                    { k: 'cache_creation_price', label: 'Cache↑ $/M', type: 'float' },
                    { k: 'cache_hit_price', label: 'Cache↓ $/M', type: 'float' },
                  ].map(({ k, label, type }) => (
                    <div key={k}>
                      <label className="block text-xs text-slate-500 mb-1">{label}</label>
                      <input
                        type="number"
                        step={type === 'float' ? '0.01' : '1'}
                        className="w-full p-2 bg-white border border-slate-200 rounded-lg text-xs focus:border-blue-500 focus:ring-1 focus:ring-blue-500/20"
                        value={(tier as any)[k]}
                        onChange={(e) => {
                          const tiers = [...pricingTiers];
                          tiers[idx] = { ...tiers[idx], [k]: type === 'float' ? parseFloat(e.target.value) || 0 : parseInt(e.target.value) || 0 };
                          setModel({ ...model, pricing_tiers: tiers });
                        }}
                      />
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-slate-400 italic">No tiers — single flat pricing used.</p>
        )}
      </div>

      {/* Output Pricing editor */}
      <div className="mb-4">
        <label className="block text-sm font-semibold text-slate-700 mb-2">
          Output Pricing <span className="text-slate-400 font-normal text-xs">(optional — for image / video / audio generation models)</span>
        </label>
        {(['image', 'video', 'audio'] as const).map((category) => {
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
          };
          const tierResolutionHints: Record<string, string[]> = {
            image: ['512', '1K', '2K', '3K', '4K'],
            video: ['720p', '1080p', '2K', '4K'],
            audio: ['low', 'standard', 'high'],
          };
          const op: OutputPricing = model.output_pricing ?? {};
          const cat: OutputPricingCategory | undefined = op[category];
          const enabled = !!cat;

          const updateCategory = (patch: Partial<OutputPricingCategory> | null) => {
            const newOp = { ...op };
            if (patch === null) {
              delete newOp[category];
            } else {
              newOp[category] = { ...(cat ?? { type: typeOptions[category][0].value, price: 0 }), ...patch };
            }
            // If all categories removed, set output_pricing to null
            const hasAny = newOp.image || newOp.video || newOp.audio;
            setModel({ ...model, output_pricing: hasAny ? newOp : null });
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
                  <span className="text-sm font-medium text-slate-700 capitalize">{category} Output Pricing</span>
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
                        Base Price {cat.type === 'per_token' ? '($/M tokens)' : cat.type === 'per_image' ? '($ per image)' : '($ per second)'}
                      </label>
                      <input
                        type="number"
                        step="0.0001"
                        className="w-full p-2 bg-white border border-slate-200 rounded-lg text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500/20"
                        value={cat.price}
                        onChange={(e) => updateCategory({ price: parseFloat(e.target.value) || 0 })}
                      />
                    </div>
                  </div>
                  {/* Resolution tiers */}
                  {(
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
                                  value={tier.price}
                                  onChange={(e) => {
                                    const tiers = [...(cat.tiers ?? [])];
                                    tiers[idx] = { ...tiers[idx], price: parseFloat(e.target.value) || 0 };
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
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Rate limits & discount */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-4">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">RPM <span className="text-slate-400 font-normal text-xs">(req/min, blank=∞)</span></label>
          <input type="number" min="0" placeholder="unlimited" className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all" value={model.rpm ?? ''} onChange={(e) => setModel({ ...model, rpm: e.target.value ? parseInt(e.target.value) : null })} />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">TPM <span className="text-slate-400 font-normal text-xs">(tok/min, blank=∞)</span></label>
          <input type="number" min="0" placeholder="unlimited" className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all" value={model.tpm ?? ''} onChange={(e) => setModel({ ...model, tpm: e.target.value ? parseInt(e.target.value) : null })} />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">Discount <span className="text-slate-400 font-normal text-xs">(1.0=full)</span></label>
          <input type="number" step="0.01" min="0" max="1" className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all" value={model.discount ?? 1.0} onChange={(e) => setModel({ ...model, discount: parseFloat(e.target.value) || 1.0 })} />
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
        <button onClick={onCancel} className="bg-slate-100 text-slate-600 px-5 py-2.5 rounded-xl text-sm hover:bg-slate-200 transition-colors">
          Cancel
        </button>
      </div>
    </div>
  );
};

// ── Main Component ────────────────────────────────────────────────────────────

/** When groupId is provided the component acts as an embedded panel (GroupDetail).
 *  When omitted it acts as a standalone page showing all providers with a group selector. */
const ProviderList = ({ groupId }: { groupId?: number } = {}) => {
  const queryClient = useQueryClient();
  const [showProviderModal, setShowProviderModal] = useState(false);
  const [editingProvider, setEditingProvider] = useState<Provider | null>(null);
  const [newProvider, setNewProvider] = useState<ProviderFormData & { group_id: number }>({
    name: '', type: 'openai', description: '', base_url: '', api_key: '',
    group_id: groupId ?? 0, authorization: 'Authorization',
    tags: [], extra_config: {},
  });
  const [expandedProvider, setExpandedProvider] = useState<number | null>(null);
  const [showAddModel, setShowAddModel] = useState<number | null>(null);
  const [editingModel, setEditingModel] = useState<Model | null>(null);
  const [newModel, setNewModel] = useState(defaultModelState);

  const providersQueryKey = groupId ? ['providers', 'group', groupId] : ['providers'];

  const { data: modelTemplates = [] } = useQuery({
    queryKey: ['model-templates'],
    queryFn: async () => {
      const response = await client.get('/api/model-templates/');
      return response.data as ModelTemplate[];
    },
  });

  const { data: providers, isLoading } = useQuery({
    queryKey: providersQueryKey,
    queryFn: async () => {
      const params = groupId ? { group_id: groupId } : undefined;
      const response = await client.get('/api/providers/', { params });
      return response.data as Provider[];
    },
  });

  // Only fetch groups when NOT scoped (standalone page needs a group selector)
  const { data: groups } = useQuery({
    queryKey: ['groups'],
    queryFn: async () => {
      const response = await client.get('/api/groups/');
      return response.data as Group[];
    },
    enabled: !groupId,
  });

  const resetNewProvider = () =>
    setNewProvider({
      name: '', type: 'openai', description: '', base_url: '', api_key: '',
      group_id: groupId ?? 0, authorization: 'Authorization', tags: [], extra_config: {},
    });

  const openAddModal = () => {
    resetNewProvider();
    setEditingProvider(null);
    setShowProviderModal(true);
  };

  const openEditModal = (provider: Provider) => {
    setEditingProvider(provider);
    setShowProviderModal(true);
  };

  const closeModal = () => {
    setShowProviderModal(false);
    setEditingProvider(null);
  };

  const createProviderMutation = useMutation({
    mutationFn: (provider: any) => client.post('/api/providers/', provider),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: providersQueryKey });
      closeModal();
      resetNewProvider();
    },
  });

  const updateProviderMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: any }) => client.put(`/api/providers/${id}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: providersQueryKey });
      closeModal();
    },
  });

  const deleteProviderMutation = useMutation({
    mutationFn: (id: number) => client.delete(`/api/providers/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: providersQueryKey }),
  });

  const createModelMutation = useMutation({
    mutationFn: (model: any) => client.post('/api/models/', model),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: providersQueryKey });
      setShowAddModel(null);
      setNewModel(defaultModelState);
    },
  });

  const updateModelMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: any }) => client.put(`/api/models/${id}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: providersQueryKey });
      setEditingModel(null);
    },
  });

  const deleteModelMutation = useMutation({
    mutationFn: (id: number) => client.delete(`/api/models/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: providersQueryKey }),
  });

  const toggleProviderMutation = useMutation({
    mutationFn: ({ id, is_active }: { id: number; is_active: boolean }) =>
      client.put(`/api/providers/${id}`, { is_active }),
    onMutate: async ({ id, is_active }) => {
      await queryClient.cancelQueries({ queryKey: providersQueryKey });
      const previous = queryClient.getQueryData<Provider[]>(providersQueryKey);
      queryClient.setQueryData<Provider[]>(providersQueryKey, (old) =>
        old?.map((p) => (p.id === id ? { ...p, is_active } : p))
      );
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) queryClient.setQueryData(providersQueryKey, context.previous);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: providersQueryKey }),
  });

  const toggleModelMutation = useMutation({
    mutationFn: ({ id, is_active }: { id: number; is_active: boolean }) =>
      client.put(`/api/models/${id}`, { is_active }),
    onMutate: async ({ id, is_active }) => {
      await queryClient.cancelQueries({ queryKey: providersQueryKey });
      const previous = queryClient.getQueryData<Provider[]>(providersQueryKey);
      queryClient.setQueryData<Provider[]>(providersQueryKey, (old) =>
        old?.map((p) => ({
          ...p,
          models: p.models.map((m) => (m.id === id ? { ...m, is_active } : m)),
        }))
      );
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) queryClient.setQueryData(providersQueryKey, context.previous);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: providersQueryKey }),
  });

  const handleEditModel = (model: Model) => {
    setEditingModel(model);
    setShowAddModel(null);
  };

  // ── Shared Provider Modal ────────────────────────────────────────────────────
  const providerModal = showProviderModal && (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="p-6 border-b border-slate-200 sticky top-0 bg-white rounded-t-2xl">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-3">
              <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-lg flex items-center justify-center">
                <Database className="w-5 h-5 text-white" />
              </div>
              <div>
                <h2 className="text-lg font-bold text-slate-800">
                  {editingProvider ? 'Edit Provider' : 'Add Provider'}
                </h2>
                <p className="text-sm text-slate-500">
                  {editingProvider ? editingProvider.name : 'Configure a new AI provider'}
                </p>
              </div>
            </div>
            <button onClick={closeModal} className="text-slate-400 hover:text-slate-600 p-1 hover:bg-slate-100 rounded-lg transition-colors">
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>
        <div className="p-6">
          <ProviderFormFields
            data={editingProvider ?? newProvider}
            onChange={(updated: ProviderFormData) =>
              editingProvider
                ? setEditingProvider({ ...editingProvider, ...updated })
                : setNewProvider({ ...newProvider, ...updated, group_id: groupId ?? newProvider.group_id })
            }
            groups={groupId === undefined ? (groups ?? []) : undefined}
          />
          <div className="mt-6 flex space-x-3 pt-4 border-t border-slate-200">
            <button
              onClick={() => {
                if (editingProvider) {
                  updateProviderMutation.mutate({ id: editingProvider.id, data: editingProvider });
                } else {
                  createProviderMutation.mutate(
                    groupId !== undefined ? { ...newProvider, group_id: groupId } : newProvider
                  );
                }
              }}
              disabled={editingProvider ? updateProviderMutation.isPending : createProviderMutation.isPending}
              className="bg-emerald-500 text-white px-5 py-2.5 rounded-xl flex items-center hover:bg-emerald-600 disabled:bg-slate-300 disabled:cursor-not-allowed transition-colors shadow-sm"
            >
              <Save className="w-4 h-4 mr-2" />
              {(editingProvider ? updateProviderMutation.isPending : createProviderMutation.isPending) ? 'Saving...' : 'Save'}
            </button>
            <button onClick={closeModal} className="bg-slate-100 text-slate-600 px-5 py-2.5 rounded-xl hover:bg-slate-200 transition-colors">
              Cancel
            </button>
          </div>
        </div>
      </div>
    </div>
  );

  if (isLoading) return (
    <div className="flex justify-center items-center h-64">
      <div className="text-slate-500">Loading...</div>
    </div>
  );

  // ── Provider list (shared rendering) ────────────────────────────────────────
  const providerListContent = (
    <div className="space-y-4">
      {providers?.map((provider) => (
        <div key={provider.id} className={`bg-white rounded-2xl shadow-sm border overflow-hidden transition-all duration-300 ${provider.is_active ? 'border-slate-200' : 'border-slate-200 opacity-60'}`}>
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
                    <><LinkIcon className="w-3 h-3 mr-1" />{provider.base_url}</>
                  ) : 'No base URL configured'}
                </p>
              </div>
            </div>
            <div className="flex items-center space-x-2" onClick={(e) => e.stopPropagation()}>
              {!provider.is_active && (
                <span className="bg-red-100 text-red-600 px-2.5 py-1 rounded-lg text-xs font-semibold mr-1">
                  Disabled
                </span>
              )}
              <span className="bg-blue-100 text-blue-700 px-3 py-1 rounded-lg text-sm font-medium mr-2">
                {provider.models.length} models
              </span>
              {/* Toggle switch */}
              <button
                onClick={() => toggleProviderMutation.mutate({ id: provider.id, is_active: !provider.is_active })}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-blue-500/20 ${provider.is_active ? 'bg-emerald-500' : 'bg-slate-300'}`}
                title={provider.is_active ? 'Disable Provider' : 'Enable Provider'}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white shadow-sm transition-transform duration-200 ${provider.is_active ? 'translate-x-6' : 'translate-x-1'}`}
                />
              </button>
              <button
                onClick={() => openEditModal(provider)}
                className="text-slate-400 hover:text-blue-600 p-2 hover:bg-blue-50 rounded-lg transition-colors"
                title="Edit Provider"
              >
                <Edit2 className="w-4 h-4" />
              </button>
              <button
                onClick={() => { if (confirm('Are you sure you want to delete this provider?')) deleteProviderMutation.mutate(provider.id); }}
                className="text-slate-400 hover:text-red-600 p-2 hover:bg-red-50 rounded-lg transition-colors"
                title="Delete Provider"
              >
                <Trash2 className="w-4 h-4" />
              </button>
              {expandedProvider === provider.id
                ? <ChevronUp className="w-5 h-5 text-slate-400 ml-2" />
                : <ChevronDown className="w-5 h-5 text-slate-400 ml-2" />}
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

              {showAddModel === provider.id && (
                <ModelForm
                  model={newModel}
                  setModel={setNewModel}
                  onSave={() => createModelMutation.mutate({ ...newModel, provider_id: provider.id })}
                  onCancel={() => { setShowAddModel(null); setNewModel(defaultModelState); }}
                  isLoading={createModelMutation.isPending}
                  templates={filterTemplatesByProviderType(modelTemplates, provider.type)}
                />
              )}

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
                        templates={filterTemplatesByProviderType(modelTemplates, provider.type)}
                      />
                    ) : (
                      <ModelCard
                        model={model}
                        onEdit={() => handleEditModel(model)}
                        onDelete={() => { if (confirm('Are you sure you want to delete this model?')) deleteModelMutation.mutate(model.id); }}
                        onToggle={() => toggleModelMutation.mutate({ id: model.id, is_active: !model.is_active })}
                      />
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
      {(!providers || providers.length === 0) && (
        <div className="text-center py-12 text-slate-500 bg-white rounded-2xl border border-slate-200">
          <Database className="w-16 h-16 mx-auto mb-4 text-slate-300" />
          <p className="text-lg font-medium text-slate-700">No providers configured yet.</p>
          <p className="text-sm mt-2">Click "Add Provider" to add your first AI provider.</p>
        </div>
      )}
    </div>
  );

  // ── Embedded mode (inside GroupDetail) ──────────────────────────────────────
  if (groupId !== undefined) {
    return (
      <>
        {providerModal}
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <p className="text-sm text-slate-500">{providers?.length || 0} providers</p>
            <button
              onClick={openAddModal}
              className="bg-blue-500 text-white px-4 py-2 rounded-xl flex items-center hover:bg-blue-600 transition-colors shadow-sm text-sm"
            >
              <Plus className="w-4 h-4 mr-2" /> Add Provider
            </button>
          </div>
          {providerListContent}
        </div>
      </>
    );
  }

  // ── Standalone page mode ─────────────────────────────────────────────────────
  return (
    <>
      {providerModal}
      <div className="space-y-6">
        <div className="flex justify-between items-center">
          <div>
            <h1 className="text-2xl font-bold text-slate-800">Providers & Models</h1>
            <p className="text-slate-500 mt-1">Manage your AI providers and their models</p>
          </div>
          <button
            onClick={openAddModal}
            className="bg-gradient-to-r from-blue-500 to-indigo-600 text-white px-5 py-2.5 rounded-xl flex items-center hover:from-blue-600 hover:to-indigo-700 transition-all shadow-lg shadow-blue-500/25"
          >
            <Plus className="w-4 h-4 mr-2" /> Add Provider
          </button>
        </div>
        {providerListContent}
      </div>
    </>
  );
};

export default ProviderList;
