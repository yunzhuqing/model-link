import { CodeBlock, CurlSection } from './HelpShared';

// ---------- code samples ----------

export const VIDEO_GENERATION = `{
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
      "aspect_ratio": "9:16",
      "resolution": "480p"
    }
  ]
}`;

export const VIDEO_GENERATION_REF = `{
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
      "aspect_ratio": "9:16",
      "resolution": "480p"
    }
  ]
}`;

export const VIDEO_GENERATION_FILE_ID_REF = `{
  "model": "doubao-seedance-2.0",
  "input": [
    {
      "type": "message",
      "content": [
        {
          "type": "input_text",
          "text": "全程使用{{file-61bf8e8c48f748f994293eb4}}的第一视角构图，全程使用{{file-5db4cb574195466cb8487ead}}作为背景音乐。第一人称视角果茶宣传广告，seedance牌「苹苹安安」苹果果茶限定款；首帧为{{file-90bb0080330f457a8c2c9aae}}，你的手摘下一颗带晨露的阿克苏红苹果，轻脆的苹果碰撞声；2-4 秒：快速切镜，你的手将苹果块投入雪克杯，加入冰块与茶底，用力摇晃，冰块碰撞声与摇晃声卡点轻快鼓点，背景音：「鲜切现摇」；4-6 秒：第一人称成品特写，分层果茶倒入透明杯，你的手轻挤奶盖在顶部铺展，在杯身贴上粉红包标，镜头拉近看奶盖与果茶的分层纹理；6-8 秒：第一人称手持举杯，你将{{file-effcaee85d8141489340e399}}中的果茶举到镜头前（模拟递到观众面前的视角），杯身标签清晰可见，背景音「来一口鲜爽」，尾帧定格为{{file-effcaee85d8141489340e399}}。背景声音统一为女生音色。"
        },
        {
          "type": "input_image",
          "file_id": "file-90bb0080330f457a8c2c9aae"
        },
        {
          "type": "input_image",
          "file_id": "file-effcaee85d8141489340e399"
        },
        {
          "type": "input_video",
          "file_id": "file-5db4cb574195466cb8487ead"
        },
        {
          "type": "input_audio",
          "file_id": "file-61bf8e8c48f748f994293eb4"
        }
      ],
      "role": "user"
    }
  ],
  "tools": [
    {
      "type": "video_generation",
      "aspect_ratio": "16:9",
      "resolution": "720p"
    }
  ],
  "background": true
}`;

export const FILES_UPLOAD_CURL = `curl --location --request POST 'http://localhost:8000/v1/files' \\
--header 'Authorization: Bearer <YOUR_API_KEY>' \\
--form 'file=@"/path/to/cat_01.png"' \\
--form 'purpose="seedance-ref"'`;

export const FILES_UPLOAD_RESPONSE = `{
  "bytes": 2381457,
  "created_at": 1781840390,
  "filename": "cat_01.png",
  "id": "file-d7bbfec7f7e545eba907ce54",
  "object": "file",
  "purpose": "seedance-ref"
}`;

export const VIDEO_GENERATION_FILE_ID_RESPONSE = `{
  "background": true,
  "created_at": 1781837397,
  "id": "resp_9e5166789007421eed1fa0614e77dc26036716a5d1474ff7",
  "metadata": null,
  "model": "doubao-seedance-2.0",
  "object": "response",
  "parallel_tool_calls": false,
  "status": "in_progress"
}`;

export const VIDEO_GENERATION_ROLE = `{
  "model": "doubao-seedance-2.0",
  "background": true,
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        {
          "type": "input_text",
          "text": "Luxury Modern Barrel Side Table product showcase. Keep the background environment (room, window, floor, door) strictly consistent across all scenes. Only the product's material and texture should change across the five storyboard images."
        },
        {
          "type": "input_image",
          "image_url": "https://example.com/storyboard_1.jpg",
          "role": "reference_image"
        },
        {
          "type": "input_image",
          "image_url": "https://example.com/storyboard_2.jpg",
          "role": "reference_image"
        },
        {
          "type": "input_image",
          "image_url": "https://example.com/storyboard_3.jpg",
          "role": "reference_image"
        },
        {
          "type": "input_image",
          "image_url": "https://example.com/storyboard_4.jpg",
          "role": "reference_image"
        },
        {
          "type": "input_image",
          "image_url": "https://example.com/storyboard_5.jpg",
          "role": "reference_image"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "video_generation",
      "seconds": 6,
      "resolution": "720p",
      "generate_audio": true,
      "aspect_ratio": "16:9"
    }
  ]
}`;

// ---------- Seedance unified section ----------

