# 音频处理与全局播放器架构设计方案

## 1. 整体架构思路

- **后端编码与元数据提取**：Django (接收上传) + Celery (异步任务) + FFmpeg (音频转码与封面提取)。
- **静态资源分发**：Nginx (利用 `Accept-Ranges: bytes` 承载 HTTP 206 断点续传，完美支持高并发拖拽起播)。
- **前端状态管理**：Pinia Store (`useGlobalAudioStore`) 统一管理播放列表和播放状态。
- **前端播放器核心**：基于 [Plyr](https://plyr.io/) 底层实例接管音频生命周期（只用其 API，不暴露原始 UI）。
- **前端 UI 展现**：集成在系统顶部的 Layout Header 中，提供悬浮、无缝的全局播放体验。

## 2. 后端链路 (Django + Celery + FFmpeg)

### 2.1 任务流程

1. **文件上传入库**：用户上传音频文件（MP3/WAV/FLAC等）以及可选的歌词文件（.lrc）。服务器将原始文件存入磁盘，并在数据库中创建音频记录，状态标记为 `processing`，返回给前端操作入列。
2. **异步转码**：下发 Celery 任务调用 FFmpeg。
   - 提取内置专辑封面（如果存在），保存为独立图片。
   - 统一转码为 `.m4a` (AAC编码)。此格式能保证几乎 100% 的浏览器兼容性，以及更好的流式传输表现。
   - 命令类如：`ffmpeg -i input.mp3 -c:a aac -b:a 192k -vn output.m4a`
3. **处理完成**：更新数据库中的流媒体文件路径（m4a_url）和封面路径（cover_url），状态置为 `ready`。如果是 WebSocket 连接，可以主动推给前端“转码完成”。

※ **注意**：得益于 Nginx 的托管与 Range 支持，后端 Uvicorn 进程不需要参与任何音频字节流的合并或响应，大幅减轻 ASGI 服务器压力。

## 3. 前端界面与交互设计 (Vue 3 + Ant Design Vue)

### 3.1 布局位置

UI 将挂载在全局 `Header` 组件的最左侧。

### 3.2 盒模型结构 (Flexbox Layout)

整个播放器包裹在一个 Flex 容器中，自左向右分为以下几个区域：

- **左侧区（音频头像/Avatar）**：
  - 使用 Ant Design Vue 的 `<a-avatar>` 组件。
  - **展示策略**：如果分离出了封面图片，则显示图片；如果没有封面，则回退显示该音频**标题的第一个字符**。
  - 交互：播放状态下可以赋予一个 css `spin` 转圈动画。

- **中侧区（内容与进度区 - Flex Vertical）**：
  - **上方（单行歌词区）**：
    - 读取当前匹配到的 LRC 歌词。
    - 强制单行显示，超出部分使用省略号或支持缓动画滚动（`text-overflow: ellipsis` 或者 `white-space: nowrap`），确保不破坏 Header 高度。
  - **下方（进度条区）**：
    - 自定义一个纤细的进度条（Slider），双向绑定到 Plyr 实例的进度状态，支持拖拉快进/后退（触发 Plyr 的 `seek`）。

- **右侧区 1（时间信息）**：
  - 格式化展示：`当前时间 / 总时间` (例: `01:23 / 03:45`)。

- **右侧区 2（控制按钮区）**：
  - 提供三个核心操作按钮的图标组件：`[⏮上一曲]`、`[⏯播放/暂停]`、`[⏭下一曲]`。

## 4. 歌词解析与同步 (LRC Parser)

### 4.1 LRC 解码

前端实现一个轻量解析器 `utils/lrcParser.ts`，利用正则表达式 `\[(\d{2}):(\d{2}\.\d{2,3})\](.*)` 处理 `.lrc` 文件。将其反序列化为如下结构：

```typescript
interface LyricLine {
  time: number; // 毫秒或秒级时间戳
  text: string; // 单行歌词文本
}
```

### 4.2 进度同步

- 监听 Plyr 的 `timeupdate` 事件获取高精度的 `currentTime`。
- 在 `LyricLine[]` 数组中查找 `time <= currentTime` 的最后一行，这就是当前应当显示在中侧上方的单行歌词。

## 5. 状态管理 (Pinia)

创建 `useGlobalAudioStore` 来维持以下状态，保障用户跨页面路由跳转时，音频播放不受干扰：

- `playlist: AudioResource[]` (播放列表)
- `currentIndex: number` (当前播放索引)
- `isPlaying: boolean`
- `currentTime: number`
- `duration: number`
- `currentLyric: string`
- `plyrInstance` (可选，或挂载在根组件中)

暴露相应的播放控制 action：`play()`, `pause()`, `next()`, `prev()`, `seek(time)`, `appendTrack(track)`。
