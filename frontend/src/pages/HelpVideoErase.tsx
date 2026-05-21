import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Copy, Check, ArrowLeft, Eraser } from 'lucide-react';
import { useBaseUrl } from '../components/help/HelpShared';

interface TocItem { id: string; label: string; indent?: boolean }
const TOC_ITEMS: TocItem[] = [
  { id: 'overview', label: '功能说明' },
  { id: 'models', label: '支持的模型' },
  { id: 'subtitle-erase', label: '字幕擦除' },
  { id: 'bg-response', label: '　└ 后台异步轮询', indent: true },
  { id: 'params', label: '工具参数' },
  { id: 'response-format', label: '响应格式' },
];

const SUBTITLE_ERASE_REQUEST = `{
  "model": "mps-smarterase",
  "background": true,
  "input": [
    {
      "role": "user",
      "type": "message",
      "content": [
        {
          "type": "input_video",
          "video_url": "https://example.cos.ap-guangzhou.myqcloud.com/video.mp4"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "video_erase",
      "erase_type": "subtitle"
    }
  ]
}`;

const BG_RESPONSE = `{
  "background": true,
  "created_at": 1779368629,
  "id": "resp_50ec8446f705609fb7ac9d1ce73be6a419eb52c7fd890c81",
  "model": "mps-smarterase",
  "object": "response",
  "status": "in_progress"
}`;

