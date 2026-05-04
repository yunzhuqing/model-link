import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Copy, Check, ArrowLeft, ImageIcon } from 'lucide-react';
import { useBaseUrl } from '../components/help/HelpShared';

interface TocItem { id: string; label: string }
const TOC_ITEMS: TocItem[] = [
  { id: 'overview', label: '功能说明' },
  { id: 'responses-api', label: 'Responses API（推荐）' },
  { id: 'responses-params', label: '工具参数' },
  { id: 'responses-response', label: '工具响应格式' },
  { id: 'images-api', label: 'Images API' },
  { id: 'images-params', label: 'Images 请求参数' },
  { id: 'images-response', label: 'Images 响应格式' },
  { id: 'edits-api', label: 'Images Edits API' },
  { id: 'edits-params', label: 'Edits 请求参数' },
  { id: 'edits-response', label: 'Edits 响应格式' },
  { id: 'seedream-sizes', label: 'Seedream 尺寸' },
  { id: 'z-image-sizes', label: 'Z-Image 尺寸' },
  { id: 'gemini-sizes', label: 'Gemini 尺寸' },
];

const RESPONSES_REQUEST = `{
  "model": "qwen-image-2.0-pro",
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        {
          "type": "input_text",
          "text": "生成狸花猫的照片"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "image_generation",
      "n": 1,
      "size": "2048x2048"
    }
  ],
  "background": false
}`;

const RESPONSES_RESPONSE = `{
  "id": "img_abc123...",
  "object": "response",
  "status": "completed",
  "model": "qwen-image-2.0-pro",
  "output": [
    {
      "type": "image_generation_call",
      "id": "img_abc123...",
      "status": "completed",
      "result": "https://..."
    }
  ]
}`;

const IMAGES_REQUEST = `{
  "model": "qwen-image-2.0-pro",
  "prompt": "将右边的狗的颜色换成红色",
  "images": [
    {
      "image_url": "https://images.pexels.com/photos/1108099/pexels-photo-1108099.jpeg?auto=compress&cs=tinysrgb&w=800"
    }
  ],
  "n": 1,
  "size": "2048x2048",
  "quality": "auto",
  "background": "auto",
  "output_format": "png"
}`;

const IMAGES_RESPONSE = `{
  "created": 1712345678,
  "data": [
    {
      "url": "https://example.com/generated-image.png",
      "revised_prompt": "一只可爱的狸花猫在阳光下打盹"
    }
  ],
  "output_format": "png"
}`;

const IMAGES_B64_RESPONSE = `{
  "created": 1712345678,
  "data": [
    {
      "b64_json": "data:image/png;base64,iVBORw0KGgo..."
    }
  ],
  "output_format": "png"
}`;

const EDITS_REQUEST = `{
  "model": "doubao-seedream-5.0",
  "prompt": "将右边的狗的颜色换成红色",
  "images": [
    {
      "image_url": "https://images.pexels.com/photos/1108099/pexels-photo-1108099.jpeg?auto=compress&cs=tinysrgb&w=800"
    }
  ],
  "n": 1,
  "size": "2048x2048",
  "quality": "auto",
  "background": "auto",
  "output_format": "png"
}`;

const EDITS_RESPONSE = `{
  "created": 1712345678,
  "data": [
    {
      "url": "https://example.com/edited-image.png",
      "revised_prompt": "将右边的狗的颜色换成红色"
    }
  ],
  "output_format": "png",
  "size": "2048x2048",
  "quality": "auto",
  "background": "opaque"
}`;

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={async () => { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000); }}
      className="absolute top-3 right-3 p-1.5 rounded-md bg-slate-700 hover:bg-slate-600 text-slate-300 hover:text-white transition-colors"
      title="复制"
    >
      {copied ? <Check className="w-4 h-4 text-green-400" /> : <Copy className="w-4 h-4" />}
    </button>
  );
}

function CodeBlock({ code, lang = 'json' }: { code: string; lang?: string }) {
  return (
    <div className="relative">
      <pre className={`language-${lang} bg-slate-900 text-slate-100 rounded-xl p-4 pr-12 text-sm overflow-x-auto leading-relaxed`}>
        <code>{code}</code>
      </pre>
      <CopyButton text={code} />
    </div>
  );
}

