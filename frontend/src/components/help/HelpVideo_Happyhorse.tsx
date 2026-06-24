import { CurlSection } from './HelpShared';

// ---------- code samples ----------

const HAPPYHORSE_T2V = `{
  "model": "happyhorse-1.0-t2v",
  "background": true,
  "input": [
    {
      "role": "user",
      "type": "message",
      "content": [
        {
          "type": "input_text",
          "text": "在一处风景秀丽的江南水乡，一位身穿旗袍的优雅女士缓缓走过石桥。镜头从远处的拱桥平推进到女士优雅的背影，河面波光粼粼，柳枝轻拂。"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "video_generation",
      "resolution": "720P",
      "seconds": 5
    }
  ]
}`;

const HAPPYHORSE_I2V = `{
  "model": "happyhorse-1.0-i2v",
  "background": true,
  "input": [
    {
      "role": "user",
      "type": "message",
      "content": [
        {
          "type": "input_text",
          "text": "阳光洒在花丛中，蝴蝶翩翩起舞，镜头缓慢推进展现花瓣的细节"
        },
        {
          "type": "input_image",
          "image_url": "https://example.com/flower.jpg"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "video_generation",
      "resolution": "1080P",
      "seconds": 5
    }
  ]
}`;

const HAPPYHORSE_R2V = `{
  "model": "happyhorse-1.0-r2v",
  "background": true,
  "input": [
    {
      "role": "user",
      "type": "message",
      "content": [
        {
          "type": "input_text",
          "text": "{{woman}}沙滩上端着红酒杯享受着红酒"
        },
        {
          "type": "input_image",
          "image_url": "https://images.pexels.com/photos/12455533/pexels-photo-12455533.jpeg",
          "file_id": "woman"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "video_generation",
      "seconds": 4,
      "aspect_ratio": "9:16",
      "resolution": "720p"
    }
  ]
}`;

const HAPPYHORSE_VIDEO_EDIT = `{
  "model": "happyhorse-1.0-video-edit",
  "background": true,
  "input": [
    {
      "role": "user",
      "type": "message",
      "content": [
        {
          "type": "input_text",
          "text": "把原视频里的人物的衣服换成红色长裙"
        },
        {
          "type": "input_video",
          "video_url": "https://example.com/source_video.mp4",
          "file_id": "src_video"
        },
        {
          "type": "input_image",
          "image_url": "https://example.com/ref_img.jpg",
          "file_id": "ref_img"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "video_generation",
      "resolution": "720P"
    }
  ]
}`;

// ---------- Happyhorse ----------

export function HappyhorseSection() {
  return (
    <div id="happyhorse" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
      <div className="p-6 border-b border-slate-100">
        <div className="flex items-center gap-3 mb-1">
          <h3 className="text-lg font-semibold text-slate-800">Happyhorse 视频生成</h3>
          <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-pink-100 text-pink-700">阿里巴巴</span>
        </div>
        <p className="text-sm text-slate-500">Happyhorse 系列视频模型，支持文生视频、图生视频、参考图生视频和视频编辑，通过 Bailian API 接入。</p>
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
                  <th className="px-4 py-2.5 font-semibold text-slate-600">类型</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">说明</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">价格</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5"><code className="text-pink-600 font-semibold">happyhorse-1.0-t2v</code></td><td className="px-4 py-2.5">T2V</td><td className="px-4 py-2.5 text-slate-600">文生视频</td><td className="px-4 py-2.5 text-slate-600">720P ¥0.9/s / 1080P ¥1.6/s</td></tr>
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5"><code className="text-pink-600 font-semibold">happyhorse-1.0-i2v</code></td><td className="px-4 py-2.5">I2V</td><td className="px-4 py-2.5 text-slate-600">图生视频</td><td className="px-4 py-2.5 text-slate-600">720P ¥0.9/s / 1080P ¥1.6/s</td></tr>
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5"><code className="text-pink-600 font-semibold">happyhorse-1.0-r2v</code></td><td className="px-4 py-2.5">R2V</td><td className="px-4 py-2.5 text-slate-600">参考图生视频</td><td className="px-4 py-2.5 text-slate-600">720P ¥0.9/s / 1080P ¥1.6/s</td></tr>
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5"><code className="text-pink-600 font-semibold">happyhorse-1.0-video-edit</code></td><td className="px-4 py-2.5">Video Edit</td><td className="px-4 py-2.5 text-slate-600">视频编辑</td><td className="px-4 py-2.5 text-slate-600">720P ¥0.9/s / 1080P ¥1.6/s</td></tr>
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5"><code className="text-pink-600 font-semibold">happyhorse-1.1-t2v</code></td><td className="px-4 py-2.5">T2V</td><td className="px-4 py-2.5 text-slate-600">文生视频 (1.1)</td><td className="px-4 py-2.5 text-slate-600">720P ¥0.9/s / 1080P ¥1.6/s</td></tr>
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5"><code className="text-pink-600 font-semibold">happyhorse-1.1-i2v</code></td><td className="px-4 py-2.5">I2V</td><td className="px-4 py-2.5 text-slate-600">图生视频 (1.1)</td><td className="px-4 py-2.5 text-slate-600">720P ¥0.9/s / 1080P ¥1.6/s</td></tr>
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5"><code className="text-pink-600 font-semibold">happyhorse-1.1-r2v</code></td><td className="px-4 py-2.5">R2V</td><td className="px-4 py-2.5 text-slate-600">参考图生视频 (1.1)</td><td className="px-4 py-2.5 text-slate-600">720P ¥0.9/s / 1080P ¥1.6/s</td></tr>
              </tbody>
            </table>
          </div>
        </div>

        {/* Text to video */}
        <div id="happyhorse-t2v" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">文生视频 (T2V)</p>
          <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 text-sm text-blue-800 mb-3">
            <strong>参数：</strong><code>resolution</code> 支持 720P / 1080P，<code>seconds</code> 设置视频时长（按秒计费）。
          </div>
          <CurlSection body={HAPPYHORSE_T2V} />
        </div>

        {/* Image to video */}
        <div id="happyhorse-i2v" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">图生视频 (I2V)</p>
          <div className="bg-amber-50 border border-amber-100 rounded-lg p-3 text-sm text-amber-800 mb-3">
            <strong>图生视频：</strong>传入一张图片作为首帧，模型基于该图生成动态视频。
          </div>
          <CurlSection body={HAPPYHORSE_I2V} />
        </div>

        {/* Reference image to video */}
        <div id="happyhorse-r2v" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">参考图生视频 (R2V)</p>
          <div className="bg-amber-50 border border-amber-100 rounded-lg p-3 text-sm text-amber-800 mb-3">
            <strong>参考图生视频：</strong>在文本中使用 <code>{`{{file_id}}`}</code> 引用图片变量，模型基于参考图内容和文本描述生成视频。支持 <code>aspect_ratio</code> 控制画面比例。
          </div>
          <CurlSection body={HAPPYHORSE_R2V} />
        </div>

        {/* Video edit */}
        <div id="happyhorse-video-edit" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">视频编辑 (Video Edit)</p>
          <div className="bg-amber-50 border border-amber-100 rounded-lg p-3 text-sm text-amber-800 mb-3">
            <strong>视频编辑：</strong>传入原始视频、参考图片和文本描述，以参考图为风格基准编辑原视频。
            <code>file_id: "ref_img"</code> 标记参考图，<code>file_id: "src_video"</code> 标记源视频。
          </div>
          <CurlSection body={HAPPYHORSE_VIDEO_EDIT} />
        </div>
      </div>
    </div>
  );
}