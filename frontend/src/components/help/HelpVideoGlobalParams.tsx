import { CodeBlock } from './HelpShared';

// ---------- code samples ----------

export const VIDEO_GENERATION_TOOL_SAMPLE = `{
  "model": "<model>",
  "background": true,
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        { "type": "input_text", "text": "提示词" },
        { "type": "input_image", "image_url": "https://..." },
        { "type": "input_video", "video_url": "https://..." },
        { "type": "input_audio", "audio_url": "https://..." }
      ]
    }
  ],
  "tools": [
    {
      "type": "video_generation",
      "aspect_ratio": "16:9",
      "resolution": "720p",
      "seconds": 5
    }
  ]
}`;

// ---------- component ----------

export function GlobalParamsSection() {
  return (
    <div id="global-params" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
      <div className="p-6 border-b border-slate-100">
        <h3 className="text-lg font-semibold text-slate-800">全局参数说明</h3>
        <p className="text-sm text-slate-500 mt-1">视频生成请求的 input 内容块类型与 video_generation 工具参数（通用，跨模型）</p>
      </div>
      <div className="p-6 space-y-6">

        {/* input content block types */}
        <div id="global-input" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">input 内容块类型</p>
          <p className="text-sm text-slate-600 mb-3">请求体 <code>input</code> 数组中 <code>message.content</code> 支持的内容块类型：</p>
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left">
                <tr>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">type</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">说明</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">关键字段</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                <tr className="hover:bg-slate-50">
                  <td className="px-4 py-2.5"><code className="text-cyan-600 font-semibold">input_text</code></td>
                  <td className="px-4 py-2.5 text-slate-600">文本提示词</td>
                  <td className="px-4 py-2.5 text-slate-500 font-mono text-xs">text</td>
                </tr>
                <tr className="hover:bg-slate-50">
                  <td className="px-4 py-2.5"><code className="text-cyan-600 font-semibold">input_image</code></td>
                  <td className="px-4 py-2.5 text-slate-600">参考图片</td>
                  <td className="px-4 py-2.5 text-slate-500 font-mono text-xs">image_url / file_id，可选 role</td>
                </tr>
                <tr className="hover:bg-slate-50">
                  <td className="px-4 py-2.5"><code className="text-cyan-600 font-semibold">input_video</code></td>
                  <td className="px-4 py-2.5 text-slate-600">参考视频</td>
                  <td className="px-4 py-2.5 text-slate-500 font-mono text-xs">video_url / file_id，可选 role、fps</td>
                </tr>
                <tr className="hover:bg-slate-50">
                  <td className="px-4 py-2.5"><code className="text-cyan-600 font-semibold">input_audio</code></td>
                  <td className="px-4 py-2.5 text-slate-600">参考音频</td>
                  <td className="px-4 py-2.5 text-slate-500 font-mono text-xs">input_audio / audio_url / file_id</td>
                </tr>
                <tr className="hover:bg-slate-50">
                  <td className="px-4 py-2.5"><code className="text-cyan-600 font-semibold">input_file</code></td>
                  <td className="px-4 py-2.5 text-slate-600">文件</td>
                  <td className="px-4 py-2.5 text-slate-500 font-mono text-xs">file_id / filename</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 text-sm text-blue-800 mt-3">
            <strong>file_id 引用：</strong><code>input_image</code> / <code>input_video</code> / <code>input_audio</code> 可通过 <code>file_id</code> 引用 <code>/v1/files</code> 上传的素材，并在文本 prompt 中用 <code>{`{{file_id}}`}</code> 占位符引用（详见各模型多模态章节）。
          </div>
        </div>

        {/* tool parameters */}
        <div id="global-tool" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">video_generation 工具参数</p>
          <p className="text-sm text-slate-600 mb-3">请求体 <code>tools</code> 数组中 <code>type: "video_generation"</code> 工具支持的参数：</p>
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left">
                <tr>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">参数</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">类型</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">说明</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5"><code className="text-cyan-600 font-semibold">type</code></td><td className="px-4 py-2.5 text-slate-600">string</td><td className="px-4 py-2.5 text-slate-600">固定值 <code>video_generation</code>（必填）</td></tr>
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5"><code className="text-cyan-600 font-semibold">size</code></td><td className="px-4 py-2.5 text-slate-600">string</td><td className="px-4 py-2.5 text-slate-600">像素尺寸，如 <code>"1280x720"</code></td></tr>
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5"><code className="text-cyan-600 font-semibold">aspect_ratio</code></td><td className="px-4 py-2.5 text-slate-600">string</td><td className="px-4 py-2.5 text-slate-600">宽高比，如 <code>"16:9"</code>、<code>"9:16"</code></td></tr>
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5"><code className="text-cyan-600 font-semibold">resolution</code></td><td className="px-4 py-2.5 text-slate-600">string</td><td className="px-4 py-2.5 text-slate-600">分辨率档位，如 <code>"480p"</code>、<code>"720p"</code>、<code>"1080p"</code></td></tr>
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5"><code className="text-cyan-600 font-semibold">seconds</code></td><td className="px-4 py-2.5 text-slate-600">number / string</td><td className="px-4 py-2.5 text-slate-600">视频时长（秒）</td></tr>
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5"><code className="text-cyan-600 font-semibold">n</code></td><td className="px-4 py-2.5 text-slate-600">number</td><td className="px-4 py-2.5 text-slate-600">生成数量（部分模型映射为人物生成策略）</td></tr>
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5"><code className="text-cyan-600 font-semibold">generate_audio</code></td><td className="px-4 py-2.5 text-slate-600">boolean</td><td className="px-4 py-2.5 text-slate-600">是否生成音频</td></tr>
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5"><code className="text-cyan-600 font-semibold">watermark</code></td><td className="px-4 py-2.5 text-slate-600">boolean</td><td className="px-4 py-2.5 text-slate-600">是否添加水印</td></tr>
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5"><code className="text-cyan-600 font-semibold">person_generation</code></td><td className="px-4 py-2.5 text-slate-600">string</td><td className="px-4 py-2.5 text-slate-600">人物生成策略（部分模型）</td></tr>
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5"><code className="text-cyan-600 font-semibold">task_type</code></td><td className="px-4 py-2.5 text-slate-600">string</td><td className="px-4 py-2.5 text-slate-600">任务模式：<code>auto</code> / <code>reference</code> / <code>edit</code> / <code>extend</code>（Seedance 2.5+）</td></tr>
                <tr className="hover:bg-slate-50"><td className="px-4 py-2.5"><code className="text-cyan-600 font-semibold">parameters</code></td><td className="px-4 py-2.5 text-slate-600">object</td><td className="px-4 py-2.5 text-slate-600">原始参数透传，按需下发到上游</td></tr>
              </tbody>
            </table>
          </div>
          <div className="bg-amber-50 border border-amber-100 rounded-lg p-3 text-sm text-amber-800 mt-3">
            <strong>注意：</strong>各参数的可用性、默认值与取值范围<strong>因模型而异</strong>，详见各模型章节说明。尺寸通常通过 <code>size</code> 或 <code>aspect_ratio</code> + <code>resolution</code> 控制，未指定时使用模型默认值。
          </div>
          <div className="mt-4">
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">请求示例</span>
            <CodeBlock code={VIDEO_GENERATION_TOOL_SAMPLE} lang="json" />
          </div>
        </div>

      </div>
    </div>
  );
}
