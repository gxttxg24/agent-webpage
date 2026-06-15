import type { Message } from "../types";

export function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  const isBot = message.role === "bot";
  if (message.role === "system") {
    return (
      <div className="self-center rounded-md bg-slate-100 px-3 py-1 text-xs text-slate-500 ring-1 ring-line">
        {message.text}
      </div>
    );
  }
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[82%] whitespace-pre-wrap rounded-md px-3 py-2 text-sm leading-6 shadow-sm ${
          isUser
            ? "bg-sky-100 text-ink"
            : isBot
              ? "bg-indigo-50 text-ink ring-1 ring-indigo-100"
              : "bg-white text-ink ring-1 ring-line"
        }`}
      >
        {isBot && (
          <div className="mb-1 text-xs font-semibold text-indigo-700">
            {message.senderName || "Bot"} <span className="font-normal text-slate-500">{message.username}</span>
          </div>
        )}
        <div>{message.text}</div>
        <div className="mt-1 text-right text-[11px] text-slate-500">
          {message.createdAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
        </div>
      </div>
    </div>
  );
}
