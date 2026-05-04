import { CurlSection, CodeBlock } from './HelpShared';

// ---------- code samples ----------

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

// ---------- Veo unified section ----------

export function VeoSection() {
  return (
    <div id="veo" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
      <div className="p-6 border-b border-slate-100">
        <div className="flex items-center gap-3 mb-1">
          <h3 className="text-lg font-semibold text-slate-800">Veo 视频生成</h3>
          <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700">Google</span>
        </div>
        <p className="text-sm text-slate-500">
          使用 Google Veo 3.1 系列模型生成高质量视频。支持通过 Gemini API 和 VertexAI 两种方式接入，API 格式统一，仅模型名不同。
        </p>
      </div>
      <div className="p-6 space-y-6">

        {/* ====== Gemini Veo ====== */}
        <div id="veo-gemini" className="scroll-mt-4">
          <div className="flex items-center gap-3 mb-3">
            <h4 className="text-base font-semibold text-slate-800">Gemini Veo</h4>
            <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700">Gemini API</span>
          </div>
          <p className="text-sm text-slate-500 mb-4">通过 Google Gemini API 调用 Veo 模型，模型名以 <code>-generate-preview</code> 结尾。Veo 仅支持生成含声音的视频。</p>

          {/* Model list */}
          <div className="mb-4">
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
          <div className="mb-4">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">文本生成视频</p>
            <CurlSection body={VEO_TEXT_TO_VIDEO} />
          </div>

          {/* Image to video */}
          <div className="mb-4">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">图像引导生成（首帧/尾帧插值）</p>
            <div className="bg-amber-50 border border-amber-100 rounded-lg p-3 text-sm text-amber-800 mb-3">
              <strong>图生视频：</strong>在 content 中传入 base64 编码的图片作为首帧（第一张图片），Veo 会以该图像为起始帧生成视频。
              传入两张图片时，第一张作为首帧，第二张作为尾帧（插值生成）。
            </div>
            <CurlSection body={VEO_IMAGE_TO_VIDEO} />
          </div>

          {/* Response */}
          <div>
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">响应格式</p>
            <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-sm text-slate-700 mb-3">
              result 字段为 Google 生成的视频 URI，需携带 API Key 才能下载。
            </div>
            <CodeBlock code={VEO_RESPONSE} />
          </div>
        </div>

        {/* ====== VertexAI Veo ====== */}
        <div id="veo-vertexai" className="scroll-mt-4">
          <div className="flex items-center gap-3 mb-3">
            <h4 className="text-base font-semibold text-slate-800">VertexAI Veo</h4>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700">Google Cloud</span>
          </div>
          <p className="text-sm text-slate-500 mb-3">
            通过 Google Cloud VertexAI 平台调用 Veo 模型，模型名以 <code>-generate-001</code> 结尾。与 Gemini Veo 使用相同的 API 格式，仅需替换 model 字段并配置 VertexAI 供应商。
          </p>

          <div className="mb-3">
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
            <strong>使用说明：</strong>VertexAI Veo 与 Gemini Veo 使用相同的请求格式，仅需将 <code>model</code> 字段替换为对应的 <code>*-generate-001</code> 模型名称。
          </div>
        </div>

        {/* ====== Model Limits ====== */}
        <div id="veo-limits" className="scroll-mt-4">
          <h4 className="text-base font-semibold text-slate-800 mb-3">模型限制说明</h4>
          <p className="text-sm text-slate-500 mb-4">各 VertexAI Veo 模型的能力边界与参数约束（Gemini Veo 约束基本一致）。</p>

          <LimitModelBlock model="veo-3.1-generate-001" rows={[
            { label: '视频时长', value: '4、6 或 8 秒；图生视频仅支持 8 秒' },
            { label: '每次最大生成数量', value: '4 个' },
            { label: '图生视频最大图片大小', value: '20 MB' },
            { label: '支持宽高比', value: '9:16、16:9' },
            { label: '支持输入分辨率', value: '720p、1080p、4K（预览）' },
            { label: '支持输出分辨率', value: '720p、1080p、4K（预览）' },
            { label: '支持帧率', value: '24 FPS' },
            { label: '输出格式', value: 'video/mp4' },
          ]} />

          <LimitModelBlock model="veo-3.1-fast-generate-001" rows={[
            { label: '视频时长', value: '4、6 或 8 秒' },
            { label: '每次最大生成数量', value: '4 个' },
            { label: '图生视频最大图片大小', value: '20 MB' },
            { label: '支持宽高比', value: '9:16、16:9' },
            { label: '支持输入分辨率', value: '720p、1080p、4K（预览）' },
            { label: '支持输出分辨率', value: '720p、1080p、4K（预览）' },
            { label: '支持帧率', value: '24 FPS' },
            { label: '输出格式', value: 'video/mp4' },
          ]} />

          <LimitModelBlock model="veo-3.1-lite-generate-001" rows={[
            { label: '视频时长', value: '4、6 或 8 秒' },
            { label: '每次最大生成数量', value: '4 个' },
            { label: '图生视频最大图片大小', value: '20 MB' },
            { label: '支持宽高比', value: '9:16、16:9' },
            { label: '支持输入分辨率', value: '720p、1080p' },
            { label: '支持输出分辨率', value: '720p、1080p' },
            { label: '支持帧率', value: '24 FPS' },
            { label: '输出格式', value: 'video/mp4' },
          ]} />

          <div className="bg-amber-50 border border-amber-100 rounded-lg p-3 text-sm text-amber-800 mt-4">
            <strong>注意：</strong><code>veo-3.1-lite-generate-001</code> 不支持 4K 分辨率，最高仅支持 1080p 输入/输出。<code>veo-3.1-generate-001</code> 的图生视频模式仅支持 8 秒时长。
          </div>
        </div>

        {/* ====== Pricing ====== */}
        <div id="veo-pricing" className="scroll-mt-4">
          <h4 className="text-base font-semibold text-slate-800 mb-3">收费标准</h4>
          <p className="text-sm text-slate-500 mb-4">Veo 3.1 系列按视频时长（秒）计费，价格因模型、分辨率和是否包含音频而异。Gemini 和 VertexAI 定价相同。</p>

          <PricingBlock model="veo-3.1-generate-001" headers={['输出类型', '720p', '1080p', '4K']}>
            <tr className="hover:bg-slate-50"><td className="px-4 py-2.5 font-medium text-slate-700">视频 + 音频</td><td className="px-4 py-2.5 text-slate-600 text-center">$0.40/s</td><td className="px-4 py-2.5 text-slate-600 text-center">$0.40/s</td><td className="px-4 py-2.5 text-slate-600 text-center">$0.60/s</td></tr>
            <tr className="hover:bg-slate-50"><td className="px-4 py-2.5 font-medium text-slate-700">仅视频</td><td className="px-4 py-2.5 text-slate-600 text-center">$0.20/s</td><td className="px-4 py-2.5 text-slate-600 text-center">$0.20/s</td><td className="px-4 py-2.5 text-slate-600 text-center">$0.40/s</td></tr>
          </PricingBlock>

          <PricingBlock model="veo-3.1-fast-generate-001" headers={['输出类型', '720p', '1080p', '4K']}>
            <tr className="hover:bg-slate-50"><td className="px-4 py-2.5 font-medium text-slate-700">视频 + 音频</td><td className="px-4 py-2.5 text-slate-600 text-center">$0.10/s</td><td className="px-4 py-2.5 text-slate-600 text-center">$0.12/s</td><td className="px-4 py-2.5 text-slate-600 text-center">$0.30/s</td></tr>
            <tr className="hover:bg-slate-50"><td className="px-4 py-2.5 font-medium text-slate-700">仅视频</td><td className="px-4 py-2.5 text-slate-600 text-center">$0.08/s</td><td className="px-4 py-2.5 text-slate-600 text-center">$0.10/s</td><td className="px-4 py-2.5 text-slate-600 text-center">$0.25/s</td></tr>
          </PricingBlock>

          <PricingBlock model="veo-3.1-lite-generate-001" headers={['输出类型', '720p', '1080p']}>
            <tr className="hover:bg-slate-50"><td className="px-4 py-2.5 font-medium text-slate-700">视频 + 音频</td><td className="px-4 py-2.5 text-slate-600 text-center">$0.05/s</td><td className="px-4 py-2.5 text-slate-600 text-center">$0.08/s</td></tr>
            <tr className="hover:bg-slate-50"><td className="px-4 py-2.5 font-medium text-slate-700">仅视频</td><td className="px-4 py-2.5 text-slate-600 text-center">$0.03/s</td><td className="px-4 py-2.5 text-slate-600 text-center">$0.05/s</td></tr>
          </PricingBlock>

          <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 text-sm text-blue-800 mt-4">
            <strong>说明：</strong>以上价格适用于 VertexAI (<code>*-generate-001</code>) 和 Gemini (<code>*-generate-preview</code>) 两种接入方式，定价相同。<code>veo-3.1-lite-generate-001</code> 不支持 4K 分辨率。
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------- helpers ----------

interface LimitRow { label: string; value: string }

function LimitTable({ rows }: { rows: LimitRow[] }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left">
          <tr>
            <th className="px-4 py-2.5 font-semibold text-slate-600 w-56">限制项</th>
            <th className="px-4 py-2.5 font-semibold text-slate-600">说明</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map(r => (
            <tr key={r.label} className="hover:bg-slate-50">
              <td className="px-4 py-2.5 font-medium text-slate-700">{r.label}</td>
              <td className="px-4 py-2.5 text-slate-600">{r.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LimitModelBlock({ model, rows }: { model: string; rows: LimitRow[] }) {
  return (
    <div className="mb-4">
      <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
        <code className="text-green-600 normal-case text-sm font-bold">{model}</code>
      </p>
      <LimitTable rows={rows} />
    </div>
  );
}

function PricingTable({ headers, children }: { headers: string[]; children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left">
          <tr>
            {headers.map(h => (
              <th key={h} className="px-4 py-2.5 font-semibold text-slate-600 text-center">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {children}
        </tbody>
      </table>
    </div>
  );
}

function PricingBlock({ model, headers, children }: { model: string; headers: string[]; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
        <code className="text-green-600 normal-case text-sm font-bold">{model}</code>
      </p>
      <PricingTable headers={headers}>{children}</PricingTable>
    </div>
  );
}