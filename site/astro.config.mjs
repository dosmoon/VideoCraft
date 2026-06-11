import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
  site: 'https://dosmoon.com',
  base: '/VideoCraft',
  integrations: [
    starlight({
      title: 'VideoCraft',
      defaultLocale: 'root',
      locales: {
        root: { label: 'English', lang: 'en' },
        'zh-cn': { label: '简体中文', lang: 'zh-CN' },
      },
      favicon: '/favicon.png',
      social: [
        { icon: 'external', label: 'dosmoon.com', href: 'https://dosmoon.com/' },
        { icon: 'github', label: 'GitHub', href: 'https://github.com/dosmoon/VideoCraft' },
      ],
      sidebar: [
        { label: 'VideoCraft', translations: { 'zh-CN': 'VideoCraft' }, link: '/' },
        { label: 'Download & Install', translations: { 'zh-CN': '下载与安装' }, link: '/download/' },
        { label: 'Quick Start', translations: { 'zh-CN': '快速上手' }, link: '/quick-start/' },
        { label: 'dosmoon home', translations: { 'zh-CN': 'dosmoon 主站' }, link: 'https://dosmoon.com/' },
      ],
      editLink: {
        baseUrl: 'https://github.com/dosmoon/VideoCraft/edit/main/docs/public/',
      },
      lastUpdated: true,
    }),
  ],
});
