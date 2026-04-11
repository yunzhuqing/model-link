import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Copy, Check, ArrowLeft, Zap } from 'lucide-react';

const BASE_URL = 'http://localhost:8000';

// ---------- TOC ----------

interface TocItem { id: string; label: string }

const TOC_ITEMS: TocItem[] = [
  { id: 'basic-request', label: '基础对话请求' },
  { id: 'streaming', label: '流式响应' },
  { id: 'with-tools', label: '工具调用' },
  { id: 'image-generation', label: '图片生成' },
  { id: 'video-generation', label: '视频生成' },
  { id: 'background', label: '后台异步请求' },
  { id: 'get-response', label: '查询异步结果' },
  { id: 'response-format', label: '响应格式' },
];

// ---------- code samples ----------

const BASIC_REQUEST = `{
  "model": "qwen-max",
  "input": [
    {
      "role": "user",
      "content": "你好，请介绍一下你自己"
    }
  ],
  "max_output_tokens": 1024,
  "temperature": 0.7
}`;

const STREAMING_REQUEST = `{
  "model": "qwen-max",
  "input": [
    {
      "role": "user",
      "content": "写一首关于春天的诗"
    }
  ],
  "stream": true
}`;

const WITH_TOOLS = `{
  "model": "qwen-max",
  "input": [
    {
      "role": "user",
      "content": "今天北京天气怎么样？"
    }
  ],
  "tools": [
    {
      "type": "function",
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
  ]
}`;

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

const VIDEO_GENERATION = `{
  "model": "doubao-seedance-2.0",
  "background": true,
  "input": [
    {
      "role": "user",
      "type": "message",
      "content": [
        {
          "type": "input_text",
          "text": "生成两只猫打架"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "video_generation",
      "size": "496×864"
    }
  ]
}`;

const VIDEO_GENERATION_REF = `{
  "model": "doubao-seedance-2.0",
  "background": true,
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        {
          "type": "input_text",
          "text": "全程使用{{video_1}}的第一视角构图，全程使用{{audio_1}}作为背景音乐。第一人称视角果茶宣传广告，seedance牌「苹苹安安」苹果果茶限定款；首帧为{{apple_1}}..."
        },
        {
          "type": "input_image",
          "image_url": "https://ark-project.tos-cn-beijing.volces.com/doc_image/r2v_tea_pic1.jpg",
          "file_id": "apple_1"
        },
        {
          "type": "input_image",
          "image_url": "https://ark-project.tos-cn-beijing.volces.com/doc_image/r2v_tea_pic2.jpg",
          "file_id": "tea_1"
        },
        {
          "type": "input_video",
          "video_url": "https://ark-project.tos-cn-beijing.volces.com/doc_video/r2v_tea_video1.mp4",
          "file_id": "video_1"
        },
        {
          "type": "input_audio",
          "audio_url": "https://ark-project.tos-cn-beijing.volces.com/doc_audio/r2v_tea_audio1.mp3",
          "file_id": "audio_1"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "video_generation",
      "size": "496x864"
    }
  ]
}`;

const BACKGROUND_REQUEST = `{
  "model": "qwen-max",
  "input": [
    {
      "role": "user",
      "content": "写一篇关于人工智能发展历史的长文"
    }
  ],
  "background": true
}`;

const BACKGROUND_RESPONSE = `{
  "id": "resp_abc123def456...",
  "object": "response",
  "status": "in_progress",
  "model": "qwen-max",
  "background": true
}`;

const GET_RESPONSE = `GET ${BASE_URL}/v1/responses/{response_id}
Authorization: Bearer <YOUR_API_KEY>`;

const BASIC_RESPONSE = `{
  "id": "resp_abc123...",
  "object": "response",
  "status": "completed",
  "model": "qwen-max",
  "output": [
    {
      "type": "message",
      "role": "assistant",
      "content": [
        {
          "type": "output_text",
          "text": "你好！我是通义千问..."
        }
      ]
    }
  ],
  "usage": {
    "input_tokens": 12,
    "output_tokens": 48,
    "total_tokens": 60
  }
}`;

