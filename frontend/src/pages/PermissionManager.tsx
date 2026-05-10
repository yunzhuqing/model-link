import { useCallback, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import client from '../api/client';
import {
  Shield,
  Crown,
  UserCog,
  Users,
  AlertCircle,
  Loader2,
  Plus,
  X,
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

// ── Role definitions ───────────────────────────────────────────────────────

interface RoleDef {
  key: string;
  label: string;
  icon: React.ReactNode;
  iconBg: string;
  borderColor: string;
  description: string;
}

const ROLE_DEFS: RoleDef[] = [
  {
    key: 'root',
    label: 'Root',
    icon: <Crown className="w-5 h-5 text-amber-600" />,
    iconBg: 'bg-amber-100',
    borderColor: 'border-amber-200',
    description: 'rootRoleDesc',
  },
  {
    key: 'admin',
    label: 'Admin',
    icon: <UserCog className="w-5 h-5 text-indigo-600" />,
    iconBg: 'bg-indigo-100',
    borderColor: 'border-indigo-200',
    description: 'adminRoleDesc',
  },
  {
    key: 'member',
    label: 'Member',
    icon: <Users className="w-5 h-5 text-emerald-600" />,
    iconBg: 'bg-emerald-100',
    borderColor: 'border-emerald-200',
    description: 'memberRoleDesc',
  },
];

// ── Component ──────────────────────────────────────────────────────────────

export default function PermissionManager() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const { data: permData, isLoading, error } = useQuery<{
    permissions: PermissionItem[];
    is_root: boolean;
  }>({
    queryKey: ['global-permissions'],
    queryFn: async () => {
      const r = await client.get('/api/permissions');
      return r.data as { permissions: PermissionItem[]; is_root: boolean };
    },
  });

  const permissions = permData?.permissions ?? [];
  const isRoot = permData?.is_root ?? false;

  const updateMutation = useMutation({
    mutationFn: ({
      key,
      data,
    }: {
      key: string;
      data: Partial<Pick<PermissionItem, 'allowed_roles'>>;
    }) => client.put(`/api/permissions/${key}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['global-permissions'] });
    },
  });

  const handleAddPermission = useCallback(
    (role: string, permKey: string, currentRoles: string[]) => {
      updateMutation.mutate({
        key: permKey,
        data: { allowed_roles: [...currentRoles, role] },
      });
    },
    [updateMutation],
  );

  const handleRemovePermission = useCallback(
    (role: string, permKey: string, currentRoles: string[]) => {
      updateMutation.mutate({
        key: permKey,
        data: { allowed_roles: currentRoles.filter((r) => r !== role) },
      });
    },
    [updateMutation],
  );

  // ── Loading ──────────────────────────────────────────────────────────────
  if (isLoading && !permData) {
    return (
      <div className="flex justify-center items-center h-64">
        <Loader2 className="w-6 h-6 text-slate-400 animate-spin" />
        <span className="ml-2 text-slate-500">{t('common.loading')}</span>
      </div>
    );
  }

  // ── Not root ─────────────────────────────────────────────────────────────
  if (!isLoading && !isRoot) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">{t('permissions.pageTitle')}</h1>
          <p className="text-slate-500 mt-1">{t('permissions.pageSubtitle')}</p>
        </div>
        <div className="bg-amber-50 border border-amber-200 rounded-2xl p-6 flex items-start space-x-3">
          <AlertCircle className="w-5 h-5 text-amber-500 mt-0.5 shrink-0" />
          <div>
            <h4 className="text-sm font-medium text-amber-800">{t('permissions.rootOnly')}</h4>
            <p className="text-sm text-amber-600 mt-1">{t('permissions.rootOnlyDesc')}</p>
          </div>
        </div>
      </div>
    );
  }

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">{t('permissions.pageTitle')}</h1>
          <p className="text-slate-500 mt-1">{t('permissions.pageSubtitle')}</p>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-2xl p-6 flex items-start space-x-3">
          <AlertCircle className="w-5 h-5 text-red-500 mt-0.5 shrink-0" />
          <div>
            <h4 className="text-sm font-medium text-red-800">{t('permissions.loadFailed')}</h4>
            <p className="text-sm text-red-600 mt-1">{(error as Error)?.message || ''}</p>
          </div>
        </div>
      )}

      {!isLoading && !error && permissions.length > 0 && (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {ROLE_DEFS.map((roleDef) => (
              <RoleCard
                key={roleDef.key}
                roleDef={roleDef}
                allPermissions={permissions}
                isUpdating={updateMutation.isPending}
                onAdd={handleAddPermission}
                onRemove={handleRemovePermission}
                t={t}
              />
            ))}
          </div>

          <div className="bg-slate-50 border border-slate-200 rounded-2xl p-4 flex items-start space-x-3">
            <Shield className="w-5 h-5 text-slate-400 mt-0.5 shrink-0" />
            <div className="text-xs text-slate-500 leading-relaxed">
              <p>{t('permissions.permissionsHint')}</p>
            </div>
          </div>
        </>
      )}

      {!isLoading && !error && permissions.length === 0 && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-12 text-center">
          <Shield className="w-12 h-12 text-slate-300 mx-auto mb-3" />
          <h3 className="text-lg font-semibold text-slate-600">{t('permissions.noPermissions')}</h3>
          <p className="text-sm text-slate-400 mt-1">{t('permissions.manageDesc')}</p>
        </div>
      )}
    </div>
  );
}

// ── Role Card ──────────────────────────────────────────────────────────────

interface RoleCardProps {
  roleDef: RoleDef;
  allPermissions: PermissionItem[];
  isUpdating: boolean;
  onAdd: (role: string, permKey: string, currentRoles: string[]) => void;
  onRemove: (role: string, permKey: string, currentRoles: string[]) => void;
  t: (key: string, options?: Record<string, string>) => string;
}

function RoleCard({
  roleDef,
  allPermissions,
  isUpdating,
  onAdd,
  onRemove,
  t,
}: RoleCardProps) {
  const [adding, setAdding] = useState(false);

  const assignedPermissions = allPermissions.filter((p) =>
    (p.allowed_roles || []).includes(roleDef.key),
  );

  const availablePermissions = allPermissions.filter(
    (p) => !(p.allowed_roles || []).includes(roleDef.key),
  );

  return (
    <div className={`bg-white rounded-2xl shadow-sm border ${roleDef.borderColor} overflow-hidden flex flex-col`}>
      <div className="px-4 py-3 border-b border-slate-100 flex items-center space-x-2.5">
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${roleDef.iconBg}`}>
          {roleDef.icon}
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-bold text-slate-800">{roleDef.label}</h3>
          <p className="text-[11px] text-slate-400">{t(`permissions.${roleDef.description}`)}</p>
        </div>
      </div>

      <div className="flex-1 px-4 py-3 space-y-2 min-h-[120px]">
        {assignedPermissions.length === 0 ? (
          <p className="text-xs text-slate-400 py-2">{t('permissions.noRolePermissions')}</p>
        ) : (
          assignedPermissions.map((perm) => (
            <div
              key={perm.key}
              className="flex items-center justify-between group"
            >
              <div className="flex-1 min-w-0">
                <span className="text-sm text-slate-700 truncate">{perm.label}</span>
                <span className="text-[10px] font-mono text-slate-400 ml-2">{perm.key}</span>
              </div>

              <button
                onClick={() =>
                  onRemove(roleDef.key, perm.key, perm.allowed_roles || [])
                }
                disabled={isUpdating}
                className="p-0.5 rounded text-slate-300 hover:text-red-500 hover:bg-red-50 transition-colors opacity-0 group-hover:opacity-100 disabled:cursor-not-allowed shrink-0 ml-2"
                title={t('permissions.removeFromRole', { role: roleDef.label })}
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          ))
        )}

        {adding ? (
          <div className="pt-1">
            <div className="bg-slate-50 rounded-lg border border-slate-200 p-2 max-h-40 overflow-y-auto space-y-0.5">
              {availablePermissions.length === 0 ? (
                <p className="text-xs text-slate-400 p-1">{t('permissions.allAssigned')}</p>
              ) : (
                availablePermissions.map((perm) => (
                  <button
                    key={perm.key}
                    type="button"
                    disabled={isUpdating}
                    onClick={() => {
                      onAdd(roleDef.key, perm.key, perm.allowed_roles || []);
                    }}
                    className="w-full text-left px-2 py-1.5 rounded text-sm text-slate-600 hover:bg-white hover:text-slate-800 transition-colors disabled:opacity-50"
                  >
                    <span>{perm.label}</span>
                    <span className="text-[10px] font-mono text-slate-400 ml-2">
                      {perm.key}
                    </span>
                  </button>
                ))
              )}
            </div>
            <button
              onClick={() => setAdding(false)}
              className="mt-1 text-xs text-slate-400 hover:text-slate-500"
            >
              {t('common.cancel')}
            </button>
          </div>
        ) : (
          <button
            onClick={() => setAdding(true)}
            disabled={isUpdating || availablePermissions.length === 0}
            className="flex items-center gap-1 text-xs text-slate-400 hover:text-indigo-500 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <Plus className="w-3.5 h-3.5" />
            {t('permissions.addPermission')}
          </button>
        )}
      </div>
    </div>
  );
}