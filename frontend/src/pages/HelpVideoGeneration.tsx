import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Copy, Check, ArrowLeft, Video } from 'lucide-react';

const BASE_URL = 'http://localhost:8000';

interface TocItem { id: string; label: string }
const TOC_ITEMS: TocItem[] = [
  { id: 'overview', label: '功能说明' },
  { id: 'text-to-video', label: '文本生成视频' },
  { id: 'multimodal', label: '多模态素材引用' },
  { id: 'seedance-models', label: 'Seedance 模型说明' },
  { id: 'seedance-pricing', label: 'Seedance 收费标准' },
  { id: 'kling-models', label: 'Kling 模型说明' },
  { id: 'gemini-veo', label: 'Gemini Veo 视频生成' },
  { id: 'vertexai-veo', label: 'VertexAI Veo 视频生成' },
  { id: 'veo-limits', label: '模型限制说明' },
  { id: 'veo-pricing', label: 'Veo 收费标准' },
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

const VEO_TEXT_TO_VIDEO = `{
  "model": "veo-3.1-generate-preview",
  "background": true,
  "input": [
    {
      "role": "user",
      "type": "message",
      "content": [
        {
          "type": "input_text",
          "text": "A cinematic, haunting video. A ghostly woman with long white hair and a flowing dress swings gently on a rope swing beneath a massive, gnarled tree in a foggy, moonlit clearing."
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "video_generation",
      "aspect_ratio": "16:9",
      "seconds": 8
    }
  ]
}`;

const VEO_IMAGE_TO_VIDEO = `{
  "model": "veo-3.1-generate-preview",
  "background": true,
  "input": [
    {
      "role": "user",
      "type": "message",
      "content": [
        {
          "type": "input_text",
          "text": "The woman slowly turns and walks into the forest."
        },
        {
          "type": "input_image",
          "image_url": "data:image/png;base64,<first_frame_base64>"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "video_generation",
      "aspect_ratio": "16:9",
      "seconds": 8
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

const VEO_RESPONSE = `{
  "id": "vid_abc123...",
  "object": "response",
  "status": "completed",
  "model": "veo-3.1-generate-preview",
  "output": [
    {
      "type": "video_generation_call",
      "id": "vid_abc123...",
      "status": "completed",
      "result": "https://generativelanguage.googleapis.com/..."
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
          <div className="p-6 space-y-3">
            <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 text-sm text-blue-800">
              <strong>提示：</strong>视频生成耗时通常在数十秒到数分钟，必须设置 <code>background: true</code>，通过 <code>GET /v1/responses/{'{response_id}'}</code> 轮询获取结果。
            </div>
            <div className="overflow-x-auto rounded-xl border border-slate-200">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left">
                  <tr>
                    <th className="px-4 py-2.5 font-semibold text-slate-600">供应商</th>
                    <th className="px-4 py-2.5 font-semibold text-slate-600">支持模型</th>
                    <th className="px-4 py-2.5 font-semibold text-slate-600">特性</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  <tr className="hover:bg-slate-50">
                    <td className="px-4 py-2.5 font-medium text-slate-700">火山引擎 (Volcengine)</td>
                    <td className="px-4 py-2.5 text-slate-600">doubao-seedance-2.0, doubao-seedance-1.5-pro, ...</td>
                    <td className="px-4 py-2.5 text-slate-500">文本/图片/视频/音频多模态，file_id 引用</td>
                  </tr>
                  <tr className="hover:bg-slate-50">
                    <td className="px-4 py-2.5 font-medium text-slate-700">腾讯云点播 (TencentVOD)</td>
                    <td className="px-4 py-2.5 text-slate-600">kling-v3-omni, kling-v3, kling-v2.1-pro, ...</td>
                    <td className="px-4 py-2.5 text-slate-500">文生视频，图生视频，支持 720p~4K，5s/15s</td>
                  </tr>
                  <tr className="hover:bg-slate-50">
                    <td className="px-4 py-2.5 font-medium text-slate-700">Google Gemini (Veo)</td>
                    <td className="px-4 py-2.5 text-slate-600">veo-3.1-generate-preview, veo-3.1-fast-generate-preview, veo-3.1-lite-generate-preview</td>
                    <td className="px-4 py-2.5 text-slate-500">文生视频，图生视频（首帧/尾帧插值）</td>
                  </tr>
                  <tr className="hover:bg-slate-50">
                    <td className="px-4 py-2.5 font-medium text-slate-700">Google VertexAI (Veo)</td>
                    <td className="px-4 py-2.5 text-slate-600">veo-3.1-generate-001, veo-3.1-fast-generate-001, veo-3.1-lite-generate-001</td>
                    <td className="px-4 py-2.5 text-slate-500">文生视频，图生视频，支持 720p/1080p/4K 输出</td>
                  </tr>
                </tbody>
              </table>
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

        {/* Seedance Models */}
        <div id="seedance-models" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <div className="flex items-center gap-3 mb-1">
              <h3 className="text-lg font-semibold text-slate-800">Seedance 模型说明</h3>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-orange-100 text-orange-700">火山引擎</span>
            </div>
            <p className="text-sm text-slate-500">豆包 Seedance 系列视频生成模型的能力对比与参数支持。</p>
          </div>
          <div className="p-6 space-y-6">
            <div className="overflow-x-auto rounded-xl border border-slate-200">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left">
                  <tr>
                    <th className="px-4 py-2.5 font-semibold text-slate-600">模型</th>
                    <th className="px-4 py-2.5 font-semibold text-slate-600">支持分辨率</th>
                    <th className="px-4 py-2.5 font-semibold text-slate-600">音频生成</th>
                    <th className="px-4 py-2.5 font-semibold text-slate-600">支持输入</th>
                    <th className="px-4 py-2.5 font-semibold text-slate-600">默认参数</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {[
                    { model: 'doubao-seedance-1.0-pro',      res: '480p, 720p, 1080p', audio: '不支持', input: '图片', defaults: '16:9 / 720p' },
                    { model: 'doubao-seedance-1.0-pro-fast', res: '480p, 720p, 1080p', audio: '不支持', input: '图片', defaults: '16:9 / 720p' },
                    { model: 'doubao-seedance-1.5-pro',      res: '480p, 720p, 1080p', audio: '✅ 支持（默认开启）', input: '图片、视频、音频', defaults: '16:9 / 720p' },
                    { model: 'doubao-seedance-2.0',          res: '480p, 720p, 1080p', audio: '✅ 支持（默认开启）', input: '图片、视频、音频', defaults: '16:9 / 720p' },
                    { model: 'doubao-seedance-2.0-fast',     res: '480p, 720p',        audio: '✅ 支持（默认开启）', input: '图片、视频、音频', defaults: '16:9 / 720p' },
                  ].map(r => (
                    <tr key={r.model} className="hover:bg-slate-50">
                      <td className="px-4 py-2.5"><code className="text-orange-600 font-semibold">{r.model}</code></td>
                      <td className="px-4 py-2.5 text-slate-600">{r.res}</td>
                      <td className="px-4 py-2.5 text-slate-600">{r.audio}</td>
                      <td className="px-4 py-2.5 text-slate-600">{r.input}</td>
                      <td className="px-4 py-2.5 text-slate-500">{r.defaults}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="bg-amber-50 border border-amber-100 rounded-lg p-3 text-sm text-amber-800">
              <strong>说明：</strong>
              <ul className="list-disc list-inside mt-1 space-y-1">
                <li>未指定 <code>aspect_ratio</code>、<code>resolution</code>、<code>size</code> 时，默认使用 <code>16:9</code> 宽高比和 <code>720p</code> 分辨率</li>
                <li><code>generate_audio</code> 参数仅 1.5-pro 及以后版本支持；1.0 系列不支持此参数，请勿传入</li>
                <li>1.5-pro 及以后版本默认生成有声视频；若需无声视频，设置 <code>generate_audio: false</code></li>
                <li>2.0 系列支持通过 <code>file_id</code> 引用多模态素材（图片、视频、音频）</li>
              </ul>
            </div>

            {/* Size mapping for 1.0 series */}
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
                Seedance 1.0 系列尺寸映射 <span className="text-slate-400 font-normal normal-case">（size ↔ aspect_ratio + resolution）</span>
              </p>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="px-4 py-2.5 font-semibold text-slate-600">宽高比</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">480p</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">720p</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">1080p</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {[
                      { ratio: '16:9', s480: '864x480',  s720: '1248x704',  s1080: '1920x1088' },
                      { ratio: '4:3',  s480: '736x544',  s720: '1120x832',  s1080: '1664x1248' },
                      { ratio: '1:1',  s480: '640x640',  s720: '960x960',   s1080: '1440x1440' },
                      { ratio: '3:4',  s480: '544x736',  s720: '832x1120',  s1080: '1248x1664' },
                      { ratio: '9:16', s480: '480x864',  s720: '704x1248',  s1080: '1088x1920' },
                      { ratio: '21:9', s480: '960x416',  s720: '1504x640',  s1080: '2176x928' },
                    ].map(r => (
                      <tr key={r.ratio} className="hover:bg-slate-50">
                        <td className="px-4 py-2.5 font-medium text-slate-700">{r.ratio}</td>
                        <td className="px-4 py-2.5 text-slate-600 text-center font-mono text-xs">{r.s480}</td>
                        <td className="px-4 py-2.5 text-slate-600 text-center font-mono text-xs">{r.s720}</td>
                        <td className="px-4 py-2.5 text-slate-600 text-center font-mono text-xs">{r.s1080}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Size mapping for 1.5/2.0 series */}
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
                Seedance 1.5 / 2.0 系列尺寸映射 <span className="text-slate-400 font-normal normal-case">（size ↔ aspect_ratio + resolution）</span>
              </p>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="px-4 py-2.5 font-semibold text-slate-600">宽高比</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">480p</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">720p</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">1080p</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {[
                      { ratio: '16:9', s480: '864x496',  s720: '1280x720',  s1080: '1920x1080' },
                      { ratio: '4:3',  s480: '752x560',  s720: '1112x834',  s1080: '1664x1248' },
                      { ratio: '1:1',  s480: '640x640',  s720: '960x960',   s1080: '1440x1440' },
                      { ratio: '3:4',  s480: '560x752',  s720: '834x1112',  s1080: '1248x1664' },
                      { ratio: '9:16', s480: '496x864',  s720: '720x1280',  s1080: '1080x1920' },
                      { ratio: '21:9', s480: '992x432',  s720: '1470x630',  s1080: '2206x946' },
                    ].map(r => (
                      <tr key={r.ratio} className="hover:bg-slate-50">
                        <td className="px-4 py-2.5 font-medium text-slate-700">{r.ratio}</td>
                        <td className="px-4 py-2.5 text-slate-600 text-center font-mono text-xs">{r.s480}</td>
                        <td className="px-4 py-2.5 text-slate-600 text-center font-mono text-xs">{r.s720}</td>
                        <td className="px-4 py-2.5 text-slate-600 text-center font-mono text-xs">{r.s1080}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 text-sm text-blue-800">
              <strong>使用方式：</strong>可通过 <code>size</code> 直接传入像素尺寸（如 <code>"496x864"</code>），系统自动解析为对应的 <code>aspect_ratio</code> 和 <code>resolution</code>；也可直接指定 <code>aspect_ratio</code> 和 <code>resolution</code> 参数。
            </div>
          </div>
        </div>

        {/* Seedance Pricing */}
        <div id="seedance-pricing" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <div className="flex items-center gap-3 mb-1">
              <h3 className="text-lg font-semibold text-slate-800">Seedance 收费标准</h3>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700">CNY / M output tokens</span>
            </div>
            <p className="text-sm text-slate-500">Seedance 系列按 output tokens 计费，价格因模型、分辨率、是否含音频/视频参考而异。</p>
          </div>
          <div className="p-6 space-y-6">
            {/* 1.0 Pro */}
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
                <code className="text-orange-600 normal-case text-sm font-bold">doubao-seedance-1.0-pro</code>
              </p>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">480p</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">720p</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">1080p</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="hover:bg-slate-50">
                      <td className="px-4 py-2.5 text-slate-600 text-center">¥15/M</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">¥15/M</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">¥15/M</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            {/* 1.0 Pro Fast */}
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
                <code className="text-orange-600 normal-case text-sm font-bold">doubao-seedance-1.0-pro-fast</code>
              </p>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">480p</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">720p</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">1080p</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="hover:bg-slate-50">
                      <td className="px-4 py-2.5 text-slate-600 text-center">¥4.2/M</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">¥4.2/M</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">¥4.2/M</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            {/* 1.5 Pro */}
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
                <code className="text-orange-600 normal-case text-sm font-bold">doubao-seedance-1.5-pro</code>
              </p>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="px-4 py-2.5 font-semibold text-slate-600">输出类型</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">480p</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">720p</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">1080p</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    <tr className="hover:bg-slate-50">
                      <td className="px-4 py-2.5 font-medium text-slate-700">有声视频</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">¥16/M</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">¥16/M</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">¥16/M</td>
                    </tr>
                    <tr className="hover:bg-slate-50">
                      <td className="px-4 py-2.5 font-medium text-slate-700">无声视频</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">¥8/M</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">¥8/M</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">¥8/M</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            {/* 2.0 */}
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
                <code className="text-orange-600 normal-case text-sm font-bold">doubao-seedance-2.0</code>
              </p>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="px-4 py-2.5 font-semibold text-slate-600">输入类型</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">480p</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">720p</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">1080p</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    <tr className="hover:bg-slate-50">
                      <td className="px-4 py-2.5 font-medium text-slate-700">不含视频输入</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">¥28/M</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">¥28/M</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">¥31/M</td>
                    </tr>
                    <tr className="hover:bg-slate-50">
                      <td className="px-4 py-2.5 font-medium text-slate-700">含视频输入</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">¥46/M</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">¥46/M</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">¥51/M</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            {/* 2.0 Fast */}
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
                <code className="text-orange-600 normal-case text-sm font-bold">doubao-seedance-2.0-fast</code>
              </p>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="px-4 py-2.5 font-semibold text-slate-600">输入类型</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">480p</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">720p</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    <tr className="hover:bg-slate-50">
                      <td className="px-4 py-2.5 font-medium text-slate-700">不含视频输入</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">¥22/M</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">¥22/M</td>
                    </tr>
                    <tr className="hover:bg-slate-50">
                      <td className="px-4 py-2.5 font-medium text-slate-700">含视频输入</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">¥37/M</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">¥37/M</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>

        {/* Kling Models (TencentVOD) */}
        <div id="kling-models" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <div className="flex items-center gap-3 mb-1">
              <h3 className="text-lg font-semibold text-slate-800">Kling 模型说明</h3>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-700">腾讯云点播</span>
            </div>
            <p className="text-sm text-slate-500">可灵 (Kling) 系列视频生成模型通过腾讯云点播 API 调用，支持文生视频和图生视频。</p>
          </div>
          <div className="p-6 space-y-6">
            <div className="overflow-x-auto rounded-xl border border-slate-200">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left">
                  <tr>
                    <th className="px-4 py-2.5 font-semibold text-slate-600">模型</th>
                    <th className="px-4 py-2.5 font-semibold text-slate-600">说明</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {[
                    { model: 'kling-v3-omni',       desc: '可灵 3.0 Omni，最新旗舰模型，支持文生视频和图生视频' },
                  ].map(r => (
                    <tr key={r.model} className="hover:bg-slate-50">
                      <td className="px-4 py-2.5"><code className="text-purple-600 font-semibold">{r.model}</code></td>
                      <td className="px-4 py-2.5 text-slate-600">{r.desc}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="overflow-x-auto rounded-xl border border-slate-200">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left">
                  <tr>
                    <th className="px-4 py-2.5 font-semibold text-slate-600">参数</th>
                    <th className="px-4 py-2.5 font-semibold text-slate-600">支持值</th>
                    <th className="px-4 py-2.5 font-semibold text-slate-600">默认值</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {[
                    { param: 'resolution',   values: '720p, 1080p, 2K, 4K', defaults: '—' },
                    { param: 'aspect_ratio',  values: '16:9, 9:16, 1:1',     defaults: '16:9' },
                    { param: 'seconds',       values: '5, 15',               defaults: '5' },
                  ].map(r => (
                    <tr key={r.param} className="hover:bg-slate-50">
                      <td className="px-4 py-2.5"><code className="text-purple-600 font-semibold">{r.param}</code></td>
                      <td className="px-4 py-2.5 text-slate-600">{r.values}</td>
                      <td className="px-4 py-2.5 text-slate-500">{r.defaults}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="bg-purple-50 border border-purple-100 rounded-lg p-3 text-sm text-purple-800">
              <strong>说明：</strong>
              <ul className="list-disc list-inside mt-1 space-y-1">
                <li>视频时长支持 <code>5</code> 秒和 <code>15</code> 秒，未指定时默认生成 5 秒视频</li>
                <li>宽高比支持 <code>16:9</code>（横屏）、<code>9:16</code>（竖屏）、<code>1:1</code>（正方形），默认 <code>16:9</code></li>
                <li>分辨率支持 <code>720p</code>、<code>1080p</code>、<code>2K</code>、<code>4K</code></li>
                <li>支持通过 <code>input_image</code> 传入参考图片实现图生视频</li>
                <li>可通过 <code>{"{{file_id}}"}</code> 在 prompt 中引用参考图片</li>
              </ul>
            </div>
          </div>
        </div>

        {/* Gemini Veo */}
        <div id="gemini-veo" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <div className="flex items-center gap-3 mb-1">
              <h3 className="text-lg font-semibold text-slate-800">Gemini Veo 视频生成</h3>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700">Google</span>
            </div>
            <p className="text-sm text-slate-500">
              使用 Google Gemini Veo 模型生成高质量视频。支持纯文本生成和图像引导生成（首帧/尾帧插值）。Veo 仅支持生成含声音的视频。
            </p>
          </div>
          <div className="p-6 space-y-6">
            {/* Model list */}
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">支持的模型</p>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="px-4 py-2.5 font-semibold text-slate-600">模型</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600">说明</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {[
                      { model: 'veo-3.1-generate-preview', desc: '高质量视频生成，最佳画面效果' },
                      { model: 'veo-3.1-fast-generate-preview', desc: '快速视频生成，速度与质量平衡' },
                      { model: 'veo-3.1-lite-generate-preview', desc: '轻量级视频生成，最快速度' },
                    ].map(r => (
                      <tr key={r.model} className="hover:bg-slate-50">
                        <td className="px-4 py-2.5"><code className="text-blue-600 font-semibold">{r.model}</code></td>
                        <td className="px-4 py-2.5 text-slate-600">{r.desc}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Text to video */}
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">文本生成视频</p>
              <CurlSection body={VEO_TEXT_TO_VIDEO} />
            </div>

            {/* Image to video */}
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">图像引导生成（首帧插值）</p>
              <div className="bg-amber-50 border border-amber-100 rounded-lg p-3 text-sm text-amber-800 mb-3">
                <strong>图生视频：</strong>在 content 中传入 base64 编码的图片作为首帧（第一张图片），Veo 会以该图像为起始帧生成视频。
                传入两张图片时，第一张作为首帧，第二张作为尾帧（插值生成）。
              </div>
              <CurlSection body={VEO_IMAGE_TO_VIDEO} />
            </div>

            {/* Response */}
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Veo 响应格式</p>
              <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-sm text-slate-700 mb-3">
                result 字段为 Google 生成的视频 URI，需携带 API Key 才能下载。
              </div>
              <CodeBlock code={VEO_RESPONSE} />
            </div>
          </div>
        </div>

        {/* VertexAI Veo */}
        <div id="vertexai-veo" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <div className="flex items-center gap-3 mb-1">
              <h3 className="text-lg font-semibold text-slate-800">VertexAI Veo 视频生成</h3>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700">Google Cloud</span>
            </div>
            <p className="text-sm text-slate-500">
              使用 Google Cloud VertexAI 平台上的 Veo 模型生成视频。与 Gemini Veo 使用相同的 API 接口，但通过 VertexAI 服务调用，模型名称以 <code>-generate-001</code> 结尾。
            </p>
          </div>
          <div className="p-6 space-y-6">
            {/* Model list */}
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">支持的模型</p>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="px-4 py-2.5 font-semibold text-slate-600">模型</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600">说明</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {[
                      { model: 'veo-3.1-generate-001', desc: '高质量视频生成，支持 4K 输出，图生视频仅支持 8 秒' },
                      { model: 'veo-3.1-fast-generate-001', desc: '快速视频生成，速度与质量平衡，支持 4K 输出' },
                      { model: 'veo-3.1-lite-generate-001', desc: '轻量级视频生成，支持 720p/1080p 输出' },
                    ].map(r => (
                      <tr key={r.model} className="hover:bg-slate-50">
                        <td className="px-4 py-2.5"><code className="text-green-600 font-semibold">{r.model}</code></td>
                        <td className="px-4 py-2.5 text-slate-600">{r.desc}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="bg-green-50 border border-green-100 rounded-lg p-3 text-sm text-green-800">
              <strong>使用说明：</strong>VertexAI Veo 与 Gemini Veo 使用相同的请求格式，仅需将 <code>model</code> 字段替换为对应的 <code>*-generate-001</code> 模型名称，并配置 VertexAI 供应商即可。
            </div>
          </div>
        </div>

        {/* Veo model limits */}
        <div id="veo-limits" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <div className="flex items-center gap-3 mb-1">
              <h3 className="text-lg font-semibold text-slate-800">模型限制说明</h3>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-orange-100 text-orange-700">VertexAI Veo</span>
            </div>
            <p className="text-sm text-slate-500">各 VertexAI Veo 模型的能力边界与参数约束。</p>
          </div>
          <div className="p-6 space-y-6">
            {/* veo-3.1-generate-001 */}
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
                <code className="text-green-600 normal-case text-sm font-bold">veo-3.1-generate-001</code>
              </p>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 w-56">限制项</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600">说明</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {[
                      { label: '视频时长',           value: '4、6 或 8 秒；图生视频仅支持 8 秒' },
                      { label: '每次最大生成数量',   value: '4 个' },
                      { label: '图生视频最大图片大小', value: '20 MB' },
                      { label: '支持宽高比',         value: '9:16、16:9' },
                      { label: '支持输入分辨率',     value: '720p、1080p、4K（预览）' },
                      { label: '支持输出分辨率',     value: '720p、1080p、4K（预览）' },
                      { label: '支持帧率',           value: '24 FPS' },
                      { label: '输出格式',           value: 'video/mp4' },
                    ].map(r => (
                      <tr key={r.label} className="hover:bg-slate-50">
                        <td className="px-4 py-2.5 font-medium text-slate-700">{r.label}</td>
                        <td className="px-4 py-2.5 text-slate-600">{r.value}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* veo-3.1-fast-generate-001 */}
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
                <code className="text-green-600 normal-case text-sm font-bold">veo-3.1-fast-generate-001</code>
              </p>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 w-56">限制项</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600">说明</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {[
                      { label: '视频时长',           value: '4、6 或 8 秒' },
                      { label: '每次最大生成数量',   value: '4 个' },
                      { label: '图生视频最大图片大小', value: '20 MB' },
                      { label: '支持宽高比',         value: '9:16、16:9' },
                      { label: '支持输入分辨率',     value: '720p、1080p、4K（预览）' },
                      { label: '支持输出分辨率',     value: '720p、1080p、4K（预览）' },
                      { label: '支持帧率',           value: '24 FPS' },
                      { label: '输出格式',           value: 'video/mp4' },
                    ].map(r => (
                      <tr key={r.label} className="hover:bg-slate-50">
                        <td className="px-4 py-2.5 font-medium text-slate-700">{r.label}</td>
                        <td className="px-4 py-2.5 text-slate-600">{r.value}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* veo-3.1-lite-generate-001 */}
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
                <code className="text-green-600 normal-case text-sm font-bold">veo-3.1-lite-generate-001</code>
              </p>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 w-56">限制项</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600">说明</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {[
                      { label: '视频时长',           value: '4、6 或 8 秒' },
                      { label: '每次最大生成数量',   value: '4 个' },
                      { label: '图生视频最大图片大小', value: '20 MB' },
                      { label: '支持宽高比',         value: '9:16、16:9' },
                      { label: '支持输入分辨率',     value: '720p、1080p' },
                      { label: '支持输出分辨率',     value: '720p、1080p' },
                      { label: '支持帧率',           value: '24 FPS' },
                      { label: '输出格式',           value: 'video/mp4' },
                    ].map(r => (
                      <tr key={r.label} className="hover:bg-slate-50">
                        <td className="px-4 py-2.5 font-medium text-slate-700">{r.label}</td>
                        <td className="px-4 py-2.5 text-slate-600">{r.value}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="bg-amber-50 border border-amber-100 rounded-lg p-3 text-sm text-amber-800">
              <strong>注意：</strong><code>veo-3.1-lite-generate-001</code> 不支持 4K 分辨率，最高仅支持 1080p 输入/输出。<code>veo-3.1-generate-001</code> 的图生视频模式仅支持 8 秒时长。
            </div>
          </div>
        </div>

        {/* Veo Pricing */}
        <div id="veo-pricing" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <div className="flex items-center gap-3 mb-1">
              <h3 className="text-lg font-semibold text-slate-800">Veo 收费标准</h3>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-100 text-emerald-700">USD / 秒</span>
            </div>
            <p className="text-sm text-slate-500">Veo 3.1 系列按视频时长（秒）计费，价格因模型、分辨率和是否包含音频而异。</p>
          </div>
          <div className="p-6 space-y-6">
            {/* veo-3.1-generate-001 */}
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
                <code className="text-green-600 normal-case text-sm font-bold">veo-3.1-generate-001</code>
              </p>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="px-4 py-2.5 font-semibold text-slate-600">输出类型</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">720p</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">1080p</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">4K</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    <tr className="hover:bg-slate-50">
                      <td className="px-4 py-2.5 font-medium text-slate-700">视频 + 音频</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">$0.40/s</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">$0.40/s</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">$0.60/s</td>
                    </tr>
                    <tr className="hover:bg-slate-50">
                      <td className="px-4 py-2.5 font-medium text-slate-700">仅视频</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">$0.20/s</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">$0.20/s</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">$0.40/s</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            {/* veo-3.1-fast-generate-001 */}
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
                <code className="text-green-600 normal-case text-sm font-bold">veo-3.1-fast-generate-001</code>
              </p>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="px-4 py-2.5 font-semibold text-slate-600">输出类型</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">720p</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">1080p</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">4K</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    <tr className="hover:bg-slate-50">
                      <td className="px-4 py-2.5 font-medium text-slate-700">视频 + 音频</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">$0.10/s</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">$0.12/s</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">$0.30/s</td>
                    </tr>
                    <tr className="hover:bg-slate-50">
                      <td className="px-4 py-2.5 font-medium text-slate-700">仅视频</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">$0.08/s</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">$0.10/s</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">$0.25/s</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            {/* veo-3.1-lite-generate-001 */}
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
                <code className="text-green-600 normal-case text-sm font-bold">veo-3.1-lite-generate-001</code>
              </p>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="px-4 py-2.5 font-semibold text-slate-600">输出类型</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">720p</th>
                      <th className="px-4 py-2.5 font-semibold text-slate-600 text-center">1080p</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    <tr className="hover:bg-slate-50">
                      <td className="px-4 py-2.5 font-medium text-slate-700">视频 + 音频</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">$0.05/s</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">$0.08/s</td>
                    </tr>
                    <tr className="hover:bg-slate-50">
                      <td className="px-4 py-2.5 font-medium text-slate-700">仅视频</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">$0.03/s</td>
                      <td className="px-4 py-2.5 text-slate-600 text-center">$0.05/s</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 text-sm text-blue-800">
              <strong>说明：</strong>以上价格适用于 VertexAI (<code>*-generate-001</code>) 和 Gemini (<code>*-generate-preview</code>) 两种接入方式，定价相同。<code>veo-3.1-lite-generate-001</code> 不支持 4K 分辨率。
            </div>
          </div>
        </div>

        {/* Params */}
        <SectionCard
          id="params"
          title="请求参数（video_generation tool）"
          description="video_generation tool 支持以下通用参数。"
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
                  { name: 'size',              required: false, type: 'string',  desc: '视频尺寸（WxH），如 "496x864"（Seedance）' },
                  { name: 'aspect_ratio',      required: false, type: 'string',  desc: '宽高比，如 "16:9"、"9:16"；别名：ratio。默认 "16:9"' },
                  { name: 'seconds',           required: false, type: 'number',  desc: '视频时长（秒）；别名：duration' },
                  { name: 'resolution',        required: false, type: 'string',  desc: '分辨率等级，如 "480p"、"720p"、"1080p"。默认 "720p"' },
                  { name: 'generate_audio',    required: false, type: 'boolean', desc: '是否生成音频，默认 true（仅 Seedance 1.5+ 支持）' },
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
            <p className="text-sm text-slate-500 mt-1">output 包含 video_generation_call 类型的输出项，result 为视频 URL 或 URI。</p>
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
