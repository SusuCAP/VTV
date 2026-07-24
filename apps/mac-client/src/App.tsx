import {
  AlertTriangle,
  Archive,
  Box,
  Check,
  ChevronRight,
  CirclePlay,
  Clapperboard,
  Download,
  FileText,
  FolderKanban,
  Loader2,
  PauseCircle,
  Play,
  Plus,
  RefreshCw,
  Upload,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  approveDelivery,
  cancelProject,
  createProject,
  getDeliveryPackage,
  listDeliveries,

  loadLatestProject,
  pauseProject,
  resumeProject,
  startProjectAnalysis,
  type ApiCreateProject,
  type ApiDelivery,
  type ApiJob,
  type ApiProject,
} from "./api";
import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./components/ui/card";
import { Input } from "./components/ui/input";
import { Label } from "./components/ui/label";
import { Progress } from "./components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./components/ui/select";
import { Separator } from "./components/ui/separator";
import { uploadEpisodeFromDialog } from "./localAgent";

// ── 类型 ──────────────────────────────────────────────────────────────────────
type Page = "projects" | "new-project" | "assets" | "production" | "exceptions" | "delivery";

// ── 工具函数 ───────────────────────────────────────────────────────────────────
function statusBadge(status: string) {
  const map: Record<string, "success" | "warning" | "destructive" | "info" | "secondary"> = {
    COMPLETED: "success", DONE: "success", "已完成": "success",
    RUNNING: "info", QUEUED: "warning", "进行中": "info",
    FAILED: "destructive", "失败": "destructive",
    PAUSED: "secondary", CANCELLED: "secondary",
  };
  return <Badge variant={map[status] ?? "secondary"}>{status}</Badge>;
}

// ── Sidebar ───────────────────────────────────────────────────────────────────
function Sidebar({ page, onPage }: { page: Page; onPage: (p: Page) => void }) {
  const nav: [React.ElementType, string, Page][] = [
    [FolderKanban, "项目", "projects"],
    [Box, "资产确认", "assets"],
    [Clapperboard, "生产监控", "production"],
    [AlertTriangle, "异常中心", "exceptions"],
    [Archive, "交付", "delivery"],
  ];
  return (
    <aside className="flex flex-col w-[200px] min-h-screen bg-[#161b26] border-r border-[#2a3347]">
      {/* Brand */}
      <div className="flex items-center gap-2 px-5 py-5 border-b border-[#2a3347]">
        <div className="w-7 h-7 rounded-md bg-indigo-600 flex items-center justify-center">
          <span className="text-white font-bold text-sm">V</span>
        </div>
        <span className="font-semibold text-white tracking-tight">VTV Studio</span>
      </div>

      {/* New Project */}
      <div className="px-3 pt-3 pb-2">
        <Button
          variant="outline"
          size="sm"
          className="w-full justify-start gap-2 text-xs"
          onClick={() => onPage("new-project")}
        >
          <Plus size={13} /> 新建项目
        </Button>
      </div>

      <Separator className="mx-3 my-1 w-auto" />

      {/* Nav */}
      <nav className="flex flex-col gap-0.5 px-2 py-2 flex-1">
        {nav.map(([Icon, label, id]) => (
          <button
            key={id}
            onClick={() => onPage(id)}
            className={[
              "flex items-center gap-2.5 rounded-md px-3 py-2 text-xs font-medium transition-colors text-left w-full",
              page === id
                ? "bg-indigo-600/20 text-indigo-300 border border-indigo-600/30"
                : "text-slate-400 hover:bg-[#1c2232] hover:text-slate-200",
            ].join(" ")}
          >
            <Icon size={14} />
            {label}
          </button>
        ))}
      </nav>
    </aside>
  );
}

// ── 阶段管道 ───────────────────────────────────────────────────────────────────
const STAGES = ["接入", "全剧分析", "资产确认", "自动生产", "质量检查", "交付"];

