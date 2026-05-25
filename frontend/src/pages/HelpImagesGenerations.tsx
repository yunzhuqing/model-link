import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Copy, Check, ArrowLeft, ImageIcon } from 'lucide-react';
import { useBaseUrl } from '../components/help/HelpShared';

interface TocItem { id: string; label: string }
const TOC_ITEMS: TocItem[] = [
  { id: 'overview', label: '功能说明' },
  { id: 'basic', label: '基础请求' },
  { id: 'params', label: '请求参数' },
  { id: 'seedream-sizes', label: 'Seedream 尺寸' },
  { id: 'z-image-sizes', label: 'Z-Image 尺寸' },
  { id: 'gpt-image-sizes', label: 'GPT Image 尺寸' },
  { id: 'response-format', label: '响应格式' },
  { id: 'curl-examples', label: 'cURL 示例' },
];

const BASIC_REQUEST = `{
  "model": "seedream-5.0",
  "prompt": "一只可爱的狸花猫在阳光下打盹",
  "n": 1,
  "size": "1024x1024",
  "response_format": "url",
  "output_format": "png"
}`;

const BASIC_RESPONSE = `{
  "created": 1712345678,
  "data": [
    {
      "url": "https://example.com/generated-image.png",
      "revised_prompt": "一只可爱的狸花猫在阳光下打盹"
    }
  ],
  "output_format": "png"
}`;

const B64_REQUEST = `{
  "model": "seedream-5.0",
  "prompt": "一幅水墨画风格的山水画",
  "n": 1,
  "size": "1024x1024",
  "response_format": "b64_json",
  "output_format": "png"
}`;

