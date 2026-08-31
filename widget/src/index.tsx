import { mountWidget } from "./bootstrap";
import "./styles/widget.css";

// IIFE 入口:currentScript 即本 widget <script> 标签,data-* 为一等配置公民。
// 重复注入由 mountWidget 复用 #ask-ai-widget-root 并跳过已挂载容器来防双浮窗。
mountWidget(document, (document.currentScript as HTMLScriptElement | null) ?? null);
