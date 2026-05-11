import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Copy, Check, Layers, MessageSquare, FileText, Image, ArrowLeft } from 'lucide-react';

import { useBaseUrl } from '../components/help/HelpShared';


// ---------- TOC definition ----------

interface TocItem {
  id: string;
  label: string;
}

const TOC_ITEMS: TocItem[] = [
  { id: 'text-single', label: '文本 Embedding' },
  { id: 'text-array', label: '文本数组 Embedding' },
  { id: 'multimodal-object', label: '多模态（对象格式）' },
  { id: 'multimodal-array', label: '多模态（数组格式）' },
  { id: 'multimodal-messages', label: '多模态（messages 格式）' },
  { id: 'doubao-embedding', label: 'Doubao 视觉嵌入' },
  { id: 'response-format', label: '响应格式' },
  { id: 'supported-models', label: '支持的模型' },
];

// ---------- code samples ----------

const TEXT_SINGLE = `{
  "model": "text-embedding-v4",
  "input": "你是谁",
  "dimensions": "64",
  "encoding_format": "float"
}`;

const TEXT_ARRAY = `{
  "model": "text-embedding-v4",
  "input": [
    "你是谁",
    "介绍一下你自己"
  ],
  "dimensions": "64",
  "encoding_format": "float"
}`;

const MULTIMODAL_OBJECT = `{
  "model": "qwen3-vl-embedding",
  "input": {
    "contents": [
      {
        "type": "text",
        "text": "这是一段测试文本，用于生成多模态融合向量"
      },
      {
        "type": "image_url",
        "image_url": {
          "url": "https://dashscope.oss-cn-beijing.aliyuncs.com/images/256_1.png"
        }
      },
      {
        "type": "video_url",
        "video_url": {
          "url": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20250107/lbcemt/new+video.mp4"
        }
      }
    ]
  },
  "parameters": {
    "dimension": "256"
  }
}`;

const MULTIMODAL_ARRAY = `{
  "model": "qwen3-vl-embedding",
  "input": [
    {
      "content": [
        {
          "type": "text",
          "text": "这是一段测试文本，用于生成多模态融合向量"
        },
        {
          "type": "image_url",
          "image_url": {
            "url": "https://dashscope.oss-cn-beijing.aliyuncs.com/images/256_1.png"
          }
        },
        {
          "type": "video_url",
          "video_url": {
            "url": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20250107/lbcemt/new+video.mp4"
          }
        }
      ]
    }
  ]
}`;

const MULTIMODAL_MESSAGES = `{
  "model": "qwen3-vl-embedding",
  "dimensions": "256",
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "这是一段测试文本，用于生成多模态融合向量"
        },
        {
          "type": "image_url",
          "image_url": {
            "url": "https://dashscope.oss-cn-beijing.aliyuncs.com/images/256_1.png"
          }
        },
        {
          "type": "video_url",
          "video_url": {
            "url": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20250107/lbcemt/new+video.mp4"
          }
        }
      ]
    }
  ]
}`;

const DOUBAO_EMBEDDING = `{
  "model": "doubao-embedding-vision",
  "encoding_format": "float",
  "input": [
    {
      "type": "video_url",
      "video_url": {
        "url": "https://ark-project.tos-cn-beijing.volces.com/doc_video/demo.mp4"
      }
    },
    {
      "type": "image_url",
      "image_url": {
        "url": "https://ark-project.tos-cn-beijing.volces.com/doc_image/demo.png"
      }
    },
    {
      "type": "text",
      "text": "视频和图片里有什么"
    }
  ]
}`;

const curlPrefix = (baseUrl: string, body: string) =>
  `curl -X POST ${baseUrl}/v1/embeddings \\\n  -H "Authorization: Bearer <YOUR_API_KEY>" \\\n  -H "Content-Type: application/json" \\\n  -d '${body}'`;

// ---------- Supported models ----------

