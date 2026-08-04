import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Clapperboard } from 'lucide-react';
import { useBaseUrl, CodeBlock, CurlSection, TableOfContents } from '../components/help/HelpShared';
import type { TocItem } from '../components/help/HelpShared';

// ---------- TOC ----------

const TOC_ITEMS: TocItem[] = [
  { id: 'overview', label: '功能说明' },
  { id: 'input-limits', label: '输入限制' },
  { id: 'ref-object', label: '示例1：参考对象' },
  { id: 't2v', label: '示例2：文生视频' },
  { id: 'i2v', label: '示例3：图生视频' },
  { id: 'params', label: '参数说明' },
  { id: 'async-task', label: '异步任务与结果查询' },
];

// ---------- code samples ----------

const REF_OBJECT_REQUEST = `{
  "model": "MiniMax-H3",
  "input": [
    {
      "type": "message",
      "content": [
        {
          "type": "input_text",
          "text": "全程使用{{video_1}}的第一视角构图，全程使用{{audio_1}}作为背景音乐。第一人称视角果茶宣传广告，seedance牌「苹苹安安」苹果果茶限定款；首帧为{{apple_1}}，你的手摘下一颗带晨露的阿克苏红苹果，轻脆的苹果碰撞声；2-4 秒：快速切镜，你的手将苹果块投入雪克杯，加入冰块与茶底，用力摇晃，冰块碰撞声与摇晃声卡点轻快鼓点，背景音：「鲜切现摇」；4-6 秒：第一人称成品特写，分层果茶倒入透明杯，你的手轻挤奶盖在顶部铺展，在杯身贴上粉红包标，镜头拉近看奶盖与果茶的分层纹理；6-8 秒：第一人称手持举杯，你将{{tea_1}}中的果茶举到镜头前（模拟递到观众面前的视角），杯身标签清晰可见，背景音「来一口鲜爽」，尾帧定格为{{tea_1}}。背景声音统一为女生音色。"
        },
        {
          "type": "input_image",
          "image_url": "https://ark-project.tos-cn-beijing.volces.com/doc_image/r2v_tea_pic1.jpg",
          "file_id": "apple_1",
          "role": "reference_image"
        },
        {
          "type": "input_image",
          "image_url": "https://ark-project.tos-cn-beijing.volces.com/doc_image/r2v_tea_pic2.jpg",
          "file_id": "tea_1",
          "role": "reference_image"
        },
        {
          "type": "input_video",
          "video_url": "https://ark-project.tos-cn-beijing.volces.com/doc_video/r2v_tea_video1.mp4",
          "file_id": "video_1",
          "role": "reference_video"
        },
        {
          "type": "input_audio",
          "audio_url": "https://ark-project.tos-cn-beijing.volces.com/doc_audio/r2v_tea_audio1.mp3",
          "file_id": "audio_1",
          "role": "reference_audio"
        }
      ],
      "role": "user"
    }
  ],
  "tools": [
    {
      "type": "video_generation",
      "aspect_ratio": "16:9",
      "resolution": "2K"
    }
  ],
  "background": true
}`;

const T2V_REQUEST = `{
  "model": "MiniMax-H3",
  "background": true,
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        {
          "type": "input_text",
          "text": "夕阳下的海边，海浪拍打礁石，一只海鸥掠过天空，镜头缓慢拉远，电影质感。"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "video_generation",
      "aspect_ratio": "16:9",
      "resolution": "2K"
    }
  ]
}`;

const I2V_REQUEST = `{
  "model": "MiniMax-H3",
  "background": true,
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        {
          "type": "input_text",
          "text": "镜头缓慢拉近，画面中的女子转身微笑"
        },
        {
          "type": "input_image",
          "image_url": "https://example.com/image.jpg",
          "file_id": "ref_image",
          "role": "reference_image"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "video_generation",
      "aspect_ratio": "16:9",
      "resolution": "2K"
    }
  ]
}`;

const BACKGROUND_RESPONSE = `{
  "id": "resp_abc123def456...",
  "object": "response",
  "status": "in_progress",
  "model": "MiniMax-H3",
  "background": true
}`;

const COMPLETED_RESPONSE = `{
  "id": "resp_abc123def456...",
  "object": "response",
  "status": "completed",
  "model": "MiniMax-H3",
  "output": [
    {
      "type": "video_generation_call",
      "id": "vid_xxx...",
      "status": "completed",
      "result": "https://.../aigcVideoGenFile.mp4"
    }
  ]
}`;

// ---------- Page ----------

