import { Link } from 'react-router-dom';
import { ArrowUpRight } from 'lucide-react';

import { CurlSection } from './HelpShared';

// ---------- code samples ----------

const MINIMAX_T2V = `{
  "model": "MiniMax-H3",
  "background": true,
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        {
          "type": "input_text",
          "text": "夕阳下的海边，海浪拍打礁石，一只海鸥掠过天空，镜头缓慢拉远，电影质感。"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "video_generation",
      "aspect_ratio": "16:9",
      "resolution": "2K",
      "seconds": 10
    }
  ]
}`;

const MINIMAX_REF_OBJECT = `{
  "model": "MiniMax-H3",
  "background": true,
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        {
          "type": "input_text",
          "text": "全程使用{{video_1}}的第一视角构图，全程使用{{audio_1}}作为背景音乐。第一人称视角果茶宣传广告；首帧为{{apple_1}}，你的手摘下一颗带晨露的阿克苏红苹果，轻脆的苹果碰撞声；2-4 秒：快速切镜，你的手将苹果块投入雪克杯，加入冰块与茶底，用力摇晃，冰块碰撞声与摇晃声卡点轻快鼓点；4-6 秒：第一人称成品特写，分层果茶倒入透明杯，在杯身贴上粉红包标；6-8 秒：第一人称手持举杯，你将{{tea_1}}中的果茶举到镜头前，杯身标签清晰可见，尾帧定格为{{tea_1}}。背景声音统一为女生音色。"
        },
        {
          "type": "input_image",
          "image_url": "https://ark-project.tos-cn-beijing.volces.com/doc_image/r2v_tea_pic1.jpg",
          "file_id": "apple_1",
          "role": "reference_image"
        },
        {
          "type": "input_image",
          "image_url": "https://ark-project.tos-cn-beijing.volces.com/doc_image/r2v_tea_pic2.jpg",
          "file_id": "tea_1",
          "role": "reference_image"
        },
        {
          "type": "input_video",
          "video_url": "https://ark-project.tos-cn-beijing.volces.com/doc_video/r2v_tea_video1.mp4",
          "file_id": "video_1",
          "role": "reference_video"
        },
        {
          "type": "input_audio",
          "audio_url": "https://ark-project.tos-cn-beijing.volces.com/doc_audio/r2v_tea_audio1.mp3",
          "file_id": "audio_1",
          "role": "reference_audio"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "video_generation",
      "aspect_ratio": "16:9",
      "resolution": "2K",
      "seconds": 10
    }
  ]
}`;

// ---------- MiniMax-H3 section ----------

export function MiniMaxH3Section() {
  return (
    <div id="minimax" className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
      <div className="p-6 border-b border-slate-100">
        <div className="flex items-center gap-3 mb-1">
          <h3 className="text-lg font-semibold text-slate-800">MiniMax-H3 视频生成</h3>
          <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-700">海螺 H3</span>
        </div>
        <p className="text-sm text-slate-500">MiniMax 海螺 H3 视频生成模型，经腾讯云 VOD 接入，支持文本、图片、视频、音频多模态输入。</p>
      </div>
      <div className="p-6 space-y-6">
        {/* Model info */}
        <div>
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">模型</p>
          <code className="text-slate-800 font-semibold text-sm">MiniMax-H3</code>
          <p className="text-sm text-slate-600 mt-1">支持文生视频、图生视频及参考对象（图片/视频/音频）多模态引用，视频时长支持 4–15 秒。</p>
        </div>

        {/* Text to video */}
        <div id="minimax-t2v" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">文生视频 (T2V)</p>
          <CurlSection body={MINIMAX_T2V} />
        </div>

        {/* Reference objects */}
        <div id="minimax-ref" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">参考对象（多模态引用）</p>
          <div className="bg-violet-50 border border-violet-100 rounded-lg p-3 text-sm text-violet-800 mb-3">
            <strong>多模态引用：</strong>通过 <code>file_id</code> 给素材命名，在文本 prompt 中用 <code>{`{{file_id}}`}</code> 格式引用；
            <code>role</code> 字段声明素材角色（<code>reference_image</code> / <code>reference_video</code> / <code>reference_audio</code>）。
          </div>
          <CurlSection body={MINIMAX_REF_OBJECT} />
        </div>

        {/* Input limits */}
        <div id="minimax-limits" className="scroll-mt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">输入限制</p>
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left">
                <tr>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">素材类型</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">数量</th>
                  <th className="px-4 py-2.5 font-semibold text-slate-600">限制</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {[
                  { type: 'input_image', count: '≤ 9 张', desc: '宽高范围 [256, 5760]' },
                  {
                    type: 'input_video',
                    count: '≤ 3 段',
                    desc: '单段时长 [2, 15] 秒；总时长 ≤ 15 秒；宽高范围 [256, 5760]；宽高比在 5:2 ～ 2:5 范围内',
                  },
                  {
                    type: 'input_audio',
                    count: '≤ 3 段',
                    desc: '单段时长 [2, 15] 秒；总时长 ≤ 15 秒；必须搭配图片或视频输入，不能单独输入',
                  },
                ].map(r => (
                  <tr key={r.type} className="hover:bg-slate-50">
                    <td className="px-4 py-2.5"><code className="text-violet-600 font-semibold">{r.type}</code></td>
                    <td className="px-4 py-2.5 text-slate-600">{r.count}</td>
                    <td className="px-4 py-2.5 text-slate-600">{r.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="bg-amber-50 border border-amber-100 rounded-lg p-3 text-sm text-amber-800 mt-3">
            <strong>注意：</strong>混合输入（图片 + 视频 + 音频）的总上限为 <strong>12 个文件</strong>。
          </div>
        </div>

        {/* Link to full guide */}
        <div id="minimax-more" className="scroll-mt-4">
          <Link
            to="/help/minimax-h3"
            className="flex items-center gap-2 p-4 bg-slate-50 border border-slate-200 rounded-xl hover:border-slate-300 hover:bg-slate-100 transition-colors text-sm text-slate-700"
          >
            <span className="font-medium">查看 MiniMax-H3 完整使用说明（参数说明、异步任务与结果查询）</span>
            <ArrowUpRight className="w-4 h-4 text-slate-400 flex-shrink-0" />
          </Link>
        </div>
      </div>
    </div>
  );
}
