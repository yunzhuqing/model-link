import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Route } from 'lucide-react';
import { CodeBlock } from '../components/help/HelpShared';

function Card({ id, title, desc, children }: { id: string; title: string; desc: string; children: React.ReactNode }) {
  return (
    <div id={id} className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
      <div className="p-6 border-b border-slate-100">
        <h3 className="text-lg font-semibold text-slate-800">{title}</h3>
        <p className="text-sm text-slate-500 mt-1">{desc}</p>
      </div>
      <div className="p-6 space-y-4">{children}</div>
    </div>
  );
}


const SERVICE_TIER_EXAMPLE = `{
  "model": "gemini-3.1-flash-image-preview",
  "service_tier": "flex",
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        { "type": "input_text", "text": "生成狸花猫的照片" }
      ]
    }
  ],
  "tools": [
    { "type": "image_generation", "n": 1, "size": "464x576" }
  ],
  "background": true
}`;

export default function HelpModelRouting() {
  const navigate = useNavigate();
  return (
    <div className="max-w-4xl mx-auto space-y-8">
      <div>
        <button onClick={() => navigate('/help')} className="flex items-center gap-1.5 text-sm text-slate-500 hover:text-indigo-600 mb-4 transition-colors">
          <ArrowLeft className="w-4 h-4" />返回帮助中心
        </button>
        <div className="flex items-center gap-4">
          <div className="p-3 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-2xl shadow-lg">
            <Route className="w-7 h-7 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-slate-900">模型路由与分发机制</h1>
            <p className="text-slate-500 text-sm mt-0.5">优先级 + 流量配比：多供应商智能分发请求</p>
          </div>
        </div>
      </div>

      <Card id="overview" title="概述" desc="当一个模型有多个供应商时，系统通过「优先级 + 流量配比」两级策略决定请求分发到哪个供应商。">
        <div className="bg-indigo-50 border border-indigo-100 rounded-xl p-5">
          <ol className="list-decimal list-inside space-y-2 text-sm text-indigo-800">
            <li>找出所有活跃的供应商模型</li>
            <li>按优先级值分组（数值越大越优先）</li>
            <li>只保留优先级最高的一组候选</li>
            <li>在最高优先级组内按流量配比选择供应商</li>
          </ol>
        </div>
      </Card>

      <Card id="priority" title="优先级（Priority）" desc="优先级决定供应商选取顺序。数值越高越先被选中，当高优先级供应商不可用时才降级。值为非负整数，默认 0。">
        <div className="overflow-x-auto rounded-xl border border-slate-200">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left">
              <tr>
                <th className="px-4 py-2.5 font-semibold">优先级值</th>
                <th className="px-4 py-2.5 font-semibold">含义</th>
                <th className="px-4 py-2.5 font-semibold">典型场景</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              <tr><td className="px-4 py-2.5"><code className="text-amber-600 font-semibold">10</code></td><td className="px-4 py-2.5">高优先</td><td className="px-4 py-2.5 text-slate-500">主力供应商、自建服务</td></tr>
              <tr><td className="px-4 py-2.5"><code className="text-amber-600 font-semibold">5</code></td><td className="px-4 py-2.5">中等</td><td className="px-4 py-2.5 text-slate-500">备用云端 API</td></tr>
              <tr><td className="px-4 py-2.5"><code className="text-amber-600 font-semibold">0</code></td><td className="px-4 py-2.5">最低（默认）</td><td className="px-4 py-2.5 text-slate-500">兜底方案</td></tr>
            </tbody>
          </table>
        </div>
      </Card>

      <Card id="traffic-ratio" title="流量配比（Traffic Ratio）" desc="同一优先级组内，按配比将流量分发到不同供应商。配比仅在同一个优先级组内生效。">
        <ul className="space-y-2 text-sm text-slate-700">
          <li>• 例如 A:60 + B:40 → A 获得约 60% 流量，B 获得约 40%</li>
          <li>• 配比为正整数，按比例缩放到 100%</li>
          <li>• 如果所有配比都为 0，则在组内均匀随机选择</li>
          <li>• 不同优先级组之间的流量完全隔离</li>
        </ul>
      </Card>

      <Card id="algorithm" title="分发算法详解" desc="根据是否传入 user_id 采用不同分发策略。">
        <div className="space-y-3">
          <div className="bg-blue-50 border border-blue-200 rounded-xl p-4">
            <p className="text-sm font-semibold text-blue-800 mb-1">传入 user_id — 哈希确定性选择</p>
            <p className="text-sm text-blue-700">hash(user_id) % 100 映射到 0-99 桶，按累进配比匹配供应商。同一用户始终路由到同一供应商，适合需要会话一致性的场景。</p>
          </div>
          <div className="bg-purple-50 border border-purple-200 rounded-xl p-4">
            <p className="text-sm font-semibold text-purple-800 mb-1">未传 user_id — 加权随机选择</p>
            <p className="text-sm text-purple-700">以配比为权重加权随机选择。每次请求独立随机，整体按配比概率分布。</p>
          </div>
        </div>
      </Card>

      <Card id="example" title="示例演示" desc="模型 qwen-max 有 3 个供应商：">
        <div className="overflow-x-auto rounded-xl border border-slate-200 mb-4">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left">
              <tr>
                <th className="px-4 py-2.5 font-semibold">供应商</th>
                <th className="px-4 py-2.5 font-semibold">优先级</th>
                <th className="px-4 py-2.5 font-semibold">配比</th>
                <th className="px-4 py-2.5 font-semibold">说明</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              <tr><td className="px-4 py-2.5 font-medium">自建 vLLM (A)</td><td className="px-4 py-2.5 text-amber-600">10</td><td className="px-4 py-2.5 text-emerald-600">60</td><td className="px-4 py-2.5 text-slate-500">主力 60% 流量</td></tr>
              <tr><td className="px-4 py-2.5 font-medium">阿里云百炼 (B)</td><td className="px-4 py-2.5 text-amber-600">10</td><td className="px-4 py-2.5 text-emerald-600">40</td><td className="px-4 py-2.5 text-slate-500">补充 40% 流量</td></tr>
              <tr><td className="px-4 py-2.5 font-medium">DeepSeek (C)</td><td className="px-4 py-2.5 text-amber-600">0</td><td className="px-4 py-2.5 text-emerald-600">100</td><td className="px-4 py-2.5 text-slate-500">兜底，A+B 不可用时启用</td></tr>
            </tbody>
          </table>
        </div>
        <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 text-sm text-slate-700 space-y-1">
          <p>• 正常情况：请求分发到 A（60%）和 B（40%），C 不参与</p>
          <p>• 若传入 user_id=&quot;alice&quot;，hash 值落在 0-59 → 选 A，60-99 → 选 B</p>
          <p>• A 和 B 都不可用时，系统自动降级到优先级 0 的 C</p>
        </div>
      </Card>

      
      <Card id="service-tier" title="服务等级（service_tier）" desc="通过 service_tier 参数将同一模型名路由到不同供应商实例或应用不同定价策略，实现分级服务（如弹性/优先/高并发）。">
        <div className="space-y-4">
          <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-4">
            <p className="text-sm font-semibold text-emerald-800 mb-2">核心规则</p>
            <ul className="text-sm text-emerald-700 space-y-1.5 list-disc list-inside">
              <li>未设置 <code>service_tier</code>（或传 <code>null</code>、<code>""</code>、<code>"auto"</code>、<code>"default"</code>）时，请求仅路由到<strong>未声明服务等级</strong>的模型实例（默认实例）</li>
              <li>设置为具体等级名（如 <code>"flex"</code>、<code>"priority"</code>、<code>"scale"</code>）时，请求仅路由到<strong>声明了该等级</strong>的模型实例</li>
              <li>各等级支持独立定价：等级配置中的价格将覆盖模型的基础价格，未配置的价格项回退到基础价格</li>
              <li>请求的等级在该模型上不可用时，返回 400 错误并在提示中列出可用等级</li>
            </ul>
          </div>

          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left">
                <tr>
                  <th className="px-4 py-2.5 font-semibold">service_tier 值</th>
                  <th className="px-4 py-2.5 font-semibold">路由行为</th>
                  <th className="px-4 py-2.5 font-semibold">典型用途</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                <tr>
                  <td className="px-4 py-2.5"><code className="text-slate-500 font-semibold">（不填 / null）</code></td>
                  <td className="px-4 py-2.5">路由到默认实例（无等级声明的实例）</td>
                  <td className="px-4 py-2.5 text-slate-500">普通请求，无需特殊 QoS</td>
                </tr>
                <tr>
                  <td className="px-4 py-2.5"><code className="text-slate-500 font-semibold">"auto"</code></td>
                  <td className="px-4 py-2.5">同不填，路由到默认实例</td>
                  <td className="px-4 py-2.5 text-slate-500">OpenAI 兼容语义，等价于默认</td>
                </tr>
                <tr>
                  <td className="px-4 py-2.5"><code className="text-slate-500 font-semibold">"default"</code></td>
                  <td className="px-4 py-2.5">同不填，路由到默认实例</td>
                  <td className="px-4 py-2.5 text-slate-500">显式指定默认等级</td>
                </tr>
                <tr>
                  <td className="px-4 py-2.5"><code className="text-teal-600 font-semibold">"flex"</code></td>
                  <td className="px-4 py-2.5">仅路由到声明了 flex 等级的实例</td>
                  <td className="px-4 py-2.5 text-slate-500">弹性/低成本通道，价格更优惠</td>
                </tr>
                <tr>
                  <td className="px-4 py-2.5"><code className="text-amber-600 font-semibold">"priority"</code></td>
                  <td className="px-4 py-2.5">仅路由到声明了 priority 等级的实例</td>
                  <td className="px-4 py-2.5 text-slate-500">高优先级通道，低延迟保证</td>
                </tr>
                <tr>
                  <td className="px-4 py-2.5"><code className="text-violet-600 font-semibold">"scale"</code></td>
                  <td className="px-4 py-2.5">仅路由到声明了 scale 等级的实例</td>
                  <td className="px-4 py-2.5 text-slate-500">高并发通道，适合批量任务</td>
                </tr>
                <tr>
                  <td className="px-4 py-2.5"><code className="text-blue-600 font-semibold">"自定义名称"</code></td>
                  <td className="px-4 py-2.5">仅路由到声明了该自定义等级的实例</td>
                  <td className="px-4 py-2.5 text-slate-500">管理员在模型配置中定义的任意等级名</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div>
            <p className="text-sm font-medium text-slate-700 mb-2">示例：使用 flex 等级调用图片生成（Responses API）</p>
            <CodeBlock code={SERVICE_TIER_EXAMPLE} />
          </div>

          <div className="bg-sky-50 border border-sky-200 rounded-xl p-4">
            <p className="text-sm font-semibold text-sky-800 mb-1">支持的接口</p>
            <p className="text-sm text-sky-700"><code>service_tier</code> 可用于以下接口：<code>/v1/responses</code>、<code>/v1/chat/completions</code>、<code>/v1/messages</code>、<code>/v1/images/generations</code>、<code>/v1/images/edits</code>、<code>/v1/audio/speech</code>。在 Chat Completions 接口中，<code>service_tier</code> 作为顶层字段传入即可（未识别的字段会透传到 metadata 供路由使用）。</p>
          </div>
        </div>
      </Card>

      <Card id="config" title="配置管理" desc="在分组详情页面的「可用模型」标签下和模型模板中管理优先级、流量配比和服务等级配置。">
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-sm text-amber-800 space-y-2">
          <p><strong>优先级/配比：</strong>分组页面 → 可用模型标签 → 编辑供应商卡片中的 priority 和 traffic_ratio 字段。默认 priority=0，traffic_ratio=0（均匀随机分发）</p>
          <p><strong>服务等级：</strong>在模型编辑弹窗中配置 service_tiers，为每个等级设置名称和可选的独立输入/输出/缓存价格。未配置等级的模型实例自动成为默认实例</p>
          <p><strong>模型模板：</strong>管理员可在模型模板中预设 service_tiers，从模板添加模型时自动继承等级配置</p>
        </div>
      </Card>
    </div>
  );
}
