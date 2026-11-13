import { isChineseLocale } from "../../../i18n/locale.tsx";

// Public catalog copy only; skill identity and execution instructions stay unchanged.
const chineseSkillCopy: Record<string, { title: string; summary: string }> = {
  "new-product-tvc-campaign": {
    "title": "新品视觉广告",
    "summary": "以鲜明的视觉记忆点、精心设计的产品揭示、统一品牌意象与精致材质表现，呈现新品发布的广告质感。"
  },
  "platform-default": {
    "title": "平台默认风格",
    "summary": "采用均衡、清晰的商业影像表达，适配常规广告需求。"
  },
  "industrial-product-commercial": {
    "title": "工业产品功能广告",
    "summary": "以工程形态、材料精度、功能演示和受控光线呈现工业产品的可信价值。"
  },
  "product-promotional-film": {
    "title": "商品卖点宣传片",
    "summary": "以清晰的使用画面、明确的卖点层级和可感知的好处展示产品，最后用简洁干净的商业画面收尾。"
  },
  "brand-manifesto-film": {
    "title": "品牌宣言叙事片",
    "summary": "以信念驱动的叙事、象征性画面、情绪升级和品牌落点构建有依据的品牌表达。"
  },
  "one-take-commercial": {
    "title": "一镜到底空间广告",
    "summary": "以连续空间调度、有动机的转场和揭示时机组织一条可追踪的广告长镜头。"
  },
  "beat-synced-camera-commercial": {
    "title": "高能卡点运镜商业短片",
    "summary": "以节奏重音、动作与剪辑的联动和视觉冲击点组织广告画面的创作方法。"
  },
  "sunlit-pastel-product-fantasy": {
    "title": "日光粉彩产品幻想",
    "summary": "以通透粉彩、细腻材质、明亮日光与流畅空间运动营造轻盈的商业幻想，最后落到精致的产品主视觉。"
  },
  "golden-macro-patisserie": {
    "title": "暖金微距烘焙质感",
    "summary": "用暖琥珀色微距画面、酥脆层次、柔软奶油、深色果实点缀与选择性对焦，呈现高端食品及材质广告中的细腻触感。"
  },
  "fashion-showcase-film": {
    "title": "时装廓形展示片",
    "summary": "以服装廓形、面料运动、编辑式姿态和秀场到生活场景的转换呈现时装价值。"
  },
  "2000s-street-fashion-film": {
    "title": "千禧街头时尚影像",
    "summary": "结合写实街头造型、胶片质感、自然人物动作、材质特写与城市切镜，以快慢交替的剪辑展现千禧年代的品牌态度，节奏可随需求调整。"
  },
  "jewelry-editorial-film": {
    "title": "珠宝微距编辑片",
    "summary": "以微距细节、镜面高光、手势引导展示和亲密编辑节奏突出珠宝的材质与佩戴关系。"
  },
  "luxury-silk-illustration": {
    "title": "流光丝绸插画广告",
    "summary": "以流动装饰线、丝绸材质行为、精炼色场和触觉优雅构建兼具平面秩序与材质感的影像。"
  },
  "art-deco-golden-age-romance": {
    "title": "几何华丽浪漫广告",
    "summary": "以几何秩序、宝石色对比、浪漫丰盛感和舞台化时代氛围构建精致的商业叙事。"
  },
  "theatrical-revue-glamour": {
    "title": "舞台歌舞华彩广告",
    "summary": "以舞台调度、群体几何、聚光魅力和递进式舞台揭示组织具有表演感的商业影像。"
  },
  "symmetrical-storybook-cinema": {
    "title": "对称童话叙事广告",
    "summary": "以轴线构图、精选色盘、章节式调度和精确喜剧节奏组织具有童话秩序的商业影像。"
  },
  "controlled-psychological-thriller": {
    "title": "克制心理悬疑广告",
    "summary": "通过克制表演、合理的暗部光线、精确走位，以及适时出现的画面与声音线索，逐步建立心理紧张感。"
  },
  "suspense-to-sensory-release": {
    "title": "悬疑转感官释放",
    "summary": "以克制悬疑、隐藏声源与冷面表演积累张力，再同步切换到清晰、可感知的产品画面，完成适用于不同品类的幽默揭晓。"
  },
  "clinic-suspense-comedy": {
    "title": "诊室悬疑喜剧",
    "summary": "以封闭诊室构图与问答营造悬疑，可在后段插入功能效果画面再回到喜剧对话，最后将产品与醒目品牌名一起定格在真实使用场景中。"
  },
  "poetic-contemplative-cinema": {
    "title": "诗性沉思影像",
    "summary": "以时间感、材质观察、静默和环境隐喻组织耐心而有情绪依据的商业影像。"
  },
  "monumental-minimalist-science-fiction": {
    "title": "宏大极简科幻影像",
    "summary": "以广阔尺度、稀疏几何、大气深度和人与环境的对照构建克制而有方向的科幻商业画面。"
  },
  "lived-in-epic-cinema": {
    "title": "生活质感史诗影像",
    "summary": "以有磨损的世界、触觉化场景设计、扎实的奇观和层层递进的利害关系构建可信的史诗商业叙事。"
  },
  "geometric-suspense-cinema": {
    "title": "几何悬疑叙事",
    "summary": "借助受控视角、建筑框景、反复出现的几何母题与揭示信息的视点变化，营造空间悬疑。"
  },
  "kinetic-wuxia-fantasy": {
    "title": "流动武侠幻想影像",
    "summary": "以可读的动作地理、衣摆与兵器运动、诗性山水和节奏化交锋组织具有东方幻想气质的商业动作影像。"
  },
  "melodrama-commerce-film": {
    "title": "戏剧冲突带货影像",
    "summary": "以强烈的短剧表演、对峙构图、反应切镜与产品触感特写推动剧情，最后通过直视镜头的明确推介完成销售表达。"
  },
  "costume-comedy-live-action": {
    "title": "古装喜剧实拍",
    "summary": "结合华丽古装场景、夸张人物表情、突然的喜剧反应和清晰的产品演示，以轻松诙谐的实拍方式完成产品推介。"
  },
  "whip-pan-promo-ambush": {
    "title": "甩镜突袭促销",
    "summary": "用有明确动机的成对甩镜、清晰的出入口空间关系和生动反应镜头制造意外，最终稳定呈现推介者与产品，揭晓促销信息。"
  },
  "designer-toy-ip-film": {
    "title": "潮玩角色世界广告",
    "summary": "以鲜明轮廓、标志性配件、可感知的材质和清晰的玩具尺度表演，塑造具有收藏吸引力的角色影像。"
  },
  "soft-3d-comfort-animation": {
    "title": "柔软三维治愈动画",
    "summary": "以圆润比例、触觉化柔软材质、温暖光线和轻柔情绪动作构建安全而有细节的三维动画。"
  },
  "luminous-youth-anime": {
    "title": "青春流光动画",
    "summary": "以发光氛围、天气细节、青春牵挂和天空到城市的转换组织具有成长感的动画叙事。"
  },
  "dream-reality-psychological-anime": {
    "title": "梦境现实心理动画",
    "summary": "以主观转场、身份母题、层叠现实和图形匹配剪辑组织具有心理深度的动画叙事。"
  },
  "kinetic-expressionist-animation": {
    "title": "动势表现主义动画",
    "summary": "以弹性绘制、表现性变形、能量化调度和色彩驱动运动组织具有强烈主观节奏的动画影像。"
  },
  "chinese-traditional-art-animation": {
    "title": "中国传统艺术动画",
    "summary": "以墨色、纸张、剪纸与装饰传统、负空间和诗性运动构建具有东方材料感的动画影像。"
  },
  "retro-pixel-arcade": {
    "title": "复古像素街机动画",
    "summary": "以有限像素色盘、精确精灵可读性、街机式场面调度和节奏化图形效果组织高辨识度的复古动画广告。"
  },
  "retro-magical-girl-animation": {
    "title": "复古魔法少女动画",
    "summary": "以变身语法、象征性道具、粉彩霓虹对比和英雄式揭示组织具有成长与行动感的动画广告。"
  },
  "shadiao-absurd-animation": {
    "title": "沙雕抽象动画",
    "summary": "以平涂色块、易读的弹性变形、突然变化和一本正经的反应制造荒诞喜剧，可配合漫画文字与声音强调节奏。"
  },
  "mixed-media-collage-motion": {
    "title": "混合媒介拼贴动效",
    "summary": "以剪纸层次、无烘焙文字的排版节奏和触觉合成组织具有平面设计秩序的动态广告。"
  },
  "surreal-pop-concept-film": {
    "title": "超现实波普概念影像",
    "summary": "以不可能尺度、波普色彩、视觉隐喻和大胆物体变形组织具有记忆点的概念广告。"
  },
  "surreal-cinematic-product-worlds": {
    "title": "超现实电影感产品世界",
    "summary": "从真实日常场景进入拓展空间、尺度变化或自洽的幻想世界，持续保留产品辨识度、真实使用与触感细节，最后稳定落到产品主视觉。"
  },
  "brand-mark-in-context": {
    "title": "品牌标志场景化广告",
    "summary": "以品牌形状回响、环境融入和揭示与识别层级组织不依赖硬贴标志的品牌影像。"
  },
  "chinese-millennium-dreamcore": {
    "title": "千禧中式梦核影像",
    "summary": "以怀旧数字质感、似曾相识的临界空间、记忆碎片和饱和夜色组织具有地方感的梦境广告。"
  },
  "miniature-world-cinema": {
    "title": "微缩世界电影广告",
    "summary": "以尺度对照、微距光学、手工细节和微型世界动作可读性组织具有玩具般真实感的商业影像。"
  },
  "deadpan-absurd-live-comedy": {
    "title": "一本正经整活实拍",
    "summary": "以写实摄影、认真表演与反应反差呈现冷面喜剧，通过少量突发强调、可选字幕和音效强化笑点。"
  },
  "hand-drawn-travel-journal": {
    "title": "手绘旅行日志影像",
    "summary": "以手绘叠加、旅行观察、地点节奏和剪贴簿连续性组织具有个人记录感的生活方式影像。"
  },
  "gentle-everyday-vlog": {
    "title": "温柔日常Vlog影像",
    "summary": "以亲密手持观察、柔和日常、自然手势和温暖环境细节组织可信而不做作的生活方式内容。"
  },
  "japanese-summer-sensory-film": {
    "title": "日系夏日感官影像",
    "summary": "以风、明亮日光、水、轻快运动或安静日常构建日系夏日氛围，通过自然的产品使用与细腻触感，收束到清晰的产品主视觉。"
  },
  "cinematic-food-story": {
    "title": "电影感美食叙事广告",
    "summary": "以食材质地、制作过程、蒸汽与声音细节和食欲揭示组织广告叙事的美食影像创作方法。"
  },
  "observational-human-documentary": {
    "title": "人文观察纪录影像",
    "summary": "以尊重式观察、环境语境、真实行动和克制旁白组织不替人物发言的纪录式商业影像。"
  },
  "craft-process-film": {
    "title": "匠人工艺过程片",
    "summary": "以材料变形、手部细节、过程因果和以制作者为中心的节奏呈现可信的制作故事。"
  },
  "absence-reveal": {
    "title": "缺席揭示",
    "summary": "先展示产品缺席时的生活、流程或场景，让观众感受到缺口，再用产品的出现证明它的价值。"
  },
  "abstract-form-language": {
    "title": "抽象形态表达",
    "summary": "用形状、运动、节奏、色彩与材质传递品牌感受，无需人物或故事，最后让抽象表达汇聚为产品。"
  },
  "absurd-meme-comedy": {
    "title": "荒诞反差喜剧",
    "summary": "把与产品有关的荒诞事件当作日常来演，用不可能的处境与认真自然的反应制造反差，再以递进、重复或反转强化记忆点。"
  },
  "attribute-backfire": {
    "title": "卖点过强反转",
    "summary": "认真铺陈求生、救援或爱情等高张力情境，在关键时刻让产品某项优势强到超乎常理，意外打乱局面，用夸张的反效果突出卖点。"
  },
  "authority-to-advocate": {
    "title": "从训斥到拥护",
    "summary": "严厉的权威人物撞见不合时宜的产品使用，亲身体验真实好处后，从训斥转为喜爱与主动索求，最终自然引出产品推荐。"
  },
  "brand-pareidolia": {
    "title": "万物皆有品牌影",
    "summary": "让对产品的强烈渴望改变人物的视线：日常物件不断显现品牌的标志性形状，直到结尾才揭示品牌，让观众读懂前面的视觉线索。"
  },
  "collectible-toy-world": {
    "title": "收藏玩具世界构建",
    "summary": "围绕品牌主体建立可收藏的角色身份、世界关系与专属仪式，让观众想加入、集齐、照料或展示这个世界。"
  },
  "collision-montage": {
    "title": "碰撞蒙太奇",
    "summary": "将两组看似无关的画面并置，通过剪辑碰撞产生单个镜头无法表达的新含义，让产品价值在联想中浮现。"
  },
  "consequence-chain": {
    "title": "连锁效应",
    "summary": "从一次微小的产品使用出发，逐层展现它带来的后续影响，用不断延伸的因果链放大产品价值。"
  },
  "counter-intuitive-correction": {
    "title": "反常识纠偏",
    "summary": "开场挑战观众习以为常的判断，制造认知缺口，再以产品及其真实特性给出新的解释。"
  },
  "doctor-patient-reversal": {
    "title": "医患问答悬疑反转",
    "summary": "以诊室中的医患追问推进悬疑，围绕产品的真实功能、使用感受或解决的问题埋设线索。可在后段插入不露产品的效果画面，再回到诊室完成喜剧反转；最终在真实使用场景中定格产品与品牌，解释此前的所有线索。"
  },
  "emotional-micro-moment": {
    "title": "微小情绪放大",
    "summary": "捕捉日常中真实却容易被忽略的动作、声音或表情，放大其中的情绪，让产品成为这一刻自然的陪伴。"
  },
  "extreme-hyperbole": {
    "title": "极致夸张",
    "summary": "把产品的某项特性推到明显不可能的程度，让卖点一眼可懂。用虚构的喜剧或奇观表达，不将夸张当成未经证实的性能承诺。"
  },
  "genre-hijack": {
    "title": "类型片借用",
    "summary": "借用自然纪录片、新闻播报、劫案预告或烹饪节目等熟悉的表达方式，严肃认真地呈现一次普通的产品使用。"
  },
  "identity-transformation": {
    "title": "身份蜕变",
    "summary": "用明确的触发动作展现人物从一种状态转向另一种状态，让产品成为身份与自我表达发生变化的开关。"
  },
  "interface-bleed": {
    "title": "数字故障侵入现实",
    "summary": "把卡顿、冻结、像素化或缓冲等数字体验带入现实，让人物真的像故障界面一样行动，再由产品帮助生活恢复流畅。"
  },
  "interruption-to-offer-reversal": {
    "title": "意外打断促销反转",
    "summary": "先制造清晰的异常或困境，借旁观者的反应建立预期，再让意外登场的推介者揭晓真实促销，衔接可信卖点、准确优惠与购买行动。"
  },
  "literalized-idiom": {
    "title": "比喻成真",
    "summary": "挑选能表达产品好处的俗语、俚语或比喻，把它按字面意思拍成真实发生的画面，让观众在会意中记住产品。"
  },
  "melodrama-commerce-reversal": {
    "title": "短剧冲突带货反转",
    "summary": "通过人物对话推动强烈的短剧冲突，再让产品带来局面反转，由获得主动权的主角介绍产品、说明真实优势并引导购买。"
  },
  "miniature-artisan-ritual": {
    "title": "微缩匠人仪式",
    "summary": "把熟悉的产品表面变成巨大的工坊，让微型匠人完成几项清晰可见的精修工作；最后拉远镜头，揭示完整产品与细节累积的成果。"
  },
  "misdirection-reversal": {
    "title": "误导与反转",
    "summary": "先建立并强化一个清晰预期，再用后段出现的细节重新解释整个故事，让反转帮助观众更准确地理解产品价值。"
  },
  "object-point-of-view": {
    "title": "物件视角叙事",
    "summary": "从产品、它保护的物件或它替代的事物出发讲故事，用物件有限、忠诚或长久的视角揭示人们忽略的价值。"
  },
  "parallel-lives": {
    "title": "平行对照",
    "summary": "并列呈现同一时刻的两种版本：使用与未使用产品、两种选择、两个人物或两个时代，让差异自然说明产品价值。"
  },
  "private-ritual": {
    "title": "私人仪式感",
    "summary": "把普通的产品使用重新组织成有意为之的私人仪式，强调这一刻属于使用者，以及产品带来的专属感受。"
  },
  "product-playground-odyssey": {
    "title": "产品乐园奇遇",
    "summary": "让可辨识的产品成为品牌主题乐园中的奖品与主角，通过可见机关启动一段连续空间冒险，最后稳稳落位，形成醒目的品牌主视觉。"
  },
  "product-triggered-world-expansion": {
    "title": "产品触发世界拓展",
    "summary": "从日常情境出发，让一个有意义的产品动作打开夸张空间或改变世界规则；始终保留产品辨识度，再把奇观带回真实使用，清晰收尾。"
  },
  "scale-shift": {
    "title": "尺度转换",
    "summary": "通过微观与宏观尺度的跳转，展示平时看不见或因过于庞大而被忽略的产品特性，让尺度变化本身成为洞察。"
  },
  "self-aware-ad": {
    "title": "广告自我解构",
    "summary": "让广告坦诚地意识到自己是一则广告，通过打破第四面墙、拆解广告套路或与观众对话，建立更可信的产品表达。"
  },
  "single-constraint-film": {
    "title": "单一规则创作",
    "summary": "为全片设定一条严格的形式规则，如只拍手部、只用一种颜色、一个长镜头或一种声音，让规则本身表达产品特性。"
  },
  "streetwear-identity-journey": {
    "title": "街头风格身份之旅",
    "summary": "以模特照片、品牌名称或已确认的参考素材展开一段城市漫游，通过穿着、携带、行动与观察展现品牌态度，串联造型、材质与街头生活。"
  },
  "summer-sensory-use-moment": {
    "title": "夏日感官使用时刻",
    "summary": "用风、光、水、运动或安静日常唤起季节感，让产品参与自然的使用动作，连接可感知的体验与细微回应，最终清晰呈现产品和品牌。"
  },
  "surreal-displacement": {
    "title": "超现实错置",
    "summary": "把熟悉的物件放到出乎意料的位置，改变它的尺度或材质，并以平静自然的方式呈现，用不可能的组合传递产品特质。"
  },
  "synesthetic-translation": {
    "title": "通感转译",
    "summary": "将味道、声音、气味或触感转化为可见的色彩、光线与物质，让观众通过画面感受到产品体验。"
  },
  "time-loop": {
    "title": "时间循环",
    "summary": "反复呈现同一时刻，每次只改变一个要素，让观众逐渐发现规律，并让产品成为打破或完善循环的关键。"
  },
  "uncanny-testimony-reveal": {
    "title": "诡异证词悬疑揭晓",
    "summary": "不点明产品身份，将真实产品表现描述成令人不安的证词，通过层层追问引导悬疑联想，再用普通的使用场景解释线索，把紧张转为向往。"
  },
  "visual-metaphor": {
    "title": "视觉隐喻",
    "summary": "把压力、轻盈、清新或记忆等抽象价值转化为画面中可见、可运行的物理规则，让观众直观理解产品。"
  },
  "world-hopping-relay": {
    "title": "跨世界接力",
    "summary": "让产品像接力棒一样在人与人之间传递，穿越不同风格、时代或媒介的世界，最终送到需要它的人手中，以旅程表现它值得被送达的价值。"
  }
};

