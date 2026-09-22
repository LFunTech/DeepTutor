"use client";

import {
  type ChangeEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useSearchParams } from "next/navigation";

import { TranscriptTurnContent } from "./TranscriptTurnContent";
import type { ContextPolicy } from "@/contracts/generated/turn-protocol";
import {
  buildAuthRefreshCommand,
  buildDemoWebSocketUrl,
  buildEduPlus2DemoStartUrl,
  buildWebSocketProtocols,
  type DemoResultPayload,
} from "@/lib/eduplus2-fronting-demo";
import {
  buildConversationUploadIntentRequest,
  buildConversationTestStartTurn,
  conversationSendBlockReason,
  conversationSpeechFailureNotice,
  encodeConversationWavFromFloat32,
  formatConversationThinkingForPeople,
  formatConversationProgressForPeople,
  formatCapabilityUsageForPeople,
  getDemoTokenExpiresAt,
  isConversationTerminalWebSocketEvent,
  isSpeechRecognitionAvailable,
  isServerSpeechRecordingAvailable,
  nextConversationAuthRefreshDelayMs,
  shouldShowConversationLoginLanding,
  withConversationSpeechStartTimeout,
  type CapabilityUsageSummary,
  type ConversationThinkingStep,
} from "@/lib/enterprise-conversation-test";
import { stripAudioMimeParameters } from "@/lib/voice-mime";
import { apiFetch, requestJson } from "@/shared/api/client";
import { browserStorage } from "@/shared/storage";

const API_V1_PREFIX = "/api/" + "v1";
const OPTIONS_PATH = `${API_V1_PREFIX}/enterprise/conversation-test/options`;
const UPLOAD_INTENTS_PATH = `${API_V1_PREFIX}/resources/upload-intents`;
const DEMO_RESULT_PATH = `${API_V1_PREFIX}/auth/eduplus2/demo/result`;
const DEMO_REFRESH_PATH = `${API_V1_PREFIX}/auth/eduplus2/demo/refresh`;
const VOICE_STT_PATH = "/api/voice/stt";
const SESSION_STORAGE_KEY = "enterprise.conversation-test.session-id";
const TOKEN_REFRESH_LEEWAY_SECONDS = 45;

type OptionItem = {
  id: string;
  label: string;
  description?: string;
  status?: string;
  disabled?: boolean;
};

type OptionsPayload = {
  knowledge_bases?: OptionItem[];
  skills?: OptionItem[];
  mcp_tools?: OptionItem[];
};

type UploadIntentPayload = {
  resource_id: string;
  upload_url: string;
  headers?: Record<string, string>;
  resource_kind?: string;
};

type CompletedResourcePayload = {
  resource_id: string;
  state?: string;
};

type SpeechInputState = "idle" | "recording" | "transcribing";

type SpeechToTextPayload = {
  text?: string;
};

type UploadedResource = {
  id: string;
  name: string;
  kind: "image" | "audio" | "video" | "file";
  status: "uploading" | "ready" | "failed";
  error?: string;
};

type TranscriptTurn = {
  id: string;
  role: "user" | "assistant";
  content: string;
  status?: "pending" | "done" | "failed";
  statusMessage?: string | undefined;
  thinkingSteps?: ConversationThinkingStep[];
  usage?: CapabilityUsageSummary | null;
  diagnosticCode?: string;
};

