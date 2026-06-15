import { useEffect, useRef, useState } from "react";
import type { ServerEvent } from "../types";

export function useChatSocket(
  url: string,
  sessionId: string,
  onEvent: (event: ServerEvent) => void
) {
  const socketRef = useRef<WebSocket | null>(null);
  const eventHandlerRef = useRef(onEvent);
  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState("Waiting for connection");

  eventHandlerRef.current = onEvent;

  useEffect(() => {
    const socket = new WebSocket(`${url}?session_id=${encodeURIComponent(sessionId)}`);
    socketRef.current = socket;

    socket.onopen = () => {
      setConnected(true);
      setStatus("Connected");
    };
    socket.onclose = () => {
      setConnected(false);
      setStatus("Disconnected");
    };
    socket.onerror = () => setStatus("Connection error");
    socket.onmessage = (event) => {
      try {
        eventHandlerRef.current(JSON.parse(event.data) as ServerEvent);
      } catch {
        setStatus("Invalid server message");
      }
    };

    return () => socket.close();
  }, [sessionId, url]);

  return { socketRef, connected, status, setStatus };
}