// English counterparts for catalog entries authored with Chinese titles.
const englishSkillTitles: Readonly<Record<string, string>> = {
  "new-product-tvc-campaign": "New Product TVC Campaign",
  "industrial-product-commercial": "Industrial Product Commercial",
  "product-promotional-film": "Product Promotional Film",
  "brand-manifesto-film": "Brand Manifesto Film",
  "one-take-commercial": "One-Take Commercial",
  "beat-synced-camera-commercial": "Beat-Synced Camera Commercial",
  "fashion-showcase-film": "Fashion Showcase Film",
  "jewelry-editorial-film": "Jewelry Editorial Film",
  "luxury-silk-illustration": "Luxury Silk Illustration",
  "art-deco-golden-age-romance": "Art Deco Golden Age Romance",
  "theatrical-revue-glamour": "Theatrical Revue Glamour",
  "symmetrical-storybook-cinema": "Symmetrical Storybook Cinema",
  "controlled-psychological-thriller": "Controlled Psychological Thriller",
  "poetic-contemplative-cinema": "Poetic Contemplative Cinema",
  "monumental-minimalist-science-fiction": "Monumental Minimalist Science Fiction",
  "lived-in-epic-cinema": "Lived-In Epic Cinema",
  "geometric-suspense-cinema": "Geometric Suspense Cinema",
  "kinetic-wuxia-fantasy": "Kinetic Wuxia Fantasy",
  "designer-toy-ip-film": "Designer Toy IP Film",
  "soft-3d-comfort-animation": "Soft 3D Comfort Animation",
  "luminous-youth-anime": "Luminous Youth Anime",
  "dream-reality-psychological-anime": "Dream-Reality Psychological Anime",
  "kinetic-expressionist-animation": "Kinetic Expressionist Animation",
  "chinese-traditional-art-animation": "Chinese Traditional Art Animation",
  "retro-pixel-arcade": "Retro Pixel Arcade",
  "retro-magical-girl-animation": "Retro Magical Girl Animation",
  "shadiao-absurd-animation": "Shadiao Absurd Animation",
  "mixed-media-collage-motion": "Mixed-Media Collage Motion",
  "surreal-pop-concept-film": "Surreal Pop Concept Film",
  "brand-mark-in-context": "Brand Mark in Context",
  "chinese-millennium-dreamcore": "Chinese Millennium Dreamcore",
  "miniature-world-cinema": "Miniature World Cinema",
  "deadpan-absurd-live-comedy": "Deadpan Absurd Live Comedy",
  "hand-drawn-travel-journal": "Hand-Drawn Travel Journal",
  "gentle-everyday-vlog": "Gentle Everyday Vlog",
  "cinematic-food-story": "Cinematic Food Story",
  "observational-human-documentary": "Observational Human Documentary",
  "craft-process-film": "Craft Process Film",
};

