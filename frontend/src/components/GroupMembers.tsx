import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { apiClient } from '../api/client';

interface Group {
  id: number;
  name: string;
  description?: string;
}

interface Member {
  id: number;
  username: string;
  email?: string;
  role: string;
  joined_at: string;
}

interface User {
  id: number;
  username: string;
  email?: string;
}

interface GroupMembersProps {
  group: Group;
  isAdmin: boolean;
}

export default function GroupMembers({ group, isAdmin }: GroupMembersProps) {
  const { addToast } = useAuth();
  const [members, setMembers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(true);
  const [showInviteDialog, setShowInviteDialog] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<User[]>([]);
  const [searching, setSearching] = useState(false);

  const fetchMembers = useCallback(async () => {
    try {
      setLoading(true);
      const res = await apiClient.get(`/api/groups/${group.id}/members`);
      setMembers(res.data);
    } catch {
      addToast('Failed to load members', 'error');
    } finally {
      setLoading(false);
    }
  }, [group.id, addToast]);

  useEffect(() => {
    fetchMembers();
  }, [fetchMembers]);

  const fetchUsers = async (query: string) => {
    try {
      setSearching(true);
      const res = await apiClient.get('/api/users', {
        params: { search: query },
      });
      // Filter out users who are already members
      const memberIds = members.map((m) => m.id);
      setSearchResults(
        res.data.filter((u: User) => !memberIds.includes(u.id))
      );
    } catch {
      addToast('Failed to search users', 'error');
    } finally {
      setSearching(false);
    }
  };

  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setSearchQuery(e.target.value);
    if (e.target.value.trim()) {
      fetchUsers(e.target.value.trim());
    } else {
      setSearchResults([]);
    }
  };

  const handleInviteUser = async (userId: number) => {
    try {
      await apiClient.post(`/api/groups/${group.id}/members`, {
        user_id: userId,
        role: 'member',
      });
      addToast('User invited successfully', 'success');
      setShowInviteDialog(false);
      setSearchQuery('');
      setSearchResults([]);
      fetchMembers();
    } catch {
      addToast('Failed to invite user', 'error');
    }
  };

  const handleRemoveMember = async (userId: number) => {
    if (!confirm('Are you sure you want to remove this member?')) return;
    try {
      await apiClient.delete(`/api/groups/${group.id}/members/${userId}`);
      addToast('Member removed successfully', 'success');
      fetchMembers();
    } catch {
      addToast('Failed to remove member', 'error');
    }
  };

  const handleRoleChange = async (userId: number, newRole: string) => {
    try {
      await apiClient.put(`/api/groups/${group.id}/members/${userId}`, {
        role: newRole,
      });
      addToast('Role updated successfully', 'success');
      fetchMembers();
    } catch {
      addToast('Failed to update role', 'error');
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-lg font-semibold text-gray-900">
          Members ({members.length})
        </h2>
        {isAdmin && (
          <button
            onClick={() => setShowInviteDialog(true)}
            className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500"
          >
            Invite User
          </button>
        )}
      </div>

      {/* Members Table */}
      <div className="bg-white shadow overflow-hidden sm:rounded-lg">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                User
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Role
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Joined
              </th>
              {isAdmin && (
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Actions
                </th>
              )}
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {members.map((member) => (
              <tr key={member.id}>
                <td className="px-6 py-4 whitespace-nowrap">
                  <div className="flex items-center">
                    <div className="ml-0">
                      <div className="text-sm font-medium text-gray-900">
                        {member.username}
                      </div>
                      {member.email && (
                        <div className="text-sm text-gray-500">
                          {member.email}
                        </div>
                      )}
                    </div>
                  </div>
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  {isAdmin && member.role !== 'owner' ? (
                    <select
                      value={member.role}
                      onChange={(e) =>
                        handleRoleChange(member.id, e.target.value)
                      }
                      className="text-sm border-gray-300 rounded-md shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
                    >
                      <option value="admin">Admin</option>
                      <option value="member">Member</option>
                    </select>
                  ) : (
                    <span
                      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                        member.role === 'owner'
                          ? 'bg-purple-100 text-purple-800'
                          : member.role === 'admin'
                          ? 'bg-indigo-100 text-indigo-800'
                          : 'bg-green-100 text-green-800'
                      }`}
                    >
                      {member.role}
                    </span>
                  )}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                  {new Date(member.joined_at).toLocaleDateString()}
                </td>
                {isAdmin && (
                  <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                    {member.role !== 'owner' && (
                      <button
                        onClick={() => handleRemoveMember(member.id)}
                        className="text-red-600 hover:text-red-900"
                      >
                        Remove
                      </button>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        {members.length === 0 && (
          <div className="px-6 py-4 text-center text-sm text-gray-500">
            No members found
          </div>
        )}
      </div>

      {/* Invite Dialog */}
      {showInviteDialog && (
        <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
            <div className="px-6 py-4 border-b border-gray-200">
              <h3 className="text-lg font-medium text-gray-900">
                Invite User to {group.name}
              </h3>
            </div>
            <div className="px-6 py-4">
              <input
                type="text"
                placeholder="Search users by name or email..."
                value={searchQuery}
                onChange={handleSearchChange}
                className="w-full border-gray-300 rounded-md shadow-sm focus:border-indigo-500 focus:ring-indigo-500 text-sm"
                autoFocus
              />
              {searching && (
                <div className="mt-4 flex justify-center">
                  <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-indigo-600"></div>
                </div>
              )}
              {searchResults.length > 0 && (
                <div className="mt-4 max-h-60 overflow-y-auto">
                  {searchResults.map((user) => (
                    <div
                      key={user.id}
                      className="flex items-center justify-between py-2 px-3 hover:bg-gray-50 rounded-md"
                    >
                      <div>
                        <div className="text-sm font-medium text-gray-900">
                          {user.username}
                        </div>
                        {user.email && (
                          <div className="text-xs text-gray-500">
                            {user.email}
                          </div>
                        )}
                      </div>
                      <button
                        onClick={() => handleInviteUser(user.id)}
                        className="text-sm text-indigo-600 hover:text-indigo-900 font-medium"
                      >
                        Invite
                      </button>
                    </div>
                  ))}
                </div>
              )}
              {searchQuery.trim() && !searching && searchResults.length === 0 && (
                <div className="mt-4 text-sm text-gray-500 text-center">
                  No users found
                </div>
              )}
            </div>
            <div className="px-6 py-3 border-t border-gray-200 flex justify-end">
              <button
                onClick={() => {
                  setShowInviteDialog(false);
                  setSearchQuery('');
                  setSearchResults([]);
                }}
                className="px-4 py-2 text-sm font-medium text-gray-700 hover:text-gray-900"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}