type SpeechRecognitionConstructor = new () => {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((event: { results: ArrayLike<{ 0: { transcript: string } }> }) => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

type BrowserAudioContextConstructor = new (options?: AudioContextOptions) => AudioContext;

function authHeaders(token: string): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

function shouldRefreshToken(expiresAt: number | null): boolean {
  return Boolean(expiresAt && nowSeconds() >= expiresAt - TOKEN_REFRESH_LEEWAY_SECONDS);
}

function classifyFile(file: File): UploadedResource["kind"] {
  if (file.type.startsWith("image/")) return "image";
  if (file.type.startsWith("audio/")) return "audio";
  if (file.type.startsWith("video/")) return "video";
  return "file";
}

async function sha256Hex(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return [...new Uint8Array(digest)]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}

function selectedLabels(options: OptionItem[], selected: string[]): string {
  const byId = new Map(options.map((item) => [item.id, item.label]));
  return selected.map((id) => byId.get(id) ?? id).join("、") || "未选择";
}

function appendText(current: string, next: string): string {
  const trimmed = next.trim();
  if (!trimmed) return current;
  return current.trim() ? `${current.trim()} ${trimmed}` : trimmed;
}

function publicErrorMessage(code: string, fallback: string): string {
  if (
    [
      "required_context_unavailable",
      "knowledge_base_unavailable",
      "skill_unavailable",
      "mcp_tool_unavailable",
      "context_authorization_failed",
    ].includes(code)
  ) {
    return `所选知识库、Skills 或外部工具暂时不可用，或当前账号无权使用。`;
  }
  return fallback || "对话没有成功完成，请稍后重试。";
}

function localUsageSummary(input: {
  knowledgeBases: string[];
  skills: string[];
  mcpTools: string[];
  resourceCount: number;
  usedVoice: boolean;
}): CapabilityUsageSummary {
  return {
    items: [
      ...input.knowledgeBases.map((label) => ({
        kind: "knowledge_base",
        label,
        status: "enabled",
        count: 0,
      })),
      ...input.skills.map((label) => ({ kind: "skill", label, status: "enabled", count: 0 })),
      ...input.mcpTools.map((label) => ({
        kind: "mcp_tool",
        label,
        status: "enabled",
        count: 0,
      })),
      ...(input.resourceCount > 0
        ? [
            {
              kind: "resource",
              label: `上传文件 ${input.resourceCount} 个`,
              status: "sent",
              count: input.resourceCount,
            },
          ]
        : []),
      ...(input.usedVoice
        ? [{ kind: "speech", label: "语音输入", status: "used", count: 1 }]
        : []),
      { kind: "chat", label: "连续对话", status: "enabled", count: 0 },
    ],
  };
}

function appendThinkingStep(
  steps: ConversationThinkingStep[] | undefined,
  next: Omit<ConversationThinkingStep, "id"> & { appendToPrevious: boolean },
): ConversationThinkingStep[] {
  const current = steps ?? [];
  const last = current[current.length - 1];
  if (!next.appendToPrevious && last?.kind === next.kind && last.title === next.title && !next.content) {
    return current;
  }
  if (next.appendToPrevious && last?.kind === next.kind) {
    return [
      ...current.slice(0, -1),
      {
        ...last,
        content: `${last.content}${next.content}`,
      },
    ];
  }
  return [
    ...current,
    {
      id: `think-${Date.now()}-${current.length}`,
      kind: next.kind,
      title: next.title,
      content: next.content,
    },
  ];
}

export default function EnterpriseConversationTestPage() {
  const searchParams = useSearchParams();
  const demoSession = searchParams.get("demo_session") ?? "";
  const [dtToken, setDtToken] = useState("");
  const [expiresAt, setExpiresAt] = useState<number | null>(null);
  const [loadingAuth, setLoadingAuth] = useState(false);
  const [authError, setAuthError] = useState("");
  const [options, setOptions] = useState<OptionsPayload>({});
  const [selectedKbs, setSelectedKbs] = useState<string[]>([]);
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);
  const [selectedMcpTools, setSelectedMcpTools] = useState<string[]>([]);
  const [contextPolicy, setContextPolicy] = useState<ContextPolicy>("required");
  const [prompt, setPrompt] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [uploads, setUploads] = useState<UploadedResource[]>([]);
  const [turns, setTurns] = useState<TranscriptTurn[]>([]);
  const [sending, setSending] = useState(false);
  const [pageNotice, setPageNotice] = useState("");
  const [speechNotice, setSpeechNotice] = useState("");
  const [speechState, setSpeechState] = useState<SpeechInputState>("idle");
  const [lastUsedVoice, setLastUsedVoice] = useState(false);
  const recognitionRef = useRef<InstanceType<SpeechRecognitionConstructor> | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const speechChunksRef = useRef<Blob[]>([]);
  const pcmAudioContextRef = useRef<AudioContext | null>(null);
  const pcmAudioSourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const pcmAudioProcessorRef = useRef<ScriptProcessorNode | null>(null);
  const pcmAudioChunksRef = useRef<Float32Array[]>([]);
  const dtTokenRef = useRef("");
  const expiresAtRef = useRef<number | null>(null);

  const readyResources = uploads.filter((item) => item.status === "ready");
  const uploading = uploads.some((item) => item.status === "uploading");
  const failedUploads = uploads.filter((item) => item.status === "failed");
  const isAuthenticated = Boolean(dtToken);

  const loginUrl = useMemo(() => {
    if (typeof window === "undefined") return buildEduPlus2DemoStartUrl("/");
    return buildEduPlus2DemoStartUrl(window.location.href.split("?")[0]);
  }, []);

  const refreshDemoToken = useCallback(async () => {
    if (!demoSession) return { token: "", expiresAt: null as number | null };
    const refreshed = await requestJson<DemoResultPayload>(DEMO_REFRESH_PATH, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ demo_session: demoSession }),
      skipAuthRedirect: true,
      scope: "network",
    });
    const token = refreshed.dt_token ?? "";
    const tokenExpiresAt = getDemoTokenExpiresAt(refreshed);
    setDtToken(token);
    dtTokenRef.current = token;
    setExpiresAt(tokenExpiresAt);
    expiresAtRef.current = tokenExpiresAt;
    return { token, expiresAt: tokenExpiresAt };
  }, [demoSession]);

  useEffect(() => {
    dtTokenRef.current = dtToken;
  }, [dtToken]);

  useEffect(() => {
    expiresAtRef.current = expiresAt;
  }, [expiresAt]);

  const ensureToken = useCallback(async () => {
    if (dtToken && !shouldRefreshToken(expiresAt)) return dtToken;
    const refreshed = await refreshDemoToken();
    return refreshed.token || dtToken;
  }, [dtToken, expiresAt, refreshDemoToken]);

  const loadOptions = useCallback(async (token: string) => {
    const payload = await requestJson<OptionsPayload>(OPTIONS_PATH, {
      headers: authHeaders(token),
      skipAuthRedirect: true,
      scope: "network",
    });
    setOptions(payload);
  }, []);

  useEffect(() => {
    const savedSessionId = browserStorage.readRaw("session", SESSION_STORAGE_KEY) ?? "";
    if (savedSessionId) setSessionId(savedSessionId);
  }, []);

  useEffect(() => {
    if (!sessionId) {
      browserStorage.removeRaw("session", SESSION_STORAGE_KEY);
      return;
    }
    browserStorage.writeRaw("session", SESSION_STORAGE_KEY, sessionId);
  }, [sessionId]);

  useEffect(() => {
    let cancelled = false;
    async function loadAuth() {
      if (!demoSession) return;
      setLoadingAuth(true);
      setAuthError("");
      try {
        const result = await requestJson<DemoResultPayload>(
          `${DEMO_RESULT_PATH}?${new URLSearchParams({ demo_session: demoSession }).toString()}`,
          { skipAuthRedirect: true, scope: "network" },
        );
        if (cancelled) return;
        if (!result.ok || !result.dt_token) {
          setAuthError("登录结果不可用，请重新进入测试。");
          return;
        }
        let token = result.dt_token;
        let tokenExpiresAt = getDemoTokenExpiresAt(result);
        if (shouldRefreshToken(tokenExpiresAt)) {
          const refreshed = await refreshDemoToken();
          token = refreshed.token || token;
          tokenExpiresAt = refreshed.expiresAt ?? tokenExpiresAt;
        }
        setDtToken(token);
        dtTokenRef.current = token;
        setExpiresAt(tokenExpiresAt);
        expiresAtRef.current = tokenExpiresAt;
        await loadOptions(token);
      } catch (error) {
        if (!cancelled) setAuthError(error instanceof Error ? error.message : "登录加载失败");
      } finally {
        if (!cancelled) setLoadingAuth(false);
      }
    }
    void loadAuth();
    return () => {
      cancelled = true;
    };
  }, [demoSession, loadOptions, refreshDemoToken]);

  const toggleSelection = (value: string, selected: string[], setter: (values: string[]) => void) => {
    setter(selected.includes(value) ? selected.filter((item) => item !== value) : [...selected, value]);
  };

  const uploadFile = useCallback(
    async (file: File) => {
      const tempId = `${file.name}-${file.size}-${Date.now()}`;
      setUploads((items) => [
        ...items,
        { id: tempId, name: file.name, kind: classifyFile(file), status: "uploading" },
      ]);
      try {
        const token = await ensureToken();
        if (!token) throw new Error("请先完成登录");
        const digest = await sha256Hex(file);
        const intent = await requestJson<UploadIntentPayload>(UPLOAD_INTENTS_PATH, {
          method: "POST",
          headers: { ...authHeaders(token), "Content-Type": "application/json" },
          body: JSON.stringify(
            buildConversationUploadIntentRequest({
              name: file.name,
              type: file.type,
              size: file.size,
              sha256: digest,
              modality: classifyFile(file),
              sessionId,
            }),
          ),
          skipAuthRedirect: true,
          scope: "network",
        });
        const upload = await apiFetch(intent.upload_url, {
          method: "PUT",
          headers: intent.headers ?? { "content-type": file.type || "application/octet-stream" },
          body: file,
          credentials: "omit",
          skipAuthRedirect: true,
        });
        if (!upload.ok) throw new Error("文件上传失败");
        const completed = await requestJson<CompletedResourcePayload>(
          `${UPLOAD_INTENTS_PATH}/${encodeURIComponent(intent.resource_id)}/complete`,
          {
            method: "POST",
            headers: { ...authHeaders(token), "Content-Type": "application/json" },
            body: JSON.stringify({ resource_kind: intent.resource_kind ?? "turn_input" }),
            skipAuthRedirect: true,
            scope: "network",
          },
        );
        setUploads((items) =>
          items.map((item) =>
            item.id === tempId
              ? { ...item, id: completed.resource_id, status: "ready" as const }
              : item,
          ),
        );
      } catch (error) {
        setUploads((items) =>
          items.map((item) =>
            item.id === tempId
              ? {
                  ...item,
                  status: "failed" as const,
                  error: error instanceof Error ? error.message : "上传失败",
                }
              : item,
          ),
        );
      }
    },
    [ensureToken, sessionId],
  );

  const onFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.currentTarget.value = "";
    for (const file of files) void uploadFile(file);
  };

  const releaseSpeechStream = () => {
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;
  };

  const releasePcmRecorder = () => {
    pcmAudioProcessorRef.current?.disconnect();
    pcmAudioSourceRef.current?.disconnect();
    void pcmAudioContextRef.current?.close();
    pcmAudioProcessorRef.current = null;
    pcmAudioSourceRef.current = null;
    pcmAudioContextRef.current = null;
  };

  const transcribeRecordedSpeech = async (blob: Blob, mimeType: string) => {
    releaseSpeechStream();
    if (!blob.size) {
      setSpeechNotice(conversationSpeechFailureNotice("empty"));
      setSpeechState("idle");
      return;
    }
    setSpeechState("transcribing");
    setSpeechNotice("正在把语音转成文字…");
    try {
      const token = await ensureToken();
      if (!token) throw new Error("请先完成登录");
      const extension = mimeType.includes("wav")
        ? "wav"
        : mimeType.includes("ogg")
          ? "ogg"
          : mimeType.includes("mp4")
            ? "mp4"
            : "webm";
      const form = new FormData();
      form.append("file", blob, `recording.${extension}`);
      form.append("language", "zh-CN");
      const payload = await requestJson<SpeechToTextPayload>(VOICE_STT_PATH, {
        method: "POST",
        headers: authHeaders(token),
        body: form,
        skipAuthRedirect: true,
        scope: "network",
      });
      const transcript = `${payload.text ?? ""}`.trim();
      if (!transcript) {
        setSpeechNotice("没有识别到文字，可以重新录制或继续手动输入。");
        return;
      }
      setPrompt((current) => appendText(current, transcript));
      setLastUsedVoice(true);
      setSpeechNotice("已将语音转成文字，可编辑后发送。");
    } catch (error) {
      setSpeechNotice(conversationSpeechFailureNotice(error));
    } finally {
      mediaRecorderRef.current = null;
      releasePcmRecorder();
      setSpeechState("idle");
    }
  };

  const startPcmSpeechInput = (stream: MediaStream) => {
    const scope = window as unknown as Record<
      string,
      BrowserAudioContextConstructor | undefined
    >;
    const AudioContextCtor = scope.AudioContext ?? scope.webkitAudioContext;
    if (!AudioContextCtor) return false;
    const audioContext = new AudioContextCtor({ sampleRate: 16_000 });
    const source = audioContext.createMediaStreamSource(stream);
    const processor = audioContext.createScriptProcessor(4096, 1, 1);
    pcmAudioChunksRef.current = [];
    processor.onaudioprocess = (event) => {
      const channel = event.inputBuffer.getChannelData(0);
      pcmAudioChunksRef.current.push(new Float32Array(channel));
    };
    source.connect(processor);
    processor.connect(audioContext.destination);
    pcmAudioContextRef.current = audioContext;
    pcmAudioSourceRef.current = source;
    pcmAudioProcessorRef.current = processor;
    return true;
  };

  const stopPcmSpeechInput = () => {
    const audioContext = pcmAudioContextRef.current;
    if (!audioContext) return false;
    const wav = encodeConversationWavFromFloat32(
      pcmAudioChunksRef.current,
      audioContext.sampleRate,
    );
    pcmAudioChunksRef.current = [];
    releasePcmRecorder();
    setSpeechState("transcribing");
    setSpeechNotice("正在把语音转成文字…");
    const wavPart = wav.buffer.slice(wav.byteOffset, wav.byteOffset + wav.byteLength) as ArrayBuffer;
    void transcribeRecordedSpeech(new Blob([wavPart], { type: "audio/wav" }), "audio/wav");
    return true;
  };

  const startRecordedSpeechInput = async () => {
    if (!isServerSpeechRecordingAvailable(window)) return false;
    let stream: MediaStream;
    try {
      stream = await withConversationSpeechStartTimeout(
        navigator.mediaDevices.getUserMedia({ audio: true }),
      );
    } catch (error) {
      setSpeechNotice(conversationSpeechFailureNotice(error));
      return true;
    }
    mediaStreamRef.current = stream;
    try {
      if (startPcmSpeechInput(stream)) {
        setSpeechState("recording");
        setSpeechNotice("正在听，请说完后点击“停止语音”。");
        return true;
      }
      const recorder = new MediaRecorder(stream);
      mediaRecorderRef.current = recorder;
      speechChunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) speechChunksRef.current.push(event.data);
      };
      recorder.onerror = () => {
        setSpeechNotice(conversationSpeechFailureNotice("audio-capture"));
      };
      recorder.onstop = () => {
        const mimeType = stripAudioMimeParameters(recorder.mimeType);
        const blob = new Blob(speechChunksRef.current, { type: mimeType });
        speechChunksRef.current = [];
        void transcribeRecordedSpeech(blob, mimeType);
      };
      recorder.start();
      setSpeechState("recording");
      setSpeechNotice("正在听，请说完后点击“停止语音”。");
      return true;
    } catch (error) {
      releasePcmRecorder();
      releaseSpeechStream();
      mediaRecorderRef.current = null;
      setSpeechNotice(conversationSpeechFailureNotice(error));
      setSpeechState("idle");
      return true;
    }
  };

  const startBrowserSpeechRecognition = () => {
    setSpeechNotice("");
    if (!isSpeechRecognitionAvailable(window)) {
      setSpeechNotice("当前浏览器不支持语音输入，可以继续使用键盘输入或上传音频文件。");
      return;
    }
    const scope = window as unknown as Record<string, SpeechRecognitionConstructor | undefined>;
    const Recognition = scope.SpeechRecognition ?? scope.webkitSpeechRecognition;
    if (!Recognition) return;
    const recognition = new Recognition();
    recognitionRef.current = recognition;
    recognition.lang = "zh-CN";
    recognition.interimResults = false;
    recognition.continuous = false;
    recognition.onresult = (event) => {
      const transcript = event.results[0]?.[0]?.transcript ?? "";
      setPrompt((current) => appendText(current, transcript));
      setLastUsedVoice(true);
    };
    recognition.onerror = (event) => setSpeechNotice(conversationSpeechFailureNotice(event.error));
    recognition.onend = () => setSpeechState("idle");
    setSpeechState("recording");
    try {
      recognition.start();
      setSpeechNotice("正在听，请说完后点击“停止语音”。");
    } catch (error) {
      setSpeechState("idle");
      setSpeechNotice(conversationSpeechFailureNotice(error));
    }
  };

  const startSpeechInput = () => {
    if (speechState !== "idle") return;
    setSpeechNotice("");
    void (async () => {
      const started = await startRecordedSpeechInput();
      if (!started) startBrowserSpeechRecognition();
    })();
  };

  const stopSpeechInput = () => {
    if (stopPcmSpeechInput()) return;
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      setSpeechState("transcribing");
      setSpeechNotice("正在把语音转成文字…");
      mediaRecorderRef.current.stop();
      return;
    }
    recognitionRef.current?.stop();
    setSpeechState("idle");
  };

  useEffect(() => {
    return () => {
      recognitionRef.current?.stop();
      const recorder = mediaRecorderRef.current;
      if (recorder && recorder.state !== "inactive") recorder.stop();
      pcmAudioProcessorRef.current?.disconnect();
      pcmAudioSourceRef.current?.disconnect();
      void pcmAudioContextRef.current?.close();
      mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  const sendMessage = async () => {
    const content = prompt.trim();
    const blockReason = conversationSendBlockReason({
      prompt: content,
      sending,
      uploading,
      failedUploadCount: failedUploads.length,
      isAuthenticated,
    });
    if (!content || sending) return;
    if (blockReason) {
      setPageNotice(blockReason);
      return;
    }
    setPageNotice("");
    setSending(true);
    const userTurnId = `u-${Date.now()}`;
    const assistantTurnId = `a-${Date.now()}`;
    const resourceIds = readyResources.map((item) => item.id);
    const localUsage = localUsageSummary({
      knowledgeBases: selectedKbs,
      skills: selectedSkills,
      mcpTools: selectedMcpTools,
      resourceCount: resourceIds.length,
      usedVoice: lastUsedVoice,
    });
    setTurns((items) => [
      ...items,
      { id: userTurnId, role: "user", content },
      {
        id: assistantTurnId,
        role: "assistant",
        content: "",
        status: "pending",
        statusMessage: "正在连接对话服务…",
        thinkingSteps: [
          {
            id: `${assistantTurnId}-connect`,
            kind: "progress",
            title: "正在连接对话服务",
            content: "",
          },
        ],
        usage: localUsage,
      },
    ]);
    setPrompt("");
    setUploads([]);
    setLastUsedVoice(false);
    try {
      const token = await ensureToken();
      if (!token) throw new Error("请先完成登录");
      const socket = new WebSocket(buildDemoWebSocketUrl(window.location), buildWebSocketProtocols(token));
      let refreshTimer: number | undefined;
      const clearAuthRefreshTimer = () => {
        if (refreshTimer === undefined) return;
        window.clearTimeout(refreshTimer);
        refreshTimer = undefined;
      };
      const sendAuthRefresh = (freshToken: string) => {
        if (freshToken && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify(buildAuthRefreshCommand(freshToken)));
        }
      };
      const scheduleAuthRefresh = (retryDelayMs?: number) => {
        clearAuthRefreshTimer();
        const delayMs =
          retryDelayMs ??
          nextConversationAuthRefreshDelayMs({
            nowSeconds: nowSeconds(),
            expiresAt: expiresAtRef.current,
            leewaySeconds: TOKEN_REFRESH_LEEWAY_SECONDS,
            minDelayMs: 1_000,
          });
        if (delayMs === null) return;
        refreshTimer = window.setTimeout(() => {
          void (async () => {
            try {
              const refreshed = await refreshDemoToken();
              sendAuthRefresh(refreshed.token || dtTokenRef.current);
              scheduleAuthRefresh();
            } catch {
              setPageNotice("登录状态刷新暂时失败，正在重试。");
              scheduleAuthRefresh(5_000);
            }
          })();
        }, delayMs);
      };
      const command = buildConversationTestStartTurn({
        prompt: content,
        sessionId: sessionId || null,
        knowledgeBases: selectedKbs,
        skills: selectedSkills,
        mcpTools: selectedMcpTools,
        resourceIds,
        contextPolicy,
      });
      socket.addEventListener("open", () => {
        if (token && shouldRefreshToken(expiresAtRef.current)) {
          sendAuthRefresh(token);
        }
        scheduleAuthRefresh();
        socket.send(JSON.stringify(command));
      });
      socket.addEventListener("message", (event) => {
        let payload: Record<string, unknown>;
        try {
          payload = JSON.parse(String(event.data)) as Record<string, unknown>;
        } catch {
          return;
        }
        const type = String(payload.type ?? "");
        const eventSessionId = String(payload.session_id ?? "");
        if (eventSessionId) setSessionId(eventSessionId);
        if (isConversationTerminalWebSocketEvent(type)) {
          clearAuthRefreshTimer();
          setSending(false);
        }
        const metadata =
          payload.metadata && typeof payload.metadata === "object"
            ? (payload.metadata as Record<string, unknown>)
            : {};
        const progressText = formatConversationProgressForPeople(type, {
          ...metadata,
          tool_name: payload.tool_name ?? payload.tool ?? metadata.tool_name,
          name: payload.name ?? metadata.name,
        });
        const thinkingDisplay = formatConversationThinkingForPeople(type, {
          ...metadata,
          content: payload.content,
          tool_name: payload.tool_name ?? payload.tool ?? metadata.tool_name,
          name: payload.name ?? metadata.name,
        });
        if (thinkingDisplay) {
          setTurns((items) =>
            items.map((item) =>
              item.id === assistantTurnId
                ? {
                    ...item,
                    thinkingSteps: appendThinkingStep(item.thinkingSteps, thinkingDisplay),
                  }
                : item,
            ),
          );
        }
        if (progressText) {
          setTurns((items) =>
            items.map((item) =>
              item.id === assistantTurnId && !item.content
                ? { ...item, statusMessage: progressText }
                : item,
            ),
          );
        }
        if (type === "content") {
          const chunk = String(payload.content ?? "");
          setTurns((items) =>
            items.map((item) =>
              item.id === assistantTurnId
                ? { ...item, content: item.content + chunk, statusMessage: undefined }
                : item,
            ),
          );
        } else if (type === "error" || type === "protocol_error") {
          const code = String(payload.error_code ?? metadata.error_code ?? "");
          const message = publicErrorMessage(code, String(payload.content ?? payload.message ?? ""));
          setTurns((items) =>
            items.map((item) =>
              item.id === assistantTurnId
                ? {
                    ...item,
                    content: message,
                    status: "failed",
                    statusMessage: undefined,
                    diagnosticCode: code,
                  }
                : item,
            ),
          );
          socket.close();
        } else if (type === "done") {
          const usage =
            metadata.capability_usage && typeof metadata.capability_usage === "object"
              ? (metadata.capability_usage as CapabilityUsageSummary)
              : localUsage;
          const status = String(metadata.status ?? "done") === "failed" ? "failed" : "done";
          const code = String(metadata.error_code ?? "");
          setTurns((items) =>
            items.map((item) =>
              item.id === assistantTurnId
                ? {
                    ...item,
                    status,
                    usage,
                    diagnosticCode: code,
                    statusMessage: undefined,
                    content:
                      item.content ||
                      (status === "failed" ? publicErrorMessage(code, "对话失败") : item.content),
                  }
                : item,
            ),
          );
          socket.close();
        }
      });
      socket.addEventListener("error", () => {
        clearAuthRefreshTimer();
        setTurns((items) =>
          items.map((item) =>
            item.id === assistantTurnId
              ? {
                  ...item,
                  content: "连接对话服务失败，请重新发送。",
                  status: "failed",
                  statusMessage: undefined,
                }
              : item,
          ),
        );
        setSending(false);
      });
      socket.addEventListener("close", () => {
        clearAuthRefreshTimer();
        setSending(false);
      });
    } catch (error) {
      setTurns((items) =>
        items.map((item) =>
          item.id === assistantTurnId
            ? {
                ...item,
                content: error instanceof Error ? error.message : "发送失败",
                status: "failed",
              }
            : item,
        ),
      );
      setSending(false);
    }
  };

  const newConversation = () => {
    setSessionId("");
    setTurns([]);
    setUploads([]);
    setPageNotice("已开始新的对话，本地测试记录已清空。");
  };

  if (
    shouldShowConversationLoginLanding({
      demoSession,
      isAuthenticated,
      loadingAuth,
      authError,
    })
  ) {
    return (
      <main className="min-h-dvh overflow-y-auto bg-[#f3efe3] px-6 py-10 text-[#20251f]">
        <section className="mx-auto flex min-h-[70vh] max-w-5xl flex-col justify-center rounded-[2rem] border border-[#d9cfb9] bg-[#fffaf0] p-8 shadow-[0_30px_90px_rgba(68,54,27,0.16)] md:p-14">
          <p className="mb-4 text-sm font-semibold tracking-[0.3em] text-[#2e7d6d]">EDUPLUS2 CONVERSATION TEST</p>
          <h1 className="max-w-3xl text-4xl font-semibold leading-tight md:text-6xl">
            一个给普通用户使用的完整对话测试台
          </h1>
          <p className="mt-6 max-w-2xl text-lg leading-8 text-[#5c6258]">
            将跳转到 EduPlus2 认证中心。登录后即可进行真实连续对话、上传图片/音频/视频/文档，选择知识库、Skills 指导技能和外部工具，并查看每轮回答实际使用了什么。
          </p>
          {authError ? <p className="mt-4 text-sm font-medium text-[#9f3424]">{authError}</p> : null}
          <a
            className="mt-10 inline-flex w-fit rounded-full bg-[#0d5f53] px-6 py-3 text-base font-semibold text-white shadow-lg shadow-[#0d5f5333] transition hover:bg-[#094a42]"
            href={loginUrl}
          >
            使用 EduPlus2 账号登录
          </a>
        </section>
      </main>
    );
  }

  return (
    <main className="h-dvh overflow-y-auto bg-[#efe9dc] px-4 py-4 text-[#1f251f] md:px-6 md:py-6 lg:overflow-hidden">
      <div className="mx-auto grid min-h-full max-w-7xl gap-5 lg:h-full lg:min-h-0 lg:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="rounded-[1.75rem] border border-[#d8ccb6] bg-[#fffaf0]/90 p-5 shadow-[0_20px_60px_rgba(64,52,28,0.12)] lg:min-h-0 lg:overflow-y-auto">
          <div className="mb-5 rounded-2xl bg-[#133f38] p-4 text-white">
            <p className="text-xs font-semibold tracking-[0.24em] text-[#a6ded2]">普通测试</p>
            <h1 className="mt-2 text-2xl font-semibold">完整对话流程</h1>
            <p className="mt-2 text-sm leading-6 text-[#d7f3eb]">默认强制校验所选能力；切到自动模式时，系统不保证一定调用。</p>
          </div>

          <div className="space-y-4 text-sm">
            <div className="rounded-2xl border border-[#e4dac8] bg-white/70 p-4">
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold">登录状态</span>
                <span className={isAuthenticated ? "text-[#0d7a5d]" : "text-[#9f4d24]"}>
                  {loadingAuth ? "读取中" : isAuthenticated ? "已就绪" : "需要登录"}
                </span>
              </div>
              {authError ? <p className="mt-2 text-[#9f3424]">{authError}</p> : null}
            </div>

            <div className="rounded-2xl border border-[#e4dac8] bg-white/70 p-4">
              <p className="mb-2 font-semibold">上下文策略</p>
              <div className="grid grid-cols-2 gap-2">
                <button
                  className={`rounded-full px-3 py-2 ${contextPolicy === "required" ? "bg-[#0d5f53] text-white" : "bg-[#ece4d5]"}`}
                  type="button"
                  onClick={() => setContextPolicy("required")}
                >
                  强制可用
                </button>
                <button
                  className={`rounded-full px-3 py-2 ${contextPolicy === "auto" ? "bg-[#0d5f53] text-white" : "bg-[#ece4d5]"}`}
                  type="button"
                  onClick={() => setContextPolicy("auto")}
                >
                  自动选择
                </button>
              </div>
            </div>

            <OptionGroup
              title="知识库"
              empty="暂无可选知识库"
              options={options.knowledge_bases ?? []}
              selected={selectedKbs}
              onToggle={(id) => toggleSelection(id, selectedKbs, setSelectedKbs)}
            />
            <OptionGroup
              title="Skills 指导技能"
              empty="暂无可选 Skills"
              options={options.skills ?? []}
              selected={selectedSkills}
              onToggle={(id) => toggleSelection(id, selectedSkills, setSelectedSkills)}
            />
            <OptionGroup
              title="外部工具"
              empty="暂无可选外部工具"
              options={options.mcp_tools ?? []}
              selected={selectedMcpTools}
              onToggle={(id) => toggleSelection(id, selectedMcpTools, setSelectedMcpTools)}
            />
          </div>
        </aside>

        <section className="flex min-h-[calc(100dvh-2rem)] flex-col rounded-[1.75rem] border border-[#d8ccb6] bg-[#fffdf7] shadow-[0_20px_80px_rgba(64,52,28,0.14)] lg:h-full lg:min-h-0">
          <header className="shrink-0 border-b border-[#e6dccb] p-5">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div>
                <p className="text-xs font-semibold tracking-[0.24em] text-[#2e7d6d]">真实服务联调</p>
                <h2 className="mt-1 text-2xl font-semibold">对话测试</h2>
              </div>
              <button
                className="w-fit rounded-full border border-[#b8a98f] px-4 py-2 text-sm font-semibold text-[#4d493f] hover:bg-[#f0eadf]"
                type="button"
                onClick={newConversation}
              >
                新建对话
              </button>
            </div>
            <p className="mt-3 text-sm text-[#67695f]">
              已选：知识库 {selectedLabels(options.knowledge_bases ?? [], selectedKbs)}；Skills {selectedLabels(options.skills ?? [], selectedSkills)}；外部工具 {selectedLabels(options.mcp_tools ?? [], selectedMcpTools)}。
            </p>
          </header>

          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
            {turns.length === 0 ? (
              <div className="rounded-[1.5rem] border border-dashed border-[#cdbf9f] bg-[#f8f1e5] p-8 text-center text-[#62665d]">
                发送第一句话，开始一段可持续的真实对话。
              </div>
            ) : null}
            {turns.map((turn) => (
              <article
                className={`max-w-3xl rounded-[1.5rem] p-4 ${
                  turn.role === "user"
                    ? "ml-auto bg-[#123f38] text-white"
                    : "mr-auto border border-[#e2d5bf] bg-white text-[#252a24]"
                }`}
                key={turn.id}
              >
                <TranscriptTurnContent
                  role={turn.role}
                  content={turn.content}
                  streaming={turn.status === "pending"}
                  statusMessage={turn.statusMessage}
                  thinkingSteps={turn.thinkingSteps}
                />
                {turn.role === "assistant" ? (
                  <CapabilityPanel usage={turn.usage} diagnosticCode={turn.diagnosticCode} />
                ) : null}
              </article>
            ))}
          </div>

          <footer className="shrink-0 border-t border-[#e6dccb] p-5">
            {pageNotice ? <p className="mb-3 rounded-xl bg-[#fff4d6] px-4 py-2 text-sm text-[#7b5c0f]">{pageNotice}</p> : null}
            {speechNotice ? <p className="mb-3 rounded-xl bg-[#f0f6ff] px-4 py-2 text-sm text-[#305478]">{speechNotice}</p> : null}
            {uploads.length > 0 ? (
              <div className="mb-3 flex flex-wrap gap-2">
                {uploads.map((item) => (
                  <span
                    className={`rounded-full px-3 py-1 text-xs font-semibold ${
                      item.status === "ready"
                        ? "bg-[#dff3e8] text-[#0f6a50]"
                        : item.status === "failed"
                          ? "bg-[#ffe4dd] text-[#9b3524]"
                          : "bg-[#f6edce] text-[#7a5c14]"
                    }`}
                    key={`${item.id}-${item.name}`}
                  >
                    {item.name} · {item.status === "ready" ? "已加入" : item.status === "failed" ? "上传失败" : "上传中"}
                  </span>
                ))}
              </div>
            ) : null}
            <div className="rounded-[1.5rem] border border-[#d8ccb6] bg-[#fbf6ed] p-3">
              <textarea
                className="min-h-28 w-full resize-none rounded-2xl border border-transparent bg-white px-4 py-3 outline-none ring-[#0d5f53]/20 focus:border-[#0d5f53] focus:ring-4"
                placeholder="输入问题，也可以先上传文件或使用语音输入…"
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
              />
              <div className="mt-3 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div className="flex flex-wrap gap-2">
                  <label className="cursor-pointer rounded-full border border-[#b8a98f] bg-white px-4 py-2 text-sm font-semibold hover:bg-[#f2ecdf]">
                    选择文件
                    <input className="sr-only" multiple type="file" onChange={onFileChange} />
                  </label>
                  <button
                    className="rounded-full border border-[#b8a98f] bg-white px-4 py-2 text-sm font-semibold hover:bg-[#f2ecdf]"
                    type="button"
                    disabled={speechState === "transcribing"}
                    onClick={speechState === "recording" ? stopSpeechInput : startSpeechInput}
                  >
                    {speechState === "recording"
                      ? "停止语音"
                      : speechState === "transcribing"
                        ? "正在转写…"
                        : "语音输入"}
                  </button>
                </div>
                <button
                  className="rounded-full bg-[#0d5f53] px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-[#0d5f5330] disabled:cursor-not-allowed disabled:bg-[#9aa39b]"
                  disabled={!prompt.trim() || sending || uploading || !isAuthenticated}
                  type="button"
                  onClick={() => void sendMessage()}
                >
                  {sending ? "发送中…" : "发送消息"}
                </button>
              </div>
            </div>
          </footer>
        </section>
      </div>
    </main>
  );
}

function OptionGroup(props: {
  title: string;
  empty: string;
  options: OptionItem[];
  selected: string[];
  onToggle: (id: string) => void;
}) {
  return (
    <div className="rounded-2xl border border-[#e4dac8] bg-white/70 p-4">
      <p className="mb-3 font-semibold">{props.title}</p>
      {props.options.length === 0 ? <p className="text-[#8a8171]">{props.empty}</p> : null}
      <div className="space-y-2">
        {props.options.map((item) => {
          const checked = props.selected.includes(item.id);
          return (
            <button
              className={`w-full rounded-2xl border px-3 py-2 text-left transition ${
                checked
                  ? "border-[#0d5f53] bg-[#e1f3ed]"
                  : "border-[#e2d7c6] bg-[#fffdf8] hover:bg-[#f4edde]"
              } ${item.disabled ? "cursor-not-allowed opacity-50" : ""}`}
              disabled={item.disabled}
              key={item.id}
              type="button"
              onClick={() => props.onToggle(item.id)}
            >
              <span className="block text-sm font-semibold">{item.label}</span>
              {item.description ? <span className="mt-1 block text-xs text-[#777366]">{item.description}</span> : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function CapabilityPanel(props: { usage?: CapabilityUsageSummary | null; diagnosticCode?: string }) {
  const rows = formatCapabilityUsageForPeople(props.usage);
  return (
    <div className="mt-4 rounded-2xl bg-[#f4efe4] p-3 text-sm text-[#464b42]">
      <p className="mb-2 font-semibold">本轮用了什么</p>
      <ul className="space-y-1">
        {rows.map((row, index) => (
          <li key={`${row.kind}-${index}`}>{row.text}</li>
        ))}
      </ul>
      {props.diagnosticCode ? (
        <details className="mt-3 rounded-xl bg-white/70 p-2">
          <summary className="cursor-pointer font-semibold">排查详情</summary>
          <p className="mt-2 text-xs text-[#6e6a60]">错误代码：{props.diagnosticCode}</p>
        </details>
      ) : null}
    </div>
  );
}
