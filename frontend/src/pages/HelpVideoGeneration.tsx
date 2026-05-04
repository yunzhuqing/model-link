import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Video } from 'lucide-react';
import { useBaseUrl, TableOfContents } from '../components/help/HelpShared';
import type { TocItem } from '../components/help/HelpShared';
import { SeedanceSection } from '../components/help/HelpVideo_Seedance';
import { VeoSection } from '../components/help/HelpVideo_Veo';
import { KlingSection } from '../components/help/HelpVideo_Kling';
import { HappyhorseSection } from '../components/help/HelpVideo_Happyhorse';

// ---------- TOC ----------

const TOC_ITEMS: TocItem[] = [
  { id: 'overview', label: '功能说明' },
  { id: 'seedance', label: 'Seedance 模型' },
  { id: 'seedance-t2v', label: '　├ 文生视频', indent: true },
  { id: 'seedance-multimodal', label: '　├ 多模态引用', indent: true },
  { id: 'seedance-models', label: '　├ 参数说明', indent: true },
  { id: 'seedance-pricing', label: '　└ 收费标准', indent: true },
  { id: 'kling', label: 'Kling 模型' },
  { id: 'kling-t2v', label: '　├ 文生视频', indent: true },
  { id: 'kling-i2v', label: '　├ 图生视频', indent: true },
  { id: 'kling-multimodal', label: '　├ 多模态引用', indent: true },
  { id: 'kling-params', label: '　├ 参数说明', indent: true },
  { id: 'kling-pricing', label: '　└ 收费标准', indent: true },
  { id: 'veo', label: 'Veo 模型' },
  { id: 'veo-gemini', label: '　├ Gemini Veo', indent: true },
  { id: 'veo-vertexai', label: '　├ VertexAI Veo', indent: true },
  { id: 'veo-limits', label: '　├ 模型限制', indent: true },
  { id: 'veo-pricing', label: '　└ 收费标准', indent: true },
  { id: 'happyhorse', label: 'Happyhorse 模型' },
  { id: 'happyhorse-t2v', label: '　├ 文生视频', indent: true },
  { id: 'happyhorse-i2v', label: '　├ 图生视频', indent: true },
  { id: 'happyhorse-r2v', label: '　├ 参考图生视频', indent: true },
  { id: 'happyhorse-video-edit', label: '　└ 视频编辑', indent: true },
];

// ---------- Page ----------

export default function HelpVideoGeneration() {
  const navigate = useNavigate();
  const baseUrl = useBaseUrl();

  return (
    <div className="flex gap-8 max-w-6xl mx-auto">
      {/* Main content */}
      <div className="flex-1 min-w-0 space-y-8">
        {/* Back + header */}
        <div>
          <button
            onClick={() => navigate('/help')}
            className="flex items-center gap-1.5 text-sm text-slate-500 hover:text-cyan-600 mb-4 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            返回帮助中心
          </button>
          <div className="flex items-center gap-4">
            <div className="p-3 bg-gradient-to-br from-cyan-500 to-teal-600 rounded-2xl shadow-lg shadow-cyan-500/25">
              <Video className="w-7 h-7 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900">视频生成</h1>
              <p className="text-slate-500 text-sm mt-0.5">通过 Responses API 的 video_generation 工具生成视频</p>
            </div>
          </div>
        </div>

        {/* Endpoint info */}
        <div className="bg-cyan-50 border border-cyan-100 rounded-xl p-4 flex flex-wrap gap-4 items-center">
          <div>
            <span className="text-xs font-semibold text-cyan-500 uppercase tracking-wide">Endpoint</span>
            <p className="font-mono text-sm text-cyan-900 mt-0.5">{baseUrl}/v1/responses</p>
          </div>
          <div className="h-10 w-px bg-cyan-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-cyan-500 uppercase tracking-wide">工具类型</span>
            <p className="font-mono text-sm text-cyan-900 mt-0.5">video_generation</p>
          </div>
          <div className="h-10 w-px bg-cyan-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-cyan-500 uppercase tracking-wide">异步模式</span>
            <p className="text-sm text-cyan-900 mt-0.5">需设置 background: true</p>
          </div>
        </div>

        {/* Overview */}
        <div id="overview" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
          <div className="p-6 border-b border-slate-100">
            <h3 className="text-lg font-semibold text-slate-800">功能说明</h3>
            <p className="text-sm text-slate-500 mt-1">视频生成 API 的使用说明与支持范围</p>
          </div>
          <div className="p-6 space-y-4 text-sm text-slate-700">
            <p>通过 <code className="text-cyan-600 bg-cyan-50 px-1 rounded">POST /v1/responses</code> 端点，在 <code>tools</code> 数组中包含 <code>video_generation</code> 工具即可进行视频生成任务。</p>
            <p>目前支持的模型供应商包括：</p>
            <div className="flex flex-wrap gap-2">
              {[
                { label: 'Doubao Seedance', color: 'bg-amber-100 text-amber-700' },
                { label: 'Kling (快手)',     color: 'bg-indigo-100 text-indigo-700' },
                { label: 'Gemini Veo',       color: 'bg-blue-100 text-blue-700' },
                { label: 'VertexAI Veo',     color: 'bg-green-100 text-green-700' },
                { label: 'Happyhorse',       color: 'bg-pink-100 text-pink-700' },
              ].map(s => (
                <span key={s.label} className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${s.color}`}>{s.label}</span>
              ))}
            </div>
            <div className="bg-amber-50 border border-amber-100 rounded-lg p-3 text-sm text-amber-800">
              <strong>注意：</strong>所有视频生成任务均为<strong>异步处理</strong>，请务必在请求中包含 <code>"background": true</code>。任务提交后会返回包含 <code>response_id</code> 的响应，后续可通过 <code>GET /v1/responses/&#123;response_id&#125;</code> 查询最终结果。
            </div>
          </div>
        </div>

        {/* ======== Seedance ======== */}
        <SeedanceSection />

        {/* ======== Kling ======== */}
        <KlingSection />

        {/* ======== Veo ======== */}
        <VeoSection />

        {/* ======== Happyhorse ======== */}
        <HappyhorseSection />
      </div>

      {/* TOC sidebar */}
      <TableOfContents items={TOC_ITEMS} accentColor="cyan" />
    </div>
  );
}