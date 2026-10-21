# 网页字体

由 `scripts/build_webfonts.py` 从原始字体裁剪生成，随前端一起打包（比赛现场离线可用）。
改了界面文案或知识库后重新运行该脚本，再在 `web/` 下 `npm run build`。

| 文件 | 字体 | 用途 | 版本 | 来源 |
| ---- | ---- | ---- | ---- | ---- |
| `sarasa-sc-400.woff2` / `sarasa-sc-700.woff2` | 更纱黑体 Sarasa Gothic SC | 正文 | 0.36.0 | https://github.com/be5invis/Sarasa-Gothic |
| `source-han-serif-700.woff2` | 思源宋体 Source Han Serif CN Bold | 标题、重点 | 2.003 | https://github.com/adobe-fonts/source-han-serif |
| `smiley-sans.woff2` | 得意黑 Smiley Sans Oblique | 数字读数、品牌字等特殊字 | 2.0.1 | https://github.com/atelier-anchor/smiley-sans |

裁剪方式：正文字体保留 GB2312 全部常用汉字 + 常用符号 + 项目里出现过的所有字；
标题与特殊字字体只保留项目源码、知识库、配置里出现过的字。

## 许可证

三套字体均以 **SIL Open Font License 1.1** 发布，全文见同目录 `OFL.txt`。版权声明（取自字体文件本身）：

- 更纱黑体：Copyright (c) 2015-2022, Renzhi Li (aka. Belleve Invis, belleve@typeof.net).
  Portions Copyright (c) 2016-2020 The Inter Project Authors.
  Portions Copyright (c) 2014, 2015 Adobe Systems Incorporated (http://www.adobe.com/).
  Portions Copyright (c) 2012 Google Inc.
- 思源宋体：© 2017-2024 Adobe (http://www.adobe.com/), with Reserved Font Name 'Source'.
- 得意黑：Copyright © 2022–2024 atelierAnchor.

本目录中的文件是上述字体的子集（只删减字符，未改动字形），仅供本项目网页显示使用。
按 OFL 第 3 条，思源宋体子集已把字体内部名称中的保留名 "Source" 改为 "CG Serif"。
