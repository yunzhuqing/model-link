import { useState } from 'react';
import type { TimeSeriesByModel } from '../../api/types';
import { fmtCost, PIE_COLORS } from './utils';

interface Props {
  data: TimeSeriesByModel[];
}

const DailyCostByModelChart = ({ data }: Props) => {
  const [hovered, setHovered] = useState<{ bar: number; segment: string } | null>(null);
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number }>({ x: 0, y: 0 });

  if (!data || data.length === 0) {
    return <div className="text-center py-10 text-slate-400 text-sm">暂无模型消费数据</div>;
  }

  // Build a map of period → { model_name → cost }
  const periodMap: Record<string, Record<string, number>> = {};
  const modelSet = new Set<string>();
  for (const d of data) {
    const p = String(d.period);
    if (!periodMap[p]) periodMap[p] = {};
    periodMap[p][d.model_name || 'unknown'] = d.total_cost_usd || 0;
    modelSet.add(d.model_name || 'unknown');
  }

  // Sort models by total cost descending
  const modelTotalCost: Record<string, number> = {};
  for (const m of modelSet) {
    modelTotalCost[m] = Object.values(periodMap).reduce((s, pm) => s + (pm[m] || 0), 0);
  }
  const models = Array.from(modelSet).sort((a, b) => (modelTotalCost[b] || 0) - (modelTotalCost[a] || 0));
  const periods = Object.keys(periodMap).sort();

  const maxCost = Math.max(...periods.map(p => Object.values(periodMap[p]).reduce((s, v) => s + v, 0)), 0.001);

  /** Parse a period string into a localized Date, handling UTC suffixes. */
  function parsePeriod(raw: string): Date {
    return raw.includes('T')
      ? new Date((raw.endsWith('Z') || raw.includes('+') ? raw : raw + 'Z'))
      : new Date(raw + (raw.includes('T') ? '' : 'T00:00:00Z'));
  }

  /** Format a period string to a short local label (HH:MM or MM-DD). */
  function periodLabel(raw: string): string {
    const dt = parsePeriod(raw);
    if (raw.includes('T')) {
      return `${String(dt.getHours()).padStart(2, '0')}:${String(dt.getMinutes()).padStart(2, '0')}`;
    }
    return `${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;
  }

  /** Format a period string to a full local date-time string. */
  function fullPeriodLabel(raw: string): string {
    const dt = parsePeriod(raw);
    const y = dt.getFullYear();
    const m = String(dt.getMonth() + 1).padStart(2, '0');
    const d = String(dt.getDate()).padStart(2, '0');
    if (raw.includes('T')) {
      return `${y}-${m}-${d} ${String(dt.getHours()).padStart(2, '0')}:${String(dt.getMinutes()).padStart(2, '0')}`;
    }
    return `${y}-${m}-${d}`;
  }

  return (
    <div>
      {/* Chart area with subtle gradient background */}
      <div className="relative">
        {/* Y-axis labels */}
        <div className="absolute left-0 top-0 h-44 flex flex-col justify-between pointer-events-none z-20" style={{ width: '65px', paddingBottom: '16px' }}>
          {[1, 0.75, 0.5, 0.25, 0].map((f, i) => {
            const val = maxCost * f;
            return (
              <span key={i} className="text-[9px] text-slate-400 leading-none text-right pr-2">
                {fmtCost(val)}
              </span>
            );
          })}
        </div>
        {/* Background grid lines */}
        <div className="absolute inset-0 flex flex-col justify-between pointer-events-none" style={{ height: '176px', paddingBottom: '16px', marginLeft: '65px' }}>
          {[0, 1, 2, 3, 4].map(i => (
            <div key={i} className="border-t border-dashed border-slate-200/60 w-full" />
          ))}
        </div>
        {/* Bars */}
        <div className="flex items-end space-x-[3px] h-44 relative z-10" style={{ marginLeft: '65px' }}>
          {periods.map((p, i) => {
            const dayModels = periodMap[p];
            const segments = models.filter(m => (dayModels[m] || 0) > 0);
            const isH = hovered?.bar === i;
            const totalDayCost = Object.values(dayModels).reduce((s, v) => s + v, 0);
            return (
              <div key={i}
                className="flex-1 flex flex-col items-center relative group"
                onMouseEnter={(e) => {
                  setHovered({ bar: i, segment: '' });
                  setTooltipPos({ x: e.clientX, y: e.clientY });
                }}
                onMouseLeave={() => setHovered(null)}
                onMouseMove={(e) => setTooltipPos({ x: e.clientX, y: e.clientY })}
              >
                {/* Bar container with rounded top */}
                <div
                  className="w-full rounded-t-lg overflow-hidden transition-all duration-300 cursor-default relative"
                  style={{
                    height: `${Math.max(totalDayCost / maxCost * 160, 1)}px`,
                    opacity: isH && !hovered?.segment ? 1 : hovered !== null && isH ? 1 : hovered !== null ? 0.4 : 0.85,
                    filter: isH && !hovered?.segment ? 'brightness(1.1)' : 'none',
                  }}
                >
                  {/* Glass background */}
                  <div className="absolute inset-0 bg-gradient-to-b from-white/5 to-transparent" />
                  {segments.map((m, si) => {
                    const cost = dayModels[m] || 0;
                    const segH = (cost / maxCost) * 160;
                    const color = PIE_COLORS[models.indexOf(m) % PIE_COLORS.length];
                    const isLast = si === segments.length - 1;
                    const isSegmentHover = hovered?.segment === m;
                    return (
                      <div
                        key={si}
                        className={`w-full transition-all duration-200 relative ${isLast ? 'rounded-b-sm' : ''}`}
                        style={{
                          height: `${segH}px`,
                          background: `linear-gradient(135deg, ${color}, ${color}bb)`,
                          opacity: isSegmentHover ? 1 : hovered?.segment && !isSegmentHover ? 0.5 : 1,
                          filter: isSegmentHover ? 'brightness(1.15) saturate(1.2)' : 'none',
                        }}
                        onMouseEnter={(e) => {
                          setHovered({ bar: i, segment: m });
                          setTooltipPos({ x: e.clientX, y: e.clientY });
                        }}
                      >
                        {/* Shimmer effect on hover */}
                        {isSegmentHover && (
                          <div className="absolute inset-0 animate-shimmer-fast"
                            style={{
                              background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent)',
                              backgroundSize: '200% 100%',
                            }} />
                        )}
                      </div>
                    );
                  })}
                </div>
                {/* X-axis label underneath the bar */}
                <span className="text-[10px] mt-1.5 text-center leading-tight transition-colors duration-200"
                  style={{
                    color: isH ? '#334155' : (i % Math.max(1, Math.ceil(periods.length / 7)) === 0 || i === periods.length - 1 ? '#94a3b8' : 'transparent'),
                    userSelect: 'none',
                    pointerEvents: 'none',
                    fontSize: '9px',
                  }}>
                  {periodLabel(p)}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Floating tooltip */}
      {hovered && (
        <div className="fixed z-50 pointer-events-none" style={{ left: tooltipPos.x + 12, top: tooltipPos.y - 10 }}>
          <div className="bg-slate-900/95 backdrop-blur-sm text-white text-xs px-3 py-2 rounded-xl shadow-2xl border border-white/10 max-w-[220px]">
            <div className="font-semibold text-white/90 mb-1">
              {fullPeriodLabel(periods[hovered.bar])}
            </div>
            {hovered.segment ? (
              <div>
                <div className="flex items-center gap-1.5 opacity-70">
                  <span className="w-2 h-2 rounded-full inline-block flex-shrink-0" style={{ backgroundColor: PIE_COLORS[models.indexOf(hovered.segment) % PIE_COLORS.length] }} />
                  <span className="truncate">{hovered.segment}</span>
                </div>
                <div className="font-medium text-white mt-0.5">{fmtCost(periodMap[periods[hovered.bar]][hovered.segment] || 0)}</div>
              </div>
            ) : (
              <div className="text-white/80">
                总计: <span className="font-medium text-white">{fmtCost(Object.values(periodMap[periods[hovered.bar]]).reduce((s, v) => s + v, 0))}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Legend */}
      <div className="flex items-center gap-3 mt-3 text-xs text-slate-500 flex-wrap">
        {models.slice(0, 8).map((m, i) => {
          const color = PIE_COLORS[i % PIE_COLORS.length];
          const isActive = !hovered || hovered.segment === m || !hovered.segment;
          return (
            <span key={i} className={`flex items-center gap-1.5 transition-all duration-200 ${isActive ? 'opacity-100' : 'opacity-40'}`}>
              <span className="w-2.5 h-2.5 rounded-full" style={{
                background: `linear-gradient(135deg, ${color}, ${color}bb)`,
                boxShadow: hovered?.segment === m ? `0 0 6px ${color}66` : 'none',
              }} />
              <span className="truncate max-w-[120px]">{m}</span>
            </span>
          );
        })}
        {models.length > 8 && <span className="text-slate-400">+{models.length - 8}</span>}
      </div>
    </div>
  );
};

export default DailyCostByModelChart;