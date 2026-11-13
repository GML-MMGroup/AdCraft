import { useUiLocale } from "../../../i18n/locale.tsx";

const zh: Record<string, string> = {
  "Add project media": "添加项目素材", "Loading media": "正在加载素材",
  "Some source videos are not ready and have not been added to this timeline.": "部分来源视频尚未就绪，未加入当前时间轴。",
  "Uploading video": "正在上传成片",
  "Action needed": "需要处理",
  "Retry upload": "重试上传",
  "Retry loading": "重试加载",
  "Dismiss": "关闭提示",
  "Saved": "已保存", "Loading editor": "正在加载编辑器", "Retry saving": "重试保存", "Close without saving": "放弃未保存修改并关闭", "Download exported video": "下载已导出视频",
  "Background music": "背景音乐", "Disabled": "已停用", "Loading waveform": "波形加载中", "Waveform unavailable": "波形不可用", "Loop": "循环播放", "Trimmed audio": "音频片段",
  "Source range": "源片",
  "Source unavailable": "素材尚不可用", "clips": "个片段", "Preview position": "预览播放位置",
  "Keep the range inside the source and timeline, without overlapping another clip.": "时间范围需在素材和时间轴之内，至少保留 0.5 秒，且不能与其他片段重叠。",
  "Editing studio": "剪辑工作台", "Composition": "成片预览", "Sources": "素材", "Properties": "片段属性", "Output settings": "输出设置",
  "Timeline": "时间轴", "Video Track": "视频轨道", "Audio Track": "音频轨道", "Time": "时间", "Draft preview": "草稿预览", "Exported output": "已导出成片",
  "Export": "导出视频", "Starting": "正在启动", "Cancel": "取消导出", "Download": "下载", "Downloading": "下载中", "Add to Canvas": "添加到画布", "Adding": "添加中",
  "Changes not exported": "有修改待导出", "Saving changes": "正在保存", "Close editor": "关闭剪辑面板", "Close panel": "收起侧栏",
  "Resolution": "分辨率", "Aspect ratio": "画幅比例", "FPS": "帧率", "Source": "跟随素材", "Set the final frame.": "设置成片规格", "Format": "格式", "Video / Audio": "视频 / 音频编码",
  "Selected clip": "当前片段", "Enabled": "启用", "Volume": "音量", "Source audio": "保留原声", "Transition": "转场", "Transition duration": "转场时长", "Fit": "适应", "Fill": "填充", "Cut": "硬切", "Fade": "淡入淡出",
  "Source in": "素材入点", "Source out": "素材出点", "Timeline position": "时间轴位置", "seconds": "秒", "Apply timing": "应用时间调整", "Timing": "时间范围", "Advanced": "高级设置",
  "Undo": "撤销", "Redo": "重做", "Remove clip": "移出时间轴", "Trim start to playhead": "裁掉播放头左侧", "Trim end to playhead": "裁掉播放头右侧", "Close gaps": "闭合空隙",
  "Snapping": "吸附", "Zoom out": "缩小时间轴", "Zoom in": "放大时间轴", "Fit timeline": "适应全部", "Timeline zoom": "时间轴缩放", "Shortcuts": "快捷键",
  "Previous frame": "上一帧", "Next frame": "下一帧", "Jump to start": "跳到开头", "Jump to end": "跳到结尾", "Play preview": "播放预览", "Pause preview": "暂停预览", "Mute preview": "静音预览", "Unmute preview": "取消预览静音",
  "Source clips": "来源素材", "Restore clip": "加入时间轴", "On timeline": "已在时间轴", "Not on timeline": "未在时间轴", "Select a clip to inspect its settings.": "选择时间轴中的片段以编辑属性。",
  "Playback": "播放 / 暂停", "Step one frame": "逐帧定位", "Undo / redo": "撤销 / 重做", "Remove selected clip": "移出选中片段", "Trim to playhead": "裁剪到播放头", "Resize preview and timeline": "调整预览与时间轴高度",
  "Drag clips to move. Drag their edges to trim.": "拖动片段调整位置，拖动边缘裁剪。", "Session history": "本次打开后的编辑历史",
  "Rewind preview": "后退五秒", "Fast forward preview": "前进五秒", "Inactive sources": "未参与合成的素材", "Optional BGM input": "可选的背景音乐",
};
export function useEditingText() {
  const locale = useUiLocale();
  return (message: string) => locale.startsWith("zh") ? zh[message] ?? message : message;
}
