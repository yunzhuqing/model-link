import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Copy, Check, ArrowLeft, MessageCircle } from 'lucide-react';
import { useBaseUrl } from '../components/help/HelpShared';


// ---------- TOC ----------

interface TocItem { id: string; label: string }

const TOC_ITEMS: TocItem[] = [
  { id: 'basic-request', label: '基础对话请求' },
  { id: 'streaming', label: '流式响应' },
  { id: 'with-tools', label: '工具调用' },
  { id: 'vision', label: '图片理解' },
  { id: 'video-understanding', label: '视频理解' },
  { id: 'response-format', label: '响应格式' },
];

// ---------- code samples ----------

const BASIC_REQUEST = `{
  "model": "qwen-max",
  "messages": [
    {
      "role": "system",
      "content": "你是一个专业的 AI 助手。"
    },
    {
      "role": "user",
      "content": "你好，请介绍一下你自己"
    }
  ],
  "max_tokens": 1024,
  "temperature": 0.7
}`;

const MULTI_TURN = `{
  "model": "qwen-max",
  "messages": [
    {"role": "user", "content": "1+1等于多少？"},
    {"role": "assistant", "content": "1+1等于2。"},
    {"role": "user", "content": "那2+2呢？"}
  ]
}`;

const STREAMING_REQUEST = `{
  "model": "qwen-max",
  "messages": [
    {"role": "user", "content": "写一首关于春天的诗"}
  ],
  "stream": true
}`;

const WITH_TOOLS = `{
  "model": "qwen-max",
  "messages": [
    {"role": "user", "content": "今天北京天气怎么样？"}
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "获取指定城市的天气信息",
        "parameters": {
          "type": "object",
          "properties": {
            "city": {
              "type": "string",
              "description": "城市名称"
            }
          },
          "required": ["city"]
        }
      }
    }
  ],
  "tool_choice": "auto"
}`;

const VISION_REQUEST = `{
  "model": "qwen-vl-max",
  "messages": [
    {
      "content": "You are a helpful assistant",
      "role": "system"
    },
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "图片里面是什么?"
        },
        {
          "type": "image_url",
          "image_url": {
            "url": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20250212/earbrt/vcg_VCG211286867973_RF.jpg"
          }
        }
      ]
    }
  ],
  "stream": true,
  "temperature": 0.7
}`;

const VIDEO_UNDERSTANDING_REQUEST = `{
  "model": "qwen3.6-plus",
  "messages": [
    {
      "role": "system",
      "content": "You are a helpful assistant"
    },
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "视频里面是什么?"
        },
        {
          "type": "video_url",
          "video_url": {
            "url": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20241115/cqqkru/1.mp4",
            "fps": "2"
          }
        }
      ]
    }
  ],
  "stream": true,
  "temperature": 0.7
}`;

const BASIC_RESPONSE = `{
  "id": "chatcmpl-abc123...",
  "object": "chat.completion",
  "created": 1714000000,
  "model": "qwen-max",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "你好！我是通义千问，一个由阿里云开发的 AI 助手..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 20,
    "completion_tokens": 48,
    "total_tokens": 68
  }
}`;

const STREAMING_RESPONSE = `data: {"id":"chatcmpl-abc","object":"chat.completion.chunk","choices":[{"delta":{"role":"assistant","content":""},"index":0}]}

data: {"id":"chatcmpl-abc","object":"chat.completion.chunk","choices":[{"delta":{"content":"你"},"index":0}]}

data: {"id":"chatcmpl-abc","object":"chat.completion.chunk","choices":[{"delta":{"content":"好"},"index":0}]}

data: {"id":"chatcmpl-abc","object":"chat.completion.chunk","choices":[{"delta":{},"finish_reason":"stop","index":0}]}

data: [DONE]`;

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

interface SectionCardProps {
  id: string;
  title: string;
  description: string;
  badge?: string;
  badgeColor?: string;
  children: React.ReactNode;
}

function SectionCard({ id, title, description, badge, badgeColor, children }: SectionCardProps) {
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
  const curl = `curl -X POST ${baseUrl}/v1/chat/completions \\\n  -H "Authorization: Bearer <YOUR_API_KEY>" \\\n  -H "Content-Type: application/json" \\\n  -d '${body}'`;
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
        if (el && el.getBoundingClientRect().top - container.getBoundingClientRect().top <= 80) cur = item.id;
      }
      setActive(cur);
    };
    container.addEventListener('scroll', onScroll, { passive: true });
    return () => container.removeEventListener('scroll', onScroll);
  }, [items]);
  const scrollTo = (id: string) => {
    const el = document.getElementById(id);
    const container = scrollRef.current;
    if (el && container) container.scrollTo({ top: container.scrollTop + el.getBoundingClientRect().top - container.getBoundingClientRect().top - 16, behavior: 'smooth' });
  };
  return (
    <aside className="w-52 flex-shrink-0 hidden xl:block">
      <div className="sticky top-0">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3 px-1">本页内容</p>
        <nav className="space-y-0.5">
          {items.map((item) => (
            <button key={item.id} onClick={() => scrollTo(item.id)}
              className={`w-full text-left px-3 py-1.5 rounded-lg text-sm transition-all duration-150 ${active === item.id ? 'bg-blue-50 text-blue-600 font-medium border-l-2 border-blue-500' : 'text-slate-500 hover:text-slate-800 hover:bg-slate-50'}`}>
              {item.label}
            </button>
          ))}
        </nav>
      </div>
    </aside>
  );
}

// ---------- main ----------