function SectionCard({ id, title, description, badge, badgeColor, children }: {
  id: string; title: string; description: string; badge?: string; badgeColor?: string; children: React.ReactNode;
}) {
  return (
    <div id={id} className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
      <div className="p-6 border-b border-slate-100">
        <div className="flex items-center gap-3 mb-1">
          <h3 className="text-lg font-semibold text-slate-800">{title}</h3>
          {badge && <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${badgeColor}`}>{badge}</span>}
        </div>
        <p className="text-sm text-slate-500">{description}</p>
      </div>
      <div className="p-6 space-y-4">{children}</div>
    </div>
  );
}

function CurlSection({ body, endpoint }: { body: string; endpoint?: string }) {
  const baseUrl = useBaseUrl();
  const [show, setShow] = useState(false);
  const url = endpoint || `${baseUrl}/v1/responses`;
  const curl = `curl -X POST ${url} \\\n  -H "Authorization: Bearer <YOUR_API_KEY>" \\\n  -H "Content-Type: application/json" \\\n  -d '${body}'`;
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide">请求体</span>
        <button onClick={() => setShow(v => !v)} className="text-xs text-blue-500 hover:text-blue-700 underline underline-offset-2">
          {show ? '隐藏 cURL' : '查看 cURL'}
        </button>
      </div>
      <CodeBlock code={body} />
      {show && (
        <div className="mt-3">
          <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">cURL 示例</span>
          <CodeBlock code={curl} lang="bash" />
        </div>
      )}
    </div>
  );
}

function TableOfContents({ items }: { items: TocItem[] }) {
  const [active, setActive] = useState(items[0]?.id ?? '');
  const scrollRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    scrollRef.current = document.querySelector('main') as HTMLElement;
    const container = scrollRef.current;
    if (!container) return;
    const onScroll = () => {
      let cur = items[0]?.id ?? '';
      for (const item of items) {
        const el = document.getElementById(item.id);
        if (el) {
          const top = el.getBoundingClientRect().top - container.getBoundingClientRect().top;
          if (top <= 80) cur = item.id;
        }
      }
      setActive(cur);
    };
    container.addEventListener('scroll', onScroll, { passive: true });
    return () => container.removeEventListener('scroll', onScroll);
  }, [items]);

  const scrollTo = (id: string) => {
    const el = document.getElementById(id);
    const container = scrollRef.current;
    if (el && container) {
      const top = el.getBoundingClientRect().top - container.getBoundingClientRect().top;
      container.scrollTo({ top: container.scrollTop + top - 16, behavior: 'smooth' });
    }
  };

  return (
    <aside className="w-52 flex-shrink-0 hidden xl:block">
      <div className="sticky top-0">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3 px-1">本页内容</p>
        <nav className="space-y-0.5">
          {items.map((item) => (
            <button
              key={item.id}
              onClick={() => scrollTo(item.id)}
              className={`w-full text-left px-3 py-1.5 rounded-lg text-sm transition-all duration-150 ${
                active === item.id
                  ? 'bg-pink-50 text-pink-600 font-medium border-l-2 border-pink-500'
                  : 'text-slate-500 hover:text-slate-800 hover:bg-slate-50'
              }`}
            >
              {item.label}
            </button>
          ))}
        </nav>
      </div>
    </aside>
  );
}

export default function HelpImageGeneration() {
  const navigate = useNavigate();
  const baseUrl = useBaseUrl();

  return (
    <div className="flex gap-8 max-w-6xl mx-auto">
      <div className="flex-1 min-w-0 space-y-8">
        {/* Back + header */}
        <div>
          <button
            onClick={() => navigate('/help')}
            className="flex items-center gap-1.5 text-sm text-slate-500 hover:text-pink-600 mb-4 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            返回帮助中心
          </button>
          <div className="flex items-center gap-4">
            <div className="p-3 bg-gradient-to-br from-pink-500 to-rose-600 rounded-2xl shadow-lg shadow-pink-500/25">
              <ImageIcon className="w-7 h-7 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900">图片生成</h1>
              <p className="text-slate-500 text-sm mt-0.5">支持 Responses API 工具调用、Images Generations API 和 Images Edits API</p>
            </div>
          </div>
        </div>

        {/* Overview */}
        <div id="overview" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <h3 className="text-lg font-semibold text-slate-800 mb-1">功能说明</h3>
            <p className="text-sm text-slate-500">提供多种图片生成和编辑方式，可根据场景选择合适的接入方式。</p>
          </div>
          <div className="p-6 space-y-3">
            <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-3 text-sm text-emerald-800">
              <strong>三种接入方式对比：</strong>
              <ul className="mt-1.5 space-y-1 list-disc list-inside text-emerald-700">
                <li><strong className="text-emerald-900">Responses API + image_generation 工具（推荐）</strong> — 对话式图片生成，支持多轮对话上下文、图生图、异步模式</li>
                <li><strong className="text-emerald-900">/v1/images/generations</strong> — OpenAI 兼容接口，参数扁平化，文生图更简洁直接</li>
                <li><strong className="text-emerald-900">/v1/images/edits</strong> — 图片编辑接口，传入原图 + 编辑指令，支持蒙版、背景控制等</li>
              </ul>
            </div>
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">
              <strong>注意：</strong>需要图片生成模型（如 Volcengine 的 seedream 系列、百炼的 qwen-image 系列、Gemini 图像生成模型等）。模型须在管理面板中配置。
            </div>
            <div className="overflow-x-auto rounded-xl border border-slate-200">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left">
                  <tr>
                    <th className="px-4 py-2.5 font-semibold text-slate-600">模型 ID</th>
                    <th className="px-4 py-2.5 font-semibold text-slate-600">输出格式</th>
                    <th className="px-4 py-2.5 font-semibold text-slate-600">输出尺寸范围</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {[
                    { model: 'qwen-image-2.0',                  format: 'png',       size: '512×512 ~ 2048×2048' },
                    { model: 'qwen-image-2.0-pro',               format: 'png',       size: '512×512 ~ 2048×2048' },
                    { model: 'z-image-turbo',                     format: 'png',       size: '1K / 1.5K / 2K（见下方尺寸表）' },
                    { model: 'doubao-seedream-4.0',              format: 'jpeg',      size: '1K ~ 4K（见下方尺寸表）' },
                    { model: 'doubao-seedream-4.5',              format: 'jpeg',      size: '2K ~ 4K（见下方尺寸表）' },
                    { model: 'doubao-seedream-5.0',              format: 'png / jpg', size: '2K ~ 3K（见下方尺寸表）' },
                    { model: 'seedream-4.0',                     format: 'jpeg',      size: '1K ~ 4K（见下方尺寸表）' },
                    { model: 'seedream-4.5',                     format: 'jpeg',      size: '2K ~ 4K（见下方尺寸表）' },
                    { model: 'seedream-5.0',                     format: 'png / jpg', size: '2K ~ 3K（见下方尺寸表）' },
                    { model: 'gemini-2.5-flash-image',           format: 'png / jpg', size: '固定分辨率（见下方尺寸表）' },
                    { model: 'gemini-3-pro-image-preview',       format: 'png / jpg', size: '1K ~ 4K（见下方尺寸表）' },
                    { model: 'gemini-3.1-flash-image-preview',   format: 'png / jpg', size: '512 ~ 4K（见下方尺寸表）' },
                  ].map((r) => (
                    <tr key={r.model} className="hover:bg-slate-50">
                      <td className="px-4 py-2.5"><code className="text-pink-600 font-semibold text-xs">{r.model}</code></td>
                      <td className="px-4 py-2.5 text-slate-600 font-mono text-xs">{r.format}</td>
                      <td className="px-4 py-2.5 text-slate-600 text-xs">{r.size}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* ========== Responses API Section ========== */}
        <div className="flex items-center gap-3">
          <div className="h-px flex-1 bg-pink-200" />
          <span className="text-xs font-semibold text-pink-400 uppercase tracking-widest px-2">方式一：Responses API（推荐）</span>
          <div className="h-px flex-1 bg-pink-200" />
        </div>

        {/* Responses API endpoint info */}
        <div className="bg-pink-50 border border-pink-100 rounded-xl p-4 flex flex-wrap gap-4 items-center">
          <div>
            <span className="text-xs font-semibold text-pink-500 uppercase tracking-wide">Endpoint</span>
            <p className="font-mono text-sm text-pink-900 mt-0.5">{baseUrl}/v1/responses</p>
          </div>
          <div className="h-8 w-px bg-pink-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-pink-500 uppercase tracking-wide">Tool Type</span>
            <p className="font-mono text-sm text-pink-900 mt-0.5">image_generation</p>
          </div>
          <div className="h-8 w-px bg-pink-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-pink-500 uppercase tracking-wide">Auth</span>
            <p className="font-mono text-sm text-pink-900 mt-0.5">Bearer &lt;API_KEY&gt;</p>
          </div>
        </div>

        {/* Responses API basic usage */}
        <SectionCard
          id="responses-api"
          title="Responses API 图片生成"
          badge="推荐"
          badgeColor="bg-emerald-100 text-emerald-700"
          description="在 tools 中设置 type: image_generation，模型会根据用户文本描述生成图片。支持多轮对话、图生图及异步模式。"
        >
          <CurlSection body={RESPONSES_REQUEST} />
        </SectionCard>

        {/* Responses API params */}
        <SectionCard
          id="responses-params"
          title="image_generation 工具参数"
          description="image_generation tool 支持以下可选参数。"
        >
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left">
                <tr>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">参数</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">类型</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">必填</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">说明</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {[
                  { name: 'type',            required: true,  type: 'string',  desc: '固定为 "image_generation"' },
                  { name: 'n',               required: false, type: 'number',  desc: '生成图片数量，别名：number、count' },
                  { name: 'size',            required: false, type: 'string',  desc: '图片尺寸，如 "1024x1024"' },
                  { name: 'response_format', required: false, type: 'string',  desc: '"b64_json"（默认）或 "url"' },
                  { name: 'image_format',    required: false, type: 'string',  desc: '"png"（默认）或 "jpg"；别名：output_format' },
                  { name: 'seed',            required: false, type: 'number',  desc: '随机种子，用于结果可复现' },
                  { name: 'aspect_ratio',   required: false, type: 'string',  desc: '宽高比，如 "1:1"、"16:9"、"9:16"（Z-Image Turbo 使用）' },
                  { name: 'resolution',      required: false, type: 'string',  desc: '分辨率档位，如 "1K"、"1.5K"、"2K"（Z-Image Turbo 使用）' },
                  { name: 'watermark',       required: false, type: 'boolean', desc: '是否添加水印' },
                ].map((r) => (
                  <tr key={r.name} className="hover:bg-slate-50">
                    <td className="px-4 py-2.5"><code className="text-pink-600 font-semibold">{r.name}</code></td>
                    <td className="px-4 py-2.5 text-slate-500 font-mono text-xs">{r.type}</td>
                    <td className="px-4 py-2.5">{r.required ? <span className="text-red-500">是</span> : <span className="text-slate-400">否</span>}</td>
                    <td className="px-4 py-2.5 text-slate-600">{r.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>

        {/* Responses API response format */}
        <SectionCard
          id="responses-response"
          title="Responses API 响应格式"
          description="output 包含 image_generation_call 类型的输出项，result 为图片 URL 或 base64。"
        >
          <CodeBlock code={RESPONSES_RESPONSE} />
        </SectionCard>

        {/* ========== Images Generations API Section ========== */}
        <div className="flex items-center gap-3">
          <div className="h-px flex-1 bg-orange-200" />
          <span className="text-xs font-semibold text-orange-400 uppercase tracking-widest px-2">方式二：Images Generations API</span>
          <div className="h-px flex-1 bg-orange-200" />
        </div>

        {/* Images API endpoint info */}
        <div className="bg-orange-50 border border-orange-100 rounded-xl p-4 flex flex-wrap gap-4 items-center">
          <div>
            <span className="text-xs font-semibold text-orange-500 uppercase tracking-wide">Endpoint</span>
            <p className="font-mono text-sm text-orange-900 mt-0.5">{baseUrl}/v1/images/generations</p>
          </div>
          <div className="h-8 w-px bg-orange-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-orange-500 uppercase tracking-wide">Method</span>
            <p className="text-sm font-medium text-orange-900 mt-0.5">POST</p>
          </div>
          <div className="h-8 w-px bg-orange-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-orange-500 uppercase tracking-wide">Auth</span>
            <p className="font-mono text-sm text-orange-900 mt-0.5">Bearer &lt;API_KEY&gt;</p>
          </div>
        </div>

        {/* Images API basic usage */}
        <SectionCard
          id="images-api"
          title="Images Generations API"
          badge="OpenAI 兼容"
          badgeColor="bg-orange-100 text-orange-700"
          description="兼容 OpenAI /v1/images/generations 接口，直接传入 prompt 生成图片，参数更简洁。"
        >
          <CurlSection body={IMAGES_REQUEST} endpoint={`${baseUrl}/v1/images/generations`} />
        </SectionCard>

        {/* Images API params */}
        <SectionCard
          id="images-params"
          title="Images API 请求参数"
          description="支持以下参数控制图片生成行为。"
        >
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left">
                <tr>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">参数</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">类型</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">必填</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">说明</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {[
                  { name: 'model',            required: true,  type: 'string',  desc: '图片生成模型名称或别名' },
                  { name: 'prompt',           required: true,  type: 'string',  desc: '图片描述文字' },
                  { name: 'images',           required: false, type: 'array',   desc: '参考图片列表，每项含 image_url，用于图生图场景' },
                  { name: 'n',                required: false, type: 'integer', desc: '生成图片数量，默认 1' },
                  { name: 'size',             required: false, type: 'string',  desc: '图片尺寸，如 "1024x1024"' },
                  { name: 'response_format',  required: false, type: 'string',  desc: '"url"（默认）或 "b64_json"' },
                  { name: 'output_format',    required: false, type: 'string',  desc: '图片格式：png | jpeg | webp' },
                  { name: 'quality',          required: false, type: 'string',  desc: '质量：standard | hd | low | medium | high | auto' },
                  { name: 'style',            required: false, type: 'string',  desc: '风格：vivid | natural' },
                  { name: 'user',             required: false, type: 'string',  desc: '终端用户标识' },
                ].map((r) => (
                  <tr key={r.name} className="hover:bg-slate-50">
                    <td className="px-4 py-2.5"><code className="text-orange-600 font-semibold">{r.name}</code></td>
                    <td className="px-4 py-2.5 text-slate-500 font-mono text-xs">{r.type}</td>
                    <td className="px-4 py-2.5">{r.required ? <span className="text-red-500">是</span> : <span className="text-slate-400">否</span>}</td>
                    <td className="px-4 py-2.5 text-slate-600">{r.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>

        {/* Images API response format */}
        <SectionCard
          id="images-response"
          title="Images API 响应格式"
          description="响应包含生成时间、图片数据和输出格式。"
        >
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">URL 格式响应</span>
            <CodeBlock code={IMAGES_RESPONSE} />
          </div>
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">Base64 格式响应</span>
            <CodeBlock code={IMAGES_B64_RESPONSE} />
          </div>
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left">
                <tr>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">字段</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">类型</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">说明</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {[
                  { name: 'created',               type: 'integer', desc: '生成时间（Unix 时间戳）' },
                  { name: 'data',                  type: 'array',   desc: '图片数据列表' },
                  { name: 'data[].url',            type: 'string',  desc: '图片 URL（response_format 为 "url" 时）' },
                  { name: 'data[].b64_json',       type: 'string',  desc: 'Base64 编码的图片数据（response_format 为 "b64_json" 时）' },
                  { name: 'data[].revised_prompt', type: 'string',  desc: '模型优化后的提示词（可选）' },
                  { name: 'output_format',         type: 'string',  desc: '图片文件格式：png | jpeg | webp' },
                ].map((r) => (
                  <tr key={r.name} className="hover:bg-slate-50">
                    <td className="px-4 py-2.5"><code className="text-orange-600 font-semibold">{r.name}</code></td>
                    <td className="px-4 py-2.5 text-slate-500 font-mono text-xs">{r.type}</td>
                    <td className="px-4 py-2.5 text-slate-600">{r.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>

        {/* ========== Images Edits API Section ========== */}
        <div className="flex items-center gap-3">
          <div className="h-px flex-1 bg-violet-200" />
          <span className="text-xs font-semibold text-violet-400 uppercase tracking-widest px-2">方式三：Images Edits API</span>
          <div className="h-px flex-1 bg-violet-200" />
        </div>

        {/* Edits API endpoint info */}
        <div className="bg-violet-50 border border-violet-100 rounded-xl p-4 flex flex-wrap gap-4 items-center">
          <div>
            <span className="text-xs font-semibold text-violet-500 uppercase tracking-wide">Endpoint</span>
            <p className="font-mono text-sm text-violet-900 mt-0.5">{baseUrl}/v1/images/edits</p>
          </div>
          <div className="h-8 w-px bg-violet-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-violet-500 uppercase tracking-wide">Method</span>
            <p className="text-sm font-medium text-violet-900 mt-0.5">POST</p>
          </div>
          <div className="h-8 w-px bg-violet-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-violet-500 uppercase tracking-wide">Auth</span>
            <p className="font-mono text-sm text-violet-900 mt-0.5">Bearer &lt;API_KEY&gt;</p>
          </div>
        </div>

        {/* Edits API basic usage */}
        <SectionCard
          id="edits-api"
          title="Images Edits API"
          badge="图片编辑"
          badgeColor="bg-violet-100 text-violet-700"
          description="兼容 OpenAI /v1/images/edits 接口，传入原始图片和编辑指令，对图片进行修改。支持蒙版（mask）、背景控制等高级参数。"
        >
          <CurlSection body={EDITS_REQUEST} endpoint={`${baseUrl}/v1/images/edits`} />
        </SectionCard>

        {/* Edits API params */}
        <SectionCard
          id="edits-params"
          title="Images Edits 请求参数"
          description="支持以下参数控制图片编辑行为。"
        >
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left">
                <tr>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">参数</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">类型</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">必填</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">说明</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {[
                  { name: 'model',           required: true,  type: 'string',  desc: '图片编辑模型名称或别名' },
                  { name: 'prompt',          required: true,  type: 'string',  desc: '编辑指令描述' },
                  { name: 'images',          required: false, type: 'array',   desc: '输入图片列表，每项含 image_url 或 file_id' },
                  { name: 'mask',            required: false, type: 'object',  desc: '蒙版图片，含 image_url 或 file_id，指定编辑区域' },
                  { name: 'n',               required: false, type: 'integer', desc: '生成图片数量，默认 1' },
                  { name: 'size',            required: false, type: 'string',  desc: '输出尺寸，如 "1024x1024"' },
                  { name: 'response_format', required: false, type: 'string',  desc: '"url"（默认）或 "b64_json"' },
                  { name: 'output_format',   required: false, type: 'string',  desc: '图片格式：png | jpeg | webp' },
                  { name: 'quality',         required: false, type: 'string',  desc: '质量：low | medium | high | auto' },
                  { name: 'background',      required: false, type: 'string',  desc: '背景：transparent | opaque | auto' },
                  { name: 'input_fidelity',  required: false, type: 'string',  desc: '输入保真度：high | low' },
                  { name: 'moderation',      required: false, type: 'string',  desc: '内容审核：low | auto' },
                  { name: 'user',            required: false, type: 'string',  desc: '终端用户标识' },
                ].map((r) => (
                  <tr key={r.name} className="hover:bg-slate-50">
                    <td className="px-4 py-2.5"><code className="text-violet-600 font-semibold">{r.name}</code></td>
                    <td className="px-4 py-2.5 text-slate-500 font-mono text-xs">{r.type}</td>
                    <td className="px-4 py-2.5">{r.required ? <span className="text-red-500">是</span> : <span className="text-slate-400">否</span>}</td>
                    <td className="px-4 py-2.5 text-slate-600">{r.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="bg-violet-50 border border-violet-200 rounded-lg p-3 text-sm text-violet-800">
            <strong>images 格式示例：</strong>
            <code className="block mt-1 bg-violet-100 rounded p-2 text-xs font-mono text-violet-900">
              {'[{"image_url": "https://example.com/photo.png"}, {"file_id": "file_abc123"}]'}
            </code>
          </div>
        </SectionCard>

        {/* Edits API response format */}
        <SectionCard
          id="edits-response"
          title="Images Edits 响应格式"
          description="响应包含编辑后的图片数据、输出格式及编辑参数。"
        >
          <CodeBlock code={EDITS_RESPONSE} />
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left">
                <tr>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">字段</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">类型</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">说明</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {[
                  { name: 'created',               type: 'integer', desc: '生成时间（Unix 时间戳）' },
                  { name: 'data',                  type: 'array',   desc: '图片数据列表' },
                  { name: 'data[].url',            type: 'string',  desc: '图片 URL（response_format 为 "url" 时）' },
                  { name: 'data[].b64_json',       type: 'string',  desc: 'Base64 编码的图片数据（response_format 为 "b64_json" 时）' },
                  { name: 'data[].revised_prompt', type: 'string',  desc: '模型优化后的提示词（可选）' },
                  { name: 'output_format',         type: 'string',  desc: '图片文件格式：png | jpeg | webp' },
                  { name: 'size',                  type: 'string',  desc: '输出图片尺寸' },
                  { name: 'quality',               type: 'string',  desc: '图片质量等级' },
                  { name: 'background',            type: 'string',  desc: '背景类型：transparent | opaque' },
                ].map((r) => (
                  <tr key={r.name} className="hover:bg-slate-50">
                    <td className="px-4 py-2.5"><code className="text-violet-600 font-semibold">{r.name}</code></td>
                    <td className="px-4 py-2.5 text-slate-500 font-mono text-xs">{r.type}</td>
                    <td className="px-4 py-2.5 text-slate-600">{r.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>

        {/* ========== Seedream Sizes ========== */}
        <div className="flex items-center gap-3">
          <div className="h-px flex-1 bg-slate-200" />
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-widest px-2">尺寸参考</span>
          <div className="h-px flex-1 bg-slate-200" />
        </div>

        <SectionCard
          id="seedream-sizes"
          title="Doubao Seedream 支持尺寸"
          description='不同 Seedream 模型支持的图片尺寸参考表。size 参数可传入 "1K"、"2K"、"3K"、"4K" 或具体分辨率（如 "2048x2048"）。'
        >
          <div className="space-y-6">
            {/* Seedream 5.0 lite */}
            <div>
              <h4 className="text-sm font-semibold text-slate-700 mb-2">Seedream 5.0 lite</h4>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="px-3 py-2 font-semibold text-slate-600 w-16">比例</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">1K</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">2K</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">3K</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">4K</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 text-xs">
                    {[
                      { ratio: '1:1',  k1: '—', k2: '2048x2048', k3: '3072x3072', k4: '—' },
                      { ratio: '3:4',  k1: '—', k2: '1728x2304', k3: '2592x3456', k4: '—' },
                      { ratio: '4:3',  k1: '—', k2: '2304x1728', k3: '3456x2592', k4: '—' },
                      { ratio: '16:9', k1: '—', k2: '2848x1600', k3: '4096x2304', k4: '—' },
                      { ratio: '9:16', k1: '—', k2: '1600x2848', k3: '2304x4096', k4: '—' },
                      { ratio: '3:2',  k1: '—', k2: '2496x1664', k3: '2496x3744', k4: '—' },
                      { ratio: '2:3',  k1: '—', k2: '1664x2496', k3: '3744x2496', k4: '—' },
                      { ratio: '21:9', k1: '—', k2: '3136x1344', k3: '4704x2016', k4: '—' },
                    ].map((r) => (
                      <tr key={r.ratio} className="hover:bg-slate-50">
                        <td className="px-3 py-1.5"><code className="text-pink-600 font-semibold">{r.ratio}</code></td>
                        <td className="px-3 py-1.5 text-slate-400">{r.k1}</td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.k2}</td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.k3}</td>
                        <td className="px-3 py-1.5 text-slate-400">{r.k4}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Seedream 4.5 */}
            <div>
              <h4 className="text-sm font-semibold text-slate-700 mb-2">Seedream 4.5</h4>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="px-3 py-2 font-semibold text-slate-600 w-16">比例</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">1K</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">2K</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">3K</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">4K</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 text-xs">
                    {[
                      { ratio: '1:1',  k1: '—', k2: '2048x2048', k3: '—', k4: '4096x4096' },
                      { ratio: '3:4',  k1: '—', k2: '1728x2304', k3: '—', k4: '3520x4704' },
                      { ratio: '4:3',  k1: '—', k2: '2304x1728', k3: '—', k4: '4704x3520' },
                      { ratio: '16:9', k1: '—', k2: '2848x1600', k3: '—', k4: '5504x3040' },
                      { ratio: '9:16', k1: '—', k2: '1600x2848', k3: '—', k4: '3040x5504' },
                      { ratio: '3:2',  k1: '—', k2: '2496x1664', k3: '—', k4: '3328x4992' },
                      { ratio: '2:3',  k1: '—', k2: '1664x2496', k3: '—', k4: '4992x3328' },
                      { ratio: '21:9', k1: '—', k2: '3136x1344', k3: '—', k4: '6240x2656' },
                    ].map((r) => (
                      <tr key={r.ratio} className="hover:bg-slate-50">
                        <td className="px-3 py-1.5"><code className="text-pink-600 font-semibold">{r.ratio}</code></td>
                        <td className="px-3 py-1.5 text-slate-400">{r.k1}</td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.k2}</td>
                        <td className="px-3 py-1.5 text-slate-400">{r.k3}</td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.k4}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Seedream 4.0 */}
            <div>
              <h4 className="text-sm font-semibold text-slate-700 mb-2">Seedream 4.0</h4>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="px-3 py-2 font-semibold text-slate-600 w-16">比例</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">1K</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">2K</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">3K</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">4K</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 text-xs">
                    {[
                      { ratio: '1:1',  k1: '1024x1024', k2: '2048x2048', k3: '—', k4: '4096x4096' },
                      { ratio: '3:4',  k1: '864x1152',  k2: '1728x2304', k3: '—', k4: '3520x4704' },
                      { ratio: '4:3',  k1: '1152x864',  k2: '2304x1728', k3: '—', k4: '4704x3520' },
                      { ratio: '16:9', k1: '1312x736',  k2: '2848x1600', k3: '—', k4: '5504x3040' },
                      { ratio: '9:16', k1: '736x1312',  k2: '1600x2848', k3: '—', k4: '3040x5504' },
                      { ratio: '2:3',  k1: '832x1248',  k2: '2496x1664', k3: '—', k4: '3328x4992' },
                      { ratio: '3:2',  k1: '1248x832',  k2: '1664x2496', k3: '—', k4: '4992x3328' },
                      { ratio: '21:9', k1: '1568x672',  k2: '3136x1344', k3: '—', k4: '6240x2656' },
                    ].map((r) => (
                      <tr key={r.ratio} className="hover:bg-slate-50">
                        <td className="px-3 py-1.5"><code className="text-pink-600 font-semibold">{r.ratio}</code></td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.k1}</td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.k2}</td>
                        <td className="px-3 py-1.5 text-slate-400">{r.k3}</td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.k4}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-800 mt-2">
            <strong>提示：</strong>size 参数支持两种格式：
            <ul className="mt-1 space-y-0.5 list-disc list-inside text-blue-700">
              <li>分辨率等级：<code>"1K"</code>、<code>"2K"</code>、<code>"3K"</code>、<code>"4K"</code>（自动匹配默认比例 1:1）</li>
              <li>精确分辨率：<code>"2048x2048"</code>、<code>"1728x2304"</code> 等（需与上表中的尺寸匹配）</li>
            </ul>
          </div>
        </SectionCard>

        <SectionCard
          id="z-image-sizes"
          title="Z-Image Turbo 支持尺寸"
          description="百炼 Z-Image Turbo 模型使用 aspect_ratio（宽高比）+ 分辨率档位（1K / 1.5K / 2K）来确定输出图片尺寸。仅支持文本输入。"
        >
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left">
                <tr>
                  <th className="px-3 py-2 font-semibold text-slate-600 w-16">比例</th>
                  <th className="px-3 py-2 font-semibold text-slate-600">1K</th>
                  <th className="px-3 py-2 font-semibold text-slate-600">1.5K</th>
                  <th className="px-3 py-2 font-semibold text-slate-600">2K</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-xs">
                {[
                  { ratio: '1:1',  k1: '1024×1024',  k15: '1280×1280',  k2: '1536×1536' },
                  { ratio: '2:3',  k1: '832×1248',   k15: '1024×1536',  k2: '1248×1872' },
                  { ratio: '3:2',  k1: '1248×832',   k15: '1536×1024',  k2: '1872×1248' },
                  { ratio: '3:4',  k1: '864×1152',   k15: '1104×1472',  k2: '1296×1728' },
                  { ratio: '4:3',  k1: '1152×864',   k15: '1472×1104',  k2: '1728×1296' },
                  { ratio: '7:9',  k1: '896×1152',   k15: '1120×1440',  k2: '1344×1728' },
                  { ratio: '9:7',  k1: '1152×896',   k15: '1440×1120',  k2: '1728×1344' },
                  { ratio: '9:16', k1: '720×1280',   k15: '864×1536',   k2: '1152×2048' },
                  { ratio: '9:21', k1: '576×1344',   k15: '720×1680',   k2: '864×2016' },
                  { ratio: '16:9', k1: '1280×720',   k15: '1536×864',   k2: '2048×1152' },
                  { ratio: '21:9', k1: '1344×576',   k15: '1680×720',   k2: '2016×864' },
                ].map((r) => (
                  <tr key={r.ratio} className="hover:bg-slate-50">
                    <td className="px-3 py-1.5"><code className="text-pink-600 font-semibold">{r.ratio}</code></td>
                    <td className="px-3 py-1.5 font-mono text-slate-600">{r.k1}</td>
                    <td className="px-3 py-1.5 font-mono text-slate-600">{r.k15}</td>
                    <td className="px-3 py-1.5 font-mono text-slate-600">{r.k2}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-800 mt-2">
            <strong>提示：</strong>Z-Image Turbo 的 size 参数使用 WxH 精确分辨率格式（如 <code>"1024*1024"</code>），需与上表中的尺寸匹配。也可通过 aspect_ratio 参数指定宽高比，系统自动匹配对应分辨率：
            <ul className="mt-1 space-y-0.5 list-disc list-inside text-blue-700">
              <li>size 精确分辨率：<code>size: "1024*1024"</code> → 直接使用</li>
              <li>仅 aspect_ratio：<code>aspect_ratio: "1:1"</code> → 默认 1K档 1024×1024</li>
              <li>size 档位 + aspect_ratio：<code>size: "2K"</code> + <code>aspect_ratio: "16:9"</code> → 自动匹配 2048×1152</li>
            </ul>
          </div>
        </SectionCard>

        <SectionCard
          id="gemini-sizes"
          title="Gemini 图像模型支持尺寸"
          description="不同 Gemini 图像模型支持的尺寸参考表，通过 TencentVOD 路由。"
        >
          <div className="space-y-6">
            {/* Gemini 2.5 Flash Image */}
            <div>
              <h4 className="text-sm font-semibold text-slate-700 mb-2">gemini-2.5-flash-image（固定分辨率）</h4>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="px-3 py-2 font-semibold text-slate-600 w-16">比例</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">分辨率</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 text-xs">
                    {[
                      { ratio: '1:1',  res: '1024x1024' },
                      { ratio: '2:3',  res: '832x1248' },
                      { ratio: '3:2',  res: '1248x832' },
                      { ratio: '3:4',  res: '864x1184' },
                      { ratio: '4:3',  res: '1184x864' },
                      { ratio: '4:5',  res: '896x1152' },
                      { ratio: '5:4',  res: '1152x896' },
                      { ratio: '9:16', res: '768x1344' },
                      { ratio: '16:9', res: '1344x768' },
                      { ratio: '21:9', res: '1536x672' },
                    ].map((r) => (
                      <tr key={r.ratio} className="hover:bg-slate-50">
                        <td className="px-3 py-1.5"><code className="text-pink-600 font-semibold">{r.ratio}</code></td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.res}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Gemini 3 Pro Image Preview */}
            <div>
              <h4 className="text-sm font-semibold text-slate-700 mb-2">gemini-3-pro-image-preview（1K / 2K / 4K）</h4>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="px-3 py-2 font-semibold text-slate-600 w-16">比例</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">1K</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">2K</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">4K</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 text-xs">
                    {[
                      { ratio: '1:1',  k1: '1024x1024', k2: '2048x2048', k4: '4096x4096' },
                      { ratio: '2:3',  k1: '848x1264',  k2: '1696x2528', k4: '3392x5056' },
                      { ratio: '3:2',  k1: '1264x848',  k2: '2528x1696', k4: '5056x3392' },
                      { ratio: '3:4',  k1: '896x1200',  k2: '1792x2400', k4: '3584x4800' },
                      { ratio: '4:3',  k1: '1200x896',  k2: '2400x1792', k4: '4800x3584' },
                      { ratio: '4:5',  k1: '928x1152',  k2: '1856x2304', k4: '3712x4608' },
                      { ratio: '5:4',  k1: '1152x928',  k2: '2304x1856', k4: '4608x3712' },
                      { ratio: '9:16', k1: '768x1376',  k2: '1536x2752', k4: '3072x5504' },
                      { ratio: '16:9', k1: '1376x768',  k2: '2752x1536', k4: '5504x3072' },
                      { ratio: '21:9', k1: '1584x672',  k2: '3168x1344', k4: '6336x2688' },
                    ].map((r) => (
                      <tr key={r.ratio} className="hover:bg-slate-50">
                        <td className="px-3 py-1.5"><code className="text-pink-600 font-semibold">{r.ratio}</code></td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.k1}</td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.k2}</td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.k4}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Gemini 3.1 Flash Image Preview */}
            <div>
              <h4 className="text-sm font-semibold text-slate-700 mb-2">gemini-3.1-flash-image-preview（512 / 1K / 2K / 4K）</h4>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="px-3 py-2 font-semibold text-slate-600 w-16">比例</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">512</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">1K</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">2K</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">4K</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 text-xs">
                    {[
                      { ratio: '1:1',  s512: '512x512',   k1: '1024x1024',  k2: '2048x2048',  k4: '4096x4096' },
                      { ratio: '1:4',  s512: '256x1024',  k1: '512x2048',   k2: '1024x4096',  k4: '2048x8192' },
                      { ratio: '1:8',  s512: '192x1536',  k1: '384x3072',   k2: '768x6144',   k4: '1536x12288' },
                      { ratio: '2:3',  s512: '424x632',   k1: '848x1264',   k2: '1696x2528',  k4: '3392x5056' },
                      { ratio: '3:2',  s512: '632x424',   k1: '1264x848',   k2: '2528x1696',  k4: '5056x3392' },
                      { ratio: '3:4',  s512: '448x600',   k1: '896x1200',   k2: '1792x2400',  k4: '3584x4800' },
                      { ratio: '4:1',  s512: '1024x256',  k1: '2048x512',   k2: '4096x1024',  k4: '8192x2048' },
                      { ratio: '4:3',  s512: '600x448',   k1: '1200x896',   k2: '2400x1792',  k4: '4800x3584' },
                      { ratio: '4:5',  s512: '464x576',   k1: '928x1152',   k2: '1856x2304',  k4: '3712x4608' },
                      { ratio: '5:4',  s512: '576x464',   k1: '1152x928',   k2: '2304x1856',  k4: '4608x3712' },
                      { ratio: '8:1',  s512: '1536x192',  k1: '3072x384',   k2: '6144x768',   k4: '12288x1536' },
                      { ratio: '9:16', s512: '384x688',   k1: '768x1376',   k2: '1536x2752',  k4: '3072x5504' },
                      { ratio: '16:9', s512: '688x384',   k1: '1376x768',   k2: '2752x1536',  k4: '5504x3072' },
                      { ratio: '21:9', s512: '792x168',   k1: '1584x672',   k2: '3168x1344',  k4: '6336x2688' },
                    ].map((r) => (
                      <tr key={r.ratio} className="hover:bg-slate-50">
                        <td className="px-3 py-1.5"><code className="text-pink-600 font-semibold">{r.ratio}</code></td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.s512}</td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.k1}</td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.k2}</td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.k4}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </SectionCard>
      </div>

      <TableOfContents items={TOC_ITEMS} />
    </div>
  );
}
