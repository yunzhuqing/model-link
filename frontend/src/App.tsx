import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { WorkspaceProvider } from './contexts/WorkspaceContext';
import { useEffect } from 'react';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import Dashboard from './pages/Dashboard';
import GroupList from './pages/GroupList';
import GroupDetail from './pages/GroupDetail';
import ModelTemplates from './pages/ModelTemplates';
import UsagePage from './pages/UsagePage';
import HelpCenter from './pages/HelpCenter';
import HelpEmbedding from './pages/HelpEmbedding';
import HelpRerank from './pages/HelpRerank';
import HelpResponses from './pages/HelpResponses';
import HelpChat from './pages/HelpChat';
import HelpMessages from './pages/HelpMessages';
import HelpImageGeneration from './pages/HelpImageGeneration';
import HelpVideoGeneration from './pages/HelpVideoGeneration';
import HelpThreed from './pages/HelpThreed';
import HelpModelRouting from './pages/HelpModelRouting';
import ApiKeyDetail from './pages/ApiKeyDetail';
import RateLimits from './pages/RateLimits';
import PermissionManager from './pages/PermissionManager';
import Layout from './components/Layout';

const queryClient = new QueryClient();

const ProtectedRoute = ({ children }: { children: React.ReactNode }) => {
  const { isAuthenticated, validateToken } = useAuth();

  // Re-validate the token on mount (handles stale tokens on navigation)
  useEffect(() => {
    validateToken();
  }, [validateToken]);

  return isAuthenticated ? <>{children}</> : <Navigate to="/login" />;
};

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route
              path="/"
              element={
                <ProtectedRoute>
                  <WorkspaceProvider>
                    <Layout />
                  </WorkspaceProvider>
                </ProtectedRoute>
              }
            >
              <Route index element={<Dashboard />} />
              <Route path="apikeys/:id" element={<ApiKeyDetail />} />
              <Route path="groups" element={<GroupList />} />
              <Route path="groups/:id" element={<GroupDetail />} />
              <Route path="model-templates" element={<ModelTemplates />} />
              <Route path="usage" element={<UsagePage />} />
              <Route path="help" element={<HelpCenter />} />
              <Route path="help/embedding" element={<HelpEmbedding />} />
              <Route path="help/rerank" element={<HelpRerank />} />
              <Route path="help/responses" element={<HelpResponses />} />
              <Route path="help/chat" element={<HelpChat />} />
              <Route path="help/messages" element={<HelpMessages />} />
              <Route path="help/image-generation" element={<HelpImageGeneration />} />
              <Route path="help/video-generation" element={<HelpVideoGeneration />} />
              <Route path="help/3d-generation" element={<HelpThreed />} />
              <Route path="help/model-routing" element={<HelpModelRouting />} />
              <Route path="rate-limits" element={<RateLimits />} />
              <Route path="permissions" element={<PermissionManager />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}

export default App;
