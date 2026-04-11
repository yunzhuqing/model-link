import { useNavigate } from 'react-router-dom';
import { BookOpen, Layers, AlignLeft, Zap, MessageCircle, MessagesSquare, ChevronRight, ImageIcon, Video, Box } from 'lucide-react';

interface HelpItem {
  path: string;
  icon: React.ReactNode;
  iconBg: string;
  title: string;
  description: string;
  tags: { label: string; color: string }[];
}

const helpItems: HelpItem[] = [
  {
    path: '/help/chat',
    icon: <MessageCircle className="w-6 h-6 text-white" />,
    iconBg: 'from-sky-500 to-blue-600',
    title: 'Chat Completions API',
    description: '兼容 OpenAI Chat Completions API，支持多轮对话、流式响应、Function Calling 及图片理解，是最广泛支持的接入格式。',
    tags: [
      { label: '流式 SSE', color: 'bg-blue-100 text-blue-700' },
      { label: '工具调用', color: 'bg-violet-100 text-violet-700' },
      { label: 'POST /v1/chat/completions', color: 'bg-slate-100 text-slate-600' },
    ],
  },
  {
    path: '/help/messages',
    icon: <MessagesSquare className="w-6 h-6 text-white" />,
    iconBg: 'from-amber-500 to-orange-600',
    title: 'Messages API',
    description: '兼容 Anthropic Claude Messages API，支持多轮对话、流式响应、工具调用及图片理解，可直接替换 base URL 接入 Claude SDK。',
    tags: [
      { label: 'Anthropic 兼容', color: 'bg-amber-100 text-amber-700' },
      { label: '工具调用', color: 'bg-violet-100 text-violet-700' },
      { label: 'POST /v1/messages', color: 'bg-slate-100 text-slate-600' },
    ],
  },
  {
    path: '/help/responses',
    icon: <Zap className="w-6 h-6 text-white" />,
    iconBg: 'from-emerald-500 to-teal-600',
    title: 'Responses API',
    description: '兼容 OpenAI Responses API，支持基础对话、流式响应（SSE）、工具调用（Function Calling）及后台异步请求等功能。',
    tags: [
      { label: '流式 SSE', color: 'bg-blue-100 text-blue-700' },
      { label: '工具调用', color: 'bg-violet-100 text-violet-700' },
      { label: 'POST /v1/responses', color: 'bg-slate-100 text-slate-600' },
    ],
  },
  {
    path: '/help/embedding',
    icon: <Layers className="w-6 h-6 text-white" />,
    iconBg: 'from-blue-500 to-indigo-600',
    title: 'Embedding API',
    description: '向量嵌入接口，支持文本嵌入、文本数组批量嵌入及图文视频多模态嵌入，兼容 OpenAI embedding 格式。',
    tags: [
      { label: '文本', color: 'bg-green-100 text-green-700' },
      { label: '多模态', color: 'bg-purple-100 text-purple-700' },
      { label: 'POST /v1/embeddings', color: 'bg-slate-100 text-slate-600' },
    ],
  },
  {
    path: '/help/rerank',
    icon: <AlignLeft className="w-6 h-6 text-white" />,
    iconBg: 'from-orange-500 to-rose-600',
    title: 'Rerank API',
    description: '文档重排序接口，根据查询与文档的相关性对候选文档列表重新排序，支持文本及图文视频多模态输入，兼容 vLLM rerank 格式。',
    tags: [
      { label: '文本', color: 'bg-green-100 text-green-700' },
      { label: '多模态', color: 'bg-purple-100 text-purple-700' },
      { label: 'POST /v1/rerank', color: 'bg-slate-100 text-slate-600' },
    ],
  },
];

interface GenerationItem {
  path: string;
  icon: React.ReactNode;
  iconBg: string;
  title: string;
  description: string;
  badge: string;
  badgeColor: string;
}

