import { useNavigate } from 'react-router-dom';
import { ArrowLeft, FileText } from 'lucide-react';

import { CodeBlock, SectionCard, TableOfContents, useBaseUrl } from '../components/help/HelpShared';

interface TocItem {
  id: string;
  label: string;
}

const TOC_ITEMS: TocItem[] = [
  { id: 'overview', label: '接口说明' },
  { id: 'multipart-upload', label: 'Form 上传' },
  { id: 'json-single', label: 'JSON 单图' },
  { id: 'json-batch', label: 'JSON 批量' },
  { id: 'response-format', label: '返回格式' },
  { id: 'limitations', label: '使用限制' },
];

const MULTIPART_RESPONSE = `{
  "bytes": 2381457,
  "created_at": 1781840390,
  "filename": "cat_01.png",
  "id": "file-d7bbfec7f7e545eba907ce54",
  "object": "file",
  "purpose": "seedance-ref"
}`;

const JSON_SINGLE_REQUEST = `{
  "input_image": "https://ark-project.tos-cn-beijing.volces.com/doc_image/r2v_tea_pic1.jpg",
  "purpose": "seedance-ref"
}`;

const JSON_BATCH_REQUEST = `{
  "input_image": [
    "https://ark-project.tos-cn-beijing.volces.com/doc_image/r2v_tea_pic1.jpg",
    "https://ark-project.tos-cn-beijing.volces.com/doc_image/r2v_tea_pic2.jpg"
  ],
  "purpose": "seedance-ref"
}`;

const JSON_RESPONSE = `{
  "data": [
    {
      "bytes": 0,
      "created_at": 1781840270,
      "id": "file-bb33273741f5458f8ee4c256",
      "object": "file"
    }
  ],
  "object": "list",
  "purpose": "seedance-ref"
}`;

const JSON_BATCH_RESPONSE = `{
  "data": [
    {
      "bytes": 0,
      "created_at": 1781840270,
      "id": "file-bb33273741f5458f8ee4c256",
      "object": "file"
    },
    {
      "bytes": 0,
      "created_at": 1781840271,
      "id": "file-bdf994f8f0e24961b9c4369a",
      "object": "file"
    }
  ],
  "object": "list",
  "purpose": "seedance-ref"
}`;

function getMultipartCurl(baseUrl: string) {
  return `curl --location --request POST '${baseUrl}/v1/files' \\
--header 'Authorization: Bearer <YOUR_API_KEY>' \\
--form 'file=@"/path/to/cat_01.png"' \\
--form 'purpose="seedance-ref"'`;
}

function getJsonCurl(baseUrl: string, body: string) {
  return `curl --location --request POST '${baseUrl}/v1/files' \\
--header 'Content-Type: application/json' \\
--header 'Authorization: Bearer <YOUR_API_KEY>' \\
--data-raw '${body}'`;
}

