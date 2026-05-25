import { useNavigate } from 'react-router-dom';
import { ArrowLeft, ImageIcon } from 'lucide-react';
import { useBaseUrl, TableOfContents, SectionCard, CodeBlock, CurlSection } from '../components/help/HelpShared';
import type { TocItem } from '../components/help/HelpShared';
const TOC_ITEMS: TocItem[] = [
  { id: 'overview', label: '功能说明' },
  { id: 'api-section', label: 'API 调用' },
  { id: 'responses-api', label: '　├ Responses API', indent: true },
  { id: 'responses-params', label: '　│　├ 工具参数', indent: true },
  { id: 'responses-response', label: '　│　└ 工具响应格式', indent: true },
  { id: 'images-api', label: '　├ Image Generations', indent: true },
  { id: 'images-params', label: '　│　├ 请求参数', indent: true },
  { id: 'images-response', label: '　│　└ 响应格式', indent: true },
  { id: 'edits-api', label: '　└ Image Edits', indent: true },
  { id: 'edits-params', label: '　　　├ 请求参数', indent: true },
  { id: 'edits-response', label: '　　　└ 响应格式', indent: true },
  { id: 'models-section', label: '模型说明' },
  { id: 'gpt-image-sizes', label: '　├ GPT Image', indent: true },
  { id: 'gemini-sizes', label: '　├ Nano Banana', indent: true },
  { id: 'seedream-sizes', label: '　├ Seedream', indent: true },
  { id: 'z-image-sizes', label: '　└ Z-Image', indent: true },
];

const RESPONSES_REQUEST = `{
  "model": "qwen-image-2.0-pro",
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        {
          "type": "input_text",
          "text": "生成狸花猫的照片"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "image_generation",
      "n": 1,
      "size": "2048x2048"
    }
  ],
  "background": false
}`;

const RESPONSES_RESPONSE = `{
  "id": "img_abc123...",
  "object": "response",
  "status": "completed",
  "model": "qwen-image-2.0-pro",
  "output": [
    {
      "type": "image_generation_call",
      "id": "img_abc123...",
      "status": "completed",
      "result": "https://..."
    }
  ]
}`;

const IMAGES_REQUEST = `{
  "model": "qwen-image-2.0-pro",
  "prompt": "将右边的狗的颜色换成红色",
  "images": [
    {
      "image_url": "https://images.pexels.com/photos/1108099/pexels-photo-1108099.jpeg?auto=compress&cs=tinysrgb&w=800"
    }
  ],
  "n": 1,
  "size": "2048x2048",
  "quality": "auto",
  "background": "auto",
  "output_format": "png"
}`;

const IMAGES_RESPONSE = `{
  "created": 1712345678,
  "data": [
    {
      "url": "https://example.com/generated-image.png",
      "revised_prompt": "一只可爱的狸花猫在阳光下打盹"
    }
  ],
  "output_format": "png"
}`;

const IMAGES_B64_RESPONSE = `{
  "created": 1712345678,
  "data": [
    {
      "b64_json": "data:image/png;base64,iVBORw0KGgo..."
    }
  ],
  "output_format": "png"
}`;

const EDITS_REQUEST = `{
  "model": "doubao-seedream-5.0",
  "prompt": "将右边的狗的颜色换成红色",
  "images": [
    {
      "image_url": "https://images.pexels.com/photos/1108099/pexels-photo-1108099.jpeg?auto=compress&cs=tinysrgb&w=800"
    }
  ],
  "n": 1,
  "size": "2048x2048",
  "quality": "auto",
  "background": "auto",
  "output_format": "png"
}`;

const EDITS_RESPONSE = `{
  "created": 1712345678,
  "data": [
    {
      "url": "https://example.com/edited-image.png",
      "revised_prompt": "将右边的狗的颜色换成红色"
    }
  ],
  "output_format": "png",
  "size": "2048x2048",
  "quality": "auto",
  "background": "opaque"
}`;

