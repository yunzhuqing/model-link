import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Route } from 'lucide-react';

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

      <Card id="config" title="配置管理" desc="在分组详情页面的「可用模型」标签下查看和修改每个模型的优先级与流量配比。">
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-sm text-amber-800 space-y-2">
          <p><strong>查看：</strong>分组页面 → 可用模型标签 → 表格中的「优先级」和「流量配比」列</p>
          <p><strong>修改：</strong>点击供应商卡片上的编辑按钮，修改模型的 priority 和 traffic_ratio 字段后保存</p>
          <p><strong>默认值：</strong>priority = 0，traffic_ratio = 0（均匀随机分发）</p>
        </div>
      </Card>
    </div>
  );
}
