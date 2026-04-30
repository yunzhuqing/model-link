import { createContext, useContext, useState, useEffect, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import client from '../api/client';

export interface WorkspaceSummary {
  id: number;
  name: string;
}

interface WorkspaceContextType {
  workspaces: WorkspaceSummary[];
  selectedWorkspace: WorkspaceSummary | null;
  setSelectedWorkspaceId: (id: number) => void;
  isLoading: boolean;
}

const WorkspaceContext = createContext<WorkspaceContextType>({
  workspaces: [],
  selectedWorkspace: null,
  setSelectedWorkspaceId: () => {},
  isLoading: false,
});

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [selectedId, setSelectedId] = useState<number | null>(() => {
    const saved = localStorage.getItem('selectedWorkspaceId');
    return saved ? Number(saved) : null;
  });

  const { data: workspaces = [], isLoading } = useQuery({
    queryKey: ['workspaces'],
    queryFn: async () => {
      const r = await client.get('/api/workspaces');
      return r.data as WorkspaceSummary[];
    },
  });

  // Auto-select first workspace if none selected
  useEffect(() => {
    if (selectedId === null && workspaces.length > 0) {
      setSelectedId(workspaces[0].id);
    }
  }, [workspaces, selectedId]);

  // Persist selection
  useEffect(() => {
    if (selectedId !== null) {
      localStorage.setItem('selectedWorkspaceId', String(selectedId));
    }
  }, [selectedId]);

  const selectedWorkspace = workspaces.find(w => w.id === selectedId) ?? null;

  return (
    <WorkspaceContext.Provider value={{
      workspaces,
      selectedWorkspace,
      setSelectedWorkspaceId: setSelectedId,
      isLoading,
    }}>
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace() {
  return useContext(WorkspaceContext);
}