export default function HelpImageGeneration() {
  const navigate = useNavigate();
  const baseUrl = useBaseUrl();

  return (
    <div className="flex gap-8 max-w-6xl mx-auto">
      <div className="flex-1 min-w-0 space-y-8">
        {/* Back + header */}
        <div>
          <button
            onClick={() => navigate('/help')}
            className="flex items-center gap-1.5 text-sm text-slate-500 hover:text-pink-600 mb-4 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            返回帮助中心
          </button>
          <div className="flex items-center gap-4">
            <div className="p-3 bg-gradient-to-br from-pink-500 to-rose-600 rounded-2xl shadow-lg shadow-pink-500/25">
              <ImageIcon className="w-7 h-7 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900">图片生成</h1>
              <p className="text-slate-500 text-sm mt-0.5">支持 Responses API 工具调用、Images Generations API 和 Images Edits API</p>
            </div>
          </div>
        </div>

        {/* Overview */}
        <div id="overview" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <h3 className="text-lg font-semibold text-slate-800 mb-1">功能说明</h3>
            <p className="text-sm text-slate-500">图片生成功能分为<strong> API 调用</strong>（三种接入方式）和<strong> 模型说明</strong>（各模型支持的尺寸参数）。</p>
          </div>
          <div className="p-6 space-y-3">
            <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-3 text-sm text-emerald-800">
              <strong>接入方式对比：</strong>
              <ul className="mt-1.5 space-y-1 list-disc list-inside text-emerald-700">
                <li><strong className="text-emerald-900">Responses API + image_generation 工具（推荐）</strong> — 对话式图片生成，支持多轮对话上下文、图生图、异步模式</li>
                <li><strong className="text-emerald-900">/v1/images/generations</strong> — OpenAI 兼容接口，参数扁平化，文生图更简洁直接</li>
                <li><strong className="text-emerald-900">/v1/images/edits</strong> — 图片编辑接口，传入原图 + 编辑指令，支持蒙版、背景控制等</li>
              </ul>
            </div>
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">
              <strong>注意：</strong>需要图片生成模型。模型须在管理面板中配置，支持的尺寸详见下方「模型说明」章节。
            </div>
            <div className="overflow-x-auto rounded-xl border border-slate-200">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left">
                  <tr>
                    <th className="px-4 py-2.5 font-semibold text-slate-600">模型系列</th>
                    <th className="px-4 py-2.5 font-semibold text-slate-600">模型 ID</th>
                    <th className="px-4 py-2.5 font-semibold text-slate-600">输出格式</th>
                    <th className="px-4 py-2.5 font-semibold text-slate-600">尺寸范围</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {[
                    { family: 'GPT Image',    models: 'gpt-image-2',              format: 'png / jpg / webp', size: '1K ~ 4K（9 种比例）' },
                    { family: 'Nano Banana',  models: 'gemini-2.5-flash-image / gemini-3-pro-image-preview / gemini-3.1-flash-image-preview', format: 'png / jpg', size: '512 ~ 4K' },
                    { family: 'Seedream',     models: 'seedream-4.0 / 4.5 / 5.0 / doubao-seedream 系列', format: 'png / jpg', size: '1K ~ 4K' },
                    { family: 'Z-Image',      models: 'z-image-turbo',             format: 'png', size: '1K / 1.5K / 2K（11 种比例）' },
                    { family: 'Qwen Image',   models: 'qwen-image-2.0 / 2.0-pro',  format: 'png', size: '512x512 ~ 2048x2048' },
                  ].map((r) => (
                    <tr key={r.family} className="hover:bg-slate-50">
                      <td className="px-4 py-2.5 font-semibold text-slate-700 text-xs">{r.family}</td>
                      <td className="px-4 py-2.5"><code className="text-pink-600 text-xs">{r.models}</code></td>
                      <td className="px-4 py-2.5 text-slate-600 font-mono text-xs">{r.format}</td>
                      <td className="px-4 py-2.5 text-slate-600 text-xs">{r.size}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* ========== API 调用 Section ========== */}
        <div id="api-section" className="flex items-center gap-3 scroll-mt-4">
          <div className="h-px flex-1 bg-slate-300" />
          <span className="text-sm font-bold text-slate-500 uppercase tracking-widest px-2">API 调用</span>
          <div className="h-px flex-1 bg-slate-300" />
        </div>

        {/* Responses API endpoint info */}
        <div className="bg-pink-50 border border-pink-100 rounded-xl p-4 flex flex-wrap gap-4 items-center">
          <div>
            <span className="text-xs font-semibold text-pink-500 uppercase tracking-wide">Endpoint</span>
            <p className="font-mono text-sm text-pink-900 mt-0.5">{baseUrl}/v1/responses</p>
          </div>
          <div className="h-8 w-px bg-pink-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-pink-500 uppercase tracking-wide">Tool Type</span>
            <p className="font-mono text-sm text-pink-900 mt-0.5">image_generation</p>
          </div>
          <div className="h-8 w-px bg-pink-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-pink-500 uppercase tracking-wide">Auth</span>
            <p className="font-mono text-sm text-pink-900 mt-0.5">Bearer &lt;API_KEY&gt;</p>
          </div>
        </div>

        {/* Responses API basic usage */}
        <SectionCard
          id="responses-api"
          title="Responses API 图片生成"
          badge="推荐"
          badgeColor="bg-emerald-100 text-emerald-700"
          description="在 tools 中设置 type: image_generation，模型会根据用户文本描述生成图片。支持多轮对话、图生图及异步模式。"
        >
          <CurlSection body={RESPONSES_REQUEST} />
        </SectionCard>

        {/* Responses API params */}
        <SectionCard
          id="responses-params"
          title="image_generation 工具参数"
          description="image_generation tool 支持以下可选参数。"
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
                  { name: 'type',            required: true,  type: 'string',  desc: '固定为 "image_generation"' },
                  { name: 'n',               required: false, type: 'number',  desc: '生成图片数量，别名：number、count' },
                  { name: 'size',            required: false, type: 'string',  desc: '图片尺寸，如 "1024x1024"' },
                  { name: 'response_format', required: false, type: 'string',  desc: '"b64_json"（默认）或 "url"' },
                  { name: 'image_format',    required: false, type: 'string',  desc: '"png"（默认）或 "jpg"；别名：output_format' },
                  { name: 'seed',            required: false, type: 'number',  desc: '随机种子，用于结果可复现' },
                  { name: 'aspect_ratio',   required: false, type: 'string',  desc: '宽高比，如 "1:1"、"16:9"、"9:16"（Z-Image Turbo 使用）' },
                  { name: 'resolution',      required: false, type: 'string',  desc: '分辨率档位，如 "1K"、"1.5K"、"2K"（Z-Image Turbo 使用）' },
                  { name: 'watermark',       required: false, type: 'boolean', desc: '是否添加水印' },
                ].map((r) => (
                  <tr key={r.name} className="hover:bg-slate-50">
                    <td className="px-4 py-2.5"><code className="text-pink-600 font-semibold">{r.name}</code></td>
                    <td className="px-4 py-2.5 text-slate-500 font-mono text-xs">{r.type}</td>
                    <td className="px-4 py-2.5">{r.required ? <span className="text-red-500">是</span> : <span className="text-slate-400">否</span>}</td>
                    <td className="px-4 py-2.5 text-slate-600">{r.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>

        {/* Responses API response format */}
        <SectionCard
          id="responses-response"
          title="Responses API 响应格式"
          description="output 包含 image_generation_call 类型的输出项，result 为图片 URL 或 base64。"
        >
          <CodeBlock code={RESPONSES_RESPONSE} />
        </SectionCard>

        {/* ========== Images Generations API Section ========== */}
        <div className="flex items-center gap-3">
          <div className="h-px flex-1 bg-orange-200" />
          <span className="text-xs font-semibold text-orange-400 uppercase tracking-widest px-2">Image Generations API</span>
          <div className="h-px flex-1 bg-orange-200" />
        </div>

        {/* Images API endpoint info */}
        <div className="bg-orange-50 border border-orange-100 rounded-xl p-4 flex flex-wrap gap-4 items-center">
          <div>
            <span className="text-xs font-semibold text-orange-500 uppercase tracking-wide">Endpoint</span>
            <p className="font-mono text-sm text-orange-900 mt-0.5">{baseUrl}/v1/images/generations</p>
          </div>
          <div className="h-8 w-px bg-orange-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-orange-500 uppercase tracking-wide">Method</span>
            <p className="text-sm font-medium text-orange-900 mt-0.5">POST</p>
          </div>
          <div className="h-8 w-px bg-orange-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-orange-500 uppercase tracking-wide">Auth</span>
            <p className="font-mono text-sm text-orange-900 mt-0.5">Bearer &lt;API_KEY&gt;</p>
          </div>
        </div>

        {/* Images API basic usage */}
        <SectionCard
          id="images-api"
          title="Images Generations API"
          badge="OpenAI 兼容"
          badgeColor="bg-orange-100 text-orange-700"
          description="兼容 OpenAI /v1/images/generations 接口，直接传入 prompt 生成图片，参数更简洁。"
        >
          <CurlSection body={IMAGES_REQUEST} endpoint={`${baseUrl}/v1/images/generations`} />
        </SectionCard>

        {/* Images API params */}
        <SectionCard
          id="images-params"
          title="Images API 请求参数"
          description="支持以下参数控制图片生成行为。"
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
                  { name: 'model',            required: true,  type: 'string',  desc: '图片生成模型名称或别名' },
                  { name: 'prompt',           required: true,  type: 'string',  desc: '图片描述文字' },
                  { name: 'images',           required: false, type: 'array',   desc: '参考图片列表，每项含 image_url，用于图生图场景' },
                  { name: 'n',                required: false, type: 'integer', desc: '生成图片数量，默认 1' },
                  { name: 'size',             required: false, type: 'string',  desc: '图片尺寸，如 "1024x1024"' },
                  { name: 'response_format',  required: false, type: 'string',  desc: '"url"（默认）或 "b64_json"' },
                  { name: 'output_format',    required: false, type: 'string',  desc: '图片格式：png | jpeg | webp' },
                  { name: 'quality',          required: false, type: 'string',  desc: '质量：standard | hd | low | medium | high | auto' },
                  { name: 'style',            required: false, type: 'string',  desc: '风格：vivid | natural' },
                  { name: 'user',             required: false, type: 'string',  desc: '终端用户标识' },
                ].map((r) => (
                  <tr key={r.name} className="hover:bg-slate-50">
                    <td className="px-4 py-2.5"><code className="text-orange-600 font-semibold">{r.name}</code></td>
                    <td className="px-4 py-2.5 text-slate-500 font-mono text-xs">{r.type}</td>
                    <td className="px-4 py-2.5">{r.required ? <span className="text-red-500">是</span> : <span className="text-slate-400">否</span>}</td>
                    <td className="px-4 py-2.5 text-slate-600">{r.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>

        {/* Images API response format */}
        <SectionCard
          id="images-response"
          title="Images API 响应格式"
          description="响应包含生成时间、图片数据和输出格式。"
        >
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">URL 格式响应</span>
            <CodeBlock code={IMAGES_RESPONSE} />
          </div>
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">Base64 格式响应</span>
            <CodeBlock code={IMAGES_B64_RESPONSE} />
          </div>
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left">
                <tr>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">字段</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">类型</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">说明</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {[
                  { name: 'created',               type: 'integer', desc: '生成时间（Unix 时间戳）' },
                  { name: 'data',                  type: 'array',   desc: '图片数据列表' },
                  { name: 'data[].url',            type: 'string',  desc: '图片 URL（response_format 为 "url" 时）' },
                  { name: 'data[].b64_json',       type: 'string',  desc: 'Base64 编码的图片数据（response_format 为 "b64_json" 时）' },
                  { name: 'data[].revised_prompt', type: 'string',  desc: '模型优化后的提示词（可选）' },
                  { name: 'output_format',         type: 'string',  desc: '图片文件格式：png | jpeg | webp' },
                ].map((r) => (
                  <tr key={r.name} className="hover:bg-slate-50">
                    <td className="px-4 py-2.5"><code className="text-orange-600 font-semibold">{r.name}</code></td>
                    <td className="px-4 py-2.5 text-slate-500 font-mono text-xs">{r.type}</td>
                    <td className="px-4 py-2.5 text-slate-600">{r.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>

        {/* ========== Images Edits API Section ========== */}
        <div className="flex items-center gap-3">
          <div className="h-px flex-1 bg-violet-200" />
          <span className="text-xs font-semibold text-violet-400 uppercase tracking-widest px-2">Image Edits API</span>
          <div className="h-px flex-1 bg-violet-200" />
        </div>

        {/* Edits API endpoint info */}
        <div className="bg-violet-50 border border-violet-100 rounded-xl p-4 flex flex-wrap gap-4 items-center">
          <div>
            <span className="text-xs font-semibold text-violet-500 uppercase tracking-wide">Endpoint</span>
            <p className="font-mono text-sm text-violet-900 mt-0.5">{baseUrl}/v1/images/edits</p>
          </div>
          <div className="h-8 w-px bg-violet-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-violet-500 uppercase tracking-wide">Method</span>
            <p className="text-sm font-medium text-violet-900 mt-0.5">POST</p>
          </div>
          <div className="h-8 w-px bg-violet-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-violet-500 uppercase tracking-wide">Auth</span>
            <p className="font-mono text-sm text-violet-900 mt-0.5">Bearer &lt;API_KEY&gt;</p>
          </div>
        </div>

        {/* Edits API basic usage */}
        <SectionCard
          id="edits-api"
          title="Images Edits API"
          badge="图片编辑"
          badgeColor="bg-violet-100 text-violet-700"
          description="兼容 OpenAI /v1/images/edits 接口，传入原始图片和编辑指令，对图片进行修改。支持蒙版（mask）、背景控制等高级参数。"
        >
          <CurlSection body={EDITS_REQUEST} endpoint={`${baseUrl}/v1/images/edits`} />
        </SectionCard>

        {/* Edits API params */}
        <SectionCard
          id="edits-params"
          title="Images Edits 请求参数"
          description="支持以下参数控制图片编辑行为。"
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
                  { name: 'model',           required: true,  type: 'string',  desc: '图片编辑模型名称或别名' },
                  { name: 'prompt',          required: true,  type: 'string',  desc: '编辑指令描述' },
                  { name: 'images',          required: false, type: 'array',   desc: '输入图片列表，每项含 image_url 或 file_id' },
                  { name: 'mask',            required: false, type: 'object',  desc: '蒙版图片，含 image_url 或 file_id，指定编辑区域' },
                  { name: 'n',               required: false, type: 'integer', desc: '生成图片数量，默认 1' },
                  { name: 'size',            required: false, type: 'string',  desc: '输出尺寸，如 "1024x1024"' },
                  { name: 'response_format', required: false, type: 'string',  desc: '"url"（默认）或 "b64_json"' },
                  { name: 'output_format',   required: false, type: 'string',  desc: '图片格式：png | jpeg | webp' },
                  { name: 'quality',         required: false, type: 'string',  desc: '质量：low | medium | high | auto' },
                  { name: 'background',      required: false, type: 'string',  desc: '背景：transparent | opaque | auto' },
                  { name: 'input_fidelity',  required: false, type: 'string',  desc: '输入保真度：high | low' },
                  { name: 'moderation',      required: false, type: 'string',  desc: '内容审核：low | auto' },
                  { name: 'user',            required: false, type: 'string',  desc: '终端用户标识' },
                ].map((r) => (
                  <tr key={r.name} className="hover:bg-slate-50">
                    <td className="px-4 py-2.5"><code className="text-violet-600 font-semibold">{r.name}</code></td>
                    <td className="px-4 py-2.5 text-slate-500 font-mono text-xs">{r.type}</td>
                    <td className="px-4 py-2.5">{r.required ? <span className="text-red-500">是</span> : <span className="text-slate-400">否</span>}</td>
                    <td className="px-4 py-2.5 text-slate-600">{r.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="bg-violet-50 border border-violet-200 rounded-lg p-3 text-sm text-violet-800">
            <strong>images 格式示例：</strong>
            <code className="block mt-1 bg-violet-100 rounded p-2 text-xs font-mono text-violet-900">
              {'[{"image_url": "https://example.com/photo.png"}, {"file_id": "file_abc123"}]'}
            </code>
          </div>
        </SectionCard>

        {/* Edits API response format */}
        <SectionCard
          id="edits-response"
          title="Images Edits 响应格式"
          description="响应包含编辑后的图片数据、输出格式及编辑参数。"
        >
          <CodeBlock code={EDITS_RESPONSE} />
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left">
                <tr>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">字段</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">类型</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">说明</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {[
                  { name: 'created',               type: 'integer', desc: '生成时间（Unix 时间戳）' },
                  { name: 'data',                  type: 'array',   desc: '图片数据列表' },
                  { name: 'data[].url',            type: 'string',  desc: '图片 URL（response_format 为 "url" 时）' },
                  { name: 'data[].b64_json',       type: 'string',  desc: 'Base64 编码的图片数据（response_format 为 "b64_json" 时）' },
                  { name: 'data[].revised_prompt', type: 'string',  desc: '模型优化后的提示词（可选）' },
                  { name: 'output_format',         type: 'string',  desc: '图片文件格式：png | jpeg | webp' },
                  { name: 'size',                  type: 'string',  desc: '输出图片尺寸' },
                  { name: 'quality',               type: 'string',  desc: '图片质量等级' },
                  { name: 'background',            type: 'string',  desc: '背景类型：transparent | opaque' },
                ].map((r) => (
                  <tr key={r.name} className="hover:bg-slate-50">
                    <td className="px-4 py-2.5"><code className="text-violet-600 font-semibold">{r.name}</code></td>
                    <td className="px-4 py-2.5 text-slate-500 font-mono text-xs">{r.type}</td>
                    <td className="px-4 py-2.5 text-slate-600">{r.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>

        {/* ========== 模型说明 Section ========== */}
        <div id="models-section" className="flex items-center gap-3 scroll-mt-4">
          <div className="h-px flex-1 bg-slate-300" />
          <span className="text-sm font-bold text-slate-500 uppercase tracking-widest px-2">模型说明</span>
          <div className="h-px flex-1 bg-slate-300" />
        </div>

        {/* GPT Image 2 size reference */}
        <SectionCard
          id="gpt-image-sizes"
          title="GPT Image 2 支持尺寸"
          description="OpenAI gpt-image-2 模型支持的图片尺寸参考表。size 参数传入 WxH 分辨率字符串，支持 1K、2K、4K 三个档位。"
        >
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left">
                <tr>
                  <th className="px-3 py-2 font-semibold text-slate-600 w-16">比例</th>
                  <th className="px-3 py-2 font-semibold text-slate-600">1K</th>
                  <th className="px-3 py-2 font-semibold text-slate-600">2K</th>
                  <th className="px-3 py-2 font-semibold text-slate-600">4K</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-xs">
                {[
                  { ratio: '1:1',  k1: '1024x1024',  k2: '2048x2048',  k4: '3840x3840' },
                  { ratio: '3:2',  k1: '1536x1024',  k2: '3072x2048',  k4: '3840x2560' },
                  { ratio: '2:3',  k1: '1024x1536',  k2: '2048x3072',  k4: '2560x3840' },
                  { ratio: '3:4',  k1: '768x1024',   k2: '1536x2048',  k4: '2880x3840' },
                  { ratio: '4:3',  k1: '1024x768',   k2: '2048x1536',  k4: '3840x2880' },
                  { ratio: '16:9', k1: '1024x576',   k2: '2048x1152',  k4: '3840x2160' },
                  { ratio: '9:16', k1: '576x1024',   k2: '1152x2048',  k4: '2160x3840' },
                  { ratio: '21:9', k1: '1024x439',   k2: '2048x878',   k4: '3840x1646' },
                  { ratio: '9:21', k1: '439x1024',   k2: '878x2048',   k4: '1646x3840' },
                ].map((r) => (
                  <tr key={r.ratio} className="hover:bg-slate-50">
                    <td className="px-3 py-1.5"><code className="text-pink-600 font-semibold">{r.ratio}</code></td>
                    <td className="px-3 py-1.5 font-mono text-slate-600">{r.k1}</td>
                    <td className="px-3 py-1.5 font-mono text-slate-600">{r.k2}</td>
                    <td className="px-3 py-1.5 font-mono text-slate-600">{r.k4}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-800 mt-2">
            <strong>提示：</strong>gpt-image-2 的 size 参数使用 WxH 精确分辨率格式，需与上表中的尺寸匹配。
            支持通过 TencentVOD 路由访问。
          </div>
        </SectionCard>

        <SectionCard
          id="gemini-sizes"
          title="Nano Banana（Gemini 图像模型）支持尺寸"
          description="Nano Banana 即 Gemini 图像生成系列模型支持的尺寸参考表，通过 TencentVOD 路由。"
        >
          <div className="space-y-6">
            {/* Gemini 2.5 Flash Image */}
            <div>
              <h4 className="text-sm font-semibold text-slate-700 mb-2">gemini-2.5-flash-image（固定分辨率）</h4>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="px-3 py-2 font-semibold text-slate-600 w-16">比例</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">分辨率</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 text-xs">
                    {[
                      { ratio: '1:1',  res: '1024x1024' },
                      { ratio: '2:3',  res: '832x1248' },
                      { ratio: '3:2',  res: '1248x832' },
                      { ratio: '3:4',  res: '864x1184' },
                      { ratio: '4:3',  res: '1184x864' },
                      { ratio: '4:5',  res: '896x1152' },
                      { ratio: '5:4',  res: '1152x896' },
                      { ratio: '9:16', res: '768x1344' },
                      { ratio: '16:9', res: '1344x768' },
                      { ratio: '21:9', res: '1536x672' },
                    ].map((r) => (
                      <tr key={r.ratio} className="hover:bg-slate-50">
                        <td className="px-3 py-1.5"><code className="text-pink-600 font-semibold">{r.ratio}</code></td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.res}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Gemini 3 Pro Image Preview */}
            <div>
              <h4 className="text-sm font-semibold text-slate-700 mb-2">gemini-3-pro-image-preview（1K / 2K / 4K）</h4>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="px-3 py-2 font-semibold text-slate-600 w-16">比例</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">1K</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">2K</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">4K</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 text-xs">
                    {[
                      { ratio: '1:1',  k1: '1024x1024', k2: '2048x2048', k4: '4096x4096' },
                      { ratio: '2:3',  k1: '848x1264',  k2: '1696x2528', k4: '3392x5056' },
                      { ratio: '3:2',  k1: '1264x848',  k2: '2528x1696', k4: '5056x3392' },
                      { ratio: '3:4',  k1: '896x1200',  k2: '1792x2400', k4: '3584x4800' },
                      { ratio: '4:3',  k1: '1200x896',  k2: '2400x1792', k4: '4800x3584' },
                      { ratio: '4:5',  k1: '928x1152',  k2: '1856x2304', k4: '3712x4608' },
                      { ratio: '5:4',  k1: '1152x928',  k2: '2304x1856', k4: '4608x3712' },
                      { ratio: '9:16', k1: '768x1376',  k2: '1536x2752', k4: '3072x5504' },
                      { ratio: '16:9', k1: '1376x768',  k2: '2752x1536', k4: '5504x3072' },
                      { ratio: '21:9', k1: '1584x672',  k2: '3168x1344', k4: '6336x2688' },
                    ].map((r) => (
                      <tr key={r.ratio} className="hover:bg-slate-50">
                        <td className="px-3 py-1.5"><code className="text-pink-600 font-semibold">{r.ratio}</code></td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.k1}</td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.k2}</td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.k4}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Gemini 3.1 Flash Image Preview */}
            <div>
              <h4 className="text-sm font-semibold text-slate-700 mb-2">gemini-3.1-flash-image-preview（512 / 1K / 2K / 4K）</h4>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="px-3 py-2 font-semibold text-slate-600 w-16">比例</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">512</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">1K</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">2K</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">4K</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 text-xs">
                    {[
                      { ratio: '1:1',  s512: '512x512',   k1: '1024x1024',  k2: '2048x2048',  k4: '4096x4096' },
                      { ratio: '1:4',  s512: '256x1024',  k1: '512x2048',   k2: '1024x4096',  k4: '2048x8192' },
                      { ratio: '1:8',  s512: '192x1536',  k1: '384x3072',   k2: '768x6144',   k4: '1536x12288' },
                      { ratio: '2:3',  s512: '424x632',   k1: '848x1264',   k2: '1696x2528',  k4: '3392x5056' },
                      { ratio: '3:2',  s512: '632x424',   k1: '1264x848',   k2: '2528x1696',  k4: '5056x3392' },
                      { ratio: '3:4',  s512: '448x600',   k1: '896x1200',   k2: '1792x2400',  k4: '3584x4800' },
                      { ratio: '4:1',  s512: '1024x256',  k1: '2048x512',   k2: '4096x1024',  k4: '8192x2048' },
                      { ratio: '4:3',  s512: '600x448',   k1: '1200x896',   k2: '2400x1792',  k4: '4800x3584' },
                      { ratio: '4:5',  s512: '464x576',   k1: '928x1152',   k2: '1856x2304',  k4: '3712x4608' },
                      { ratio: '5:4',  s512: '576x464',   k1: '1152x928',   k2: '2304x1856',  k4: '4608x3712' },
                      { ratio: '8:1',  s512: '1536x192',  k1: '3072x384',   k2: '6144x768',   k4: '12288x1536' },
                      { ratio: '9:16', s512: '384x688',   k1: '768x1376',   k2: '1536x2752',  k4: '3072x5504' },
                      { ratio: '16:9', s512: '688x384',   k1: '1376x768',   k2: '2752x1536',  k4: '5504x3072' },
                      { ratio: '21:9', s512: '792x168',   k1: '1584x672',   k2: '3168x1344',  k4: '6336x2688' },
                    ].map((r) => (
                      <tr key={r.ratio} className="hover:bg-slate-50">
                        <td className="px-3 py-1.5"><code className="text-pink-600 font-semibold">{r.ratio}</code></td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.s512}</td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.k1}</td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.k2}</td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.k4}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </SectionCard>
        <SectionCard
          id="seedream-sizes"
          title="Seedream 支持尺寸"
          description='doubao-seedream 为国内模型名称，seedream 为海外模型名称。size 参数传入 WxH 精确分辨率（如 "2048x2048"），需与下表中的尺寸匹配。'
        >
          <div className="space-y-6">
            {/* Seedream 5.0 lite */}
            <div>
              <h4 className="text-sm font-semibold text-slate-700 mb-2">Seedream 5.0 lite</h4>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="px-3 py-2 font-semibold text-slate-600 w-16">比例</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">1K</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">2K</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">3K</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">4K</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 text-xs">
                    {[
                      { ratio: '1:1',  k1: '—', k2: '2048x2048', k3: '3072x3072', k4: '—' },
                      { ratio: '3:4',  k1: '—', k2: '1728x2304', k3: '2592x3456', k4: '—' },
                      { ratio: '4:3',  k1: '—', k2: '2304x1728', k3: '3456x2592', k4: '—' },
                      { ratio: '16:9', k1: '—', k2: '2848x1600', k3: '4096x2304', k4: '—' },
                      { ratio: '9:16', k1: '—', k2: '1600x2848', k3: '2304x4096', k4: '—' },
                      { ratio: '3:2',  k1: '—', k2: '2496x1664', k3: '2496x3744', k4: '—' },
                      { ratio: '2:3',  k1: '—', k2: '1664x2496', k3: '3744x2496', k4: '—' },
                      { ratio: '21:9', k1: '—', k2: '3136x1344', k3: '4704x2016', k4: '—' },
                    ].map((r) => (
                      <tr key={r.ratio} className="hover:bg-slate-50">
                        <td className="px-3 py-1.5"><code className="text-pink-600 font-semibold">{r.ratio}</code></td>
                        <td className="px-3 py-1.5 text-slate-400">{r.k1}</td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.k2}</td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.k3}</td>
                        <td className="px-3 py-1.5 text-slate-400">{r.k4}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Seedream 4.5 */}
            <div>
              <h4 className="text-sm font-semibold text-slate-700 mb-2">Seedream 4.5</h4>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="px-3 py-2 font-semibold text-slate-600 w-16">比例</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">1K</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">2K</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">3K</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">4K</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 text-xs">
                    {[
                      { ratio: '1:1',  k1: '—', k2: '2048x2048', k3: '—', k4: '4096x4096' },
                      { ratio: '3:4',  k1: '—', k2: '1728x2304', k3: '—', k4: '3520x4704' },
                      { ratio: '4:3',  k1: '—', k2: '2304x1728', k3: '—', k4: '4704x3520' },
                      { ratio: '16:9', k1: '—', k2: '2848x1600', k3: '—', k4: '5504x3040' },
                      { ratio: '9:16', k1: '—', k2: '1600x2848', k3: '—', k4: '3040x5504' },
                      { ratio: '3:2',  k1: '—', k2: '2496x1664', k3: '—', k4: '3328x4992' },
                      { ratio: '2:3',  k1: '—', k2: '1664x2496', k3: '—', k4: '4992x3328' },
                      { ratio: '21:9', k1: '—', k2: '3136x1344', k3: '—', k4: '6240x2656' },
                    ].map((r) => (
                      <tr key={r.ratio} className="hover:bg-slate-50">
                        <td className="px-3 py-1.5"><code className="text-pink-600 font-semibold">{r.ratio}</code></td>
                        <td className="px-3 py-1.5 text-slate-400">{r.k1}</td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.k2}</td>
                        <td className="px-3 py-1.5 text-slate-400">{r.k3}</td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.k4}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Seedream 4.0 */}
            <div>
              <h4 className="text-sm font-semibold text-slate-700 mb-2">Seedream 4.0</h4>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left">
                    <tr>
                      <th className="px-3 py-2 font-semibold text-slate-600 w-16">比例</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">1K</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">2K</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">3K</th>
                      <th className="px-3 py-2 font-semibold text-slate-600">4K</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 text-xs">
                    {[
                      { ratio: '1:1',  k1: '1024x1024', k2: '2048x2048', k3: '—', k4: '4096x4096' },
                      { ratio: '3:4',  k1: '864x1152',  k2: '1728x2304', k3: '—', k4: '3520x4704' },
                      { ratio: '4:3',  k1: '1152x864',  k2: '2304x1728', k3: '—', k4: '4704x3520' },
                      { ratio: '16:9', k1: '1312x736',  k2: '2848x1600', k3: '—', k4: '5504x3040' },
                      { ratio: '9:16', k1: '736x1312',  k2: '1600x2848', k3: '—', k4: '3040x5504' },
                      { ratio: '2:3',  k1: '832x1248',  k2: '2496x1664', k3: '—', k4: '3328x4992' },
                      { ratio: '3:2',  k1: '1248x832',  k2: '1664x2496', k3: '—', k4: '4992x3328' },
                      { ratio: '21:9', k1: '1568x672',  k2: '3136x1344', k3: '—', k4: '6240x2656' },
                    ].map((r) => (
                      <tr key={r.ratio} className="hover:bg-slate-50">
                        <td className="px-3 py-1.5"><code className="text-pink-600 font-semibold">{r.ratio}</code></td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.k1}</td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.k2}</td>
                        <td className="px-3 py-1.5 text-slate-400">{r.k3}</td>
                        <td className="px-3 py-1.5 font-mono text-slate-600">{r.k4}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-800 mt-2">
            <strong>提示：</strong>Seedream 的 size 参数仅支持 WxH 精确分辨率格式（如 <code>"2048x2048"</code>），需与上表中的尺寸匹配。
          </div>
        </SectionCard>

        <SectionCard
          id="z-image-sizes"
          title="Z-Image Turbo 支持尺寸"
          description="百炼 Z-Image Turbo 模型使用 aspect_ratio（宽高比）+ 分辨率档位（1K / 1.5K / 2K）来确定输出图片尺寸。仅支持文本输入。"
        >
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left">
                <tr>
                  <th className="px-3 py-2 font-semibold text-slate-600 w-16">比例</th>
                  <th className="px-3 py-2 font-semibold text-slate-600">1K</th>
                  <th className="px-3 py-2 font-semibold text-slate-600">1.5K</th>
                  <th className="px-3 py-2 font-semibold text-slate-600">2K</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-xs">
                {[
                  { ratio: '1:1',  k1: '1024x1024',  k15: '1280x1280',  k2: '1536x1536' },
                  { ratio: '2:3',  k1: '832x1248',   k15: '1024x1536',  k2: '1248x1872' },
                  { ratio: '3:2',  k1: '1248x832',   k15: '1536x1024',  k2: '1872x1248' },
                  { ratio: '3:4',  k1: '864x1152',   k15: '1104x1472',  k2: '1296x1728' },
                  { ratio: '4:3',  k1: '1152x864',   k15: '1472x1104',  k2: '1728x1296' },
                  { ratio: '7:9',  k1: '896x1152',   k15: '1120x1440',  k2: '1344x1728' },
                  { ratio: '9:7',  k1: '1152x896',   k15: '1440x1120',  k2: '1728x1344' },
                  { ratio: '9:16', k1: '720x1280',   k15: '864x1536',   k2: '1152x2048' },
                  { ratio: '9:21', k1: '576x1344',   k15: '720x1680',   k2: '864x2016' },
                  { ratio: '16:9', k1: '1280x720',   k15: '1536x864',   k2: '2048x1152' },
                  { ratio: '21:9', k1: '1344x576',   k15: '1680x720',   k2: '2016x864' },
                ].map((r) => (
                  <tr key={r.ratio} className="hover:bg-slate-50">
                    <td className="px-3 py-1.5"><code className="text-pink-600 font-semibold">{r.ratio}</code></td>
                    <td className="px-3 py-1.5 font-mono text-slate-600">{r.k1}</td>
                    <td className="px-3 py-1.5 font-mono text-slate-600">{r.k15}</td>
                    <td className="px-3 py-1.5 font-mono text-slate-600">{r.k2}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-800 mt-2">
            <strong>提示：</strong>Z-Image Turbo 的 size 参数使用 WxH 精确分辨率格式（如 <code>"1024*1024"</code>），需与上表中的尺寸匹配。也可通过 aspect_ratio 参数指定宽高比，系统自动匹配对应分辨率：
            <ul className="mt-1 space-y-0.5 list-disc list-inside text-blue-700">
              <li>size 精确分辨率：<code>size: "1024*1024"</code> → 直接使用</li>
              <li>仅 aspect_ratio：<code>aspect_ratio: "1:1"</code> → 默认 1K档 1024x1024</li>
              <li>size 档位 + aspect_ratio：<code>size: "2K"</code> + <code>aspect_ratio: "16:9"</code> → 自动匹配 2048x1152</li>
            </ul>
          </div>
        </SectionCard>

      </div>

      <TableOfContents items={TOC_ITEMS} accentColor="cyan" />
    </div>
  );
}
