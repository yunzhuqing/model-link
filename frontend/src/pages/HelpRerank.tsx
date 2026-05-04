import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Copy, Check, ArrowLeft, AlignLeft, Image } from 'lucide-react';

import { useBaseUrl } from '../components/help/HelpShared';

// ---------- TOC ----------

interface TocItem { id: string; label: string }

const TOC_ITEMS: TocItem[] = [
  { id: 'text-rerank', label: '文本 Rerank' },
  { id: 'multimodal-rerank', label: '多模态 Rerank' },
  { id: 'response-format', label: '响应格式' },
  { id: 'supported-models', label: '支持的模型' },
];

// ---------- code samples ----------

const TEXT_RERANK = `{
  "model": "qwen3-rerank",
  "query": "What is the capital of France?",
  "documents": [
    "The capital of Brazil is Brasilia.",
    "The capital of France is Paris.",
    "Horses and cows are both animals"
  ],
  "top_n": 2,
  "return_documents": true,
  "instruct": "Given a web search query, retrieve relevant passages that answer the query."
}`;

const MULTIMODAL_TEXT_QUERY = `{
  "model": "qwen3-vl-rerank",
  "query": {"text": "什么是文本排序模型"},
  "documents": [
    {"text": "文本排序模型广泛用于搜索引擎和推荐系统中"},
    {"image": "https://img.alicdn.com/imgextra/i3/O1CN01rdstgY1uiZWt8gqSL_!!6000000006071-0-tps-1970-356.jpg"},
    {"video": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20250107/lbcemt/new+video.mp4"}
  ],
  "top_n": 2,
  "return_documents": true
}`;

const MULTIMODAL_IMAGE_QUERY = `{
  "model": "qwen3-vl-rerank",
  "query": {"image": "https://img.alicdn.com/imgextra/i3/O1CN01rdstgY1uiZWt8gqSL_!!6000000006071-0-tps-1970-356.jpg"},
  "documents": [
    {"text": "文本排序模型广泛用于搜索引擎和推荐系统中"},
    {"image": "https://img.alicdn.com/imgextra/i3/O1CN01rdstgY1uiZWt8gqSL_!!6000000006071-0-tps-1970-356.jpg"},
    {"video": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20250107/lbcemt/new+video.mp4"}
  ],
  "top_n": 2,
  "return_documents": true
}`;

const CURL_TEXT = (baseUrl: string) => `curl -X POST ${baseUrl}/v1/rerank \\
  -H "Authorization: Bearer <YOUR_API_KEY>" \\
  -H "Content-Type: application/json" \\
  -d '${TEXT_RERANK}'`;

const CURL_MULTIMODAL = (baseUrl: string) => `curl -X POST ${baseUrl}/v1/rerank \\
  -H "Authorization: Bearer <YOUR_API_KEY>" \\
  -H "Content-Type: application/json" \\
  -d '${MULTIMODAL_TEXT_QUERY}'`;

const RESPONSE_EXAMPLE = `{
  "id": "rerank-fae51b2b664d4ed38f5969b612edff77",
  "model": "qwen3-rerank",
  "usage": {
    "total_tokens": 56
  },
  "results": [
    {
      "index": 1,
      "document": {
        "text": "The capital of France is Paris."
      },
      "relevance_score": 0.99853515625
    },
    {
      "index": 0,
      "document": {
        "text": "The capital of Brazil is Brasilia."
      },
      "relevance_score": 0.0005860328674316406
    }
  ]
}`;

// ---------- Models ----------

interface ModelEntry { name: string; type: string; typeColor: string; description: string }

const SUPPORTED_MODELS: ModelEntry[] = [
  {
    name: 'qwen3-rerank',
    type: '文本',
    typeColor: 'bg-green-100 text-green-700',
    description: '通义千问文本排序模型，支持多语言查询与文档，适合语义搜索重排序',
  },
  {
    name: 'qwen3-vl-rerank',
    type: '多模态',
    typeColor: 'bg-purple-100 text-purple-700',
    description: '通义千问多模态排序模型，支持文本、图片、视频混合查询与文档排序',
  },
];

// ---------- sub-components ----------

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

interface CardProps {
  id: string;
  icon: React.ReactNode;
  title: string;
  badge: string;
  badgeColor: string;
  description: string;
  children: React.ReactNode;
}

