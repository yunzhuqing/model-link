import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Copy, Check, ArrowLeft, Box } from 'lucide-react';
import { useBaseUrl } from '../components/help/HelpShared';

interface TocItem { id: string; label: string; indent?: boolean }
const TOC_ITEMS: TocItem[] = [
  { id: 'overview', label: '功能说明' },
  { id: 'models', label: '支持的模型' },
  { id: 'hunyuan3d', label: '混元 3D' },
  { id: 'single-image', label: '　└ 单图生成', indent: true },
  { id: 'multi-view', label: '　└ 多视角图生成', indent: true },
  { id: 'text-to-3d', label: '　└ 文本生成 3D', indent: true },
  { id: 'part', label: '　└ 3D 部件分割', indent: true },
  { id: 'reduce-face', label: '　└ 3D 减面', indent: true },
  { id: 'seed3d', label: 'Doubao Seed3D' },
  { id: 'seed3d-usage', label: '　└ 请求示例', indent: true },
  { id: 'params', label: '工具参数' },
  { id: 'response-format', label: '响应格式' },
  { id: 'response-single', label: '　├ 单个输出项', indent: true },
  { id: 'response-multi', label: '　└ 多个输出项', indent: true },
];

const THREED_SINGLE = `{
  "model": "hunyuan-3d-3.1-pro",
  "background": true,
  "input": [
    {
      "role": "user",
      "type": "message",
      "content": [
        {
          "type": "input_image",
          "image_url": "https://example.com/dog.jpg"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "3d_generation",
      "output_format": "GLB",
      "pbr": true,
      "face_count": 500000,
      "generate_type": "Normal"
    }
  ]
}`;

const THREED_MULTI_VIEW = `{
  "model": "hunyuan-3d-3.1-pro",
  "background": true,
  "input": [
    {
      "role": "user",
      "type": "message",
      "content": [
        {
          "type": "input_image",
          "image_url": "https://example.com/front.jpg"
        },
        {
          "type": "input_image",
          "image_url": "https://example.com/back.jpg",
          "view": "back"
        },
        {
          "type": "input_image",
          "image_url": "https://example.com/left.jpg",
          "view": "left"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "3d_generation",
      "output_format": "GLB",
      "pbr": true,
      "face_count": 500000,
      "generate_type": "Normal"
    }
  ]
}`;

const SEED3D_REQUEST = `{
  "model": "doubao-seed3d-2.0",
  "background": true,
  "input": [
    {
      "role": "user",
      "type": "message",
      "content": [
        {
          "type": "input_image",
          "image_url": "https://ark-project.tos-cn-beijing.volces.com/doc_image/seed3d_imageTo3d.png"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "3d_generation",
      "face_count": 100000
    }
  ]
}`;

const THREED_TEXT = `{
  "model": "hunyuan-3d-3.1-pro",
  "background": true,
  "input": [
    {
      "role": "user",
      "type": "message",
      "content": [
        {
          "type": "input_text",
          "text": "一只可爱的柴犬玩具"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "3d_generation",
      "output_format": "GLB",
      "generate_type": "Sketch"
    }
  ]
}`;

const THREED_PART = `{
  "model": "hunyuan-3d-1.5-part",
  "background": true,
  "input": [
    {
      "role": "user",
      "type": "message",
      "content": [
        {
          "type": "input_file",
          "file_url": "https://example.com/model.fbx"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "3d_generation"
    }
  ]
}`;

const THREED_REDUCE_FACE = `{
  "model": "hunyuan-3d-reduce-face",
  "background": true,
  "input": [
    {
      "role": "user",
      "type": "message",
      "content": [
        {
          "type": "input_file",
          "file_url": "https://example.com/model.glb"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "3d_generation"
    }
  ]
}`;

const THREED_REDUCE_FACE_RESPONSE = `{
  "id": "resp_d83ac94428a533da6c9262ec0e29eaeade34eb290b90160b",
  "object": "response",
  "status": "completed",
  "model": "hunyuan-3d-reduce-face",
  "output": [
    {
      "type": "3d_generation_call",
      "id": "1456843823107260416",
      "status": "completed",
      "content": [
        {
          "type": "OBJ",
          "url": "https://...output.obj",
          "preview_url": ""
        }
      ]
    },
    {
      "type": "3d_generation_call",
      "id": "1456843823107260416-1",
      "status": "completed",
      "content": [
        {
          "type": "GLB",
          "url": "https://...output.glb",
          "preview_url": ""
        }
      ]
    },
    {
      "type": "3d_generation_call",
      "id": "1456843823107260416-2",
      "status": "completed",
      "content": [
        {
          "type": "IMAGE",
          "url": "https://...output.png",
          "preview_url": ""
        }
      ]
    }
  ],
  "usage": {
    "input_tokens": 0,
    "output_tokens": 3,
    "total_tokens": 3
  }
}`;

