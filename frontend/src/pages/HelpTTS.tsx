import { useNavigate } from 'react-router-dom';
import { ArrowLeft, AudioLines, Volume2 } from 'lucide-react';

import { CodeBlock, SectionCard, TableOfContents, useBaseUrl } from '../components/help/HelpShared';

interface TocItem {
  id: string;
  label: string;
}

const TOC_ITEMS: TocItem[] = [
  { id: 'request-example', label: '请求示例' },
  { id: 'parameters', label: '请求参数' },
  { id: 'response', label: '响应说明' },
  { id: 'supported-models', label: '支持的模型' },
  { id: 'voices', label: '音色参考' },
];

const REQUEST_BODY = `{
  "model": "seed-audio-1.0",
  "input": [
    {
      "type": "text",
      "text": "伴随着轻松愉快的背景音乐在第5s 开始说\\"欢迎来到酷家乐\\""
    },
    {
      "type": "audio_url",
      "audio_url": {
        "url": "https://ark-project.tos-cn-beijing.volces.com/doc_audio/r2v_tea_audio1.mp3"
      }
    }
  ],
  "enable_url": true,
  "output_format": "mp3",
  "voice": ""
}`;

const CURL_EXAMPLE = `curl --location --request POST 'http://localhost:8000/v1/audio/speech' \\
--header 'Content-Type: application/json' \\
--header 'Authorization: Bearer {apikey}' \\
--data-raw '${REQUEST_BODY}'`;

const URL_RESPONSE = `{
  "created": 1785398400,
  "data": [
    {
      "url": "https://<storage-host>/tts_<request-id>.mp3",
      "model": "seed-audio-1.0",
      "content_type": "audio/mpeg",
      "duration": 12.5
    }
  ],
  "usage": {
    "price": {
      "payable_amount": 0.00375,
      "discount": 1.0,
      "actual_amount": 0.00375,
      "currency": "USD",
      "exchange_rate": 1.0
    }
  }
}`;

