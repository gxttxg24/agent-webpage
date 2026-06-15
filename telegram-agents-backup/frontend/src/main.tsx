import React, { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Bot, CalendarDays, MessageCircle, RotateCcw, Send, Wifi, WifiOff } from "lucide-react";
import { MessageBubble } from "./components/MessageBubble";
import { ScheduleBoard } from "./components/ScheduleBoard";
import { useChatSocket } from "./hooks/useChatSocket";
import type { ActiveView, BotParticipant, Message, ScheduleDay, ServerEvent } from "./types";
import "./styles.css";

const WS_URL = import.meta.env.VITE_WS_URL || "ws://127.0.0.1:8000/ws/chat";

function App() {
  const sessionId = useMemo(() => getSessionId(), []);
  const messagesRef = useRef<HTMLDivElement | null>(null);
  const [groupMessages, setGroupMessages] = useState<Message[]>([
    {
      id: crypto.randomUUID(),
      role: "system",
      text: "Group chat is ready. Mention configured bots with @username.",
      createdAt: new Date()
    }
  ]);
  const [privateMessages, setPrivateMessages] = useState<Record<string, Message[]>>({});
  const [input, setInput] = useState("");
  const [typing, setTyping] = useState(false);
  const [activeView, setActiveView] = useState<ActiveView>("group");
  const [activeBotProfile, setActiveBotProfile] = useState<string>("");
  const [scheduleDays, setScheduleDays] = useState<ScheduleDay[]>([]);
  const [scheduleLoading, setScheduleLoading] = useState(false);
  const [scheduleOwnerProfile, setScheduleOwnerProfile] = useState("ME");
  const [bots, setBots] = useState<BotParticipant[]>([]);
  const { socketRef, connected, status, setStatus } = useChatSocket(
    WS_URL,
    sessionId,
    handleServerEvent
  );

  useEffect(() => {
    messagesRef.current?.scrollTo({ top: messagesRef.current.scrollHeight, behavior: "smooth" });
  }, [groupMessages, privateMessages, typing, status, activeView, activeBotProfile]);

  useEffect(() => {
    if (!connected) {
      setTyping(false);
    }
  }, [connected]);

  function handleServerEvent(event: ServerEvent) {
    if (event.type === "typing") {
      setTyping(Boolean(event.active));
      return;
    }
    if (event.type === "workflow_status") {
      setStatus(event.label || "Working");
      return;
    }
    if (event.type === "assistant_message") {
      appendGroupMessage("assistant", event.text || "");
      setActiveView("group");
      setStatus("Done");
      return;
    }
    if (event.type === "group_message" && event.message) {
      appendGroupMessage("bot", event.message.text, {
        senderName: event.message.sender_name,
        username: event.message.username
      });
      return;
    }
    if (event.type === "schedule_overview") {
      setScheduleOwnerProfile(event.owner_profile || "ME");
      setScheduleDays(event.days || []);
      setScheduleLoading(false);
      setActiveView("schedule");
      setStatus("Schedule loaded");
      return;
    }
    if (event.type === "bot_roster") {
      setBots(event.bots || []);
      return;
    }
    if (event.type === "bot_invited") {
      if (event.bot) {
        setBots((current) => mergeBot(current, event.bot as BotParticipant));
        appendGroupMessage(
          "system",
          `${event.bot.display_name} ${event.already_invited ? "is already in this chat" : "joined this chat"}`
        );
      }
      return;
    }
    if (event.type === "private_forwarded" && event.bot) {
      appendPrivateMessage(event.bot.profile, "system", `Forwarded to group as ${event.bot.display_name}`);
      return;
    }
    if (event.type === "private_message_failed") {
      appendPrivateMessage(activeBotProfile, "system", "This bot is no longer available");
      return;
    }
    if (event.type === "bot_invite_failed") {
      appendGroupMessage("system", `${event.username || "@bot"} is not a configured bot`);
      return;
    }
    if (event.type === "error") {
      appendGroupMessage("system", event.text || "Backend processing failed");
      setScheduleLoading(false);
      setStatus("Error");
      return;
    }
    if (event.type === "system") {
      setStatus(event.text || "System event");
    }
  }

  function appendGroupMessage(role: Message["role"], text: string, extra: Partial<Message> = {}) {
    setGroupMessages((current) => [
      ...current,
      {
        id: crypto.randomUUID(),
        role,
        text,
        createdAt: new Date(),
        ...extra
      }
    ]);
  }

  function appendPrivateMessage(profile: string, role: Message["role"], text: string, extra: Partial<Message> = {}) {
    if (!profile) {
      return;
    }
    setPrivateMessages((current) => ({
      ...current,
      [profile]: [
        ...(current[profile] || []),
        {
          id: crypto.randomUUID(),
          role,
          text,
          createdAt: new Date(),
          ...extra
        }
      ]
    }));
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const text = input.trim();
    if (!text || !connected || socketRef.current?.readyState !== WebSocket.OPEN) {
      return;
    }
    if (activeView === "private" && activeBotProfile) {
      appendPrivateMessage(activeBotProfile, "user", text);
      socketRef.current.send(
        JSON.stringify({
          type: "user_message",
          conversation: "private",
          target_profile: activeBotProfile,
          text
        })
      );
    } else {
      appendGroupMessage("user", text);
      socketRef.current.send(JSON.stringify({ type: "user_message", conversation: "group", text }));
      setActiveView("group");
    }
    setInput("");
    setStatus("Sent");
  }

  function resetSession() {
    socketRef.current?.send(JSON.stringify({ type: "reset_session" }));
    setGroupMessages([]);
    setPrivateMessages({});
    setScheduleDays([]);
    setActiveView("group");
    setActiveBotProfile("");
    setStatus("Session reset");
  }

  function openSchedule() {
    setActiveView("schedule");
    if (!connected || socketRef.current?.readyState !== WebSocket.OPEN) {
      setStatus("Connect before loading schedule");
      return;
    }
    setScheduleLoading(true);
    setStatus("Loading schedule");
    socketRef.current.send(
      JSON.stringify({
        type: "schedule_overview",
        days: 7,
        owner_profile: scheduleOwnerProfile
      })
    );
  }

  function loadScheduleFor(profile: string) {
    setScheduleOwnerProfile(profile);
    setActiveView("schedule");
    if (!connected || socketRef.current?.readyState !== WebSocket.OPEN) {
      setStatus("Connect before loading schedule");
      return;
    }
    setScheduleLoading(true);
    setStatus("Loading schedule");
    socketRef.current.send(JSON.stringify({ type: "schedule_overview", days: 7, owner_profile: profile }));
  }

  function openPrivateChat(bot: BotParticipant) {
    setActiveBotProfile(bot.profile);
    setActiveView("private");
    setStatus(`Private chat with ${bot.display_name}`);
  }

  const activeBot = bots.find((bot) => bot.profile === activeBotProfile);
  const scheduleParticipants = [
    { profile: "ME", display_name: "Me", username: "", role: "user", invited: true },
    ...bots
  ];
  const visibleMessages =
    activeView === "private" && activeBotProfile
      ? privateMessages[activeBotProfile] || []
      : groupMessages;
  const headerTitle =
    activeView === "private" && activeBot ? activeBot.display_name : "Group Chat";
  const headerSubtitle =
    activeView === "private" && activeBot
      ? `${activeBot.username} forwards your messages into the group`
      : typing
        ? "typing..."
        : status;

  return (
    <main className="min-h-screen bg-slate-200 text-ink">
      <div className="mx-auto flex h-screen max-w-7xl overflow-hidden border-x border-line bg-panel">
        <aside className="hidden w-80 shrink-0 overflow-y-auto border-r border-line bg-slate-50 md:block">
          <div className="border-b border-line px-5 py-4">
            <div className="text-lg font-semibold">Telegram Agents</div>
            <div className="mt-1 text-sm text-slate-500">Web chat bridge</div>
          </div>
          <div className="p-3">
            <button
              type="button"
              onClick={() => setActiveView("group")}
              className={`flex w-full items-center gap-3 rounded-md p-3 text-left shadow-sm ring-1 ring-line ${
                activeView === "group" ? "bg-white" : "bg-slate-50 hover:bg-white"
              }`}
            >
              <span className="flex h-11 w-11 items-center justify-center rounded-full bg-brand text-sm font-semibold text-white">
                G
              </span>
              <span className="min-w-0">
                <span className="block font-medium">Group Chat</span>
                <span className="block truncate text-sm text-slate-500">@ bots and orchestrator here</span>
              </span>
            </button>
            <button
              type="button"
              onClick={openSchedule}
              className={`mt-3 flex w-full items-center gap-3 rounded-md p-3 text-left shadow-sm ring-1 ring-line ${
                activeView === "schedule" ? "bg-white" : "bg-slate-50 hover:bg-white"
              }`}
            >
              <span className="flex h-11 w-11 items-center justify-center rounded-full bg-emerald-500 text-white">
                <CalendarDays size={20} />
              </span>
              <span className="min-w-0">
                <span className="block font-medium">Schedule</span>
                <span className="block truncate text-sm text-slate-500">Open timetable view</span>
              </span>
            </button>
            {bots.length > 0 && (
              <div className="mt-4">
                <div className="flex items-center justify-between px-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <span>Bots</span>
                  <span>{bots.length}</span>
                </div>
                <div className="mt-2 space-y-2">
                  {bots.map((bot) => (
                    <button
                      type="button"
                      key={bot.profile}
                      onClick={() => openPrivateChat(bot)}
                      className={`flex items-center gap-3 rounded-md border border-line p-3 ${
                        activeView === "private" && activeBotProfile === bot.profile
                          ? "bg-white"
                          : bot.invited
                            ? "bg-white hover:bg-slate-50"
                            : "bg-slate-50 hover:bg-white"
                      }`}
                    >
                      <span
                        className={`flex h-9 w-9 items-center justify-center rounded-md ${
                          bot.invited ? "bg-indigo-600 text-white" : "bg-white text-slate-500 ring-1 ring-line"
                        }`}
                      >
                        <Bot size={18} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">{bot.display_name}</span>
                        <span className="block truncate text-xs text-slate-500">{bot.username}</span>
                      </span>
                      <span
                        className={`h-2.5 w-2.5 rounded-full ${
                          bot.invited ? "bg-emerald-500" : "bg-slate-300"
                        }`}
                        title={bot.invited ? "Joined" : "Available"}
                      />
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </aside>

        <section className="flex min-w-0 flex-1 flex-col bg-chat-bg">
          <header className="flex h-16 items-center justify-between border-b border-line bg-white px-4 md:px-6">
            <div className="min-w-0">
              <div className="font-semibold">{headerTitle}</div>
              <div className="truncate text-sm text-slate-500">{headerSubtitle}</div>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setActiveView("group")}
                className={`inline-flex h-9 w-9 items-center justify-center rounded-md border border-line ${
                  activeView === "group" ? "bg-sky-50 text-brand" : "bg-white text-slate-600 hover:bg-slate-50"
                }`}
                title="Group chat"
              >
                <MessageCircle size={18} />
              </button>
              <button
                type="button"
                onClick={openSchedule}
                className={`inline-flex h-9 w-9 items-center justify-center rounded-md border border-line ${
                  activeView === "schedule" ? "bg-emerald-50 text-emerald-700" : "bg-white text-slate-600 hover:bg-slate-50"
                }`}
                title="Schedule"
              >
                <CalendarDays size={18} />
              </button>
              <span className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-line bg-white text-slate-600">
                {connected ? <Wifi size={18} /> : <WifiOff size={18} />}
              </span>
              <button
                type="button"
                onClick={resetSession}
                className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-line bg-white text-slate-600 hover:bg-slate-50"
                title="Reset session"
              >
                <RotateCcw size={18} />
              </button>
            </div>
          </header>

          {activeView === "group" || activeView === "private" ? (
            <div ref={messagesRef} className="flex-1 overflow-y-auto px-3 py-5 md:px-8">
              <div className="mx-auto flex max-w-3xl flex-col gap-3">
                {activeView === "private" && visibleMessages.length === 0 && activeBot && (
                  <div className="self-center rounded-md bg-slate-100 px-3 py-1 text-xs text-slate-500 ring-1 ring-line">
                    Messages here are forwarded to the group as {activeBot.display_name}.
                  </div>
                )}
                {visibleMessages.map((message) => (
                  <MessageBubble key={message.id} message={message} />
                ))}
                {typing && (
                  <div className="w-fit rounded-md bg-white px-4 py-2 text-sm text-slate-500 shadow-sm ring-1 ring-line">
                    ...
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="flex-1 overflow-auto bg-slate-100 px-3 py-4 md:px-6">
              <ScheduleBoard
                days={scheduleDays}
                loading={scheduleLoading}
                ownerProfile={scheduleOwnerProfile}
                participants={scheduleParticipants}
                onOwnerChange={loadScheduleFor}
                onRefresh={openSchedule}
              />
            </div>
          )}

          {activeView === "schedule" && (
            <div className="border-t border-line bg-white px-3 py-2 text-sm text-slate-500 md:px-6">
              <div className="mx-auto flex max-w-5xl items-center justify-between gap-3">
                <span>Schedule is loaded directly from your calendar store.</span>
                <button
                  type="button"
                  onClick={openSchedule}
                  className="rounded-md border border-line px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
                >
                  Refresh
                </button>
              </div>
            </div>
          )}

          <form onSubmit={submit} className="border-t border-line bg-white px-3 py-3 md:px-6">
            <div className="mx-auto flex max-w-3xl items-end gap-2">
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    submit(event);
                  }
                }}
                rows={1}
                className="max-h-36 min-h-11 flex-1 resize-none rounded-md border border-line bg-slate-50 px-3 py-2.5 text-sm outline-none focus:border-brand focus:bg-white"
                placeholder={
                  activeView === "private" && activeBot
                    ? `Message ${activeBot.display_name}`
                    : "Type a group message or @OrchestratorBot request"
                }
              />
              <button
                type="submit"
                disabled={!connected || !input.trim()}
                className="inline-flex h-11 w-11 items-center justify-center rounded-md bg-brand text-white hover:bg-brand-dark disabled:cursor-not-allowed disabled:bg-slate-300"
                title="Send"
              >
                <Send size={19} />
              </button>
            </div>
          </form>
        </section>
      </div>
    </main>
  );
}

function getSessionId() {
  const key = "telegram-agents-web-session";
  const existing = localStorage.getItem(key);
  if (existing) {
    return existing;
  }
  const created = crypto.randomUUID();
  localStorage.setItem(key, created);
  return created;
}

function mergeBot(current: BotParticipant[], bot: BotParticipant) {
  const next = current.some((item) => item.profile === bot.profile)
    ? current.map((item) => (item.profile === bot.profile ? bot : item))
    : [...current, bot];
  return next.sort((left, right) => left.profile.localeCompare(right.profile));
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
