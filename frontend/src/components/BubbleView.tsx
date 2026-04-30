import { useEffect, useRef, useState, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import type { WorkspaceRateLimitStatus } from '../api/client';
import { X, Key, Users, Server } from 'lucide-react';

function fmtNum(n: number): string {
  if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e4) return (n / 1e3).toFixed(1) + 'K';
  return n.toLocaleString();
}

export interface BubbleData {
  key: string;
  model_name: string;
  provider_name: string;
  provider_type: string;
  group_name: string;
  rpm_used: number;
  tpm_used: number;
  rpm_limit: number | null;
  tpm_limit: number | null;
  pct: number;
  total_usage: number;
  apikeys?: { name: string; group_name: string; rpm: number; tpm: number }[];
}

export function buildBubbleData(wsLimits: WorkspaceRateLimitStatus[]): BubbleData[] {
  const r: BubbleData[] = [];
  for (const rl of wsLimits) {
    const apis = (rl.apikeys || []).map(k => ({
      name: k.api_key_name || k.preview,
      group_name: k.group_name || '',
      rpm: k.rpm_used,
      tpm: k.tpm_used,
    }));

    const uR = rl.rpm?.used ?? 0;
    const uT = rl.tpm?.used ?? 0;
    const pR = rl.rpm?.limit ? Math.round(uR / rl.rpm.limit * 100) : 0;
    const pT = rl.tpm?.limit ? Math.round(uT / rl.tpm.limit * 100) : 0;

    const pvs = rl.providers ?? [];
    const providerMaxPct = pvs.reduce((max, p) => {
      const ppR = p.rpm_limit ? Math.round(p.rpm_used / p.rpm_limit * 100) : 0;
      const ppT = p.tpm_limit ? Math.round(p.tpm_used / p.tpm_limit * 100) : 0;
      return Math.max(max, ppR, ppT);
    }, 0);

    r.push({
      key: `ws-${rl.model_name}-${rl.provider_type || 's'}-${rl.provider_id ?? 'shared'}`,
      model_name: rl.model_name,
      provider_name: rl.provider_name || rl.provider_type || 'Shared',
      provider_type: rl.provider_type || '',
      group_name: '',
      rpm_used: uR,
      tpm_used: uT,
      rpm_limit: rl.rpm?.limit ?? null,
      tpm_limit: rl.tpm?.limit ?? null,
      pct: Math.max(pR, pT, providerMaxPct),
      total_usage: (uR + uT / 1000) || 0.001,
      apikeys: apis,
    });
  }
  return r;
}

const COLORS = {
  crit: 0xef4444,
  high: 0xf97316,
  mid: 0xeab308,
  low: 0x4ade80,
  idle: 0x22d3ee,
};
const EMIS = {
  crit: 0x7f1d1d,
  high: 0x7c2d12,
  mid: 0x713f12,
  low: 0x14532d,
  idle: 0x083344,
};
const GLOW = {
  crit: 0xfca5a5,
  high: 0xfdba74,
  mid: 0xfef08a,
  low: 0x86efac,
  idle: 0x67e8f9,
};

function pick(pct: number, set: Record<string, number>): number {
  if (pct >= 90) return set.crit;
  if (pct >= 75) return set.high;
  if (pct >= 50) return set.mid;
  if (pct >= 25) return set.low;
  return set.idle;
}

function colorHex(pct: number): string {
  return '#' + pick(pct, COLORS).toString(16).padStart(6, '0');
}

