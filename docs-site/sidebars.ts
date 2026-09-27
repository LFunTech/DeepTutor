import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  agentDeveloperSidebar: [
    {type: 'doc', id: 'agent-developer/index', label: '接入概览'},
    {type: 'doc', id: 'agent-developer/quickstart', label: '快速开始'},
    {type: 'doc', id: 'agent-developer/auth-and-security', label: '认证与安全'},
    {type: 'doc', id: 'agent-developer/call-flows', label: '调用链路'},
    {type: 'doc', id: 'agent-developer/capability-selection', label: '对话能力选择'},
    {type: 'doc', id: 'agent-developer/websocket-protocol', label: 'WebSocket 入口与事件'},
    {type: 'doc', id: 'agent-developer/http-api', label: 'HTTP API 目录'},
    {type: 'category', label: '身份交换', items: [
      'agent-developer/api/http/exchange',
    ]},
    {type: 'category', label: '选项与会话', items: [
      'agent-developer/api/http/ui-settings',
      'agent-developer/api/http/list-sessions',
      'agent-developer/api/http/get-session',
      'agent-developer/api/http/rename-session',
      'agent-developer/api/http/delete-session',
      'agent-developer/api/http/message-events',
      'agent-developer/api/http/update-organization',
      'agent-developer/api/http/branch-selection',
      'agent-developer/api/http/delete-message',
    ]},
    {type: 'category', label: '资源与语音', items: [
      'agent-developer/api/http/upload-intent',
      'agent-developer/api/http/complete-upload',
      'agent-developer/api/http/read-resource',
      'agent-developer/api/http/tts',
      'agent-developer/api/http/stt',
    ]},
    {type: 'category', label: 'WebSocket 命令', items: [
      'agent-developer/api/ws/start_turn',
      'agent-developer/api/ws/subscribe_turn',
      'agent-developer/api/ws/subscribe_session',
      'agent-developer/api/ws/resume_from',
      'agent-developer/api/ws/unsubscribe',
      'agent-developer/api/ws/cancel_turn',
      'agent-developer/api/ws/regenerate',
      'agent-developer/api/ws/submit_user_reply',
      'agent-developer/api/ws/check_active_turn',
      'agent-developer/api/ws/auth_refresh',
      'agent-developer/api/ws/ping',
    ]},
    {type: 'doc', id: 'agent-developer/errors', label: '错误与排障'},
    {type: 'doc', id: 'agent-developer/local-differences', label: '环境与契约边界'},
  ],
};

export default sidebars;