const THREED_RESPONSE = `{
  "id": "3d_abc123...",
  "object": "response",
  "status": "completed",
  "model": "hunyuan-3d-3.1-pro",
  "output": [
    {
      "type": "3d_generation_call",
      "id": "job_xxx",
      "status": "completed",
      "content": [
        {
          "type": "GLB",
          "url": "https://...",
          "preview_url": "https://..."
        }
      ]
    }
  ]
}`;

const THREED_PART_RESPONSE = `{
  "id": "resp_f07e518e6118f27ffd8a88fc673021e41e584f752d12b201",
  "object": "response",
  "status": "completed",
  "model": "hunyuan-3d-1.5-part",
  "output": [
    {
      "type": "3d_generation_call",
      "id": "1452645336451072000",
      "status": "completed",
      "content": [
        {
          "type": "GLB",
          "url": "https://.../part_0.glb",
          "preview_url": ""
        }
      ]
    },
    {
      "type": "3d_generation_call",
      "id": "1452645336451072000-1",
      "status": "completed",
      "content": [
        {
          "type": "GLB",
          "url": "https://.../part_1.glb",
          "preview_url": ""
        }
      ]
    }
    // ... 更多部件（part_2 ~ part_N）
  ],
  "usage": {
    "input_tokens": 0,
    "output_tokens": 9,
    "total_tokens": 9
  }
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
  const baseUrl = useBaseUrl();
  const [show, setShow] = useState(false);
  const curl = `curl -X POST ${baseUrl}/v1/responses \\\n  -H "Authorization: Bearer <YOUR_API_KEY>" \\\n  -H "Content-Type: application/json" \\\n  -d '${body}'`;
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
                  ? 'bg-purple-50 text-purple-600 font-medium border-l-2 border-purple-500'
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

export default function HelpThreed() {
  const navigate = useNavigate();
  const baseUrl = useBaseUrl();

  return (
    <div className="flex gap-8 max-w-6xl mx-auto">
      <div className="flex-1 min-w-0 space-y-8">
        {/* Back + header */}
        <div>
          <button
            onClick={() => navigate('/help')}
            className="flex items-center gap-1.5 text-sm text-slate-500 hover:text-purple-600 mb-4 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            返回帮助中心
          </button>
          <div className="flex items-center gap-4">
            <div className="p-3 bg-gradient-to-br from-purple-500 to-violet-600 rounded-2xl shadow-lg shadow-purple-500/25">
              <Box className="w-7 h-7 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900">3D 生成</h1>
              <p className="text-slate-500 text-sm mt-0.5">通过 Responses API 的 3d_generation 工具生成 3D 模型（混元 3D / Doubao Seed3D）</p>
            </div>
          </div>
        </div>

        {/* Endpoint info */}
        <div className="bg-purple-50 border border-purple-100 rounded-xl p-4 flex flex-wrap gap-4 items-center">
          <div>
            <span className="text-xs font-semibold text-purple-500 uppercase tracking-wide">Endpoint</span>
            <p className="font-mono text-sm text-purple-900 mt-0.5">{baseUrl}/v1/responses</p>
          </div>
          <div className="h-8 w-px bg-purple-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-purple-500 uppercase tracking-wide">Tool Type</span>
            <p className="font-mono text-sm text-purple-900 mt-0.5">3d_generation</p>
          </div>
          <div className="h-8 w-px bg-purple-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-purple-500 uppercase tracking-wide">必须</span>
            <p className="font-mono text-sm text-purple-900 mt-0.5">background: true</p>
          </div>
        </div>

        {/* Overview */}
        <div id="overview" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <h3 className="text-lg font-semibold text-slate-800 mb-1">功能说明</h3>
            <p className="text-sm text-slate-500">
              通过在 tools 中指定 3d_generation 类型，触发 3D 模型生成功能。支持混元 3D（单图、多视角、文本、3D 文件部件分割、3D 减面）和 Doubao Seed3D（单图）模型，生成 3D 模型文件（OBJ、GLB、STL、USDZ、FBX、MP4）。
            </p>
          </div>
          <div className="p-6 space-y-3">
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">
              <strong>重要：</strong>3D 生成为异步长时任务，<strong>必须设置 <code>background: true</code></strong>。
              提交后立即返回 <code>response_id</code>，通过 <code>GET /v1/responses/{'{response_id}'}</code> 轮询结果。
            </div>
            <div className="bg-purple-50 border border-purple-200 rounded-lg p-3 text-sm text-purple-800">
              <strong>Provider 配置：</strong>混元 3D 选择类型 <code>Hunyuan 3D (Tencent)</code>，填写腾讯云 Secret ID（AK）、Secret Key（SK）及 Region。Doubao Seed3D 选择类型 <code>Volcengine ARK</code>，配置对应的 API Key 和 Base URL。
            </div>
          </div>
        </div>

        {/* Models */}
        <SectionCard
          id="models"
          title="支持的模型"
          description="支持混元 3D（Rapid / Pro / Part / ReduceFace 系列）和 Doubao Seed3D 模型。"
        >
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left">
                <tr>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">模型名称</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">供应商</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">输入方式</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">说明</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {[
                  { name: 'hunyuan-3d-rapid',   vendor: '混元', input: '单图', desc: 'Rapid 系列（快速生成）' },
                  { name: 'hy-3d-express',       vendor: '混元', input: '单图', desc: 'Rapid 系列（快速生成）' },
                  { name: 'hunyuan-3d-pro',      vendor: '混元', input: '单图/多视角/文本', desc: 'Pro 系列（兼容旧版）' },
                  { name: 'hunyuan-3d-3.0-pro',  vendor: '混元', input: '单图/多视角/文本', desc: 'Pro 3.0 版本' },
                  { name: 'hunyuan-3d-3.1-pro',  vendor: '混元', input: '单图/多视角/文本', desc: 'Pro 3.1 版本（推荐）' },
                  { name: 'hunyuan-3d-1.5-part', vendor: '混元', input: '3D 文件（FBX）', desc: 'Part 1.5 部件分割' },
                  { name: 'hunyuan-3d-reduce-face', vendor: '混元', input: '3D 文件（GLB/OBJ）', desc: 'ReduceFace 减面模型' },
                  { name: 'hy-3d-3.0',           vendor: '混元', input: '单图/多视角/文本', desc: 'Pro 系列（别名映射差异）' },
                  { name: 'hy-3d-3.1',           vendor: '混元', input: '单图/多视角/文本', desc: 'Pro 系列（别名映射差异）' },
                  { name: 'doubao-seed3d-2.0',   vendor: 'Doubao', input: '单图（必填）', desc: 'Doubao Seed3D 2.0，仅支持图生 3D' },
                ].map((r) => (
                  <tr key={r.name} className="hover:bg-slate-50">
                    <td className="px-4 py-2.5"><code className="text-purple-600 font-semibold text-xs">{r.name}</code></td>
                    <td className="px-4 py-2.5">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${r.vendor === '混元' ? 'bg-purple-100 text-purple-700' : 'bg-cyan-100 text-cyan-700'}`}>
                        {r.vendor}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-slate-600 text-xs">{r.input}</td>
                    <td className="px-4 py-2.5 text-slate-600 text-xs">{r.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>

        {/* ======== Hunyuan 3D ======== */}
        <div id="hunyuan3d" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <div className="flex items-center gap-3 mb-1">
              <h3 className="text-lg font-semibold text-slate-800">混元 3D 模型</h3>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-700">Hunyuan</span>
            </div>
            <p className="text-sm text-slate-500">腾讯混元 3D 模型，支持单图、多视角图片、文本描述和 3D 文件（部件分割、减面）等多种输入方式生成或处理 3D 模型。</p>
          </div>
          <div className="p-6 space-y-6">
            {/* Single image */}
        <SectionCard
          id="single-image"
          title="单图生成 3D（Rapid / Pro）"
          badge="ImageUrl"
          badgeColor="bg-purple-100 text-purple-700"
          description="传入一张图片（无 view 字段），生成对应 3D 模型。Rapid 和 Pro 模型均支持。"
        >
          <CurlSection body={THREED_SINGLE} />
        </SectionCard>

        {/* Multi-view */}
        <SectionCard
          id="multi-view"
          title="多视角图片生成 3D（Pro 专用）"
          badge="MultiViewImages"
          badgeColor="bg-indigo-100 text-indigo-700"
          description="在 input_image 块中添加 view 字段指定视角，质量更高。主图（无 view）同时设置为 ImageUrl，带 view 的图作为 MultiViewImages。"
        >
          <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-sm text-slate-700">
            <strong>视角枚举值（view 字段）：</strong>
            <div className="flex flex-wrap gap-1.5 mt-2">
              {['front', 'back', 'left', 'right', 'up', 'down', 'left_front', 'right_front'].map((v) => (
                <code key={v} className="bg-white border border-slate-200 px-2 py-0.5 rounded text-xs text-purple-600">{v}</code>
              ))}
            </div>
          </div>
          <CurlSection body={THREED_MULTI_VIEW} />
        </SectionCard>

        {/* Text to 3D */}
        <SectionCard
          id="text-to-3d"
          title="文本生成 3D（Pro 专用）"
          badge="Prompt"
          badgeColor="bg-teal-100 text-teal-700"
          description="当不传入图片时，使用文本描述生成 3D 模型。generate_type: Sketch 模式下 prompt 和图片可同时传入。"
        >
          <CurlSection body={THREED_TEXT} />
        </SectionCard>

        {/* Part — 3D file segmentation */}
        <SectionCard
          id="part"
          title="3D 部件分割（hunyuan-3d-1.5-part）"
          badge="input_file"
          badgeColor="bg-orange-100 text-orange-700"
          description="传入一个 3D 文件（如 FBX），自动分割为独立部件并输出分离后的模型文件。"
        >
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">
            <strong>约束：</strong>
            <ul className="list-disc list-inside mt-1.5 space-y-1">
              <li>输入 <code>input_file</code> <strong>必填</strong>，<code>file_url</code> 指向 3D 文件地址</li>
              <li>支持的文件格式：FBX、OBJ、GLB 等 3D 文件格式</li>
              <li>返回分离后的部件模型文件（OBJ、FBX）和预览图（IMAGE）</li>
              <li>需设置 <code>"background": true</code> 进行异步任务</li>
            </ul>
          </div>
          <CurlSection body={THREED_PART} />
        </SectionCard>

        {/* ReduceFace — 3D face reduction */}
        <SectionCard
          id="reduce-face"
          title="3D 减面（hunyuan-3d-reduce-face）"
          badge="input_file"
          badgeColor="bg-green-100 text-green-700"
          description="传入一个 3D 文件（GLB、OBJ 等），自动进行减面优化，输出简化后的模型文件。"
        >
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">
            <strong>约束：</strong>
            <ul className="list-disc list-inside mt-1.5 space-y-1">
              <li>输入 <code>input_file</code> <strong>必填</strong>，<code>file_url</code> 指向 3D 文件地址</li>
              <li>支持的文件格式：GLB、OBJ 等 3D 文件格式</li>
              <li>返回减面后的模型文件（OBJ、GLB）和预览图（IMAGE）</li>
              <li>需设置 <code>"background": true</code> 进行异步任务</li>
            </ul>
          </div>
          <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-sm text-slate-700">
            <strong>可选参数：</strong>
            <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2">
              {[
                { name: 'face_level', type: 'string', values: '"high" | "medium" | "low"', desc: '面数级别，控制减面后的面数' },
                { name: 'polygon_type', type: 'string', values: '"triangle" | "quadrilateral"', desc: '多边形类型' },
              ].map((p) => (
                <div key={p.name} className="flex items-center gap-1.5">
                  <code className="text-purple-600 font-semibold text-xs">{p.name}</code>
                  <span className="text-slate-400 text-xs">{p.values}</span>
                  <span className="text-slate-500 text-xs ml-1">{p.desc}</span>
                </div>
              ))}
            </div>
          </div>
          <CurlSection body={THREED_REDUCE_FACE} />
        </SectionCard>
          </div>
        </div>

        {/* ======== Doubao Seed3D ======== */}
        <SectionCard
          id="seed3d"
          title="Doubao Seed3D 模型"
          badge="Seed3D"
          badgeColor="bg-cyan-100 text-cyan-700"
          description="Doubao Seed3D 2.0 是火山引擎提供的图生 3D 模型，仅需一张图片即可生成高质量 3D 模型。"
        >
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">
            <strong>约束：</strong>
            <ul className="list-disc list-inside mt-1.5 space-y-1">
              <li>输入 <code>input_image</code> <strong>必填</strong>，支持 <code>image_url</code>（URL）和 <code>image_base64</code>（base64 编码）两种输入方式</li>
              <li>支持 <code>face_count</code> 参数控制生成面数</li>
              <li>支持 <code>output_format</code> 指定输出格式</li>
              <li>需设置 <code>"background": true</code> 进行异步任务</li>
            </ul>
          </div>
          <div id="seed3d-usage" className="scroll-mt-4">
            <CurlSection body={SEED3D_REQUEST} />
          </div>
        </SectionCard>

        {/* Params */}
        <SectionCard
          id="params"
          title="工具参数（3d_generation tool）"
          description="3d_generation tool 支持以下参数。Pro-only 参数仅对 Pro 系列模型生效。"
        >
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left">
                <tr>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">参数</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">类型</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">适用</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">说明</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {[
                  { name: 'type',             type: 'string',  scope: '通用',     desc: '固定为 "3d_generation"' },
                  { name: 'output_format',    type: 'string',  scope: '通用',     desc: 'OBJ | GLB | STL | USDZ | FBX | MP4；别名：result_format' },
                  { name: 'pbr',              type: 'boolean', scope: '通用',     desc: '是否开启 PBR 材质生成；别名：enable_pbr' },
                  { name: 'enable_geometry',  type: 'boolean', scope: '通用',     desc: '开启白模（无纹理几何）生成，开启后不支持 OBJ 格式；别名：geometry' },
                  { name: 'face_count',       type: 'number',  scope: 'Pro/Seed3D', desc: '生成面数（混元 Pro: 3000–1500000；Seed3D 也支持）' },
                  { name: 'generate_type',    type: 'string',  scope: 'Pro-only', desc: 'Normal | LowPoly | Geometry | Sketch' },
                  { name: 'polygon_type',     type: 'string',  scope: 'Pro/ReduceFace', desc: 'triangle | quadrilateral（Pro LowPoly / ReduceFace）' },
                  { name: 'face_level',       type: 'string',  scope: 'ReduceFace-only', desc: 'high | medium | low，控制减面后的面数' },
                ].map((r) => (
                  <tr key={r.name} className="hover:bg-slate-50">
                    <td className="px-4 py-2.5"><code className="text-purple-600 font-semibold">{r.name}</code></td>
                    <td className="px-4 py-2.5 text-slate-500 font-mono text-xs">{r.type}</td>
                    <td className="px-4 py-2.5">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${r.scope === '通用' ? 'bg-slate-100 text-slate-600' : 'bg-purple-100 text-purple-700'}`}>
                        {r.scope}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-slate-600">{r.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-sm text-slate-700">
            <strong>多视角图片传入方式：</strong>多视角图片不在 tool 参数中传入，而是在 <code>input</code> 的 <code>input_image</code> 内容块中添加 <code>view</code> 字段指定视角：
            <ul className="list-disc list-inside mt-1.5 space-y-1 text-slate-600">
              <li>无 <code>view</code> 字段的 input_image → <code>ImageUrl</code>（主图）</li>
              <li>有 <code>view</code> 字段的 input_image → <code>MultiViewImages</code>（仅 Pro 模型）</li>
            </ul>
          </div>
        </SectionCard>

        {/* Response format */}
        <div id="response-format" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <h3 className="text-lg font-semibold text-slate-800">响应格式</h3>
            <p className="text-sm text-slate-500 mt-1">3D 生成任务为异步执行，提交后需通过 GET 轮询获取结果。output 为 3d_generation_call 类型的输出项数组，Rapid / Pro 模型通常返回 1 项，部件分割、减面等多结果场景返回多项。content 数组中每项含 type（文件格式）和 url（下载地址）。</p>
          </div>
          <div className="p-6 space-y-6">
            <div>
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">轮询查询</span>
              <CodeBlock code={`GET ${baseUrl}/v1/responses/{response_id}\nAuthorization: Bearer <YOUR_API_KEY>`} lang="bash" />
            </div>

            {/* Single output item */}
            <div id="response-single" className="scroll-mt-4">
              <p className="text-sm font-semibold text-slate-700 mb-2">单个输出项（hunyuan-3d / Seed3D / hunyuan-3d-1.5-part 都适用）</p>
              <p className="text-sm text-slate-500 mb-3">output 包含 1 个 3d_generation_call 项，content 为生成的 3D 文件列表，每项含 type（GLB / OBJ / FBX 等）和 url。</p>
              <CodeBlock code={THREED_RESPONSE} />
            </div>

            {/* Multiple output items */}
            <div id="response-multi" className="scroll-mt-4">
              <p className="text-sm font-semibold text-slate-700 mb-2">多个输出项（hunyuan-3d-1.5-part 部件分割 / hunyuan-3d-reduce-face 减面等场景）</p>
              <p className="text-sm text-slate-500 mb-3">output 包含多个 3d_generation_call 项，每个 item 对应一个独立输出（如分割后的各个 3D 部件或减面后的不同格式文件），各自有独立的 content 数组。</p>
              <CodeBlock code={THREED_PART_RESPONSE} />
            </div>
          </div>
        </div>
      </div>

      <TableOfContents items={TOC_ITEMS} />
    </div>
  );
}
