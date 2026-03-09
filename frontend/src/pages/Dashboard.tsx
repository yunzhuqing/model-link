import { useQuery } from '@tanstack/react-query';
import client from '../api/client';
import { Database, Cpu, DollarSign, Zap, Link as LinkIcon, Activity, TrendingUp, BarChart3 } from 'lucide-react';

interface Model {
  id: number;
  name: string;
  context_size: number;
  input_price: number;
  output_price: number;
  support_kvcache: boolean;
  support_image: boolean;
  support_audio: boolean;
  support_video: boolean;
  support_file: boolean;
  support_web_search: boolean;
  support_tool_search: boolean;
}

interface Provider {
  id: number;
  name: string;
  description: string;
  base_url: string;
  models: Model[];
}

const Dashboard = () => {
  const { data: providers, isLoading } = useQuery({
    queryKey: ['providers'],
    queryFn: async () => {
      const response = await client.get('/api/providers/');
      return response.data as Provider[];
    },
  });

  const models = providers?.flatMap(p => p.models) || [];
  
  // Calculate statistics
  const totalProviders = providers?.length || 0;
  const totalModels = models.length;
  
  // Calculate average prices
  const avgInputPrice = models.length > 0 
    ? (models.reduce((acc, m) => acc + (m.input_price || 0), 0) / models.length).toFixed(4)
    : '0.0000';
  const avgOutputPrice = models.length > 0 
    ? (models.reduce((acc, m) => acc + (m.output_price || 0), 0) / models.length).toFixed(4)
    : '0.0000';
  
  // Feature support counts
  const featureCounts = {
    kvcache: models.filter(m => m.support_kvcache).length,
    image: models.filter(m => m.support_image).length,
    audio: models.filter(m => m.support_audio).length,
    video: models.filter(m => m.support_video).length,
    file: models.filter(m => m.support_file).length,
    web_search: models.filter(m => m.support_web_search).length,
    tool_search: models.filter(m => m.support_tool_search).length,
  };

  // Max context window
  const maxContext = Math.max(...models.map(m => m.context_size || 0), 0);

  // Top models by context size
  const topModels = [...models]
    .sort((a, b) => (b.context_size || 0) - (a.context_size || 0))
    .slice(0, 5);

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Dashboard Overview</h1>
          <p className="text-slate-500 mt-1">Monitor your AI Gateway statistics</p>
        </div>
        <div className="flex items-center space-x-2 px-4 py-2 bg-green-50 border border-green-200 rounded-xl">
          <Activity className="w-4 h-4 text-green-500" />
          <span className="text-sm font-medium text-green-700">System Healthy</span>
        </div>
      </div>
      
      {/* Main Stats */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatCard
          icon={<Database className="w-6 h-6 text-blue-600" />}
          label="Total Providers"
          value={totalProviders}
          color="blue"
          trend="+2 this month"
        />
        <StatCard
          icon={<Cpu className="w-6 h-6 text-emerald-600" />}
          label="Total Models"
          value={totalModels}
          color="emerald"
          trend="+5 this month"
        />
        <StatCard
          icon={<Zap className="w-6 h-6 text-amber-600" />}
          label="Max Context Window"
          value={maxContext > 0 ? maxContext.toLocaleString() : 'N/A'}
          color="amber"
          unit="tokens"
        />
        <StatCard
          icon={<TrendingUp className="w-6 h-6 text-violet-600" />}
          label="Active Requests"
          value="1.2K"
          color="violet"
          trend="+12% today"
        />
      </div>

      {/* Pricing Overview */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-lg font-bold text-slate-800">Average Pricing</h2>
            <p className="text-sm text-slate-500">Per million tokens across all models</p>
          </div>
          <DollarSign className="w-5 h-5 text-slate-400" />
        </div>
        <div className="grid grid-cols-2 gap-6">
          <div className="bg-gradient-to-br from-blue-50 to-indigo-50 rounded-xl p-6 border border-blue-100">
            <p className="text-sm font-medium text-blue-600 mb-1">Input Price</p>
            <p className="text-3xl font-bold text-slate-800">${avgInputPrice}</p>
            <p className="text-xs text-slate-500 mt-1">per million tokens</p>
          </div>
          <div className="bg-gradient-to-br from-emerald-50 to-green-50 rounded-xl p-6 border border-emerald-100">
            <p className="text-sm font-medium text-emerald-600 mb-1">Output Price</p>
            <p className="text-3xl font-bold text-slate-800">${avgOutputPrice}</p>
            <p className="text-xs text-slate-500 mt-1">per million tokens</p>
          </div>
        </div>
      </div>

      {/* Feature Support */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-lg font-bold text-slate-800">Feature Support Overview</h2>
            <p className="text-sm text-slate-500">Model capabilities distribution</p>
          </div>
          <BarChart3 className="w-5 h-5 text-slate-400" />
        </div>
        {isLoading ? (
          <div className="text-center py-8 text-slate-500">Loading...</div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4">
            <FeatureStat label="KV Cache" count={featureCounts.kvcache} total={totalModels} color="violet" />
            <FeatureStat label="Image" count={featureCounts.image} total={totalModels} color="blue" />
            <FeatureStat label="Audio" count={featureCounts.audio} total={totalModels} color="emerald" />
            <FeatureStat label="Video" count={featureCounts.video} total={totalModels} color="rose" />
            <FeatureStat label="File" count={featureCounts.file} total={totalModels} color="amber" />
            <FeatureStat label="Web Search" count={featureCounts.web_search} total={totalModels} color="indigo" />
            <FeatureStat label="Tool Search" count={featureCounts.tool_search} total={totalModels} color="pink" />
          </div>
        )}
      </div>

      {/* Providers Summary */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h2 className="text-lg font-bold text-slate-800">Providers</h2>
              <p className="text-sm text-slate-500">Configured AI providers</p>
            </div>
            <Database className="w-5 h-5 text-slate-400" />
          </div>
          {isLoading ? (
            <div className="text-center py-8 text-slate-500">Loading...</div>
          ) : providers && providers.length > 0 ? (
            <div className="space-y-3">
              {providers.map(provider => (
                <div key={provider.id} className="flex items-center justify-between p-4 bg-slate-50 rounded-xl hover:bg-slate-100 transition-colors">
                  <div className="flex items-center space-x-3">
                    <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-lg flex items-center justify-center">
                      <Database className="w-5 h-5 text-white" />
                    </div>
                    <div>
                      <p className="font-medium text-slate-800">{provider.name}</p>
                      <p className="text-sm text-slate-500 flex items-center">
                        {provider.base_url ? (
                          <>
                            <LinkIcon className="w-3 h-3 mr-1" />
                            {provider.base_url}
                          </>
                        ) : 'No URL configured'}
                      </p>
                    </div>
                  </div>
                  <span className="bg-blue-100 text-blue-700 px-3 py-1 rounded-lg text-sm font-medium">
                    {provider.models.length} models
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-slate-500">
              <Database className="w-12 h-12 mx-auto mb-3 text-slate-300" />
              <p>No providers configured yet.</p>
            </div>
          )}
        </div>

        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h2 className="text-lg font-bold text-slate-800">Top Models by Context</h2>
              <p className="text-sm text-slate-500">Largest context windows</p>
            </div>
            <Cpu className="w-5 h-5 text-slate-400" />
          </div>
          {isLoading ? (
            <div className="text-center py-8 text-slate-500">Loading...</div>
          ) : topModels.length > 0 ? (
            <div className="space-y-3">
              {topModels.map((model, index) => (
                <div key={model.id} className="flex items-center justify-between p-4 bg-slate-50 rounded-xl hover:bg-slate-100 transition-colors">
                  <div className="flex items-center space-x-3">
                    <span className="w-8 h-8 bg-slate-200 rounded-lg flex items-center justify-center text-sm font-bold text-slate-600">
                      {index + 1}
                    </span>
                    <div>
                      <p className="font-medium text-slate-800">{model.name}</p>
                      <p className="text-sm text-slate-500">
                        ${model.input_price}/M input · ${model.output_price}/M output
                      </p>
                    </div>
                  </div>
                  <span className="bg-emerald-100 text-emerald-700 px-3 py-1 rounded-lg text-sm font-medium">
                    {(model.context_size / 1000).toFixed(0)}K ctx
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-slate-500">
              <Cpu className="w-12 h-12 mx-auto mb-3 text-slate-300" />
              <p>No models configured yet.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

// Stat Card Component
const StatCard = ({ 
  icon, 
  label, 
  value, 
  color, 
  unit,
  trend 
}: { 
  icon: React.ReactNode; 
  label: string; 
  value: string | number; 
  color: string;
  unit?: string;
  trend?: string;
}) => {
  const colors: Record<string, { bg: string; border: string }> = {
    blue: { bg: 'bg-blue-50', border: 'border-blue-100' },
    emerald: { bg: 'bg-emerald-50', border: 'border-emerald-100' },
    amber: { bg: 'bg-amber-50', border: 'border-amber-100' },
    violet: { bg: 'bg-violet-50', border: 'border-violet-100' },
  };
  
  return (
    <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between">
        <div className={`p-3 rounded-xl ${colors[color]?.bg || 'bg-slate-50'} border ${colors[color]?.border || 'border-slate-100'}`}>
          {icon}
        </div>
        {trend && (
          <span className="text-xs font-medium text-emerald-600 bg-emerald-50 px-2 py-1 rounded-full">
            {trend}
          </span>
        )}
      </div>
      <div className="mt-4">
        <p className="text-sm font-medium text-slate-500">{label}</p>
        <p className="text-2xl font-bold text-slate-800 mt-1">
          {value}{unit && <span className="text-sm font-normal text-slate-500 ml-1">{unit}</span>}
        </p>
      </div>
    </div>
  );
};

// Feature Stat Component
const FeatureStat = ({ 
  label, 
  count, 
  total, 
  color 
}: { 
  label: string; 
  count: number; 
  total: number; 
  color: string;
}) => {
  const colors: Record<string, string> = {
    violet: 'text-violet-500',
    blue: 'text-blue-500',
    emerald: 'text-emerald-500',
    rose: 'text-rose-500',
    amber: 'text-amber-500',
    indigo: 'text-indigo-500',
    pink: 'text-pink-500',
  };
  
  const percentage = total > 0 ? (count / total) * 100 : 0;
  
  return (
    <div className="text-center p-4 bg-slate-50 rounded-xl">
      <div className="relative w-14 h-14 mx-auto mb-2">
        <svg className="w-14 h-14 transform -rotate-90">
          <circle
            cx="28"
            cy="28"
            r="24"
            stroke="#e2e8f0"
            strokeWidth="4"
            fill="none"
          />
          <circle
            cx="28"
            cy="28"
            r="24"
            stroke="currentColor"
            strokeWidth="4"
            fill="none"
            strokeLinecap="round"
            strokeDasharray={`${percentage * 1.51} 151`}
            className={colors[color] || 'text-slate-500'}
          />
        </svg>
        <span className="absolute inset-0 flex items-center justify-center text-sm font-bold text-slate-700">
          {count}
        </span>
      </div>
      <p className="text-xs font-medium text-slate-600">{label}</p>
    </div>
  );
};

export default Dashboard;