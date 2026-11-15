# 视频指导

先保证精灵轮廓和动作方向，再加入跳跃、冲刺、拾取和反馈。保持像素边缘与网格一致，不要用平滑模糊破坏 sprite readability。图形效果出现后要及时退出，让结果可读。

声音可用按键、碰撞、拾取、短促提示和低层环境节奏，音效应对应动作而非盖住反馈。

## Optional shot phrasing

Use viewport-first wording when scrolling creates ambiguity: "The side-view viewport
scrolls right while the sprite stays near center and runs along the platform." For a
stationary screen, state the sprite's screen-space path instead. Keep pixel alignment,
discrete poses and brief readable feedback. Do not impose lens blur, handheld drift or
smooth photographic interpolation on retro arcade motion.
