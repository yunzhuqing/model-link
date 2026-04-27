/**
 * UsageRecordsTable — Reusable paginated usage records table component.
 *
 * Displays usage records filtered by group_id or api_key_hash,
 * with pagination and model name search.
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import client from '../api/client';
import { Search, ChevronLeft, ChevronRight, Cpu } from 'lucide-react';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface UsageRecord {
  id: number;
  user_name: string | null;
  group_id: number | null;
  group_name: string | null;
  api_key_preview: string | null;
  api_key_name: string | null;
  model_name: string | null;
  provider_name: string | null;
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_tokens: number;
  reasoning_tokens: number;
  output_image_number: number;
  output_video_number: number;
  output_audio_seconds: number;
  web_search_requests: number;
  duration_ms: number | null;
  payable_amount: number;
  discount: number;
  actual_amount: number;
  currency?: string;
  created_at: string;
}

interface RecordsData {
  total: number;
  page: number;
  page_size: number;
  pages: number;
  records: UsageRecord[];
}

interface Props {
  groupId?: number;
  apiKeyHash?: string;
}

/* ── Helpers ────────────────────────────────────────────────────────────── */

function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return String(n);
}

function fmtAmount(amount: number | string | null | undefined, currency?: string): string {
  const v = Number(amount);
  if (amount == null || isNaN(v) || v === 0) return '—';
  const sym = (currency || 'USD').toUpperCase() === 'CNY' ? '¥' : '$';
  if (v < 0.0001) return `${sym}${v.toExponential(2)}`;
  if (v < 0.01) return `${sym}${v.toFixed(6)}`;
  if (v < 1) return `${sym}${v.toFixed(4)}`;
  return `${sym}${v.toFixed(4)}`;
}

function fmtDate(iso: string): string {
  try {
    let utcStr = iso;
    if (!utcStr.endsWith('Z') && !utcStr.includes('+') && !/[-]\d{2}:\d{2}$/.test(utcStr)) {
      utcStr += 'Z';
    }
    return new Date(utcStr).toLocaleString(undefined, {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
  } catch {
    return iso;
  }
}

function fmtDuration(ms: number | null): string {
  if (ms == null) return '—';
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}m${rem.toFixed(0)}s`;
}

/* ── Component ─────────────────────────────────────────────────────────── */

export default function UsageRecordsTable({ groupId, apiKeyHash }: Props) {
  const [page, setPage] = useState(1);
  const [modelFilter, setModelFilter] = useState('');

  const params = new URLSearchParams({
    page: String(page),
    page_size: '20',
    ...(groupId ? { group_id: String(groupId) } : {}),
    ...(apiKeyHash ? { api_key_hash: apiKeyHash } : {}),
    ...(modelFilter ? { model_name: modelFilter } : {}),
  });

  const { data, isLoading } = useQuery<RecordsData>({
    queryKey: ['usage-records-sub', params.toString()],
    queryFn: async () => {
      const res = await client.get(`/api/usage/records?${params}`);
      return res.data;
    },
  });

  return (
    <div>
      {/* Filter bar */}
      <div className="flex items-center gap-3 mb-4">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input
            type="text"
            placeholder="搜索模型名称..."
            value={modelFilter}
            onChange={(e) => { setModelFilter(e.target.value); setPage(1); }}
            className="w-full text-sm border border-slate-200 rounded-lg pl-9 pr-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-300"
          />
        </div>
        <span className="text-xs text-slate-400">
          共 {data?.total ?? 0} 条记录
        </span>
      </div>

      {/* Table */}
      {isLoading ? (
        <div className="text-center py-12 text-slate-400">加载中...</div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200">
                  {[
                    { label: '时间', align: 'text-left' },
                    { label: '模型', align: 'text-left' },
                    { label: 'Provider', align: 'text-left' },
                    { label: 'API Key', align: 'text-left' },
                    { label: '输入', align: 'text-center' },
                    { label: '输出', align: 'text-center' },
                    { label: '推理', align: 'text-center' },
                    { label: '图片', align: 'text-center' },
                    { label: '视频', align: 'text-center' },
                    { label: '金额', align: 'text-right' },
                    { label: '耗时', align: 'text-center' },
                  ].map((h) => (
                    <th key={h.label} className={`px-3 py-2.5 ${h.align} text-xs font-semibold text-slate-500 whitespace-nowrap`}>
                      {h.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {(data?.records ?? []).map((r) => (
                  <tr key={r.id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-3 py-2.5 text-slate-500 whitespace-nowrap text-xs">{fmtDate(r.created_at)}</td>
                    <td className="px-3 py-2.5 text-slate-800 font-medium max-w-[140px] truncate">{r.model_name || '—'}</td>
                    <td className="px-3 py-2.5 text-slate-600 whitespace-nowrap max-w-[100px] truncate">{r.provider_name || '—'}</td>
                    <td className="px-3 py-2.5">
                      <p className="text-slate-700 text-xs font-medium">{r.api_key_name || '—'}</p>
                      <p className="text-slate-400 font-mono text-xs">{r.api_key_preview || ''}</p>
                    </td>
                    <td className="px-3 py-2.5 text-indigo-700 font-mono text-center whitespace-nowrap">{fmtNum(r.input_tokens)}</td>
                    <td className="px-3 py-2.5 text-emerald-700 font-mono text-center whitespace-nowrap">{fmtNum(r.output_tokens)}</td>
                    <td className="px-3 py-2.5 text-violet-700 font-mono text-center whitespace-nowrap">
                      {r.reasoning_tokens > 0 ? fmtNum(r.reasoning_tokens) : '—'}
                    </td>
                    <td className="px-3 py-2.5 text-amber-700 text-center whitespace-nowrap">
                      {r.output_image_number > 0 ? r.output_image_number : '—'}
                    </td>
                    <td className="px-3 py-2.5 text-rose-700 text-center whitespace-nowrap">
                      {r.output_video_number > 0 ? r.output_video_number : '—'}
                    </td>
                    <td className="px-3 py-2.5 text-right whitespace-nowrap">
                      <span className="text-orange-700 font-mono text-xs font-medium">
                        {fmtAmount(r.actual_amount, r.currency)}
                      </span>
                      {r.discount != null && Number(r.discount) < 1 && (
                        <span className="ml-1 text-xs text-green-600 bg-green-50 px-1 py-0.5 rounded">
                          {Math.round((1 - Number(r.discount)) * 100)}%off
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-slate-600 font-mono text-center whitespace-nowrap text-xs">
                      {fmtDuration(r.duration_ms)}
                    </td>
                  </tr>
                ))}
                {(data?.records ?? []).length === 0 && (
                  <tr>
                    <td colSpan={11} className="text-center py-12 text-slate-400">
                      <Cpu className="w-10 h-10 mx-auto mb-2 text-slate-200" />
                      暂无消耗记录
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {(data?.pages ?? 0) > 1 && (
            <div className="flex items-center justify-between mt-4">
              <p className="text-sm text-slate-500">
                共 {data?.total} 条，第 {page} / {data?.pages} 页
              </p>
              <div className="flex gap-2">
                <button
                  disabled={page <= 1}
                  onClick={() => setPage((p) => p - 1)}
                  className="p-2 rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                <button
                  disabled={page >= (data?.pages ?? 1)}
                  onClick={() => setPage((p) => p + 1)}
                  className="p-2 rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
