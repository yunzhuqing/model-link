import { useState, useEffect, useRef, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { X, Plus, ChevronDown, Search } from 'lucide-react';
import { groupsApi, type Group } from '../api/client';

interface Props {
  value?: number[];
  onChange: (ids: number[]) => void;
  placeholder?: string;
}

/** Multi-select dropdown of groups with search. Selected ids render as chips. */
export default function GroupMultiSelect({ value = [], onChange, placeholder = '全部分组' }: Props) {
  const [allGroups, setAllGroups] = useState<Group[]>([]);
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [dropdownStyle, setDropdownStyle] = useState<React.CSSProperties>({});
  const containerRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    groupsApi.list().then((res) => setAllGroups(res.data)).catch(() => {});
  }, []);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      const target = e.target as Node;
      if (
        containerRef.current && !containerRef.current.contains(target) &&
        dropdownRef.current && !dropdownRef.current.contains(target)
      ) {
        setOpen(false);
        setSearch('');
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  useEffect(() => {
    if (open && searchInputRef.current) {
      searchInputRef.current.focus();
    }
  }, [open]);

  const selectedSet = useMemo(() => new Set(value), [value]);

  const selectedGroups = useMemo(
    () => allGroups.filter((g) => selectedSet.has(g.id)),
    [allGroups, selectedSet],
  );

  const available = useMemo(() => {
    const q = search.toLowerCase().trim();
    return allGroups
      .filter((g) => !selectedSet.has(g.id))
      .filter((g) => !q || g.name.toLowerCase().includes(q) || String(g.id).includes(q));
  }, [allGroups, selectedSet, search]);

  function toggleDropdown() {
    if (!open && buttonRef.current) {
      const rect = buttonRef.current.getBoundingClientRect();
      setDropdownStyle({
        position: 'fixed',
        top: rect.bottom + 4,
        left: rect.left,
        width: Math.max(rect.width, 240),
        maxWidth: 380,
        zIndex: 9999,
      });
      setSearch('');
    }
    setOpen(!open);
  }

  function addGroup(id: number) {
    if (!selectedSet.has(id)) onChange([...value, id]);
    setSearch('');
  }

  function removeGroup(id: number) {
    onChange(value.filter((v) => v !== id));
  }

  return (
    <div ref={containerRef} className="relative">
      <div className="flex flex-wrap items-center gap-1 min-h-[38px] px-2 py-1 border border-slate-200 rounded-lg bg-white focus-within:ring-2 focus-within:ring-blue-300">
        {selectedGroups.map((g) => (
          <span
            key={g.id}
            className="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-full bg-blue-100 text-blue-800"
          >
            <span className="font-medium">{g.name}</span>
            <button
              type="button"
              onClick={() => removeGroup(g.id)}
              className="ml-0.5 hover:text-red-600"
            >
              <X size={12} />
            </button>
          </span>
        ))}
        <button
          ref={buttonRef}
          type="button"
          onClick={toggleDropdown}
          className="inline-flex items-center gap-1 px-2 py-0.5 text-xs text-slate-500 hover:text-slate-700"
        >
          {selectedGroups.length === 0 && (
            <span className="text-slate-400">{placeholder}</span>
          )}
          <Plus size={14} />
          <ChevronDown size={10} />
        </button>
      </div>

      {open && createPortal(
        <div ref={dropdownRef} style={dropdownStyle} className="border border-slate-200 rounded-lg bg-white shadow-lg overflow-hidden">
          <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-100">
            <Search size={14} className="text-slate-400 shrink-0" />
            <input
              ref={searchInputRef}
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索分组名称或 ID..."
              className="w-full text-sm bg-transparent border-none outline-none text-slate-700 placeholder-slate-400"
            />
          </div>
          <div className="max-h-56 overflow-y-auto">
            {available.length === 0 ? (
              <div className="px-3 py-2 text-sm text-slate-400">
                {search ? '无匹配分组' : '无可选分组'}
              </div>
            ) : (
              available.map((g) => (
                <button
                  key={g.id}
                  type="button"
                  onClick={() => addGroup(g.id)}
                  className="w-full text-left px-3 py-1.5 text-sm hover:bg-slate-100 text-slate-700 flex items-center justify-between gap-2"
                >
                  <span>{g.name}</span>
                  <span className="text-xs text-slate-400">#{g.id}</span>
                </button>
              ))
            )}
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
