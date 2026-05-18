import { CurlSection } from './HelpShared';

// ---------- code samples ----------

const PIXVERSE_T2V = `{
  "model": "pixverse-v6",
  "background": true,
  "input": [
    {
      "role": "user",
      "type": "message",
      "content": [
        {
          "type": "input_text",
          "text": "一只可爱的橘猫在阳光明媚的窗台上伸懒腰，镜头从侧面慢慢推进，猫咪睁开眼睛看向镜头，毛发的细节清晰可见。电影质感，自然光线。"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "video_generation",
      "resolution": "720p",
      "seconds": 5
    }
  ]
}`;

const PIXVERSE_I2V = `{
  "model": "pixverse-v6",
  "background": true,
  "input": [
    {
      "role": "user",
      "type": "message",
      "content": [
        {
          "type": "input_text",
          "text": "镜头缓慢拉近，猫咪的耳朵微微颤动，尾巴轻轻摇摆"
        },
        {
          "type": "input_image",
          "image_url": "https://example.com/cat.jpg"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "video_generation",
      "seconds": 5
    }
  ]
}`;

const PIXVERSE_C1_REF_EDIT = `{
  "model": "pixverse-c1",
  "background": true,
  "input": [
    {
      "role": "user",
      "type": "message",
      "content": [
        {
          "type": "input_text",
          "text": "把 @ref_img 中的杯子替换为 @ref_obj 中的花瓶"
        },
        {
          "type": "input_image",
          "file_id": "ref_img",
          "image_url": "https://example.com/scene.jpg"
        },
        {
          "type": "input_image",
          "file_id": "ref_obj",
          "image_url": "https://example.com/vase.jpg"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "video_generation",
      "resolution": "720p"
    }
  ]
}`;

// ---------- PixVerse section ----------

