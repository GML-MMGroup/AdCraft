export const localeText = {
  en: {
    home: "Home", projects: "Projects", assets: "Assets", trash: "Trash", tutorial: "Tutorial", language: "中文",
    account: { allProjects: "All Projects", myAssets: "My Assets", apiSpace: "API Space", signOut: "Sign Out", menu: "Account menu" },
    homePage: {
      unmute: "Unmute", mute: "Mute",
      recentProjects: "Recent Projects", discover: "Discover", createProject: "Create Your Project",
      heroDescription: "AdCraft — The first agentic video production platform for marketing and advertising. Infinite canvas · shot-by-shot replication · fully automated, from idea to final cut.",
      previewCase: "Preview Case", close: "Close", newProject: "New Project", continueEditing: "Continue editing the current workflow canvas.",
    },
    projectsPage: {
      title: "All Projects", all: "All", favorites: "Favorites", select: "Select", done: "Done", selectAll: "Select all", selectAllProjects: "Select all projects",
      clearSelection: "Clear selection", selected: "selected", favorite: "Favorite", removeFavorite: "Remove favorite", saving: "Saving…",
      moveToTrash: "Move to trash", moving: "Moving…", search: "Search projects", newProject: "New Project", selectionCleared: "Selection cleared because the project list changed.",
      moveConfirm: "Move {count} {noun} to trash?", moved: "{count} {noun} moved to trash.", moveFailed: "Could not move {name} to trash.",
      updateFailed: "{count} {noun} could not be {action}.", project: "project", projects: "projects", updated: "updated", movedToTrash: "moved to trash",
    },
    trashPage: {
      title: "Trash", projects: "Projects", search: "Search deleted items", select: "Select", done: "Done", selectAll: "Select all", selectAllProjects: "Select all projects", clearSelection: "Clear selection",
      selected: "selected", restore: "Restore", restoreSelected: "Restore selected", restoring: "Restoring…", empty: "Trash is empty", deletedMeta: "Deleted project · {date}", restoredFailed: "{count} {noun} could not be restored.",
    },
    mode: {
      status: "Choose your creation mode", openingPersonal: "Opening personal creation…", openingBrand: "Opening brand professional…", stageLabel: "Choose a creation mode",
      personalEyebrow: "Individual practice", personalTitle: "Personal Creation", personalDescription: "Start with your own point of view and turn a first idea into a moving frame.",
      brandEyebrow: "Brand system", brandTitle: "Brand Professional", brandDescription: "Build inside a living identity with a guided system for every campaign decision.",
      error: "Unable to create your project. Please choose a mode to try again.",
    },
    assetsPage: { title: "Assets", my: "My Assets", recommended: "Recommended Assets", search: "Search assets", scope: "Asset library scope", category: "Asset category", loading: "Loading assets…", empty: "No assets found.", categories: { characters: "Characters", scenes: "Scenes", props: "Props" } },
  },
  zh: {
    home: "主页", projects: "项目", assets: "素材", trash: "回收站", tutorial: "教程", language: "English",
    account: { allProjects: "全部项目", myAssets: "我的素材", apiSpace: "API 空间", signOut: "退出登录", menu: "账户菜单" },
    homePage: {
      unmute: "取消静音", mute: "静音",
      recentProjects: "最近项目", discover: "探索", createProject: "创建项目",
      heroDescription: "AdCraft — 面向营销与广告的智能视频制作平台。从灵感到成片，借助无限画布、逐镜复刻与自动化流程完成创作。",
      previewCase: "预览案例", close: "关闭", newProject: "新项目", continueEditing: "继续编辑当前工作流画布。",
    },
    projectsPage: {
      title: "全部项目", all: "全部", favorites: "收藏", select: "选择", done: "完成", selectAll: "全选", selectAllProjects: "全选项目",
      clearSelection: "清除选择", selected: "已选择", favorite: "收藏", removeFavorite: "取消收藏", saving: "保存中…",
      moveToTrash: "移入回收站", moving: "移动中…", search: "搜索项目", newProject: "新项目", selectionCleared: "项目列表变化，已清除选择。",
      moveConfirm: "将 {count} 个{noun}移入回收站？", moved: "已将 {count} 个{noun}移入回收站。", moveFailed: "无法将{name}移入回收站。",
      updateFailed: "{count} 个{noun}无法{action}。", project: "项目", projects: "项目", updated: "更新", movedToTrash: "移入回收站",
    },
    trashPage: {
      title: "回收站", projects: "项目", search: "搜索已删除项目", select: "选择", done: "完成", selectAll: "全选", selectAllProjects: "全选项目", clearSelection: "清除选择",
      selected: "已选择", restore: "恢复", restoreSelected: "恢复所选", restoring: "恢复中…", empty: "回收站为空", deletedMeta: "已删除项目 · {date}", restoredFailed: "{count} 个{noun}无法恢复。",
    },
    mode: {
      status: "选择创作模式", openingPersonal: "正在打开个人创作…", openingBrand: "正在打开品牌专业…", stageLabel: "选择创作模式",
      personalEyebrow: "个人实践", personalTitle: "个人创作", personalDescription: "从你的视角出发，将最初的想法变成一段动态画面。",
      brandEyebrow: "品牌系统", brandTitle: "品牌专业", brandDescription: "在完整的品牌体系中，为每个广告决策建立清晰的创作路径。",
      error: "项目创建失败，请重新选择创作模式。",
    },
    assetsPage: { title: "素材", my: "我的素材", recommended: "推荐素材", search: "搜索素材", scope: "素材库范围", category: "素材分类", loading: "正在加载素材…", empty: "未找到素材。", categories: { characters: "角色", scenes: "场景", props: "道具" } },
  },
} as const;
