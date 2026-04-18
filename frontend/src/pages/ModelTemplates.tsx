import { useState, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import client from '../api/client';
import { Plus, Edit2, Trash2, Save, LayoutTemplate, Search, X, RefreshCw } from 'lucide-react';

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
  input_price: 0,
  output_price: 0,
  cache_creation_price: 0,
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
});

const FEATURES = [
  { key: 'support_kvcache', label: 'KV Cache' },
  { key: 'support_image', label: 'Image' },
  { key: 'support_audio', label: 'Audio' },
  { key: 'support_video', label: 'Video' },
  { key: 'support_file', label: 'File' },
  { key: 'support_web_search', label: 'Web Search' },
  { key: 'support_tool_search', label: 'Tool Search' },
  { key: 'support_thinking', label: 'Thinking' },
  { key: 'support_online_image', label: 'Online Image URL' },
  { key: 'support_online_video', label: 'Online Video URL' },
  { key: 'support_embedding', label: 'Embedding' },
];

const ALL_TAB = '__ALL__';

/* ─── Derive model family from template label ─── */
function getModelFamily(label: string): string {
  const lower = label.toLowerCase();
  if (lower.startsWith('gpt-') || lower.startsWith('gpt ')) return 'GPT';
  if (lower.startsWith('claude')) return 'Claude';
  if (lower.startsWith('gemini')) return 'Gemini';
  if (lower.startsWith('deepseek') || lower.includes('deepseek')) return 'DeepSeek';
  if (lower.startsWith('kimi')) return 'Kimi';
  if (lower.startsWith('glm')) return 'GLM';
  if (lower.startsWith('qwen')) return 'Qwen';
  if (lower.startsWith('minimax')) return 'MiniMax';
  if (lower.startsWith('doubao')) return 'Doubao';
  if (lower.includes('embedding')) return 'Embedding';
  // Fallback: first word of label
  return label.split(/[\s\-]/)[0];
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
  const set = (patch: Partial<Omit<ModelTemplate, 'id'>>) => onChange({ ...value, ...patch });

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6 space-y-5">
      {/* Basic identity */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Label *</label>
          <input
            placeholder="GPT-4o"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
            value={value.label}
            onChange={(e) => set({ label: e.target.value })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Provider *</label>
          <input
            placeholder="OpenAI"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
            value={value.provider}
            onChange={(e) => set({ provider: e.target.value })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Model Name *</label>
          <input
            placeholder="gpt-4o"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
            value={value.name}
            onChange={(e) => set({ name: e.target.value })}
          />
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Alias</label>
          <input
            placeholder="gpt-4o"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
            value={value.alias || ''}
            onChange={(e) => set({ alias: e.target.value || null })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Context Size</label>
          <input
            type="number"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
            value={value.context_size}
            onChange={(e) => set({ context_size: parseInt(e.target.value) || 0 })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Input Size</label>
          <input
            type="number"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
            value={value.input_size}
            onChange={(e) => set({ input_size: parseInt(e.target.value) || 0 })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Output Size</label>
          <input
            type="number"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
            value={value.output_size ?? 4096}
            onChange={(e) => set({ output_size: parseInt(e.target.value) || 0 })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Reasoning Effort</label>
          <input
            placeholder="low / medium / high"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
            value={value.reasoning_effort || ''}
            onChange={(e) => set({ reasoning_effort: e.target.value || null })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Image Formats</label>
          <input
            placeholder="png,jpeg,webp"
            className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
            value={value.supported_image_formats || ''}
            onChange={(e) => set({ supported_image_formats: e.target.value || null })}
          />
        </div>
      </div>

      {/* Pricing Tiers */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold text-slate-700">Pricing Tiers <span className="text-slate-400 font-normal text-xs">(optional — for models with context-size-based pricing)</span></h3>
          <button
            type="button"
            onClick={() => set({ pricing_tiers: [...(value.pricing_tiers ?? []), { label: '', context_size: value.context_size, input_size: value.input_size, output_size: value.output_size, input_price: value.input_price, output_price: value.output_price, cache_creation_price: value.cache_creation_price, cache_hit_price: value.cache_hit_price }] })}
            className="text-xs bg-blue-50 text-blue-600 px-2 py-1 rounded-lg hover:bg-blue-100 transition-colors"
          >
            + Add Tier
          </button>
        </div>
        {value.pricing_tiers && value.pricing_tiers.length > 0 ? (
          <div className="space-y-3">
            {value.pricing_tiers.map((tier, idx) => (
              <div key={idx} className="bg-slate-50 p-3 rounded-xl border border-slate-200">
                <div className="flex items-center justify-between mb-2">
                  <input
                    placeholder="Tier label, e.g. <=272k ctx"
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
                          const tiers = [...value.pricing_tiers!];
                          tiers[idx] = { ...tiers[idx], [k]: type === 'float' ? parseFloat(e.target.value) || 0 : parseInt(e.target.value) || 0 };
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
          <p className="text-xs text-slate-400 italic">No tiers — single flat pricing used.</p>
        )}
      </div>

      {/* Pricing */}
      <div>
        <h3 className="text-sm font-semibold text-slate-700 mb-2">Pricing (per 1M tokens)</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Currency</label>
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
            { key: 'input_price', label: 'Input /M' },
            { key: 'output_price', label: 'Output /M' },
            { key: 'cache_creation_price', label: 'Cache Create /M' },
            { key: 'cache_hit_price', label: 'Cache Hit /M' },
          ].map(({ key, label }) => (
            <div key={key}>
              <label className="block text-sm font-medium text-slate-700 mb-1">{label}</label>
              <input
                type="number"
                step="0.01"
                className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                value={(value as any)[key]}
                onChange={(e) => set({ [key]: parseFloat(e.target.value) || 0 } as any)}
              />
            </div>
          ))}
        </div>
      </div>

      {/* Rate limits & discount */}
      <div>
        <h3 className="text-sm font-semibold text-slate-700 mb-2">Rate Limits &amp; Discount</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              RPM
              <span className="text-slate-400 font-normal ml-1 text-xs">(requests/min, blank = unlimited)</span>
            </label>
            <input
              type="number"
              min="0"
              placeholder="unlimited"
              className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
              value={value.rpm ?? ''}
              onChange={(e) => set({ rpm: e.target.value ? parseInt(e.target.value) : null })}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              TPM
              <span className="text-slate-400 font-normal ml-1 text-xs">(tokens/min, blank = unlimited)</span>
            </label>
            <input
              type="number"
              min="0"
              placeholder="unlimited"
              className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
              value={value.tpm ?? ''}
              onChange={(e) => set({ tpm: e.target.value ? parseInt(e.target.value) : null })}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Discount
              <span className="text-slate-400 font-normal ml-1 text-xs">(1.0 = full price, 0.9 = 10% off)</span>
            </label>
            <input
              type="number"
              step="0.01"
              min="0"
              max="1"
              className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
              value={value.discount ?? 1.0}
              onChange={(e) => set({ discount: parseFloat(e.target.value) || 1.0 })}
            />
          </div>
        </div>
      </div>

      {/* Retirement */}
      <div>
        <h3 className="text-sm font-semibold text-slate-700 mb-2">Retirement</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Retirement Date
              <span className="text-slate-400 font-normal ml-1 text-xs">(optional — model cannot be used after this date)</span>
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
        <h3 className="text-sm font-semibold text-slate-700 mb-2">Supported Features</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {FEATURES.map(({ key, label }) => (
            <label key={key} className="flex items-center space-x-2 cursor-pointer p-2 rounded-lg hover:bg-slate-50 transition-colors">
              <input
                type="checkbox"
                checked={!!(value as any)[key]}
                onChange={(e) => set({ [key]: e.target.checked } as any)}
                className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
              />
              <span className="text-sm text-slate-600">{label}</span>
            </label>
          ))}
        </div>
      </div>

      {/* Actions */}
      <div className="flex space-x-3 pt-2 border-t border-slate-100">
        <button
          onClick={onSave}
          disabled={isSaving || !value.label || !value.name || !value.provider}
          className="bg-emerald-500 text-white px-5 py-2.5 rounded-xl text-sm flex items-center hover:bg-emerald-600 disabled:bg-slate-300 disabled:cursor-not-allowed transition-colors shadow-sm"
        >
          <Save className="w-4 h-4 mr-2" /> {isSaving ? 'Saving…' : 'Save'}
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

/* ─── Template card (read-only row) ─── */
const TemplateCard = ({
  tpl,
  onEdit,
  onDelete,
}: {
  tpl: ModelTemplate;
  onEdit: () => void;
  onDelete: () => void;
}) => (
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
              {tpl.pricing_tiers.length} tiers
            </span>
          )}
          {tpl.is_retired && (
            <span className="bg-red-100 text-red-700 px-2 py-0.5 rounded text-xs font-medium">
              Retired
            </span>
          )}
          {!tpl.is_retired && tpl.retirement_time && (
            <span className="bg-orange-100 text-orange-700 px-2 py-0.5 rounded text-xs font-medium">
              Retires {new Date(tpl.retirement_time).toLocaleDateString()}
            </span>
          )}
        </div>

        {/* Pricing row */}
        {tpl.pricing_tiers && tpl.pricing_tiers.length > 0 ? (
          <div className="mt-3 space-y-1">
            {tpl.pricing_tiers.map((tier, i) => (
              <div key={i} className="flex flex-wrap gap-3 text-sm text-slate-600">
                <span className="text-slate-500 text-xs font-medium w-20">{tier.label}</span>
                <span><span className="text-slate-400 text-xs mr-1">ctx</span>{tier.context_size.toLocaleString()}</span>
                <span><span className="text-slate-400 text-xs mr-1">in</span>${tier.input_price}/M</span>
                <span><span className="text-slate-400 text-xs mr-1">out</span>${tier.output_price}/M</span>
                {tier.cache_hit_price > 0 && <span><span className="text-slate-400 text-xs mr-1">cache↓</span>${tier.cache_hit_price}/M</span>}
              </div>
            ))}
          </div>
        ) : (
          <div className="flex flex-wrap gap-4 mt-3 text-sm text-slate-600">
            <span>
              <span className="text-slate-400 text-xs mr-1">ctx</span>
              {tpl.context_size.toLocaleString()}
            </span>
            <span>
              <span className="text-slate-400 text-xs mr-1">in</span>
              ${tpl.input_price}/M
            </span>
            <span>
              <span className="text-slate-400 text-xs mr-1">out</span>
              ${tpl.output_price}/M
            </span>
            {tpl.cache_creation_price > 0 && (
              <span>
                <span className="text-slate-400 text-xs mr-1">cache↑</span>
                ${tpl.cache_creation_price}/M
              </span>
            )}
            {tpl.cache_hit_price > 0 && (
              <span>
                <span className="text-slate-400 text-xs mr-1">cache↓</span>
                ${tpl.cache_hit_price}/M
              </span>
            )}
          </div>
        )}

        {/* Feature badges */}
        <div className="flex flex-wrap gap-1.5 mt-3">
          {FEATURES.filter(({ key }) => !!(tpl as any)[key]).map(({ key, label }) => (
            <span
              key={key}
              className="bg-blue-50 text-blue-700 px-2 py-0.5 rounded text-xs font-medium"
            >
              {label}
            </span>
          ))}
        </div>
      </div>

      {/* Actions */}
      <div className="flex space-x-1 ml-4 shrink-0">
        <button
          onClick={onEdit}
          className="text-slate-400 hover:text-blue-600 p-2 hover:bg-blue-50 rounded-lg transition-colors"
          title="Edit"
        >
          <Edit2 className="w-4 h-4" />
        </button>
        <button
          onClick={onDelete}
          className="text-slate-400 hover:text-red-600 p-2 hover:bg-red-50 rounded-lg transition-colors"
          title="Delete"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
    </div>
  </div>
);

/* ─── Main page ─── */
export default function ModelTemplates() {
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
      alert(`Sync complete: ${added} added, ${updated} updated.`);
    },
    onError: () => {
      alert('Failed to sync templates. Please try again.');
    },
  });

  // Derive unique model families & counts
  const familyTabs = useMemo(() => {
    const countMap = new Map<string, number>();
    for (const t of templates) {
      const family = getModelFamily(t.label);
      countMap.set(family, (countMap.get(family) || 0) + 1);
    }
    // Sort families alphabetically
    const sorted = Array.from(countMap.entries()).sort((a, b) => a[0].localeCompare(b[0]));
    return sorted;
  }, [templates]);

  // Filter templates by active tab (model family) + search query
  const filteredTemplates = useMemo(() => {
    let list = templates;
    if (activeTab !== ALL_TAB) {
      list = list.filter((t) => getModelFamily(t.label) === activeTab);
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      list = list.filter(
        (t) =>
          t.label.toLowerCase().includes(q) ||
          t.name.toLowerCase().includes(q) ||
          (t.alias && t.alias.toLowerCase().includes(q)) ||
          t.provider.toLowerCase().includes(q)
      );
    }
    return list;
  }, [templates, activeTab, searchQuery]);

  // Group filtered templates by provider for display within a family tab
  const groupedByProvider = useMemo(() => {
    const groups = new Map<string, ModelTemplate[]>();
    for (const t of filteredTemplates) {
      if (!groups.has(t.provider)) groups.set(t.provider, []);
      groups.get(t.provider)!.push(t);
    }
    return Array.from(groups.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [filteredTemplates]);

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="text-slate-500">Loading…</div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Model Templates</h1>
          <p className="text-slate-500 mt-1">
            Pre-defined templates that auto-fill the Add Model form.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => seedMutation.mutate()}
            disabled={seedMutation.isPending}
            className="bg-amber-500 text-white px-5 py-2.5 rounded-xl flex items-center hover:bg-amber-600 disabled:bg-slate-300 disabled:cursor-not-allowed transition-all shadow-lg shadow-amber-500/25"
          >
            <RefreshCw className={`w-4 h-4 mr-2 ${seedMutation.isPending ? 'animate-spin' : ''}`} />
            {seedMutation.isPending ? 'Syncing…' : 'Sync Templates'}
          </button>
          <button
            onClick={() => { setShowAdd(true); setEditingTpl(null); }}
            className="bg-gradient-to-r from-blue-500 to-indigo-600 text-white px-5 py-2.5 rounded-xl flex items-center hover:from-blue-600 hover:to-indigo-700 transition-all shadow-lg shadow-blue-500/25"
          >
            <Plus className="w-4 h-4 mr-2" /> Add Template
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
              All
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
              placeholder="Search by model name, label, alias, or provider…"
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
          <p className="text-lg font-medium text-slate-700">No templates yet.</p>
          <p className="text-sm mt-2">Click "Add Template" to create your first one.</p>
        </div>
      ) : filteredTemplates.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-2xl border border-slate-200 text-slate-500">
          <Search className="w-12 h-12 mx-auto mb-3 text-slate-300" />
          <p className="text-lg font-medium text-slate-700">No matching templates</p>
          <p className="text-sm mt-1">
            {searchQuery
              ? `No templates match "${searchQuery}"${activeTab !== ALL_TAB ? ` in ${activeTab}` : ''}.`
              : `No templates found for ${activeTab}.`}
          </p>
          <button
            onClick={() => { setSearchQuery(''); setActiveTab(ALL_TAB); }}
            className="mt-3 text-sm text-blue-600 hover:text-blue-700 font-medium"
          >
            Clear filters
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
                {providerTemplates.length} model{providerTemplates.length !== 1 ? 's' : ''}
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
                    if (confirm(`Delete template "${tpl.label}"?`)) {
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