export default function HelpFiles() {
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
            <div className="p-3 bg-gradient-to-br from-rose-500 to-orange-600 rounded-2xl shadow-lg shadow-rose-500/25">
              <FileText className="w-7 h-7 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900">Files API</h1>
              <p className="text-slate-500 text-sm mt-0.5">上传参考素材到文件库，供 Seedance 等场景复用</p>
            </div>
          </div>
        </div>

        <div id="overview" className="bg-rose-50 border border-rose-100 rounded-xl p-4 flex flex-wrap gap-4 items-center scroll-mt-4">
          <div>
            <span className="text-xs font-semibold text-rose-500 uppercase tracking-wide">Endpoint</span>
            <p className="font-mono text-sm text-rose-900 mt-0.5">{baseUrl}/v1/files</p>
          </div>
          <div className="h-8 w-px bg-rose-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-rose-500 uppercase tracking-wide">Method</span>
            <p className="text-sm font-medium text-rose-900 mt-0.5">POST</p>
          </div>
          <div className="h-8 w-px bg-rose-200 hidden sm:block" />
          <div>
            <span className="text-xs font-semibold text-rose-500 uppercase tracking-wide">Auth</span>
            <p className="font-mono text-sm text-rose-900 mt-0.5">Bearer &lt;API_KEY&gt;</p>
          </div>
          <div className="basis-full bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">
            <strong>当前限制：</strong>目前 <code>purpose</code> 仅支持 <code>seedance-ref</code>。
          </div>
        </div>

        <SectionCard
          id="multipart-upload"
          title="Form 提交上传文件"
          badge="multipart/form-data"
          badgeColor="bg-rose-100 text-rose-700"
          description="通过标准 multipart/form-data 上传本地文件，字段名使用 file，适合直接上传图片素材。"
        >
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left">
                <tr>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">字段</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">类型</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">必填</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">说明</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {[
                  { name: 'file', required: true, type: 'binary', desc: '要上传的本地文件' },
                  { name: 'purpose', required: true, type: 'string', desc: '当前仅支持 seedance-ref' },
                  { name: 'group_id', required: false, type: 'string', desc: '可选；若未传则尝试使用 provider 的 extra_config.ark_group_id' },
                ].map((row) => (
                  <tr key={row.name} className="hover:bg-slate-50">
                    <td className="px-4 py-2.5"><code className="text-blue-600 font-semibold">{row.name}</code></td>
                    <td className="px-4 py-2.5 text-slate-500 font-mono text-xs">{row.type}</td>
                    <td className="px-4 py-2.5">{row.required ? <span className="text-red-500">是</span> : <span className="text-slate-400">否</span>}</td>
                    <td className="px-4 py-2.5 text-slate-600">{row.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">cURL 示例</span>
            <CodeBlock code={getMultipartCurl(baseUrl)} lang="bash" />
          </div>
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">返回值</span>
            <CodeBlock code={MULTIPART_RESPONSE} />
          </div>
        </SectionCard>

        <SectionCard
          id="json-single"
          title="JSON 提交单张图片 URL"
          badge="application/json"
          badgeColor="bg-emerald-100 text-emerald-700"
          description="扩展模式下可通过 JSON 请求体传入 input_image。input_image 可以是单个字符串 URL。"
        >
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left">
                <tr>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">字段</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">类型</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">必填</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">说明</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {[
                  { name: 'input_image', required: true, type: 'string', desc: '公网图片 URL' },
                  { name: 'purpose', required: true, type: 'string', desc: '当前仅支持 seedance-ref' },
                  { name: 'filename', required: false, type: 'string', desc: '可选，作为素材名称使用' },
                  { name: 'group_id', required: false, type: 'string', desc: '可选；若未传则尝试使用 provider 的 extra_config.ark_group_id' },
                ].map((row) => (
                  <tr key={row.name} className="hover:bg-slate-50">
                    <td className="px-4 py-2.5"><code className="text-blue-600 font-semibold">{row.name}</code></td>
                    <td className="px-4 py-2.5 text-slate-500 font-mono text-xs">{row.type}</td>
                    <td className="px-4 py-2.5">{row.required ? <span className="text-red-500">是</span> : <span className="text-slate-400">否</span>}</td>
                    <td className="px-4 py-2.5 text-slate-600">{row.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">请求体</span>
            <CodeBlock code={JSON_SINGLE_REQUEST} />
          </div>
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">cURL 示例</span>
            <CodeBlock code={getJsonCurl(baseUrl, JSON_SINGLE_REQUEST)} lang="bash" />
          </div>
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">返回值</span>
            <CodeBlock code={JSON_RESPONSE} />
          </div>
        </SectionCard>

        <SectionCard
          id="json-batch"
          title="JSON 批量提交图片 URL"
          badge="batch"
          badgeColor="bg-cyan-100 text-cyan-700"
          description="input_image 也可以是字符串数组，一次批量提交多张图片 URL。返回值中的 data 数组会按上传结果逐项返回 file 对象。"
        >
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">请求体</span>
            <CodeBlock code={JSON_BATCH_REQUEST} />
          </div>
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">cURL 示例</span>
            <CodeBlock code={getJsonCurl(baseUrl, JSON_BATCH_REQUEST)} lang="bash" />
          </div>
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">批量返回值示例</span>
            <CodeBlock code={JSON_BATCH_RESPONSE} />
          </div>
        </SectionCard>

        <SectionCard
          id="response-format"
          title="返回格式说明"
          description="multipart 上传返回单个 file 对象；JSON 模式返回 list 对象，data 字段中包含一个或多个 file 对象。"
        >
          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-xl border border-slate-200 p-4 bg-slate-50">
              <p className="text-sm font-semibold text-slate-800 mb-2">multipart/form-data</p>
              <p className="text-sm text-slate-600 leading-relaxed">返回单个文件对象，包含 <code>id</code>、<code>bytes</code>、<code>filename</code>、<code>purpose</code> 等字段。</p>
            </div>
            <div className="rounded-xl border border-slate-200 p-4 bg-slate-50">
              <p className="text-sm font-semibold text-slate-800 mb-2">application/json</p>
              <p className="text-sm text-slate-600 leading-relaxed">返回 <code>object: "list"</code>，每张图片对应一个 <code>file</code> 项，位于 <code>data</code> 数组中。</p>
            </div>
          </div>
        </SectionCard>

        <SectionCard
          id="limitations"
          title="使用限制"
          badge="当前实现"
          badgeColor="bg-amber-100 text-amber-700"
          description="以下限制来自当前后端实现，建议在接入前先确认。"
        >
          <ul className="list-disc list-inside space-y-2 text-sm text-slate-700">
            <li><code>purpose</code> 目前仅支持 <code>seedance-ref</code>。</li>
            <li>JSON 模式目前使用 <code>input_image</code> 字段，只支持单个 URL 字符串或 URL 字符串数组。</li>
            <li>若请求里未传 <code>group_id</code>，则需要 provider 侧已配置 <code>extra_config.ark_group_id</code>。</li>
            <li>multipart 上传的本地文件会先保存，再注册到上游素材库；JSON 模式会直接使用传入的图片 URL 建立素材。</li>
          </ul>
        </SectionCard>
      </div>

      <TableOfContents items={TOC_ITEMS} accentColor="blue" />
    </div>
  );
}
