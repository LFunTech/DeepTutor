import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

import {
  buildConversationUploadIntentRequest,
  buildConversationTestStartTurn,
  conversationSendBlockReason,
  getDemoTokenExpiresAt,
  nextConversationAuthRefreshDelayMs,
  formatCapabilityUsageForPeople,
  formatConversationThinkingForPeople,
  formatConversationProgressForPeople,
  conversationSpeechFailureNotice,
  encodeConversationWavFromFloat32,
  withConversationSpeechStartTimeout,
  isSpeechRecognitionAvailable,
  isServerSpeechRecordingAvailable,
  isConversationTerminalWebSocketEvent,
  settlePendingConversationTurnAfterSocketClose,
  splitAssistantThinkingFromAnswer,
  shouldShowConversationLoginLanding,
  conversationAuthRefreshFailureState,
  clearConversationAuthRefreshNotice,
  extractConversationAskUserPrompt,
  buildConversationAskUserReply,
  conversationPublicErrorMessage,
} from "../lib/enterprise-conversation-test";

test("ordinary conversation test page sends required context and resource ids over start_turn only", () => {
  const command = buildConversationTestStartTurn({
    prompt: " 请分析这张试卷 ",
    sessionId: "session-1",
    knowledgeBases: ["七年级数学"],
    skills: ["step-by-step"],
    mcpTools: ["lightrag.query"],
    resourceIds: ["res_img_1"],
    contextPolicy: "required",
  });

  assert.equal(command.type, "start_turn");
  assert.equal(command.protocol_version, "2.0");
  assert.equal(command.content, "请分析这张试卷");
  assert.equal(command.session_id, "session-1");
  assert.deepEqual(command.knowledge_bases, ["七年级数学"]);
  assert.deepEqual(command.skills, ["step-by-step"]);
  assert.deepEqual(command.mcp_tools, ["lightrag.query"]);
  assert.equal(command.context_policy, "required");
  assert.deepEqual(command.resource_ids, ["res_img_1"]);
  assert.deepEqual(command.attachments, []);
  assert.doesNotMatch(JSON.stringify(command), /base64|upload_url|object_key|http:\/\/third-party/);
});

test("ordinary conversation upload request only sends file metadata needed for pre-signed upload", () => {
  const body = buildConversationUploadIntentRequest({
    name: "试卷.png",
    type: "image/png",
    size: 1024,
    sha256: "f".repeat(64),
    modality: "image",
    sessionId: "session-1",
  });

  assert.deepEqual(body, {
    modality: "image",
    mime_type: "image/png",
    size_bytes: 1024,
    sha256: "f".repeat(64),
    purpose: "chat_turn",
    session_id: "session-1",
    filename: "试卷.png",
    expires_seconds: 900,
  });
  assert.doesNotMatch(JSON.stringify(body), /base64|upload_url|object_key|data:image/);
});

test("ordinary conversation composer blocks sending while uploads are unsettled", () => {
  assert.equal(
    conversationSendBlockReason({
      prompt: "请讲解附件",
      sending: false,
      uploading: true,
      failedUploadCount: 0,
      isAuthenticated: true,
    }),
    "文件还在上传中，完成后再发送。",
  );
  assert.equal(
    conversationSendBlockReason({
      prompt: "请讲解附件",
      sending: false,
      uploading: false,
      failedUploadCount: 1,
      isAuthenticated: true,
    }),
    "有文件上传失败，请移除失败项或重新选择后再发送。",
  );
  assert.equal(
    conversationSendBlockReason({
      prompt: "请讲解附件",
      sending: false,
      uploading: false,
      failedUploadCount: 0,
      isAuthenticated: true,
    }),
    "",
  );
});

test("ordinary capability usage copy avoids raw protocol labels by default", () => {
  const rows = formatCapabilityUsageForPeople({
    items: [
      { kind: "knowledge_base", label: "七年级数学", status: "used", count: 1 },
      { kind: "skill", label: "分步讲解方法", status: "enabled", count: 0 },
      { kind: "mcp_tool", label: "lightrag.query", status: "enabled", count: 0 },
      { kind: "resource", label: "上传图片 1 张", status: "sent", count: 1 },
    ],
  });

  assert.deepEqual(rows.map((row) => row.text), [
    "七年级数学：已用于回答",
    "分步讲解方法：已启用但本轮未用",
    "外部检索工具：已启用但本轮未用",
    "上传图片 1 张：已发送给模型",
  ]);
  assert.equal(rows.some((row) => row.text.includes("mcp_tool")), false);
  assert.equal(rows.some((row) => row.text.includes("lightrag.query")), false);
});