function PipelineBar({ progress }: { progress: number }) {
  const doneIdx = Math.floor(progress * STAGES.length);
  return (
    <div className="flex items-center gap-0 px-6 py-4 border-b border-[#2a3347] bg-[#161b26]">
      {STAGES.map((stage, i) => {
        const done = i < doneIdx;
        const current = i === doneIdx;
        return (
          <div key={stage} className="flex items-center flex-1 last:flex-none">
            <div className="flex flex-col items-center gap-1.5 min-w-[72px]">
              <div
                className={[
                  "w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-semibold border",
                  done ? "bg-indigo-600 border-indigo-500 text-white"
                    : current ? "bg-[#1c2232] border-indigo-500 text-indigo-400 ring-2 ring-indigo-600/30"
                    : "bg-[#1c2232] border-[#2a3347] text-slate-600",
                ].join(" ")}
              >
                {done ? <Check size={11} /> : i + 1}
              </div>
              <span className={[
                "text-[10px] font-medium",
                done || current ? "text-slate-300" : "text-slate-600",
              ].join(" ")}>{stage}</span>
            </div>
            {i < STAGES.length - 1 && (
              <div className={["flex-1 h-px mt-[-14px]", done ? "bg-indigo-600" : "bg-[#2a3347]"].join(" ")} />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── 新建项目 ───────────────────────────────────────────────────────────────────
function NewProjectPage({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [market, setMarket] = useState("en-US");
  const [quality, setQuality] = useState("standard");
  const [budget, setBudget] = useState("500");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const markets = [
    { value: "en-US", label: "美国英语 (en-US)" },
    { value: "en-GB", label: "英国英语 (en-GB)" },
    { value: "es-US", label: "美国西语 (es-US)" },
    { value: "ko-KR", label: "韩语 (ko-KR)" },
    { value: "ja-JP", label: "日语 (ja-JP)" },
  ];

  const handle = async () => {
    if (!name.trim()) { setErr("请输入项目名称"); return; }
    setLoading(true); setErr(null);
    try {
      const localeMap: Record<string, string> = {
        "en-US": "en-US", "en-GB": "en-GB", "es-US": "es-US", "ko-KR": "ko-KR", "ja-JP": "ja-JP",
      };
      const p: ApiCreateProject = {
        name: name.trim(),
        target_market: market.split("-")[1] ?? market,
        locale: localeMap[market] ?? "en-US",
        quality_profile: quality,
        budget_currency: "USD",
        budget_warning_at: Math.round(Number(budget) * 0.8),
        budget_hard_limit: Number(budget),
        output_spec: { aspect_ratio: "9:16", width: 1080, height: 1920, fps: 24, video_codec: "h264", audio_codec: "aac" },
      };
      await createProject(p);
      onDone();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "创建失败");
    } finally { setLoading(false); }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-8 py-5 border-b border-[#2a3347]">
        <div>
          <p className="text-[11px] text-slate-500 mb-1">新建项目</p>
          <h1 className="text-xl font-bold text-white">创建项目</h1>
        </div>
      </div>
      <div className="flex-1 overflow-auto px-8 py-6">
        <div className="max-w-lg space-y-5">
          {err && (
            <div className="rounded-md bg-red-900/30 border border-red-700/50 px-4 py-3 text-sm text-red-300">{err}</div>
          )}
          <div className="space-y-1.5">
            <Label>项目名称</Label>
            <Input value={name} onChange={e => setName(e.target.value)} placeholder="Drama-US-001" />
          </div>
          <div className="space-y-1.5">
            <Label>目标市场</Label>
            <Select value={market} onValueChange={setMarket}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {markets.map(m => <SelectItem key={m.value} value={m.value}>{m.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>质量档位</Label>
            <Select value={quality} onValueChange={setQuality}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="preview">预览（最快/最低成本）</SelectItem>
                <SelectItem value="standard">标准（均衡）</SelectItem>
                <SelectItem value="research_best">研究最优（最高质量）</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>预算上限（USD）</Label>
            <Input type="number" min="10" value={budget} onChange={e => setBudget(e.target.value)} />
          </div>
          <div className="flex gap-3 pt-2">
            <Button variant="outline" onClick={onDone}>取消</Button>
            <Button onClick={handle} disabled={loading}>
              {loading && <Loader2 size={13} className="animate-spin" />}
              创建项目
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── 资产确认 ───────────────────────────────────────────────────────────────────
function AssetConfirmationPage({ projectId }: { projectId: string }) {
  const chars = [
    { id: "c1", source: "张伟", localized: "David Zhang", status: "CONFIRMED", episodes: 24 },
    { id: "c2", source: "李梅", localized: "May Li", status: "DRAFT", episodes: 18 },
    { id: "c3", source: "王局长", localized: "Director Wang", status: "DRAFT", episodes: 6 },
  ];

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-8 py-5 border-b border-[#2a3347]">
        <div>
          <p className="text-[11px] text-slate-500 mb-1">资产管理</p>
          <h1 className="text-xl font-bold text-white">资产确认</h1>
          <p className="text-xs text-slate-500 mt-1">确认角色本土化设定后锁定版本，下游生成将引用此版本</p>
        </div>
        <Button disabled className="opacity-50">全部锁定</Button>
      </div>
      <div className="flex-1 overflow-auto px-8 py-4">
        <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">人物资产 ({chars.length})</h3>
        <div className="rounded-lg border border-[#2a3347] overflow-hidden">
          <div className="grid grid-cols-[1fr_1fr_100px_100px_120px] text-[11px] font-medium text-slate-500 bg-[#161b26] px-4 py-2.5 border-b border-[#2a3347]">
            <span>原始角色</span><span>本土化名称</span><span>出现集数</span><span>状态</span><span>操作</span>
          </div>
          {chars.map(c => (
            <div key={c.id} className="grid grid-cols-[1fr_1fr_100px_100px_120px] items-center px-4 py-3 border-b border-[#2a3347] last:border-0 hover:bg-[#1c2232]/60">
              <span className="text-sm text-slate-300">{c.source}</span>
              <span className="text-sm text-indigo-300">{c.localized}</span>
              <span className="text-xs text-slate-500">{c.episodes} 集</span>
              <span>{c.status === "CONFIRMED"
                ? <Badge variant="success">已确认</Badge>
                : <Badge variant="secondary">草稿</Badge>
              }</span>
              <div className="flex gap-1.5">
                <Button size="sm" variant="ghost" className="h-6 px-2 text-[11px]">编辑</Button>
                {c.status !== "CONFIRMED" && (
                  <Button size="sm" variant="outline" className="h-6 px-2 text-[11px]">确认</Button>
                )}
              </div>
            </div>
          ))}
        </div>
        <div className="mt-4 rounded-md bg-amber-900/20 border border-amber-700/30 px-4 py-3 flex items-start gap-3">
          <AlertTriangle size={14} className="text-amber-400 mt-0.5 flex-shrink-0" />
          <p className="text-xs text-amber-300">项目 ID: <code className="font-mono">{projectId || "—"}</code>。确认资产后点击"全部锁定"以冻结版本，触发下游生产流水线。</p>
        </div>
      </div>
    </div>
  );
}

// ── 生产监控 ───────────────────────────────────────────────────────────────────
function ProductionMonitorPage({ projectId, jobs }: { projectId: string; jobs: ApiJob[] }) {
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState<string | null>(null);

  const act = async (fn: () => Promise<unknown>, msg: string, key: string) => {
    setLoading(key);
    try { await fn(); setNotice(msg); }
    catch (e) { setNotice(e instanceof Error ? e.message : "操作失败"); }
    finally { setLoading(null); }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-8 py-5 border-b border-[#2a3347]">
        <div>
          <p className="text-[11px] text-slate-500 mb-1">生产管理</p>
          <h1 className="text-xl font-bold text-white">生产监控</h1>
        </div>
        <div className="flex items-center gap-2">
          {notice && <span className="text-xs text-emerald-400">{notice}</span>}
          <Button
            variant="outline" size="sm"
            disabled={loading === "pause"}
            onClick={() => act(() => pauseProject(projectId, "手动暂停"), "已暂停", "pause")}
          >
            {loading === "pause" ? <Loader2 size={12} className="animate-spin" /> : <PauseCircle size={13} />}
            暂停
          </Button>
          <Button
            variant="secondary" size="sm"
            onClick={() => act(() => resumeProject(projectId), "已恢复", "resume")}
          >
            <CirclePlay size={13} /> 恢复
          </Button>
          <Button
            variant="destructive" size="sm"
            onClick={() => { if (confirm("确认取消所有任务？")) act(() => cancelProject(projectId, "手动取消"), "已取消", "cancel"); }}
          >
            <XCircle size={13} /> 取消
          </Button>
        </div>
      </div>
      <div className="flex-1 overflow-auto px-8 py-4">
        {jobs.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-slate-600">
            <RefreshCw size={36} className="mb-3 opacity-30" />
            <p className="text-sm">暂无运行中的任务</p>
            <p className="text-xs mt-1 text-slate-700">上传剧集并启动分析后在此查看进度</p>
          </div>
        ) : (
          <div className="rounded-lg border border-[#2a3347] overflow-hidden">
            <div className="grid grid-cols-[140px_1fr_120px_220px_80px] text-[11px] font-medium text-slate-500 bg-[#161b26] px-4 py-2.5 border-b border-[#2a3347]">
              <span>任务 ID</span><span>类型</span><span>状态</span><span>进度</span><span>阶段</span>
            </div>
            {jobs.map(job => (
              <div key={job.id} className="grid grid-cols-[140px_1fr_120px_220px_80px] items-center px-4 py-3 border-b border-[#2a3347] last:border-0 hover:bg-[#1c2232]/60 text-xs">
                <code className="text-indigo-300 font-mono">{job.id.slice(0, 10)}…</code>
                <span className="text-slate-400">{job.kind}</span>
                {statusBadge(job.status)}
                <div className="flex items-center gap-2">
                  <Progress value={Math.round((job.progress ?? 0) * 100)} className="flex-1" />
                  <span className="text-[10px] text-slate-500 w-8 text-right">{Math.round((job.progress ?? 0) * 100)}%</span>
                </div>
                <span className="text-slate-500 text-center">{job.completed_stages}/{job.total_stages}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── 交付 ───────────────────────────────────────────────────────────────────────
function DeliveryPage({ projectId }: { projectId: string }) {
  const [deliveries, setDeliveries] = useState<ApiDelivery[]>([]);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!projectId) { setLoading(false); return; }
    setLoading(true);
    listDeliveries(projectId).then(setDeliveries).catch(() => {}).finally(() => setLoading(false));
  }, [projectId]);

  const approve = async (id: string) => {
    try {
      const u = await approveDelivery(id);
      setDeliveries(prev => prev.map(d => d.id === id ? u : d));
      setNotice(`交付 ${id.slice(0, 8)} 已批准`);
    } catch (e) { setNotice(e instanceof Error ? e.message : "操作失败"); }
  };

  const download = async (id: string) => {
    try { const p = await getDeliveryPackage(id); window.open(p.download_url, "_blank"); }
    catch (e) { setNotice(e instanceof Error ? e.message : "下载失败"); }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-8 py-5 border-b border-[#2a3347]">
        <div>
          <p className="text-[11px] text-slate-500 mb-1">交付管理</p>
          <h1 className="text-xl font-bold text-white">交付</h1>
        </div>
        {notice && <span className="text-xs text-emerald-400">{notice}</span>}
      </div>
      <div className="flex-1 overflow-auto px-8 py-4">
        {loading ? (
          <div className="flex items-center justify-center py-20"><Loader2 size={24} className="animate-spin text-indigo-500" /></div>
        ) : deliveries.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-slate-600">
            <Archive size={36} className="mb-3 opacity-30" />
            <p className="text-sm">暂无交付记录</p>
            <p className="text-xs mt-1 text-slate-700">完成集合成并通过质量检查后交付包将出现在此处</p>
          </div>
        ) : (
          <div className="rounded-lg border border-[#2a3347] overflow-hidden">
            <div className="grid grid-cols-[120px_1fr_100px_140px_120px] text-[11px] font-medium text-slate-500 bg-[#161b26] px-4 py-2.5 border-b border-[#2a3347]">
              <span>ID</span><span>集</span><span>状态</span><span>创建时间</span><span>操作</span>
            </div>
            {deliveries.map(d => (
              <div key={d.id} className="grid grid-cols-[120px_1fr_100px_140px_120px] items-center px-4 py-3 border-b border-[#2a3347] last:border-0 hover:bg-[#1c2232]/60 text-xs">
                <code className="text-indigo-300 font-mono">{d.id.slice(0, 8)}</code>
                <span className="text-slate-400">{d.episode_id ? d.episode_id.slice(0, 8) : "全集"}</span>
                {d.status === "APPROVED" ? <Badge variant="success">已批准</Badge> : <Badge variant="secondary">{d.status}</Badge>}
                <span className="text-slate-500">{new Date(d.created_at).toLocaleDateString("zh-CN")}</span>
                <div className="flex gap-1.5">
                  {d.status === "DRAFT" && (
                    <Button size="sm" variant="outline" className="h-6 px-2 text-[11px]" onClick={() => approve(d.id)}>批准</Button>
                  )}
                  {d.status === "APPROVED" && (
                    <Button size="sm" variant="ghost" className="h-6 px-2 text-[11px]" onClick={() => download(d.id)}>
                      <Download size={11} /> 下载
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── 异常中心 ───────────────────────────────────────────────────────────────────
function ExceptionPage({ projectId }: { projectId: string }) {
  return (
    <div className="flex flex-col h-full">
      <div className="px-8 py-5 border-b border-[#2a3347]">
        <p className="text-[11px] text-slate-500 mb-1">质量管理</p>
        <h1 className="text-xl font-bold text-white">异常中心</h1>
      </div>
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center text-slate-600">
          <AlertTriangle size={36} className="mb-3 opacity-30 mx-auto" />
          <p className="text-sm">异常列表从 API 加载</p>
          <p className="text-xs mt-1 text-slate-700">项目 ID: {projectId || "—"}</p>
        </div>
      </div>
    </div>
  );
}

function ProjectDashboard({
  project,
  jobs,
  connection,
  onAnalyze,
  onUpload,
  analysisState,
  uploadState,
  error,
  notice,
}: {
  project: ApiProject | null;
  jobs: ApiJob[];
  connection: string;
  onAnalyze: () => void;
  onUpload: () => void;
  analysisState: string;
  uploadState: string;
  error: string | null;
  notice: string | null;
}) {
  const progress = jobs.length > 0
    ? jobs.find(j => ["QUEUED","RUNNING"].includes(j.status))?.progress ?? (project?.status === "COMPLETED" ? 1 : 0)
    : 0;

  const totalEps = jobs.filter(j => j.kind === "EPISODE_INGEST").length;
  const budgetLimit = project ? `${project.budget.currency} ${project.budget.hard_limit}` : "—";
  const exceptionCount = jobs.filter(j => j.status === "FAILED").length;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-start justify-between px-8 py-5 border-b border-[#2a3347]">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[11px] text-slate-500">项目</span>
            <ChevronRight size={11} className="text-slate-600" />
            <span className={[
              "text-[11px] font-medium",
              connection === "live" ? "text-emerald-400" : connection === "offline" ? "text-amber-400" : "text-slate-500",
            ].join(" ")}>
              {connection === "live" ? "● 已连接" : connection === "offline" ? "○ 离线演示" : connection === "empty" ? "○ 尚无项目" : "○ 连接中…"}
            </span>
          </div>
          <h1 className="text-xl font-bold text-white truncate">
            {project?.name ?? "—"}
          </h1>
          {project && (
            <p className="text-[11px] text-slate-500 mt-0.5">
              {project.target_market} · {project.locale} · {project.quality_profile}
            </p>
          )}
          {error && <p className="text-[11px] text-red-400 mt-1">{error}</p>}
          {notice && <p className="text-[11px] text-emerald-400 mt-1">{notice}</p>}
        </div>
        <div className="flex gap-2 ml-4 flex-shrink-0">
          <Button
            variant="outline"
            size="sm"
            disabled={connection !== "live" || uploadState.includes("%")}
            onClick={onUpload}
          >
            <Upload size={13} /> {uploadState}
          </Button>
          <Button
            size="sm"
            disabled={!project || analysisState === "提交中…"}
            onClick={onAnalyze}
          >
            <Play size={13} /> {analysisState}
          </Button>
        </div>
      </div>

      {/* Pipeline */}
      <PipelineBar progress={progress} />

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4 px-8 py-4 border-b border-[#2a3347]">
        <Card>
          <CardHeader><CardTitle className="text-slate-400">总体进度</CardTitle></CardHeader>
          <CardContent>
            <p className="text-2xl font-bold text-white">{Math.round(progress * 100)}%</p>
            <Progress value={progress * 100} className="mt-3" />
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-slate-400">已接入集数</CardTitle></CardHeader>
          <CardContent>
            <p className="text-2xl font-bold text-white">{totalEps}</p>
            <p className="text-[11px] text-slate-500 mt-1">预算上限：{budgetLimit}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-slate-400">异常镜头</CardTitle></CardHeader>
          <CardContent>
            <p className={["text-2xl font-bold", exceptionCount > 0 ? "text-amber-400" : "text-white"].join(" ")}>
              {exceptionCount}
            </p>
            <p className="text-[11px] text-slate-500 mt-1">待处理任务</p>
          </CardContent>
        </Card>
      </div>

      {/* Jobs table */}
      <div className="flex-1 overflow-auto px-8 py-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-slate-300">任务列表</h2>
          <span className="text-[11px] text-slate-500">{jobs.length} 个任务</span>
        </div>
        {jobs.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-slate-600">
            <FileText size={36} className="mb-3 opacity-40" />
            <p className="text-sm">暂无任务，上传剧集并启动分析</p>
          </div>
        ) : (
          <div className="rounded-lg border border-[#2a3347] overflow-hidden">
            <div className="grid grid-cols-[1fr_140px_120px_180px_100px] gap-0 text-[11px] font-medium text-slate-500 bg-[#161b26] px-4 py-2.5 border-b border-[#2a3347]">
              <span>任务 ID</span><span>类型</span><span>状态</span><span>进度</span><span>阶段</span>
            </div>
            {jobs.map(job => (
              <div
                key={job.id}
                className="grid grid-cols-[1fr_140px_120px_180px_100px] gap-0 items-center px-4 py-3 border-b border-[#2a3347] last:border-0 text-[12px] hover:bg-[#1c2232]/60 transition-colors"
              >
                <code className="text-indigo-300 font-mono text-[11px]">{job.id.slice(0, 12)}…</code>
                <span className="text-slate-400">{job.kind}</span>
                <span>{statusBadge(job.status)}</span>
                <div className="flex items-center gap-2">
                  <Progress value={Math.round((job.progress ?? 0) * 100)} className="flex-1 h-1.5" />
                  <span className="text-[10px] text-slate-500 w-8 text-right">{Math.round((job.progress ?? 0) * 100)}%</span>
                </div>
                <span className="text-[11px] text-slate-500">{job.completed_stages}/{job.total_stages}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
// ── 主 App ────────────────────────────────────────────────────────────────────
export default function App() {
  const [page, setPage] = useState<Page>("projects");
  const [connection, setConnection] = useState<"loading" | "live" | "offline" | "empty">("loading");
  const [project, setProject] = useState<ApiProject | null>(null);
  const [jobs, setJobs] = useState<ApiJob[]>([]);
  const [analysisState, setAnalysisState] = useState("开始分析");
  const [uploadState, setUploadState] = useState("上传剧集");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    setConnection("loading");
    loadLatestProject()
      .then(snap => {
        if (!snap) { setConnection("empty"); return; }
        setProject(snap.project);
        setJobs(snap.jobs);
        setConnection("live");
      })
      .catch(() => setConnection("offline"));
  }, []);

  useEffect(() => { load(); }, [load]);

  const onAnalyze = async () => {
    if (!project) return;
    setAnalysisState("提交中…"); setError(null); setNotice(null);
    try {
      const id = await startProjectAnalysis(project.id);
      setAnalysisState(`已提交 ${id.slice(0, 8)}`);
      setNotice("分析任务已提交");
    } catch (e) {
      setAnalysisState("提交失败");
      setError(e instanceof Error ? e.message : "分析提交失败");
    }
  };

  const onUpload = async () => {
    if (!project) return;
    setError(null); setUploadState("选择文件…");
    try {
      const result = await uploadEpisodeFromDialog(
        project.id, jobs.length + 1,
        p => setUploadState(`上传 ${Math.round(100 * p.uploadedBytes / p.totalBytes)}%`),
      );
      if (!result) { setUploadState("上传剧集"); return; }
      setUploadState("上传完成");
      setNotice(`接入任务 ${result.ingestJobId?.slice(0, 8) ?? "—"} 已创建`);
      setTimeout(load, 1000);
    } catch (e) {
      setUploadState("上传失败");
      setError(e instanceof Error ? e.message : "上传失败");
    }
  };

  const renderPage = () => {
    switch (page) {
      case "new-project":
        return <NewProjectPage onDone={() => { setPage("projects"); load(); }} />;
      case "assets":
        return <AssetConfirmationPage projectId={project?.id ?? ""} />;
      case "production":
        return <ProductionMonitorPage projectId={project?.id ?? ""} jobs={jobs} />;
      case "delivery":
        return <DeliveryPage projectId={project?.id ?? ""} />;
      case "exceptions":
        return <ExceptionPage projectId={project?.id ?? ""} />;
      default:
        return (
          <ProjectDashboard
            project={project} jobs={jobs} connection={connection}
            onAnalyze={onAnalyze} onUpload={onUpload}
            analysisState={analysisState} uploadState={uploadState}
            error={error} notice={notice}
          />
        );
    }
  };

  return (
    <div className="flex min-h-screen bg-[#0f1117]">
      <Sidebar page={page} onPage={setPage} />
      <main className="flex-1 min-w-0 overflow-hidden">{renderPage()}</main>
    </div>
  );
}