export function SeedanceSection() {
  return (
    <div id="seedance" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
      <div className="p-6 border-b border-slate-100">
        <div className="flex items-center gap-3 mb-1">
          <h3 className="text-lg font-semibold text-slate-800">Seedance 视频生成</h3>
          <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-orange-100 text-orange-700">火山引擎</span>
        </div>
        <p className="text-sm text-slate-500">豆包 Seedance 系列视频模型，支持文生视频、图生视频、多模态素材引用，通过火山引擎 API 接入。</p>
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
        </div>

        {/* Text to video */}
        <div id="seedance-t2v" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">文生视频 (T2V)</p>
          <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 text-sm text-blue-800 mb-3">
            <strong>参数：</strong>通过 <code>size</code> 指定像素尺寸，或使用 <code>aspect_ratio</code> + <code>resolution</code> 控制视频尺寸。
          </div>
          <CurlSection body={VIDEO_GENERATION} />
        </div>

        {/* Multimodal reference */}
        <div id="seedance-multimodal" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">多模态素材引用</p>
          <div className="bg-violet-50 border border-violet-100 rounded-lg p-3 text-sm text-violet-800 mb-3">
            <strong>多模态引用：</strong>通过 <code>file_id</code> 给素材命名，在文本 prompt 中用 <code>{`{{file_id}}`}</code> 格式引用，支持 <code>input_image</code>、<code>input_video</code>、<code>input_audio</code>。
          </div>

          <div className="bg-white border border-slate-200 rounded-xl p-4 space-y-4">
            <div id="seedance-multimodal-url" className="scroll-mt-4">
              <p className="text-sm font-semibold text-slate-800 mb-2">1. file_id 引用 URL</p>
              <p className="text-sm text-slate-600 mb-3">直接在 <code>input_image</code>、<code>input_video</code>、<code>input_audio</code> 中传入素材 URL，同时附带自定义 <code>file_id</code>，再在文本里通过 <code>{`{{file_id}}`}</code> 引用。</p>
              <CurlSection body={VIDEO_GENERATION_REF} />
            </div>
          </div>

          <div id="seedance-multimodal-file" className="bg-slate-50 border border-slate-200 rounded-xl p-4 mt-4 space-y-4 scroll-mt-4">
            <p className="text-sm font-semibold text-slate-800">2. file_id 引用 file 对象</p>
            <p className="text-sm text-slate-600">先通过 <code>/v1/files</code> 创建文件，拿到返回的 <code>file-xxx</code>，再在视频生成请求里把它作为 <code>file_id</code> 使用。</p>
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">
              <strong>备注：</strong>这种方式更适合 Seedance 素材库场景，尤其是真人素材和虚拟素材的复用与统一管理。
            </div>
            <div>
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">1. 先创建文件</span>
              <CodeBlock code={FILES_UPLOAD_CURL} lang="bash" />
            </div>
            <div>
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">上传返回值</span>
              <CodeBlock code={FILES_UPLOAD_RESPONSE} />
            </div>
            <div>
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">2. 在视频生成请求中使用 file_id</span>
              <CurlSection body={VIDEO_GENERATION_FILE_ID_REF} />
            </div>
            <div>
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">任务提交返回值</span>
              <CodeBlock code={VIDEO_GENERATION_FILE_ID_RESPONSE} />
            </div>
          </div>
        </div>

        {/* Image role control */}
        <div id="seedance-role" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">图片角色（role）控制</p>
          <div className="bg-emerald-50 border border-emerald-100 rounded-lg p-3 text-sm text-emerald-800 mb-3">
            <strong>图片角色：</strong>给 <code>input_image</code> 设置 <code>role</code> 字段可显式控制每张图片的用途，取值：<code>first_frame</code>（首帧）、<code>last_frame</code>（尾帧）、<code>reference_image</code>（参考图）。
            <ul className="list-disc list-inside mt-2 space-y-1">
              <li>所有图片均未指定 <code>role</code> 时，系统自动按位置分配：<strong>第一张 → 首帧、最后一张 → 尾帧、中间 → 参考图</strong></li>
              <li>只要任意一张图片显式指定了 <code>role</code>，系统将<strong>原样保留用户输入</strong>，不再自动改写（即使全部为 <code>reference_image</code>）</li>
              <li>适用于多张参考图分镜场景：将所有分镜图设为 <code>reference_image</code>，由文本 prompt 描述分镜顺序，避免被误当作首/尾帧</li>
            </ul>
          </div>
          <CurlSection body={VIDEO_GENERATION_ROLE} />
        </div>

        {/* Model parameter specs */}
        <div id="seedance-models" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">模型参数说明</p>
          <div className="bg-amber-50 border border-amber-100 rounded-lg p-3 text-sm text-amber-800 mb-3">
            <strong>说明：</strong>
            <ul className="list-disc list-inside mt-1 space-y-1">
              <li>未指定 <code>aspect_ratio</code>、<code>resolution</code>、<code>size</code> 时，默认使用 <code>16:9</code> 宽高比和 <code>720p</code> 分辨率</li>
              <li><code>generate_audio</code> 参数仅 1.5-pro 及以后版本支持；1.0 系列不支持此参数，请勿传入</li>
              <li>1.5-pro 及以后版本默认生成有声视频；若需无声视频，设置 <code>generate_audio: false</code></li>
              <li>2.0 系列支持通过 <code>file_id</code> 引用多模态素材（图片、视频、音频）</li>
            </ul>
          </div>

          {/* Size mapping for 1.0 series */}
          <div className="mb-4">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
              Seedance 1.0 系列尺寸映射 <span className="text-slate-400 font-normal normal-case">（size ↔ aspect_ratio + resolution）</span>
            </p>
            <SizeTable rows={[
              { ratio: '16:9', s480: '864x480',  s720: '1248x704',  s1080: '1920x1088' },
              { ratio: '4:3',  s480: '736x544',  s720: '1120x832',  s1080: '1664x1248' },
              { ratio: '1:1',  s480: '640x640',  s720: '960x960',   s1080: '1440x1440' },
              { ratio: '3:4',  s480: '544x736',  s720: '832x1120',  s1080: '1248x1664' },
              { ratio: '9:16', s480: '480x864',  s720: '704x1248',  s1080: '1088x1920' },
              { ratio: '21:9', s480: '960x416',  s720: '1504x640',  s1080: '2176x928' },
            ]} />
          </div>

          {/* Size mapping for 1.5/2.0 series */}
          <div>
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
              Seedance 1.5 / 2.0 系列尺寸映射 <span className="text-slate-400 font-normal normal-case">（size ↔ aspect_ratio + resolution）</span>
            </p>
            <SizeTable rows={[
              { ratio: '16:9', s480: '864x496',  s720: '1280x720',  s1080: '1920x1080' },
              { ratio: '4:3',  s480: '752x560',  s720: '1112x834',  s1080: '1664x1248' },
              { ratio: '1:1',  s480: '640x640',  s720: '960x960',   s1080: '1440x1440' },
              { ratio: '3:4',  s480: '560x752',  s720: '834x1112',  s1080: '1248x1664' },
              { ratio: '9:16', s480: '496x864',  s720: '720x1280',  s1080: '1080x1920' },
              { ratio: '21:9', s480: '992x432',  s720: '1470x630',  s1080: '2206x946' },
            ]} />
          </div>
          <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 text-sm text-blue-800 mt-4">
            <strong>使用方式：</strong>可通过 <code>size</code> 直接传入像素尺寸（如 <code>"496x864"</code>），系统自动解析为对应的 <code>aspect_ratio</code> 和 <code>resolution</code>；也可直接指定 <code>aspect_ratio</code> 和 <code>resolution</code> 参数。
          </div>
        </div>

        {/* Pricing */}
        <div id="seedance-pricing" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">收费标准 (CNY / M output tokens)</p>
          {/* 1.0 Pro */}
          <PricingBlock model="doubao-seedance-1.0-pro" headers={['480p', '720p', '1080p']}>
            <tr className="hover:bg-slate-50">
              <td className="px-4 py-2.5 text-slate-600 text-center">¥15/M</td>
              <td className="px-4 py-2.5 text-slate-600 text-center">¥15/M</td>
              <td className="px-4 py-2.5 text-slate-600 text-center">¥15/M</td>
            </tr>
          </PricingBlock>

          {/* 1.0 Pro Fast */}
          <PricingBlock model="doubao-seedance-1.0-pro-fast" headers={['480p', '720p', '1080p']}>
            <tr className="hover:bg-slate-50">
              <td className="px-4 py-2.5 text-slate-600 text-center">¥4.2/M</td>
              <td className="px-4 py-2.5 text-slate-600 text-center">¥4.2/M</td>
              <td className="px-4 py-2.5 text-slate-600 text-center">¥4.2/M</td>
            </tr>
          </PricingBlock>

          {/* 1.5 Pro */}
          <PricingBlock model="doubao-seedance-1.5-pro" headers={['输出类型', '480p', '720p', '1080p']}>
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
          </PricingBlock>

          {/* 2.0 */}
          <PricingBlock model="doubao-seedance-2.0" headers={['输入类型', '480p', '720p', '1080p']}>
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
          </PricingBlock>

          {/* 2.0 Fast */}
          <PricingBlock model="doubao-seedance-2.0-fast" headers={['输入类型', '480p', '720p']}>
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
          </PricingBlock>
        </div>
      </div>
    </div>
  );
}

// ---------- helpers ----------

interface SizeRow { ratio: string; s480: string; s720: string; s1080: string }

function SizeTable({ rows }: { rows: SizeRow[] }) {
  return (
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
          {rows.map(r => (
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
  );
}

function PricingBlock({ model, headers, children }: { model: string; headers: string[]; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
        <code className="text-orange-600 normal-case text-sm font-bold">{model}</code>
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