export function skillBilingualTitles(skill: { skill_id: string; title: string }): { chinese: string; english: string } {
  const original = skill.title.trim() || skill.skill_id;
  const originallyChinese = /\p{Script=Han}/u.test(original);
  return {
    chinese: originallyChinese ? original : chineseSkillCopy[skill.skill_id]?.title ?? original,
    english: originallyChinese ? englishSkillTitles[skill.skill_id] ?? original : original,
  };
}

const chineseCategoryTitles: Record<string, string> = {
  "commercial-craft": "商业广告",
  "luxury-fashion": "奢华与时尚",
  "cinematic-narrative": "电影叙事",
  "animation-illustration": "动画与插画",
  "experimental-graphic": "实验与图形",
  "lifestyle-documentary": "生活与纪录"
};

export function skillDisplayTitle(skill: { skill_id: string; title: string }, locale: string): string {
  return isChineseLocale(locale) ? chineseSkillCopy[skill.skill_id]?.title ?? skill.title : skill.title;
}

export function skillDisplaySummary(skill: { skill_id: string; summary: string }, locale: string): string {
  return isChineseLocale(locale) ? chineseSkillCopy[skill.skill_id]?.summary ?? skill.summary : skill.summary;
}

export function skillCategoryTitle(category: { category_id: string; title: string }, locale: string): string {
  return isChineseLocale(locale) ? chineseCategoryTitles[category.category_id] ?? category.title : category.title;
}
