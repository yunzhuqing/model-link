import { CurlSection, CodeBlock } from './HelpShared';

// ---------- code samples ----------

const KLING_V3_OMNI_TEXT_TO_VIDEO = `{
  "model": "kling-v3-omni",
  "background": true,
  "input": [
    {
      "role": "user",
      "type": "message",
      "content": [
        {
          "type": "input_text",
          "text": "在古代长安的街道上，一位身着红色长袍的女子慢慢走过石板路。夕阳的余晖洒在她的身上，影子被拉得很长。远处传来驼铃声。"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "video_generation",
      "aspect_ratio": "9:16"
    }
  ]
}`;

const KLING_BACKGROUND_RESPONSE = `{
  "background": true,
  "created_at": 1780580262,
  "id": "resp_eebe6924290bd7a18c785c144b188807ff4727bb11a84102",
  "metadata": null,
  "model": "kling-v3-omni",
  "object": "response",
  "parallel_tool_calls": false,
  "status": "in_progress"
}`;

const KLING_BACKGROUND_COMPLETED = `{
  "created_at": 1780580344,
  "id": "resp_eebe6924290bd7a18c785c144b188807ff4727bb11a84102",
  "metadata": null,
  "model": "kling-v3-omni",
  "object": "response",
  "output": [
    {
      "id": "vid_91677010b8e1159a88ec29976f81fa9c27c79d045e9857a7",
      "result": "http://251000800.vod2.myqcloud.com/.../aigcVideoGenFile.mp4",
      "status": "completed",
      "type": "video_generation_call"
    }
  ],
  "parallel_tool_calls": false,
  "status": "completed",
  "usage": {
    "input_tokens": 0,
    "output_tokens": 1,
    "price": {
      "actual_amount": 1.0,
      "currency": "CNY",
      "discount": 1.0,
      "exchange_rate": 7.0,
      "payable_amount": 1.0
    },
    "total_tokens": 1
  }
}`;

const KLING_V3_OMNI_IMAGE_TO_VIDEO = `{
  "model": "kling-v3-omni",
  "background": true,
  "input": [
    {
      "role": "user",
      "type": "message",
      "content": [
        {
          "type": "input_text",
          "text": "镜头缓慢拉近，女子的长发被风吹动，她抬头看向镜头"
        },
        {
          "type": "input_image",
          "image_url": "https://example.com/image.jpg"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "video_generation",
      "duration": 5
    }
  ]
}`;

const KLING_V3_OMNI_MULTIMODAL_REF = `{
  "model": "kling-v3-omni",
  "background": true,
  "input": [
    {
      "role": "user",
      "type": "message",
      "content": [
        {
          "type": "input_text",
          "text": "让 {{ref_image}} 中的女子做出 {{ref_video}} 中的舞蹈动作"
        },
        {
          "type": "input_image",
          "file_id": "ref_image",
          "image_url": "https://example.com/image.jpg"
        },
        {
          "type": "input_video",
          "file_id": "ref_video",
          "video_url": "https://example.com/dance.mp4"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "video_generation",
      "duration": 5
    }
  ]
}`;

// ---------- Kling unified section ----------

