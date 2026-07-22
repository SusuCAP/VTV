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
import { useState } from "react";
import { episodes, exceptions } from "./data";

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

function Metrics() {
  return <section className="metrics">
    <div><span>总体进度</span><strong className="accent">28%</strong><p>7 / 25 集</p><progress value="28" max="100"/></div>
    <div><span>预算</span><strong>USD 18,450</strong><p>上限 USD 65,000 · 已用 28%</p><progress value="28" max="100"/></div>
    <div><span>异常镜头</span><strong className="accent">156</strong><p>待处理 23</p></div>
  </section>;
}

function EpisodeList() {
  return <section className="episode-panel">
    <div className="section-title"><h2>剧集列表</h2><span>共 25 集</span></div>
    <div className="table-head"><span>剧集</span><span>上传状态</span><span>分析状态</span><span>时长</span><span>更新时间</span></div>
    {episodes.map((episode) => <div className="episode-row" key={episode.id}>
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
  const [started, setStarted] = useState(false);
  return <div className="app-shell"><Sidebar/><main>
    <header><div><p>项目列表 / 当前项目</p><h1>Drama-US-001</h1><span>目标市场：美国 · 语言：英语 · 质量档位：research_best</span></div><div className="actions"><button><Upload size={17}/>上传剧集</button><button className="primary" onClick={() => setStarted(true)}><Play size={17}/>{started ? "分析已提交" : "开始分析"}</button></div></header>
    <Pipeline/><Metrics/><div className="workspace"><EpisodeList/><ExceptionReview/></div>
  </main></div>;
}