export default function HelpChat() {
  const navigate = useNavigate();
  const baseUrl = useBaseUrl();
  return (
    <div className="flex gap-8 max-w-6xl mx-auto">
      <div className="flex-1 min-w-0 space-y-8">
        <div>
          <button onClick={() => navigate('/help')} className="flex items-center gap-1.5 text-sm text-slate-500 hover:text-blue-600 mb-4 transition-colors">
            <ArrowLeft className="w-4 h-4" />返回帮助中心
          </button>
          <div className="flex items-center gap-4">
            <div className="p-3 bg-gradient-to-br from-sky-500 to-blue-600 rounded-2xl shadow-lg shadow-sky-500/25">
              <MessageCircle className="w-7 h-7 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900">Chat Completions API</h1>
              <p className="text-slate-500 text-sm mt-0.5">OpenAI Chat Completions 兼容接口使用指南</p>
            </div>
          </div>
        </div>

        {/* Endpoint info */}
        <div className="bg-sky-50 border border-sky-100 rounded-xl p-4 flex flex-wrap gap-4 items-center">
          <div><span className="text-xs font-semibold text-sky-400 uppercase tracking-wide">Endpoint</span>
            <p className="font-mono text-sm text-sky-900 mt-0.5">{baseUrl}/v1/chat/completions</p></div>
          <div className="h-8 w-px bg-sky-200 hidden sm:block" />
          <div><span className="text-xs font-semibold text-sky-400 uppercase tracking-wide">Method</span>
            <p className="text-sm font-medium text-sky-900 mt-0.5">POST</p></div>
          <div className="h-8 w-px bg-sky-200 hidden sm:block" />
          <div><span className="text-xs font-semibold text-sky-400 uppercase tracking-wide">Auth</span>
            <p className="font-mono text-sm text-sky-900 mt-0.5">Bearer &lt;API_KEY&gt;</p></div>
        </div>

        {/* Basic request */}
        <SectionCard id="basic-request" title="基础对话请求" description="通过 messages 数组传入对话历史，支持 system / user / assistant 三种角色。">
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
                  { name: 'model',       required: true,  type: 'string',  desc: '模型名称或别名' },
                  { name: 'messages',    required: true,  type: 'array',   desc: '对话消息列表，每项含 role 和 content' },
                  { name: 'stream',      required: false, type: 'boolean', desc: '是否流式输出，默认 false' },
                  { name: 'max_tokens',  required: false, type: 'number',  desc: '最大输出 token 数' },
                  { name: 'temperature', required: false, type: 'number',  desc: '采样温度，0~2' },
                  { name: 'top_p',       required: false, type: 'number',  desc: 'Top-p 采样参数' },
                  { name: 'tools',       required: false, type: 'array',   desc: '工具列表（Function Calling）' },
                  { name: 'tool_choice', required: false, type: 'string',  desc: '"auto" | "none" | 指定函数名' },
                ].map((r) => (
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
          <div>
            <p className="text-sm font-medium text-slate-700 mb-2">单轮对话</p>
            <CurlSection body={BASIC_REQUEST} />
          </div>
          <div>
            <p className="text-sm font-medium text-slate-700 mb-2">多轮对话（携带历史消息）</p>
            <CurlSection body={MULTI_TURN} />
          </div>
        </SectionCard>

        {/* Streaming */}
        <SectionCard id="streaming" title="流式响应" badge="SSE" badgeColor="bg-blue-100 text-blue-700"
          description='设置 "stream": true，服务端以 Server-Sent Events 格式逐 token 推送内容，最后发送 [DONE] 信号。'>
          <CurlSection body={STREAMING_REQUEST} />
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">SSE 响应格式</span>
            <CodeBlock code={STREAMING_RESPONSE} lang="bash" />
          </div>
        </SectionCard>

        {/* Tools */}
        <SectionCard id="with-tools" title="工具调用（Function Calling）" badge="Tools" badgeColor="bg-violet-100 text-violet-700"
          description="在 tools 中声明可调用函数，模型在判断需要时返回 tool_calls，客户端执行后将结果以 tool 角色消息发回继续对话。">
          <CurlSection body={WITH_TOOLS} />
        </SectionCard>

        {/* Vision */}
        <SectionCard id="vision" title="图片理解（Vision）" badge="Vision" badgeColor="bg-pink-100 text-pink-700"
          description="content 支持数组格式，可同时传入文本和图片（image_url），适用于支持视觉能力的多模态模型。">
          <CurlSection body={VISION_REQUEST} />
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">
            <strong>注意：</strong>图片理解需要使用支持视觉的模型，如 <code>qwen-vl-max</code>、<code>qwen-vl-plus</code> 等，请确保模型配置中已勾选 <code>support_image</code>。
          </div>
        </SectionCard>

        {/* Video Understanding */}
        <SectionCard id="video-understanding" title="视频理解（Video Understanding）" badge="Video" badgeColor="bg-green-100 text-green-700"
          description="content 支持数组格式，可同时传入文本和视频（video_url）。通过 fps 参数控制视频采样帧率，适用于支持视频理解的多模态模型。">
          <CurlSection body={VIDEO_UNDERSTANDING_REQUEST} />
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">
            <strong>注意：</strong>视频理解需要使用支持视频输入的模型，如 <code>qwen3.6-plus</code> 等。<code>video_url</code> 中的 <code>fps</code> 参数用于控制视频采样帧率，可按需调整。
          </div>
        </SectionCard>

        {/* Response format */}
        <div id="response-format" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <h3 className="text-lg font-semibold text-slate-800">响应格式</h3>
            <p className="text-sm text-slate-500 mt-1">兼容 OpenAI Chat Completions API 响应格式。</p>
          </div>
          <div className="p-6"><CodeBlock code={BASIC_RESPONSE} /></div>
        </div>
      </div>
      <TableOfContents items={TOC_ITEMS} />
    </div>
  );
}