export function PixVerseSection() {
  return (
    <div id="pixverse" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
      <div className="p-6 border-b border-slate-100">
        <div className="flex items-center gap-3 mb-1">
          <h3 className="text-lg font-semibold text-slate-800">PixVerse 视频生成</h3>
          <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-rose-100 text-rose-700">爱诗科技</span>
        </div>
        <p className="text-sm text-slate-500">
          使用 PixVerse V6 / C1 模型生成视频，支持文生视频 (T2V)、图生视频 (I2V) 和参考对象编辑，通过 TencentVOD 接入。
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
                  <th className="px-4 py-2.5 font-semibold text-slate-600">功能</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">说明</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">720p 价格</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                <tr className="hover:bg-slate-50">
                  <td className="px-4 py-2.5"><code className="text-rose-600 font-semibold">pixverse-v6</code></td>
                  <td className="px-4 py-2.5 text-slate-600">T2V / I2V</td>
                  <td className="px-4 py-2.5 text-slate-600">支持文生视频、图生视频，可选音频</td>
                  <td className="px-4 py-2.5 text-slate-600">¥0.264/s</td>
                </tr>
                <tr className="hover:bg-slate-50">
                  <td className="px-4 py-2.5"><code className="text-rose-600 font-semibold">pixverse-c1</code></td>
                  <td className="px-4 py-2.5 text-slate-600">T2V / I2V / 参考编辑</td>
                  <td className="px-4 py-2.5 text-slate-600">支持参考对象编辑，可选音频</td>
                  <td className="px-4 py-2.5 text-slate-600">¥0.293/s</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        {/* Text to video */}
        <div id="pixverse-t2v" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">文本生成视频 (T2V)</p>
          <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 text-sm text-blue-800 mb-3">
            <strong>参数：</strong><code>resolution</code> 支持 480p / 540p / 720p / 1080p / 2K / 4K，<code>seconds</code> 设置视频时长。可选 <code>generate_audio: true</code> 生成带音频的视频（价格不同）。
          </div>
          <CurlSection body={PIXVERSE_T2V} />
        </div>

        {/* Image to video */}
        <div id="pixverse-i2v" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">图生视频 (I2V)</p>
          <div className="bg-amber-50 border border-amber-100 rounded-lg p-3 text-sm text-amber-800 mb-3">
            <strong>注意事项：</strong>PixVerse 图生视频<strong>不支持</strong> <code>aspect_ratio</code> 参数，画面比例将基于输入图片自动确定（C1 参考对象编辑模式除外）。
          </div>
          <CurlSection body={PIXVERSE_I2V} />
        </div>

        {/* Reference object editing (C1 only) */}
        <div id="pixverse-ref-edit" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">参考对象编辑 (C1)</p>
          <div className="bg-violet-50 border border-violet-100 rounded-lg p-3 text-sm text-violet-800 mb-3">
            <strong>参考对象编辑：</strong>仅 <code>pixverse-c1</code> 支持。通过 <code>file_id</code> 标记参考图和替换对象，在文本 prompt 中用 <code>@file_id </code> 格式引用。此模式下支持 <code>aspect_ratio</code> + <code>resolution</code>。
          </div>
          <CurlSection body={PIXVERSE_C1_REF_EDIT} />
        </div>

        {/* Parameters */}
        <div id="pixverse-params" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">参数说明</p>
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left">
                <tr>
                  <th className="px-4 py-2.5 font-semibold text-slate-600 w-40">参数</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600 w-24">类型</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600 w-24">可选值</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">说明</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5 font-medium">resolution</td><td className="px-4 py-2.5">string</td><td className="px-4 py-2.5 text-slate-500">480p ~ 4K</td><td className="px-4 py-2.5 text-slate-600">输出分辨率</td></tr>
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5 font-medium">seconds</td><td className="px-4 py-2.5">int</td><td className="px-4 py-2.5 text-slate-500">≥ 1</td><td className="px-4 py-2.5 text-slate-600">视频时长（秒），按秒计费</td></tr>
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5 font-medium">aspect_ratio</td><td className="px-4 py-2.5">string</td><td className="px-4 py-2.5 text-slate-500">16:9 / 9:16 / 1:1 等</td><td className="px-4 py-2.5 text-slate-600">画面宽高比（仅 T2V 和 C1 参考编辑支持）</td></tr>
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5 font-medium">generate_audio</td><td className="px-4 py-2.5">bool</td><td className="px-4 py-2.5 text-slate-500">true / false</td><td className="px-4 py-2.5 text-slate-600">是否生成音频（音频另外计费）</td></tr>
              </tbody>
            </table>
          </div>
        </div>

        <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 text-sm text-blue-800">
          <strong>支持的分辨率：</strong><code>480p</code>、<code>540p</code>、<code>720p</code>、<code>1080p</code>、<code>2K</code>、<code>4K</code>
        </div>

        {/* Pricing */}
        <div id="pixverse-pricing" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">收费标准 (CNY / 秒)</p>
          <div className="space-y-4">
            <PricingBlock model="pixverse-v6" headers={['分辨率', '无音频', '有音频']}>
              <tr><td className="px-4 py-2.5">480p / 540p</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.205</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.264</td></tr>
              <tr><td className="px-4 py-2.5">720p</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.264</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.352</td></tr>
              <tr><td className="px-4 py-2.5">1080p</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.528</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.675</td></tr>
              <tr><td className="px-4 py-2.5">2K</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.634</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.810</td></tr>
              <tr><td className="px-4 py-2.5">4K</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.769</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.971</td></tr>
            </PricingBlock>

            <PricingBlock model="pixverse-c1" headers={['分辨率', '无音频', '有音频']}>
              <tr><td className="px-4 py-2.5">480p / 540p</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.235</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.293</td></tr>
              <tr><td className="px-4 py-2.5">720p</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.293</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.381</td></tr>
              <tr><td className="px-4 py-2.5">1080p</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.557</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.704</td></tr>
              <tr><td className="px-4 py-2.5">2K</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.669</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.845</td></tr>
              <tr><td className="px-4 py-2.5">4K</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.803</td><td className="px-4 py-2.5 text-slate-600 text-center">¥1.014</td></tr>
            </PricingBlock>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------- helpers ----------

function PricingBlock({ model, headers, children }: { model: string; headers: string[]; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
        <code className="text-rose-600 normal-case text-sm font-bold">{model}</code>
      </p>
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
    </div>
  );
}