export default function HelpMiniMaxH3() {
  const navigate = useNavigate();
  const baseUrl = useBaseUrl();

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
            <div className="p-3 bg-gradient-to-br from-slate-700 to-slate-900 rounded-2xl shadow-lg shadow-slate-700/25">
              <Clapperboard className="w-7 h-7 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900">MiniMax-H3 模型使用说明</h1>
              <p className="text-slate-500 text-sm mt-0.5">海螺 H3 视频生成模型，支持文本、图片、视频、音频多模态输入</p>
            </div>
          </div>
        </div>

        {/* Endpoint info */}
        <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 flex flex-wrap gap-4 items-center">
          <div>
            <span className="text-xs font-semibold text-blue-500 uppercase tracking-wide">Endpoint</span>
            <p className="font-mono text-sm text-blue-900 mt-0.5">{baseUrl}/v1/responses</p>
          </div>
          <div className="h-10 w-px bg-blue-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-blue-500 uppercase tracking-wide">工具类型</span>
            <p className="font-mono text-sm text-blue-900 mt-0.5">video_generation</p>
          </div>
          <div className="h-10 w-px bg-blue-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-blue-500 uppercase tracking-wide">异步模式</span>
            <p className="text-sm text-blue-900 mt-0.5">需设置 background: true</p>
          </div>
        </div>

        {/* Overview */}
        <div id="overview" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <h3 className="text-lg font-semibold text-slate-800">功能说明</h3>
            <p className="text-sm text-slate-500 mt-1">MiniMax-H3 模型的能力与接入方式</p>
          </div>
          <div className="p-6 space-y-4 text-sm text-slate-700">
            <p>
              <code className="text-blue-600 bg-blue-50 px-1 rounded">MiniMax-H3</code> 是 MiniMax 海螺（Hailuo）H3 视频生成模型，经腾讯云 VOD 接入。
              通过 <code className="text-blue-600 bg-blue-50 px-1 rounded">POST /v1/responses</code> 端点，在 <code>tools</code> 数组中包含{' '}
              <code>video_generation</code> 工具即可发起视频生成任务。
            </p>
            <p>模型支持以下多模态输入：</p>
            <div className="flex flex-wrap gap-2">
              {[
                { label: 'input_text（文本）', color: 'bg-blue-100 text-blue-700' },
                { label: 'input_image（图片）', color: 'bg-emerald-100 text-emerald-700' },
                { label: 'input_video（视频）', color: 'bg-violet-100 text-violet-700' },
                { label: 'input_audio（音频）', color: 'bg-rose-100 text-rose-700' },
              ].map(s => (
                <span key={s.label} className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${s.color}`}>{s.label}</span>
              ))}
            </div>
            <p>视频时长支持 <strong>4–15 秒</strong>，通过 <code>tools[].seconds</code> 参数控制（未指定时默认 5 秒）。</p>
            <div className="bg-amber-50 border border-amber-100 rounded-lg p-3 text-sm text-amber-800">
              <strong>注意：</strong>所有视频生成任务均为<strong>异步处理</strong>，请务必在请求中包含 <code>"background": true</code>。
              任务提交后会返回包含 <code>response_id</code> 的响应，后续可通过 <code>GET /v1/responses/&#123;response_id&#125;</code> 查询最终结果。
            </div>
          </div>
        </div>

        {/* Input limits */}
        <div id="input-limits" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <h3 className="text-lg font-semibold text-slate-800">输入限制</h3>
            <p className="text-sm text-slate-500 mt-1">参考对象素材的数量、时长与尺寸限制</p>
          </div>
          <div className="p-6 space-y-4 text-sm text-slate-700">
            <div className="overflow-x-auto rounded-xl border border-slate-200">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left">
                  <tr>
                    <th className="px-4 py-2.5 font-semibold text-slate-600">素材类型</th>
                    <th className="px-4 py-2.5 font-semibold text-slate-600">数量</th>
                    <th className="px-4 py-2.5 font-semibold text-slate-600">限制</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {[
                    {
                      type: 'input_image',
                      count: '≤ 9 张',
                      desc: '宽高范围 [256, 5760]',
                    },
                    {
                      type: 'input_video',
                      count: '≤ 3 段',
                      desc: '单段时长 [2, 15] 秒；总时长 ≤ 15 秒；宽高范围 [256, 5760]；宽高比在 5:2 ～ 2:5 范围内',
                    },
                    {
                      type: 'input_audio',
                      count: '≤ 3 段',
                      desc: '单段时长 [2, 15] 秒；总时长 ≤ 15 秒；必须搭配图片或视频输入，不能单独输入',
                    },
                  ].map(r => (
                    <tr key={r.type} className="hover:bg-slate-50">
                      <td className="px-4 py-2.5"><code className="text-violet-600 font-semibold">{r.type}</code></td>
                      <td className="px-4 py-2.5 text-slate-600">{r.count}</td>
                      <td className="px-4 py-2.5 text-slate-600">{r.desc}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="bg-amber-50 border border-amber-100 rounded-lg p-3 text-sm text-amber-800">
              <strong>注意：</strong>混合输入（图片 + 视频 + 音频）的总上限为 <strong>12 个文件</strong>。
            </div>
          </div>
        </div>

        {/* Example 1: reference objects */}
        <div id="ref-object" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <div className="flex items-center gap-3 mb-1">
              <h3 className="text-lg font-semibold text-slate-800">示例1：参考对象</h3>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-violet-100 text-violet-700">多模态引用</span>
            </div>
            <p className="text-sm text-slate-500">同时引用参考图片、参考视频和参考音频，生成带统一构图与背景音乐的视频。</p>
          </div>
          <div className="p-6 space-y-4">
            <div className="bg-violet-50 border border-violet-100 rounded-lg p-3 text-sm text-violet-800">
              <strong>多模态引用方式：</strong>
              <ul className="mt-1.5 space-y-1 list-disc list-inside text-violet-700">
                <li>通过 <code>file_id</code> 给素材命名，在文本 prompt 中用 <code>{`{{file_id}}`}</code> 格式引用</li>
                <li><code>role</code> 字段声明素材角色：<code>reference_image</code>（参考图）、<code>reference_video</code>（参考视频）、<code>reference_audio</code>（参考音频）</li>
                <li><code>image_url</code> / <code>video_url</code> / <code>audio_url</code> 支持公网可访问的素材地址</li>
              </ul>
            </div>
            <CurlSection body={REF_OBJECT_REQUEST} />
          </div>
        </div>

        {/* Example 2: text to video */}
        <div id="t2v" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <div className="flex items-center gap-3 mb-1">
              <h3 className="text-lg font-semibold text-slate-800">示例2：文生视频（T2V）</h3>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700">文本生成</span>
            </div>
            <p className="text-sm text-slate-500">仅通过文本描述生成视频，支持指定宽高比与分辨率。</p>
          </div>
          <div className="p-6 space-y-4">
            <CurlSection body={T2V_REQUEST} />
          </div>
        </div>

        {/* Example 3: image to video */}
        <div id="i2v" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <div className="flex items-center gap-3 mb-1">
              <h3 className="text-lg font-semibold text-slate-800">示例3：图生视频（I2V）</h3>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-100 text-emerald-700">图片引导</span>
            </div>
            <p className="text-sm text-slate-500">以参考图片引导视频内容，配合文本描述控制镜头与动作。</p>
          </div>
          <div className="p-6 space-y-4">
            <CurlSection body={I2V_REQUEST} />
          </div>
        </div>

        {/* Parameters */}
        <div id="params" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <h3 className="text-lg font-semibold text-slate-800">参数说明</h3>
            <p className="text-sm text-slate-500 mt-1">MiniMax-H3 请求参数一览</p>
          </div>
          <div className="p-6 space-y-4">
            <div className="overflow-x-auto rounded-xl border border-slate-200">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left">
                  <tr>
                    <th className="px-4 py-2.5 font-semibold text-slate-600">参数</th>
                    <th className="px-4 py-2.5 font-semibold text-slate-600">说明</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {[
                    { param: 'model', desc: '模型名称，MiniMax-H3（海螺 H3，经腾讯云 VOD 接入）' },
                    { param: 'input', desc: '消息列表，content 支持 input_text / input_image / input_video / input_audio 混合输入' },
                    { param: 'file_id', desc: '素材唯一标识，在文本 prompt 中用 {{file_id}} 格式引用该素材' },
                    { param: 'role', desc: '素材角色：reference_image（参考图）、reference_video（参考视频）、reference_audio（参考音频）' },
                    { param: 'tools[].type', desc: '固定为 video_generation，触发视频生成工具' },
                    { param: 'tools[].aspect_ratio', desc: '输出宽高比，如 16:9、9:16' },
                    { param: 'tools[].resolution', desc: '输出分辨率，如 480p、720p、1080p、2K' },
                    { param: 'tools[].seconds', desc: '视频时长（秒），支持 4–15s，如 5、10；未指定时默认 5 秒' },
                    { param: 'background', desc: '置为 true 时后台异步执行，立即返回 response_id，用于耗时较长的视频生成任务' },
                  ].map(r => (
                    <tr key={r.param} className="hover:bg-slate-50">
                      <td className="px-4 py-2.5"><code className="text-blue-600 font-semibold">{r.param}</code></td>
                      <td className="px-4 py-2.5 text-slate-600">{r.desc}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Async task */}
        <div id="async-task" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <h3 className="text-lg font-semibold text-slate-800">异步任务与结果查询</h3>
            <p className="text-sm text-slate-500 mt-1">视频生成耗时较长，通过 background 模式异步执行并轮询结果</p>
          </div>
          <div className="p-6 space-y-4">
            <div>
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wide block mb-2">立即响应（status: in_progress）</span>
              <CodeBlock code={BACKGROUND_RESPONSE} />
            </div>
            <div>
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wide block mb-2">轮询查询</span>
              <CodeBlock code={`GET /v1/responses/{response_id}\nAuthorization: Bearer <YOUR_API_KEY>`} lang="bash" />
            </div>
            <div>
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wide block mb-2">任务完成响应（status: completed）</span>
              <CodeBlock code={COMPLETED_RESPONSE} />
            </div>
            <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 text-sm text-blue-800">
              <strong>提示：</strong>任务完成后，从 <code>output</code> 中取 <code>video_generation_call</code> 类型条目的 <code>result</code> 字段，即为生成的视频文件地址。
            </div>
          </div>
        </div>
      </div>

      {/* TOC sidebar */}
      <TableOfContents items={TOC_ITEMS} accentColor="blue" />
    </div>
  );
}
