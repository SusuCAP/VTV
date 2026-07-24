import {
  AlertTriangle,
  Archive,
  Box,
  Check,
  ChevronRight,
  CirclePlay,
  Clapperboard,
  Download,
  FolderKanban,
  PauseCircle,
  Play,
  Plus,
  Upload,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
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
  type ApiProject,
} from "./api";
import { episodes as demoEpisodes, exceptions, type Episode } from "./data";
import { uploadEpisodeFromDialog } from "./localAgent";

type Page = "project" | "new-project" | "assets" | "production" | "exceptions" | "delivery";

const stages = ["接入", "全剧分析", "资产确认", "自动生产", "质量检查", "交付"];

// ── Sidebar ──────────────────────────────────────────────────────────────────
function Sidebar({ page, onPage }: { page: Page; onPage: (p: Page) => void }) {
  const items: [React.ElementType, string, Page][] = [
    [FolderKanban, "项目", "project"],
    [Box, "资产确认", "assets"],
    [Clapperboard, "生产监控", "production"],
    [AlertTriangle, "异常", "exceptions"],
    [Archive, "交付", "delivery"],
  ];
  return (
    <aside className="sidebar">
      <div className="brand"><span>V</span>TV</div>
      <nav>
        {items.map(([Icon, label, id]) => (
          <button
            className={page === id ? "active" : ""}
            key={id}
            onClick={() => onPage(id)}
          >
            <Icon size={19} /><span>{label}</span>
          </button>
        ))}
      </nav>
      <button className="new-project-btn" onClick={() => onPage("new-project")}>
        <Plus size={16} /> 新建项目
      </button>
    </aside>
  );
}

// ── Pipeline ─────────────────────────────────────────────────────────────────
function Pipeline() {
  return (
    <section className="pipeline" aria-label="生产阶段">
      {stages.map((stage, index) => (
        <div className={`stage ${index < 2 ? "done" : ""} ${index === 1 ? "current" : ""}`} key={stage}>
          <div className="stage-line" />
          <span className="stage-dot">{index === 0 ? <Check size={15} /> : index + 1}</span>
          <strong>{stage}</strong>
          <small>{index === 0 ? "已完成" : index === 1 ? "进行中" : "待开始"}</small>
        </div>
      ))}
    </section>
  );
}

// ── Metrics ──────────────────────────────────────────────────────────────────
function Metrics({ episodeCount, progress, budgetLimit }: { episodeCount: number; progress: number; budgetLimit: string }) {
  return (
    <section className="metrics">
      <div><span>总体进度</span><strong className="accent">{Math.round(progress * 100)}%</strong><p>{episodeCount} 集已接入</p><progress value={progress * 100} max="100" /></div>
      <div><span>预算上限</span><strong>{budgetLimit}</strong><p>成本由 Stage Attempt 实际用量汇总</p><progress value="0" max="100" /></div>
      <div><span>异常镜头</span><strong className="accent">156</strong><p>待处理 23</p></div>
    </section>
  );
}

// ── Episode list ──────────────────────────────────────────────────────────────
function EpisodeList({ items, live }: { items: Episode[]; live: boolean }) {
  return (
    <section className="episode-panel">
      <div className="section-title"><h2>剧集列表</h2><span>{live ? `共 ${items.length} 集` : "离线演示数据"}</span></div>
      <div className="table-head"><span>剧集</span><span>上传状态</span><span>分析状态</span><span>时长</span><span>更新时间</span></div>
      {items.map((episode) => (
        <div className="episode-row" key={episode.id}>
          <div><ChevronRight size={14} /><strong>第 {String(episode.id).padStart(2, "0")} 集</strong><small>{episode.filename}</small></div>
          <span className="ok"><Check size={14} />{episode.upload}</span>
          <div><span>{episode.analysis}</span>{episode.progress && episode.analysis.includes("分析中") ? <progress value={episode.progress} max="100" /> : null}</div>
          <span>{episode.duration}</span><span>{episode.updated}</span>
        </div>
      ))}
    </section>
  );
}