const generationItems: GenerationItem[] = [
  {
    path: '/help/image-generation',
    icon: <ImageIcon className="w-5 h-5 text-white" />,
    iconBg: 'from-pink-500 to-rose-600',
    title: '图片生成',
    description: '通过 image_generation 工具触发图片生成，支持文本描述生图及图生图，返回图片 URL 或 base64。',
    badge: 'image_generation',
    badgeColor: 'bg-pink-100 text-pink-700',
  },
  {
    path: '/help/video-generation',
    icon: <Video className="w-5 h-5 text-white" />,
    iconBg: 'from-cyan-500 to-teal-600',
    title: '视频生成',
    description: '通过 video_generation 工具触发视频生成，支持文本描述及多模态素材（图片/视频/音频）参考，异步模式。',
    badge: 'video_generation',
    badgeColor: 'bg-cyan-100 text-cyan-700',
  },
  {
    path: '/help/3d-generation',
    icon: <Box className="w-5 h-5 text-white" />,
    iconBg: 'from-purple-500 to-violet-600',
    title: '3D 生成',
    description: '通过 3d_generation 工具调用混元 3D 生成 3D 模型，支持单图/多视角图/文本输入，仅支持异步模式（background: true）。',
    badge: '3d_generation',
    badgeColor: 'bg-purple-100 text-purple-700',
  },
];

export default function HelpCenter() {
  const navigate = useNavigate();

  return (
    <div className="max-w-3xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex items-center gap-4">
        <div className="p-3 bg-gradient-to-br from-slate-600 to-slate-800 rounded-2xl shadow-lg">
          <BookOpen className="w-7 h-7 text-white" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-slate-900">帮助中心</h1>
          <p className="text-slate-500 text-sm mt-0.5">选择一个主题查看详细的 API 使用指南</p>
        </div>
      </div>

      {/* API guides */}
      <div className="space-y-4">
        {helpItems.map((item) => (
          <button
            key={item.path}
            onClick={() => navigate(item.path)}
            className="w-full text-left bg-white rounded-2xl border border-slate-200 shadow-sm hover:shadow-md hover:border-blue-200 transition-all duration-200 overflow-hidden group"
          >
            <div className="p-6 flex items-start gap-5">
              <div className={`flex-shrink-0 w-12 h-12 bg-gradient-to-br ${item.iconBg} rounded-xl flex items-center justify-center shadow-lg`}>
                {item.icon}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between mb-1">
                  <h3 className="text-lg font-semibold text-slate-800 group-hover:text-blue-600 transition-colors">
                    {item.title}
                  </h3>
                  <ChevronRight className="w-5 h-5 text-slate-300 group-hover:text-blue-400 transition-colors flex-shrink-0 ml-2" />
                </div>
                <p className="text-sm text-slate-500 leading-relaxed mb-3">{item.description}</p>
                <div className="flex flex-wrap gap-2">
                  {item.tags.map((tag) => (
                    <span key={tag.label} className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${tag.color}`}>
                      {tag.label}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </button>
        ))}
      </div>

      {/* Generation features group */}
      <div>
        <div className="flex items-center gap-3 mb-3">
          <div className="h-px flex-1 bg-slate-200" />
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-widest px-2">Responses API 生成功能</span>
          <div className="h-px flex-1 bg-slate-200" />
        </div>
        <div className="space-y-3">
          {generationItems.map((item) => (
            <button
              key={item.path}
              onClick={() => navigate(item.path)}
              className="w-full text-left bg-white rounded-2xl border border-slate-200 shadow-sm hover:shadow-md hover:border-blue-200 transition-all duration-200 overflow-hidden group"
            >
              <div className="p-5 flex items-center gap-4">
                <div className={`flex-shrink-0 w-10 h-10 bg-gradient-to-br ${item.iconBg} rounded-xl flex items-center justify-center shadow-md`}>
                  {item.icon}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <h3 className="text-base font-semibold text-slate-800 group-hover:text-blue-600 transition-colors">
                      {item.title}
                    </h3>
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${item.badgeColor}`}>{item.badge}</span>
                  </div>
                  <p className="text-sm text-slate-500 leading-relaxed">{item.description}</p>
                </div>
                <ChevronRight className="w-5 h-5 text-slate-300 group-hover:text-blue-400 transition-colors flex-shrink-0" />
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