test("voice input detection degrades safely when Web Speech API is unavailable", () => {
  assert.equal(isSpeechRecognitionAvailable({}), false);
  assert.equal(isSpeechRecognitionAvailable({ webkitSpeechRecognition: function Fake() {} }), true);
  assert.equal(isSpeechRecognitionAvailable({ SpeechRecognition: function Fake() {} }), true);
});

test("ordinary conversation page prefers server speech recording when browser recording is available", () => {
  assert.equal(isServerSpeechRecordingAvailable({}), false);
  assert.equal(
    isServerSpeechRecordingAvailable({
      MediaRecorder: function FakeRecorder() {},
      navigator: { mediaDevices: { getUserMedia: function fakeGetUserMedia() {} } },
    }),
    true,
  );
  assert.equal(
    isServerSpeechRecordingAvailable({
      MediaRecorder: function FakeRecorder() {},
      navigator: { mediaDevices: {} },
    }),
    false,
  );
});

test("ordinary conversation page explains speech input failures without blocking text input", () => {
  assert.equal(
    conversationSpeechFailureNotice("not-allowed"),
    "无法使用麦克风，请在浏览器地址栏允许麦克风权限后重试；也可以继续键盘输入。",
  );
  assert.equal(
    conversationSpeechFailureNotice("no-speech"),
    "没有听到清晰语音，请靠近麦克风后重试；也可以继续键盘输入。",
  );
  assert.equal(
    conversationSpeechFailureNotice("network"),
    "浏览器语音服务暂时不可用，已切换为文字输入；你也可以直接上传音频文件。",
  );
  assert.equal(
    conversationSpeechFailureNotice("timeout"),
    "麦克风没有响应，请检查浏览器权限或设备后重试；也可以继续键盘输入。",
  );
  assert.equal(
    conversationSpeechFailureNotice(new Error("No active STT model is configured.")),
    "当前服务还没有配置语音转写能力，请先使用文字输入或上传音频文件。",
  );
});

test("ordinary conversation page times out hanging microphone permission prompts", async () => {
  await assert.rejects(
    withConversationSpeechStartTimeout(new Promise(() => undefined), 5),
    /timeout/i,
  );

  const stream = await withConversationSpeechStartTimeout(Promise.resolve("stream"), 50);
  assert.equal(stream, "stream");
});

test("assistant answer text separates raw think blocks from visible final answer", () => {
  assert.deepEqual(
    splitAssistantThinkingFromAnswer("<think>先分析题意</think>\n\n最终答案：$y=x^2$。"),
    {
      answer: "\n\n最终答案：$y=x^2$。",
      thinking: "先分析题意",
    },
  );
  assert.deepEqual(splitAssistantThinkingFromAnswer("前言<thinking>隐藏推理</thinking>结论"), {
    answer: "前言结论",
    thinking: "隐藏推理",
  });
  assert.deepEqual(splitAssistantThinkingFromAnswer("<think>仍在思考"), {
    answer: "",
    thinking: "仍在思考",
  });
});

test("ordinary conversation records browser speech as canonical 16 kHz mono PCM WAV", () => {
  const wav = encodeConversationWavFromFloat32([new Float32Array([-2, -0.5, 0, 0.5, 2])], 16_000);
  const header = Buffer.from(wav.slice(0, 44));
  const pcm = new DataView(wav.buffer, wav.byteOffset + 44, wav.byteLength - 44);

  assert.equal(header.subarray(0, 4).toString("ascii"), "RIFF");
  assert.equal(header.subarray(8, 12).toString("ascii"), "WAVE");
  assert.equal(header.readUInt16LE(22), 1);
  assert.equal(header.readUInt32LE(24), 16_000);
  assert.equal(header.readUInt16LE(34), 16);
  assert.equal(pcm.getInt16(0, true), -32768);
  assert.equal(pcm.getInt16(2, true), -16384);
  assert.equal(pcm.getInt16(4, true), 0);
  assert.equal(pcm.getInt16(6, true), 16383);
  assert.equal(pcm.getInt16(8, true), 32767);
});

test("conversation test page uses dt token expiry instead of demo session cache expiry", () => {
  const expiresAt = getDemoTokenExpiresAt({
    ok: true,
    request_id: "demo-1",
    token_type: "Bearer",
    dt_token: "x",
    expires_at: 2000,
    summary: { expires_at: 1060 },
  });

  assert.equal(expiresAt, 1060);
});

