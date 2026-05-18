import { CurlSection } from './HelpShared';

// ---------- code samples ----------

const VIDU_T2V = `{
  "model": "viduq3-turbo",
  "background": true,
  "input": [
    {
      "role": "user",
      "type": "message",
      "content": [
        {
          "type": "input_text",
          "text": "在一座未来城市的夜景中，霓虹灯光闪烁，一辆悬浮汽车在摩天大楼之间穿梭。镜头跟随跑车，穿过层层云雾，最终停在一座高塔顶端。半写实风格，电影质感。"
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

const VIDU_I2V = `{
  "model": "viduq3-pro",
  "background": true,
  "input": [
    {
      "role": "user",
      "type": "message",
      "content": [
        {
          "type": "input_text",
          "text": "镜头缓慢拉近，女孩微微一笑，长发被微风吹动，背景是盛开的花园"
        },
        {
          "type": "input_image",
          "image_url": "https://example.com/portrait.jpg"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "video_generation",
      "aspect_ratio": "16:9",
      "seconds": 5
    }
  ]
}`;

const VIDU_MULTIMODAL = `{
  "model": "viduq3",
  "background": true,
  "input": [
    {
      "role": "user",
      "type": "message",
      "content": [
        {
          "type": "input_text",
          "text": "让 @ref_img 中的角色做出 @ref_video 中的动作，背景为赛博朋克风格的街道"
        },
        {
          "type": "input_image",
          "file_id": "ref_img",
          "image_url": "https://example.com/character.jpg"
        },
        {
          "type": "input_video",
          "file_id": "ref_video",
          "video_url": "https://example.com/action.mp4"
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

// ---------- Vidu section ----------

export function ViduSection() {
  return (
    <div id="vidu" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
      <div className="p-6 border-b border-slate-100">
        <div className="flex items-center gap-3 mb-1">
          <h3 className="text-lg font-semibold text-slate-800">Vidu 视频生成</h3>
          <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-700">生数科技</span>
        </div>
        <p className="text-sm text-slate-500">
          使用 Vidu Q3 系列模型生成视频，支持文生视频 (T2V)、图生视频 (I2V) 和多模态素材引用，通过 TencentVOD 接入。
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
                  <th className="px-4 py-2.5 font-semibold text-slate-600">分辨率</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">说明</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">720p 价格</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                <tr className="hover:bg-slate-50">
                  <td className="px-4 py-2.5"><code className="text-purple-600 font-semibold">viduq3-mix</code></td>
                  <td className="px-4 py-2.5 text-slate-600">720p / 1080p</td>
                  <td className="px-4 py-2.5 text-slate-600">快速混合模型，无音频</td>
                  <td className="px-4 py-2.5 text-slate-600">¥0.782/s</td>
                </tr>
                <tr className="hover:bg-slate-50">
                  <td className="px-4 py-2.5"><code className="text-purple-600 font-semibold">viduq3</code></td>
                  <td className="px-4 py-2.5 text-slate-600">480p ~ 4K</td>
                  <td className="px-4 py-2.5 text-slate-600">标准质量</td>
                  <td className="px-4 py-2.5 text-slate-600">¥0.625/s</td>
                </tr>
                <tr className="hover:bg-slate-50">
                  <td className="px-4 py-2.5"><code className="text-purple-600 font-semibold">viduq3-pro</code></td>
                  <td className="px-4 py-2.5 text-slate-600">480p ~ 4K</td>
                  <td className="px-4 py-2.5 text-slate-600">专业质量</td>
                  <td className="px-4 py-2.5 text-slate-600">¥0.782/s</td>
                </tr>
                <tr className="hover:bg-slate-50">
                  <td className="px-4 py-2.5"><code className="text-purple-600 font-semibold">viduq3-turbo</code></td>
                  <td className="px-4 py-2.5 text-slate-600">480p ~ 4K</td>
                  <td className="px-4 py-2.5 text-slate-600">极速生成</td>
                  <td className="px-4 py-2.5 text-slate-600">¥0.375/s</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        {/* Text to video */}
        <div id="vidu-t2v" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">文本生成视频 (T2V)</p>
          <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 text-sm text-blue-800 mb-3">
            <strong>参数：</strong><code>resolution</code> 支持 480p / 720p / 1080p / 2K / 4K，<code>seconds</code> 设置视频时长（按秒计费）。
          </div>
          <CurlSection body={VIDU_T2V} />
        </div>

        {/* Image to video */}
        <div id="vidu-i2v" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">图生视频 (I2V)</p>
          <div className="bg-amber-50 border border-amber-100 rounded-lg p-3 text-sm text-amber-800 mb-3">
            <strong>图生视频：</strong>传入一张图片作为首帧，Vidu 会基于该图生成动态视频。支持 <code>aspect_ratio</code> 控制画面比例。
          </div>
          <CurlSection body={VIDU_I2V} />
        </div>

        {/* Multimodal reference */}
        <div id="vidu-multimodal" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">多模态素材引用</p>
          <div className="bg-violet-50 border border-violet-100 rounded-lg p-3 text-sm text-violet-800 mb-3">
            <strong>多模态引用：</strong>通过 <code>file_id</code> 给素材命名，在文本 prompt 中用 <code>@file_id </code> 格式引用（注意 <code>@</code> 后跟空格），支持 <code>input_image</code> 和 <code>input_video</code>。
          </div>
          <CurlSection body={VIDU_MULTIMODAL} />
        </div>

        {/* Parameters */}
        <div id="vidu-params" className="scroll-mt-4">
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
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5 font-medium">resolution</td><td className="px-4 py-2.5">string</td><td className="px-4 py-2.5 text-slate-500">480p / 720p / 1080p / 2K / 4K</td><td className="px-4 py-2.5 text-slate-600">输出分辨率</td></tr>
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5 font-medium">seconds</td><td className="px-4 py-2.5">int</td><td className="px-4 py-2.5 text-slate-500">≥ 1</td><td className="px-4 py-2.5 text-slate-600">视频时长（秒），按秒计费</td></tr>
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5 font-medium">aspect_ratio</td><td className="px-4 py-2.5">string</td><td className="px-4 py-2.5 text-slate-500">16:9 / 9:16 / 1:1 / 4:3 / 3:4</td><td className="px-4 py-2.5 text-slate-600">画面宽高比</td></tr>
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5 font-medium">negative_prompt</td><td className="px-4 py-2.5">string</td><td className="px-4 py-2.5 text-slate-500">任意字符</td><td className="px-4 py-2.5 text-slate-600">不希望生成的负面描述</td></tr>
              </tbody>
            </table>
          </div>
        </div>

        <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 text-sm text-blue-800">
          <strong>支持的分辨率：</strong><code>480p</code>、<code>720p</code>、<code>1080p</code>、<code>2K</code>、<code>4K</code>（viduq3-mix 仅支持 720p / 1080p）
        </div>

        {/* Pricing */}
        <div id="vidu-pricing" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">收费标准 (CNY / 秒)</p>
          <div className="space-y-4">
            <PricingBlock model="viduq3-turbo" headers={['分辨率', '价格']}>
              <tr><td className="px-4 py-2.5">480p</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.250</td></tr>
              <tr><td className="px-4 py-2.5">720p</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.375</td></tr>
              <tr><td className="px-4 py-2.5">1080p</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.438</td></tr>
              <tr><td className="px-4 py-2.5">2K</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.526</td></tr>
              <tr><td className="px-4 py-2.5">4K</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.631</td></tr>
            </PricingBlock>

            <PricingBlock model="viduq3" headers={['分辨率', '价格']}>
              <tr><td className="px-4 py-2.5">480p</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.313</td></tr>
              <tr><td className="px-4 py-2.5">720p</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.625</td></tr>
              <tr><td className="px-4 py-2.5">1080p</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.782</td></tr>
              <tr><td className="px-4 py-2.5">2K</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.939</td></tr>
              <tr><td className="px-4 py-2.5">4K</td><td className="px-4 py-2.5 text-slate-600 text-center">¥1.127</td></tr>
            </PricingBlock>

            <PricingBlock model="viduq3-pro / viduq3-mix" headers={['分辨率', '价格']}>
              <tr><td className="px-4 py-2.5">480p</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.313 (Pro)</td></tr>
              <tr><td className="px-4 py-2.5">720p</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.782</td></tr>
              <tr><td className="px-4 py-2.5">1080p</td><td className="px-4 py-2.5 text-slate-600 text-center">¥0.938</td></tr>
              <tr><td className="px-4 py-2.5">2K</td><td className="px-4 py-2.5 text-slate-600 text-center">¥1.126 (Pro)</td></tr>
              <tr><td className="px-4 py-2.5">4K</td><td className="px-4 py-2.5 text-slate-600 text-center">¥1.352 (Pro)</td></tr>
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
        <code className="text-purple-600 normal-case text-sm font-bold">{model}</code>
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