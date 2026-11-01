import { defineConfig } from 'vite';

// 单文件 IIFE 构建：产物拷到 mobile/web/whale/ 后由 WebView 直接加载。
export default defineConfig({
  base: './',
  build: {
    outDir: 'dist-lib',
    emptyOutDir: true,
    target: 'es2020',
    lib: {
      entry: 'src/bundle.ts',
      name: 'WhaleAvatar',
      formats: ['iife'],
      fileName: () => 'whale-avatar.js'
    },
    rollupOptions: {
      output: { inlineDynamicImports: true }
    }
  }
});