test("ordinary conversation page calls DeepTutor skills Skills instead of learning methods", () => {
  const source = readFileSync(
    join(process.cwd(), "app/enterprise/eduplus2/conversation-test/page.tsx"),
    "utf8",
  );

  assert.match(source, /title="Skills/);
  assert.doesNotMatch(source, /学习方法/);
});

test("websocket error events release the ordinary conversation composer", () => {
  assert.equal(isConversationTerminalWebSocketEvent("error"), true);
  assert.equal(isConversationTerminalWebSocketEvent("protocol_error"), true);
  assert.equal(isConversationTerminalWebSocketEvent("done"), true);
  assert.equal(isConversationTerminalWebSocketEvent("content"), false);
  assert.equal(isConversationTerminalWebSocketEvent("progress"), false);
});

test("ordinary conversation page settles pending assistant turn when websocket closes without done", () => {
  const turns = settlePendingConversationTurnAfterSocketClose(
    [
      { id: "u-1", role: "user", content: "讲讲这个题目" },
      {
        id: "a-1",
        role: "assistant",
        content: "",
        status: "pending",
        statusMessage: "正在输出",
      },
    ],
    "a-1",
  );

  assert.deepEqual(turns[1], {
    id: "a-1",
    role: "assistant",
    content: "连接已中断，请重新发送。",
    status: "failed",
    statusMessage: undefined,
  });
});

test("ordinary conversation page extracts ask_user reply cards from safe tool result metadata", () => {
  const prompt = extractConversationAskUserPrompt({
    type: "tool_result",
    metadata: {
      tool_metadata: {
        ask_user: {
          intro: "为了继续讲解，请补充：",
          questions: [
            {
              id: "goal",
              header: "目标",
              prompt: "你希望先解决什么？",
              options: [
                { label: "先讲概念", description: "适合入门" },
                { label: "直接做题" },
              ],
            },
            {
              id: "focus",
              prompt: "还想覆盖哪些？",
              options: [{ label: "公式" }, { label: "例题" }],
              multi_select: true,
            },
          ],
        },
      },
    },
  });

  assert.deepEqual(prompt, {
    intro: "为了继续讲解，请补充：",
    questions: [
      {
        id: "goal",
        header: "目标",
        prompt: "你希望先解决什么？",
        options: [
          { label: "先讲概念", description: "适合入门" },
          { label: "直接做题", description: "" },
        ],
        multiSelect: false,
        allowFreeText: true,
        placeholder: "",
      },
      {
        id: "focus",
        header: "",
        prompt: "还想覆盖哪些？",
        options: [
          { label: "公式", description: "" },
          { label: "例题", description: "" },
        ],
        multiSelect: true,
        allowFreeText: true,
        placeholder: "",
      },
    ],
  });
});

test("ordinary conversation page builds submit_user_reply answers for ask_user turns", () => {
  const reply = buildConversationAskUserReply(
    {
      intro: "请补充",
      questions: [
        {
          id: "goal",
          header: "目标",
          prompt: "你希望先解决什么？",
          options: [],
          multiSelect: false,
          allowFreeText: true,
          placeholder: "",
        },
        {
          id: "focus",
          header: "",
          prompt: "还想覆盖哪些？",
          options: [],
          multiSelect: true,
          allowFreeText: true,
          placeholder: "",
        },
      ],
    },
    { goal: "先讲概念", focus: "公式、例题" },
  );

  assert.deepEqual(reply.answers, [
    { questionId: "goal", text: "先讲概念" },
    { questionId: "focus", text: "公式、例题" },
  ]);
  assert.equal(reply.text, "你希望先解决什么？：先讲概念\n还想覆盖哪些？：公式、例题");
});

test("ordinary conversation page explains active turns instead of showing service unavailable", () => {
  assert.equal(
    conversationPublicErrorMessage("session_active_turn", "Service unavailable"),
    "上一轮还在等待你的补充，请先回答页面里的追问，或点击“新建对话”重新开始。",
  );
  assert.equal(
    conversationPublicErrorMessage("turn_authorization_expired", "Turn authorization is no longer valid"),
    "登录状态已刷新或过期，请重新发送这一轮。",
  );
});

test("stale demo sessions return users to the ordinary login landing", () => {
  assert.equal(
    shouldShowConversationLoginLanding({
      demoSession: null,
      isAuthenticated: false,
      loadingAuth: false,
      authError: "",
    }),
    true,
  );
  assert.equal(
    shouldShowConversationLoginLanding({
      demoSession: "stale-session",
      isAuthenticated: false,
      loadingAuth: false,
      authError: "Demo session not found",
    }),
    true,
  );
  assert.equal(
    shouldShowConversationLoginLanding({
      demoSession: "fresh-session",
      isAuthenticated: true,
      loadingAuth: false,
      authError: "",
    }),
    false,
  );
  assert.equal(
    shouldShowConversationLoginLanding({
      demoSession: "fresh-session",
      isAuthenticated: false,
      loadingAuth: true,
      authError: "",
    }),
    false,
  );
});

test("ordinary conversation websocket refreshes short lived demo tokens during long turns", () => {
  assert.equal(
    nextConversationAuthRefreshDelayMs({
      nowSeconds: 1_000,
      expiresAt: 1_060,
      leewaySeconds: 45,
      minDelayMs: 1_000,
    }),
    15_000,
  );
  assert.equal(
    nextConversationAuthRefreshDelayMs({
      nowSeconds: 1_020,
      expiresAt: 1_060,
      leewaySeconds: 45,
      minDelayMs: 1_000,
    }),
    1_000,
  );
  assert.equal(
    nextConversationAuthRefreshDelayMs({
      nowSeconds: 1_000,
      expiresAt: null,
      leewaySeconds: 45,
    }),
    null,
  );
});

test("ordinary conversation page treats one auth refresh failure as transient", () => {
  const firstFailure = conversationAuthRefreshFailureState({
    consecutiveFailures: 0,
  });

  assert.deepEqual(firstFailure, {
    consecutiveFailures: 1,
    notice: "",
  });

  const secondFailure = conversationAuthRefreshFailureState(firstFailure);
  assert.deepEqual(secondFailure, {
    consecutiveFailures: 2,
    notice: "登录状态刷新暂时失败，正在重试。",
  });

  assert.equal(
    clearConversationAuthRefreshNotice("登录状态刷新暂时失败，正在重试。"),
    "",
  );
  assert.equal(
    clearConversationAuthRefreshNotice("文件还在上传中，完成后再发送。"),
    "文件还在上传中，完成后再发送。",
  );
});

test("ordinary conversation page shows friendly progress before the first answer token", () => {
  assert.equal(
    formatConversationProgressForPeople("tool_call", { tool_name: "rag" }),
    "正在查找知识库内容…",
  );
  assert.equal(formatConversationProgressForPeople("sources", {}), "已找到可参考内容，正在整理回答…");
  assert.equal(formatConversationProgressForPeople("auth_ack", {}), "");
  assert.equal(formatConversationProgressForPeople("content", {}), "");
});

test("ordinary conversation page starts with a non technical waiting message", () => {
  const source = readFileSync(
    join(process.cwd(), "app/enterprise/eduplus2/conversation-test/page.tsx"),
    "utf8",
  );

  assert.match(source, /正在连接对话服务/);
});

test("ordinary conversation page constrains desktop chat panel so the transcript can scroll", () => {
  const source = readFileSync(
    join(process.cwd(), "app/enterprise/eduplus2/conversation-test/page.tsx"),
    "utf8",
  );

  assert.match(source, /lg:h-dvh/);
  assert.match(source, /lg:overflow-hidden/);
  assert.match(source, /lg:h-\[calc\(100dvh-2\.5rem\)\]/);
  assert.match(source, /<section className="[^"]*overflow-hidden[^"]*lg:h-full/);
});

test("ordinary conversation thinking trace uses safe user facing copy", () => {
  assert.deepEqual(formatConversationThinkingForPeople("thinking", { content: "<think>先判断题意</think>" }), {
    kind: "thinking",
    title: "思考中",
    content: "先判断题意",
    appendToPrevious: true,
  });
  assert.deepEqual(
    formatConversationThinkingForPeople("tool_call", {
      tool_name: "rag",
      content: '{"query":"不要把工具参数展示给普通用户"}',
    }),
    {
      kind: "tool_call",
      title: "正在查找知识库内容",
      content: "",
      appendToPrevious: false,
    },
  );
  assert.deepEqual(formatConversationThinkingForPeople("sources", { content: "raw source body" }), {
    kind: "sources",
    title: "已找到可参考内容",
    content: "",
    appendToPrevious: false,
  });
  assert.equal(formatConversationThinkingForPeople("auth_ack", {}), null);
});

test("ordinary conversation thinking progress hides technical retrieval counters", () => {
  assert.deepEqual(formatConversationThinkingForPeople("progress", { content: "Query: 解题" }), {
    kind: "progress",
    title: "正在理解你的问题",
    content: "",
    appendToPrevious: false,
  });
  assert.deepEqual(
    formatConversationThinkingForPeople("progress", {
      content: "Retrieved 6085 characters of grounded context.",
    }),
    {
      kind: "progress",
      title: "已找到可参考内容",
      content: "",
      appendToPrevious: false,
    },
  );
});
