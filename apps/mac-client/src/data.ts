export type Episode = {
  id: number;
  filename: string;
  upload: string;
  analysis: string;
  duration: string;
  updated: string;
  progress?: number;
};

export type ExceptionItem = {
  id: number;
  type: "身份一致性" | "中文残留" | "口型";
  severity: "严重" | "中等" | "轻微";
  episode: string;
  timecode: string;
};

export const episodes: Episode[] = [
  { id: 1, filename: "E01.mp4", upload: "已上传", analysis: "分析中 45%", duration: "00:12:45", updated: "14:20", progress: 45 },
  { id: 2, filename: "E02.mp4", upload: "已上传", analysis: "分析中 10%", duration: "00:11:30", updated: "13:05", progress: 10 },
  { id: 3, filename: "E03.mp4", upload: "已上传", analysis: "分析完成", duration: "00:13:02", updated: "11:48", progress: 100 },
  { id: 4, filename: "E04.mp4", upload: "已上传", analysis: "排队中", duration: "00:12:18", updated: "11:20" },
  { id: 5, filename: "E05.mp4", upload: "已上传", analysis: "排队中", duration: "00:11:55", updated: "10:58" },
  { id: 6, filename: "E06.mp4", upload: "上传中 60%", analysis: "—", duration: "00:12:30", updated: "—", progress: 60 },
];

export const exceptions: ExceptionItem[] = [
  { id: 1, type: "身份一致性", severity: "严重", episode: "第 01 集", timecode: "00:02:35" },
  { id: 2, type: "中文残留", severity: "中等", episode: "第 01 集", timecode: "00:05:12" },
  { id: 3, type: "口型", severity: "严重", episode: "第 01 集", timecode: "00:07:48" },
  { id: 4, type: "身份一致性", severity: "轻微", episode: "第 02 集", timecode: "00:10:22" },
];