export function KlingSection() {
  return (
    <div id="kling" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
      <div className="p-6 border-b border-slate-100">
        <div className="flex items-center gap-3 mb-1">
          <h3 className="text-lg font-semibold text-slate-800">Kling 视频生成</h3>
          <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-indigo-100 text-indigo-700">快手</span>
        </div>
        <p className="text-sm text-slate-500">
          使用快手 Kling V3 Omni 模型生成视频，支持文生视频 (T2V)、图生视频 (I2V) 和多模态素材引用。
        </p>
      </div>
      <div className="p-6 space-y-6">
        {/* Model info */}
        <div>
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">模型</p>
          <code className="text-indigo-600 font-semibold text-sm">kling-v3-omni</code>
          <p className="text-sm text-slate-600 mt-1">Kling V3 Omni 是多模态统一视频生成模型，同时支持文本生成视频和图片引导生成视频。</p>
        </div>

        {/* Text to video */}
        <div id="kling-t2v" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">文本生成视频 (T2V)</p>
          <CurlSection body={KLING_V3_OMNI_TEXT_TO_VIDEO} />
        </div>

        {/* Background async response */}
        <div id="kling-t2v-response" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">异步响应示例</p>
          <div className="space-y-4">
            <div>
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wide block mb-2">立即响应（status: in_progress）</span>
              <CodeBlock code={KLING_BACKGROUND_RESPONSE} />
            </div>
            <div>
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wide block mb-2">轮询查询</span>
              <CodeBlock code={`GET /v1/responses/{response_id}\nAuthorization: Bearer <YOUR_API_KEY>`} lang="bash" />
            </div>
            <div>
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wide block mb-2">任务完成响应（status: completed）</span>
              <CodeBlock code={KLING_BACKGROUND_COMPLETED} />
            </div>
          </div>
        </div>

        {/* Image to video */}
        <div id="kling-i2v" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">图生视频 (I2V)</p>
          <div className="bg-amber-50 border border-amber-100 rounded-lg p-3 text-sm text-amber-800 mb-3">
            <strong>图生视频：</strong>在 content 中传入图片 URL，Kling 会基于该图生成动态视频。
          </div>
          <CurlSection body={KLING_V3_OMNI_IMAGE_TO_VIDEO} />
        </div>

        {/* Multimodal reference */}
        <div id="kling-multimodal" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">多模态素材引用</p>
          <div className="bg-violet-50 border border-violet-100 rounded-lg p-3 text-sm text-violet-800 mb-3">
            <strong>多模态引用：</strong>通过 <code>file_id</code> 给素材命名，在文本 prompt 中用 <code>{`{{file_id}}`}</code> 格式引用，支持 <code>input_image</code> 和 <code>input_video</code>。
          </div>
          <CurlSection body={KLING_V3_OMNI_MULTIMODAL_REF} />
        </div>

        {/* Parameters */}
        <div id="kling-params" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">图生视频参数说明</p>
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
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5 font-medium">image_tail_required</td><td className="px-4 py-2.5">bool</td><td className="px-4 py-2.5 text-slate-500">true / false</td><td className="px-4 py-2.5 text-slate-600">是否必须传入尾帧图片</td></tr>
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5 font-medium">negative_prompt</td><td className="px-4 py-2.5">string</td><td className="px-4 py-2.5 text-slate-500">任意字符</td><td className="px-4 py-2.5 text-slate-600">不希望生成的负面描述</td></tr>
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5 font-medium">generate_modes</td><td className="px-4 py-2.5">list[string]</td><td className="px-4 py-2.5 text-slate-500">标准 / 影视 / 电影</td><td className="px-4 py-2.5 text-slate-600">风格模式（数组形式）</td></tr>
              </tbody>
            </table>
          </div>
        </div>

        <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 text-sm text-blue-800">
          <strong>支持的分辨率：</strong><code>480P</code>、<code>720P</code>、<code>1080P(高清)</code>
        </div>

        {/* Pricing */}
        <div id="kling-pricing" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">收费标准 (CNY / 次)</p>
          <PricingBlock model="kling-v3-omni" headers={['时长', '720p', '1080p']}>
            <tr className="hover:bg-slate-50"><td className="px-4 py-2.5 font-medium text-slate-700">生成 5 秒</td><td className="px-4 py-2.5 text-slate-600 text-center">¥1.80</td><td className="px-4 py-2.5 text-slate-600 text-center">¥2.70</td></tr>
            <tr className="hover:bg-slate-50"><td className="px-4 py-2.5 font-medium text-slate-700">生成 10 秒</td><td className="px-4 py-2.5 text-slate-600 text-center">¥3.15</td><td className="px-4 py-2.5 text-slate-600 text-center">¥4.72</td></tr>
          </PricingBlock>
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
        <code className="text-indigo-600 normal-case text-sm font-bold">{model}</code>
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