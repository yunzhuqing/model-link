import { useState } from 'react';
import { Outlet, Link, useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../contexts/AuthContext';
import LanguageSwitcher from './LanguageSwitcher';
import {
  LayoutDashboard,
  Database,
  LogOut,
  Users,
  Settings,
  ChevronRight,
  LayoutTemplate,
  BookOpen,
  Layers,
  BarChart3,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-react';

interface SubNavItem {
  path: string;
  labelKey: string;
}

interface NavItem {
  path: string;
  labelKey: string;
  icon: React.ElementType;
  descKey: string;
  children?: SubNavItem[];
}

const navItems: NavItem[] = [
  { path: '/', labelKey: 'nav.dashboard', icon: LayoutDashboard, descKey: 'nav.dashboardDesc' },
  { path: '/groups', labelKey: 'nav.groups', icon: Users, descKey: 'nav.groupsDesc' },
  { path: '/model-templates', labelKey: 'nav.modelTemplates', icon: LayoutTemplate, descKey: 'nav.modelTemplatesDesc' },
  { path: '/usage', labelKey: 'nav.usage', icon: BarChart3, descKey: 'nav.usageDesc' },
  {
    path: '/help',
    labelKey: 'nav.help',
    icon: BookOpen,
    descKey: 'nav.helpDesc',
    children: [
      { path: '/help/chat', labelKey: 'nav.helpChat' },
      { path: '/help/messages', labelKey: 'nav.helpMessages' },
      { path: '/help/responses', labelKey: 'nav.helpResponses' },
      { path: '/help/embedding', labelKey: 'nav.helpEmbedding' },
      { path: '/help/rerank', labelKey: 'nav.helpRerank' },
      { path: '/help/image-generation', labelKey: 'nav.helpImageGeneration' },
      { path: '/help/video-generation', labelKey: 'nav.helpVideoGeneration' },
      { path: '/help/3d-generation', labelKey: 'nav.help3dGeneration' },
    ],
  },
];

const Layout = () => {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation();

  // Sidebar collapsed state (default: collapsed)
  const [collapsed, setCollapsed] = useState(true);

  // Track which parent nav items are expanded (default: expand if a child is active)
  const [expanded, setExpanded] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {};
    navItems.forEach((item) => {
      if (item.children) {
        init[item.path] = item.children.some((c) => location.pathname.startsWith(c.path));
      }
    });
    return init;
  });

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const currentPage = navItems.find((item) =>
    item.path === '/' ? location.pathname === '/' : location.pathname.startsWith(item.path)
  );

  // Determine if we're on apikeys detail page
  const isApiKeyDetailPage = location.pathname.startsWith('/apikeys/');

  const toggleExpand = (path: string) => {
    setExpanded((prev) => ({ ...prev, [path]: !prev[path] }));
  };

  return (
    <div className="flex h-screen bg-slate-50">
      {/* Sidebar */}
      <aside className={`${collapsed ? 'w-[68px]' : 'w-72'} bg-white border-r border-slate-200 flex flex-col shadow-sm transition-all duration-300 flex-shrink-0`}>
        {/* Logo Section */}
        <div className={`${collapsed ? 'p-3' : 'p-6'} border-b border-slate-100`}>
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-xl flex items-center justify-center shadow-lg shadow-blue-500/25 flex-shrink-0 cursor-pointer"
              onClick={() => setCollapsed(!collapsed)}
              title={collapsed ? '展开侧栏' : '收起侧栏'}
            >
              <Database className="w-5 h-5 text-white" />
            </div>
            {!collapsed && (
                <div className="min-w-0">
                <h1 className="text-lg font-bold text-slate-800">AI Gateway</h1>
              </div>
            )}
          </div>
        </div>

        {/* Navigation */}
        <nav className={`flex-1 ${collapsed ? 'p-2' : 'p-4'} space-y-1 overflow-y-auto overflow-x-hidden`}>
          {navItems.map((item) => {
            const isActive = item.path === '/'
              ? location.pathname === '/'
              : location.pathname.startsWith(item.path);
            const Icon = item.icon;
            const isExpanded = expanded[item.path] ?? false;
            const hasChildren = !!item.children?.length;

            return (
              <div key={item.path}>
                {/* Parent item */}
                <div
                  className={`flex items-center ${collapsed ? 'justify-center px-2 py-3' : 'px-4 py-3'} rounded-xl transition-all duration-200 group cursor-pointer ${
                    isActive
                      ? 'bg-blue-50 text-blue-600 shadow-sm'
                      : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
                  }`}
                  onClick={() => {
                    if (collapsed) {
                      // When collapsed, expand sidebar and navigate or expand children
                      if (hasChildren) {
                        setCollapsed(false);
                        toggleExpand(item.path);
                      } else {
                        navigate(item.path);
                      }
                    } else {
                      if (hasChildren) {
                        toggleExpand(item.path);
                      } else {
                        navigate(item.path);
                      }
                    }
                  }}
                  title={collapsed ? t(item.labelKey) : undefined}
                >
                  <div className={`p-2 rounded-lg ${collapsed ? '' : 'mr-3'} transition-colors ${
                    isActive ? 'bg-blue-100' : 'bg-slate-100 group-hover:bg-slate-200'
                  }`}>
                    <Icon className={`w-5 h-5 ${isActive ? 'text-blue-600' : 'text-slate-500'}`} />
                  </div>
                  {!collapsed && (
                    <>
                      <div className="flex-1 min-w-0">
                        <span className={`font-medium ${isActive ? 'text-blue-600' : ''}`}>{t(item.labelKey)}</span>
                      </div>
                      {hasChildren ? (
                        <ChevronRight
                          className={`w-4 h-4 transition-transform duration-200 flex-shrink-0 ${
                            isExpanded ? 'rotate-90 text-blue-400' : 'text-slate-300'
                          }`}
                        />
                      ) : isActive ? (
                        <ChevronRight className="w-4 h-4 text-blue-400 flex-shrink-0" />
                      ) : null}
                    </>
                  )}
                </div>

                {/* Sub-menu (only when expanded sidebar) */}
                {!collapsed && hasChildren && isExpanded && (
                  <div className="ml-4 mt-1 space-y-0.5 border-l-2 border-slate-100 pl-3">
                    {item.children!.map((child) => {
                      const childActive = location.pathname === child.path || location.pathname.startsWith(child.path + '/');
                      return (
                        <Link
                          key={child.path}
                          to={child.path}
                          className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-all duration-150 ${
                            childActive
                              ? 'bg-blue-50 text-blue-600 font-medium'
                              : 'text-slate-500 hover:bg-slate-50 hover:text-slate-800'
                          }`}
                        >
                          <Layers className={`w-3.5 h-3.5 flex-shrink-0 ${childActive ? 'text-blue-500' : 'text-slate-400'}`} />
                          {t(child.labelKey)}
                        </Link>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </nav>

        {/* Bottom Section */}
        <div className={`${collapsed ? 'p-2' : 'p-4'} border-t border-slate-100 space-y-1`}>
          {/* Collapse toggle button */}
          <button
            onClick={() => setCollapsed(!collapsed)}
            className={`flex items-center w-full ${collapsed ? 'justify-center px-2 py-3' : 'px-4 py-3'} text-slate-600 hover:bg-slate-50 hover:text-slate-900 rounded-xl transition-all duration-200 group`}
            title={collapsed ? '展开侧栏' : '收起侧栏'}
          >
            <div className={`p-2 rounded-lg ${collapsed ? '' : 'mr-3'} bg-slate-100 group-hover:bg-slate-200 transition-colors`}>
              {collapsed ? (
                <PanelLeftOpen className="w-5 h-5 text-slate-500" />
              ) : (
                <PanelLeftClose className="w-5 h-5 text-slate-500" />
              )}
            </div>
            {!collapsed && <span className="font-medium">{t('nav.collapseSidebar')}</span>}
          </button>

          {/* Logout button */}
          <button
            onClick={handleLogout}
            className={`flex items-center w-full ${collapsed ? 'justify-center px-2 py-3' : 'px-4 py-3'} text-slate-600 hover:bg-red-50 hover:text-red-600 rounded-xl transition-all duration-200 group`}
            title={collapsed ? 'Logout' : undefined}
          >
            <div className={`p-2 rounded-lg ${collapsed ? '' : 'mr-3'} bg-slate-100 group-hover:bg-red-100 transition-colors`}>
              <LogOut className="w-5 h-5 text-slate-500 group-hover:text-red-500" />
            </div>
            {!collapsed && <span className="font-medium">{t('nav.logout')}</span>}
          </button>
        </div>
      </aside>

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <header className="bg-white border-b border-slate-200 px-8 h-16 flex items-center justify-between shadow-sm">
          <div className="flex items-center">
            <h2 className="text-xl font-semibold text-slate-800">
              {isApiKeyDetailPage ? t('apiKey.viewDetail') : (currentPage ? t(currentPage.labelKey) : t('nav.dashboard'))}
            </h2>
            {currentPage?.descKey && !isApiKeyDetailPage && (
              <span className="ml-3 text-sm text-slate-400 hidden md:inline">
                {t(currentPage.descKey)}
              </span>
            )}
          </div>
          <div className="flex items-center space-x-4">
            <LanguageSwitcher />
            <button className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg transition-colors">
              <Settings className="w-5 h-5" />
            </button>
          </div>
        </header>

        {/* Page Content */}
        <main className="flex-1 overflow-auto p-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
};

export default Layout;
