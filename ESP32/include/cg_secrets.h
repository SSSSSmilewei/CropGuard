#pragma once

// ============================================================
// WiFi 凭据（现场手机热点）
// ------------------------------------------------------------
// ⚠️ 本仓库是公开的，**不要把真实热点名/密码写在这个文件里**。
//    真实凭据请走 B 方案（下面），它已在 ESP32/.gitignore 里忽略。
//
// 两种填法：
//   A) 直接改下面的默认值 —— 只适合临时本地调试，
//      一旦提交就会把热点密码公开（本项目踩过这个坑，别再来一次）
//   B) 复制 cg_secrets.local.h.example 为同目录下的 cg_secrets.local.h
//      并在里面重新定义 WIFI_SSID / WIFI_PASS
//      —— 该文件已被忽略，不会提交到公开仓库（推荐）
//
// 下面的默认值只是占位符，保证"没配本地凭据时也能编译通过"。
// ============================================================

#if defined(__has_include)
#  if __has_include("cg_secrets.local.h")
#    include "cg_secrets.local.h"
#  endif
#endif

#ifndef WIFI_SSID
#  define WIFI_SSID "your-hotspot-ssid"
#endif
#ifndef WIFI_PASS
#  define WIFI_PASS "your-hotspot-password"
#endif