function DetailPanel({ d, onClose }: { d: BubbleData; onClose: () => void }) {
  const { t } = useTranslation();
  const rpmP = d.rpm_limit ? Math.round(d.rpm_used / d.rpm_limit * 100) : 0;
  const tpmP = d.tpm_limit ? Math.round(d.tpm_used / d.tpm_limit * 100) : 0;
  return (
    <div className="absolute top-4 right-4 w-80 bg-slate-900/95 backdrop-blur-lg border border-slate-700/50 rounded-2xl shadow-2xl z-20 overflow-hidden pointer-events-auto">
      <div className="flex items-center justify-between p-4 border-b border-slate-700/50">
        <h3 className="font-bold text-white text-sm truncate max-w-[200px]">{d.model_name}</h3>
        <button
          onClick={onClose}
          className="p-1 rounded-lg hover:bg-slate-700 text-slate-400"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className="p-4 space-y-3">
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <Server className="w-3.5 h-3.5" />
          <span>{d.provider_name}</span>
          {d.group_name && <span className="text-slate-500">· {d.group_name}</span>}
          <span
            className="ml-auto px-2 py-0.5 rounded-full text-[10px] font-medium"
            style={{
              background: '#' + pick(d.pct, EMIS).toString(16).padStart(6, '0'),
              color: '#' + pick(d.pct, GLOW).toString(16).padStart(6, '0'),
            }}
          >
            {d.pct}%
          </span>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div className="bg-slate-800 rounded-xl p-3">
            <div className="text-[10px] text-slate-500 mb-1">RPM</div>
            <div className="font-mono font-bold text-sm text-white">
              {fmtNum(d.rpm_used)}
              {d.rpm_limit ? (
                <span className="text-xs text-slate-500 font-normal">
                  /{fmtNum(d.rpm_limit)}
                </span>
              ) : null}
            </div>
            {d.rpm_limit ? (
              <div className="mt-1.5 h-1 bg-slate-700 rounded-full">
                <div
                  className="h-full rounded-full"
                  style={{
                    width: Math.min(rpmP, 100) + '%',
                    background: colorHex(rpmP),
                  }}
                />
              </div>
            ) : null}
          </div>
          <div className="bg-slate-800 rounded-xl p-3">
            <div className="text-[10px] text-slate-500 mb-1">TPM</div>
            <div className="font-mono font-bold text-sm text-white">
              {fmtNum(d.tpm_used)}
              {d.tpm_limit ? (
                <span className="text-xs text-slate-500 font-normal">
                  /{fmtNum(d.tpm_limit)}
                </span>
              ) : null}
            </div>
            {d.tpm_limit ? (
              <div className="mt-1.5 h-1 bg-slate-700 rounded-full">
                <div
                  className="h-full rounded-full"
                  style={{
                    width: Math.min(tpmP, 100) + '%',
                    background: colorHex(tpmP),
                  }}
                />
              </div>
            ) : null}
          </div>
        </div>
        {d.apikeys && d.apikeys.length > 0 && (
          <div>
            <h4 className="text-[10px] text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <Key className="w-3 h-3" />
              {t('rateLimits.apiKeyUsage')}
            </h4>
            <div className="space-y-1 max-h-48 overflow-y-auto">
              {d.apikeys.map((k, i) => (
                <div
                  key={i}
                  className="flex items-center gap-2 bg-slate-800/50 rounded-lg px-3 py-2 text-xs"
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-slate-300 truncate font-medium">{k.name}</div>
                    {k.group_name ? (
                      <div className="text-[10px] text-slate-500 flex items-center gap-1">
                        <Users className="w-2.5 h-2.5" />
                        {k.group_name}
                      </div>
                    ) : null}
                  </div>
                  <div className="text-right flex-shrink-0">
                    <div className="font-mono text-slate-400 text-[10px]">
                      {fmtNum(k.rpm)} <span className="text-slate-600">RPM</span>
                    </div>
                    <div className="font-mono text-slate-400 text-[10px]">
                      {fmtNum(k.tpm)} <span className="text-slate-600">TPM</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Legend() {
  const items = [
    { l: '≥90%', c: '#ef4444', g: '#fca5a5' },
    { l: '75-90%', c: '#f97316', g: '#fdba74' },
    { l: '50-75%', c: '#eab308', g: '#fef08a' },
    { l: '25-50%', c: '#4ade80', g: '#86efac' },
    { l: '<25%', c: '#22d3ee', g: '#67e8f9' },
  ];
  return (
    <div className="absolute bottom-4 left-4 flex flex-wrap gap-2 z-10 pointer-events-none">
      {items.map(x => (
        <div
          key={x.l}
          className="flex items-center gap-1.5 bg-slate-900/80 backdrop-blur-sm rounded-full px-3 py-1.5 border border-slate-700/40"
        >
          <div
            className="w-2.5 h-2.5 rounded-full"
            style={{ background: x.c, boxShadow: `0 0 6px ${x.g}` }}
          />
          <span className="text-[10px] text-slate-400">{x.l}</span>
        </div>
      ))}
    </div>
  );
}

export default function BubbleView({
  wsLimits,
}: {
  wsLimits: WorkspaceRateLimitStatus[];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const animRef = useRef<number>(0);
  const sceneRef = useRef<{
    scene: THREE.Scene;
    cam: THREE.PerspectiveCamera;
    rend: THREE.WebGLRenderer;
    ctrl: OrbitControls;
    meshes: { mesh: THREE.Mesh; ring: THREE.Mesh; data: BubbleData }[];
    rc: THREE.Raycaster;
    stars: THREE.Points;
  } | null>(null);
  const [selected, setSelected] = useState<BubbleData | null>(null);

  const bubbles = useMemo(() => buildBubbleData(wsLimits), [wsLimits]);
  const mU = useMemo(
    () => Math.max(...bubbles.map(b => b.total_usage || 0.001), 0.001),
    [bubbles],
  );

  const getR = useCallback((u: number) => 0.5 + (u / mU) * 3.0, [mU]);

  useEffect(() => {
    if (!containerRef.current || bubbles.length === 0) return;
    const el = containerRef.current;
    const W = el.clientWidth;
    const H = Math.max(el.clientHeight, 520);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color('#050514');
    scene.fog = new THREE.FogExp2('#050514', 0.0001);

    const cam = new THREE.PerspectiveCamera(50, W / H, 0.1, 100);
    cam.position.set(0, 2, 14);
    cam.lookAt(0, 0, 0);

    const rend = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    rend.setSize(W, H);
    rend.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    rend.toneMapping = THREE.ACESFilmicToneMapping;
    rend.toneMappingExposure = 1.2;
    el.appendChild(rend.domElement);

    const ctrl = new OrbitControls(cam, rend.domElement);
    ctrl.enableDamping = true;
    ctrl.dampingFactor = 0.08;
    ctrl.minDistance = 5;
    ctrl.maxDistance = 30;
    ctrl.maxPolarAngle = Math.PI * 0.75;
    ctrl.autoRotate = true;
    ctrl.autoRotateSpeed = 0.4;
    ctrl.target.set(0, 0, 0);
    ctrl.update();

    // Lighting
    scene.add(new THREE.AmbientLight('#334155', 0.5));
    const dl = new THREE.DirectionalLight('#ffffff', 0.7);
    dl.position.set(5, 10, 5);
    scene.add(dl);
    const p1 = new THREE.PointLight('#60a5fa', 1.5, 20);
    p1.position.set(-5, 2, 5);
    scene.add(p1);
    const p2 = new THREE.PointLight('#a78bfa', 1.5, 20);
    p2.position.set(5, -1, -5);
    scene.add(p2);

    // Grid
    const grid = new THREE.PolarGridHelper(8, 24, 16, 64, '#1e293b', '#1e293b');
    scene.add(grid);

    // Stars background
    const starGeo = new THREE.BufferGeometry();
    const sp = new Float32Array(600 * 3);
    for (let i = 0; i < 600; i++) {
      sp[i * 3] = (Math.random() - 0.5) * 50;
      sp[i * 3 + 1] = (Math.random() - 0.5) * 35;
      sp[i * 3 + 2] = (Math.random() - 0.5) * 25;
    }
    starGeo.setAttribute('position', new THREE.BufferAttribute(sp, 3));
    const stars = new THREE.Points(
      starGeo,
      new THREE.PointsMaterial({
        color: '#334155',
        size: 0.03,
        transparent: true,
        opacity: 0.5,
      }),
    );
    scene.add(stars);

    // Raycaster for click detection
    const rc = new THREE.Raycaster();
    const meshes: {
      mesh: THREE.Mesh;
      ring: THREE.Mesh;
      data: BubbleData;
    }[] = [];
    const n = bubbles.length;
    const gr = (1 + Math.sqrt(5)) / 2; // golden ratio for spherical distribution

    for (let i = 0; i < n; i++) {
      const bd = bubbles[i];
      const tot = bd.total_usage || 0.001;
      const rad = getR(tot);

      const geo = new THREE.SphereGeometry(rad, 48, 48);
      const mat = new THREE.MeshStandardMaterial({
        color: pick(bd.pct, COLORS),
        emissive: pick(bd.pct, EMIS),
        emissiveIntensity: 0.5,
        roughness: 0.25,
        metalness: 0.1,
      });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.castShadow = true;
      (mesh as any).__bd = bd;

      // Glow ring
      const rGeo = new THREE.TorusGeometry(rad * 1.15, 0.04, 16, 48);
      const rMat = new THREE.MeshBasicMaterial({
        color: pick(bd.pct, GLOW),
        transparent: true,
        opacity: 0.5,
      });
      const ring = new THREE.Mesh(rGeo, rMat);
      ring.rotation.x = Math.PI / 2;
      mesh.add(ring);

      // Position using Fibonacci sphere distribution
      if (n === 1) {
        mesh.position.set(0, 0, 0);
      } else {
        const theta = Math.acos(1 - (2 * (i + 0.5)) / n);
        const phi = (2 * Math.PI * i) / gr;
        const r = 5 + (tot / mU) * 3;
        mesh.position.set(
          r * Math.sin(theta) * Math.cos(phi),
          r * Math.sin(theta) * Math.sin(phi),
          r * Math.cos(theta),
        );
      }
      scene.add(mesh);
      meshes.push({ mesh, ring, data: bd });
    }

    sceneRef.current = { scene, cam, rend, ctrl, meshes, rc, stars };

    const clock = new THREE.Clock();
    const animate = () => {
      animRef.current = requestAnimationFrame(animate);
      const t = clock.getElapsedTime();
      ctrl.update();

      // Animate rings and mesh rotation
      meshes.forEach((m, j) => {
        const pulse = 1 + Math.sin(t * 2 + j) * 0.06 * (m.data.pct / 100);
        m.ring.scale.setScalar(pulse);
        (m.ring.material as THREE.MeshBasicMaterial).opacity =
          0.3 + Math.sin(t * 2 + j) * 0.2;
        m.mesh.rotation.y += 0.003;
        m.mesh.rotation.x += 0.001;
      });
      stars.rotation.y += 0.0001;
      stars.rotation.x += 0.00005;
      rend.render(scene, cam);
    };
    animate();

    const onResize = () => {
      const w2 = el.clientWidth;
      const h2 = Math.max(el.clientHeight, 520);
      cam.aspect = w2 / h2;
      cam.updateProjectionMatrix();
      rend.setSize(w2, h2);
    };
    window.addEventListener('resize', onResize);

    return () => {
      cancelAnimationFrame(animRef.current);
      window.removeEventListener('resize', onResize);
      rend.dispose();
      if (el.contains(rend.domElement)) el.removeChild(rend.domElement);
    };
  }, [bubbles, mU, getR]);

  const onCanvasClick = useCallback(
    (e: React.MouseEvent) => {
      if (!sceneRef.current) return;
      const el = containerRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const mx = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      const my = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      sceneRef.current.rc.setFromCamera(
        new THREE.Vector2(mx, my),
        sceneRef.current.cam,
      );
      const hits = sceneRef.current.rc.intersectObjects(
        sceneRef.current.meshes.map(m => m.mesh),
      );
      if (hits.length > 0) {
        setSelected((hits[0].object as any).__bd as BubbleData);
      } else {
        setSelected(null);
      }
    },
    [],
  );

  if (bubbles.length === 0) return null;

  return (
    <div
      ref={containerRef}
      className="relative w-full rounded-2xl overflow-hidden border border-slate-700/30 cursor-pointer"
      style={{ minHeight: 520 }}
      onClick={onCanvasClick}
    >
      <Legend />
      {selected && <DetailPanel d={selected} onClose={() => setSelected(null)} />}
      <div className="absolute top-4 left-4 bg-slate-900/70 backdrop-blur-sm rounded-lg px-3 py-1.5 border border-slate-700/40 z-10 pointer-events-none">
        <span className="text-[11px] text-slate-400">
          点击球体查看详情 · 拖拽旋转 · 滚轮缩放
        </span>
      </div>
    </div>
  );
}