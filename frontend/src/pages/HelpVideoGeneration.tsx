import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Copy, Check, ArrowLeft, Video } from 'lucide-react';

const BASE_URL = 'http://localhost:8000';

interface TocItem { id: string; label: string }
const TOC_ITEMS: TocItem[] = [
  { id: 'overview', label: '功能说明' },
  { id: 'text-to-video', label: '文本生成视频' },
  { id: 'multimodal', label: '多模态素材引用' },
  { id: 'params', label: '请求参数' },
  { id: 'response-format', label: '响应格式' },
];

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
      "size": "496x864"
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

const VIDEO_GENERATION_RESPONSE = `{
  "id": "vid_abc123...",
  "object": "response",
  "status": "completed",
  "model": "doubao-seedance-2.0",
  "output": [
    {
      "type": "video_generation_call",
      "id": "vid_abc123...",
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
                  ? 'bg-cyan-50 text-cyan-600 font-medium border-l-2 border-cyan-500'
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

export default function HelpVideoGeneration() {
  const navigate = useNavigate();

  return (
    <div className="flex gap-8 max-w-6xl mx-auto">
      <div className="flex-1 min-w-0 space-y-8">
        {/* Back + header */}
        <div>
          <button
            onClick={() => navigate('/help')}
            className="flex items-center gap-1.5 text-sm text-slate-500 hover:text-cyan-600 mb-4 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            返回帮助中心
          </button>
          <div className="flex items-center gap-4">
            <div className="p-3 bg-gradient-to-br from-cyan-500 to-teal-600 rounded-2xl shadow-lg shadow-cyan-500/25">
              <Video className="w-7 h-7 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900">视频生成</h1>
              <p className="text-slate-500 text-sm mt-0.5">通过 Responses API 的 video_generation 工具生成视频</p>
            </div>
          </div>
        </div>

        {/* Endpoint info */}
        <div className="bg-cyan-50 border border-cyan-100 rounded-xl p-4 flex flex-wrap gap-4 items-center">
          <div>
            <span className="text-xs font-semibold text-cyan-500 uppercase tracking-wide">Endpoint</span>
            <p className="font-mono text-sm text-cyan-900 mt-0.5">{BASE_URL}/v1/responses</p>
          </div>
          <div className="h-8 w-px bg-cyan-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-cyan-500 uppercase tracking-wide">Tool Type</span>
            <p className="font-mono text-sm text-cyan-900 mt-0.5">video_generation</p>
          </div>
          <div className="h-8 w-px bg-cyan-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-cyan-500 uppercase tracking-wide">Auth</span>
            <p className="font-mono text-sm text-cyan-900 mt-0.5">Bearer &lt;API_KEY&gt;</p>
          </div>
        </div>

        {/* Overview */}
        <div id="overview" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <h3 className="text-lg font-semibold text-slate-800 mb-1">功能说明</h3>
            <p className="text-sm text-slate-500">通过在 tools 中指定 video_generation 类型触发视频生成。支持纯文本描述，也支持传入参考图片、视频、音频等多模态素材。</p>
          </div>
          <div className="p-6">
            <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 text-sm text-blue-800">
              <strong>提示：</strong>视频生成耗时通常在数十秒到数分钟，必须设置 <code>background: true</code>，通过 <code>GET /v1/responses/{'{response_id}'}</code> 轮询获取结果。
            </div>
          </div>
        </div>

        {/* Text to video */}
        <SectionCard
          id="text-to-video"
          title="文本描述生成视频"
          badge="video_generation"
          badgeColor="bg-cyan-100 text-cyan-700"
          description="通过文本描述让模型生成视频，需设置 background: true 异步执行。"
        >
          <CurlSection body={VIDEO_GENERATION} />
        </SectionCard>

        {/* Multimodal */}
        <SectionCard
          id="multimodal"
          title="多模态素材引用"
          badge="file_id"
          badgeColor="bg-violet-100 text-violet-700"
          description="通过 file_id 给素材命名，在文本 prompt 中用 {{file_id}} 格式引用，支持图片、视频、音频参考。"
        >
          <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-sm text-slate-700">
            通过 <code>file_id</code> 给素材命名，在文本 prompt 中用 <code>{'{{'} file_id {'}}'}</code> 格式引用，让模型知道每段素材的角色。
            支持的 content type：<code>input_image</code>、<code>input_video</code>、<code>input_audio</code>。
          </div>
          <CurlSection body={VIDEO_GENERATION_REF} />
        </SectionCard>

        {/* Params */}
        <SectionCard
          id="params"
          title="请求参数（video_generation tool）"
          description="video_generation tool 支持以下参数。"
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
                  { name: 'type',              required: true,  type: 'string',  desc: '固定为 "video_generation"' },
                  { name: 'size / video_size', required: false, type: 'string',  desc: '视频尺寸（WxH），如 "496x864"' },
                  { name: 'aspect_ratio',      required: false, type: 'string',  desc: '宽高比，如 "16:9"、"9:16"；别名：ratio' },
                  { name: 'seconds',           required: false, type: 'number',  desc: '视频时长（秒）；别名：duration' },
                  { name: 'resolution',        required: false, type: 'string',  desc: '分辨率等级，如 "720p"、"1080p"' },
                  { name: 'n / number',        required: false, type: 'number',  desc: '生成视频数量' },
                  { name: 'generate_audio',    required: false, type: 'boolean', desc: '是否生成音频，默认 true；别名：audio_generation' },
                  { name: 'negative_prompt',   required: false, type: 'string',  desc: '负面提示词' },
                  { name: 'reference_images',  required: false, type: 'array',   desc: '参考图片 URL 列表（图生视频）' },
                  { name: 'reference_videos',  required: false, type: 'array',   desc: '参考视频 URL 列表（视频参考）' },
                  { name: 'last_frame_url',    required: false, type: 'string',  desc: '尾帧图片 URL' },
                  { name: 'seed',              required: false, type: 'number',  desc: '随机种子' },
                  { name: 'watermark',         required: false, type: 'boolean', desc: '是否添加水印' },
                ].map((r) => (
                  <tr key={r.name} className="hover:bg-slate-50">
                    <td className="px-4 py-2.5"><code className="text-cyan-600 font-semibold">{r.name}</code></td>
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
            <p className="text-sm text-slate-500 mt-1">output 包含 video_generation_call 类型的输出项，result 为视频 URL。</p>
          </div>
          <div className="p-6">
            <CodeBlock code={VIDEO_GENERATION_RESPONSE} />
          </div>
        </div>
      </div>

      <TableOfContents items={TOC_ITEMS} />
    </div>
  );
}
