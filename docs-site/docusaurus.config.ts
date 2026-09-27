import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const siteUrl = process.env.DOCS_SITE_URL || 'http://localhost:3000';
const baseUrl = process.env.DOCS_BASE_URL || '/docs/';
const filingNumbers = [process.env.DOCS_ICP_NUMBER, process.env.DOCS_PUBLIC_SECURITY_NUMBER]
  .map((value) => value?.trim())
  .filter((value): value is string => Boolean(value));

const config: Config = {
  title: '智能体基座 Agent 开发者文档',
  tagline: '面向第三方 Agent 的认证、调用链路与接口契约',
  url: siteUrl,
  baseUrl,
  trailingSlash: true,
  onBrokenLinks: 'throw',
  markdown: {
    mermaid: true,
    hooks: {onBrokenMarkdownLinks: 'throw'},
  },
  themes: ['@docusaurus/theme-mermaid'],
  i18n: {
    defaultLocale: 'zh-Hans',
    locales: ['zh-Hans'],
    localeConfigs: {
      'zh-Hans': {label: '简体中文', direction: 'ltr', htmlLang: 'zh-Hans'},
    },
  },
  presets: [
    [
      'classic',
      {
        docs: {
          routeBasePath: '/',
          sidebarPath: './sidebars.ts',
          lastVersion: 'current',
          versions: {current: {label: '当前实现', path: ''}},
        },
        blog: false,
        theme: {customCss: './src/css/custom.css'},
      } satisfies Preset.Options,
    ],
  ],
  themeConfig: {
    colorMode: {defaultMode: 'light', disableSwitch: false, respectPrefersColorScheme: true},
    navbar: {
      title: '智能体基座 · Agent 开发者',
      items: [{type: 'docSidebar', sidebarId: 'agentDeveloperSidebar', position: 'left', label: '接入指南'}],
    },
    footer: {
      style: 'dark',
      copyright: [`Copyright © ${new Date().getFullYear()} 智能体基座`, ...filingNumbers].join(' · '),
    },
    prism: {theme: prismThemes.github, darkTheme: prismThemes.dracula},
  } satisfies Preset.ThemeConfig,
};

export default config;