function Card({ id, icon, title, badge, badgeColor, description, children }: CardProps) {
  return (
    <div id={id} className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
      <div className="p-6 border-b border-slate-100">
        <div className="flex items-center gap-3 mb-2">
          <div className="p-2 bg-blue-50 rounded-lg text-blue-600">{icon}</div>
          <h3 className="text-lg font-semibold text-slate-800">{title}</h3>
          <span className={`ml-auto px-2.5 py-0.5 rounded-full text-xs font-medium ${badgeColor}`}>{badge}</span>
        </div>
        <p className="text-sm text-slate-500 ml-12">{description}</p>
      </div>
      <div className="p-6 space-y-4">{children}</div>
    </div>
  );
}

function ParamTable({ rows }: { rows: { name: string; required: boolean; type: string; desc: string }[] }) {
  return (
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
          {rows.map((r) => (
            <tr key={r.name} className="hover:bg-slate-50">
              <td className="px-4 py-2.5"><code className="text-blue-600 font-semibold">{r.name}</code></td>
              <td className="px-4 py-2.5 text-slate-500 font-mono text-xs">{r.type}</td>
              <td className="px-4 py-2.5">{r.required ? <span className="text-red-500">是</span> : <span className="text-slate-400">否</span>}</td>
              <td className="px-4 py-2.5 text-slate-600">{r.desc}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------- TOC component ----------

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
                  ? 'bg-blue-50 text-blue-600 font-medium border-l-2 border-blue-500'
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

// ---------- main ----------

export default function HelpRerank() {
  const navigate = useNavigate();
  const baseUrl = useBaseUrl();
  const [showCurl1, setShowCurl1] = useState(false);
  const [showCurl2, setShowCurl2] = useState(false);
  const [showCurl3, setShowCurl3] = useState(false);

  return (
    <div className="flex gap-8 max-w-6xl mx-auto">
      {/* Main content */}
      <div className="flex-1 min-w-0 space-y-8">
        {/* Back + header */}
        <div>
          <button
            onClick={() => navigate('/help')}
            className="flex items-center gap-1.5 text-sm text-slate-500 hover:text-blue-600 mb-4 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            返回帮助中心
          </button>
          <div className="flex items-center gap-4">
            <div className="p-3 bg-gradient-to-br from-orange-500 to-rose-600 rounded-2xl shadow-lg shadow-orange-500/25">
              <AlignLeft className="w-7 h-7 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900">Rerank API</h1>
              <p className="text-slate-500 text-sm mt-0.5">文档重排序接口使用指南</p>
            </div>
          </div>
        </div>

        {/* Endpoint info */}
        <div className="bg-orange-50 border border-orange-100 rounded-xl p-4 flex flex-wrap gap-4 items-center">
          <div>
            <span className="text-xs font-semibold text-orange-400 uppercase tracking-wide">Endpoint</span>
            <p className="font-mono text-sm text-orange-900 mt-0.5">{baseUrl}/v1/rerank</p>
          </div>
          <div className="h-8 w-px bg-orange-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-orange-400 uppercase tracking-wide">Method</span>
            <p className="text-sm font-medium text-orange-900 mt-0.5">POST</p>
          </div>
          <div className="h-8 w-px bg-orange-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-orange-400 uppercase tracking-wide">Auth</span>
            <p className="font-mono text-sm text-orange-900 mt-0.5">Bearer &lt;API_KEY&gt;</p>
          </div>
        </div>

        {/* Text Rerank */}
        <Card
          id="text-rerank"
          icon={<AlignLeft className="w-5 h-5" />}
          title="文本 Rerank"
          badge="文本"
          badgeColor="bg-green-100 text-green-700"
          description="对候选文本列表按查询相关性重新排序，返回 top_n 个最相关结果及相关性分数。"
        >
          <ParamTable rows={[
            { name: 'model',            required: true,  type: 'string',          desc: '模型名称，如 qwen3-rerank' },
            { name: 'query',            required: true,  type: 'string',          desc: '查询文本' },
            { name: 'documents',        required: true,  type: 'string[]',        desc: '候选文本列表' },
            { name: 'top_n',            required: false, type: 'number',          desc: '返回最相关的前 N 个结果' },
            { name: 'return_documents', required: false, type: 'boolean',         desc: '是否在结果中返回文档内容，默认 true' },
            { name: 'instruct',         required: false, type: 'string',          desc: '可选指令，引导模型理解检索任务类型' },
          ]} />

          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide">请求体</span>
              <button onClick={() => setShowCurl1(v => !v)} className="text-xs text-blue-500 hover:text-blue-700 underline underline-offset-2">
                {showCurl1 ? '隐藏 cURL' : '查看 cURL'}
              </button>
            </div>
            <CodeBlock code={TEXT_RERANK} />
          </div>
          {showCurl1 && (
            <div>
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">cURL 示例</span>
              <CodeBlock code={CURL_TEXT(baseUrl)} lang="bash" />
            </div>
          )}
        </Card>

        {/* Multimodal Rerank */}
        <Card
          id="multimodal-rerank"
          icon={<Image className="w-5 h-5" />}
          title="多模态 Rerank"
          badge="多模态"
          badgeColor="bg-purple-100 text-purple-700"
          description="支持文本、图片、视频混合输入，query 和 documents 均可为多模态内容。"
        >
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">
            <strong>注意：</strong>多模态 Rerank 使用 Dashscope 专用 API（非 compatible-api），query 和 documents 需为 dict 格式（<code>{"{"}"text": "..."{"}"}</code> / <code>{"{"}"image": "..."{"}"}</code> / <code>{"{"}"video": "..."{"}"}</code>）。
          </div>

          <ParamTable rows={[
            { name: 'model',            required: true,  type: 'string',                    desc: '模型名称，如 qwen3-vl-rerank' },
            { name: 'query',            required: true,  type: 'object | string',           desc: '查询内容，可为 {"text": "..."} / {"image": "..."} / {"video": "..."}' },
            { name: 'documents',        required: true,  type: 'object[]',                  desc: '候选文档列表，每项为 {"text": ...} / {"image": ...} / {"video": ...}' },
            { name: 'top_n',            required: false, type: 'number',                    desc: '返回最相关的前 N 个结果' },
            { name: 'return_documents', required: false, type: 'boolean',                   desc: '是否返回文档内容，默认 true' },
          ]} />

          <div className="space-y-4">
            <div>
              <p className="text-sm font-medium text-slate-700 mb-2">示例一：文本查询 + 混合文档</p>
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide">请求体</span>
                <button onClick={() => setShowCurl2(v => !v)} className="text-xs text-blue-500 hover:text-blue-700 underline underline-offset-2">
                  {showCurl2 ? '隐藏 cURL' : '查看 cURL'}
                </button>
              </div>
              <CodeBlock code={MULTIMODAL_TEXT_QUERY} />
              {showCurl2 && (
                <div className="mt-3">
                  <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">cURL 示例</span>
                  <CodeBlock code={CURL_MULTIMODAL(baseUrl)} lang="bash" />
                </div>
              )}
            </div>

            <div>
              <p className="text-sm font-medium text-slate-700 mb-2">示例二：图片查询 + 混合文档</p>
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide">请求体</span>
                <button onClick={() => setShowCurl3(v => !v)} className="text-xs text-blue-500 hover:text-blue-700 underline underline-offset-2">
                  {showCurl3 ? '隐藏 cURL' : '查看 cURL'}
                </button>
              </div>
              <CodeBlock code={MULTIMODAL_IMAGE_QUERY} />
              {showCurl3 && (
                <div className="mt-3">
                  <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">cURL 示例</span>
                  <CodeBlock code={`curl -X POST ${baseUrl}/v1/rerank \\\n  -H "Authorization: Bearer <YOUR_API_KEY>" \\\n  -H "Content-Type: application/json" \\\n  -d '${MULTIMODAL_IMAGE_QUERY}'`} lang="bash" />
                </div>
              )}
            </div>
          </div>
        </Card>

        {/* Response format */}
        <div id="response-format" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <h3 className="text-lg font-semibold text-slate-800">响应格式</h3>
            <p className="text-sm text-slate-500 mt-1">兼容 vLLM Rerank API 响应格式，results 按 relevance_score 降序排列。</p>
          </div>
          <div className="p-6">
            <CodeBlock code={RESPONSE_EXAMPLE} />
          </div>
        </div>

        {/* Supported models */}
        <div id="supported-models" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <h3 className="text-lg font-semibold text-slate-800">支持的模型</h3>
            <p className="text-sm text-slate-500 mt-1">以下模型可通过本 API 调用，请在配置供应商时选择对应模型。</p>
          </div>
          <div className="divide-y divide-slate-100">
            {SUPPORTED_MODELS.map((m) => (
              <div key={m.name} className="px-6 py-4 flex items-start gap-4">
                <span className={`mt-0.5 flex-shrink-0 px-2.5 py-0.5 rounded-full text-xs font-medium ${m.typeColor}`}>{m.type}</span>
                <div className="flex-1 min-w-0">
                  <code className="text-sm font-semibold text-slate-800">{m.name}</code>
                  <p className="text-sm text-slate-500 mt-0.5">{m.description}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right TOC */}
      <TableOfContents items={TOC_ITEMS} />
    </div>
  );
}
