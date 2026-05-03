import { useState, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import client from '../api/client';
import {
  Shield,
  ToggleLeft,
  ToggleRight,
  Users,
  UserCog,
  Crown,
  AlertCircle,
  Loader2,
} from 'lucide-react';

// ── Types ──────────────────────────────────────────────────────────────────

interface PermissionItem {
  id: number;
  key: string;
  label: string;
  description: string;
  allowed_roles: string[];
  is_enabled: boolean;
  created_at: string | null;
  updated_at: string | null;
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function groupPermissions(permissions: PermissionItem[]) {
  const rootOnly: PermissionItem[] = [];
  const adminAndAbove: PermissionItem[] = [];
  const allRoles: PermissionItem[] = [];

  for (const p of permissions) {
    const roles = p.allowed_roles || [];
    if (roles.includes('member')) {
      allRoles.push(p);
    } else if (roles.includes('admin')) {
      adminAndAbove.push(p);
    } else {
      rootOnly.push(p);
    }
  }

  return { rootOnly, adminAndAbove, allRoles };
}

// ── Component ──────────────────────────────────────────────────────────────

export default function PermissionManager() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  // ── Fetch global permissions plus is_root flag ───────────────────────────
  const {
    data: permData,
    isLoading: permsLoading,
    error: permsError,
  } = useQuery<{ permissions: PermissionItem[]; is_root: boolean }>({
    queryKey: ['global-permissions'],
    queryFn: async () => {
      const r = await client.get('/api/permissions');
      return r.data as { permissions: PermissionItem[]; is_root: boolean };
    },
  });

  const permissions = permData?.permissions ?? [];
  const isRoot = permData?.is_root ?? false;

  // ── Toggle permission ────────────────────────────────────────────────────
  const toggleMutation = useMutation({
    mutationFn: ({ key, is_enabled }: { key: string; is_enabled: boolean }) =>
      client.put(`/api/permissions/${key}/toggle`, { is_enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['global-permissions'] });
    },
  });

  // ── Update permission (batch enable/disable) ─────────────────────────────
  const updateMutation = useMutation({
    mutationFn: ({ key, data }: { key: string; data: Partial<Pick<PermissionItem, 'is_enabled' | 'allowed_roles'>> }) =>
      client.put(`/api/permissions/${key}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['global-permissions'] });
    },
  });

  // ── Batch handlers ───────────────────────────────────────────────────────
  const handleBatchToggle = useCallback(
    (enabled: boolean) => {
      for (const p of permissions) {
        toggleMutation.mutate({ key: p.key, is_enabled: enabled });
      }
    },
    [permissions, toggleMutation],
  );

  const isUpdating = toggleMutation.isPending || updateMutation.isPending;

  // ── Loading state ────────────────────────────────────────────────────────
  if (permsLoading && !permData) {
    return (
      <div className="flex justify-center items-center h-64">
        <Loader2 className="w-6 h-6 text-slate-400 animate-spin" />
        <span className="ml-2 text-slate-500">{t('common.loading')}</span>
      </div>
    );
  }

  // ── Not root ─────────────────────────────────────────────────────────────
  if (!permsLoading && !isRoot) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">{t('permissions.pageTitle')}</h1>
          <p className="text-slate-500 mt-1">{t('permissions.pageSubtitle')}</p>
        </div>
        <div className="bg-amber-50 border border-amber-200 rounded-2xl p-6 flex items-start space-x-3">
          <AlertCircle className="w-5 h-5 text-amber-500 mt-0.5 flex-shrink-0" />
          <div>
            <h4 className="text-sm font-medium text-amber-800">{t('permissions.rootOnly')}</h4>
            <p className="text-sm text-amber-600 mt-1">{t('permissions.rootOnlyDesc')}</p>
          </div>
        </div>
      </div>
    );
  }

  // ── Group the permissions ─────────────────────────────────────────────────
  const grouped = permissions.length > 0 ? groupPermissions(permissions) : null;

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">{t('permissions.pageTitle')}</h1>
          <p className="text-slate-500 mt-1">{t('permissions.pageSubtitle')}</p>
        </div>
        <span className="inline-flex items-center px-3 py-1.5 bg-indigo-50 text-indigo-700 text-sm font-medium rounded-lg border border-indigo-200">
          <Shield className="w-4 h-4 mr-1.5" />{t('permissions.globalControl')}
        </span>
      </div>

      {/* Load error */}
      {permsError && (
        <div className="bg-red-50 border border-red-200 rounded-2xl p-6 flex items-start space-x-3">
          <AlertCircle className="w-5 h-5 text-red-500 mt-0.5 flex-shrink-0" />
          <div>
            <h4 className="text-sm font-medium text-red-800">{t('permissions.loadFailed')}</h4>
            <p className="text-sm text-red-600 mt-1">{(permsError as Error)?.message || ''}</p>
          </div>
        </div>
      )}

      {/* Permissions Content */}
      {!permsLoading && !permsError && grouped && permissions.length > 0 && (
        <>
          {/* Bulk Actions Bar */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-4 flex items-center justify-between">
            <div className="text-sm text-slate-500">
              {permissions.length} {t('permissions.points')}
            </div>
            <div className="flex items-center space-x-2">
              <button
                onClick={() => handleBatchToggle(true)}
                disabled={isUpdating}
                className="px-3 py-1.5 text-xs font-medium rounded-lg bg-emerald-50 text-emerald-600 border border-emerald-200 hover:bg-emerald-100 transition-colors disabled:opacity-50"
              >
                {t('permissions.enableAll')}
              </button>
              <button
                onClick={() => handleBatchToggle(false)}
                disabled={isUpdating}
                className="px-3 py-1.5 text-xs font-medium rounded-lg bg-red-50 text-red-600 border border-red-200 hover:bg-red-100 transition-colors disabled:opacity-50"
              >
                {t('permissions.disableAll')}
              </button>
            </div>
          </div>

          {/* Root-Only Permissions */}
          {grouped.rootOnly.length > 0 && (
            <PermissionSection
              title={t('permissions.rootOnlySection')}
              description={t('permissions.rootOnlySectionDesc')}
              icon={<Crown className="w-5 h-5 text-amber-600" />}
              iconBg="bg-amber-100"
              borderColor="border-amber-200"
              items={grouped.rootOnly}
              isUpdating={isUpdating}
              onToggle={(key, enabled) => toggleMutation.mutate({ key, is_enabled: enabled })}
            />
          )}

          {/* Admin & Above Permissions */}
          {grouped.adminAndAbove.length > 0 && (
            <PermissionSection
              title={t('permissions.adminSection')}
              description={t('permissions.adminSectionDesc')}
              icon={<UserCog className="w-5 h-5 text-indigo-600" />}
              iconBg="bg-indigo-100"
              borderColor="border-indigo-200"
              items={grouped.adminAndAbove}
              isUpdating={isUpdating}
              onToggle={(key, enabled) => toggleMutation.mutate({ key, is_enabled: enabled })}
            />
          )}

          {/* All Roles Permissions */}
          {grouped.allRoles.length > 0 && (
            <PermissionSection
              title={t('permissions.memberSection')}
              description={t('permissions.memberSectionDesc')}
              icon={<Users className="w-5 h-5 text-emerald-600" />}
              iconBg="bg-emerald-100"
              borderColor="border-emerald-200"
              items={grouped.allRoles}
              isUpdating={isUpdating}
              onToggle={(key, enabled) => toggleMutation.mutate({ key, is_enabled: enabled })}
            />
          )}

          {/* Info Footer */}
          <div className="bg-slate-50 border border-slate-200 rounded-2xl p-4 flex items-start space-x-3">
            <Shield className="w-5 h-5 text-slate-400 mt-0.5 flex-shrink-0" />
            <div className="text-xs text-slate-500 leading-relaxed">
              <p>{t('permissions.permissionsHint')}</p>
            </div>
          </div>
        </>
      )}

      {/* Empty state */}
      {!permsLoading && !permsError && permissions.length === 0 && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-12 text-center">
          <Shield className="w-12 h-12 text-slate-300 mx-auto mb-3" />
          <h3 className="text-lg font-semibold text-slate-600">{t('permissions.noPermissions')}</h3>
          <p className="text-sm text-slate-400 mt-1">{t('permissions.manageDesc')}</p>
        </div>
      )}
    </div>
  );
}

// ── Permission Section Sub-component ──────────────────────────────────────

interface PermissionSectionProps {
  title: string;
  description: string;
  icon: React.ReactNode;
  iconBg: string;
  borderColor: string;
  items: PermissionItem[];
  isUpdating: boolean;
  onToggle: (key: string, enabled: boolean) => void;
}

const ROLE_CONFIG: Record<string, { label: string; bg: string; text: string }> = {
  root: { label: 'Root', bg: 'bg-amber-100', text: 'text-amber-700' },
  admin: { label: 'Admin', bg: 'bg-indigo-100', text: 'text-indigo-700' },
  member: { label: 'Member', bg: 'bg-emerald-100', text: 'text-emerald-700' },
};

function PermissionSection({
  title,
  description,
  icon,
  iconBg,
  borderColor,
  items,
  isUpdating,
  onToggle,
}: PermissionSectionProps) {
  const { t } = useTranslation();

  return (
    <div className={`bg-white rounded-2xl shadow-sm border ${borderColor} overflow-hidden`}>
      {/* Section Header */}
      <div className="px-6 py-4 border-b border-slate-100 flex items-center space-x-3">
        <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${iconBg}`}>
          {icon}
        </div>
        <div className="flex-1">
          <h3 className="text-sm font-bold text-slate-800">{title}</h3>
          <p className="text-xs text-slate-400">{description}</p>
        </div>
        <span className="text-xs text-slate-400">{items.length} {t('permissions.points')}</span>
      </div>

      {/* Permission Items */}
      <div className="divide-y divide-slate-50">
        {items.map(item => (
          <div
            key={item.key}
            className="px-6 py-4 flex items-center justify-between hover:bg-slate-50/50 transition-colors"
          >
            <div className="flex-1 min-w-0 mr-4">
              <div className="flex items-center flex-wrap gap-2 mb-1">
                <h4 className="text-sm font-semibold text-slate-700">{item.label}</h4>
                <span className="text-[10px] font-mono text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded">
                  {item.key}
                </span>
              </div>
              {item.description && (
                <p className="text-xs text-slate-400 mb-2 line-clamp-2">{item.description}</p>
              )}
              {/* Allowed roles badges */}
              <div className="flex items-center flex-wrap gap-1.5">
                <span className="text-[10px] text-slate-400">{t('permissions.allRoles')}:</span>
                {(item.allowed_roles || []).map(role => {
                  const cfg = ROLE_CONFIG[role];
                  if (!cfg) return null;
                  return (
                    <span
                      key={role}
                      className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${cfg.bg} ${cfg.text}`}
                    >
                      {cfg.label}
                    </span>
                  );
                })}
              </div>
            </div>

            <button
              onClick={() => onToggle(item.key, !item.is_enabled)}
              disabled={isUpdating}
              className={`flex-shrink-0 p-1.5 rounded-lg transition-all duration-200 cursor-pointer
                ${item.is_enabled
                  ? 'bg-emerald-50 text-emerald-600 hover:bg-emerald-100'
                  : 'bg-slate-100 text-slate-400 hover:bg-slate-200'
                }
                disabled:opacity-50 disabled:cursor-not-allowed
                focus:outline-none focus:ring-2 focus:ring-indigo-500/20
              `}
              title={item.is_enabled ? t('permissions.disable') : t('permissions.enable')}
            >
              {item.is_enabled ? (
                <ToggleRight className="w-6 h-6" />
              ) : (
                <ToggleLeft className="w-6 h-6" />
              )}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}