const B64_RESPONSE = `{
  "created": 1712345678,
  "data": [
    {
      "b64_json": "data:image/png;base64,iVBORw0KGgo..."
    }
  ],
  "output_format": "png"
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
  const baseUrl = useBaseUrl();
  const [show, setShow] = useState(false);
  const curl = `curl -X POST ${baseUrl}/v1/images/generations \\\n  -H "Authorization: Bearer <YOUR_API_KEY>" \\\n  -H "Content-Type: application/json" \\\n  -d '${body}'`;
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
                  ? 'bg-orange-50 text-orange-600 font-medium border-l-2 border-orange-500'
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

export default function HelpImagesGenerations() {
  const navigate = useNavigate();
  const baseUrl = useBaseUrl();

  return (
    <div className="flex gap-8 max-w-6xl mx-auto">
      <div className="flex-1 min-w-0 space-y-8">
        {/* Back + header */}
        <div>
          <button
            onClick={() => navigate('/help')}
            className="flex items-center gap-1.5 text-sm text-slate-500 hover:text-orange-600 mb-4 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            返回帮助中心
          </button>
          <div className="flex items-center gap-4">
            <div className="p-3 bg-gradient-to-br from-orange-500 to-amber-600 rounded-2xl shadow-lg shadow-orange-500/25">
              <ImageIcon className="w-7 h-7 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900">Images Generations API</h1>
              <p className="text-slate-500 text-sm mt-0.5">OpenAI 兼容的图片生成接口，直接生成图片</p>
            </div>
          </div>
        </div>

        {/* Endpoint info */}
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

        {/* Overview */}
        <div id="overview" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <h3 className="text-lg font-semibold text-slate-800 mb-1">功能说明</h3>
            <p className="text-sm text-slate-500">兼容 OpenAI <code>/v1/images/generations</code> 接口格式，通过文本描述直接生成图片。无需使用 Responses API 的工具机制，直接传入 prompt 即可生成。</p>
          </div>
          <div className="p-6 space-y-3">
            <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-3 text-sm text-emerald-800">
              <strong>与 Responses API image_generation 工具的区别：</strong>
              <ul className="mt-1.5 space-y-1 list-disc list-inside text-emerald-700">
                <li><code>/v1/images/generations</code> — 直接图片生成，参数扁平化，更简洁</li>
                <li><code>/v1/responses</code> + <code>image_generation</code> 工具 — 对话式图片生成，支持多轮对话上下文</li>
              </ul>
            </div>
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">
              <strong>注意：</strong>需要图片生成模型（如 Volcengine 的 seedream 系列、百炼的 qwen-image 系列、Gemini 图像生成模型等）。模型须在管理面板中配置。
            </div>
          </div>
        </div>

        {/* Basic usage */}
        <SectionCard
          id="basic"
          title="基础请求"
          badge="POST"
          badgeColor="bg-orange-100 text-orange-700"
          description="传入模型名称和文本描述即可生成图片，返回图片 URL 或 base64 数据。"
        >
          <CurlSection body={BASIC_REQUEST} />
        </SectionCard>

        {/* Params */}
        <SectionCard
          id="params"
          title="请求参数"
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
                  { name: 'n',                required: false, type: 'integer', desc: '生成图片数量，默认 1' },
                  { name: 'size',             required: false, type: 'string',  desc: '图片尺寸，如 "1024x1024"' },
                  { name: 'response_format',  required: false, type: 'string',  desc: '"url"（默认）或 "b64_json"' },
                  { name: 'output_format',    required: false, type: 'string',  desc: '图片格式：png | jpeg | webp' },
                  { name: 'quality',          required: false, type: 'string',  desc: '质量：standard | hd | low | medium | high | auto' },
                  { name: 'aspect_ratio',   required: false, type: 'string',  desc: '宽高比，如 "1:1"、"16:9"、"9:16"（Z-Image Turbo 使用）' },
                  { name: 'resolution',      required: false, type: 'string',  desc: '分辨率档位，如 "1K"、"1.5K"、"2K"（Z-Image Turbo 使用）' },
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

        {/* Seedream size reference */}
        <SectionCard
          id="seedream-sizes"
          title="Doubao Seedream 支持尺寸"
          description="不同 Seedream 模型支持的图片尺寸参考表。size 参数可传入 &quot;1K&quot;、&quot;2K&quot;、&quot;3K&quot;、&quot;4K&quot; 或具体分辨率（如 &quot;2048x2048&quot;）。"
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
                        <td className="px-3 py-1.5"><code className="text-orange-600 font-semibold">{r.ratio}</code></td>
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
                        <td className="px-3 py-1.5"><code className="text-orange-600 font-semibold">{r.ratio}</code></td>
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
                        <td className="px-3 py-1.5"><code className="text-orange-600 font-semibold">{r.ratio}</code></td>
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

        {/* Z-Image Turbo size reference */}
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
                    <td className="px-3 py-1.5"><code className="text-orange-600 font-semibold">{r.ratio}</code></td>
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

        {/* GPT Image 2 size reference */}
        <SectionCard
          id="gpt-image-sizes"
          title="GPT Image 2 支持尺寸"
          description="OpenAI gpt-image-2 模型支持的图片尺寸参考表。size 参数传入 WxH 分辨率字符串，支持 1K、2K、4K 三个档位。"
        >
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
                  { ratio: '1:1',  k1: '1024x1024',  k2: '2048x2048',  k4: '3840x3840' },
                  { ratio: '3:2',  k1: '1536x1024',  k2: '3072x2048',  k4: '3840x2560' },
                  { ratio: '2:3',  k1: '1024x1536',  k2: '2048x3072',  k4: '2560x3840' },
                  { ratio: '3:4',  k1: '768x1024',   k2: '1536x2048',  k4: '2880x3840' },
                  { ratio: '4:3',  k1: '1024x768',   k2: '2048x1536',  k4: '3840x2880' },
                  { ratio: '16:9', k1: '1024x576',   k2: '2048x1152',  k4: '3840x2160' },
                  { ratio: '9:16', k1: '576x1024',   k2: '1152x2048',  k4: '2160x3840' },
                  { ratio: '21:9', k1: '1024x439',   k2: '2048x878',   k4: '3840x1646' },
                  { ratio: '9:21', k1: '439x1024',   k2: '878x2048',   k4: '1646x3840' },
                ].map((r) => (
                  <tr key={r.ratio} className="hover:bg-slate-50">
                    <td className="px-3 py-1.5"><code className="text-orange-600 font-semibold">{r.ratio}</code></td>
                    <td className="px-3 py-1.5 font-mono text-slate-600">{r.k1}</td>
                    <td className="px-3 py-1.5 font-mono text-slate-600">{r.k2}</td>
                    <td className="px-3 py-1.5 font-mono text-slate-600">{r.k4}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-800 mt-2">
            <strong>提示：</strong>gpt-image-2 的 size 参数使用 WxH 精确分辨率格式，需与上表中的尺寸匹配。
            支持通过 TencentVOD 路由访问。
          </div>
        </SectionCard>

        {/* Response format */}
        <SectionCard
          id="response-format"
          title="响应格式"
          description="响应包含生成时间、图片数据和输出格式。"
        >
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">URL 格式响应</span>
            <CodeBlock code={BASIC_RESPONSE} />
          </div>
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">Base64 格式响应</span>
            <CodeBlock code={B64_RESPONSE} />
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
                  { name: 'created',        type: 'integer', desc: '生成时间（Unix 时间戳）' },
                  { name: 'data',           type: 'array',   desc: '图片数据列表' },
                  { name: 'data[].url',     type: 'string',  desc: '图片 URL（response_format 为 "url" 时）' },
                  { name: 'data[].b64_json', type: 'string', desc: 'Base64 编码的图片数据（response_format 为 "b64_json" 时）' },
                  { name: 'data[].revised_prompt', type: 'string', desc: '模型优化后的提示词（可选）' },
                  { name: 'output_format',  type: 'string',  desc: '图片文件格式：png | jpeg | webp' },
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

        {/* cURL examples */}
        <SectionCard
          id="curl-examples"
          title="更多示例"
          description="不同参数组合的请求示例。"
        >
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">返回 Base64 格式</span>
            <CurlSection body={B64_REQUEST} />
          </div>
        </SectionCard>
      </div>

      <TableOfContents items={TOC_ITEMS} />
    </div>
  );
}
