import { useQuery } from '@tanstack/react-query';
import client from '../api/client';
import { Database, Cpu, DollarSign, Zap, Link as LinkIcon, User, Activity } from 'lucide-react';

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
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold text-gray-800">Dashboard Overview</h1>
        <div className="flex items-center space-x-2 text-sm text-gray-500">
          <Activity className="w-4 h-4 text-green-500" />
          <span>System Healthy</span>
        </div>
      </div>
      
      {/* Main Stats */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatCard
          icon={<Database className="w-6 h-6 text-blue-600" />}
          label="Total Providers"
          value={totalProviders}
          color="blue"
        />
        <StatCard
          icon={<Cpu className="w-6 h-6 text-green-600" />}
          label="Total Models"
          value={totalModels}
          color="green"
        />
        <StatCard
          icon={<Zap className="w-6 h-6 text-yellow-600" />}
          label="Max Context Window"
          value={maxContext > 0 ? maxContext.toLocaleString() : 'N/A'}
          color="yellow"
          unit="tokens"
        />
        <StatCard
          icon={<User className="w-6 h-6 text-purple-600" />}
          label="Active User"
          value="1"
          color="purple"
        />
      </div>

      {/* Pricing Overview */}
      <div className="bg-white rounded-lg shadow-sm p-6">
        <h2 className="text-lg font-bold text-gray-800 mb-4 flex items-center">
          <DollarSign className="w-5 h-5 mr-2 text-gray-500" />
          Average Pricing ($/M tokens)
        </h2>
        <div className="grid grid-cols-2 gap-8">
          <div className="text-center p-4 bg-blue-50 rounded-lg">
            <p className="text-3xl font-bold text-blue-600">${avgInputPrice}</p>
            <p className="text-sm text-gray-500 mt-1">Average Input Price</p>
          </div>
          <div className="text-center p-4 bg-green-50 rounded-lg">
            <p className="text-3xl font-bold text-green-600">${avgOutputPrice}</p>
            <p className="text-sm text-gray-500 mt-1">Average Output Price</p>
          </div>
        </div>
      </div>

      {/* Feature Support */}
      <div className="bg-white rounded-lg shadow-sm p-6">
        <h2 className="text-lg font-bold text-gray-800 mb-4">Feature Support Overview</h2>
        {isLoading ? (
          <p>Loading...</p>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4">
            <FeatureStat label="KV Cache" count={featureCounts.kvcache} total={totalModels} color="purple" />
            <FeatureStat label="Image" count={featureCounts.image} total={totalModels} color="blue" />
            <FeatureStat label="Audio" count={featureCounts.audio} total={totalModels} color="green" />
            <FeatureStat label="Video" count={featureCounts.video} total={totalModels} color="red" />
            <FeatureStat label="File" count={featureCounts.file} total={totalModels} color="yellow" />
            <FeatureStat label="Web Search" count={featureCounts.web_search} total={totalModels} color="indigo" />
            <FeatureStat label="Tool Search" count={featureCounts.tool_search} total={totalModels} color="pink" />
          </div>
        )}
      </div>

      {/* Providers Summary */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-lg shadow-sm p-6">
          <h2 className="text-lg font-bold text-gray-800 mb-4 flex items-center">
            <Database className="w-5 h-5 mr-2 text-gray-500" />
            Providers
          </h2>
          {isLoading ? (
            <p>Loading...</p>
          ) : providers && providers.length > 0 ? (
            <div className="space-y-3">
              {providers.map(provider => (
                <div key={provider.id} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                  <div>
                    <p className="font-medium text-gray-800">{provider.name}</p>
                    <p className="text-sm text-gray-500 flex items-center">
                      {provider.base_url ? (
                        <>
                          <LinkIcon className="w-3 h-3 mr-1" />
                          {provider.base_url}
                        </>
                      ) : 'No URL configured'}
                    </p>
                  </div>
                  <span className="bg-blue-100 text-blue-700 px-2 py-1 rounded text-sm font-medium">
                    {provider.models.length} models
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-gray-500 text-center py-4">No providers configured yet.</p>
          )}
        </div>

        <div className="bg-white rounded-lg shadow-sm p-6">
          <h2 className="text-lg font-bold text-gray-800 mb-4 flex items-center">
            <Cpu className="w-5 h-5 mr-2 text-gray-500" />
            Top Models by Context Size
          </h2>
          {isLoading ? (
            <p>Loading...</p>
          ) : topModels.length > 0 ? (
            <div className="space-y-3">
              {topModels.map((model, index) => (
                <div key={model.id} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                  <div className="flex items-center">
                    <span className="w-6 h-6 bg-gray-200 rounded-full flex items-center justify-center text-sm font-medium text-gray-600 mr-3">
                      {index + 1}
                    </span>
                    <div>
                      <p className="font-medium text-gray-800">{model.name}</p>
                      <p className="text-sm text-gray-500">
                        ${model.input_price}/M input · ${model.output_price}/M output
                      </p>
                    </div>
                  </div>
                  <span className="bg-green-100 text-green-700 px-2 py-1 rounded text-sm font-medium">
                    {(model.context_size / 1000).toFixed(0)}K ctx
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-gray-500 text-center py-4">No models configured yet.</p>
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
  unit 
}: { 
  icon: React.ReactNode; 
  label: string; 
  value: string | number; 
  color: string;
  unit?: string;
}) => {
  const colors: Record<string, string> = {
    blue: 'bg-blue-100',
    green: 'bg-green-100',
    yellow: 'bg-yellow-100',
    purple: 'bg-purple-100',
  };
  
  return (
    <div className="bg-white p-6 rounded-lg shadow-sm">
      <div className="flex items-center">
        <div className={`p-3 rounded-full mr-4 ${colors[color]}`}>
          {icon}
        </div>
        <div>
          <p className="text-sm text-gray-500 font-medium">{label}</p>
          <p className="text-2xl font-bold text-gray-800">
            {value}{unit && <span className="text-sm font-normal text-gray-500 ml-1">{unit}</span>}
          </p>
        </div>
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
    purple: 'bg-purple-500',
    blue: 'bg-blue-500',
    green: 'bg-green-500',
    red: 'bg-red-500',
    yellow: 'bg-yellow-500',
    indigo: 'bg-indigo-500',
    pink: 'bg-pink-500',
  };
  
  const percentage = total > 0 ? (count / total) * 100 : 0;
  
  return (
    <div className="text-center">
      <div className="relative w-12 h-12 mx-auto mb-2">
        <svg className="w-12 h-12 transform -rotate-90">
          <circle
            cx="24"
            cy="24"
            r="20"
            stroke="#e5e7eb"
            strokeWidth="4"
            fill="none"
          />
          <circle
            cx="24"
            cy="24"
            r="20"
            stroke="currentColor"
            strokeWidth="4"
            fill="none"
            strokeLinecap="round"
            strokeDasharray={`${percentage * 1.26} 126`}
            className={colors[color].replace('bg-', 'text-')}
          />
        </svg>
        <span className="absolute inset-0 flex items-center justify-center text-sm font-medium text-gray-700">
          {count}
        </span>
      </div>
      <p className="text-xs text-gray-500">{label}</p>
    </div>
  );
};

export default Dashboard;