function ParamTable({ rows }: { rows: { name: string; required: boolean; type: string; desc: string }[] }) {
  return (
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
          {rows.map((r) => (
            <tr key={r.name} className="hover:bg-slate-50">
              <td className="px-4 py-2.5"><code className="text-blue-600 font-semibold">{r.name}</code></td>
              <td className="px-4 py-2.5 text-slate-500 font-mono text-xs">{r.type}</td>
              <td className="px-4 py-2.5">{r.required ? <span className="text-red-500">是</span> : <span className="text-slate-400">否</span>}</td>
              <td className="px-4 py-2.5 text-slate-600">{r.desc}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface ModelEntry {
  name: string;
  type: string;
  typeColor: string;
  description: string;
}

const SUPPORTED_MODELS: ModelEntry[] = [
  {
    name: 'seed-audio-1.0',
    type: '多模态',
    typeColor: 'bg-purple-100 text-purple-700',
    description: '火山引擎 Seed Audio 系列，支持文本、参考音频等多模态输入，可通过参考音频或 voice 指定音色。',
  },
  {
    name: 'gpt-4o-mini-tts',
    type: '文本',
    typeColor: 'bg-green-100 text-green-700',
    description: 'OpenAI 语音合成模型，需指定 voice（alloy / echo / fable / onyx / nova / shimmer），支持 instructions 控制语气风格。',
  },
];

export default function HelpTTS() {
  const navigate = useNavigate();
  const baseUrl = useBaseUrl();

  return (
    <div className="flex gap-8 max-w-6xl mx-auto">
      <div className="flex-1 min-w-0 space-y-8">
        <div>
          <button
            onClick={() => navigate('/help')}
            className="flex items-center gap-1.5 text-sm text-slate-500 hover:text-blue-600 mb-4 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            返回帮助中心
          </button>
          <div className="flex items-center gap-4">
            <div className="p-3 bg-gradient-to-br from-violet-500 to-fuchsia-600 rounded-2xl shadow-lg shadow-violet-500/25">
              <AudioLines className="w-7 h-7 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900">TTS 语音合成</h1>
              <p className="text-slate-500 text-sm mt-0.5">文本转语音接口使用指南，兼容 OpenAI Audio API 格式</p>
            </div>
          </div>
        </div>

        <div className="bg-violet-50 border border-violet-100 rounded-xl p-4 flex flex-wrap gap-4 items-center">
          <div>
            <span className="text-xs font-semibold text-violet-400 uppercase tracking-wide">Endpoint</span>
            <p className="font-mono text-sm text-violet-900 mt-0.5">{baseUrl}/v1/audio/speech</p>
          </div>
          <div className="h-8 w-px bg-violet-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-violet-400 uppercase tracking-wide">Method</span>
            <p className="text-sm font-medium text-violet-900 mt-0.5">POST</p>
          </div>
          <div className="h-8 w-px bg-violet-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-violet-400 uppercase tracking-wide">Auth</span>
            <p className="font-mono text-sm text-violet-900 mt-0.5">Bearer &lt;API_KEY&gt;</p>
          </div>
        </div>

        <SectionCard
          id="request-example"
          title="请求示例"
          description="支持 OpenAI 风格的 input 内容块数组：text 块为要合成的文本，audio_url 块为参考音频（用于指定说话人音色/背景音频）。"
        >
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">请求体</span>
            <CodeBlock code={REQUEST_BODY} />
          </div>
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">cURL 示例</span>
            <CodeBlock code={CURL_EXAMPLE} lang="bash" />
          </div>
        </SectionCard>

        <SectionCard
          id="parameters"
          title="请求参数"
          description="以下为 /v1/audio/speech 支持的请求参数。"
        >
          <ParamTable rows={[
            { name: 'model',            required: true,  type: 'string',              desc: '模型名称，如 seed-audio-1.0、gpt-4o-mini-tts' },
            { name: 'input',            required: true,  type: 'string | object[]',   desc: '要合成的文本，或内容块数组（text / audio_url 等，可混合）' },
            { name: 'voice',            required: false, type: 'string',              desc: '音色名称；seed-audio 可留空 "" 使用参考音频，gpt-4o-mini-tts 必填' },
            { name: 'enable_url',       required: false, type: 'boolean',             desc: 'true 返回音频文件 URL（JSON），false（默认）返回音频流' },
            { name: 'output_format',    required: false, type: 'string',              desc: '输出音频格式，默认 mp3' },
            { name: 'response_format',  required: false, type: 'string',              desc: 'OpenAI 兼容字段，支持 mp3 / opus / aac / flac / wav / pcm，默认 mp3' },
            { name: 'speed',            required: false, type: 'number',              desc: '语速 0.25 - 4.0，默认 1.0' },
            { name: 'instructions',     required: false, type: 'string',              desc: '声音风格指令（gpt-4o-mini-tts）' },
            { name: 'enable_subtitle',  required: false, type: 'boolean',             desc: '是否生成字幕，仅在 enable_url=true 时返回' },
          ]} />
        </SectionCard>

        <SectionCard
          id="response"
          title="响应说明"
          description="根据 enable_url 参数返回音频流或音频文件 URL。"
        >
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">
            <strong>注意：</strong><code>enable_url=true</code> 时返回 JSON（含音频 URL）；<code>enable_url=false</code>（默认）时直接返回原始音频流（如 <code>audio/mpeg</code>）。
          </div>
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">enable_url=true 响应示例</span>
            <CodeBlock code={URL_RESPONSE} />
          </div>
        </SectionCard>

        <SectionCard
          id="supported-models"
          title="支持的模型"
          description="以下模型可通过本 API 调用，请在配置供应商时选择对应模型。"
        >
          <div className="divide-y divide-slate-100">
            {SUPPORTED_MODELS.map((m) => (
              <div key={m.name} className="py-3 flex items-start gap-4">
                <span className={`mt-0.5 flex-shrink-0 px-2.5 py-0.5 rounded-full text-xs font-medium ${m.typeColor}`}>{m.type}</span>
                <div className="flex-1 min-w-0">
                  <code className="text-sm font-semibold text-slate-800">{m.name}</code>
                  <p className="text-sm text-slate-500 mt-0.5">{m.description}</p>
                </div>
              </div>
            ))}
          </div>
        </SectionCard>

        <SectionCard
          id="voices"
          title="音色参考"
          description="seed-audio 系列模型的音色参考列表。"
        >
          <div className="flex items-start gap-3">
            <div className="p-2 bg-violet-50 rounded-lg text-violet-600 flex-shrink-0">
              <Volume2 className="w-5 h-5" />
            </div>
            <div className="text-sm text-slate-600 leading-relaxed">
              <p>
                seed-audio 支持通过 <code>voice</code> 字段指定音色，或通过 <code>input</code> 中的
                <code>audio_url</code> 参考音频指定说话人；<code>voice</code> 留空 <code>""</code> 时使用参考音频。
              </p>
              <p className="mt-2">
                音色参考列表：
                <a
                  href="https://docs.volcengine.com/docs/6561/1257544?lang=zh"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 hover:text-blue-800 underline underline-offset-2 break-all"
                >
                  https://docs.volcengine.com/docs/6561/1257544?lang=zh
                </a>
              </p>
            </div>
          </div>
        </SectionCard>
      </div>

      <TableOfContents items={TOC_ITEMS} />
    </div>
  );
}