interface ModelEntry {
  name: string;
  type: string;
  typeColor: string;
  description: string;
}

const SUPPORTED_MODELS: ModelEntry[] = [
  {
    name: 'text-embedding-v4',
    type: '文本',
    typeColor: 'bg-green-100 text-green-700',
    description: '通用文本向量模型，支持多语言，适合语义搜索、RAG 等场景',
  },
  {
    name: 'text-embedding-v3',
    type: '文本',
    typeColor: 'bg-green-100 text-green-700',
    description: '通用文本向量模型（上一代），兼容旧版接入',
  },
  {
    name: 'qwen3-vl-embedding',
    type: '多模态',
    typeColor: 'bg-purple-100 text-purple-700',
    description: '支持文本、图片、视频混合输入，生成融合多模态向量',
  },
  {
    name: 'doubao-embedding-vision',
    type: '多模态',
    typeColor: 'bg-purple-100 text-purple-700',
    description: '豆包视觉嵌入模型，支持文本、图片、视频多模态向量生成',
  },
  ];

// ---------- sub-components ----------

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <button
      onClick={handleCopy}
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

interface SectionProps {
  id: string;
  icon: React.ReactNode;
  title: string;
  badge: string;
  badgeColor: string;
  description: string;
  jsonBody: string;
  children?: React.ReactNode;
}

function Section({ id, icon, title, badge, badgeColor, description, jsonBody, children }: SectionProps) {
  const baseUrl = useBaseUrl();
  const [showCurl, setShowCurl] = useState(false);
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
      <div className="p-6 space-y-4">
        {children}
        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide">请求体</span>
            <button
              onClick={() => setShowCurl((v) => !v)}
              className="text-xs text-blue-500 hover:text-blue-700 underline underline-offset-2"
            >
              {showCurl ? '隐藏 cURL' : '查看 cURL'}
            </button>
          </div>
          <CodeBlock code={jsonBody} />
        </div>
        {showCurl && (
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">cURL 示例</span>
            <CodeBlock code={curlPrefix(baseUrl, jsonBody)} lang="bash" />
          </div>
        )}
      </div>
    </div>
  );
}

// ---------- TOC component ----------

