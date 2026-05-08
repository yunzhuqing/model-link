import { useState, useEffect, useRef } from 'react';
import { X, Plus, ChevronDown } from 'lucide-react';
import { tagsApi, type Tag } from '../api/client';

interface TagEntry {
  name: string;
  value: string;
}

interface Props {
  value?: TagEntry[];
  onChange: (tags: TagEntry[]) => void;
}

export default function TagSelector({ value = [], onChange }: Props) {
  const [allTags, setAllTags] = useState<Tag[]>([]);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    tagsApi.list().then((res) => setAllTags(res.data)).catch(() => {});
  }, []);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const selectedKey = (t: TagEntry) => `${t.name}:${t.value}`;
  const tagKey = (t: Tag) => `${t.name}:${t.value}`;

  const selectedSet = new Set(value.map(selectedKey));
  const availableTags = allTags.filter((t) => !selectedSet.has(tagKey(t)));

  // Group available tags by name for display
  const grouped: Record<string, Tag[]> = {};
  for (const t of availableTags) {
    if (!grouped[t.name]) grouped[t.name] = [];
    grouped[t.name].push(t);
  }

  function addTag(tag: Tag) {
    onChange([...value, { name: tag.name, value: tag.value }]);
  }

  function removeTag(entry: TagEntry) {
    onChange(value.filter((t) => selectedKey(t) !== selectedKey(entry)));
  }

  return (
    <div ref={containerRef} className="relative">
      <div className="flex flex-wrap items-center gap-1 min-h-[36px] px-2 py-1 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800">
        {value.map((entry) => (
          <span
            key={selectedKey(entry)}
            className="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-full bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200"
          >
            <span className="font-medium">{entry.name}</span>
            <span>=</span>
            <span>{entry.value}</span>
            <button
              type="button"
              onClick={() => removeTag(entry)}
              className="ml-0.5 hover:text-red-600"
            >
              <X size={12} />
            </button>
          </span>
        ))}
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="inline-flex items-center gap-1 px-2 py-0.5 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
        >
          <Plus size={14} />
          <ChevronDown size={10} />
        </button>
      </div>

      {open && (
        <div className="absolute z-50 mt-1 w-full max-h-48 overflow-y-auto border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800 shadow-lg">
          {Object.keys(grouped).length === 0 ? (
            <div className="px-3 py-2 text-sm text-gray-400">No tags available</div>
          ) : (
            Object.entries(grouped).map(([name, tags]) => (
              <div key={name}>
                <div className="px-3 py-1 text-xs font-semibold text-gray-400 bg-gray-50 dark:bg-gray-750">
                  {name}
                </div>
                {tags.map((tag) => (
                  <button
                    key={tag.id}
                    type="button"
                    onClick={() => addTag(tag)}
                    className="w-full text-left px-3 py-1.5 text-sm hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300"
                  >
                    {tag.value}
                  </button>
                ))}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