const STREAMING_SSE = `event: response.output_item.added
data: {"type":"response.output_item.added","output_index":0,"item":{...}}

event: response.output_text.delta
data: {"type":"response.output_text.delta","output_index":0,"content_index":0,"delta":"你好"}

event: response.output_text.delta
data: {"type":"response.output_text.delta","output_index":0,"content_index":0,"delta":"！"}

event: response.completed
data: {"type":"response.completed","response":{...}}`;

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
          {badge && (
            <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${badgeColor}`}>{badge}</span>
          )}
        </div>
        <p className="text-sm text-slate-500">{description}</p>
      </div>
      <div className="p-6 space-y-4">{children}</div>
    </div>
  );
}

function CurlSection({ method = 'POST', body }: { method?: string; body: string }) {
  const [show, setShow] = useState(false);
  const curl = method === 'GET'
    ? `curl -X GET "${BASE_URL}/v1/responses/{response_id}" \\\n  -H "Authorization: Bearer <YOUR_API_KEY>"`
    : `curl -X POST ${BASE_URL}/v1/responses \\\n  -H "Authorization: Bearer <YOUR_API_KEY>" \\\n  -H "Content-Type: application/json" \\\n  -d '${body}'`;

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

// ---------- TOC ----------

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

export default function HelpResponses() {
  const navigate = useNavigate();

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
            <div className="p-3 bg-gradient-to-br from-emerald-500 to-teal-600 rounded-2xl shadow-lg shadow-emerald-500/25">
              <Zap className="w-7 h-7 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900">Responses API</h1>
              <p className="text-slate-500 text-sm mt-0.5">OpenAI Responses API 兼容接口使用指南</p>
            </div>
          </div>
        </div>

        {/* Endpoint info */}
        <div className="bg-emerald-50 border border-emerald-100 rounded-xl p-4 flex flex-wrap gap-4 items-center">
          <div>
            <span className="text-xs font-semibold text-emerald-500 uppercase tracking-wide">Endpoint</span>
            <p className="font-mono text-sm text-emerald-900 mt-0.5">{BASE_URL}/v1/responses</p>
          </div>
          <div className="h-8 w-px bg-emerald-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-emerald-500 uppercase tracking-wide">Method</span>
            <p className="text-sm font-medium text-emerald-900 mt-0.5">POST</p>
          </div>
          <div className="h-8 w-px bg-emerald-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-emerald-500 uppercase tracking-wide">Auth</span>
            <p className="font-mono text-sm text-emerald-900 mt-0.5">Bearer &lt;API_KEY&gt;</p>
          </div>
        </div>

        {/* Basic request */}
        <SectionCard
          id="basic-request"
          title="基础对话请求"
          description="最简单的对话请求，通过 input 传入消息列表，支持多轮对话历史。"
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
                  { name: 'model',             required: true,  type: 'string',        desc: '模型名称或别名' },
                  { name: 'input',             required: true,  type: 'array',         desc: '对话消息列表，每项含 role 和 content' },
                  { name: 'stream',            required: false, type: 'boolean',       desc: '是否开启流式响应，默认 false' },
                  { name: 'max_output_tokens', required: false, type: 'number',        desc: '最大输出 token 数' },
                  { name: 'temperature',       required: false, type: 'number',        desc: '采样温度，0~2' },
                  { name: 'tools',             required: false, type: 'array',         desc: '工具列表，支持 function / image_generation' },
                  { name: 'background',        required: false, type: 'boolean',       desc: '是否异步后台执行，默认 false' },
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
          <CurlSection body={BASIC_REQUEST} />
        </SectionCard>

        {/* Streaming */}
        <SectionCard
          id="streaming"
          title="流式响应"
          badge="SSE"
          badgeColor="bg-blue-100 text-blue-700"
          description='设置 "stream": true 开启流式响应，服务端通过 Server-Sent Events（SSE）逐步推送内容。'
        >
          <CurlSection body={STREAMING_REQUEST} />
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">SSE 事件格式</span>
            <CodeBlock code={STREAMING_SSE} lang="bash" />
          </div>
          <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 text-sm text-blue-800">
            <strong>主要 SSE 事件类型：</strong>
            <ul className="mt-1.5 space-y-1 list-disc list-inside text-blue-700">
              <li><code>response.output_item.added</code> — 新输出项开始</li>
              <li><code>response.output_text.delta</code> — 文本增量内容</li>
              <li><code>response.output_item.done</code> — 输出项完成</li>
              <li><code>response.completed</code> — 整个响应完成</li>
            </ul>
          </div>
        </SectionCard>

        {/* Tool calling */}
        <SectionCard
          id="with-tools"
          title="工具调用（Function Calling）"
          badge="Tools"
          badgeColor="bg-violet-100 text-violet-700"
          description="通过 tools 字段定义可调用函数，模型在需要时会返回 function_call 输出项。"
        >
          <CurlSection body={WITH_TOOLS} />
        </SectionCard>

        {/* Image generation */}
        <SectionCard
          id="image-generation"
          title="图片生成"
          badge="image_generation"
          badgeColor="bg-pink-100 text-pink-700"
          description='通过 tools 中的 image_generation 类型触发图片生成，模型会根据用户指令生成图片并以 image_generation_call 类型输出图片 URL。'
        >
          <CurlSection body={IMAGE_GENERATION} />
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">
            <strong>注意：</strong>图片生成功能需要供应商支持图像生成能力（如百炼的 qwen-image-2.0-pro 模型）。
          </div>
        </SectionCard>

        {/* Video generation */}
        <SectionCard
          id="video-generation"
          title="视频生成"
          badge="video_generation"
          badgeColor="bg-cyan-100 text-cyan-700"
          description='通过 tools 中的 video_generation 类型触发视频生成。支持纯文本描述，也支持传入参考图片、视频、音频等多模态素材，通过 file_id 在文本中引用。'
        >
          <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 text-sm text-blue-800">
            <strong>提示：</strong>视频生成耗时通常在数十秒到数分钟，建议设置 <code>background: true</code>，通过 <code>GET /v1/responses/{'{response_id}'}</code> 轮询获取结果。
          </div>

          <div>
            <p className="text-sm font-medium text-slate-700 mb-2">示例一：文本描述生成视频</p>
            <CurlSection body={VIDEO_GENERATION} />
          </div>

          <div>
            <p className="text-sm font-medium text-slate-700 mb-2">示例二：多模态素材引用（图片 / 视频 / 音频参考）</p>
            <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-sm text-slate-700 mb-2">
              通过 <code>file_id</code> 给素材命名，在文本 prompt 中用 <code>{'{{'} file_id {'}}'}</code> 格式引用，让模型知道每段素材的角色。
              支持的 content type：<code>input_image</code>、<code>input_video</code>、<code>input_audio</code>。
            </div>
            <CurlSection body={VIDEO_GENERATION_REF} />
          </div>
        </SectionCard>

        {/* Background */}
        <SectionCard
          id="background"
          title="后台异步请求"
          badge="async"
          badgeColor="bg-amber-100 text-amber-700"
          description='设置 "background": true 后，请求立即返回 202 并附带 response_id，实际推理在后台执行，适合长时任务（如长文生成、视频生成）。'
        >
          <CurlSection body={BACKGROUND_REQUEST} />
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">202 立即响应</span>
            <CodeBlock code={BACKGROUND_RESPONSE} />
          </div>
        </SectionCard>

        {/* Get response */}
        <SectionCard
          id="get-response"
          title="查询异步结果"
          description="使用 response_id 轮询查询后台任务的状态和结果。"
        >
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">请求</span>
            <CodeBlock code={GET_RESPONSE} lang="bash" />
          </div>
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left">
                <tr>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">status</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">说明</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {[
                  { status: 'queued',      desc: '任务已提交，等待执行' },
                  { status: 'in_progress', desc: '任务正在执行中，继续轮询' },
                  { status: 'completed',   desc: '任务完成，响应体包含完整 output' },
                  { status: 'incomplete',  desc: '任务超时或达到输出限制，结果不完整' },
                  { status: 'failed',      desc: '任务执行失败，响应体包含 error 字段' },
                  { status: 'cancelled',   desc: '任务已被取消' },
                ].map((r) => (
                  <tr key={r.status} className="hover:bg-slate-50">
                    <td className="px-4 py-2.5"><code className="text-emerald-600 font-semibold">{r.status}</code></td>
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
            <p className="text-sm text-slate-500 mt-1">兼容 OpenAI Responses API 格式，output 为输出项列表。</p>
          </div>
          <div className="p-6">
            <CodeBlock code={BASIC_RESPONSE} />
          </div>
        </div>
      </div>

      {/* Right TOC */}
      <TableOfContents items={TOC_ITEMS} />
    </div>
  );
}