function TableOfContents({ items }: { items: TocItem[] }) {
  const [active, setActive] = useState<string>(items[0]?.id ?? '');
  const scrollContainerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    // Find the scrollable main container
    scrollContainerRef.current = document.querySelector('main') as HTMLElement;
    const container = scrollContainerRef.current;
    if (!container) return;

    const handleScroll = () => {
      let current = items[0]?.id ?? '';
      for (const item of items) {
        const el = document.getElementById(item.id);
        if (el) {
          const rect = el.getBoundingClientRect();
          const containerRect = container.getBoundingClientRect();
          if (rect.top - containerRect.top <= 80) {
            current = item.id;
          }
        }
      }
      setActive(current);
    };

    container.addEventListener('scroll', handleScroll, { passive: true });
    return () => container.removeEventListener('scroll', handleScroll);
  }, [items]);

  const scrollTo = (id: string) => {
    const el = document.getElementById(id);
    const container = scrollContainerRef.current;
    if (el && container) {
      const elTop = el.getBoundingClientRect().top;
      const containerTop = container.getBoundingClientRect().top;
      container.scrollTo({ top: container.scrollTop + elTop - containerTop - 16, behavior: 'smooth' });
    }
  };

  return (
    <aside className="w-52 flex-shrink-0 hidden xl:block">
      <div className="sticky top-0 pt-0">
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

// ---------- main page ----------

export default function HelpEmbedding() {
  const navigate = useNavigate();
  const baseUrl = useBaseUrl();

  return (
    <div className="flex gap-8 max-w-6xl mx-auto">
      {/* Main content */}
      <div className="flex-1 min-w-0 space-y-8">
        {/* Back button + header */}
        <div>
          <button
            onClick={() => navigate('/help')}
            className="flex items-center gap-1.5 text-sm text-slate-500 hover:text-blue-600 mb-4 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            返回帮助中心
          </button>
          <div className="flex items-center gap-4">
            <div className="p-3 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-2xl shadow-lg shadow-blue-500/25">
              <Layers className="w-7 h-7 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900">Embedding API</h1>
              <p className="text-slate-500 text-sm mt-0.5">向量嵌入接口使用指南</p>
            </div>
          </div>
        </div>

        {/* Endpoint info */}
        <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 flex flex-wrap gap-4 items-center">
          <div>
            <span className="text-xs font-semibold text-blue-400 uppercase tracking-wide">Endpoint</span>
            <p className="font-mono text-sm text-blue-900 mt-0.5">{baseUrl}/v1/embeddings</p>
          </div>
          <div className="h-8 w-px bg-blue-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-blue-400 uppercase tracking-wide">Method</span>
            <p className="text-sm font-medium text-blue-900 mt-0.5">POST</p>
          </div>
          <div className="h-8 w-px bg-blue-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-blue-400 uppercase tracking-wide">Auth</span>
            <p className="font-mono text-sm text-blue-900 mt-0.5">Bearer &lt;API_KEY&gt;</p>
          </div>
        </div>

        {/* Sections */}
        <div className="space-y-6">
          <Section
            id="text-single"
            icon={<FileText className="w-5 h-5" />}
            title="文本 Embedding"
            badge="文本"
            badgeColor="bg-green-100 text-green-700"
            description="对单条文本生成向量表示，适用于语义搜索、相似度计算等场景。"
            jsonBody={TEXT_SINGLE}
          >
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
              {[
                { name: 'model', required: true, desc: '模型名称' },
                { name: 'input', required: true, desc: '输入文本' },
                { name: 'dimensions', required: false, desc: '向量维度' },
                { name: 'encoding_format', required: false, desc: '"float" 或 "base64"' },
              ].map((p) => (
                <div key={p.name} className="bg-slate-50 rounded-lg p-3">
                  <div className="flex items-center gap-1 mb-1">
                    <code className="text-blue-600 font-semibold text-xs">{p.name}</code>
                    {p.required && <span className="text-red-400 text-xs">*</span>}
                  </div>
                  <p className="text-slate-500 text-xs">{p.desc}</p>
                </div>
              ))}
            </div>
          </Section>

          <Section
            id="text-array"
            icon={<FileText className="w-5 h-5" />}
            title="文本数组 Embedding"
            badge="文本"
            badgeColor="bg-green-100 text-green-700"
            description="批量对多条文本生成向量，一次请求处理多个输入，返回对应的向量列表。"
            jsonBody={TEXT_ARRAY}
          />

          <Section
            id="multimodal-object"
            icon={<Image className="w-5 h-5" />}
            title="多模态 Embedding（input 对象格式）"
            badge="多模态"
            badgeColor="bg-purple-100 text-purple-700"
            description="将文本、图片、视频混合输入，通过 input.contents 传入 content block 列表。适用于 qwen3-vl-embedding 等多模态模型。"
            jsonBody={MULTIMODAL_OBJECT}
          >
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">
              <strong>注意：</strong>使用多模态 Embedding 时，需要在模型管理后台勾选{' '}
              <code>support_image</code> 或 <code>support_video</code>，否则会走文本 Embedding API。
            </div>
          </Section>

          <Section
            id="multimodal-array"
            icon={<Image className="w-5 h-5" />}
            title="多模态 Embedding（input 数组格式）"
            badge="多模态"
            badgeColor="bg-purple-100 text-purple-700"
            description="input 为数组，每个元素包含 content 字段（content block 列表），支持批量多模态输入。"
            jsonBody={MULTIMODAL_ARRAY}
          />

          <Section
            id="multimodal-messages"
            icon={<MessageSquare className="w-5 h-5" />}
            title="多模态 Embedding（messages 格式）"
            badge="多模态"
            badgeColor="bg-purple-100 text-purple-700"
            description="使用 messages 字段传入多模态内容，格式与 Chat Completions API 一致，适合从对话场景迁移。"
            jsonBody={MULTIMODAL_MESSAGES}
          />

          <Section
            id="doubao-embedding"
            icon={<Layers className="w-5 h-5" />}
            title="Doubao 视觉嵌入"
            badge="多模态"
            badgeColor="bg-purple-100 text-purple-700"
            description="doubao-embedding-vision 使用 content block 数组格式传入文本、图片、视频，底层调用火山引擎 /embeddings/multimodal 端点，返回融合后的多模态向量。支持在线图片/视频 URL。"
            jsonBody={DOUBAO_EMBEDDING}
          >
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-800 space-y-2">
              <p><strong>与通用多模态 Embedding 的差异：</strong></p>
              <ul className="list-disc list-inside space-y-1">
                <li><code>input</code> 直接传入 content block 数组，无需包裹在 <code>contents</code> 或 <code>content</code> 字段中</li>
                <li>固定使用 <code>encoding_format: "float"</code>，返回 float 向量</li>
                <li><code>dimensions</code> 为整数类型（非字符串），可选参数</li>
                <li>单次请求生成一个融合向量，将所有输入（文本+图片+视频）合并为一个 embedding</li>
              </ul>
            </div>
            <div>
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">参数说明</span>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-sm">
                {[
                  { name: 'model', required: true, desc: 'doubao-embedding-vision' },
                  { name: 'input', required: true, desc: 'content block 数组' },
                  { name: 'encoding_format', required: false, desc: '"float"（仅支持 float）' },
                  { name: 'dimensions', required: false, desc: '向量维度（1024 或 2048）' },
                  { name: 'type: text', required: false, desc: '文本块' },
                  { name: 'type: image_url', required: false, desc: '图片 URL 块' },
                  { name: 'type: video_url', required: false, desc: '视频 URL 块' },
                ].map((p) => (
                  <div key={p.name} className="bg-slate-50 rounded-lg p-3">
                    <div className="flex items-center gap-1 mb-1">
                      <code className="text-blue-600 font-semibold text-xs">{p.name}</code>
                      {p.required && <span className="text-red-400 text-xs">*</span>}
                    </div>
                    <p className="text-slate-500 text-xs">{p.desc}</p>
                  </div>
                ))}
              </div>
            </div>
            <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-sm text-slate-600">
              <strong>官方文档：</strong>
              <a
                href="https://www.volcengine.com/docs/82379/1409291?lang=zh"
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-600 hover:text-blue-800 underline underline-offset-2 ml-1"
              >
                火山引擎多模态向量化 API 文档
              </a>
            </div>
          </Section>

          {/* Response format */}
          <div id="response-format" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
            <div className="p-6 border-b border-slate-100">
              <h3 className="text-lg font-semibold text-slate-800">响应格式</h3>
              <p className="text-sm text-slate-500 mt-1">所有 Embedding 请求均返回统一格式的响应。</p>
            </div>
            <div className="p-6">
              <CodeBlock code={`{
  "object": "list",
  "data": [
    {
      "object": "embedding",
      "index": 0,
      "embedding": [0.0023064255, -0.009327292, ...]
    }
  ],
  "model": "text-embedding-v4",
  "usage": {
    "prompt_tokens": 8,
    "total_tokens": 8
  }
}`} />
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
                  <span className={`mt-0.5 flex-shrink-0 px-2.5 py-0.5 rounded-full text-xs font-medium ${m.typeColor}`}>
                    {m.type}
                  </span>
                  <div className="flex-1 min-w-0">
                    <code className="text-sm font-semibold text-slate-800">{m.name}</code>
                    <p className="text-sm text-slate-500 mt-0.5">{m.description}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Right TOC */}
      <TableOfContents items={TOC_ITEMS} />
    </div>
  );
}
