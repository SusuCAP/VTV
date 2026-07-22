import {
  AlertTriangle,
  Archive,
  Box,
  Check,
  ChevronRight,
  CirclePlay,
  Clapperboard,
  FolderKanban,
  Play,
  Upload,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { loadLatestProject, startProjectAnalysis, type ApiProject } from "./api";
import { episodes as demoEpisodes, exceptions, type Episode } from "./data";

const stages = ["接入", "全剧分析", "资产确认", "自动生产", "质量检查", "交付"];

function Sidebar() {
  const items = [
    [FolderKanban, "项目"], [Box, "资产"], [Clapperboard, "生产"],
    [AlertTriangle, "异常"], [Archive, "交付"],
  ] as const;
  return <aside className="sidebar">
    <div className="brand"><span>V</span>TV</div>
    <nav>{items.map(([Icon, label], index) => <button className={index === 0 ? "active" : ""} key={label}><Icon size={19}/><span>{label}</span></button>)}</nav>
  </aside>;
}

function Pipeline() {
  return <section className="pipeline" aria-label="生产阶段">
    {stages.map((stage, index) => <div className={`stage ${index < 2 ? "done" : ""} ${index === 1 ? "current" : ""}`} key={stage}>
      <div className="stage-line" />
      <span className="stage-dot">{index === 0 ? <Check size={15}/> : index + 1}</span>
      <strong>{stage}</strong><small>{index === 0 ? "已完成" : index === 1 ? "进行中" : "待开始"}</small>
    </div>)}
  </section>;
}

function Metrics({ episodeCount, progress, budgetLimit }: { episodeCount: number; progress: number; budgetLimit: string }) {
  return <section className="metrics">
    <div><span>总体进度</span><strong className="accent">{Math.round(progress * 100)}%</strong><p>{episodeCount} 集已接入</p><progress value={progress * 100} max="100"/></div>
    <div><span>预算上限</span><strong>{budgetLimit}</strong><p>成本由 Stage Attempt 实际用量汇总</p><progress value="0" max="100"/></div>
    <div><span>异常镜头</span><strong className="accent">156</strong><p>待处理 23</p></div>
  </section>;
}

function EpisodeList({ items, live }: { items: Episode[]; live: boolean }) {
  return <section className="episode-panel">
    <div className="section-title"><h2>剧集列表</h2><span>{live ? `共 ${items.length} 集` : "离线演示数据"}</span></div>
    <div className="table-head"><span>剧集</span><span>上传状态</span><span>分析状态</span><span>时长</span><span>更新时间</span></div>
    {items.map((episode) => <div className="episode-row" key={episode.id}>
      <div><ChevronRight size={14}/><strong>第 {String(episode.id).padStart(2, "0")} 集</strong><small>{episode.filename}</small></div>
      <span className="ok"><Check size={14}/>{episode.upload}</span>
      <div><span>{episode.analysis}</span>{episode.progress && episode.analysis.includes("分析中") ? <progress value={episode.progress} max="100"/> : null}</div>
      <span>{episode.duration}</span><span>{episode.updated}</span>
    </div>)}
  </section>;
}

function ExceptionReview() {
  const [selected, setSelected] = useState(1);
  const [resolved, setResolved] = useState<number[]>([]);
  const active = exceptions.find((item) => item.id === selected) ?? exceptions[0];
  return <section className="review-region">
    <div className="exception-list">
      <div className="section-title"><h2>异常审阅</h2><span>异常队列 (23)</span></div>
      {exceptions.map((item) => <button onClick={() => setSelected(item.id)} className={selected === item.id ? "selected" : ""} key={item.id}>
        <span className="thumb"><CirclePlay size={22}/></span><span><strong>{item.type}</strong><small>{item.episode} · {item.timecode}</small></span><em>{resolved.includes(item.id) ? "已处理" : item.severity}</em>
      </button>)}
    </div>
    <div className="detail">
      <div className="section-title"><h2>异常详情</h2><span>1 / 23</span></div>
      <img src="/assets/review-frame.png" alt="异常镜头预览：办公室对话场景"/>
      <div className="player"><Play size={17} fill="currentColor"/><span>00:02:35 / 00:12:45</span><div><i /></div></div>
      <dl><dt>异常类型</dt><dd>{active.type}</dd><dt>严重程度</dt><dd className="danger">{active.severity}</dd><dt>所属剧集</dt><dd>{active.episode}</dd><dt>时间码</dt><dd>{active.timecode}</dd></dl>
      <p className="description">当前镜头中人物与参考设定不一致，请核对角色形象并重新生成候选。</p>
      <button className="primary resolve" onClick={() => setResolved([...new Set([...resolved, active.id])])}>{resolved.includes(active.id) ? "已标记为处理" : "标记为已处理"}</button>
    </div>
  </section>;
}

export default function App() {
  const [connection, setConnection] = useState<"loading" | "live" | "offline" | "empty">("loading");
  const [project, setProject] = useState<ApiProject | null>(null);
  const [episodeItems, setEpisodeItems] = useState<Episode[]>(demoEpisodes);
  const [jobProgress, setJobProgress] = useState(0.28);
  const [analysisState, setAnalysisState] = useState("开始分析");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    loadLatestProject().then((snapshot) => {
      if (!active) return;
      if (!snapshot) {
        setConnection("empty");
        setEpisodeItems([]);
        return;
      }
      setProject(snapshot.project);
      setEpisodeItems(snapshot.episodes.map((episode) => ({
        id: episode.episode_no,
        filename: episode.title ?? `E${String(episode.episode_no).padStart(2, "0")}.mp4`,
        upload: episode.upload_status === "COMPLETED" ? "已上传" : episode.upload_status,
        analysis: episode.processing_status,
        duration: episode.duration_ms ? new Date(episode.duration_ms).toISOString().slice(11, 19) : "待探测",
        updated: "服务端",
        progress: snapshot.jobs.find((job) => job.kind === "EPISODE_INGEST")?.progress ? 100 * (snapshot.jobs.find((job) => job.kind === "EPISODE_INGEST")?.progress ?? 0) : undefined,
      })));
      const activeJob = snapshot.jobs.find((job) => ["QUEUED", "RUNNING"].includes(job.status));
      setJobProgress(activeJob?.progress ?? (snapshot.project.status === "COMPLETED" ? 1 : 0));
      setConnection("live");
    }).catch((reason: unknown) => {
      if (!active) return;
      setConnection("offline");
      setError(reason instanceof Error ? reason.message : "控制 API 连接失败");
    });
    return () => { active = false; };
  }, []);

  const statusText = useMemo(() => ({ loading: "正在连接控制 API", live: "控制 API 已连接", offline: "离线演示", empty: "尚无项目" })[connection], [connection]);
  const startAnalysis = async () => {
    if (!project) return;
    setAnalysisState("提交中…");
    setError(null);
    try {
      const jobId = await startProjectAnalysis(project.id);
      setAnalysisState(`已提交 ${jobId.slice(0, 8)}`);
    } catch (reason) {
      setAnalysisState("提交失败");
      setError(reason instanceof Error ? reason.message : "分析提交失败");
    }
  };

  const displayName = project?.name ?? "Drama-US-001";
  const targetMarket = project?.target_market ?? "US";
  const locale = project?.locale ?? "en-US";
  const quality = project?.quality_profile ?? "research_best";
  const budgetLimit = project ? `${project.budget.currency} ${project.budget.hard_limit}` : "USD 65,000";
  return <div className="app-shell"><Sidebar/><main>
    <header><div><p>项目列表 / 当前项目 · <b className={`connection ${connection}`}>{statusText}</b></p><h1>{displayName}</h1><span>目标市场：{targetMarket} · 语言：{locale} · 质量档位：{quality}</span>{error ? <small className="api-error">{error}</small> : null}</div><div className="actions"><button disabled={connection !== "live"} onClick={() => setError("上传需要本地媒体 Agent；当前 API 查询与分析提交已联通。") }><Upload size={17}/>上传剧集</button><button className="primary" disabled={!project || analysisState === "提交中…"} onClick={startAnalysis}><Play size={17}/>{analysisState}</button></div></header>
    <Pipeline/><Metrics episodeCount={episodeItems.length} progress={jobProgress} budgetLimit={budgetLimit}/><div className="workspace"><EpisodeList items={episodeItems} live={connection === "live"}/><ExceptionReview/></div>
  </main></div>;
}