const QUERY_RESPONSE = `{
  "created_at": 1779368679,
  "id": "vid_b3a54794a6661e1ce995aa495a660099674a9cc271dd177d",
  "model": "mps-smarterase",
  "object": "response",
  "output": [
    {
      "id": "vid_b3a54794a6661e1ce995aa495a660099674a9cc271dd177d",
      "result": "https://cos.ap-shanghai.myqcloud.com/.../erase_test_1.mp4?...",
      "status": "completed",
      "type": "video_erase_call"
    }
  ],
  "status": "completed",
  "usage": {
    "input_tokens": 0,
    "output_tokens": 1,
    "total_tokens": 1
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
    if (el && scrollRef.current) {
      scrollRef.current.scrollTo({ top: el.offsetTop - 80, behavior: 'smooth' });
    }
  };

  return (
    <aside className="hidden lg:block w-52 flex-shrink-0">
      <div className="sticky top-8">
        <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">页面导航</h4>
        <nav className="space-y-0.5">
          {items.map((item) => (
            <button
              key={item.id}
              onClick={() => scrollTo(item.id)}
              className={`w-full text-left px-3 py-1.5 rounded-lg text-sm transition-all duration-150 ${
                active === item.id
                  ? 'bg-orange-50 text-orange-600 font-medium border-l-2 border-orange-500'
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

export default function HelpVideoErase() {
  const navigate = useNavigate();
  const baseUrl = useBaseUrl();

  return (
    <div className="flex gap-8 max-w-6xl mx-auto">
      <div className="flex-1 min-w-0 space-y-8">
        {/* Back + header */}
        <div>
          <button
            onClick={() => navigate('/help')}
            className="flex items-center gap-1.5 text-sm text-slate-500 hover:text-orange-600 mb-4 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            返回帮助中心
          </button>
          <div className="flex items-center gap-4">
            <div className="p-3 bg-gradient-to-br from-orange-500 to-amber-600 rounded-2xl shadow-lg shadow-orange-500/25">
              <Eraser className="w-7 h-7 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900">视频智能擦除</h1>
              <p className="text-slate-500 text-sm mt-0.5">通过 Responses API 的 video_erase 工具智能擦除视频字幕/水印（腾讯云 MPS）</p>
            </div>
          </div>
        </div>

        {/* Endpoint info */}
        <div className="bg-orange-50 border border-orange-100 rounded-xl p-4 flex flex-wrap gap-4 items-center">
          <div>
            <span className="text-xs font-semibold text-orange-500 uppercase tracking-wide">Endpoint</span>
            <p className="font-mono text-sm text-orange-900 mt-0.5">{baseUrl}/v1/responses</p>
          </div>
          <div className="h-8 w-px bg-orange-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-orange-500 uppercase tracking-wide">Tool Type</span>
            <p className="font-mono text-sm text-orange-900 mt-0.5">video_erase</p>
          </div>
          <div className="h-8 w-px bg-orange-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-orange-500 uppercase tracking-wide">必须</span>
            <p className="font-mono text-sm text-orange-900 mt-0.5">background: true</p>
          </div>
        </div>

        {/* Overview */}
        <div id="overview" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <h3 className="text-lg font-semibold text-slate-800 mb-1">功能说明</h3>
            <p className="text-sm text-slate-500">
              通过在 tools 中指定 video_erase 类型，触发视频智能擦除功能。基于腾讯云 MPS SmartErase 能力，支持自动识别并擦除视频中的字幕、水印等。
            </p>
          </div>
          <div className="p-6 space-y-3">
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">
              <strong>重要：</strong>视频智能擦除为异步长时任务，<strong>必须设置 <code>background: true</code></strong>。
              提交后立即返回 <code>response_id</code>，通过 <code>GET /v1/responses/{'{response_id}'}</code> 轮询结果。
            </div>
            <div className="bg-orange-50 border border-orange-200 rounded-lg p-3 text-sm text-orange-800">
              <strong>Provider 配置：</strong>选择类型 <code>MPS Smart Erase (Tencent)</code>，填写腾讯云 Secret ID（AK）、Secret Key（SK）。
            </div>
          </div>
        </div>

        {/* Supported Models */}
        <SectionCard id="models" title="支持的模型" description="当前支持的 MPS 智能擦除模型">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200">
                  <th className="text-left font-semibold text-slate-600 py-2 px-3">模型</th>
                  <th className="text-left font-semibold text-slate-600 py-2 px-3">擦除类型</th>
                  <th className="text-left font-semibold text-slate-600 py-2 px-3">说明</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                <tr>
                  <td className="py-2 px-3 font-mono text-sm text-slate-800">mps-smarterase</td>
                  <td className="py-2 px-3"><span className="px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700">字幕 / 水印</span></td>
                  <td className="py-2 px-3 text-slate-500">MPS 通用智能擦除</td>
                </tr>
                <tr>
                  <td className="py-2 px-3 font-mono text-sm text-slate-800">mps-erase-subtitle-standard</td>
                  <td className="py-2 px-3"><span className="px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700">字幕</span></td>
                  <td className="py-2 px-3 text-slate-500">标准字幕擦除</td>
                </tr>
              </tbody>
            </table>
          </div>
        </SectionCard>

        {/* Subtitle Erase */}
        <SectionCard id="subtitle-erase" title="字幕擦除" description="使用 mps-smarterase 模型智能擦除视频中的字幕">
          <CurlSection body={SUBTITLE_ERASE_REQUEST} />
        </SectionCard>

        {/* Background Response */}
        <SectionCard
          id="bg-response"
          title="后台异步轮询"
          description="提交任务后立即返回 in_progress 状态，通过 response_id 轮询获取结果"
          badge="background"
          badgeColor="bg-amber-100 text-amber-700"
        >
          <div>
            <p className="text-sm text-slate-600 mb-3">提交任务后立即返回，<code>status</code> 为 <code>in_progress</code>：</p>
            <CodeBlock code={BG_RESPONSE} />
          </div>
          <div>
            <p className="text-sm text-slate-600 mb-3">
              通过 <code className="text-orange-600 bg-orange-50 px-1 rounded">GET {baseUrl}/v1/responses/{'{response_id}'}</code> 查询最终结果，
              <code>status</code> 变为 <code>completed</code>，<code>output[].result</code> 为擦除后视频的下载 URL：
            </p>
            <CodeBlock code={QUERY_RESPONSE} />
          </div>
        </SectionCard>

        {/* Params */}
        <SectionCard id="params" title="工具参数" description="video_erase 工具支持的参数">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200">
                  <th className="text-left font-semibold text-slate-600 py-2 px-3">参数</th>
                  <th className="text-left font-semibold text-slate-600 py-2 px-3">类型</th>
                  <th className="text-left font-semibold text-slate-600 py-2 px-3">必填</th>
                  <th className="text-left font-semibold text-slate-600 py-2 px-3">说明</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                <tr>
                  <td className="py-2 px-3 font-mono text-sm">type</td>
                  <td className="py-2 px-3 text-slate-500">string</td>
                  <td className="py-2 px-3"><span className="px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700">是</span></td>
                  <td className="py-2 px-3 text-slate-500">固定为 <code>video_erase</code></td>
                </tr>
                <tr>
                  <td className="py-2 px-3 font-mono text-sm">erase_type</td>
                  <td className="py-2 px-3 text-slate-500">string</td>
                  <td className="py-2 px-3"><span className="px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700">是</span></td>
                  <td className="py-2 px-3 text-slate-500">擦除类型：<code>subtitle</code>（字幕）</td>
                </tr>
                <tr>
                  <td className="py-2 px-3 font-mono text-sm">erase_method</td>
                  <td className="py-2 px-3 text-slate-500">string</td>
                  <td className="py-2 px-3"><span className="px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-500">否</span></td>
                  <td className="py-2 px-3 text-slate-500">擦除方式：<code>auto</code>（自动，默认）或 <code>custom</code>（自定义区域）</td>
                </tr>
                <tr>
                  <td className="py-2 px-3 font-mono text-sm">area</td>
                  <td className="py-2 px-3 text-slate-500">array</td>
                  <td className="py-2 px-3"><span className="px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-500">否</span></td>
                  <td className="py-2 px-3 text-slate-500">自定义擦除区域（erase_method 为 custom 时使用）</td>
                </tr>
                <tr>
                  <td className="py-2 px-3 font-mono text-sm">template_id</td>
                  <td className="py-2 px-3 text-slate-500">integer</td>
                  <td className="py-2 px-3"><span className="px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-500">否</span></td>
                  <td className="py-2 px-3 text-slate-500">MPS 模板 Definition ID（默认 303）</td>
                </tr>
              </tbody>
            </table>
          </div>
        </SectionCard>

        {/* Response Format */}
        <SectionCard id="response-format" title="响应格式" description="video_erase_call 输出字段说明">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200">
                  <th className="text-left font-semibold text-slate-600 py-2 px-3">字段</th>
                  <th className="text-left font-semibold text-slate-600 py-2 px-3">类型</th>
                  <th className="text-left font-semibold text-slate-600 py-2 px-3">说明</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                <tr>
                  <td className="py-2 px-3 font-mono text-sm">type</td>
                  <td className="py-2 px-3 text-slate-500">string</td>
                  <td className="py-2 px-3 text-slate-500">固定为 <code>video_erase_call</code></td>
                </tr>
                <tr>
                  <td className="py-2 px-3 font-mono text-sm">id</td>
                  <td className="py-2 px-3 text-slate-500">string</td>
                  <td className="py-2 px-3 text-slate-500">输出项唯一标识</td>
                </tr>
                <tr>
                  <td className="py-2 px-3 font-mono text-sm">status</td>
                  <td className="py-2 px-3 text-slate-500">string</td>
                  <td className="py-2 px-3 text-slate-500"><code>completed</code> 表示任务完成（失败时抛出错误）</td>
                </tr>
                <tr>
                  <td className="py-2 px-3 font-mono text-sm">result</td>
                  <td className="py-2 px-3 text-slate-500">string</td>
                  <td className="py-2 px-3 text-slate-500">擦除后视频的下载 URL（预签名 URL，有效期 7 天）</td>
                </tr>
              </tbody>
            </table>
          </div>
        </SectionCard>
      </div>

      {/* TOC sidebar */}
      <TableOfContents items={TOC_ITEMS} />
    </div>
  );
}