// ── New Project Page ──────────────────────────────────────────────────────────
function NewProjectPage({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [market, setMarket] = useState("en-US");
  const [quality, setQuality] = useState("standard");
  const [budget, setBudget] = useState("500");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleCreate = async () => {
    if (!name.trim()) { setError("请输入项目名称"); return; }
    setSubmitting(true); setError(null);
    try {
      const localeMap: Record<string, string> = {
        "en-US": "en-US", "en-GB": "en-GB", "es-US": "es-US",
        "ko-KR": "ko-KR", "ja-JP": "ja-JP",
      };
      const payload: ApiCreateProject = {
        name: name.trim(),
        target_market: market.split("-")[1] ?? market,
        locale: localeMap[market] ?? "en-US",
        quality_profile: quality,
        budget_currency: "USD",
        budget_warning_at: Math.round(Number(budget) * 0.8),
        budget_hard_limit: Number(budget),
        output_spec: { aspect_ratio: "9:16", width: 1080, height: 1920, fps: 24, video_codec: "h264", audio_codec: "aac" },
      };
      await createProject(payload);
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "创建失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="page-form">
      <h2>新建项目</h2>
      {error && <p className="api-error">{error}</p>}
      <label>项目名称<input value={name} onChange={(e) => setName(e.target.value)} placeholder="Drama-US-001" /></label>
      <label>目标市场
        <select value={market} onChange={(e) => setMarket(e.target.value)}>
          <option value="en-US">美国英语 (en-US)</option>
          <option value="en-GB">英国英语 (en-GB)</option>
          <option value="es-US">美国西语 (es-US)</option>
          <option value="ko-KR">韩语 (ko-KR)</option>
          <option value="ja-JP">日语 (ja-JP)</option>
        </select>
      </label>
      <label>质量档位
        <select value={quality} onChange={(e) => setQuality(e.target.value)}>
          <option value="preview">预览（最快/最低成本）</option>
          <option value="standard">标准（均衡）</option>
          <option value="research_best">研究最优（最高质量）</option>
        </select>
      </label>
      <label>预算上限 (USD)<input type="number" min="10" value={budget} onChange={(e) => setBudget(e.target.value)} /></label>
      <div className="form-actions">
        <button onClick={onDone}>取消</button>
        <button className="primary" disabled={submitting} onClick={handleCreate}>
          {submitting ? "创建中…" : "创建项目"}
        </button>
      </div>
    </div>
  );
}

// ── Asset Confirmation Page ───────────────────────────────────────────────────
function AssetConfirmationPage({ projectId }: { projectId: string }) {
  const mockCharacters = [
    { id: "c1", source: "张伟", localized: "David Zhang", status: "CONFIRMED", episodes: 24 },
    { id: "c2", source: "李梅", localized: "May Li", status: "DRAFT", episodes: 18 },
    { id: "c3", source: "王局长", localized: "Director Wang", status: "DRAFT", episodes: 6 },
  ];
  return (
    <div className="page-assets">
      <div className="page-header">
        <h2>资产确认</h2>
        <p className="subtitle">确认角色本土化设定后锁定版本，下游生成将引用此版本。</p>
      </div>
      <section>
        <h3>人物资产 ({mockCharacters.length})</h3>
        <div className="table-head"><span>原始角色</span><span>本土化名称</span><span>出现集数</span><span>状态</span><span>操作</span></div>
        {mockCharacters.map((c) => (
          <div className="asset-row" key={c.id}>
            <span>{c.source}</span>
            <span className="editable">{c.localized}</span>
            <span>{c.episodes} 集</span>
            <span className={`status-badge ${c.status === "CONFIRMED" ? "ok" : "draft"}`}>
              {c.status === "CONFIRMED" ? "已确认" : "草稿"}
            </span>
            <div className="row-actions">
              <button className="small">编辑</button>
              {c.status !== "CONFIRMED" && <button className="small primary">确认锁定</button>}
            </div>
          </div>
        ))}
      </section>
      <section className="asset-notice">
        <AlertTriangle size={16} />
        <p>项目 ID: <code>{projectId}</code>。确认资产后点击"全部锁定"以冻结版本，触发下游生产流水线。</p>
        <button className="primary" disabled>全部锁定（需从控制 API 获取真实资产）</button>
      </section>
    </div>
  );
}

// ── Production Monitor Page ───────────────────────────────────────────────────
function ProductionMonitorPage({ projectId, jobs }: { projectId: string; jobs: { id: string; kind: string; status: string; total_stages: number; completed_stages: number; progress: number }[] }) {
  const [pausing, setPausing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const handlePause = async () => {
    setPausing(true);
    try { await pauseProject(projectId, "用户手动暂停"); setNotice("已暂停"); }
    catch (e) { setNotice(e instanceof Error ? e.message : "暂停失败"); }
    finally { setPausing(false); }
  };
  const handleResume = async () => {
    try { await resumeProject(projectId); setNotice("已恢复"); }
    catch (e) { setNotice(e instanceof Error ? e.message : "恢复失败"); }
  };

  return (
    <div className="page-production">
      <div className="page-header">
        <h2>生产监控</h2>
        <div className="control-actions">
          {notice && <small className="api-notice">{notice}</small>}
          <button onClick={handlePause} disabled={pausing}><PauseCircle size={16} /> 暂停</button>
          <button onClick={handleResume}><CirclePlay size={16} /> 恢复</button>
          <button className="danger" onClick={() => { if (confirm("确认取消所有任务？")) cancelProject(projectId, "用户手动取消").catch(() => null); }}><XCircle size={16} /> 取消</button>
        </div>
      </div>
      {jobs.length === 0
        ? <p className="empty">暂无运行中的任务。上传剧集并启动分析后在此查看进度。</p>
        : (
          <div className="job-list">
            <div className="table-head"><span>任务 ID</span><span>类型</span><span>状态</span><span>进度</span><span>完成阶段</span></div>
            {jobs.map((job) => (
              <div className="job-row" key={job.id}>
                <code>{job.id.slice(0, 8)}</code>
                <span>{job.kind}</span>
                <span className={`status-badge ${job.status === "COMPLETED" ? "ok" : job.status === "FAILED" ? "danger" : "running"}`}>{job.status}</span>
                <div className="progress-cell"><progress value={Math.round(job.progress * 100)} max="100" /><small>{Math.round(job.progress * 100)}%</small></div>
                <span>{job.completed_stages} / {job.total_stages}</span>
              </div>
            ))}
          </div>
        )}
    </div>
  );
}

// ── Delivery Page ─────────────────────────────────────────────────────────────
function DeliveryPage({ projectId }: { projectId: string }) {
  const [deliveries, setDeliveries] = useState<ApiDelivery[]>([]);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    listDeliveries(projectId)
      .then(setDeliveries)
      .catch(() => setDeliveries([]))
      .finally(() => setLoading(false));
  }, [projectId]);

  const handleApprove = async (id: string) => {
    try {
      const updated = await approveDelivery(id);
      setDeliveries((prev) => prev.map((d) => (d.id === id ? updated : d)));
      setNotice(`交付 ${id.slice(0, 8)} 已批准`);
    } catch (e) { setNotice(e instanceof Error ? e.message : "批准失败"); }
  };

  const handleDownload = async (id: string) => {
    try {
      const pkg = await getDeliveryPackage(id);
      window.open(pkg.download_url, "_blank");
    } catch (e) { setNotice(e instanceof Error ? e.message : "下载失败"); }
  };

  return (
    <div className="page-delivery">
      <div className="page-header">
        <h2>交付</h2>
        {notice && <small className="api-notice">{notice}</small>}
      </div>
      {loading ? <p>加载中…</p> : deliveries.length === 0
        ? <p className="empty">暂无交付记录。完成集合成并通过质量检查后交付包将出现在此处。</p>
        : (
          <div className="delivery-list">
            <div className="table-head"><span>ID</span><span>集</span><span>状态</span><span>创建时间</span><span>操作</span></div>
            {deliveries.map((d) => (
              <div className="delivery-row" key={d.id}>
                <code>{d.id.slice(0, 8)}</code>
                <span>{d.episode_id ? d.episode_id.slice(0, 8) : "全集"}</span>
                <span className={`status-badge ${d.status === "APPROVED" ? "ok" : "draft"}`}>{d.status}</span>
                <span>{new Date(d.created_at).toLocaleDateString("zh-CN")}</span>
                <div className="row-actions">
                  {d.status === "DRAFT" && <button className="small primary" onClick={() => handleApprove(d.id)}>批准</button>}
                  {d.status === "APPROVED" && <button className="small" onClick={() => handleDownload(d.id)}><Download size={14} /> 下载</button>}
                </div>
              </div>
            ))}
          </div>
        )}
    </div>
  );
}

// ── Exception Review ──────────────────────────────────────────────────────────
function ExceptionReview() {
  const [resolved, setResolved] = useState<number[]>([]);
  const active = exceptions[0];
  if (!active) return null;
  return (
    <section className="exception-panel">
      <div className="section-title"><h2>异常中心</h2><span>{exceptions.filter((e) => !resolved.includes(e.id)).length} 待处理</span></div>
      <ul>{exceptions.map((e) => (
        <li key={e.id} className={resolved.includes(e.id) ? "resolved" : ""}>
          <span className={`severity ${e.severity === "严重" ? "danger" : ""}`}>{e.severity}</span>
          <div><strong>{e.type}</strong><small>{e.episode}</small></div>
          <span>{e.timecode}</span>
        </li>
      ))}</ul>
      <div className="detail">
        <div className="section-title"><h2>异常详情</h2><span>1 / {exceptions.length}</span></div>
        <img src="/assets/review-frame.png" alt="异常镜头预览" />
        <div className="player"><Play size={17} fill="currentColor" /><span>00:02:35 / 00:12:45</span><div><i /></div></div>
        <dl>
          <dt>异常类型</dt><dd>{active.type}</dd>
          <dt>严重程度</dt><dd className="danger">{active.severity}</dd>
          <dt>所属剧集</dt><dd>{active.episode}</dd>
          <dt>时间码</dt><dd>{active.timecode}</dd>
        </dl>
        <p className="description">当前镜头中人物与参考设定不一致，请核对角色形象并重新生成候选。</p>
        <button className="primary resolve" onClick={() => setResolved([...new Set([...resolved, active.id])])}>
          {resolved.includes(active.id) ? "已标记为处理" : "标记为已处理"}
        </button>
      </div>
    </section>
  );
}

// ── Main App ──────────────────────────────────────────────────────────────────
export default function App() {
  const [page, setPage] = useState<Page>("project");
  const [connection, setConnection] = useState<"loading" | "live" | "offline" | "empty">("loading");
  const [project, setProject] = useState<ApiProject | null>(null);
  const [episodeItems, setEpisodeItems] = useState<Episode[]>(demoEpisodes);
  const [jobs, setJobs] = useState<{ id: string; kind: string; status: string; total_stages: number; completed_stages: number; progress: number }[]>([]);
  const [jobProgress, setJobProgress] = useState(0.28);
  const [analysisState, setAnalysisState] = useState("开始分析");
  const [uploadState, setUploadState] = useState("上传剧集");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    loadLatestProject().then((snapshot) => {
      if (!active) return;
      if (!snapshot) { setConnection("empty"); setEpisodeItems([]); return; }
      setProject(snapshot.project);
      setJobs(snapshot.jobs);
      setEpisodeItems(snapshot.episodes.map((episode) => ({
        id: episode.episode_no,
        filename: episode.title ?? `E${String(episode.episode_no).padStart(2, "0")}.mp4`,
        upload: episode.upload_status === "COMPLETED" ? "已上传" : episode.upload_status,
        analysis: episode.processing_status,
        duration: episode.duration_ms ? new Date(episode.duration_ms).toISOString().slice(11, 19) : "待探测",
        updated: "服务端",
        progress: snapshot.jobs.find((j) => j.kind === "EPISODE_INGEST")?.progress
          ? 100 * (snapshot.jobs.find((j) => j.kind === "EPISODE_INGEST")?.progress ?? 0)
          : undefined,
      })));
      const activeJob = snapshot.jobs.find((j) => ["QUEUED", "RUNNING"].includes(j.status));
      setJobProgress(activeJob?.progress ?? (snapshot.project.status === "COMPLETED" ? 1 : 0));
      setConnection("live");
    }).catch((reason: unknown) => {
      if (!active) return;
      setConnection("offline");
      setError(reason instanceof Error ? reason.message : "控制 API 连接失败");
    });
    return () => { active = false; };
  }, []);

  const statusText = useMemo(
    () => ({ loading: "正在连接控制 API", live: "控制 API 已连接", offline: "离线演示", empty: "尚无项目" })[connection],
    [connection],
  );

  const startAnalysis = async () => {
    if (!project) return;
    setAnalysisState("提交中…"); setError(null); setNotice(null);
    try {
      const jobId = await startProjectAnalysis(project.id);
      setAnalysisState(`已提交 ${jobId.slice(0, 8)}`);
    } catch (reason) {
      setAnalysisState("提交失败");
      setError(reason instanceof Error ? reason.message : "分析提交失败");
    }
  };

  const uploadEpisode = async () => {
    if (!project) return;
    setError(null); setUploadState("选择文件…");
    try {
      const result = await uploadEpisodeFromDialog(
        project.id,
        episodeItems.length + 1,
        (progress) => setUploadState(`上传 ${Math.round(100 * progress.uploadedBytes / progress.totalBytes)}%`),
      );
      if (!result) { setUploadState("上传剧集"); return; }
      setUploadState("上传完成");
      setNotice(`已创建接入任务 ${result.ingestJobId?.slice(0, 8) ?? "—"}`);
      window.setTimeout(() => window.location.reload(), 800);
    } catch (reason) {
      setUploadState("上传失败");
      setError(reason instanceof Error ? reason.message : "媒体上传失败");
    }
  };

  const displayName = project?.name ?? "Drama-US-001";
  const targetMarket = project?.target_market ?? "US";
  const locale = project?.locale ?? "en-US";
  const quality = project?.quality_profile ?? "research_best";
  const budgetLimit = project ? `${project.budget.currency} ${project.budget.hard_limit}` : "USD 65,000";

  // ── Page: New Project ──────────────────────────────────────────────────────
  if (page === "new-project") {
    return (
      <div className="app-shell">
        <Sidebar page={page} onPage={setPage} />
        <main><NewProjectPage onDone={() => { setPage("project"); window.location.reload(); }} /></main>
      </div>
    );
  }

  // ── Page: Asset Confirmation ───────────────────────────────────────────────
  if (page === "assets") {
    return (
      <div className="app-shell">
        <Sidebar page={page} onPage={setPage} />
        <main><AssetConfirmationPage projectId={project?.id ?? ""} /></main>
      </div>
    );
  }

  // ── Page: Production Monitor ───────────────────────────────────────────────
  if (page === "production") {
    return (
      <div className="app-shell">
        <Sidebar page={page} onPage={setPage} />
        <main><ProductionMonitorPage projectId={project?.id ?? ""} jobs={jobs} /></main>
      </div>
    );
  }

  // ── Page: Delivery ─────────────────────────────────────────────────────────
  if (page === "delivery") {
    return (
      <div className="app-shell">
        <Sidebar page={page} onPage={setPage} />
        <main><DeliveryPage projectId={project?.id ?? ""} /></main>
      </div>
    );
  }

  // ── Page: Project (default) ────────────────────────────────────────────────
  return (
    <div className="app-shell">
      <Sidebar page={page} onPage={setPage} />
      <main>
        <header>
          <div>
            <p>项目列表 / 当前项目 · <b className={`connection ${connection}`}>{statusText}</b></p>
            <h1>{displayName}</h1>
            <span>目标市场：{targetMarket} · 语言：{locale} · 质量档位：{quality}</span>
            {error ? <small className="api-error">{error}</small> : null}
            {notice ? <small className="api-notice">{notice}</small> : null}
          </div>
          <div className="actions">
            <button
              disabled={connection !== "live" || uploadState.includes("上传 ")}
              onClick={uploadEpisode}
            ><Upload size={17} />{uploadState}</button>
            <button
              className="primary"
              disabled={!project || analysisState === "提交中…"}
              onClick={startAnalysis}
            ><Play size={17} />{analysisState}</button>
          </div>
        </header>
        <Pipeline />
        <Metrics episodeCount={episodeItems.length} progress={jobProgress} budgetLimit={budgetLimit} />
        <div className="workspace">
          <EpisodeList items={episodeItems} live={connection === "live"} />
          {page === "exceptions" ? <ExceptionReview /> : null}
        </div>
      </main>
    </div>
  );
}
