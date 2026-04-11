import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Copy, Check, ArrowLeft, ImageIcon } from 'lucide-react';

const BASE_URL = 'http://localhost:8000';

interface TocItem { id: string; label: string }
const TOC_ITEMS: TocItem[] = [
  { id: 'overview', label: '功能说明' },
  { id: 'basic', label: '基础图片生成' },
  { id: 'params', label: '请求参数' },
  { id: 'response-format', label: '响应格式' },
];

const IMAGE_GENERATION = `{
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

const IMAGE_GENERATION_RESPONSE = `{
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

function CurlSection({ body }: { body: string }) {
  const [show, setShow] = useState(false);
  const curl = `curl -X POST ${BASE_URL}/v1/responses \\\n  -H "Authorization: Bearer <YOUR_API_KEY>" \\\n  -H "Content-Type: application/json" \\\n  -d '${body}'`;
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
              <p className="text-slate-500 text-sm mt-0.5">通过 Responses API 的 image_generation 工具生成图片</p>
            </div>
          </div>
        </div>

        {/* Endpoint info */}
        <div className="bg-pink-50 border border-pink-100 rounded-xl p-4 flex flex-wrap gap-4 items-center">
          <div>
            <span className="text-xs font-semibold text-pink-500 uppercase tracking-wide">Endpoint</span>
            <p className="font-mono text-sm text-pink-900 mt-0.5">{BASE_URL}/v1/responses</p>
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

        {/* Overview */}
        <div id="overview" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <h3 className="text-lg font-semibold text-slate-800 mb-1">功能说明</h3>
            <p className="text-sm text-slate-500">通过在 tools 中指定 image_generation 类型，触发图片生成功能。模型会根据用户输入生成图片，并以 image_generation_call 类型返回图片 URL 或 base64 数据。</p>
          </div>
          <div className="p-6">
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">
              <strong>注意：</strong>图片生成功能需要供应商和模型支持图像生成能力（如百炼的 qwen-image-2.0-pro 模型）。同步模式（background: false）等待生成完成后返回；如生成耗时较长，建议使用 background: true 异步模式。
            </div>
          </div>
        </div>

        {/* Basic usage */}
        <SectionCard
          id="basic"
          title="基础图片生成"
          badge="image_generation"
          badgeColor="bg-pink-100 text-pink-700"
          description="在 tools 中设置 type: image_generation，模型会根据用户文本描述生成图片。"
        >
          <CurlSection body={IMAGE_GENERATION} />
        </SectionCard>

        {/* Params */}
        <SectionCard
          id="params"
          title="请求参数（image_generation tool）"
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
                  { name: 'size',            required: false, type: 'string',  desc: '图片尺寸，如 "1024x1024" 或 "2K"' },
                  { name: 'response_format', required: false, type: 'string',  desc: '"b64_json"（默认）或 "url"' },
                  { name: 'image_format',    required: false, type: 'string',  desc: '"png"（默认）或 "jpg"；别名：output_format' },
                  { name: 'seed',            required: false, type: 'number',  desc: '随机种子，用于结果可复现' },
                  { name: 'watermark',       required: false, type: 'boolean', desc: '是否添加水印' },
                  { name: 'reference_images',required: false, type: 'array',   desc: '参考图片 URL 列表（图生图）；别名：image' },
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

        {/* Response format */}
        <div id="response-format" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <h3 className="text-lg font-semibold text-slate-800">响应格式</h3>
            <p className="text-sm text-slate-500 mt-1">output 包含 image_generation_call 类型的输出项，result 为图片 URL 或 base64。</p>
          </div>
          <div className="p-6">
            <CodeBlock code={IMAGE_GENERATION_RESPONSE} />
          </div>
        </div>
      </div>

      <TableOfContents items={TOC_ITEMS} />
    </div>
  );
}
